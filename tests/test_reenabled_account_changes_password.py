"""A re-enabled account in production must choose a new password (audit 6 Oct 2026, L4).

    python3 -m unittest tests.test_reenabled_account_changes_password -v

The start-up sweep marks every *active* account still on a trial password to change it (F1), so
an account disabled during the trial and enabled by the administrator later came back with
``1234`` and no such mark. In production, enabling an account now sets the mark itself.
"""
from __future__ import annotations

import unittest
from unittest import mock

from tests import test_api_v2 as _v2

PROD = {"PENSION_ENV": "production"}


class ReEnabledAccount(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide

    def _disable(self, admin: dict, username: str) -> str:
        users = self.client.get("/api/v2/admin/users", headers=admin).json()
        uid = next(u["id"] for u in users if u["username"] == username)
        r = self.client.post(f"/api/v2/admin/users/{uid}/disable", headers=admin, json={"reason": "On leave."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["active"])
        return uid

    def test_in_production_enabling_marks_the_password_for_change(self) -> None:
        admin = self.login("admin", "ag")
        uid = self._disable(admin, "agriculture")
        with mock.patch.dict("os.environ", PROD):
            r = self.client.post(f"/api/v2/admin/users/{uid}/enable", headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["active"])
        self.assertTrue(r.json()["must_change_password"])
        log = self.client.get("/api/v2/admin/audit-log", headers=admin).json()
        self.assertEqual(log[0]["action"], "USER_ENABLE")
        self.assertEqual(log[0]["after"], {"active": True, "must_change_password": True})

    def test_in_the_trial_enabling_leaves_the_password_alone(self) -> None:
        admin = self.login("admin", "ag")
        uid = self._disable(admin, "agriculture")
        r = self.client.post(f"/api/v2/admin/users/{uid}/enable", headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["must_change_password"])


if __name__ == "__main__":
    unittest.main()
