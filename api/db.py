"""The shared database for the multi-department case system: PostgreSQL (SQLite where there is none).

PostgreSQL since 9 Oct 2026: ``PENSION_DATABASE_URL`` (``postgresql://user:pw@host:port/db``) names
the database; ``deploy/docker-compose.postgres.yml`` runs one on this box and both run scripts source
``deploy/postgres.env``. The trial's SQLite file was imported and retired that day; a SQLite file is
used only where ``PENSION_DB`` names one explicitly (a box with no PostgreSQL), never by default.
The statements are written once; ``api.dbcore`` translates the sqlite3 idioms for PostgreSQL and
hands back the same kind of connection and rows. The migrations are plain SQL files in
``api/migrations/``, applied in order and recorded in ``schema_migrations``; where PostgreSQL needs
its own DDL (triggers, identity columns, a widened CHECK) ``api/migrations/postgres/<same name>.sql``
is applied in that file's place.

Who writes: request threads and the run reconciler (``api.case_runs``). The pipeline thread
never touches the database except to record its timings (``pipeline.timing``) -- it writes its
artefacts as it always has, and the reconciler reads them. The GP Fund module (GP/backend, its
own process on :8201) keeps its cases in the same database, in ``gpf_cases`` and
``gpf_documents`` (migration 0005, 29 Sep 2026), and applies that migration itself if it starts first.

Tests: with ``PENSION_TEST_DATABASE_URL`` set, every connection goes to that database and each
test's ``DB_PATH`` (the temporary path the fixtures patch in) becomes a schema of its own, dropped
when the process ends -- so the suites run unchanged on either engine (``tools/run-tests.sh``).

    python3 -m api.db info               # which engine, which database, which migrations
    python3 -m api.db migrate            # apply migrations
    python3 -m api.db seed               # departments, one officer per department, AG users (idempotent)
    python3 -m api.db import-sqlite artifacts/portal.sqlite3 [--replace]   # move a SQLite database's rows into PostgreSQL
    python3 -m api.db credentials        # rebuild artifacts/credentials/credentials.html from the CSV
    python3 -m api.db reset-department-password <slug>   # new generated password for one department
    python3 -m api.db reset-password <username> [<new password>]
    python3 -m api.db refresh-credentials <password>   # sheet rows for every account on this password; changes nothing
    python3 -m api.db add-reviewer <username> "<Officer's name>" --tier senior-auditor|assistant-ao|ao --wing Pension-III [<password>]
    python3 -m api.db add-reviewer <username> "<Officer's name>" --dag [<password>]   # the Deputy AG
    python3 -m api.db seed-wing-tiers [<password>]   # the trial's 15 tier accounts (sa/aao/ao.pension1..5), idempotent
    python3 -m api.db forget-credentials   # delete the plaintext sheet once passwords are handed out
    python3 -m api.db drop-test-schemas    # remove schemas a killed test run left in the test database

Production (PENSION_ENV=production, api.settings): PENSION_SEED_PASSWORD is refused, every
password the seed or a reset sets must be changed at first sign-in, and set-all-passwords is
refused. The sheet is still written once, owner-readable, for the administrator to hand the
passwords out from; ``forget-credentials`` then removes it.

Credentials: ``seed`` generates a unique password for every user it creates and writes the
plaintext ONCE to ``artifacts/credentials/credentials.csv`` (owner-readable only), then renders
``credentials.html`` from it. Nothing under ``artifacts/`` is served by any portal. Set
``PENSION_SEED_PASSWORD`` to give every seeded user the same password instead (tests, demos).
"""
from __future__ import annotations

import atexit
import hashlib
import os
import re
import sqlite3
import sys
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Union

from api import dbcore

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = Path(__file__).resolve().parent / "migrations"

PG_MIGRATIONS = MIGRATIONS / "postgres"

#: PostgreSQL, when set: ``postgresql://user:password@host:port/database``.
DATABASE_URL: str | None = os.environ.get("PENSION_DATABASE_URL") or None
#: The test suites' database. Every connection goes there, each ``DB_PATH`` as its own schema.
#: Never set for a server: ``run.sh`` leaves it alone and ``tools/run-tests.sh`` sets it.
TEST_DATABASE_URL: str | None = os.environ.get("PENSION_TEST_DATABASE_URL") or None
#: A SQLite file, used only when ``PENSION_DB`` names one and no URL is set (a box with no
#: PostgreSQL). Tests patch it (``mock.patch.object(db, "DB_PATH", tmp)``). None: PostgreSQL is
#: required, and ``connect()`` refuses rather than quietly opening an empty file (9 Oct 2026, the day
#: the trial's file was retired).
DB_PATH: Path | None = Path(os.environ["PENSION_DB"]) if os.environ.get("PENSION_DB") else None

#: For annotations: a connection and a row from either engine.
Connection = Union[sqlite3.Connection, dbcore.PgConnection]
Row = Union[sqlite3.Row, dbcore.Row]
#: For ``except`` clauses: tuples holding both engines' classes.
Error, IntegrityError, OperationalError = dbcore.Error, dbcore.IntegrityError, dbcore.OperationalError

#: The one advisory lock every write transaction takes on PostgreSQL (see transaction()).
WRITER_LOCK = 7_240_001

#: One password for every seeded user, where set (tests, demos). Unset: each user gets a unique
#: generated password, written once to the credentials sheet.
SEED_PASSWORD: str | None = os.environ.get("PENSION_SEED_PASSWORD") or None

CREDENTIALS_DIR = ROOT / "artifacts" / "credentials"
CREDENTIALS_CSV = CREDENTIALS_DIR / "credentials.csv"
CREDENTIALS_HTML = CREDENTIALS_DIR / "credentials.html"

#: The AG portal's users. Department accounts -- the DDO (Drawing and Disbursing Officer) who files the
#: department's cases, role DEPT_OFFICER -- are generated from api.departments: one per
#: department, username = the department's slug.
AG_USERS: tuple[tuple[str, str, str], ...] = (
    # The Accountant General's own desk (decision of 9 Oct 2026, afternoon): one login, ag.reviewer,
    # for the AG, the Additional AG and the other senior officers, acting at every tier in every wing and overriding like the
    # Deputy AG. It is the one shared login the office keeps (the C1 rule of 7 Oct 2026 stands for
    # every other account); the named trial login syed.haider of 7 Oct is renamed back to it by the
    # seed (see seed()) so the trial's records stay attached. Tier officers are created by the
    # administrator, with `python3 -m api.db add-reviewer`, or for the trial `seed-wing-tiers`.
    ("ag.reviewer", "AG / Additional AG and senior officers (all wings)", "AG_REVIEWER"),
    ("admin", "System Administrator", "ADMIN"),
)

