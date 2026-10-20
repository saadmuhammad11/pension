"""Where a GP Fund reading job's time goes: one JSON object per line, in a file.

One line per page stage (classify, extract, barcodes) and one per model call, under the
reading job's id, in ``<GPF_DATA_DIR>/jobs/<job-id>.jsonl``. Writes never raise into the read:
a lost line is not a lost examination.

A file, not the database. This was written to the pension tree's ``run_timings`` table and is
not any more (20 Oct 2026, the office's instruction): a log is append-only, read by eye and by
grep, wants no schema, and should not share the store that holds the cases and has to be
backed up and restored. The pension pipeline's own log moved the same way and for the same
reason -- see pipeline/timing.py, whose file this mirrors line for line so one reader can read
both.

GPF_TIMING_DB=1 puts the table writes back for a deployment that has something pointed at it.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

_local = threading.local()
_lock = threading.Lock()
_log_lock = threading.Lock()
_conn: Any = None

#: The call log. GPF_CALL_LOG=0 turns it off.
CALL_LOG = os.environ.get("GPF_CALL_LOG", "1") not in ("0", "false", "no", "off")

#: The same records in run_timings. Off by default: logs do not belong in the case database.
TIMING_DB = os.environ.get("GPF_TIMING_DB", "0") not in ("0", "false", "no", "off")


def log_dir() -> Path:
    """Where a job's calls are written. Beside the module's other data, not in the database."""
    return Path(os.environ.get("GPF_DATA_DIR") or ".") / "jobs"


def _log_line(job_id: str, row: dict) -> None:
    """Append one call to the job's log. Never raises into the read."""
    if not CALL_LOG:
        return
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False, default=str)
        with _log_lock, (d / f"{job_id}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:                                 # noqa: BLE001 -- a lost line, never a lost read
        pass


def current() -> str | None:
    return getattr(_local, "job_id", None)


@contextmanager
def bind(job_id: str | None) -> Iterator[None]:
    before = current()
    _local.job_id = job_id
    try:
        yield
    finally:
        _local.job_id = before


def carry(fn, *, page: int | None = None):
    """Wrap a callable about to be handed to a pool, so it runs bound to the submitting
    thread's job.

    The job id lives in a threading.local, which a pool worker does not inherit. Without this,
    every per-page `timing.stage(...)` inside a worker finds no job, record() drops the row,
    and the run that was just made three times faster reports no timings at all -- which is
    how a measurement disappears exactly when it becomes interesting (20 Oct 2026).

    The wait between submission and start is kept too: with four workers and more pages than
    that, the later pages queue, and a page's wall time is not its model time.
    """
    job_id = current()
    submitted = time.monotonic()

    def wrapped(*a, **k):
        waited = time.monotonic() - submitted
        with bind(job_id):
            _local.queue_s = waited
            try:
                return fn(*a, **k)
            finally:
                _local.queue_s = None
    return wrapped


def _db_target() -> str | Path | None:
    raw = os.environ.get("GPF_DB")
    if raw == "":
        return None                                   # the module on its own JSON store: no table
    if raw:
        return raw if raw.lower().startswith(("postgresql://", "postgres://")) else Path(raw)
    from ..store import DEFAULT_DB
    return Path(DEFAULT_DB)


def _connection() -> Any:
    global _conn
    with _lock:
        if _conn is not None:
            return _conn
        target = _db_target()
        if target is None:
            return None
        try:
            from ..dbshim import dbcore
            conn = dbcore.connect(target)
            for stmt in dbcore.run_timings_ddl(dbcore.backend_of(conn)):
                conn.execute(stmt)
        except Exception:                             # noqa: BLE001 -- no database, no timing rows
            return None
        _conn = conn
        return conn


def _drop_connection() -> None:
    global _conn
    with _lock:
        try:
            if _conn is not None:
                _conn.close()
        except Exception:                             # noqa: BLE001
            pass
        _conn = None


def record(kind: str, stage: str, *, started: float, ended: float, name: str | None = None, page: int | None = None,
           pages: int | None = None, status: str = "ok", detail: dict | None = None, job_id: str | None = None) -> None:
    jid = job_id or current()
    if not jid:
        return
    _log_line(jid, {
        "at": datetime.fromtimestamp(started).isoformat(timespec="milliseconds"),
        "ended": datetime.fromtimestamp(ended).isoformat(timespec="milliseconds"),
        "kind": kind, "stage": stage, "name": name, "page": page, "pages": pages,
        "duration_s": round(ended - started, 3),
        "queue_s": getattr(_local, "queue_s", None),
        "status": status, "detail": detail,
    })
    if not TIMING_DB:
        return
    conn = _connection()
    if conn is None:
        return
    try:
        with _lock:
            conn.execute(
                "INSERT INTO run_timings(run_id, kind, stage, name, page, started_at, ended_at, duration_s, queue_s, pages, status, detail_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
                (jid, kind, stage, name, page, datetime.fromtimestamp(started).isoformat(timespec="milliseconds"),
                 datetime.fromtimestamp(ended).isoformat(timespec="milliseconds"), round(ended - started, 3), pages, status,
                 json.dumps(detail, ensure_ascii=False, default=str) if detail else None))
    except Exception:                                 # noqa: BLE001 -- a lost row, never a lost read
        _drop_connection()


@contextmanager
def stage(name: str, *, page: int | None = None, pages: int | None = None) -> Iterator[None]:
    started = time.time(); status = "ok"
    try:
        yield
    except BaseException:
        status = "error"
        raise
    finally:
        record("stage", name, started=started, ended=time.time(), page=page, pages=pages, status=status)


def model_call(role: str, *, started: float, ended: float, schema: str | None = None, page: int | None = None,
               status: str = "ok", detail: dict[str, Any] | None = None) -> None:
    record("model", role, started=started, ended=ended, name=schema, page=page, status=status, detail=detail)
