"""One account per pension-wing officer, replacing the shared desk logins (13 October 2026).

    /home/tmc/vllm_env/bin/python3 -m unittest tests.test_named_wing_officers -v

The office sent its list of 31 officers: Senior Auditors, Assistant AOs and Accounts Officers
across Pension-I to Pension-V. Each gets their own account (``config/ag_officers.json``), keeping
the three existing roles and their existing permissions. The shared desk logins they replace --
sa.pension1 ... ao.pension5 -- are deactivated, never deleted: cases reference them and their past
actions are on the record under their own names.
"""
from __future__ import annotations

import re
import unittest

from api import db
from tests import test_api_v2 as _v2

DESK_LOGINS = tuple(f"{short}.pension{n}" for n in range(1, 6) for short in ("sa", "aao", "ao"))


class TheRoster(unittest.TestCase):
    def setUp(self) -> None:
        self.officers = db.load_ag_officers()

    def test_thirty_one_officers_across_the_five_wings(self) -> None:
        self.assertEqual(len(self.officers), 31)
        from api.departments import PENSION_SECTION_ORDER
        by_wing: dict[str, list[str]] = {}
        for o in self.officers:
            self.assertIn(o["pension_wing"], PENSION_SECTION_ORDER)
            by_wing.setdefault(o["pension_wing"], []).append(o["role"])
        self.assertEqual(sorted(by_wing), sorted(PENSION_SECTION_ORDER))
        for wing, roles in by_wing.items():
            self.assertEqual(roles.count("AG_ASSISTANT_AO"), 1, wing)   # one AAO per wing
            self.assertEqual(roles.count("AG_AO"), 1, wing)             # one AO per wing
            self.assertGreaterEqual(roles.count("AG_SENIOR_AUDITOR"), 3, wing)

    def test_only_the_three_existing_roles_are_used(self) -> None:
        """No permission is invented: these are the roles the workflow already knows."""
        from api import workflow
        for o in self.officers:
            self.assertIn(o["role"], workflow.TIER_ROLES, o["username"])

    def test_the_usernames_are_unique_and_follow_the_rule(self) -> None:
        names = [o["username"] for o in self.officers]
        self.assertEqual(len(set(names)), len(names))
        for u in names:
            self.assertRegex(u, r"^[a-z0-9]+(\.[a-z0-9]+)*$", u)
            self.assertNotIn("..", u)
        got = {o["display_name"]: o["username"] for o in self.officers if o["display_name"] != "Tariq Chaudhry"}
        self.assertEqual(got["M. Haseeb Tahir"], "m.haseeb.tahir")       # a trailing dot is not doubled
        self.assertEqual(got["Ammad-Ud-Din"], "ammad.ud.din")            # a hyphen is a break
        self.assertEqual(got["Amaisa"], "amaisa")                        # one part, no dot
        self.assertEqual(got["Irfan Ahmad Janjua"], "irfan.ahmad.janjua")

    def test_one_person_in_two_wings_gets_one_account_per_wing(self) -> None:
        tariq = [o for o in self.officers if o["display_name"] == "Tariq Chaudhry"]
        self.assertEqual(sorted(o["username"] for o in tariq),
                         ["tariq.chaudhry.p2", "tariq.chaudhry.p5"])
        self.assertEqual({o["pension_wing"] for o in tariq}, {"Pension-II", "Pension-V"})

    def test_no_personnel_numbers_are_kept(self) -> None:
        for o in self.officers:
            self.assertEqual(set(o) - {"username", "display_name", "role", "role_label", "pension_wing"}, set())


