"""The shared database for the multi-department case system: SQLite, one file, WAL.

Standard library only. The build spec (§4) names PostgreSQL for cases, reference data and
append-only audit; on this box neither Postgres client libraries nor SQLAlchemy are installed
and there is no pip, so the pilot runs on ``sqlite3`` with the schema written to port. The
migrations are plain SQL files in ``api/migrations/``, applied in order and recorded in
``schema_migrations``; the same files go under ``infra/postgres/init`` when that day comes.

Who writes: request threads and the run reconciler (``api.case_runs``). The pipeline thread
never touches the database -- it writes its artefacts as it always has, and the reconciler
reads them. The GP Fund module (GP/backend, its own process on :8201) keeps its cases in the
same file, in ``gpf_cases`` and ``gpf_documents`` (migration 0005, 29 Sep 2026), and applies
that migration itself if it starts first. WAL mode plus a busy timeout is enough for that traffic.

    python3 -m api.db migrate            # apply migrations
    python3 -m api.db seed               # departments, one officer per department, AG users (idempotent)
    python3 -m api.db credentials        # rebuild artifacts/credentials/credentials.html from the CSV
    python3 -m api.db reset-department-password <slug>   # new generated password for one department
    python3 -m api.db reset-password <username> [<new password>]
    python3 -m api.db forget-credentials   # delete the plaintext sheet once passwords are handed out

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

import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = Path(__file__).resolve().parent / "migrations"

#: Overridable for tests (``mock.patch.object(db, "DB_PATH", tmp)``) and deployments
#: (``PENSION_DB``). Kept beside the run artefacts so one backup covers both.
DB_PATH = Path(os.environ.get("PENSION_DB") or ROOT / "artifacts" / "portal.sqlite3")

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
    ("ag.reviewer", "Syed Haider (AG Punjab, Pension Wing)", "AG_REVIEWER"),
    ("admin", "System Administrator", "ADMIN"),
)

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


def new_id() -> str:
    return uuid.uuid4().hex


def connect(path: Path | None = None) -> sqlite3.Connection:
    """A connection with the pragmas this application relies on. Rows come back as sqlite3.Row."""
    target = Path(path or DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` ... ``COMMIT``, rolled back on any exception.

    IMMEDIATE takes the write lock up front, so two request threads changing the same case
    queue behind each other instead of both reading the old status and both writing.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _apply_migration(conn: sqlite3.Connection, script: str) -> None:
    """Run a migration statement by statement (triggers span several semicolons, so statements
    are cut where sqlite says one is complete); a column that already exists is not an error."""
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


def migrate(conn: sqlite3.Connection | None = None) -> list[str]:
    """Apply every migration file not yet recorded. Returns the versions applied."""
    own = conn is None
    conn = conn or connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                     "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        applied: list[str] = []
        for path in sorted(MIGRATIONS.glob("*.sql")):
            version = path.stem
            if version in done:
                continue
            # executescript issues its own COMMIT first, so it cannot sit inside transaction().
            # CREATE statements are IF NOT EXISTS; an ALTER TABLE ADD COLUMN has no such form,
            # so a column a half-applied run already added is skipped rather than fatal.
            _apply_migration(conn, path.read_text(encoding="utf-8"))
            # OR IGNORE: the GP Fund module records 0005 itself (gpf/store.py), and the two
            # starting together on a fresh database must not abort the migrations after it.
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                         (version, now()))
            applied.append(version)
        return applied
    finally:
        if own:
            conn.close()


def seed(conn: sqlite3.Connection | None = None, *, quiet: bool = False) -> dict:
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


def _dept_name(conn: sqlite3.Connection, code: str | None) -> str:
    if not code:
        return "Accountant General Punjab"
    row = conn.execute("SELECT name FROM departments WHERE code = ?", (code,)).fetchone()
    return row["name"] if row else code


def _retire_ag_upload(conn: sqlite3.Connection) -> None:
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


def _credentials_rows(conn: sqlite3.Connection | None = None) -> list[dict]:
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
        live = {u["username"] for u in conn.execute("SELECT username FROM users WHERE active = 1")}
    finally:
        if own:
            conn.close()
    from api.departments import AG_PORTAL_PORT, SINGLE_PORTAL
    rows_out = []
    for u, r in latest.items():
        if u not in live:
            continue
        if SINGLE_PORTAL and r.get("url"):
            host = r["url"].split("//", 1)[-1].split(":")[0]
            r = {**r, "port": str(AG_PORTAL_PORT), "url": f"http://{host}:{AG_PORTAL_PORT}/"}
        rows_out.append(r)
    return sorted(rows_out, key=lambda r: (r["department"].lower(), r["username"]))


def render_credentials_html() -> Path:
    """The office's sign-in sheet: every login, searchable, sorted by department. Never served."""
    import html
    from api import passwords
    rows = _credentials_rows()
    tr = "\n".join(
        f"<tr><td>{html.escape(r['department'])}</td><td><code>{html.escape(r['username'])}</code></td>"
        f"<td><code>{html.escape(r['password'])}</code></td><td>{html.escape(r['port'])}</td>"
        f"<td><a href=\"{html.escape(r['url'])}\">{html.escape(r['url'])}</a></td>"
        f"<td>{html.escape(r['role'].replace('_', ' ').title())}</td></tr>"
        for r in rows)
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
</style></head><body>
<header><h1>Pension portals — sign-in credentials</h1><p>Government of the Punjab · Accountant General Office, Lahore · CONFIDENTIAL — for the office's own use; not published anywhere.</p></header>
<main>
<input id="q" placeholder="Search department, username or port" autofocus> <span class="n" id="count"></span>
<div class="warn">Everyone signs in at the same address with their own account; what they see follows from the account. Passwords can be reset with <code>python3 -m api.db reset-department-password &lt;username&gt;</code>; this file is regenerated from <code>credentials.csv</code>.</div>
<table><thead><tr><th>Department</th><th>Username</th><th>Password</th><th>Port</th><th>Portal</th><th>Role</th></tr></thead>
<tbody id="rows">
{tr}
</tbody></table>
</main>
<script>
var q=document.getElementById('q'),rows=[].slice.call(document.querySelectorAll('#rows tr')),count=document.getElementById('count');
function filter(){{var t=q.value.trim().toLowerCase(),n=0;rows.forEach(function(r){{var show=!t||r.textContent.toLowerCase().indexOf(t)>-1;r.style.display=show?'':'none';if(show)n++;}});count.textContent=n+' of '+rows.length;}}
q.addEventListener('input',filter);filter();
</script></body></html>"""
    passwords.write_private(CREDENTIALS_HTML, doc)
    return CREDENTIALS_HTML


def reset_department_password(slug: str, conn: sqlite3.Connection | None = None) -> str | None:
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


def set_all_passwords(password: str, conn: sqlite3.Connection | None = None) -> int:
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


def reset_password(username: str, password: str, conn: sqlite3.Connection | None = None) -> bool:
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
    if cmd == "migrate":
        applied = migrate()
        print(f"applied {applied or 'nothing new'} to {DB_PATH}")
        return 0
    if cmd == "seed":
        migrate()
        result = seed()
        print(f"seeded {DB_PATH}: {result}")
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
    if cmd == "forget-credentials":
        removed = forget_credentials()
        print("removed " + ", ".join(removed) if removed else "no credentials sheet to remove")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
