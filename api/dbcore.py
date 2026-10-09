"""The database engine behind ``api.db``: PostgreSQL, with SQLite kept for a box that has none.

The application was written against ``sqlite3`` -- ``?`` placeholders, ``sqlite3.Row`` access by
name and by position, ``BEGIN IMMEDIATE``, ``INSERT OR IGNORE`` -- and that is a lot of working
code. This module lets the same statements run on PostgreSQL (9 Oct 2026): ``PgConnection`` is a
connection with the ``sqlite3.Connection`` surface the code uses (``execute`` returning something
to ``fetchone`` / ``fetchall`` / iterate, ``executescript``, ``commit``, ``close``), and it
rewrites each statement on the way in:

    ?                       ->  %s        (outside string literals)
    :name                   ->  %(name)s  (when the parameters are a dict)
    INSERT OR IGNORE INTO   ->  INSERT INTO ... ON CONFLICT DO NOTHING
    BEGIN IMMEDIATE         ->  BEGIN     (api.db.transaction takes an advisory lock after it)
    PRAGMA table_info(t)    ->  the same columns from information_schema
    PRAGMA foreign_keys=OFF ->  SET session_replication_role = replica   (tests; needs a superuser)
    PRAGMA anything-else    ->  nothing
    True / False            ->  1 / 0     (the schema keeps INTEGER 0/1 flags)

Everything else is SQL both engines speak: the schema uses TEXT, INTEGER, DOUBLE PRECISION, ISO
timestamps as TEXT, ``ON CONFLICT ... DO UPDATE SET x = excluded.x``, savepoints, ``substr``, ``CAST``.
What differs in the DDL (triggers, identity columns, widening a CHECK) lives in
``api/migrations/postgres/`` as per-version overrides; see ``api.db.migrate``.

Rows come back as ``Row``: ``row["name"]``, ``row[0]``, ``row.keys()``, ``dict(row)``, iteration
over the values -- what ``sqlite3.Row`` offers. Parameters are bound client-side (psycopg's
``ClientCursor``), so a string ``'2'`` compared to an INTEGER column is a literal PostgreSQL casts,
as SQLite would have; server-side binding would have typed it ``text`` and refused.

The driver is ``psycopg`` 3 with its bundled libpq, imported from the interpreter if it has it,
else from ``<root>/vendor`` (``deploy/vendor-psycopg.sh``). Nothing here imports the rest of the
pension tree, so the GP Fund module (its own process) loads this file by path and shares it.

Nothing is imported from psycopg until a PostgreSQL connection is asked for; a SQLite-only
deployment never needs the driver.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Any, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"

_psycopg: Any = None
_import_lock = threading.Lock()


def psycopg() -> Any:
    """The psycopg module: the interpreter's own, else the vendored copy."""
    global _psycopg
    if _psycopg is not None:
        return _psycopg
    with _import_lock:
        if _psycopg is not None:
            return _psycopg
        try:
            import psycopg as mod
        except ModuleNotFoundError:
            if not VENDOR.is_dir():
                raise ModuleNotFoundError(
                    "psycopg is not installed and there is no vendor/ directory; run deploy/vendor-psycopg.sh "
                    "or pip install 'psycopg[binary]'") from None
            if str(VENDOR) not in sys.path:
                sys.path.append(str(VENDOR))          # appended: never shadows the interpreter's own packages
            import psycopg as mod
        _psycopg = mod
        return mod


def driver_available() -> bool:
    try:
        psycopg()
        return True
    except ModuleNotFoundError:
        return False


def is_postgres(target: Any) -> bool:
    """A ``postgresql://`` / ``postgres://`` URL names PostgreSQL; a path names a SQLite file."""
    return isinstance(target, str) and target.lower().startswith(("postgresql://", "postgres://"))


def backend_of(conn: Any) -> str:
    return "postgres" if isinstance(conn, PgConnection) else "sqlite"


def masked(target: Any) -> str:
    """The target for a log line: the URL with its password hidden, or the file path."""
    if not is_postgres(target):
        return str(target)
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", target)


# -- rows ----------------------------------------------------------------------------------------

class Row:
    """A result row with ``sqlite3.Row``'s manners: by name, by position, ``keys()``, ``dict(row)``."""
    __slots__ = ("_keys", "_values")

    def __init__(self, keys: Sequence[str], values: Sequence[Any]):
        self._keys = tuple(keys)
        self._values = tuple(values)

    def keys(self) -> list[str]:
        return list(self._keys)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, (int, slice)):
            return self._values[key]
        try:
            return self._values[self._keys.index(key)]
        except ValueError:
            raise IndexError(f"No item with that key: {key!r}") from None

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, key: Any) -> bool:
        return key in self._keys

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Row):
            return self._keys == other._keys and self._values == other._values
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return "Row(" + ", ".join(f"{k}={v!r}" for k, v in zip(self._keys, self._values)) + ")"


