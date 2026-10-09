"""Signing out ends the GP Fund frame sign-in in that browser (audit 6 Oct 2026, Medium).

    python3 -m unittest tests.test_signout_clears_gpf -v

The frame cookie (HttpOnly, path /gpf, two hours) outlived sign-out and the idle timeout, so the
next person at a shared office PC could open /gpf/ as the officer who had just left.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from tests import test_api_v2 as _v2


class SignOut(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide

    def test_sign_out_deletes_the_frame_cookie_even_without_a_session(self) -> None:
        r = self.client.post("/api/v2/auth/gpf-session", headers=self.sa())
        self.assertTrue(r.cookies.get("pension_gpf"))
        self.assertTrue(self.client.cookies.get("pension_gpf", path="/gpf"))
        # No Authorization header: the idle timeout and a refused token sign out after the session.
        r = self.client.post("/api/v2/auth/logout")
        self.assertEqual(r.status_code, 200)
        cleared = r.headers["set-cookie"].lower()
        for part in ("pension_gpf=", "max-age=0", "path=/gpf"):
            self.assertIn(part, cleared)
        self.assertIsNone(self.client.cookies.get("pension_gpf", path="/gpf"))

    def test_the_portal_calls_it_on_every_way_a_session_ends(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "portals/src/shared/auth/AuthProvider.tsx").read_text()
        end = source[source.index("const end = useCallback"):source.index("const logout = useCallback")]
        self.assertIn("/api/v2/auth/logout", end)          # sign-out, idle timeout and 401 all go through end()


if __name__ == "__main__":
    unittest.main()
