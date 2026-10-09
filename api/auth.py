"""Who is calling: username/password login, signed tokens, and the FastAPI dependencies.

Standard library for the passwords (``hashlib.scrypt``; nothing else is installed on this box)
and PyJWT for the tokens. A token carries the user's id, role, department and
``token_version``; every request re-reads the user row, so disabling a user or resetting their
password (which bumps the version) locks them out on their next request, not at expiry.

The token lives in the browser's ``localStorage`` and travels in ``Authorization: Bearer``.
Images and the live event stream cannot send headers from an ``<img>`` or ``EventSource``, so
those routes -- and only those -- also accept ``?token=``.

The old ``/api/*`` routes need the same token (``api.server``), and the desk they act at is
one the signed-in account holds (``api.desks.desk_for_account``).

An account whose password was set by someone else -- the seed, the administrator -- carries
``must_change_password`` where the deployment asks for it (``api.settings``). Such an account
may sign in, read who it is and change its password; every other route refuses it with 403
until it has.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, Query, Request

from api import db, settings
from api.departments import AG_PORTAL_PORT, AG_PORTAL_SLUG, BY_CODE, DEPARTMENT_NAMES, portal_for

#: Login rate limit: after this many failures a username is locked for LOCKOUT_SECONDS.
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60
#: And across usernames from one address, so a caller cannot try one password on all 88
#: accounts (password spraying). Generous: a department office signs in from one NAT address.
ADDRESS_MAX_FAILURES = 30
ADDRESS_LOCKOUT_SECONDS = 15 * 60

#: Passwords refused outright, and checked for at production start-up (``flag_weak_passwords``).
#: The trial's shared password heads the list.
WEAK_PASSWORDS = frozenset({
    "1234", "12345", "123456", "1234567", "12345678", "123456789", "1234567890", "password",
    "password1", "password123", "pension", "pension123", "admin", "admin123", "qwerty", "qwerty123",
    "abc123", "11111111", "00000000", "punjab", "punjab123", "lahore", "lahore123", "pakistan",
    "pakistan123", "welcome", "welcome1", "changeme", "letmein",
})

#: The routes an account that must change its password may still use.
PASSWORD_CHANGE_PATHS = ("/api/v2/auth/me", "/api/v2/auth/change-password")

TOKEN_TTL = timedelta(hours=12)
_SECRET_FILE = db.ROOT / "artifacts" / ".jwt_secret"


# -- passwords -------------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """``scrypt$<salt b64>$<hash b64>``. n=2^14, r=8, p=1: ~20 ms, the usual interactive setting."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest, expected)


def password_problem(password: str, username: str = "") -> str | None:
    """Why this password may not be used, or None. The same rule for every route that sets one."""
    if len(password) < settings.min_password_length():
        return f"the password must be at least {settings.min_password_length()} characters"
    folded = password.casefold()
    if folded in WEAK_PASSWORDS or folded.strip("0123456789!@#.") in WEAK_PASSWORDS:
        return "that password is too common; choose another"
    if username and username.casefold() in folded:
        return "the password may not contain the username"
    if len(set(password)) < 4:
        return "the password needs more than three different characters"
    return None


# -- tokens ------------------------------------------------------------------------------------

#: The signing key's floor in production: HS256 wants at least 32 bytes (RFC 7518 §3.2).
MIN_SECRET_LENGTH = 32

#: Values that are not secrets: deploy/pension.env.example ships CHANGE_ME, and a server left on
#: it signs sessions anyone who has read that file can forge (audit 6 Oct 2026, item 2).
_PLACEHOLDER_SECRETS = {"change_me", "changeme", "change-me", "secret", "test-secret", "password"}


class InsecureSecret(RuntimeError):
    """Production was asked to sign sessions with a missing, placeholder or short key."""


def production_secret_problem() -> str | None:
    """Why PENSION_JWT_SECRET is not fit for production, or None when it is."""
    given = os.environ.get("PENSION_JWT_SECRET", "").strip()
    if not given:
        return "PENSION_JWT_SECRET is not set"
    if given.lower() in _PLACEHOLDER_SECRETS or "change_me" in given.lower():
        return "PENSION_JWT_SECRET is still the placeholder from pension.env.example"
    if len(given) < MIN_SECRET_LENGTH:
        return f"PENSION_JWT_SECRET is {len(given)} characters; production needs at least {MIN_SECRET_LENGTH}"
    return None


