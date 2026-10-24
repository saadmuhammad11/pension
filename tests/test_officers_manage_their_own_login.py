"""A senior officer changes their own password and login name.

24 Oct 2026. Changing your own password has always been possible on the API and could only be
reached when an administrator had forced a reset -- so an officer who wanted a new password
had to ask for one to be reset first, which is a worse habit than the one it guarded. The
login name was the administrator's alone.

The Deputy AG, the Additional AG and the AG hold a login in their own name and no
administrator sits above them in the office. A DDO's login is its department's slug, which
identifies the department and not a person, so that one stays with the administrator.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import v2  # noqa: E402


class WhoMayRenameThemselves(unittest.TestCase):

    def test_the_three_senior_desks(self) -> None:
        self.assertEqual(set(v2.MAY_RENAME_SELF), {"AG_DAG", "AG_REVIEWER", "AG_ADDL"})

    def test_and_nobody_else(self) -> None:
        for role in ("DEPT_OFFICER", "AG_SENIOR_AUDITOR", "AG_ASSISTANT_AO", "AG_AO", "ADMIN"):
            self.assertNotIn(role, v2.MAY_RENAME_SELF, role)

    def test_a_dept_officer_is_left_out_on_purpose(self) -> None:
        """Its login is the department's slug: renaming it renames the department's way in."""
        self.assertNotIn("DEPT_OFFICER", v2.MAY_RENAME_SELF)


class TheRulesItFollows(unittest.TestCase):
    """Read off the route, so a later edit that drops one of them is noticed."""

    SRC = (ROOT / "api" / "v2.py").read_text(encoding="utf-8")
    ROUTE = SRC[SRC.index("def change_own_username"):SRC.index("#: The cookie the GP Fund frame")]

    def test_the_password_is_asked_for(self) -> None:
        """A session left unattended must not be able to rename the account it is signed in to."""
        self.assertIn("verify_password", self.ROUTE)
        self.assertIn('raise HTTPException(403, "the password is wrong")', self.ROUTE)

    def test_wrong_attempts_are_counted(self) -> None:
        self.assertIn("_locked(conn, key)", self.ROUTE)
        self.assertIn("_note_failure", self.ROUTE)

    def test_the_role_is_checked_on_the_server(self) -> None:
        """The screen hides the form; the server is what decides."""
        self.assertIn("user.role not in MAY_RENAME_SELF", self.ROUTE)

    def test_the_same_shape_rule_as_the_administrators_rename(self) -> None:
        self.assertIn(r"[a-z0-9._-]{3,40}", self.ROUTE)

    def test_a_taken_name_is_a_conflict(self) -> None:
        self.assertIn('409, "that username is taken"', self.ROUTE)

    def test_every_session_ends(self) -> None:
        """The token names the account as it was; one left open is one nobody can account for."""
        self.assertIn("token_version = token_version + 1", self.ROUTE)

    def test_it_is_audited_under_the_officers_own_name(self) -> None:
        self.assertIn('action="USER_RENAME"', self.ROUTE)
        self.assertIn("actor=user", self.ROUTE)

    def test_a_shared_login_is_still_refused_in_production(self) -> None:
        self.assertIn("SHARED_LOGINS", self.ROUTE)


class TheScreenAgreesWithTheServer(unittest.TestCase):

    def test_the_two_lists_are_the_same(self) -> None:
        tsx = (ROOT / "portals" / "src" / "shared" / "screens" / "MyAccount.tsx").read_text(encoding="utf-8")
        line = next(ln for ln in tsx.splitlines() if "MAY_MANAGE_OWN_PROFILE = [" in ln)
        for role in v2.MAY_RENAME_SELF:
            self.assertIn(role, line, role)

    def test_there_is_a_way_in_from_the_header(self) -> None:
        header = (ROOT / "portals" / "src" / "shared" / "components" / "Header.tsx").read_text(encoding="utf-8")
        self.assertIn("#/account", header)

    def test_the_screen_is_for_those_three_desks_and_nobody_else(self) -> None:
        """Every other account stays the administrator's to manage, which is what it was.

        Two gates carry the list: the guard that sends an officer away from an address they
        may not open, and the branch that draws the screen. The shell's third mention of the
        address -- `known`, which only says the portal has such a path -- is roleless on
        purpose: without it an officer without the right fell through to the dashboard
        instead of being sent there (24 Oct 2026).
        """
        shell = (ROOT / "portals" / "src" / "shared" / "PortalShell.tsx").read_text(encoding="utf-8")
        self.assertIn("(cleanPath !== '/account' || MAY_MANAGE_OWN_PROFILE.includes(user.role))", shell)
        self.assertIn("cleanPath === '/account' && MAY_MANAGE_OWN_PROFILE.includes(user.role)", shell)

    def test_and_the_way_in_is_not_drawn_for_anyone_else(self) -> None:
        header = (ROOT / "portals" / "src" / "shared" / "components" / "Header.tsx").read_text(encoding="utf-8")
        self.assertIn("MAY_MANAGE_OWN_PROFILE.includes(user.role)", header)


if __name__ == "__main__":
    unittest.main()