def _row_factory(cursor: Any):
    names = tuple(d.name for d in cursor.description) if cursor.description else ()

    def make(values: Sequence[Any]) -> Row:
        return Row(names, values)
    return make


class _EmptyCursor:
    """What a PRAGMA that means nothing on PostgreSQL returns."""
    rowcount = -1
    lastrowid = None
    description = None

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list:
        return []

    def fetchmany(self, size: int = 0) -> list:
        return []

    def __iter__(self) -> Iterator[Any]:
        return iter(())

    def close(self) -> None:
        pass


_EMPTY = _EmptyCursor()

# -- statement translation -----------------------------------------------------------------------

_INSERT_OR_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\b", re.IGNORECASE)
_INSERT_OR_REPLACE = re.compile(r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\b", re.IGNORECASE)
_BEGIN = re.compile(r"^\s*BEGIN\s+(IMMEDIATE|EXCLUSIVE|DEFERRED)\b", re.IGNORECASE)
_PRAGMA = re.compile(r"^\s*PRAGMA\s+(\w+)(?:\s*\(\s*(\w+)\s*\))?", re.IGNORECASE)
_TABLE_INFO = (
    "SELECT ordinal_position - 1 AS cid, column_name AS name, data_type AS type, "
    "CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull, column_default AS dflt_value, 0 AS pk "
    "FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = '{table}' "
    "ORDER BY ordinal_position")


def translate(sql: str, *, has_params: bool, named: bool = False) -> str | None:
    """The PostgreSQL form of one statement written for sqlite3; None for a PRAGMA to ignore."""
    m = _PRAGMA.match(sql)
    if m:
        what = m.group(1).lower()
        if what == "table_info" and m.group(2):
            return _TABLE_INFO.format(table=m.group(2).lower())
        if what == "foreign_keys":
            # Only the tests turn referential checks off, to exercise a trigger on its own. The
            # append-only triggers are ENABLE ALWAYS, so they keep firing in replica mode.
            value = sql.split("=", 1)[1].strip().strip(";").lower() if "=" in sql else ""
            if value in ("off", "0", "false"):
                return "SET session_replication_role = replica"
            if value in ("on", "1", "true"):
                return "SET session_replication_role = DEFAULT"
        return None
    if _INSERT_OR_REPLACE.match(sql):
        raise NotImplementedError("INSERT OR REPLACE has no conflict target; write ON CONFLICT (...) DO UPDATE")
    ignore = bool(_INSERT_OR_IGNORE.match(sql))
    if ignore:
        sql = _INSERT_OR_IGNORE.sub("INSERT INTO", sql, count=1)
    sql = _BEGIN.sub("BEGIN", sql, count=1)
    sql = _placeholders(sql, escape_percent=has_params, named=named)
    if ignore and "on conflict" not in sql.lower():
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _placeholders(sql: str, *, escape_percent: bool, named: bool = False) -> str:
    """``?`` -> ``%s`` (``:name`` -> ``%(name)s`` for dict parameters) and, when parameters
    follow, a literal ``%`` -> ``%%``; string literals and quoted identifiers are left as written."""
    out: list[str] = []
    quote: str | None = None
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if quote:
            out.append(c)
            if c == quote:
                if i + 1 < n and sql[i + 1] == quote:       # '' inside a literal
                    out.append(quote); i += 1
                else:
                    quote = None
            elif c == "%" and escape_percent:
                out.append("%")
        elif c in ("'", '"'):
            quote = c; out.append(c)
        elif c == "?":
            out.append("%s")
        elif c == ":" and named and i + 1 < n and (m := _NAME.match(sql, i + 1)) and not sql.startswith("::", i) \
                and not (i > 0 and sql[i - 1] == ":"):
            out.append(f"%({m.group(0)})s"); i = m.end(); continue
        elif c == "%" and escape_percent:
            out.append("%%")
        elif c == "-" and sql.startswith("--", i):           # a comment runs to the end of the line
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(sql[i:j]); i = j; continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _params(params: Any) -> Any:
    if params is None:
        return None
    if isinstance(params, dict):
        return {k: (int(v) if isinstance(v, bool) else v) for k, v in params.items()}
    return tuple(int(v) if isinstance(v, bool) else v for v in params)


_ADD_COLUMN = re.compile(r"\bADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS)", re.IGNORECASE)
_REAL = re.compile(r"\bREAL\b")


def ddl_for_postgres(script: str) -> str:
    """A migration written for sqlite3 made idempotent on PostgreSQL: ``ADD COLUMN IF NOT EXISTS``
    (sqlite has no such form; api.db skips its 'duplicate column' error instead) and ``DOUBLE
    PRECISION`` for ``REAL``. Triggers and identity columns need an override file."""
    script = _ADD_COLUMN.sub("ADD COLUMN IF NOT EXISTS ", script)
    return _REAL.sub("DOUBLE PRECISION", script)


# -- the connection ------------------------------------------------------------------------------

class PgConnection:
    """A psycopg connection worn like a ``sqlite3.Connection``.

    Autocommit, as the application's sqlite connections were (``isolation_level=None``): a
    statement outside ``BEGIN``/``COMMIT`` is its own transaction, and ``api.db.transaction``
    brackets the writes that belong together.
    """
    backend = "postgres"

    def __init__(self, dsn: str, *, schema: str | None = None, connect_timeout: float = 10.0):
        pg = psycopg()
        self._pg = pg
        self._status = pg.pq.TransactionStatus
        self._c = pg.connect(dsn, autocommit=True, connect_timeout=connect_timeout,
                             cursor_factory=pg.ClientCursor, row_factory=_row_factory)
        self.dsn = dsn
        self.schema = schema
        if schema:
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
                raise ValueError(f"not a schema name: {schema!r}")
            self._c.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            self._c.execute(f'SET search_path TO "{schema}"')

    # sqlite3.Connection lets callers set this; every row here is already a Row.
    @property
    def row_factory(self) -> Any:
        return Row

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        pass

    def execute(self, sql: str, params: Any = ()) -> Any:
        named = isinstance(params, dict)
        has = True if named else bool(params)
        text = translate(sql, has_params=has, named=named)
        if text is None:
            return _EMPTY
        return self._c.execute(text, _params(params) if has else None)

    def executemany(self, sql: str, seq_of_params: Any) -> Any:
        seq = [_params(p) for p in seq_of_params]
        text = translate(sql, has_params=True, named=bool(seq) and isinstance(seq[0], dict))
        cur = self._c.cursor()
        cur.executemany(text, seq)
        return cur

    def executescript(self, script: str) -> Any:
        """The script as written, in one round trip -- several statements, ``$$`` bodies and all."""
        return self._c.execute(script)

    def cursor(self) -> Any:
        return self._c.cursor()

    @property
    def in_transaction(self) -> bool:
        return self._c.info.transaction_status in (self._status.INTRANS, self._status.INERROR)

    def commit(self) -> None:
        st = self._c.info.transaction_status
        if st == self._status.INTRANS:
            self._c.execute("COMMIT")
        elif st == self._status.INERROR:
            self._c.execute("ROLLBACK")

    def rollback(self) -> None:
        if self.in_transaction:
            self._c.execute("ROLLBACK")

    def close(self) -> None:
        self._c.close()

    @property
    def closed(self) -> bool:
        return self._c.closed

    def __enter__(self) -> "PgConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # sqlite3's context manager commits or rolls back the open transaction; same here.
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

    def __repr__(self) -> str:
        return f"<PgConnection {masked(self.dsn)} schema={self.schema or 'public'}>"


def connect_sqlite(path: Path | str) -> sqlite3.Connection:
    """The sqlite3 connection the application always had: WAL, foreign keys, a busy timeout."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def connect(target: Path | str, *, schema: str | None = None) -> Any:
    """A connection to ``target``: a PostgreSQL URL (optionally into one schema) or a SQLite path."""
    if is_postgres(target):
        return PgConnection(str(target), schema=schema)
    return connect_sqlite(target)


def table_names(conn: Any) -> set[str]:
    if backend_of(conn) == "postgres":
        return {r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")}
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# -- errors, for ``except`` clauses that must hold on either engine -------------------------------

def _error_classes() -> tuple[tuple[type, ...], tuple[type, ...], tuple[type, ...]]:
    error: tuple[type, ...] = (sqlite3.Error,)
    integrity: tuple[type, ...] = (sqlite3.IntegrityError,)
    operational: tuple[type, ...] = (sqlite3.OperationalError,)
    if driver_available():
        pg = psycopg()
        error += (pg.Error,)
        integrity += (pg.IntegrityError,)
        # A lost connection, a lock not available, a server shutting down: the same family of
        # trouble sqlite reports as OperationalError.
        operational += (pg.OperationalError, pg.InterfaceError)
    return error, integrity, operational


Error, IntegrityError, OperationalError = _error_classes()


# -- shared DDL ------------------------------------------------------------------------------------

def run_timings_ddl(backend: str) -> tuple[str, str]:
    """The ``run_timings`` table (migration 0011) for a writer that may start before the API has
    migrated: the table and its index, in the engine's form."""
    key = ("BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if backend == "postgres" else "INTEGER PRIMARY KEY")
    real = "DOUBLE PRECISION" if backend == "postgres" else "REAL"
    return (
        f"CREATE TABLE IF NOT EXISTS run_timings (id {key}, run_id TEXT NOT NULL, kind TEXT NOT NULL, "
        f"stage TEXT NOT NULL, name TEXT, page INTEGER, started_at TEXT NOT NULL, ended_at TEXT NOT NULL, "
        f"duration_s {real} NOT NULL, queue_s {real}, pages INTEGER, status TEXT NOT NULL DEFAULT 'ok', detail_json TEXT)",
        "CREATE INDEX IF NOT EXISTS run_timings_run ON run_timings(run_id, started_at)")
