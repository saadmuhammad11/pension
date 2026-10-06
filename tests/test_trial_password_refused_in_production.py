"""In production a trial password opens nothing (audit 6 Oct 2026, later report item 2).

    python3 -m unittest tests.test_trial_password_refused_in_production -v

Production start-up marks accounts still on ``1234`` to change their password, but the change
screen takes ``1234`` as the current password, so the first person to type it -- an attacker
included -- chose the new one. Signing in with a weak password is now refused outright in
production; the administrator's reset hands out a password that the officer then replaces.
"""
from __future__ import annotations

import unittest
from unittest import mock

from api import db
from api.auth import hash_password
from tests import test_api_v2 as _v2

PROD = {"PENSION_ENV": "production"}


class TrialPassword(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login

    def _put_on_trial_password(self, username: str) -> None:
        conn = db.connect()
        try:
            conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hash_password("1234"), username))
            conn.commit()
        finally:
            conn.close()

    def _login(self, username: str, password: str):
        return self.client.post("/api/v2/auth/login", json={"username": username, "password": password},
                                headers={"X-Portal": "ag"})

    def test_the_trial_password_signs_in_during_the_trial_but_not_in_production(self) -> None:
        self._put_on_trial_password("agriculture")
        self.assertEqual(self._login("agriculture", "1234").status_code, 200)
        with mock.patch.dict("os.environ", PROD):
            r = self._login("agriculture", "1234")
            self.assertEqual(r.status_code, 403, r.text)
            self.assertIn("trial password is no longer accepted", r.json()["detail"])
            # Not a lockout: the account is not counted as failing, and a wrong password still is.
            self.assertEqual(self._login("agriculture", "definitely-wrong").status_code, 401)

    def test_the_administrator_s_reset_opens_the_account_again(self) -> None:
        self._put_on_trial_password("agriculture")
        admin = self.login("admin", "ag")
        uid = next(u["id"] for u in self.client.get("/api/v2/admin/users", headers=admin).json() if u["username"] == "agriculture")
        with mock.patch.dict("os.environ", PROD):
            r = self.client.post(f"/api/v2/admin/users/{uid}/reset-password", headers=admin,
                                 json={"password": "Harbour-Timber-Crystal-41"})
            self.assertEqual(r.status_code, 200, r.text)
            r = self._login("agriculture", "Harbour-Timber-Crystal-41")
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(r.json()["user"]["must_change_password"])   # and the officer replaces it


if __name__ == "__main__":
    unittest.main()