def require_production_secret() -> None:
    problem = production_secret_problem()
    if problem:
        raise InsecureSecret(f"{problem}. Generate one with `openssl rand -base64 48` and set it in "
                             f"/etc/pension/pension.env (docs/DEPLOYMENT.md).")


def _secret() -> str:
    if settings.production():
        # Never sign or check a token with a key production would refuse, however we got here.
        require_production_secret()
    given = os.environ.get("PENSION_JWT_SECRET")
    if given:
        return given
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text().strip()
    _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(48)
    fd = os.open(_SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(value)
    return value


@dataclass(frozen=True)
class User:
    id: str
    username: str
    display_name: str
    role: str
    department_code: str | None
    active: bool
    token_version: int
    must_change_password: bool = False
    #: The pension wing (Pension-I .. V) a tier officer belongs to (C3, 9 Oct 2026); None otherwise.
    pension_wing: str | None = None

    @property
    def portal(self) -> str | None:
        return portal_for(self.role, self.department_code)

    def to_dict(self) -> dict:
        return {"id": self.id, "username": self.username, "display_name": self.display_name,
                "role": self.role, "department_code": self.department_code,
                "department_name": DEPARTMENT_NAMES.get(self.department_code or "", self.department_code),
                "pension_wing": self.pension_wing,
                "active": self.active, "portal": self.portal,
                "must_change_password": self.must_change_password}


def user_from_row(row: db.Row) -> User:
    keys = row.keys()
    return User(id=row["id"], username=row["username"], display_name=row["display_name"],
                role=row["role"], department_code=row["department_code"],
                active=bool(row["active"]), token_version=int(row["token_version"]),
                must_change_password=bool(row["must_change_password"]) if "must_change_password" in keys else False,
                pension_wing=row["pension_wing"] if "pension_wing" in keys else None)


def issue_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user.id, "role": user.role, "dept": user.department_code,
                       "portal": user.portal, "tv": user.token_version, "iat": now, "exp": now + TOKEN_TTL},
                      _secret(), algorithm="HS256")


#: The GP Fund frame's sign-in (api.v2 /auth/gpf-session): a token that opens /gpf/ and nothing else.
GPF_SCOPE = "gpf"
#: A short-lived token for the URLs a browser cannot send a header with -- page images,
#: signature crops, the event stream, document downloads (frontend review F10, 9 Oct 2026). GET
#: and HEAD only, 15 minutes, refused on every JSON route and every write. The session token
#: itself no longer needs to ride on an image URL into the browser's disk cache.
MEDIA_SCOPE = "media"
MEDIA_TOKEN_TTL = timedelta(minutes=15)
GPF_TOKEN_TTL = timedelta(hours=2)


def issue_scoped_token(user: User, scope: str, ttl: timedelta) -> str:
    """A token for one purpose. ``user_for_token`` refuses it anywhere but that purpose."""
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user.id, "role": user.role, "tv": user.token_version, "scope": scope,
                       "iat": now, "exp": now + ttl}, _secret(), algorithm="HS256")


class AuthError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


#: A hash to check an unknown username's password against, so a wrong name costs the same
#: time as a wrong password and the difference cannot be measured.
_DECOY_HASH = hash_password("decoy-" + secrets.token_hex(8))


def _attempt_key(username: str, address: str | None) -> str:
    """Failures are counted per username AND caller address: five wrong guesses lock that caller
    out of that account for a minute, without letting anyone lock the account for everyone."""
    return f"{username}@{address or '?'}"


def _prune_attempts(conn: db.Connection) -> None:
    conn.execute("DELETE FROM login_attempts WHERE updated_at < ?",
                 ((datetime.now() - timedelta(days=1)).isoformat(timespec="seconds"),))


