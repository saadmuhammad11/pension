"""The key the pension portal presents to this module, and nothing else may.

The module has no sign-in of its own: it is opened inside the pension portal's case screen and
every request reaches it through that portal, which has already decided who the officer is and
what they may touch (``api/v2.py`` gpf_act_check). Until 13 Oct 2026 the only thing between the
module and anyone who could reach its port was the loopback bind -- every mutating endpoint
trusted an ``officer`` string in the request body, so any process on the box could act as the
Deputy AG and read any claimant's scans (audit of 13 Oct 2026, C-04). A bind is a deployment
property, not an access control.

So every ``/api`` request now carries a shared key. It comes from ``GPF_API_KEY`` where the two
sides run on different hosts, and otherwise from a file both read on the one box they share,
created on first use with owner-only access -- the same arrangement ``api/auth.py`` uses for the
session secret. The pension side's copy of this is ``api.gpf_bridge.api_key``; the two must agree
on the environment variable's name and the file's path, and on nothing else.
"""
from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path

#: The pension tree, four levels up: GP/backend/gpf/apikey.py -> the repository root.
PENSION_ROOT = Path(__file__).resolve().parents[3]
KEY_FILE = PENSION_ROOT / "artifacts" / ".gpf_api_key"
HEADER = "x-gpf-key"
#: Open without the key: a health probe says only whether the module is up.
OPEN_PATHS = ("/api/health",)


#: Resolved once. The middleware below runs on every request, and a case's scans are dozens of
#: them, so reading the file each time would be a disk read per page image inside the event
#: loop. ``None`` is cached too: a box that cannot make the key will not start making it on the
#: next request, and the module refuses until it is restarted with one.
_key: str | None = None
_key_read = False
_key_lock = threading.Lock()


def _read_key() -> str | None:
    given = os.environ.get("GPF_API_KEY", "").strip()
    if given:
        return given
    try:
        if KEY_FILE.exists():
            return KEY_FILE.read_text(encoding="utf-8").strip() or None
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(32)
        # Written before it is readable by anyone else, as the session secret is.
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, key.encode("utf-8"))
        finally:
            os.close(fd)
        return key
    except FileExistsError:                           # the other side created it between the two calls
        try:
            return KEY_FILE.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    except OSError:
        return None


def api_key() -> str | None:
    """The key both sides use, or None when there is none to be had."""
    global _key, _key_read
    if _key_read:
        return _key
    with _key_lock:
        if not _key_read:
            _key, _key_read = _read_key(), True
    return _key


def forget_key() -> None:
    """Drop the resolved key, so the next call reads it again. For the tests."""
    global _key, _key_read
    with _key_lock:
        _key, _key_read = None, False


def presented_is_right(presented: str | None) -> bool:
    """Constant-time comparison; False when this module has no key to compare against."""
    expected = api_key()
    if not expected:
        return False
    return secrets.compare_digest(str(presented or ""), expected)
