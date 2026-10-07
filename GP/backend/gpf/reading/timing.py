"""Where a GP Fund reading job's time goes, kept in the database (perf/pipeline, 7 Oct 2026).

The module's own small writer -- it runs as its own process and does not import the pension
tree -- to the same ``run_timings`` table (api/migrations/0011 in the pension tree; created here
if absent) in the database ``GPF_DB`` names. Rows: one per page stage (classify, extract,
barcodes) and one per model call, under the reading job's id. Writes never raise into the read.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

_local = threading.local()
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


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


def _db_path() -> Path | None:
    raw = os.environ.get("GPF_DB")
    if raw == "":
        return None                                   # the module on its own JSON store: no table
    if raw:
        return Path(raw)
    from ..store import DEFAULT_DB
    return Path(DEFAULT_DB)


def _connection() -> sqlite3.Connection | None:
    global _conn
    with _lock:
        if _conn is not None:
            return _conn
        path = _db_path()
        if path is None:
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, timeout=5.0, isolation_level=None, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS run_timings (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL, "
                "stage TEXT NOT NULL, name TEXT, page INTEGER, started_at TEXT NOT NULL, ended_at TEXT NOT NULL, "
                "duration_s REAL NOT NULL, queue_s REAL, pages INTEGER, status TEXT NOT NULL DEFAULT 'ok', detail_json TEXT)")
            conn.execute("CREATE INDEX IF NOT EXISTS run_timings_run ON run_timings(run_id, started_at)")
        except sqlite3.Error:
            return None
        _conn = conn
        return conn


def record(kind: str, stage: str, *, started: float, ended: float, name: str | None = None, page: int | None = None,
           pages: int | None = None, status: str = "ok", detail: dict | None = None, job_id: str | None = None) -> None:
    jid = job_id or current()
    if not jid:
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
    except sqlite3.Error:
        pass


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
