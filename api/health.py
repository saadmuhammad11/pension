"""What ``/api/health`` answers: the database, the disk, the model servers and GP Fund.

The route used to report the run count and nothing else, so monitoring showed green through a
real outage (audit 6 Oct 2026, later report item 11). Now:

* ``ok`` is false, and the answer 503, only when the database cannot be read: without it the API
  cannot do its job at all.
* a short artefact disk, a model server that does not answer and a GP Fund module that is down
  are reported in ``degraded`` with the answer still 200: the API still serves the register and
  the cases, uploads are refused on their own with the reason (R8), and a verification says what
  is down. A 503 for a low disk showed every user the portal's outage screen (review C3, 9 Oct 2026).
* the model servers and GP Fund are probed in the background -- one probe per target at a time,
  in parallel, at most every 30 seconds with a 2-second timeout -- and the route answers from the
  last result at once, so a poller never waits on nine seconds of timeouts.
* in production the database error's text stays in the log; the answer says only that the
  database is unavailable.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

PROBE_TIMEOUT_S = 2.0
PROBE_TTL_S = 30.0
_cache: dict[str, tuple[float, bool]] = {}
_cache_lock = threading.Lock()

#: The model endpoints the pipeline calls (api/settings F4; defaults as in extraction and rag).
MODEL_ENDPOINTS = {
    "vision": ("PENSION_VISION_URL", "http://127.0.0.1:8011/v1/chat/completions"),
    "ocr": ("PENSION_OCR_URL", "http://127.0.0.1:8012/v1/chat/completions"),
    "embedding": ("PENSION_EMBED_URL", "http://127.0.0.1:8093/v1/embeddings"),
}


def health_url(endpoint: str) -> str:
    """The server's /health beside whatever path the pipeline calls."""
    parts = urlsplit(endpoint)
    return urlunsplit((parts.scheme, parts.netloc, "/health", "", ""))


def probe(url: str, timeout: float = PROBE_TIMEOUT_S) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310 -- our own servers
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


_inflight: set[str] = set()


def _refresh(name: str, fetch) -> None:
    try:
        value = bool(fetch())
    except Exception:                                 # noqa: BLE001 -- a probe that raises is a probe that failed
        value = False
    with _cache_lock:
        _cache[name] = (time.monotonic() + PROBE_TTL_S, value)
        _inflight.discard(name)


def _cached(name: str, fetch) -> bool:
    """The last known answer for ``name``; a stale or missing one is refreshed in the background
    (single-flight per target). The very first question about a target is answered by probing it
    once, synchronously, so a fresh process does not report everything down for 30 seconds."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(name)
        if hit and hit[0] > now:
            return hit[1]
        if hit is None:
            start_sync = name not in _inflight
            _inflight.add(name)
        else:
            start_sync = False
            if name in _inflight:
                return hit[1]
            _inflight.add(name)
    if start_sync:
        _refresh(name, fetch)
        with _cache_lock:
            return _cache[name][1]
    threading.Thread(target=_refresh, args=(name, fetch), name=f"health-{name}", daemon=True).start()
    return hit[1]


def forget() -> None:
    """Drop the probe memory (tests)."""
    with _cache_lock:
        _cache.clear()
        _inflight.clear()


def _engine() -> str:
    from api import db
    return db.backend()


def _database() -> tuple[bool, str | None]:
    from api import db
    try:
        conn = db.connect()
        try:
            n = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:                                     # noqa: BLE001 -- any failure is the finding
        from api import settings
        import logging
        logging.getLogger(__name__).error("health: the database cannot be read: %s: %s", type(exc).__name__, exc)
        if settings.production():
            return False, "the database is unavailable"            # the detail is in the log, not for the network
        return False, f"{type(exc).__name__}: {exc}"
    return (n > 0), (None if n > 0 else "no migration applied")


def _disk() -> tuple[bool, dict]:
    from api.runs import ARTIFACTS, disk_shortfall
    probe_path = ARTIFACTS
    while not probe_path.exists() and probe_path != probe_path.parent:
        probe_path = probe_path.parent
    try:
        free_gb = round(shutil.disk_usage(probe_path).free / 1024 ** 3, 1)
    except OSError:
        free_gb = None
    short = disk_shortfall()
    return short is None, {"free_gb": free_gb, "problem": short}


def report() -> tuple[dict, int]:
    """The health body and the status code to send it with."""
    from api import gpf_bridge
    from api.runs import RUNS
    db_ok, db_problem = _database()
    disk_ok, disk = _disk()
    models = {}
    for name, (var, default) in MODEL_ENDPOINTS.items():
        url = health_url(os.environ.get(var) or default)
        models[name] = _cached(f"model:{name}", lambda u=url: probe(u))
    gpf_ok = _cached("gpf", lambda: gpf_bridge.health() is not None)
    active = sum(1 for r in RUNS.values() if r.state in ("queued", "running"))
    # The disk, the models and GP Fund degrade the service; only the database fails it (review C3).
    degraded = ([] if disk_ok else ["disk"]) + [n for n, ok in models.items() if not ok] + ([] if gpf_ok else ["gpf"])
    ok = db_ok
    body = {
        "ok": ok,
        "runs": active,
        "database": {"ok": db_ok, "engine": _engine(), **({"problem": db_problem} if db_problem else {})},
        "disk": {"ok": disk_ok, **disk},
        "models": models,
        "gpf": {"ok": gpf_ok},
        "degraded": degraded,
    }
    return body, (200 if ok else 503)
