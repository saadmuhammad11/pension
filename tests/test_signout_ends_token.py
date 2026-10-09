"""Signing out ends the session token itself, not just the tab's copy (audit 6 Oct 2026, N15).

    python3 -m unittest tests.test_signout_ends_token -v

``/api/v2/auth/logout`` only cleared the GP Fund frame cookie; the bearer token stayed valid until
its 12-hour expiry. It now bumps the officer's ``token_version`` when it is given a valid token, so
that token (and the frame token, which carries the same version) is refused from then on.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from tests import test_api_v2 as _v2


class SignOutEndsToken(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide

    def test_the_token_is_refused_after_sign_out(self) -> None:
        headers = self.sa()
        self.assertEqual(self.client.get("/api/v2/auth/me", headers=headers).status_code, 200)
        r = self.client.post("/api/v2/auth/logout", headers=headers)
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/v2/auth/me", headers=headers)
        self.assertEqual(r.status_code, 401, r.text)
        self.assertIn("sign in again", r.json()["detail"])

    def test_the_frame_token_dies_with_the_session(self) -> None:
        headers = self.sa()
        r = self.client.post("/api/v2/auth/gpf-session", headers=headers)
        frame = r.cookies.get("pension_gpf")
        self.assertTrue(frame)
        check = lambda: self.client.get("/api/v2/auth/gpf-check", headers={"X-Gpf-Session": frame}).status_code
        self.assertEqual(check(), 200)
        self.client.post("/api/v2/auth/logout", headers=headers)
        self.assertEqual(check(), 401)

    def test_a_fresh_sign_in_works_afterwards(self) -> None:
        headers = self.sa()
        self.client.post("/api/v2/auth/logout", headers=headers)
        again = self.sa()
        self.assertEqual(self.client.get("/api/v2/auth/me", headers=again).status_code, 200)

    def test_sign_out_without_or_with_a_dead_token_is_still_fine(self) -> None:
        self.assertEqual(self.client.post("/api/v2/auth/logout").status_code, 200)
        headers = self.sa()
        self.client.post("/api/v2/auth/logout", headers=headers)
        self.assertEqual(self.client.post("/api/v2/auth/logout", headers=headers).status_code, 200)   # twice
        self.assertEqual(self.client.post("/api/v2/auth/logout", headers={"Authorization": "Bearer junk"}).status_code, 200)

    def test_sign_out_is_on_the_audit_trail(self) -> None:
        headers = self.sa()
        self.client.post("/api/v2/auth/logout", headers=headers)
        admin = self.login("admin", "ag")
        r = self.client.get("/api/v2/admin/audit-log", headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        entries = [e for e in r.json() if e.get("action") == "SIGN_OUT"]
        self.assertEqual(len(entries), 1, r.json()[:3])
        me = self.client.get("/api/v2/auth/me", headers=admin).json()["user"]
        self.assertNotEqual(entries[0].get("actor_id"), me["id"])             # the officer who left, not the admin

    def test_the_portal_sends_the_token_with_the_sign_out(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "portals/src/shared/auth/AuthProvider.tsx").read_text()
        end = source[source.index("const end = useCallback"):source.index("const logout = useCallback")]
        self.assertIn("/api/v2/auth/logout", end)
        self.assertIn("Authorization", end)
        self.assertLess(end.index("fetch('/api/v2/auth/logout'"), end.index("setToken(null)"))   # before it is dropped


if __name__ == "__main__":
    unittest.main()