#: Shared or role-named logins that production refuses to start with (C1): a decision must carry a
#: person's name, and every one of these could be anyone at the desk. ``ag.reviewer`` is not on the
#: list since 9 Oct 2026: it is the Accountant General's desk by decision, shared by the office's
#: senior officers, and the audit trail records it as that desk.
SHARED_LOGINS = ("reviewer", "ag.upload", "dag", "dag.pension", "ao", "officer", "auditor")

#: Logins renamed in place by the seed: same id, same password, sessions ended (token_version),
#: records untouched. 7 Oct 2026 renamed ag.reviewer to syed.haider (C1); 9 Oct 2026 renamed it
#: back, the desk login being the office's decision.
RENAMED_LOGINS = {"syed.haider": "ag.reviewer"}

#: The trial's tier accounts (9 Oct 2026): a Senior Auditor, an Assistant AO and an AO per pension
#: wing, named by desk; the office replaces them with named officers from the Users screen.
WING_TIER_LOGINS = (("sa", "AG_SENIOR_AUDITOR", "Senior Auditor"), ("aao", "AG_ASSISTANT_AO", "Assistant Accounts Officer"),
                    ("ao", "AG_AO", "Accounts Officer"))

#: The office's own pension-wing officers, one account per person (list of 13 Oct 2026). Data,
#: not code: ``config/ag_officers.json``, so the office edits the roster without a release. The
#: roles are the existing three and carry their existing permissions; nothing here grants anything.
AG_OFFICERS_FILE = ROOT / "config" / "ag_officers.json"


def load_ag_officers() -> list[dict]:
    """The roster: username, display name, role, role label and pension wing, in file order."""
    import json as _json
    if not AG_OFFICERS_FILE.exists():
        return []
    return list(_json.loads(AG_OFFICERS_FILE.read_text(encoding="utf-8")).get("officers") or [])


#: Accounts retired on 25 Sep 2026 -- the AG Upload role, and the first two demo officers whose
#: usernames predate the slug rule. Their records move to the department's own officer (or the
#: administrator, for a department that has none) and the account is removed.
RETIRED_USERS = ("ag.upload", "police.officer", "edu.officer")


def seed_users() -> list[tuple[str, str, str, str | None]]:
    """(username, display name, role, department code) for everyone the seed creates."""
    from api.departments import DEPARTMENTS
    out = [(u, n, r, None) for u, n, r in AG_USERS]
    out += [(d.slug, f"{d.name} — DDO", "DEPT_OFFICER", d.code) for d in DEPARTMENTS]
    return out


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def stamp() -> str:
    """A timestamp that orders rows written in the same second (audit rows): ISO-8601 with
    microseconds. Sorts after the second-precision stamps of the same second, as text."""
    return datetime.now().isoformat(timespec="microseconds")


def new_id() -> str:
    return uuid.uuid4().hex


def target(path: Path | str | None = None) -> str | Path:
    """What ``connect(path)`` opens: a PostgreSQL URL or a SQLite path."""
    if path is not None and dbcore.is_postgres(path):
        return str(path)
    if TEST_DATABASE_URL:
        return TEST_DATABASE_URL
    if path is not None:
        return Path(path)
    if DATABASE_URL:
        return DATABASE_URL
    if DB_PATH is None:
        raise RuntimeError("no database: set PENSION_DATABASE_URL (PostgreSQL; deploy/postgres.env) "
                           "or PENSION_DB for a SQLite file")
    return DB_PATH


def backend() -> str:
    """``postgres`` or ``sqlite``: the engine behind ``connect()``."""
    return "postgres" if dbcore.is_postgres(target()) else "sqlite"


def describe() -> str:
    """The target for a log line, password hidden."""
    t = target()
    if TEST_DATABASE_URL:
        return f"{dbcore.masked(t)} (test schema {_test_schema(None)})"
    return dbcore.masked(t)


def connect(path: Path | str | None = None) -> Connection:
    """A connection to the database: PostgreSQL via ``PENSION_DATABASE_URL``, else the SQLite file.

    Rows come back by name and by position (``sqlite3.Row`` / ``dbcore.Row``). Autocommit on both
    engines: bracket related writes with ``transaction()``.
    """
    if path is not None and dbcore.is_postgres(path):
        return dbcore.connect(str(path))
    if TEST_DATABASE_URL:
        return dbcore.connect(TEST_DATABASE_URL, schema=_test_schema(path))
    if path is None and DATABASE_URL:
        return dbcore.connect(DATABASE_URL)
    return dbcore.connect_sqlite(target(path))


# -- the test database: one schema per DB_PATH, gone when the process ends ----------------------
_test_schemas: set[str] = set()
_test_lock = threading.Lock()


def _test_schema(path: Path | str | None) -> str:
    name = "t_" + hashlib.sha1(str(Path(path or DB_PATH or "default")).encode("utf-8")).hexdigest()[:16]
    with _test_lock:
        fresh = name not in _test_schemas
        _test_schemas.add(name)
        if fresh:
            if not _test_schemas - {name}:
                atexit.register(drop_test_schemas)
            conn = dbcore.connect(TEST_DATABASE_URL)
            try:
                conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
                conn.execute(f'CREATE SCHEMA "{name}"')
            finally:
                conn.close()
    return name


