"""Where a GP Fund reading job's time goes, kept in the database (perf/pipeline, 7 Oct 2026).

The module's own small writer -- it runs as its own process -- to the same ``run_timings`` table
(api/migrations/0011 in the pension tree; created here if absent) in the database ``GPF_DB`` names:
a PostgreSQL URL (9 Oct 2026) or a SQLite file, through the pension tree's engine shim
(``gpf.dbshim``). Rows: one per page stage (classify, extract, barcodes) and one per model call,
under the reading job's id. Writes never raise into the read.
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
_conn: Any = None


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