def _locked(conn: db.Connection, username: str) -> int:
    """Seconds left on this key's lockout, or 0."""
    row = conn.execute("SELECT locked_until FROM login_attempts WHERE username = ?", (username,)).fetchone()
    if not row or not row["locked_until"]:
        return 0
    left = (datetime.fromisoformat(row["locked_until"]) - datetime.now()).total_seconds()
    return int(left) + 1 if left > 0 else 0


def _address_key(address: str | None) -> str | None:
    return f"*@{address}" if address else None


def _note_failure(conn: db.Connection, username: str, *, max_failures: int = MAX_FAILURES,
                  lockout_seconds: int = LOCKOUT_SECONDS) -> None:
    row = conn.execute("SELECT failures FROM login_attempts WHERE username = ?", (username,)).fetchone()
    failures = (row["failures"] if row else 0) + 1
    locked = None
    if failures >= max_failures:
        locked = (datetime.now() + timedelta(seconds=lockout_seconds)).isoformat(timespec="seconds")
        failures = 0
    conn.execute("INSERT INTO login_attempts(username, failures, locked_until, updated_at) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(username) DO UPDATE SET failures = excluded.failures, "
                 "locked_until = excluded.locked_until, updated_at = excluded.updated_at",
                 (username, failures, locked, db.now()))


def authenticate(username: str, password: str, portal: str | None, conn: db.Connection,
                 host: str | None = None, address: str | None = None) -> User:
    """Check the credentials, the rate limit, and that this account belongs on the portal that asked.

    ``portal`` is the slug of the portal the request came through -- a department's, or ``ag`` --
    set by the portal server (``X-Portal``). A department's officer is admitted only at their own
    department's portal; the Pension Wing and the administrator only at the AG portal.
    """
    username = username.strip()
    key = _attempt_key(username, address)
    _prune_attempts(conn)
    left = _locked(conn, key)
    address_key = _address_key(address)
    if address_key:
        left = max(left, _locked(conn, address_key))
    if left:
        raise AuthError(429, f"too many failed attempts; try again in {left} seconds")
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    # One message, and the same amount of work, for a wrong name and a wrong password: neither
    # the words nor the timing tell an attacker which usernames exist.
    ok = verify_password(password, row["password_hash"] if row is not None else _DECOY_HASH) and row is not None
    if not ok:
        _note_failure(conn, key)
        if address_key:
            _note_failure(conn, address_key, max_failures=ADDRESS_MAX_FAILURES,
                          lockout_seconds=ADDRESS_LOCKOUT_SECONDS)
        raise AuthError(401, "wrong username or password")
    conn.execute("DELETE FROM login_attempts WHERE username = ?", (key,))
    user = user_from_row(row)
    if not user.active:
        raise AuthError(403, "this account has been disabled; ask the administrator")
    from api import settings
    if settings.production() and password_problem(password, user.username):
        # A database carried over from the trial: the start-up sweep marks these accounts to
        # change their password, but the change screen takes "1234" as the current password, so
        # whoever typed it first -- an attacker included -- chose the new one (audit 6 Oct 2026).
        # The trial password opens nothing in production; the administrator hands out a new one.
        raise AuthError(403, "this account's trial password is no longer accepted; "
                             "ask the administrator for a new password")
    if user.portal is None:
        raise AuthError(403, "this account has no department and cannot sign in; ask the administrator")
    if not portal:
        raise AuthError(422, "the portal this request came through was not identified")
    if portal != user.portal:
        where = host or "the server"
        if user.role == "DEPT_OFFICER" and user.portal != AG_PORTAL_SLUG:
            dept = BY_CODE.get(user.department_code or "")
            target = f"http://{where}:{dept.port}/" if dept else "its own portal"
            raise AuthError(403, f"this account signs in at the {DEPARTMENT_NAMES.get(user.department_code or '', '')} "
                                 f"portal: {target}")
        raise AuthError(403, f"this account signs in at the pension portal: http://{where}:{AG_PORTAL_PORT}/")
    return user