def drop_test_schemas(*, every: bool = False) -> list[str]:
    """Drop the test schemas this process made -- or, with ``every``, all ``t_*`` schemas a killed
    run may have left behind. Returns the names dropped."""
    if not TEST_DATABASE_URL:
        return []
    try:
        conn = dbcore.connect(TEST_DATABASE_URL)
    except Exception:                                 # noqa: BLE001 -- the server is gone; nothing to tidy
        return []
    try:
        with _test_lock:
            names = sorted(_test_schemas)
            _test_schemas.clear()
        if every:
            names = [r[0] for r in conn.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 't\\_%' ESCAPE '\\'")]
        for name in names:
            conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
        return names
    finally:
        conn.close()


@contextmanager
def transaction(conn: Connection) -> Iterator[Connection]:
    """``BEGIN`` ... ``COMMIT``, rolled back on any exception; writers queue behind one another.

    On SQLite, ``BEGIN IMMEDIATE`` takes the write lock up front, so two request threads changing
    the same case queue instead of both reading the old status and both writing. PostgreSQL's
    READ COMMITTED would let both proceed, so there the transaction takes one advisory lock
    first (released with the transaction): the same discipline, and the write traffic is small.
    """
    if dbcore.backend_of(conn) == "postgres":
        conn.execute("BEGIN")
        conn.execute("SELECT pg_advisory_xact_lock(?)", (WRITER_LOCK,))
    else:
        conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _apply_migration(conn: Connection, script: str) -> None:
    """Run one migration file.

    PostgreSQL: the whole file in one transaction (functions with ``$$`` bodies cannot be split on
    semicolons), with ``ADD COLUMN`` made ``IF NOT EXISTS`` (``dbcore.ddl_for_postgres``).
    SQLite: statement by statement (triggers span several semicolons, so statements are cut where
    sqlite says one is complete); a column that already exists is not an error."""
    if dbcore.backend_of(conn) == "postgres":
        conn.execute("BEGIN")
        try:
            conn.executescript(dbcore.ddl_for_postgres(script))
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        return
    buf = ""
    for line in script.splitlines():
        if line.strip().startswith("--") and not buf:
            continue
        buf += line + "\n"
        if sqlite3.complete_statement(buf):
            stmt = buf.strip(); buf = ""
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" in str(exc).lower() and stmt.upper().startswith("ALTER TABLE"):
                    continue
                raise
    if buf.strip():
        conn.execute(buf)
    conn.commit()


def migration_file(path: Path, *, postgres: bool) -> Path:
    """The file to apply for one version: the PostgreSQL override where there is one."""
    if postgres and (PG_MIGRATIONS / path.name).exists():
        return PG_MIGRATIONS / path.name
    return path


def migrate(conn: Connection | None = None) -> list[str]:
    """Apply every migration file not yet recorded. Returns the versions applied."""
    own = conn is None
    conn = conn or connect()
    pg = dbcore.backend_of(conn) == "postgres"
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                     "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        applied: list[str] = []
        for path in sorted(MIGRATIONS.glob("*.sql")):
            version = path.stem
            if version in done:
                continue
            # SQLite: schema changes run with foreign-key enforcement off (its own advice for a
            # table rebuild, 0010); the pragma takes effect only outside a transaction, which is
            # where _apply_migration leaves the connection. CREATE statements are IF NOT EXISTS;
            # an ALTER TABLE ADD COLUMN has no such form there, so a column a half-applied run
            # already added is skipped rather than fatal. PostgreSQL needs neither.
            if not pg:
                conn.execute("PRAGMA foreign_keys=OFF")
            try:
                _apply_migration(conn, migration_file(path, postgres=pg).read_text(encoding="utf-8"))
            finally:
                if not pg:
                    conn.execute("PRAGMA foreign_keys=ON")
            # OR IGNORE: the GP Fund module records 0005 itself (gpf/store.py), and the two
            # starting together on a fresh database must not abort the migrations after it.
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                         (version, now()))
            applied.append(version)
        return applied
    finally:
        if own:
            conn.close()


# -- moving a SQLite database into PostgreSQL ------------------------------------------------------

#: Parents before children, so the foreign keys hold as the rows arrive.
TABLES_IN_ORDER = ("departments", "users", "cases", "case_documents", "case_runs", "case_events", "audit_log",
                   "login_attempts", "gpf_cases", "gpf_documents", "case_rounds", "case_round_requests",
                   "case_round_checks", "run_timings")


def import_sqlite(source: Path | str, *, replace: bool = False, conn: Connection | None = None) -> dict[str, int]:
    """Copy every row of a SQLite database (the trial's ``portal.sqlite3``) into the PostgreSQL
    database ``connect()`` opens, table by table in foreign-key order, in one transaction.

    The target must be migrated and empty; ``replace`` empties it first (TRUNCATE, which the
    append-only triggers do not stop). ``schema_migrations`` is not copied: the target records its
    own. Returns rows copied per table.
    """
    own = conn is None
    conn = conn or connect()
    if dbcore.backend_of(conn) != "postgres":
        raise RuntimeError("import-sqlite copies into PostgreSQL; set PENSION_DATABASE_URL")
    src = sqlite3.connect(f"file:{Path(source)}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        have_src = dbcore.table_names(src)
        have_dst = dbcore.table_names(conn)
        tables = [t for t in TABLES_IN_ORDER if t in have_src and t in have_dst]
        missing = [t for t in TABLES_IN_ORDER if t in have_src and t not in have_dst]
        if missing:
            raise RuntimeError(f"target lacks {missing}; run migrate first")
        counts: dict[str, int] = {}
        with transaction(conn):
            if replace:
                conn.execute("TRUNCATE " + ", ".join(reversed(tables)) + " RESTART IDENTITY CASCADE")
            else:
                for t in tables:
                    if conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone():
                        raise RuntimeError(f"target table {t} already has rows; use --replace to empty the target first")
            for t in tables:
                src_cols = [r["name"] for r in src.execute(f"PRAGMA table_info({t})")]
                dst_cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}
                cols = [c for c in src_cols if c in dst_cols]
                sql = f"INSERT INTO {t}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
                rows = [tuple(r[c] for c in cols) for r in src.execute(f"SELECT {', '.join(cols)} FROM {t}")]
                for i in range(0, len(rows), 500):
                    conn.executemany(sql, rows[i:i + 500])
                counts[t] = len(rows)
            if "run_timings" in tables and counts["run_timings"]:
                conn.execute("SELECT setval(pg_get_serial_sequence('run_timings', 'id'), "
                             "(SELECT MAX(id) FROM run_timings))")
        return counts
    finally:
        src.close()
        if own:
            conn.close()


