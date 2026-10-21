"""Persistence: a case repository and a document store.

Two seams kept deliberately simple and swappable:

* `DbCaseRepository` — the cases, in the shared portal database (29 Sep 2026): the database the
  AG Punjab pension case system keeps its cases in -- PostgreSQL, named by ``GPF_DB`` as a URL
  (9 Oct 2026), or the SQLite file ``artifacts/portal.sqlite3`` at the top of the pension tree --
  tables ``gpf_cases`` and ``gpf_documents`` (schema in ``api/migrations/0005_gpf_cases.sql``
  there). One backup covers both products. The `Repository` protocol is the contract.
  ``SqliteCaseRepository`` remains as the old name of the same class.
* `CaseRepository` — the original in-memory store with write-through JSON snapshots. Kept for
  tests and for running the module on its own (``GPF_DB=`` empty); the snapshots it wrote before
  the move are imported into the database once, by id, the first time the SQLite repository sees
  them.
* `DocumentStore` — case pages are never overwritten (spec §7.1). Every upload
  is stored by content hash with its SHA-256, size, type, officer and time,
  which is exactly what the audit trail and issue pack record (§13.4, §15).
  Given a database, it also records each page in ``gpf_documents``.

CaseState is plain data (dicts/lists), so snapshots are ordinary JSON.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol

from .dbshim import dbcore
from .engine import CaseState


# ── document store ────────────────────────────────────────────────────────────
class DocumentStore:
    def __init__(self, root: Path, db: "Optional[DbCaseRepository]" = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = db

    def save(self, case_id: str, filename: str, content: bytes,
             *, content_type: Optional[str] = None) -> dict:
        sha = hashlib.sha256(content).hexdigest()
        case_dir = self.root / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename or "upload")
        path = case_dir / (sha[:16] + "_" + safe)
        path.write_bytes(content)
        meta = {
            "name": filename,
            "storedAs": str(path.relative_to(self.root)),
            "hash": sha,
            "size": len(content),
            "type": content_type or mimetypes.guess_type(filename or "")[0] or "application/octet-stream",
        }
        if self.db is not None:
            self.db.record_document(case_id, meta)
        return meta

    def read(self, case_id: str, stored_as: str) -> Optional[bytes]:
        path = self.root / stored_as
        try:
            path.resolve().relative_to(self.root.resolve())  # path-traversal guard
        except ValueError:
            return None
        return path.read_bytes() if path.exists() else None


# ── case repository ───────────────────────────────────────────────────────────
_SNAPSHOT_FIELDS = ("k", "F", "without_sap", "officer", "version", "results", "prev",
                    "last_diff", "history", "disp", "audit", "returns", "issued", "uploads",
                    "caseDisp", "caseNote", "meta")


def _to_snapshot(s: CaseState, case_id: str) -> dict:
    d = {f: getattr(s, f) for f in _SNAPSHOT_FIELDS}
    d["id"] = case_id
    return d


def _from_snapshot(d: dict) -> CaseState:
    s = CaseState(k=d["k"], F=d["F"])
    for f in _SNAPSHOT_FIELDS:
        if f in d:
            setattr(s, f, d[f])
    return s


class Repository(Protocol):
    def create(self, case_id: str, state: CaseState) -> None: ...
    def get(self, case_id: str) -> Optional[CaseState]: ...
    def save(self, case_id: str, state: CaseState) -> None: ...
    def list_ids(self) -> list[str]: ...
    def exists(self, case_id: str) -> bool: ...


class CaseRepository:
    """In-memory, with optional write-through JSON snapshots for durability."""

    def __init__(self, snapshot_dir: Optional[Path] = None):
        self._mem: dict[str, CaseState] = {}
        self._dir = Path(snapshot_dir) if snapshot_dir else None
        if self._dir:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._load_all()

    def _snap_path(self, case_id: str) -> Path:
        return self._dir / (case_id + ".json")

    def _load_all(self) -> None:
        for p in sorted(self._dir.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                self._mem[d["id"]] = _from_snapshot(d)
            except Exception:
                continue

    def _persist(self, case_id: str, state: CaseState) -> None:
        if not self._dir:
            return
        self._snap_path(case_id).write_text(
            json.dumps(_to_snapshot(state, case_id), ensure_ascii=False, indent=1),
            encoding="utf-8")

    def create(self, case_id: str, state: CaseState) -> None:
        self._mem[case_id] = state
        self._persist(case_id, state)

    def get(self, case_id: str) -> Optional[CaseState]:
        return self._mem.get(case_id)

    def save(self, case_id: str, state: CaseState) -> None:
        self._mem[case_id] = state
        self._persist(case_id, state)

    def list_ids(self) -> list[str]:
        return list(self._mem.keys())

    def exists(self, case_id: str) -> bool:
        return case_id in self._mem


# ── the shared database ───────────────────────────────────────────────────────
#: The pension tree's migration that defines gpf_cases and gpf_documents. This file sits at
#: <pension>/GP/backend/gpf/store.py, so the pension root is three levels up.
PENSION_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = PENSION_ROOT / "artifacts" / "portal.sqlite3"
SCHEMA_SQL = PENSION_ROOT / "api" / "migrations" / "0005_gpf_cases.sql"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class DbCaseRepository:
    """Cases in the shared portal database, with the in-memory map the service works on.

    Semantics are those of `CaseRepository`: `get` hands back the live object, `save` makes it
    durable. The database is the durable copy and the whole record is loaded at start-up, so a
    restart -- of this module or of the machine -- loses nothing that was saved.

    ``db`` is a PostgreSQL URL or the path of a SQLite file (``dbcore`` tells them apart). The one
    connection is shared by the request threads; writes take a lock, since a psycopg connection
    runs one statement at a time (sqlite serialised them itself).
    """

    def __init__(self, db: Path | str = DEFAULT_DB, *, schema_sql: Path = SCHEMA_SQL,
                 import_dir: Optional[Path] = None):
        self.target: Any = str(db) if dbcore.is_postgres(str(db)) else Path(db)
        self.path: Optional[Path] = self.target if isinstance(self.target, Path) else None   # None on PostgreSQL
        self.conn = dbcore.connect(self.target)
        self.backend = dbcore.backend_of(self.conn)
        self._lock = threading.RLock()
        self._ensure_schema(schema_sql)
        self.imported = self.import_snapshots(import_dir) if import_dir else 0
        self._mem: dict[str, CaseState] = {}
        for row in self.conn.execute("SELECT id, state_json FROM gpf_cases ORDER BY created_at, id"):
            self._mem[row["id"]] = _from_snapshot(json.loads(row["state_json"]))

    def _ensure_schema(self, schema_sql: Path) -> None:
        have = dbcore.table_names(self.conn)
        if {"gpf_cases", "gpf_documents"} <= have:
            return
        if not schema_sql.exists():
            raise RuntimeError(f"{dbcore.masked(self.target)} has no gpf_cases table and the schema file "
                               f"{schema_sql} is missing")
        # The same file the pension API applies at start-up; recorded there so it is not re-run.
        self.conn.executescript(schema_sql.read_text(encoding="utf-8"))
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                          "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        self.conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                          (schema_sql.stem, _now()))

    # -- rows ------------------------------------------------------------------
    @staticmethod
    def _columns(case_id: str, s: CaseState) -> dict:
        officer = s.officer or {}
        return {
            "id": case_id, "kind": (s.F or {}).get("kind") or s.k.split("-scan-")[0],
            "officer_id": officer.get("id"), "officer_name": officer.get("name"),
            "version": int(s.version or 1), "returns": int(s.returns or 0), "issued": int(bool(s.issued)),
            "case_disp": s.caseDisp, "from_scans": int(s.meta is not None),
            "state_json": json.dumps(_to_snapshot(s, case_id), ensure_ascii=False),
        }

    def _write(self, case_id: str, s: CaseState, *, created_at: Optional[str] = None) -> None:
        cols = self._columns(case_id, s)
        stamp = _now()
        # ISO-8601 like the rest of the database; the module's own audit stamps are DD-MM-YYYY.
        cols["created_at"] = created_at or stamp
        cols["updated_at"] = stamp
        names = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in ("id", "created_at"))
        with self._lock:
            self._execute(f"INSERT INTO gpf_cases({names}) VALUES ({marks}) "
                          f"ON CONFLICT(id) DO UPDATE SET {updates}", tuple(cols.values()))

    def _execute(self, sql: str, params: tuple) -> None:
        """Run one write, reopening the connection once if it has gone away.

        The module holds a single connection opened at import and never reopened, so a
        PostgreSQL restart -- or an idle timeout, or a failover -- broke every GP Fund write
        permanently until someone restarted the service (H-17). The pension API opens a
        connection per request and never noticed; its own timing module already reconnects,
        and this is the same move.

        One retry, not a loop: if the fresh connection fails too, the database is down and the
        caller must hear about it rather than wait while this spins.
        """
        try:
            self.conn.execute(sql, params)
            return
        except Exception:                             # noqa: BLE001 -- retried once, then raised
            try:
                self.conn = dbcore.connect(self.target)
            except Exception:
                raise
        self.conn.execute(sql, params)

    def record_document(self, case_id: str, meta: dict) -> None:
        with self._lock:
            self._execute(
                "INSERT INTO gpf_documents(id, case_id, name, stored_as, sha256, bytes, content_type, saved_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, case_id, meta["name"] or "upload", meta["storedAs"], meta["hash"],
                 meta["size"], meta["type"], _now()))

    def import_snapshots(self, snapshot_dir: Path) -> int:
        """Load the JSON snapshots the file-backed repository wrote, skipping ids already present.
        The files are left where they are; nothing writes them any more."""
        snapshot_dir = Path(snapshot_dir)
        if not snapshot_dir.is_dir():
            return 0
        have = {r["id"] for r in self.conn.execute("SELECT id FROM gpf_cases")}
        n = 0
        for p in sorted(snapshot_dir.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                case_id = d["id"]
            except Exception:
                continue
            if case_id in have:
                continue
            created = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
            self._write(case_id, _from_snapshot(d), created_at=created)
            have.add(case_id)
            n += 1
        return n

    # -- Repository ------------------------------------------------------------
    def create(self, case_id: str, state: CaseState) -> None:
        self._mem[case_id] = state
        self._write(case_id, state)

    def get(self, case_id: str) -> Optional[CaseState]:
        return self._mem.get(case_id)

    def save(self, case_id: str, state: CaseState) -> None:
        """Persist first; on failure put memory back to what the database holds.

        It was memory first and the database afterwards with no rollback, and a write that
        raised gave the caller a 500 while every later read went on showing the disposal, the
        waiver and the verification as recorded -- until the next restart, when they were
        gone, because memory is rebuilt from the table (audit of 13 Oct 2026, H-17). An
        officer who saw an error, looked again and found their decision there would reasonably
        conclude it had gone in.

        Ordering the two is not enough on its own. get() hands back the stored object and the
        service mutates it in place, so by the time save() is called the change is ALREADY in
        memory and re-assigning the same object changes nothing. The only honest repair is to
        reload the case from the database, which is the last state that really exists, and let
        the exception go to the caller.

        If the reload fails too the case is dropped from memory rather than left mutated: the
        next read fetches it, and a 404 an officer can retry beats a decision that looks saved
        and is not.
        """
        try:
            self._write(case_id, state)
        except Exception:
            try:
                self._mem[case_id] = self._reload(case_id)
            except Exception:                         # noqa: BLE001 -- the database is unreachable
                self._mem.pop(case_id, None)
            raise
        self._mem[case_id] = state

    def _reload(self, case_id: str) -> CaseState:
        """One case, as the database holds it."""
        row = self.conn.execute("SELECT state_json FROM gpf_cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise KeyError(case_id)
        return _from_snapshot(json.loads(row["state_json"]))

    def list_ids(self) -> list[str]:
        return list(self._mem.keys())

    def exists(self, case_id: str) -> bool:
        return case_id in self._mem


#: The class's name until 9 Oct 2026, when the database stopped being only SQLite.
SqliteCaseRepository = DbCaseRepository