class TheSeedAndTheDeskLogins(unittest.TestCase):
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def _conn(self):
        return db.connect()

    def test_every_officer_is_created_with_their_wing_and_role(self) -> None:
        conn = self._conn()
        try:
            for o in db.load_ag_officers():
                row = conn.execute("SELECT display_name, role, pension_wing, active, must_change_password "
                                   "FROM users WHERE username = ?", (o["username"],)).fetchone()
                self.assertIsNotNone(row, o["username"])
                self.assertEqual(row["display_name"], o["display_name"])
                self.assertEqual(row["role"], o["role"])
                self.assertEqual(row["pension_wing"], o["pension_wing"])
                self.assertEqual(row["active"], 1)
                self.assertEqual(row["must_change_password"], 0)        # off for the trial
        finally:
            conn.close()

    def test_the_desk_logins_are_closed_but_kept(self) -> None:
        conn = self._conn()
        try:
            db.seed_wing_tiers(db.SEED_PASSWORD, conn)          # as if the trial had created them
            db.retire_desk_logins(conn)
            for username in DESK_LOGINS:
                row = conn.execute("SELECT active FROM users WHERE username = ?", (username,)).fetchone()
                self.assertIsNotNone(row, f"{username} must never be deleted")
                self.assertEqual(row["active"], 0, username)
        finally:
            conn.close()

    def test_a_desk_login_is_not_closed_while_nobody_has_taken_it_over(self) -> None:
        """A wing is never left without anyone who can sign in."""
        conn = self._conn()
        try:
            conn.execute("UPDATE users SET active = 0 WHERE pension_wing = 'Pension-I' "
                         "AND role = 'AG_SENIOR_AUDITOR'")
            db.seed_wing_tiers(db.SEED_PASSWORD, conn)
            db.retire_desk_logins(conn)
            row = conn.execute("SELECT active FROM users WHERE username = 'sa.pension1'").fetchone()
            self.assertEqual(row["active"], 1, "nobody holds Pension-I's Senior Auditor desk yet")
        finally:
            conn.close()

    def test_a_closed_desk_login_cannot_sign_in(self) -> None:
        conn = self._conn()
        try:
            db.seed_wing_tiers(db.SEED_PASSWORD, conn)
            db.retire_desk_logins(conn)
        finally:
            conn.close()
        r = self.client.post("/api/v2/auth/login", json={"username": "sa.pension1", "password": db.SEED_PASSWORD},
                             headers={"X-Portal": "ag"})
        # 403 with the right password, and the generic 401 with a wrong one: a closed account is
        # refused either way, and the sheet of who is disabled is not readable from outside.
        self.assertEqual(r.status_code, 403, r.text)
        self.assertIn("disabled", r.json()["detail"])


class TheSignInSheet(unittest.TestCase):
    """start.html / artifacts/credentials: grouped by wing, the closed desk logins gone."""

    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown

    def _render(self) -> str:
        import tempfile
        from pathlib import Path
        keep = (db.CREDENTIALS_DIR, db.CREDENTIALS_CSV, db.CREDENTIALS_HTML)
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            db.CREDENTIALS_DIR, db.CREDENTIALS_CSV, db.CREDENTIALS_HTML = d, d / "c.csv", d / "c.html"
            try:
                conn = db.connect()
                try:
                    db.seed_wing_tiers(db.SEED_PASSWORD, conn)
                    db.retire_desk_logins(conn)
                    # The sheet is rendered from the password CSV, which the seed writes only for
                    # the accounts it creates. These accounts already exist in the fixture, so the
                    # CSV is written here for every live one -- the renderer is what is under test.
                    live = [dict(r) | {"dept_name": db._dept_name(conn, r["department_code"])}
                            for r in conn.execute("SELECT username, role, department_code FROM users WHERE active = 1")]
                finally:
                    conn.close()
                from api.departments import portal_for
                db._record_credentials([
                    {"portal": portal_for(r["role"], r["department_code"]) or "ag", "department": r["dept_name"],
                     "username": r["username"], "password": db.SEED_PASSWORD or "1234",
                     "role": r["role"], "department_code": r["department_code"] or ""}
                    for r in live])
                db.render_credentials_html()
                return db.CREDENTIALS_HTML.read_text(encoding="utf-8")
            finally:
                db.CREDENTIALS_DIR, db.CREDENTIALS_CSV, db.CREDENTIALS_HTML = keep

    def test_it_is_grouped_by_wing_and_keeps_the_departments(self) -> None:
        html = self._render()
        groups = re.findall(r'<tr class="grp"><th colspan="5">(.*?)</th>', html)
        self.assertEqual(groups[:5], ["Pension-I", "Pension-II", "Pension-III", "Pension-IV", "Pension-V"])
        self.assertIn("Office of the Accountant General Punjab", groups)
        self.assertGreater(len(groups), 10, "the department groups are still listed")

    def test_the_closed_desk_logins_are_off_the_sheet(self) -> None:
        html = self._render()
        for username in DESK_LOGINS:
            self.assertNotIn(f"<code>{username}</code>", html, username)

    def test_every_officer_is_on_it_by_name(self) -> None:
        html = self._render()
        for o in db.load_ag_officers():
            self.assertIn(f"<code>{o['username']}</code>", html, o["username"])
            self.assertIn(o["display_name"].replace("&", "&amp;"), html, o["display_name"])

    def test_it_has_a_search_box(self) -> None:
        self.assertIn('id="q"', self._render())