def seed(conn: Connection | None = None, *, quiet: bool = False) -> dict:
    """Departments, one officer per department, the AG users; the AG Upload retirement. Idempotent.

    Inserts what is missing and changes nothing already present -- except the department rows'
    portal particulars (slug, theme, port, name), which follow the config file, and the retired
    AG Upload account, whose records move to the department's own officer.
    """
    from api import passwords, settings
    from api.auth import hash_password
    from api.departments import DEPARTMENTS, LEGACY_DEPARTMENT, RETIRED_CODES, portal_for

    shared = SEED_PASSWORD
    if shared and settings.production():
        # One password for everyone is the trial's convenience and production's first hole.
        print("[db] PENSION_SEED_PASSWORD is ignored in production; seeded accounts get generated passwords",
              file=sys.stderr)
        shared = None
    must_change = 1 if settings.force_password_change() else 0
    own = conn is None
    conn = conn or connect()
    try:
        created: list[dict] = []
        with transaction(conn):
            active = {d.code for d in DEPARTMENTS} | {LEGACY_DEPARTMENT[0]}
            for d in DEPARTMENTS:
                conn.execute(
                    "INSERT INTO departments(code, name, digital, active, slug, is_police, theme, port, pension_section) "
                    "VALUES (?, ?, 1, 1, ?, ?, ?, ?, ?) ON CONFLICT(code) DO UPDATE SET name = excluded.name, "
                    "digital = 1, active = 1, slug = excluded.slug, is_police = excluded.is_police, "
                    "theme = excluded.theme, port = excluded.port, pension_section = excluded.pension_section",
                    (d.code, d.name, d.slug, int(d.is_police), d.theme, d.port, d.pension_section))
            code, name, _ = LEGACY_DEPARTMENT
            conn.execute("INSERT OR IGNORE INTO departments(code, name, digital, active) VALUES (?, ?, 0, 1)", (code, name))
            for code, name in RETIRED_CODES.items():
                conn.execute("INSERT OR IGNORE INTO departments(code, name, digital, active) VALUES (?, ?, 0, 0)", (code, name))
            # Anything else on the table that is not on the list has no portal: inactive, kept for its cases.
            placeholders = ",".join("?" * len(active))
            conn.execute(f"UPDATE departments SET active = 0 WHERE code NOT IN ({placeholders})", tuple(active))

            for old_name, new_name in RENAMED_LOGINS.items():
                if (conn.execute("SELECT 1 FROM users WHERE username = ?", (old_name,)).fetchone()
                        and not conn.execute("SELECT 1 FROM users WHERE username = ?", (new_name,)).fetchone()):
                    conn.execute("UPDATE users SET username = ?, token_version = token_version + 1, updated_at = ? "
                                 "WHERE username = ?", (new_name, now(), old_name))
                    if not quiet:
                        print(f"[db] renamed the shared login {old_name!r} to {new_name!r} (C1); its sessions were ended",
                              file=sys.stderr)
            for username, display, role, dept in seed_users():
                if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                    continue
                password = shared or passwords.generate()
                stamp = now()
                conn.execute(
                    "INSERT INTO users(id, username, display_name, password_hash, role, "
                    "department_code, active, token_version, must_change_password, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?)",
                    (new_id(), username, display, hash_password(password), role, dept, must_change, stamp, stamp))
                created.append({"portal": portal_for(role, dept) or "", "department": _dept_name(conn, dept),
                                "username": username, "password": password, "role": role,
                                "department_code": dept or ""})
            created += _insert_ag_officers(conn, shared, must_change=must_change)
            retire_desk_logins(conn, quiet=quiet)
            _retire_ag_upload(conn)
        if created:
            _record_credentials(created)
            if not quiet:
                print(f"[db] seeded {len(created)} user(s); passwords in {CREDENTIALS_CSV}"
                      + (" (all PENSION_SEED_PASSWORD)" if shared else ""), file=sys.stderr)
        elif CREDENTIALS_CSV.exists() and not CREDENTIALS_HTML.exists():
            render_credentials_html()
        return {"users_created": [c["username"] for c in created]}
    finally:
        if own:
            conn.close()


def _insert_ag_officers(conn: Connection, shared: str | None, *, must_change: int) -> list[dict]:
    """The named wing officers the office gave us, created once each. Returns what was created.

    One account per person (13 Oct 2026). Several Senior Auditors share a wing and sign in from
    different PCs at the same time; nothing here or in ``api.auth`` ends one session when another
    begins, so they do not displace each other. The desk logins they replace are closed by
    ``retire_desk_logins`` once these exist, never deleted.
    """
    from api import passwords
    from api.auth import hash_password
    created: list[dict] = []
    for o in load_ag_officers():
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (o["username"],)).fetchone():
            continue
        # One password each unless the trial sets a shared one, exactly as the rest of the seed.
        password = shared or passwords.generate()
        stamp = now()
        conn.execute(
            "INSERT INTO users(id, username, display_name, password_hash, role, department_code, pension_wing, "
            "active, token_version, must_change_password, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?, 1, 1, ?, ?, ?)",
            (new_id(), o["username"], o["display_name"], hash_password(password), o["role"],
             o["pension_wing"], must_change, stamp, stamp))
        created.append({"portal": "ag", "department": f"Office of the Accountant General Punjab \u00b7 {o['pension_wing']}",
                        "username": o["username"], "password": password, "role": o["role"],
                        "department_code": ""})
    return created


