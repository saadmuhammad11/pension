"""Where a run's time goes, kept in the database (perf/pipeline, 7 Oct 2026).

Every stage of a run, every model call it makes (vision, OCR), and every wait -- for the run
slot, for a pool worker -- is one row in ``run_timings`` (api/migrations/0011). Written from the
run's own thread and from the pool threads it fans out to; durable, so a restart loses nothing
and the benchmark (tools/bench.py) reads the same rows an officer's run writes.

Binding: ``bind(run_id)`` marks the current thread as working for a run. Pools do not inherit
thread state, so a callable submitted to one is wrapped with ``carry`` at submit time, which
remembers the run id and the moment of submission; when a worker picks it up, the wait is the
page's queue time and the id is bound in that worker.

Writes never raise into the pipeline: a database that cannot be reached loses the timing row,
not the run.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

_local = threading.local()
_lock = threading.Lock()
_conn: Any = None
_conn_path: Any = None          # what the connection was opened on: (target, DB_PATH) at the time


def current() -> str | None:
    """The run the current thread is working for, or None."""
    return getattr(_local, "run_id", None)


@contextmanager
def bind(run_id: str | None) -> Iterator[None]:
    """Mark this thread as working for ``run_id`` for the duration of the block."""
    before = current()
    _local.run_id = run_id
    try:
        yield
    finally:
        _local.run_id = before


def carry(fn: Callable[..., Any], *, stage: str, page: int | None = None) -> Callable[..., Any]:
    """Wrap a callable about to be handed to a pool: it runs bound to the submitting thread's run,
    and the time between submission and start is recorded as that page's queue wait."""
    run_id = current()
    submitted = time.monotonic()

    def wrapped(*a: Any, **k: Any) -> Any:
        waited = time.monotonic() - submitted
        with bind(run_id):
            _local.queue_s = waited
            try:
                return fn(*a, **k)
            finally:
                _local.queue_s = None
    return wrapped


def _connection() -> Any:
    """One connection for the process, opened lazily on the app's database (PostgreSQL or the
    SQLite file, whatever ``api.db`` is pointed at); reopened if the database target changes."""
    global _conn, _conn_path
    from api import db, dbcore
    key = (str(db.target()), str(db.DB_PATH))
    with _lock:
        if _conn is not None and _conn_path == key:
            return _conn
        try:
            conn = db.connect()
            for stmt in dbcore.run_timings_ddl(dbcore.backend_of(conn)):
                conn.execute(stmt)
        except Exception:                             # noqa: BLE001 -- no database, no timing rows
            return None
        _conn, _conn_path = conn, key
        return conn


def _drop_connection() -> None:
    """Forget a connection that failed; the next row opens a new one."""
    global _conn, _conn_path
    with _lock:
        try:
            if _conn is not None:
                _conn.close()
        except Exception:                             # noqa: BLE001
            pass
        _conn, _conn_path = None, None


def record(kind: str, stage: str, *, started: float, ended: float, name: str | None = None, page: int | None = None,
           pages: int | None = None, queue_s: float | None = None, status: str = "ok", detail: dict | None = None,
           run_id: str | None = None) -> None:
    """One row. ``started``/``ended`` are time.time() stamps. Silent on any database error."""
    rid = run_id or current()
    if not rid:
        return
    conn = _connection()
    if conn is None:
        return
    try:
        with _lock:
            conn.execute(
                "INSERT INTO run_timings(run_id, kind, stage, name, page, started_at, ended_at, duration_s, queue_s, pages, status, detail_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (rid, kind, stage, name, page, datetime.fromtimestamp(started).isoformat(timespec="milliseconds"),
                 datetime.fromtimestamp(ended).isoformat(timespec="milliseconds"), round(ended - started, 3),
                 None if queue_s is None else round(queue_s, 3), pages, status,
                 json.dumps(detail, ensure_ascii=False, default=str) if detail else None))
    except Exception:                                 # noqa: BLE001 -- a lost row, never a lost run
        _drop_connection()


@contextmanager
def stage(name: str, *, pages: int | None = None, detail: dict | None = None) -> Iterator[dict]:
    """Time one stage of the current run. The yielded dict may be given ``pages`` / ``detail`` as
    the stage learns them."""
    info: dict[str, Any] = {"pages": pages, "detail": dict(detail or {})}
    started = time.time()
    status = "ok"
    try:
        yield info
    except BaseException as exc:
        status = "error"
        info["detail"]["error"] = str(exc)[:300]
        raise
    finally:
        record("stage", name, started=started, ended=time.time(), pages=info.get("pages"), status=status,
               detail=info.get("detail") or None)


def queue_wait(stage_name: str, *, started: float, ended: float, name: str | None = None) -> None:
    record("queue", stage_name, started=started, ended=ended, name=name, queue_s=ended - started)


def model_call(role: str, *, started: float, ended: float, schema: str | None = None, page: int | None = None,
               status: str = "ok", detail: dict | None = None) -> None:
    """One request to a model server: ``role`` is vision or ocr; the round trip is the server's
    time (its own queueing included); the queue wait is the page's wait for a pool worker."""
    record("model", role, started=started, ended=ended, name=schema, page=page,
           queue_s=getattr(_local, "queue_s", None), status=status, detail=detail)


def page_of(image: str | Path) -> int | None:
    """The page number a rendered page image is named with: pages/p004-04.png -> 4, p041.png -> 41."""
    import re
    m = re.match(r"p(\d{1,4})(?!\d)", Path(image).stem)
    return int(m.group(1)) if m else None


def summary(run_id: str, conn: Any = None) -> dict:
    """Totals per stage and per model role for one run, from the table."""
    from api import db
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM run_timings WHERE run_id = ? ORDER BY started_at", (run_id,))]
    finally:
        if own:
            conn.close()
    stages = {}
    models: dict[str, dict] = {}
    queue = 0.0
    for r in rows:
        if r["kind"] == "stage":
            stages[r["stage"]] = {"duration_s": r["duration_s"], "pages": r["pages"], "status": r["status"]}
        elif r["kind"] == "model":
            m = models.setdefault(r["stage"], {"calls": 0, "total_s": 0.0, "max_s": 0.0, "errors": 0, "queue_s": 0.0})
            m["calls"] += 1; m["total_s"] += r["duration_s"]; m["max_s"] = max(m["max_s"], r["duration_s"])
            m["errors"] += r["status"] != "ok"; m["queue_s"] += r["queue_s"] or 0.0
        elif r["kind"] == "queue":
            queue += r["queue_s"] or r["duration_s"]
    wall = None
    if rows:
        wall = (datetime.fromisoformat(max(r["ended_at"] for r in rows)) - datetime.fromisoformat(min(r["started_at"] for r in rows))).total_seconds()
    return {"run_id": run_id, "wall_s": wall, "slot_wait_s": queue, "stages": stages, "models": models, "rows": len(rows)}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python3 -m pipeline.timing <run_id>", file=sys.stderr)
        return 2
    s = summary(argv[1])
    print(f"run {s['run_id']}: wall {s['wall_s']} s, slot wait {s['slot_wait_s']:.1f} s, {s['rows']} rows")
    for name, st in sorted(s["stages"].items(), key=lambda kv: -kv[1]["duration_s"]):
        print(f"  {name:<12} {st['duration_s']:8.1f} s  pages={st['pages']}  {st['status']}")
    for role, m in s["models"].items():
        print(f"  model {role:<6} {m['calls']:4d} calls  {m['total_s']:8.1f} s  max {m['max_s']:.1f} s  queue {m['queue_s']:.1f} s  errors {m['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
