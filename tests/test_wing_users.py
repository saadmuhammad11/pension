"""User management for the wing tiers (scope change C4, 9 Oct 2026).

    /home/tmc/vllm_env/bin/python3 -m unittest tests.test_wing_users -v
"""
from __future__ import annotations

import unittest

from api import db
from tests import test_api_v2 as _v2


class WingUsers(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide

    def _create(self, admin: dict, **body) -> object:
        return self.client.post("/api/v2/admin/users", headers=admin,
                                json={"display_name": body.get("username", "x").title(), "password": "Strong-Pass-2026!", **body})

    def test_a_user_per_tier_and_wing_and_the_filters(self) -> None:
        admin = self.login("admin", "ag")
        made = []
        for n, wing in enumerate(["Pension-I", "Pension-II", "Pension-III", "Pension-IV", "Pension-V"], start=1):
            for role in ("AG_SENIOR_AUDITOR", "AG_ASSISTANT_AO", "AG_AO"):
                r = self._create(admin, username=f"new.{role.lower()}.{n}", role=role, pension_wing=wing)
                self.assertEqual(r.status_code, 201, r.text)
                self.assertEqual((r.json()["role"], r.json()["pension_wing"], r.json()["department_code"]), (role, wing, None))
                made.append(r.json()["username"])
        by_wing = self.client.get("/api/v2/admin/users?pension_wing=Pension-III", headers=admin).json()
        self.assertTrue(all(u["pension_wing"] == "Pension-III" for u in by_wing))
        self.assertEqual(len([u for u in by_wing if u["username"].startswith("new.")]), 3)
        by_role = self.client.get("/api/v2/admin/users?role=AG_AO", headers=admin).json()
        self.assertTrue(all(u["role"] == "AG_AO" for u in by_role) and len(by_role) >= 5)
        # The new officer signs in at the AG portal and the session carries the tier and the wing.
        r = self.client.post("/api/v2/auth/login", json={"username": made[0], "password": "Strong-Pass-2026!"}, headers={"X-Portal": "ag"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["user"]["role"], r.json()["user"]["pension_wing"]), ("AG_SENIOR_AUDITOR", "Pension-I"))
        self.assertEqual((r.json()["capabilities"]["tier"], r.json()["capabilities"]["tier_label"]), ("SENIOR_AUDITOR", "Senior Auditor"))

    def test_a_wing_is_refused_on_a_ddo_and_a_department_on_a_wing_officer(self) -> None:
        admin = self.login("admin", "ag")
        r = self._create(admin, username="ddo.wing", role="DEPT_OFFICER", department_code="HEALTH", pension_wing="Pension-I")
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("not to a pension wing", r.json()["detail"])
        r = self._create(admin, username="sa.dept", role="AG_SENIOR_AUDITOR", pension_wing="Pension-I", department_code="HEALTH")
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("no department", r.json()["detail"])
        r = self._create(admin, username="sa.nowing", role="AG_SENIOR_AUDITOR")
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("pension wing", r.json()["detail"])
        r = self._create(admin, username="sa.badwing", role="AG_SENIOR_AUDITOR", pension_wing="Pension-IX")
        self.assertEqual(r.status_code, 422, r.text)
        r = self._create(admin, username="dag.wing", role="AG_DAG", pension_wing="Pension-I")
        self.assertEqual(r.status_code, 422, r.text)
        r = self._create(admin, username="desk.two", role="AG_REVIEWER")                 # the AG's desk: no wing, no department
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["pension_wing"], r.json()["department_code"]), (None, None))
        self.assertEqual(self._create(admin, username="desk.three", role="AG_REVIEWER", pension_wing="Pension-I").status_code, 422)
        r = self._create(admin, username="dag.two", role="AG_DAG")
        self.assertEqual(r.status_code, 201, r.text)

    def test_the_coverage_report_names_the_tiers_with_nobody(self) -> None:
        admin = self.login("admin", "ag")
        cov = self.client.get("/api/v2/admin/wing-coverage", headers=admin).json()
        self.assertEqual([w["wing"] for w in cov["wings"]], ["Pension-I", "Pension-II", "Pension-III", "Pension-IV", "Pension-V"])
        self.assertEqual(cov["gaps"], [])                                        # the fixture staffs every tier of every wing
        self.assertEqual(cov["deputy_ag"], 1)
        # Disable every AO of Pension-II -- the named officer and the desk login behind them
        # (13 Oct 2026: a wing has named officers as well as the desk account) -- and the report
        # flags the tier as having nobody.
        users = self.client.get("/api/v2/admin/users?pension_wing=Pension-II&role=AG_AO", headers=admin).json()
        self.assertGreaterEqual(len(users), 1)
        for u in users:
            r = self.client.post(f"/api/v2/admin/users/{u['id']}/disable", headers=admin, json={"reason": "transferred"})
            self.assertEqual(r.status_code, 200, r.text)
        cov = self.client.get("/api/v2/admin/wing-coverage", headers=admin).json()
        self.assertEqual(cov["gaps"], [{"wing": "Pension-II", "tier": "AO"}])
        tiers = next(w for w in cov["wings"] if w["wing"] == "Pension-II")["tiers"]
        self.assertEqual(tiers["AO"], 0)                                  # the tier that was emptied
        self.assertGreaterEqual(tiers["SENIOR_AUDITOR"], 1)               # the others are still staffed
        self.assertGreaterEqual(tiers["ASSISTANT_AO"], 1)
        self.assertEqual(cov["tier_labels"]["AO"], "Accounts Officer")
        # Not the DDO's or a tier officer's business.
        self.assertEqual(self.client.get("/api/v2/admin/wing-coverage", headers=self.login("punjab-police", "punjab-police")).status_code, 403)

    def test_an_ag_desk_account_is_given_a_tier_and_a_wing_with_a_reason(self) -> None:
        admin = self.login("admin", "ag")
        legacy = next(u for u in self.client.get("/api/v2/admin/users", headers=admin).json() if u["username"] == "ag.reviewer")
        self.assertEqual(legacy["role"], "AG_REVIEWER")
        r = self.client.post(f"/api/v2/admin/users/{legacy['id']}/role", headers=admin, json={"role": "AG_AO", "pension_wing": "Pension-III", "reason": "short"})
        self.assertEqual(r.status_code, 422, r.text)
        r = self.client.post(f"/api/v2/admin/users/{legacy['id']}/role", headers=admin,
                             json={"role": "AG_AO", "pension_wing": "Pension-III", "reason": "Posted as Accounts Officer, Pension-III, by the AG's order."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["role"], r.json()["pension_wing"]), ("AG_AO", "Pension-III"))
        # The old session is over; the new one carries the tier.
        r = self.client.post("/api/v2/auth/login", json={"username": "ag.reviewer", "password": db.SEED_PASSWORD}, headers={"X-Portal": "ag"})
        self.assertEqual(r.json()["capabilities"]["tier"], "AO")
        log = self.client.get("/api/v2/admin/audit-log?limit=20", headers=admin).json()
        row = next(e for e in log if e["action"] == "USER_ROLE_CHANGE")
        self.assertEqual((row["before"]["role"], row["after"]), ("AG_REVIEWER", {"role": "AG_AO", "pension_wing": "Pension-III"}))
        # A DDO's account is a department's: it is not turned into an AG account.
        ddo = next(u for u in self.client.get("/api/v2/admin/users", headers=admin).json() if u["username"] == "punjab-police")
        r = self.client.post(f"/api/v2/admin/users/{ddo['id']}/role", headers=admin, json={"role": "AG_AO", "pension_wing": "Pension-V", "reason": "x" * 12})
        self.assertEqual(r.status_code, 422, r.text)

    def test_the_command_line_creates_tier_officers(self) -> None:
        pw = db.add_reviewer("cli.sa", "Command Line Senior Auditor", tier="senior-auditor", wing="Pension-IV")
        self.assertTrue(pw)
        with self.assertRaises(ValueError):
            db.add_reviewer("cli.nowing", "No Wing", tier="ao")
        with self.assertRaises(ValueError):
            db.add_reviewer("cli.legacy", "No Tier")
        conn = db.connect()
        try:
            row = conn.execute("SELECT role, pension_wing FROM users WHERE username = 'cli.sa'").fetchone()
            self.assertEqual((row["role"], row["pension_wing"]), ("AG_SENIOR_AUDITOR", "Pension-IV"))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