def retire_desk_logins(conn: Connection, *, quiet: bool = True) -> list[str]:
    """Close the shared desk logins a named officer has taken over. Returns what was closed.

    sa.pension1 ... ao.pension5 were one login per tier per wing, shared by everyone at that desk
    (9 Oct 2026). They are deactivated, never deleted: ``cases.created_by`` references them, and
    every case event and audit row they wrote keeps their name and role, so the history still
    reads correctly. Bumping ``token_version`` ends any session still open on them.

    A desk login is closed only once an ACTIVE named officer holds the same role in the same
    wing, so a wing is never left without anyone who can sign in -- which is why this runs with
    the seed, after the roster is created, and not as a migration before it.
    """
    from api.departments import PENSION_SECTION_ORDER
    closed: list[str] = []
    for n, wing in enumerate(PENSION_SECTION_ORDER, start=1):
        for short, role, _label in WING_TIER_LOGINS:
            username = f"{short}.pension{n}"
            row = conn.execute("SELECT 1 FROM users WHERE username = ? AND active = 1", (username,)).fetchone()
            if row is None:
                continue
            taken_over = conn.execute(
                "SELECT 1 FROM users WHERE role = ? AND pension_wing = ? AND active = 1 AND username <> ?",
                (role, wing, username)).fetchone()
            if taken_over is None:
                continue                      # nobody has taken this desk over yet; leave it open
            conn.execute("UPDATE users SET active = 0, token_version = token_version + 1, updated_at = ? "
                         "WHERE username = ?", (now(), username))
            closed.append(username)
    if closed and not quiet:
        print(f"[db] closed {len(closed)} shared desk login(s) now held by named officers: "
              + ", ".join(closed), file=sys.stderr)
    return closed


def seed_ag_officers(password: str | None = None, conn: Connection | None = None) -> list[str]:
    """``config/ag_officers.json`` as accounts, on ``password`` (the seed password by default).

    Idempotent: an account that exists is left exactly as it is, password included.
    """
    from api import settings
    own = conn is None
    conn = conn or connect()
    try:
        with transaction(conn):
            created = _insert_ag_officers(conn, password or SEED_PASSWORD or None,
                                          must_change=1 if settings.force_password_change() else 0)
            retire_desk_logins(conn, quiet=False)
        if created:
            _record_credentials(created)
        return [c["username"] for c in created]
    finally:
        if own:
            conn.close()


#: Senior Auditor, then Assistant AO, then AO: the order a case climbs, so the sheet reads the
#: way the wing works.
_ROLE_RANK = {"AG_SENIOR_AUDITOR": 0, "AG_ASSISTANT_AO": 1, "AG_AO": 2}


def _role_rank(role: str) -> int:
    return _ROLE_RANK.get(role, 9)


def _role_words(role: str) -> str:
    """The office's name for a role on the sign-in sheet ("Senior Auditor", not "Ag Senior Auditor")."""
    from api.departments import ROLE_LABELS
    return ROLE_LABELS.get(role) or role.replace("_", " ").title()


def _dept_name(conn: Connection, code: str | None) -> str:
    if not code:
        return "Office of the Accountant General Punjab"
    row = conn.execute("SELECT name FROM departments WHERE code = ?", (code,)).fetchone()
    return row["name"] if row else code


def _retire_ag_upload(conn: Connection) -> None:
    """Move a retired account's records to each case's own department officer, then remove the
    account. Runs inside the seed's transaction; a no-op once done."""
    for username in RETIRED_USERS:
        old = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if old is None:
            continue
        for case in conn.execute("SELECT id, department_code FROM cases WHERE created_by = ?", (old["id"],)):
            officer = conn.execute(
                "SELECT id FROM users WHERE role = 'DEPT_OFFICER' AND department_code = ? AND active = 1 "
                "AND username NOT IN (%s) ORDER BY created_at LIMIT 1" % ",".join("?" * len(RETIRED_USERS)),
                (case["department_code"], *RETIRED_USERS)).fetchone()
            if officer is None:
                # A department with no officer on the system (a retired code): the administrator holds it.
                officer = conn.execute("SELECT id FROM users WHERE role = 'ADMIN' ORDER BY created_at LIMIT 1").fetchone()
            conn.execute("UPDATE cases SET created_by = ? WHERE id = ?", (officer["id"], case["id"]))
            conn.execute("UPDATE case_documents SET uploaded_by = ? WHERE case_id = ? AND uploaded_by = ?",
                         (officer["id"], case["id"], old["id"]))
            conn.execute("UPDATE case_runs SET started_by = ? WHERE case_id = ? AND started_by = ?",
                         (officer["id"], case["id"], old["id"]))
        # Documents or runs on other cases (none expected) go to the administrator.
        admin = conn.execute("SELECT id FROM users WHERE role = 'ADMIN' ORDER BY created_at LIMIT 1").fetchone()
        if admin:
            conn.execute("UPDATE case_documents SET uploaded_by = ? WHERE uploaded_by = ?", (admin["id"], old["id"]))
            conn.execute("UPDATE case_runs SET started_by = ? WHERE started_by = ?", (admin["id"], old["id"]))
            conn.execute("UPDATE cases SET created_by = ? WHERE created_by = ?", (admin["id"], old["id"]))
        conn.execute("DELETE FROM users WHERE id = ?", (old["id"],))


# -- the credentials sheet ----------------------------------------------------------------------

def public_host() -> str:
    """The address the office reaches this server at: PENSION_PUBLIC_HOST, else the LAN address."""
    given = os.environ.get("PENSION_PUBLIC_HOST")
    if given:
        return given
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        host = s.getsockname()[0]
        s.close()
        return host
    except OSError:
        return "localhost"


def _record_credentials(created: list[dict]) -> None:
    """Append this run's new passwords to the CSV (owner-readable only) and re-render the HTML."""
    import csv
    import io
    from api.departments import portal_url
    host = public_host()
    buf = io.StringIO()
    w = csv.writer(buf)
    if not CREDENTIALS_CSV.exists():
        w.writerow(["portal", "department", "username", "password", "port", "url", "role", "created_at"])
    for c in created:
        url = portal_url(c["portal"], host) if c["portal"] else ""
        port = url.rsplit(":", 1)[-1].rstrip("/") if url else ""
        w.writerow([c["portal"], c["department"], c["username"], c["password"], port, url, c["role"], now()])
    from api import passwords
    passwords.write_private(CREDENTIALS_CSV, buf.getvalue(), append=True)
    render_credentials_html()


