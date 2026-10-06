"""Trial or production: the one switch the deployment sets (docs/DEPLOYMENT.md §3.4).

    PENSION_ENV=production      the deployed posture
    (unset)                     the trial on this box, as it ran before 5 Oct 2026

Production changes behaviour only where the trial's convenience is a risk once real officers
and real cases are on it: no API description pages, no open sign-in sheet, no shared seed
password, a password change at first sign-in, the portal listening on loopback behind nginx.
Everything the trial does stays as it was while the variable is unset, so the office's pilot
on :5184 is not disturbed by preparing the deployment.

Read on every call rather than once at import, so tests can set the variable around a case.
"""
from __future__ import annotations

import os


def production() -> bool:
    return os.environ.get("PENSION_ENV", "").strip().lower() in ("production", "prod")


def _flag(name: str) -> bool | None:
    value = os.environ.get(name, "").strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    return None


def force_password_change() -> bool:
    """A password someone else set (the seed, the administrator) must be replaced at first sign-in.

    On in production; PENSION_FORCE_PASSWORD_CHANGE=1 turns it on for a trial, =0 off anywhere.
    """
    given = _flag("PENSION_FORCE_PASSWORD_CHANGE")
    return production() if given is None else given


def api_docs() -> bool:
    """FastAPI's /docs, /redoc and /openapi.json. Off in production; PENSION_API_DOCS=1 forces them on."""
    given = _flag("PENSION_API_DOCS")
    return (not production()) if given is None else given


def min_password_length() -> int:
    return 10 if production() else 8


def max_bundle_pages() -> int:
    """Pages the merged case file may have, whatever it was uploaded as. The per-file limit above
    is checked at upload, where a zip's contents are not opened; a zip of PDFs reached the
    pipeline with any number of pages (audit 6 Oct 2026)."""
    try:
        return max(1, int(os.environ.get("PENSION_MAX_BUNDLE_PAGES", "1000")))
    except ValueError:
        return 1000


def max_case_pages() -> int:
    """Pages one uploaded PDF may have. A real pension file is 40-120 pages; a 5,000-page upload
    would hold the vision model for days."""
    try:
        return max(1, int(os.environ.get("PENSION_MAX_PAGES", "500")))
    except ValueError:
        return 500