class WhatAnOfficerSees(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def _officer(self, wing: str, role: str) -> dict:
        o = next(x for x in db.load_ag_officers() if x["pension_wing"] == wing and x["role"] == role)
        return self.login(o["username"], "ag")

    def test_each_officer_sees_only_their_own_wing(self) -> None:
        from api.departments import BY_SLUG, PENSION_SECTION_OF
        # One case filed by a Punjab Police department, whichever wing that belongs to.
        ddo = self.login("punjab-police", "punjab-police")
        self.create(ddo)
        wing = PENSION_SECTION_OF[BY_SLUG["punjab-police"].code]
        for role in ("AG_SENIOR_AUDITOR", "AG_ASSISTANT_AO", "AG_AO"):
            seen = self.client.get("/api/v2/cases?product=PENSION", headers=self._officer(wing, role)).json()
            self.assertTrue(all(PENSION_SECTION_OF.get(c["department_code"]) == wing for c in seen),
                            f"{role} of {wing} sees another wing's cases")
        other = next(w for w in PENSION_SECTION_OF.values() if w != wing)
        seen = self.client.get("/api/v2/cases?product=PENSION",
                               headers=self._officer(other, "AG_SENIOR_AUDITOR")).json()
        self.assertFalse([c for c in seen if PENSION_SECTION_OF.get(c["department_code"]) == wing],
                         f"a {other} officer sees {wing}'s cases")

    def test_two_senior_auditors_of_one_wing_hold_sessions_at_once(self) -> None:
        """Several officers of a wing sign in from different PCs; neither displaces the other."""
        from api.departments import BY_SLUG, PENSION_SECTION_OF
        wing = PENSION_SECTION_OF[BY_SLUG["punjab-police"].code]
        both = [o for o in db.load_ag_officers()
                if o["pension_wing"] == wing and o["role"] == "AG_SENIOR_AUDITOR"][:2]
        self.assertEqual(len(both), 2, "this wing has at least two Senior Auditors")
        first = self.login(both[0]["username"], "ag")
        second = self.login(both[1]["username"], "ag")
        for who, headers in ((both[0], first), (both[1], second)):
            r = self.client.get("/api/v2/auth/me", headers=headers)
            self.assertEqual(r.status_code, 200, f"{who['username']} was signed out")
            self.assertEqual(r.json()["user"]["username"], who["username"])

    def test_one_officer_may_hold_two_sessions_on_two_machines(self) -> None:
        o = next(x for x in db.load_ag_officers() if x["role"] == "AG_SENIOR_AUDITOR")
        pc1 = self.login(o["username"], "ag")
        pc2 = self.login(o["username"], "ag")
        self.assertEqual(self.client.get("/api/v2/auth/me", headers=pc1).status_code, 200)
        self.assertEqual(self.client.get("/api/v2/auth/me", headers=pc2).status_code, 200)


if __name__ == "__main__":
    unittest.main()