def _credentials_rows(conn: Connection | None = None) -> list[dict]:
    import csv
    if not CREDENTIALS_CSV.exists():
        return []
    with open(CREDENTIALS_CSV, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    # The newest row per username wins (a reset appends a new one); accounts since removed drop out.
    latest: dict[str, dict] = {}
    for r in rows:
        latest[r["username"]] = r
    own = conn is None
    conn = conn or connect()
    try:
        # The person's own name and wing come from the account, not from the CSV: the sheet names
        # the officer, and the CSV was written before there were named officers to name.
        live = {u["username"]: u for u in
                conn.execute("SELECT username, display_name, pension_wing, role FROM users WHERE active = 1")}
    finally:
        if own:
            conn.close()
    from api.departments import AG_PORTAL_PORT, SINGLE_PORTAL
    rows_out = []
    for u, r in latest.items():
        if u not in live:
            continue
        account = live[u]
        r = {**r, "display_name": account["display_name"], "wing": account["pension_wing"] or "",
             "role": account["role"] or r.get("role", "")}
        if SINGLE_PORTAL and r.get("url"):
            host = r["url"].split("//", 1)[-1].split(":")[0]
            r = {**r, "port": str(AG_PORTAL_PORT), "url": f"http://{host}:{AG_PORTAL_PORT}/"}
        rows_out.append(r)
    return sorted(rows_out, key=lambda r: (r["department"].lower(), r["username"]))


def render_credentials_html() -> Path:
    """The office's sign-in sheet: every login, searchable, sorted by department. Never served."""
    import html
    from api import passwords
    from api.departments import PENSION_SECTION_ORDER
    rows = _credentials_rows()

    # Grouped by wing, the office's own officers first and in wing order, then the AG's desk,
    # then the departments (13 Oct 2026). The wing is the heading, so the row says who the
    # person is rather than repeating it.
    order = {w: i for i, w in enumerate(PENSION_SECTION_ORDER)}

    def group_of(r: dict) -> str:
        return r.get("wing") or r.get("department") or "Other"

    def sort_key(r: dict) -> tuple:
        wing = r.get("wing") or ""
        return (0, order.get(wing, 99), wing, _role_rank(r["role"]), r["display_name"].lower()) if wing \
            else (1, 0, group_of(r).lower(), 0, r["display_name"].lower())

    body, last = [], None
    for r in sorted(rows, key=sort_key):
        group = group_of(r)
        if group != last:
            body.append(f'<tr class="grp"><th colspan="5">{html.escape(group)}</th></tr>')
            last = group
        body.append(
            f"<tr><td>{html.escape(r['display_name'])}</td>"
            f"<td>{html.escape(_role_words(r['role']))}</td>"
            f"<td><code>{html.escape(r['username'])}</code></td>"
            f"<td><code>{html.escape(r['password'])}</code></td>"
            f"<td><a href=\"{html.escape(r['url'])}\">{html.escape(r['url'])}</a></td></tr>")
    tr = "\n".join(body)
    doc = f"""<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pension portals — sign-in credentials (confidential)</title>
<style>
body{{margin:0;font:14px/1.5 "Segoe UI",system-ui,Arial,sans-serif;color:#1F2937;background:#F4F7F4}}
header{{background:#1B4332;color:#fff;padding:18px 24px}} h1{{margin:0;font-size:20px}} header p{{margin:4px 0 0;opacity:.85;font-size:13px}}
main{{max-width:1200px;margin:0 auto;padding:20px 16px 40px}}
input{{width:100%;max-width:420px;padding:10px 12px;border:1px solid #CFD8D2;border-radius:8px;font-size:15px}}
table{{border-collapse:collapse;width:100%;background:#fff;border:1px solid #E2E8E3;border-radius:12px;overflow:hidden;margin-top:14px}}
th,td{{padding:8px 12px;border-top:1px solid #E2E8E3;text-align:left;vertical-align:top}} th{{background:#EDF4EE;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#6B7280;border-top:none;cursor:pointer}}
code{{font-family:Consolas,Menlo,monospace;background:#F1F4F1;padding:1px 6px;border-radius:6px}}
.warn{{background:#FFF6E6;border:1px solid #F0D9AE;border-radius:10px;padding:10px 14px;margin-top:14px;font-size:13px}}
.n{{color:#6B7280;font-size:12px;margin-left:8px}}
tr.grp th{{background:#1B4332;color:#fff;font-size:12px;letter-spacing:.06em;cursor:default}}
</style></head><body>
<header><h1>Pension portals — sign-in credentials</h1><p>Government of the Punjab · Accountant General Office, Lahore · CONFIDENTIAL — for the office's own use; not published anywhere.</p></header>
<main>
<input id="q" placeholder="Search a name, wing, role or username" autofocus> <span class="n" id="count"></span>
<div class="warn">Everyone signs in at the same address with their own account; what they see follows from the account. Passwords can be reset with <code>python3 -m api.db reset-department-password &lt;username&gt;</code>; this file is regenerated from <code>credentials.csv</code>.</div>
<div class="warn"><strong>How a case moves (pension and GP Fund).</strong> The department's DDO files the case and submits it. The Office of the Accountant General's reviewer verifies it with AI, reads the findings and the list of any missing or defective documents, and decides: approve, return to the department with the documents named, ask for documents, or reject &mdash; each with a remark. <strong>Nothing is approved or returned automatically</strong> (decisions of 7 and 9 October 2026); a return made inside the GP Fund module's screens is recorded there, and the case itself is returned by the reviewer.</div>
<table><thead><tr><th>Name</th><th>Role</th><th>Username</th><th>Password</th><th>Portal</th></tr></thead>
<tbody id="rows">
{tr}
</tbody></table>
</main>
<script>
var q=document.getElementById('q'),all=[].slice.call(document.querySelectorAll('#rows tr')),count=document.getElementById('count');
var people=all.filter(function(r){{return !r.classList.contains('grp');}});
function filter(){{
  var t=q.value.trim().toLowerCase(),n=0,group=null,shown=0;
  function closeGroup(){{ if(group) group.style.display=shown?'':'none'; }}
  all.forEach(function(r){{
    if(r.classList.contains('grp')){{ closeGroup(); group=r; shown=0; return; }}
    var hay=r.textContent.toLowerCase()+' '+(group?group.textContent.toLowerCase():'');
    var show=!t||hay.indexOf(t)>-1; r.style.display=show?'':'none'; if(show){{n++;shown++;}}
  }});
  closeGroup();
  count.textContent=n+' of '+people.length;
}}
q.addEventListener('input',filter);filter();
</script></body></html>"""
    passwords.write_private(CREDENTIALS_HTML, doc)
    return CREDENTIALS_HTML


def reset_department_password(slug: str, conn: Connection | None = None) -> str | None:
    """A new generated password for one department's officer (or any username); recorded on the sheet."""
    from api import passwords, settings
    from api.auth import hash_password
    from api.departments import portal_for
    own = conn is None
    conn = conn or connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (slug,)).fetchone()
        if row is None:
            return None
        password = passwords.generate()
        with transaction(conn):
            conn.execute("UPDATE users SET password_hash = ?, token_version = token_version + 1, "
                         "must_change_password = ?, updated_at = ? WHERE id = ?",
                         (hash_password(password), int(settings.force_password_change()), now(), row["id"]))
        _record_credentials([{"portal": portal_for(row["role"], row["department_code"]) or "",
                              "department": _dept_name(conn, row["department_code"]), "username": row["username"],
                              "password": password, "role": row["role"], "department_code": row["department_code"] or ""}])
        return password
    finally:
        if own:
            conn.close()


