"""What ``/api/health`` answers: the database, the disk, the model servers and GP Fund.

The route used to report the run count and nothing else, so monitoring showed green through a
real outage (audit 6 Oct 2026, later report item 11). Now:

* ``ok`` is false, and the answer 503, when the database cannot be read or the artefact disk is
  below its reserve: the API cannot do its job.
* the model servers and the GP Fund module are reported but do not fail the check: the API still
  serves cases and the register without them, and a case verification says what is down. They
  are probed at most every 30 seconds, with a 2-second timeout, so the route stays cheap for a
  poller.
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


def _cached(name: str, fetch) -> bool:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(name)
        if hit and hit[0] > now:
            return hit[1]
    value = bool(fetch())
    with _cache_lock:
        _cache[name] = (now + PROBE_TTL_S, value)
    return value


def forget() -> None:
    """Drop the probe memory (tests)."""
    with _cache_lock:
        _cache.clear()


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
    degraded = [n for n, ok in models.items() if not ok] + ([] if gpf_ok else ["gpf"])
    ok = db_ok and disk_ok
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