def user_for_token(token: str, conn: db.Connection, scope: str | None = None) -> User:
    """The account behind a token. A scoped token (``issue_scoped_token``) is accepted only where
    that scope is asked for, and an ordinary session token only where none is."""
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError(401, "your session has expired; sign in again") from None
    except jwt.InvalidTokenError:
        raise AuthError(401, "invalid session token; sign in again") from None
    if claims.get("scope") != scope:
        raise AuthError(401, "this token is not valid here; sign in again")
    row = conn.execute("SELECT * FROM users WHERE id = ?", (claims.get("sub"),)).fetchone()
    if row is None:
        raise AuthError(401, "this account no longer exists")
    user = user_from_row(row)
    if not user.active:
        raise AuthError(401, "this account has been disabled")
    if int(claims.get("tv", -1)) != user.token_version:
        raise AuthError(401, "your session was ended by a password reset; sign in again")
    return user


# -- FastAPI dependencies ----------------------------------------------------------------------

def get_conn() -> db.Connection:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def password_change_due(user: User, path: str) -> bool:
    """True where this account must change its password before it may use ``path``."""
    return user.must_change_password and path not in PASSWORD_CHANGE_PATHS


PASSWORD_CHANGE_DUE = "change your password before you continue"


def current_user(request: Request, authorization: str | None = Header(default=None),
                 conn: db.Connection = Depends(get_conn)) -> User:
    token = _bearer(authorization)
    if not token:
        raise HTTPException(401, "sign in first")
    try:
        user = user_for_token(token, conn)
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from None
    if password_change_due(user, request.url.path):
        raise HTTPException(403, PASSWORD_CHANGE_DUE)
    return user


def current_user_q(request: Request, authorization: str | None = Header(default=None),
                   token: str | None = Query(default=None),
                   conn: db.Connection = Depends(get_conn)) -> User:
    """Like ``current_user`` but also reads ``?token=`` -- for ``<img>``, ``EventSource`` and a
    download link. A media token (``MEDIA_SCOPE``) is accepted here, on GET and HEAD only; so is a
    session token, for the portal that has not yet been rebuilt to ask for media tokens."""
    value = _bearer(authorization) or token
    if not value:
        raise HTTPException(401, "sign in first")
    try:
        try:
            user = user_for_token(value, conn)
        except AuthError as plain:
            if request.method not in ("GET", "HEAD"):
                raise
            try:
                user = user_for_token(value, conn, scope=MEDIA_SCOPE)
            except AuthError:
                raise plain from None
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from None
    if password_change_due(user, request.url.path):
        raise HTTPException(403, PASSWORD_CHANGE_DUE)
    return user


def require_roles(*roles: str):
    """A dependency that admits only these roles. 403 names the role that was refused."""
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"a {user.role.replace('_', ' ').lower()} may not do this")
        return user
    return dep


# -- production start-up -------------------------------------------------------------------------

def shared_logins(conn: db.Connection) -> list[str]:
    """Active accounts whose login names a desk, not a person (``db.SHARED_LOGINS``). Production
    refuses to start with one (business decision C1, 7 Oct 2026): every decision is recorded
    under a named officer, and a shared login records nobody."""
    from api.db import SHARED_LOGINS
    rows = conn.execute("SELECT username FROM users WHERE active = 1").fetchall()
    return sorted(r["username"] for r in rows if r["username"].lower() in SHARED_LOGINS)


def flag_weak_passwords(conn: db.Connection) -> list[str]:
    """Mark every active account still on a shared or obvious password to change it at next sign-in.

    Run when the API starts in production, so a database carried over from the trial -- where
    every account was ``1234`` -- cannot go live with those passwords. Checks the weak list's
    commonest entries and the username itself: about 20 ms per check, a few seconds for the
    office's ~90 accounts. Returns the usernames flagged.
    """
    candidates = ("1234", "12345678", "password", "pension")
    flagged: list[str] = []
    for row in conn.execute("SELECT * FROM users WHERE active = 1").fetchall():
        if "must_change_password" in row.keys() and row["must_change_password"]:
            continue
        stored = row["password_hash"]
        if any(verify_password(c, stored) for c in (*candidates, row["username"])):
            conn.execute("UPDATE users SET must_change_password = 1, updated_at = ? WHERE id = ?",
                         (db.now(), row["id"]))
            flagged.append(row["username"])
    return flagged