def set_all_passwords(password: str, conn: Connection | None = None) -> int:
    """One password for every live account (the office asked for ``1234`` while the system is being
    tried out); every existing session ends, and the sign-in sheet is rewritten to match.
    Refused in production."""
    from api import settings
    from api.auth import hash_password
    from api.departments import portal_for
    if settings.production():
        raise PermissionError("set-all-passwords gives every account one password; it is refused in production")
    own = conn is None
    conn = conn or connect()
    try:
        users = conn.execute("SELECT * FROM users WHERE active = 1 ORDER BY username").fetchall()
        with transaction(conn):
            for u in users:
                conn.execute("UPDATE users SET password_hash = ?, token_version = token_version + 1, updated_at = ? WHERE id = ?",
                             (hash_password(password), now(), u["id"]))
        _record_credentials([{"portal": portal_for(u["role"], u["department_code"]) or "",
                              "department": _dept_name(conn, u["department_code"]), "username": u["username"],
                              "password": password, "role": u["role"], "department_code": u["department_code"] or ""}
                             for u in users])
        return len(users)
    finally:
        if own:
            conn.close()


def refresh_credentials(password: str, conn: Connection | None = None) -> list[str]:
    """Bring the sign-in sheet back in step with the accounts, without touching any account.

    The sheet is written when passwords are generated or set; after the trial's accounts were
    put on one password by hand, the sheet still showed the generated ones and sent the first
    reader to a locked account (6 Oct 2026). This checks every active account against the
    password given and records a sheet row for each that matches. Nothing is changed in the
    database and no session ends. Returns the usernames recorded.
    """
    from api.auth import verify_password
    from api.departments import portal_for
    own = conn is None
    conn = conn or connect()
    try:
        users = conn.execute("SELECT * FROM users WHERE active = 1 ORDER BY username").fetchall()
        matched = [u for u in users if verify_password(password, u["password_hash"])]
        if matched:
            _record_credentials([{"portal": portal_for(u["role"], u["department_code"]) or "",
                                  # A wing officer's "department" cell names the wing (9 Oct 2026).
                                  "department": _dept_name(conn, u["department_code"]) + (
                                      f" · {u['pension_wing']}" if "pension_wing" in u.keys() and u["pension_wing"] else ""),
                                  "username": u["username"],
                                  "password": password, "role": u["role"], "department_code": u["department_code"] or ""}
                                 for u in matched])
        return [u["username"] for u in matched]
    finally:
        if own:
            conn.close()


def reset_password(username: str, password: str, conn: Connection | None = None) -> bool:
    """Set a user's password from the command line; their existing tokens stop working.

    Where the deployment forces it (production), the user must replace it at next sign-in."""
    from api import settings
    from api.auth import hash_password, password_problem

    problem = password_problem(password, username)
    if problem:
        raise ValueError(problem)
    own = conn is None
    conn = conn or connect()
    try:
        with transaction(conn):
            cur = conn.execute(
                "UPDATE users SET password_hash = ?, token_version = token_version + 1, "
                "must_change_password = ?, updated_at = ? WHERE username = ?",
                (hash_password(password), int(settings.force_password_change()), now(), username))
        return cur.rowcount == 1
    finally:
        if own:
            conn.close()


#: The tier names the command line takes, and the roles they are (C3, 9 Oct 2026).
TIER_ARGS = {"senior-auditor": "AG_SENIOR_AUDITOR", "assistant-ao": "AG_ASSISTANT_AO", "ao": "AG_AO"}


def seed_wing_tiers(password: str | None = None, conn: Connection | None = None) -> list[str]:
    """The trial's tier accounts: sa.pension1, aao.pension1, ao.pension1 ... ao.pension5, one per tier
    per wing, on ``password`` (the seed password by default). Accounts that exist are left alone;
    the usernames created are returned. Decision of 9 Oct 2026: the office starts the wings on desk
    logins and gives each officer a named account from the Users screen when the list arrives."""
    from api import settings
    from api.auth import hash_password
    from api.departments import PENSION_SECTION_ORDER
    pw = password or SEED_PASSWORD
    own = conn is None
    conn = conn or connect()
    created: list[str] = []
    try:
        with transaction(conn):
            for n, wing in enumerate(PENSION_SECTION_ORDER, start=1):
                for short, role, label in WING_TIER_LOGINS:
                    username = f"{short}.pension{n}"
                    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                        continue
                    stamp = now()
                    conn.execute(
                        "INSERT INTO users(id, username, display_name, password_hash, role, department_code, pension_wing, active, "
                        "token_version, must_change_password, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, ?, 1, 1, ?, ?, ?)",
                        (new_id(), username, f"{label}, {wing}", hash_password(pw), role, wing,
                         1 if settings.force_password_change() else 0, stamp, stamp))
                    created.append(username)
        return created
    finally:
        if own:
            conn.close()


def add_reviewer(username: str, display_name: str, *, dag: bool = False, password: str | None = None,
                 tier: str | None = None, wing: str | None = None, conn: Connection | None = None) -> str:
    """Create a named AG account and return its password: a tier officer (``tier`` one of
    senior-auditor / assistant-ao / ao, with the pension ``wing`` Pension-I .. Pension-V), or the
    Deputy AG with ``dag``. The legacy AG_REVIEWER role is not created any more (Q5).

    The way the office adds its officers from the command line (the Users screen does the same).
    A generated password unless one is given; in production it must be changed at first sign-in."""
    from api.departments import PENSION_SECTION_ORDER
    if dag and tier:
        raise ValueError("an account is the Deputy AG or a tier officer, not both")
    if not dag:
        if tier not in TIER_ARGS:
            raise ValueError("name the tier: --tier senior-auditor | assistant-ao | ao (or --dag for the Deputy AG)")
        if wing not in PENSION_SECTION_ORDER:
            raise ValueError(f"a tier officer needs a pension wing: --wing one of {', '.join(PENSION_SECTION_ORDER)}")
    role = "AG_DAG" if dag else TIER_ARGS[tier]
    from api import passwords, settings
    from api.auth import hash_password, password_problem
    username = (username or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9._-]{2,40}", username):
        raise ValueError("username: lower-case letters, digits, dots, hyphens; 3 to 41 characters")
    if username in SHARED_LOGINS or not display_name.strip():
        raise ValueError("a reviewer's login carries the officer's own name (decision C1)")
    pw = password or passwords.generate()
    if password and password_problem(password, username):
        raise ValueError(password_problem(password, username))
    own = conn is None
    conn = conn or connect()
    try:
        with transaction(conn):
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise ValueError(f"a user {username!r} already exists")
            stamp = now()
            conn.execute(
                "INSERT INTO users(id, username, display_name, password_hash, role, department_code, pension_wing, active, "
                "token_version, must_change_password, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, ?, 1, 1, ?, ?, ?)",
                (new_id(), username, display_name.strip(), hash_password(pw), role, None if dag else wing,
                 1 if settings.force_password_change() else 0, stamp, stamp))
        return pw
    finally:
        if own:
            conn.close()


def forget_credentials() -> list[str]:
    """Delete the plaintext sign-in sheet (CSV and HTML). Returns what was removed."""
    removed = []
    for path in (CREDENTIALS_CSV, CREDENTIALS_HTML):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return removed


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "info":
        print(f"engine:   {backend()}")
        print(f"database: {describe()}")
        try:
            conn = connect()
            try:
                versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] \
                    if "schema_migrations" in dbcore.table_names(conn) else []
                counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                          for t in TABLES_IN_ORDER if t in dbcore.table_names(conn)}
            finally:
                conn.close()
        except Exception as exc:                      # noqa: BLE001 -- the answer is the finding
            print(f"cannot connect: {type(exc).__name__}: {exc}")
            return 1
        pending = [p.stem for p in sorted(MIGRATIONS.glob("*.sql")) if p.stem not in versions]
        print(f"migrations: {len(versions)} applied" + (f", pending {pending}" if pending else ""))
        for t, n in counts.items():
            print(f"  {t:<22}{n:>8}")
        return 0
    if cmd == "migrate":
        applied = migrate()
        print(f"applied {applied or 'nothing new'} to {describe()}")
        return 0
    if cmd == "seed":
        migrate()
        result = seed()
        print(f"seeded {describe()}: {result}")
        return 0
    if cmd == "import-sqlite" and len(argv) >= 3:
        migrate()
        try:
            counts = import_sqlite(argv[2], replace="--replace" in argv[3:])
        except RuntimeError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        for t, n in counts.items():
            print(f"  {t:<22}{n:>8}")
        print(f"copied {sum(counts.values())} rows from {argv[2]} into {describe()}")
        return 0
    if cmd == "drop-test-schemas":
        names = drop_test_schemas(every=True)
        print(f"dropped {len(names)} test schema(s)" + (" (PENSION_TEST_DATABASE_URL is not set)" if not TEST_DATABASE_URL else ""))
        return 0
    if cmd == "credentials":
        migrate()
        print(render_credentials_html())
        return 0
    if cmd == "reset-department-password" and len(argv) >= 3:
        migrate()
        pw = reset_department_password(argv[2])
        print(f"new password for {argv[2]}: {pw}" if pw else f"no user {argv[2]!r}")
        return 0 if pw else 1
    if cmd == "set-all-passwords" and len(argv) >= 3:
        migrate()
        try:
            n = set_all_passwords(argv[2])
        except PermissionError as exc:
            print(exc)
            return 1
        print(f"{n} accounts now use the given password; sheet: {CREDENTIALS_HTML}")
        return 0
    if cmd == "refresh-credentials" and len(argv) >= 3:
        migrate()
        names = refresh_credentials(argv[2])
        print(f"{len(names)} account(s) are on the given password; sheet rewritten: {CREDENTIALS_HTML}")
        return 0 if names else 1
    if cmd == "reset-password" and len(argv) >= 3:
        import getpass
        password = argv[3] if len(argv) > 3 else getpass.getpass("new password: ")
        migrate()
        try:
            ok = reset_password(argv[2], password)
        except ValueError as exc:
            print(exc)
            return 1
        print("done" if ok else f"no user {argv[2]!r}")
        return 0 if ok else 1
    if cmd == "add-reviewer" and len(argv) >= 4:
        migrate()
        rest = argv[4:]
        dag = "--dag" in rest
        tier = wing = None
        given: list[str] = []
        i = 0
        while i < len(rest):
            if rest[i] == "--dag":
                pass
            elif rest[i] == "--tier" and i + 1 < len(rest):
                tier = rest[i + 1]; i += 1
            elif rest[i] == "--wing" and i + 1 < len(rest):
                wing = rest[i + 1]; i += 1
            else:
                given.append(rest[i])
            i += 1
        try:
            pw = add_reviewer(argv[2], argv[3], dag=dag, tier=tier, wing=wing, password=given[0] if given else None)
        except ValueError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(f"created {argv[2]} ({'AG_DAG' if dag else TIER_ARGS[tier] + ', ' + wing}); password: {pw}")
        return 0
    if cmd == "seed-wing-tiers":
        migrate()
        made = seed_wing_tiers(argv[2] if len(argv) > 2 else None)
        print(f"created {len(made)} tier account(s): {', '.join(made) or 'none (all present)'}")
        return 0
    if cmd == "forget-credentials":
        removed = forget_credentials()
        print("removed " + ", ".join(removed) if removed else "no credentials sheet to remove")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
