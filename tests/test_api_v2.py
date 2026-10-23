"""The multi-department API end to end, over FastAPI's TestClient, with the pipeline stubbed.

    python3 -m unittest tests.test_api_v2 -v

The stub for ``api.runs.execute`` writes a case report of our choosing and marks the run done,
so the whole lifecycle -- file (which submits), verify at the AG, return by itself, approve by
itself, decide by hand, resubmit, override -- runs in a second and without a GPU. The real
pipeline is exercised by the E2E pass. Decision of 28 Sep 2026: the verification is the AG's.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from api import case_runs, db, gpf_bridge, runs, workflow

PDF = b"%PDF-1.4\n%golden case\n"
PDF2 = b"%PDF-1.4\n%another paper\n"

CLEAN_REPORT = {"claimant_name": "Mst. Gulshan Jan", "flags": [],
                "checklist": {"result": "COMPLETE", "items": [], "missing": 0},
                "recommendation": {"verdict": "FORWARD", "blocking_flags": []}}
# A finding but every paper present: the case waits for the AG to clear it.
FLAGS_ONLY_REPORT = {"claimant_name": "Fozia Akhtar",
                     "flags": [{"id": "F-1", "severity": "HIGH", "class": "RULE-UNDECLARED",
                                "title": "Unrecorded recovery", "blocks_ppo": True}],
                     "checklist": {"result": "COMPLETE", "items": [], "missing": 0},
                     "recommendation": {"verdict": "HOLD", "blocking_flags": ["F-1"]}}
FLAGGED_REPORT = {"claimant_name": "Fozia Akhtar",
                  "flags": [{"id": "F-1", "severity": "HIGH", "class": "RULE-UNDECLARED",
                             "title": "Unrecorded recovery", "blocks_ppo": True}],
                  "checklist": {"result": "INCOMPLETE", "missing": 1,
                                "items": [{"id": "AG-06", "requirement": "NADRA FRC", "status": "MISSING"}]},
                  "recommendation": {"verdict": "RETURN_FOR_CORRECTION", "blocking_flags": ["F-1"]}}


def ensure_deputy_ag() -> None:
    """A named Deputy AG (role AG_DAG; decisions C1/G6) on the seed password, for the tests that need
    the senior officer's powers: the override, and the GP Fund DAG band. The administrator has
    neither any more."""
    from api.auth import hash_password
    conn = db.connect()
    try:
        if not conn.execute("SELECT 1 FROM users WHERE username = 'fatima.hameed'").fetchone():
            conn.execute("INSERT INTO users(id, username, display_name, password_hash, role, department_code, active, "
                         "token_version, must_change_password, created_at, updated_at) VALUES (?, 'fatima.hameed', "
                         "'Fatima Hameed (Deputy AG, Pension)', ?, 'AG_DAG', NULL, 1, 1, 0, ?, ?)",
                         (db.new_id(), hash_password(db.SEED_PASSWORD), db.now(), db.now()))
            conn.commit()
    finally:
        conn.close()


#: The tier accounts the fixtures create (C3, 9 Oct 2026): one Senior Auditor, Assistant AO and
#: AO per pension wing, on the seed password. usernames sa.p1 .. ao.p5.
TIER_SHORT = {"AG_SENIOR_AUDITOR": "sa", "AG_ASSISTANT_AO": "aao", "AG_AO": "ao"}


def ensure_tiers() -> None:
    """A Senior Auditor, an Assistant AO and an AO for every wing, so a test can run a case through
    the chain whatever department it files for."""
    from api.auth import hash_password
    from api.departments import PENSION_SECTION_ORDER
    conn = db.connect()
    try:
        have = {r["username"] for r in conn.execute("SELECT username FROM users")}
        pw = hash_password(db.SEED_PASSWORD)
        for n, wing in enumerate(PENSION_SECTION_ORDER, start=1):
            for role, short in TIER_SHORT.items():
                name = f"{short}.p{n}"
                if name in have:
                    continue
                conn.execute("INSERT INTO users(id, username, display_name, password_hash, role, department_code, pension_wing, "
                             "active, token_version, must_change_password, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, ?, 1, 1, 0, ?, ?)",
                             (db.new_id(), name, f"{workflow.TIER_LABELS[workflow.TIER_OF_ROLE[role]]} {n} ({wing})", pw, role, wing,
                              db.now(), db.now()))
        conn.commit()
    finally:
        conn.close()


def tier_username(role: str, dept_slug: str) -> str:
    """The fixture account of this tier for the wing the department belongs to."""
    from api.departments import BY_SLUG, PENSION_SECTION_OF, PENSION_SECTION_ORDER
    wing = PENSION_SECTION_OF[BY_SLUG[dept_slug].code]
    return f"{TIER_SHORT[role]}.p{PENSION_SECTION_ORDER.index(wing) + 1}"


class V2Test(unittest.TestCase):
    report_to_write: dict = CLEAN_REPORT
    fail_runs: bool = False

    def setUp(self) -> None:
        # addCleanup, not tearDown: unittest skips tearDown entirely when setUp raises part
        # way through, and this fixture seeds 119 accounts and writes their plaintext sheet
        # beside the temporary database. Two of those directories were found in /tmp on
        # 20 Oct 2026, left by runs that were interrupted. Registered the moment it exists,
        # so whatever happens after this line it still goes.
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-v2-")
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        artifacts = root / "artifacts"
        artifacts.mkdir()

        def fake_execute(run: runs.Run) -> None:
            run.run_dir.mkdir(parents=True, exist_ok=True)
            runs.persist_intake(run)
            (run.run_dir / "manifest.json").write_text(json.dumps({"pages": []}))
            if self.fail_runs:
                run.state, run.error = "failed", "vision service down"
            else:
                (run.run_dir / "case_report.json").write_text(json.dumps(self.report_to_write))
                run.state = "done"
            run.emit("end", run.state, state=run.state)

        self._patches = [
            mock.patch.object(db, "DB_PATH", root / "portal.sqlite3"),
            mock.patch.object(runs, "ARTIFACTS", artifacts),
            mock.patch.object(runs, "UPLOADS", artifacts / "uploads"),
            mock.patch.object(runs, "execute", fake_execute),
            mock.patch.object(case_runs, "CASE_FILES", artifacts / "cases"),
            mock.patch.object(case_runs, "start_reconciler", lambda *a, **k: None),
            # No reconciler here, so every read must sync at once (the request-path rate limit is
            # its own test: tests/test_sync_throttle.py).
            mock.patch.object(case_runs, "SYNC_MIN_INTERVAL_S", 0.0),
            mock.patch.dict("os.environ", {"PENSION_JWT_SECRET": "test-secret-for-the-case-system-fixture-0123456789"}),
            mock.patch.object(db, "SEED_PASSWORD", "Pension@2026"),
            mock.patch.object(db, "CREDENTIALS_CSV", root / "credentials.csv"),
            mock.patch.object(db, "CREDENTIALS_HTML", root / "credentials.html"),
        ]
        for p in self._patches:
            p.start()
        self._saved_runs = dict(runs.RUNS)
        runs.RUNS.clear()
        db.migrate()
        db.seed(quiet=True)
        ensure_deputy_ag()
        ensure_tiers()
        from api.server import app
        self.client = TestClient(app, client=("127.0.0.1", 50000))   # the peer the proxy is, so X-Forwarded-For counts

    def tearDown(self) -> None:
        runs.RUNS.clear()
        runs.RUNS.update(self._saved_runs)
        for p in reversed(self._patches):
            p.stop()

    # -- helpers ----------------------------------------------------------------------------

    def login(self, username: str, portal: str) -> dict:
        from api.departments import SINGLE_PORTAL
        portal = "ag" if SINGLE_PORTAL else portal                     # one portal for everyone
        r = self.client.post("/api/v2/auth/login", json={"username": username, "password": db.SEED_PASSWORD},
                             headers={"X-Portal": portal})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def create(self, headers: dict, files=(("case.pdf", PDF),), **fields) -> dict:
        # A pension case is filed under a declared type (29 Sep 2026); tests that do not care
        # get a family pension. Pass case_type=None to leave it out.
        if fields.get("product", "PENSION") == "PENSION" and "case_type" not in fields:
            fields["case_type"] = "DEATH_IN_SERVICE"
        fields = {k: v for k, v in fields.items() if v is not None}
        r = self.client.post("/api/v2/cases", headers=headers, data=fields,
                             files=[("files", (n, io.BytesIO(b), "application/pdf")) for n, b in files])
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    # -- the tiers (C3) ------------------------------------------------------------------------
    def sa(self, dept_slug: str = "punjab-police") -> dict:
        """The Senior Auditor of the wing this department belongs to."""
        return self.login(tier_username("AG_SENIOR_AUDITOR", dept_slug), "ag")

    def aao(self, dept_slug: str = "punjab-police") -> dict:
        return self.login(tier_username("AG_ASSISTANT_AO", dept_slug), "ag")

    def ao(self, dept_slug: str = "punjab-police") -> dict:
        return self.login(tier_username("AG_AO", dept_slug), "ag")

    def escalate(self, case_id: str, dept_slug: str = "punjab-police") -> dict:
        """Senior Auditor forwards to the Assistant AO, who forwards to the AO; returns the AO's headers."""
        r = self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=self.sa(dept_slug), json={})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=self.aao(dept_slug), json={})
        self.assertEqual(r.status_code, 200, r.text)
        return self.ao(dept_slug)

    def decide(self, case_id: str, action: str, body: dict, dept_slug: str = "punjab-police"):
        """Up the chain, then the AO's approve or reject; the response of that last call."""
        ao = self.escalate(case_id, dept_slug)
        return self.client.post(f"/api/v2/cases/{case_id}/{action}", headers=ao, json=body)

    def verify(self, headers: dict, case_id: str) -> dict:
        r = self.client.post(f"/api/v2/cases/{case_id}/check", headers=headers)
        self.assertEqual(r.status_code, 202, r.text)
        return r.json()

    # -- auth -------------------------------------------------------------------------------

    def test_a_department_signs_in_only_at_its_own_portal(self) -> None:
        # Punjab Police's officer at the School Education portal, and at the AG portal: refused,
        # told where to go. At their own portal: admitted, with the department's name.
        r = self.client.post("/api/v2/auth/login", json={"username": "punjab-police", "password": db.SEED_PASSWORD},
                             headers={"X-Portal": "school-education", "Host": "10.0.0.5:5181"})
        self.assertEqual(r.status_code, 403)
        self.assertIn(":5184/", r.json()["detail"])
        r = self.client.post("/api/v2/auth/login", json={"username": "punjab-police", "password": db.SEED_PASSWORD},
                             headers={"X-Portal": "ag"})
        self.assertEqual(r.status_code, 200)                          # one portal for everyone
        r = self.client.post("/api/v2/auth/login", json={"username": "ag.reviewer", "password": db.SEED_PASSWORD},
                             headers={"X-Portal": "punjab-police"})
        self.assertEqual(r.status_code, 403)
        self.assertIn(":5184/", r.json()["detail"])
        r = self.client.post("/api/v2/auth/login", json={"username": "punjab-police", "password": db.SEED_PASSWORD})
        self.assertEqual(r.status_code, 422)                          # no portal identified
        h = self.login("punjab-police", "punjab-police")
        me = self.client.get("/api/v2/auth/me", headers=h).json()
        self.assertEqual(me["user"]["department_code"], "PUNJAB_POLICE")
        self.assertEqual(me["user"]["department_name"], "Punjab Police")
        self.assertTrue(me["capabilities"]["forward"])
        self.assertFalse(me["capabilities"]["review"])

    def test_no_token_is_401_and_wrong_password_is_401(self) -> None:
        self.assertEqual(self.client.get("/api/v2/cases").status_code, 401)
        r = self.client.post("/api/v2/auth/login", json={"username": "admin", "password": "nope"}, headers={"X-Portal": "ag"})
        self.assertEqual(r.status_code, 401)

    def test_five_wrong_passwords_lock_the_username_for_a_minute(self) -> None:
        for _ in range(5):
            self.client.post("/api/v2/auth/login", json={"username": "admin", "password": "nope"}, headers={"X-Portal": "ag"})
        r = self.client.post("/api/v2/auth/login", json={"username": "admin", "password": db.SEED_PASSWORD}, headers={"X-Portal": "ag"})
        self.assertEqual(r.status_code, 429)
        self.assertIn("try again", r.json()["detail"])

    def test_disabling_a_user_ends_their_session_at_once(self) -> None:
        admin = self.login("admin", "ag")
        edu = self.login("school-education", "school-education")
        self.assertEqual(self.client.get("/api/v2/cases", headers=edu).status_code, 200)
        r = self.client.post("/api/v2/admin/users/school-education/disable", headers=admin, json={"reason": "left"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/v2/cases", headers=edu).status_code, 401)
        log = self.client.get("/api/v2/admin/audit-log", headers=admin).json()
        self.assertEqual(log[0]["action"], "USER_DISABLE")

    def test_reset_password_revokes_old_tokens(self) -> None:
        admin = self.login("admin", "ag")
        police = self.login("punjab-police", "punjab-police")
        r = self.client.post("/api/v2/admin/users/punjab-police/reset-password", headers=admin,
                             json={"password": "NewPass#2026", "reason": "Officer forgot the password; identity confirmed."})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/v2/auth/me", headers=police).status_code, 401)
        r = self.client.post("/api/v2/auth/login", json={"username": "punjab-police", "password": "NewPass#2026"},
                             headers={"X-Portal": "ag"})
        self.assertEqual(r.status_code, 200)

    def test_an_account_can_be_renamed_and_signs_in_under_the_new_name(self) -> None:
        """The administrator changes a username (23 Oct 2026). The account keeps everything else."""
        admin = self.login("admin", "ag")
        police = self.login("punjab-police", "punjab-police")
        before = self.client.get("/api/v2/auth/me", headers=police).json()
        r = self.client.post("/api/v2/admin/users/punjab-police/username", headers=admin,
                             json={"username": "renamed.officer", "reason": "Login was the department, not the officer."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["username"], "renamed.officer")
        # Read before anything else is audited: a refused sign-in writes LOGIN_FAILED on top.
        entry = self.client.get("/api/v2/admin/audit-log", headers=admin).json()[0]
        self.assertEqual(entry["action"], "USER_RENAME")
        self.assertEqual(entry["before"], {"username": "punjab-police"})
        self.assertEqual(entry["after"], {"username": "renamed.officer"})
        # The sessions end: the token named an account signing in as a username that is gone.
        self.assertEqual(self.client.get("/api/v2/auth/me", headers=police).status_code, 401)
        self.assertEqual(self.client.post("/api/v2/auth/login", headers={"X-Portal": "ag"},
                                          json={"username": "punjab-police", "password": db.SEED_PASSWORD}).status_code, 401)
        # The same account, under the new name: same id, role, department, display name.
        again = self.login("renamed.officer", "punjab-police")
        now = self.client.get("/api/v2/auth/me", headers=again).json()
        for key in ("id", "role", "department_code", "display_name"):
            self.assertEqual(now.get(key), before.get(key), key)

    def test_a_rename_is_refused_where_it_would_be_wrong(self) -> None:
        admin = self.login("admin", "ag")
        reason = "Login was the department, not the officer."
        def rename(body: dict) -> int:
            return self.client.post("/api/v2/admin/users/punjab-police/username", headers=admin, json=body).status_code
        self.assertEqual(rename({"username": "AB", "reason": reason}), 422)                    # too short
        self.assertEqual(rename({"username": "has space", "reason": reason}), 422)             # not the alphabet
        self.assertEqual(rename({"username": "punjab-police", "reason": reason}), 422)         # the name it has
        self.assertEqual(rename({"username": "renamed.officer", "reason": "typo"}), 422)       # no reason worth the name
        self.assertEqual(rename({"username": "tauqeer.ahmad", "reason": reason}), 409)         # an officer already has it
        # Refused means refused: the account still signs in as it did.
        self.assertEqual(self.client.post("/api/v2/auth/login", headers={"X-Portal": "ag"},
                                          json={"username": "punjab-police", "password": db.SEED_PASSWORD}).status_code, 200)

    def test_only_the_administrator_renames_an_account(self) -> None:
        for who, portal in (("punjab-police", "punjab-police"), ("tauqeer.ahmad", "ag")):
            headers = self.login(who, portal)
            r = self.client.post("/api/v2/admin/users/school-education/username", headers=headers,
                                 json={"username": "new.name", "reason": "Trying it on from the wrong desk."})
            self.assertEqual(r.status_code, 403, f"{who}: {r.text}")

    def test_the_month_s_register_downloads_as_a_spreadsheet(self) -> None:
        """Every user may take the month's cases away (23 Oct 2026), scoped as the register is."""
        import csv as _csv
        import io as _io
        dept = self.login("punjab-police", "punjab-police")
        case = self.create(dept)["case"]
        month = case["created_at"][:7]
        r = self.client.get(f"/api/v2/reports/monthly.csv?month={month}", headers=dept)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("text/csv", r.headers["content-type"])
        self.assertEqual(r.headers["content-disposition"], f'attachment; filename="cases-{month}.csv"')
        rows = list(_csv.DictReader(_io.StringIO(r.text)))
        self.assertEqual([x["Case"] for x in rows], [case["case_no"]])
        self.assertEqual(rows[0]["Department"], "Punjab Police")
        # A month with nothing filed in it is a spreadsheet of headings, not a 404: the office
        # asked for that month and the answer is that the month was empty.
        empty = self.client.get("/api/v2/reports/monthly.csv?month=2001-01", headers=dept)
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(list(_csv.DictReader(_io.StringIO(empty.text))), [])
        self.assertTrue(empty.text.startswith("Case,Department,"))
        self.assertEqual(self.client.get("/api/v2/reports/monthly.csv?month=2026-13", headers=dept).status_code, 422)
        self.assertEqual(self.client.get("/api/v2/reports/monthly.csv?month=october", headers=dept).status_code, 422)

    def test_a_department_downloads_its_own_cases_and_no_others(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        edu = self.login("school-education", "school-education")
        mine = self.create(police)["case"]
        theirs = self.create(edu)["case"]
        month = mine["created_at"][:7]
        text = self.client.get(f"/api/v2/reports/monthly.csv?month={month}", headers=police).text
        self.assertIn(mine["case_no"], text)
        self.assertNotIn(theirs["case_no"], text)
        # And it may not ask for another department's by naming it.
        self.assertEqual(self.client.get(f"/api/v2/reports/monthly.csv?month={month}&department=SCHOOL_EDUCATION",
                                         headers=police).status_code, 403)

    def test_where_cases_are_waiting_is_shown_to_the_roles_that_supervise_the_desks(self) -> None:
        """by_desk is the oversight roles' (23 Oct 2026): the Deputy AG, the AG's own desk and
        the administrator, who reads every register anyway.

        Not a tier officer. A Senior Auditor, an AAO and an AO each hold ONE desk, and a chart
        of how long the others are taking is a view of colleagues' workload, not their own.
        Not a department, which is told the case is with the Office of the Accountant General
        and never which desk holds it.
        """
        admin = self.login("admin", "ag")
        dept = self.login("punjab-police", "punjab-police")
        case = self.create(dept)["case"]
        desks = self.client.get("/api/v2/stats?product=PENSION", headers=admin).json()["by_desk"]
        self.assertEqual([d["desk"] for d in desks], ["RECEIVED", "SENIOR_AUDITOR", "ASSISTANT_AO", "AO"])
        standing = [d for d in desks if d["total"]]
        self.assertEqual(len(standing), 1, desks)
        self.assertEqual(standing[0]["oldest_case"], case["case_no"])
        self.assertEqual(standing[0]["waiting_over_a_week"], 0)       # filed a moment ago

        for who, portal in (("punjab-police", "punjab-police"),            # the department
                            ("tauqeer.ahmad", "ag")):                      # a tier officer
            stats = self.client.get("/api/v2/stats?product=PENSION", headers=self.login(who, portal)).json()
            self.assertNotIn("by_desk", stats, who)
        for who in ("ag.reviewer",):                                       # the AG's own desk
            stats = self.client.get("/api/v2/stats?product=PENSION", headers=self.login(who, "ag")).json()
            self.assertIn("by_desk", stats, who)

    # -- scoping ----------------------------------------------------------------------------

    def test_a_department_sees_only_its_own_cases(self) -> None:
        police, edu = self.login("punjab-police", "punjab-police"), self.login("school-education", "school-education")
        made = self.create(police)
        case_id = made["case"]["id"]
        self.assertEqual(made["case"]["department_code"], "PUNJAB_POLICE")
        self.assertEqual(len(self.client.get("/api/v2/cases", headers=edu).json()), 0)
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=edu).status_code, 403)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/forward", headers=edu, json={}).status_code, 403)
        reviewer = self.sa()
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).status_code, 200)

    def test_a_department_officer_cannot_choose_another_department(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        made = self.create(police, department_code="HEALTH")
        self.assertEqual(made["case"]["department_code"], "PUNJAB_POLICE")

    def test_the_same_papers_from_two_departments_are_two_runs(self) -> None:
        police, edu = self.login("punjab-police", "punjab-police"), self.login("school-education", "school-education")
        a = self.verify(self.sa(), self.create(police)["case"]["id"])["run_id"]
        b = self.verify(self.sa("school-education"), self.create(edu)["case"]["id"])["run_id"]   # each wing's own Senior Auditor
        self.assertNotEqual(a, b)

    # -- lifecycle --------------------------------------------------------------------------

    def test_filing_submits_and_a_clean_verification_waits_for_the_ag_s_decision(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        made = self.create(police, claimant_name="Gulshan Jan")
        case_id = made["case"]["id"]
        self.assertEqual(made["case"]["status"], "FORWARDED")            # filing is submission
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()
        self.assertIsNone(case["latest_run"])
        self.assertNotIn("RUN_CHECK", case["allowed_actions"])            # the verification is the AG's
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/check", headers=police).status_code, 403)

        reviewer = self.sa()
        counts = self.client.get("/api/v2/departments/counts", headers=reviewer).json()
        self.assertEqual(next(c for c in counts if c["code"] == "PUNJAB_POLICE")["awaiting_review"], 1)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertIn("RUN_CHECK", case["allowed_actions"])
        run_id = self.verify(reviewer, case_id)["run_id"]
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        # Nothing missing, no finding -- and still nobody's decision but an officer's (M1, 7 Oct 2026).
        self.assertEqual(case["status"], "UNDER_REVIEW", case["events"][-1])
        self.assertEqual([e["action"] for e in case["events"]], ["CREATE", "FORWARD", "RUN_CHECK", "CHECK_DONE"])
        self.assertEqual(case["events"][-1]["actor_role"], "SYSTEM")
        self.assertTrue(case["events"][-1]["payload"]["nothing_outstanding"])
        self.assertIn("nothing is approved automatically", case["events"][-1]["remark"])
        self.assertEqual(case["latest_run"]["verdict"], "FORWARD")
        self.assertIn("FORWARD_TIER", case["allowed_actions"])         # the Senior Auditor forwards; the AO decides (C3)
        rep = self.client.get(f"/api/v2/cases/{case_id}/runs/{run_id}/report", headers=reviewer)
        self.assertEqual(rep.json()["claimant_name"], "Mst. Gulshan Jan")
        # Up the chain, then the AO approves, by hand and with a remark; the department sees the decision, not the AI's reading.
        r = self.decide(case_id, "approve", {"remark": "Papers complete and in order; approved."})
        self.assertEqual(r.status_code, 200, r.text)
        seen = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()
        self.assertEqual(seen["status"], "APPROVED")
        self.assertEqual(seen["events"][-1]["action"], "APPROVE")
        self.assertEqual(seen["events"][-1]["actor_role"], "AG_AO")
        self.assertNotIn("verdict", seen["latest_run"])
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}/runs/{run_id}/report", headers=police).status_code, 403)
        # The old register agrees: a FORWARD decision was mirrored onto the run.
        self.assertTrue((runs.ARTIFACTS / f"run-{run_id}" / "decisions.jsonl").exists())

    def test_missing_documents_wait_for_the_ag_who_returns_the_case_with_the_list(self) -> None:
        self.report_to_write = FLAGGED_REPORT
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        self.verify(reviewer, case_id)
        # No automatic return (9 Oct 2026): the case waits for the AG, who sees what is missing.
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")
        self.assertEqual(case["events"][-1]["action"], "CHECK_DONE")
        self.assertEqual([i["id"] for i in case["events"][-1]["payload"]["missing_checklist"]], ["AG-06"])
        self.assertIn("missing or defective", case["events"][-1]["remark"])
        seen = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()
        self.assertEqual(seen["status"], "UNDER_REVIEW")
        self.assertNotIn("missing_checklist", seen["events"][-1]["payload"])   # the AI's reading stays at the AG
        self.assertNotIn("ADD_DOCS", seen["allowed_actions"])
        # The AG returns it, naming the paper.
        r = self.client.post(f"/api/v2/cases/{case_id}/return", headers=reviewer,
                             json={"remark": "NADRA FRC missing; attach and resubmit.", "items": [{"id": "AG-06"}]})
        self.assertEqual(r.status_code, 200, r.text)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()
        self.assertEqual(case["status"], "RETURNED")
        last = case["events"][-1]
        self.assertEqual((last["action"], last["actor_role"]), ("RETURN", "AG_SENIOR_AUDITOR"))
        self.assertIn("NADRA FRC", last["remark"])
        self.assertEqual([i["id"] for i in last["payload"]["items"]], ["AG-06"])
        self.assertNotIn("high_flags", last["payload"])                   # findings stay at the AG
        self.assertIn("ADD_DOCS", case["allowed_actions"])
        # Attach the paper and resubmit: a new round, then back on the AG's desk.
        r = self.client.post(f"/api/v2/cases/{case_id}/documents", headers=police,
                             files=[("files", ("frc.pdf", io.BytesIO(PDF2), "application/pdf"))])
        self.assertEqual((r.json()["submission_no"], r.json()["status"]), (2, "DRAFT"))
        r = self.client.post(f"/api/v2/cases/{case_id}/forward", headers=police, json={"remark": "FRC attached."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["case"]["status"], "FORWARDED")
        self.report_to_write = CLEAN_REPORT
        self.verify(reviewer, case_id)
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()["status"], "UNDER_REVIEW")

    def test_findings_wait_for_the_ag_and_clearing_the_last_one_leaves_the_decision_to_the_ag(self) -> None:
        self.report_to_write = FLAGS_ONLY_REPORT
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        run_id = self.verify(reviewer, case_id)["run_id"]
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")
        self.assertEqual(case["events"][-1]["action"], "CHECK_DONE")
        # Approving over an uncleared finding needs a real reason (the AO's call, once the case reaches it).
        ao = self.escalate(case_id)
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=ao, json={"remark": "ok"})
        self.assertEqual(r.status_code, 422)
        # Clearing the finding opens the gate; the case still waits for the officer's own decision (M1).
        r = self.client.post(f"/api/v2/cases/{case_id}/runs/{run_id}/dispositions", headers=ao,
                             json={"flag_id": "F-1", "action": "WAIVE", "ground": "Recovery verified by hand against the LPC."})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(r.json()["gate"]["open"])
        self.assertNotIn("case", r.json())
        seen = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()
        self.assertEqual(seen["status"], "UNDER_REVIEW")
        self.assertEqual(seen["events"][-1]["action"], "CHECK_DONE")
        # With the gate open a plain remark approves (no override needed), and the officer is named.
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=ao, json={"remark": "Cleared; approved."})
        self.assertEqual(r.status_code, 200, r.text)
        seen = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()
        self.assertEqual((seen["status"], seen["events"][-1]["action"]), ("APPROVED", "APPROVE"))

    def test_return_by_hand_add_documents_and_resubmit(self) -> None:
        edu = self.login("school-education", "school-education")
        case_id = self.create(edu)["case"]["id"]
        reviewer = self.sa("school-education")
        self.report_to_write = FLAGS_ONLY_REPORT
        self.verify(reviewer, case_id)                     # every action follows the examination
        r = self.client.post(f"/api/v2/cases/{case_id}/return", headers=reviewer, json={"remark": "Attach the LPC."})
        self.assertEqual(r.json()["case"]["status"], "RETURNED")
        r = self.client.post(f"/api/v2/cases/{case_id}/documents", headers=edu,
                             files=[("files", ("lpc.pdf", io.BytesIO(PDF2), "application/pdf"))])
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["submission_no"], 2)
        self.assertEqual(len(r.json()["documents"]), 2)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/check", headers=edu).status_code, 403)
        r = self.client.post(f"/api/v2/cases/{case_id}/forward", headers=edu, json={"remark": "LPC attached."})
        self.assertEqual(r.json()["case"]["status"], "FORWARDED")
        self.assertEqual(r.json()["case"]["officer_remark"], "LPC attached.")
        self.report_to_write = CLEAN_REPORT                # the corrected papers verify clean
        run_id = self.verify(reviewer, case_id)["run_id"]
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")   # clean, and still the AG's decision (M1)
        self.assertEqual(case["latest_run"]["submission_no"], 2)
        self.assertEqual(case["latest_run"]["run_id"], run_id)

    def test_every_department_files_its_own_case_and_returns_come_back_to_it(self) -> None:
        agri = self.login("agriculture", "agriculture")
        made = self.create(agri)
        self.assertEqual((made["case"]["department_code"], made["case"]["created_via"]), ("AGRICULTURE", "DEPARTMENT"))
        reviewer = self.sa("agriculture")
        counts = self.client.get("/api/v2/departments/counts", headers=reviewer).json()
        self.assertEqual(next(c for c in counts if c["code"] == "AGRICULTURE")["total"], 1)
        names = [c["name"] for c in counts]
        self.assertEqual(names, sorted(names, key=str.lower))            # alphabetical for the sidebar
        self.report_to_write = FLAGS_ONLY_REPORT
        self.verify(reviewer, made["case"]["id"])
        r = self.client.post(f"/api/v2/cases/{made['case']['id']}/request-docs", headers=reviewer,
                             json={"remark": "Need the death certificate."})
        self.assertEqual(r.status_code, 200, r.text)
        mine = self.client.get("/api/v2/cases", headers=agri).json()
        self.assertEqual([c["status"] for c in mine], ["DOCS_REQUESTED"])
        police = self.login("punjab-police", "punjab-police")
        self.assertEqual(self.client.get("/api/v2/cases", headers=police).json(), [])

    def test_the_old_portal_routes_need_a_token_now(self) -> None:
        self.assertEqual(self.client.get("/api/health").status_code, 200)          # reference, open
        self.assertEqual(self.client.get("/api/cases").status_code, 401)           # the old register
        self.assertEqual(self.client.get("/api/runs").status_code, 401)
        # The old routes know no departments, wings or tiers, so a department's token opens none
        # of them and neither does a tier officer's (audit of 12 Oct 2026: a Senior Auditor could
        # list every run and open any wing's report there); the AG's desk and the administrator
        # read, and only the Deputy AG may act there.
        police = self.login("punjab-police", "punjab-police")
        self.assertEqual(self.client.get("/api/runs", headers=police).status_code, 403)
        senior_auditor = self.sa()
        r = self.client.get("/api/runs", headers=senior_auditor)
        self.assertEqual(r.status_code, 403)
        self.assertIn("case system", r.json()["detail"])
        reviewer = self.login("ag.reviewer", "ag")
        self.assertEqual(self.client.get("/api/runs", headers=reviewer).status_code, 200)
        self.assertEqual(self.client.post("/api/runs", headers=reviewer).status_code, 403)
        admin = self.login("admin", "ag")
        self.assertEqual(self.client.get("/api/runs", headers=admin).status_code, 200)

    def test_a_locked_out_caller_does_not_lock_the_account_for_others(self) -> None:
        """Five wrong passwords from one address lock that address out of the account for a
        minute; the officer signing in from their own machine is unaffected."""
        for _ in range(5):
            self.client.post("/api/v2/auth/login", json={"username": "admin", "password": "nope"},
                             headers={"X-Portal": "ag", "X-Forwarded-For": "10.9.9.9"})
        r = self.client.post("/api/v2/auth/login", json={"username": "admin", "password": db.SEED_PASSWORD},
                             headers={"X-Portal": "ag", "X-Forwarded-For": "10.9.9.9"})
        self.assertEqual(r.status_code, 429)
        r = self.client.post("/api/v2/auth/login", json={"username": "admin", "password": db.SEED_PASSWORD},
                             headers={"X-Portal": "ag", "X-Forwarded-For": "10.1.1.1"})
        self.assertEqual(r.status_code, 200)

    def test_a_department_token_opens_no_other_department_run(self) -> None:
        """Run-keyed routes are scoped to the case's department, whoever knows the run id."""
        self.report_to_write = FLAGGED_REPORT
        police, edu = self.login("punjab-police", "punjab-police"), self.login("school-education", "school-education")
        made = self.create(police)
        reviewer = self.sa()
        run_id = self.verify(reviewer, made["case"]["id"])["run_id"]
        for path in (f"/api/v2/runs/{run_id}/report", f"/api/v2/runs/{run_id}/pages/1", f"/api/v2/runs/{run_id}/events"):
            self.assertIn(self.client.get(path, headers=edu).status_code, (403, 404), path)
            self.assertIn(self.client.get(path, headers=police).status_code, (403, 404), path)   # nor its own: the findings are the AG's
        self.assertEqual(self.client.get(f"/api/v2/runs/{run_id}/report", headers=reviewer).status_code, 200)

    def test_findings_cannot_be_changed_once_the_case_has_left_the_ag(self) -> None:
        self.report_to_write = FLAGS_ONLY_REPORT
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        run_id = self.verify(reviewer, case_id)["run_id"]
        self.decide(case_id, "reject", {"remark": "Recovery stands; the case fails."})
        body = {"flag_id": "F-1", "action": "WAIVE", "ground": "Verified against the original by hand."}
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/runs/{run_id}/dispositions", headers=reviewer, json=body).status_code, 409)

    def test_adding_documents_after_a_return_opens_one_new_round_only(self) -> None:
        edu = self.login("school-education", "school-education")
        case_id = self.create(edu)["case"]["id"]
        reviewer = self.sa("school-education")
        self.report_to_write = FLAGS_ONLY_REPORT
        self.verify(reviewer, case_id)
        self.client.post(f"/api/v2/cases/{case_id}/return", headers=reviewer, json={"remark": "Attach the LPC."})
        for name in ("lpc.pdf", "frc.pdf"):
            r = self.client.post(f"/api/v2/cases/{case_id}/documents", headers=edu,
                                 files=[("files", (name, io.BytesIO(PDF2 + name.encode()), "application/pdf"))])
            self.assertEqual(r.status_code, 201, r.text)
            self.assertEqual((r.json()["submission_no"], r.json()["status"]), (2, "DRAFT"))

    def test_a_refused_decision_does_not_take_the_case_up(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        self.report_to_write = FLAGS_ONLY_REPORT
        self.verify(reviewer, case_id)
        r = self.client.post(f"/api/v2/cases/{case_id}/return", headers=reviewer, json={"remark": ""})
        self.assertEqual(r.status_code, 422)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")
        self.assertEqual([e["action"] for e in case["events"]][-1], "CHECK_DONE")   # nothing recorded for the refusal

    def test_a_failed_check_stays_with_the_ag_to_verify_again(self) -> None:
        self.fail_runs = True
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        self.verify(reviewer, case_id)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(case["status"], "AI_FAILED")
        self.assertIn("vision", case["events"][-1]["remark"])
        self.assertIn("RUN_CHECK", case["allowed_actions"])
        # The department cannot touch a case the AG holds, and is not told the engine's error.
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/documents", headers=police,
                                          files=[("files", ("more.pdf", io.BytesIO(PDF2), "application/pdf"))]).status_code, 409)
        self.assertNotIn("error", self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()["latest_run"])
        # Verifying again on the SAME papers resumes the same run id: one row, started afresh, and
        # the reconciler's sweep must not mistake it for the old failure (audit A-3).
        self.fail_runs = False
        self.verify(reviewer, case_id)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(case["status"], "UNDER_REVIEW", case["events"][-1])
        self.assertEqual(case["events"][-1]["action"], "CHECK_DONE")
        self.assertEqual(len(case["runs"]), 1, "a re-run of the same papers is the same run, not a second row")

    # -- GP Fund cases: the second product, examined by the GP Fund module ---------------------

    @staticmethod
    def _gpf_view(hard_doc: bool = False, conf: bool = False, disp: str | None = None) -> dict:
        hard = [{"id": "r-a3", "code": "A3", "title": "Attested CNIC copy", "doc": "CNIC copy",
                 "cure": {"kind": "doc"}, "disposition": None, "status": "hard"}] if hard_doc else []
        confs = [{"id": "v-1", "code": "R4", "title": "Signature to verify", "cure": {"kind": "verify"}, "status": "conf"}] if conf else []
        return {"id": "gpf-case-1", "version": 1, "caseDisp": disp, "caseNote": "", "meta": {"label": "Refundable (from scans)"},
                "lists": {"hard": hard, "adv": [], "conf": confs, "sap": [], "ok": []},
                "position": {"hard": len(hard), "adv": 0, "open": len(hard), "conf": len(confs), "sap": 0, "total": len(hard)}}

    def _gpf_module(self, view: dict):
        """The GP Fund module, stubbed: the read finishes at once and its case reads as `view`."""
        patches = [mock.patch.object(gpf_bridge, "start_examination", lambda *a, **k: {"jobId": "job-1", "state": "running"}),
                   mock.patch.object(gpf_bridge, "job", lambda job_id: {"jobId": job_id, "state": "done", "done": 3, "total": 3,
                                                                          "result": {"id": "gpf-case-1"}}),
                   mock.patch.object(gpf_bridge, "case", lambda cid: view),
                   mock.patch.object(gpf_bridge, "health", lambda: {"ok": True})]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def test_a_gp_fund_case_is_filed_under_its_product_and_needs_a_kind(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        r = self.client.post("/api/v2/cases", headers=police, data={"product": "GPF"},
                             files=[("files", ("case.pdf", io.BytesIO(PDF), "application/pdf"))])
        self.assertEqual(r.status_code, 422)                          # the kind of claim is required
        made = self.create(police, product="GPF", gpf_kind="refundable", claimant_name="Subscriber F. Test")
        self.assertEqual((made["case"]["product"], made["case"]["status"]), ("GPF", "FORWARDED"))
        self.assertEqual(made["case"]["intake"]["gpf_kind"], "refundable")
        self.assertEqual(len(self.client.get("/api/v2/cases?product=GPF", headers=police).json()), 1)
        self.assertEqual(len(self.client.get("/api/v2/cases?product=PENSION", headers=police).json()), 0)
        self.assertEqual(self.client.get("/api/v2/cases?product=JUNK", headers=police).status_code, 422)
        reviewer = self.sa()
        counts = self.client.get("/api/v2/departments/counts?product=PENSION", headers=reviewer).json()
        self.assertEqual(next(c for c in counts if c["code"] == "PUNJAB_POLICE")["total"], 0)
        counts = self.client.get("/api/v2/departments/counts?product=GPF", headers=reviewer).json()
        self.assertEqual(next(c for c in counts if c["code"] == "PUNJAB_POLICE")["awaiting_review"], 1)
        st = self.client.get("/api/v2/stats?product=GPF", headers=reviewer).json()
        self.assertEqual((st["total"], st["scope"]["product"]), (1, "GPF"))
        # The department's screens never reach the module.
        self.assertEqual(self.client.get(f"/api/v2/cases/{made['case']['id']}/gpf", headers=police).status_code, 403)

    def test_a_gp_fund_examination_with_a_missing_document_waits_for_the_ag(self) -> None:
        self._gpf_module(self._gpf_view(hard_doc=True))
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police, product="GPF", gpf_kind="refundable")["case"]["id"]
        reviewer = self.sa()
        r = self.verify(reviewer, case_id)
        self.assertTrue(r["run_id"].startswith(case_runs.GPF_RUN_PREFIX))
        # No automatic return (9 Oct 2026): the AG sees the missing paper and decides.
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")
        last = case["events"][-1]
        self.assertEqual(last["action"], "CHECK_DONE")
        self.assertEqual([m["id"] for m in last["payload"]["missing_checklist"]], ["A3"])
        seen = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()
        self.assertEqual(seen["status"], "UNDER_REVIEW")
        self.assertNotIn("gpf", seen["events"][-1]["payload"])          # the module's reading stays at the AG
        self.assertNotIn("missing_checklist", seen["events"][-1]["payload"])
        r = self.client.post(f"/api/v2/cases/{case_id}/return", headers=reviewer,
                             json={"remark": "CNIC copy missing; attach and resubmit.",
                                   "items": [{"label": "CNIC copy of the subscriber"}]})
        self.assertEqual(r.status_code, 200, r.text)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()
        self.assertEqual((case["status"], case["events"][-1]["action"]), ("RETURNED", "RETURN"))
        self.assertIn("CNIC", case["events"][-1]["remark"])
        full = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(full["gpf_case_id"], "gpf-case-1")
        g = self.client.get(f"/api/v2/cases/{case_id}/gpf", headers=reviewer).json()
        self.assertEqual(g["case"]["counts"]["hard"], 1)
        self.assertIn("#/case/gpf-case-1", g["embed_url"])

    def test_a_gp_fund_case_waits_for_the_officer_and_follows_their_disposal(self) -> None:
        self._gpf_module(self._gpf_view(conf=True))
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police, product="GPF", gpf_kind="final")["case"]["id"]
        reviewer = self.sa()
        self.verify(reviewer, case_id)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")               # a verification task: the officer decides
        # The officer passes the case for payment in the module's own screens. The pension-side case
        # still waits for the AG's own approval (M1, 7 Oct 2026): nothing moves it by itself.
        self._gpf_module(self._gpf_view(conf=False, disp="passed for payment"))
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")
        self.assertIn("FORWARD_TIER", case["allowed_actions"])
        r = self.decide(case_id, "approve", {"remark": "Passed in the GP Fund examination; approved."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()["status"], "APPROVED")

    def test_a_clean_gp_fund_examination_waits_for_the_ag_and_so_does_a_return_made_in_the_module(self) -> None:
        self._gpf_module(self._gpf_view())
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police, product="GPF", gpf_kind="balance_transfer")["case"]["id"]
        reviewer = self.sa()
        self.verify(reviewer, case_id)
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()["status"], "UNDER_REVIEW")
        # A second case: the officer returns it from the module after examination.
        self._gpf_module(self._gpf_view(conf=True))
        other = self.create(police, product="GPF", gpf_kind="death")["case"]["id"]
        self.verify(reviewer, other)
        self.assertEqual(self.client.get(f"/api/v2/cases/{other}", headers=reviewer).json()["status"], "UNDER_REVIEW")
        self._gpf_module(self._gpf_view(hard_doc=True, disp="returned"))
        # The module's own return moves nothing on the pension side (9 Oct 2026: no automatic
        # return); the case waits until the AG returns it with the Return button.
        case = self.client.get(f"/api/v2/cases/{other}", headers=police).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")
        self.assertNotIn("GPF_RETURN", [e["action"] for e in case["events"]])
        r = self.client.post(f"/api/v2/cases/{other}/return", headers=reviewer,
                             json={"remark": "Returned after the GP Fund examination: CNIC copy missing."})
        self.assertEqual(r.status_code, 200, r.text)
        case = self.client.get(f"/api/v2/cases/{other}", headers=police).json()
        self.assertEqual((case["status"], case["events"][-1]["action"], case["events"][-1]["actor_role"]),
                         ("RETURNED", "RETURN", "AG_SENIOR_AUDITOR"))

    def test_uploads_must_be_documents_and_names_are_bounded(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        r = self.client.post("/api/v2/cases", headers=police, data={"case_type": "FRESH_SELF"},
                             files=[("files", ("x.pdf", io.BytesIO(b"just some text, not a PDF"), "application/pdf"))])
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("x.pdf", r.json()["detail"])
        r = self.client.post("/api/v2/cases", headers=police, data={"claimant_name": "Z" * 300, "case_type": "FRESH_SELF"},
                             files=[("files", ("ok.pdf", io.BytesIO(PDF), "application/pdf"))])
        self.assertEqual(r.status_code, 422, r.text)
        r = self.client.post("/api/v2/cases", headers=police, data={"claimant_name": "Mst.\x07 Gulshan", "case_type": "FRESH_SELF"},
                             files=[("files", ("ok.pdf", io.BytesIO(PDF), "application/pdf"))])
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["case"]["claimant_name"], "Mst. Gulshan")

    def test_unknown_filters_and_no_op_overrides_are_refused(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        self.assertEqual(self.client.get("/api/v2/cases?status_filter=JUNK", headers=police).status_code, 422)
        self.assertEqual(self.client.get("/api/v2/cases?department=SCHOOL_EDUCATION", headers=police).status_code, 403)
        case_id = self.create(police)["case"]["id"]
        dag = self.login("fatima.hameed", "ag")
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=dag,
                             json={"to_status": "FORWARDED", "reason": "nothing changes here"})
        self.assertEqual(r.status_code, 409, r.text)

    def test_a_decision_needs_a_completed_verification(self) -> None:
        """Approve, reject, return and request-documents all wait for the AI examination of the
        papers as submitted (29 Sep 2026); only the examination itself comes first."""
        self.report_to_write = FLAGS_ONLY_REPORT
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        for a in ("APPROVE", "REJECT", "RETURN", "REQUEST_DOCS"):
            self.assertNotIn(a, case["allowed_actions"])
        self.assertIn("RUN_CHECK", case["allowed_actions"])
        for action in ("approve", "reject", "return", "request-docs"):
            r = self.client.post(f"/api/v2/cases/{case_id}/{action}", headers=reviewer, json={"remark": "Verified by hand; in order."})
            self.assertEqual(r.status_code, 409, r.text)
            self.assertIn("verify the case with AI", r.json()["detail"])
        # A verification that did not complete does not count.
        self.fail_runs = True
        self.verify(reviewer, case_id)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(case["status"], "AI_FAILED")
        self.assertNotIn("APPROVE", case["allowed_actions"])
        self.fail_runs = False
        self.verify(reviewer, case_id)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")
        for a in ("FORWARD_TIER", "RETURN", "REQUEST_DOCS"):
            self.assertIn(a, case["allowed_actions"])
        # Sent back and resubmitted: the new round of papers needs its own examination.
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/return", headers=reviewer, json={"remark": "attach the FRC"}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/documents", headers=police,
                                          files=[("files", ("frc.pdf", io.BytesIO(PDF2), "application/pdf"))]).status_code, 201)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/forward", headers=police, json={"remark": "attached"}).status_code, 200)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertNotIn("FORWARD_TIER", case["allowed_actions"]); self.assertNotIn("RETURN", case["allowed_actions"])
        # The AO is refused: the new filing has not been sent up to the AO's desk (12 Oct 2026).
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/reject", headers=self.ao(), json={"remark": "still wrong papers"}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/return", headers=reviewer, json={"remark": "still wrong papers"}).status_code, 409)

    def test_admin_override_is_audited(self) -> None:
        self.report_to_write = FLAGS_ONLY_REPORT                    # a finding, so the case waits for the AG
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=self.ao(), json={"remark": "Verified by hand; in order."})
        self.assertEqual(r.status_code, 403)                         # the SA holds it: not yet sent to the AO's desk
        self.verify(reviewer, case_id)
        ao = self.escalate(case_id)
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=ao, json={"remark": "In order."})
        self.assertEqual(r.status_code, 422)                         # approving over a finding needs a real reason
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=ao, json={"remark": "Verified by hand; in order."})
        self.assertEqual(r.status_code, 200, r.text)
        dag = self.login("fatima.hameed", "ag")
        admin = self.login("admin", "ag")
        # The administrator takes no case action (G6); the Deputy AG overrides.
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/override", headers=admin,
                                          json={"to_status": "RETURNED", "reason": "Approved on the wrong file."}).status_code, 403)
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=dag, json={"to_status": "RETURNED"})
        self.assertEqual(r.status_code, 422)                         # reason required
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=dag,
                             json={"to_status": "RETURNED", "reason": "Approved on the wrong file."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["case"]["status"], "RETURNED")
        log = self.client.get("/api/v2/admin/audit-log", headers=admin).json()
        self.assertEqual(log[0]["action"], "CASE_OVERRIDE")
        self.assertEqual((log[0]["before"], log[0]["after"]), ({"status": "APPROVED"}, {"status": "RETURNED"}))
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/override", headers=reviewer,
                                          json={"to_status": "APPROVED", "reason": "x"}).status_code, 403)

    def test_page_and_event_routes_take_a_query_token_but_case_reads_do_not(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        run_id = self.verify(reviewer, case_id)["run_id"]
        token = reviewer["Authorization"].split(" ", 1)[1]
        r = self.client.get(f"/api/v2/cases/{case_id}/runs/{run_id}/pages/1?token={token}")
        self.assertEqual(r.status_code, 404)                         # authorised; the stub has no pages
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}?token={token}").status_code, 401)
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}/runs/nope/report", headers=reviewer).status_code, 404)

    def test_old_portal_runs_are_imported_once_under_the_legacy_department(self) -> None:
        from api import legacy
        run_dir = runs.ARTIFACTS / "run-abcdef123456"
        run_dir.mkdir(parents=True)
        (run_dir / "case_report.json").write_text(json.dumps(FLAGGED_REPORT))
        (run_dir / "decisions.jsonl").write_text(json.dumps({
            "action": "RETURN_FOR_CORRECTION", "officer": "Syed Haider", "justification": "FRC missing",
            "at": "2026-09-20T10:00:00"}) + "\n")
        (runs.ARTIFACTS / "uploads").mkdir(exist_ok=True)
        (runs.ARTIFACTS / "uploads" / "abcdef123456-widow.pdf").write_bytes(PDF)
        self.assertEqual(legacy.import_legacy_runs(), 1)
        self.assertEqual(legacy.import_legacy_runs(), 0)                 # idempotent
        reviewer = self.login("ag.reviewer", "ag")                       # the legacy bucket has no wing: the AG's desk reads every wing
        rows = self.client.get("/api/v2/cases", headers=reviewer).json()
        leg = next(r for r in rows if r["case_no"] == "LEGACY-abcdef123456")
        self.assertEqual((leg["status"], leg["department_code"], leg["claimant_name"], leg["created_via"]),
                         ("RETURNED", "LEGACY", "Fozia Akhtar", "DEPARTMENT"))
        full = self.client.get(f"/api/v2/cases/{leg['id']}", headers=reviewer).json()
        self.assertEqual([e["action"] for e in full["events"]], ["CREATE", "CHECK_DONE", "FORWARD", "TAKE_UP", "RETURN"])
        self.assertEqual(full["events"][-1]["remark"], "FRC missing")
        self.assertEqual(len(full["documents"]), 1)
        rep = self.client.get(f"/api/v2/runs/abcdef123456/report", headers=reviewer)
        self.assertEqual(rep.status_code, 200)
        police = self.login("punjab-police", "punjab-police")
        self.assertEqual(self.client.get("/api/v2/cases", headers=police).json(), [])
        # The import user cannot sign in.
        r = self.client.post("/api/v2/auth/login", json={"username": "legacy.import", "password": "x"}, headers={"X-Portal": "ag"})
        self.assertEqual(r.status_code, 401)

    def test_stats_are_scoped_and_agree_with_the_register(self) -> None:
        police, edu = self.login("punjab-police", "punjab-police"), self.login("school-education", "school-education")
        self.create(police); self.create(edu)
        st = self.client.get("/api/v2/stats", headers=police).json()
        self.assertEqual(st["total"], 1)
        self.assertEqual(st["by_status"]["FORWARDED"], 1)
        self.assertEqual(len(st["weeks"]), 12)
        self.assertEqual(st["weeks"][-1]["filed"], 1)
        # The engine's verdicts and findings are AI output: never in a department's statistics.
        for key in ("verdicts", "high_flags", "deficiencies"):
            self.assertNotIn(key, st)
        rev = self.login("fatima.hameed", "ag")                         # the Deputy AG sees every wing (a tier officer sees one)
        st = self.client.get("/api/v2/stats", headers=rev).json()
        self.assertEqual(st["verdicts"]["FORWARD"], 0)                # nothing verified yet
        self.assertEqual(st["total"], 2)
        self.assertEqual({d["code"] for d in st["by_department"]}, {"PUNJAB_POLICE", "SCHOOL_EDUCATION"})
        st = self.client.get("/api/v2/stats?department=PUNJAB_POLICE", headers=rev).json()
        self.assertEqual(st["total"], 1)
        admin = self.login("admin", "ag")
        st = self.client.get("/api/v2/stats", headers=admin).json()
        self.assertIn("users_by_role", st)
        # The two figures the dashboards chart: ageing of the pending cases and the top deficiencies.
        age = st["ageing"]
        self.assertEqual(age["with_ag"]["total"], 2)                  # both cases sit at FORWARDED, just filed
        self.assertEqual(age["with_ag"]["buckets"]["0-3"], 2)
        self.assertEqual(age["with_department"]["total"], 0)
        self.assertIsNotNone(age["with_ag"]["oldest_case"])
        d = st["deficiencies"]
        self.assertEqual(d["verified_cases"], 0)
        for item in d["items"]:
            self.assertEqual(set(item), {"id", "requirement", "missing", "defective"})
            self.assertGreater(item["missing"] + item["defective"], 0)

    # -- the declared case type (29 Sep 2026) ---------------------------------------------------

    TYPED_REPORT = {**FLAGS_ONLY_REPORT,            # a finding, so the case waits for the AG
                    "case_type": {"case_type": "FAMILY_PENSION_DEATH_IN_SERVICE", "case_type_confidence": 1.0,
                                  "source": "declared", "declared": "DEATH_IN_SERVICE",
                                  "detected": "FAMILY_PENSION_DEATH_AFTER_RETIREMENT"},
                    "case_type_detected": {"case_type": "FAMILY_PENSION_DEATH_AFTER_RETIREMENT", "case_type_confidence": 0.98},
                    "case_variant": "WIDOW", "case_variant_source": "detected"}

    def test_a_pension_case_needs_a_declared_type(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        r = self.client.post("/api/v2/cases", headers=police, data={},
                             files=[("files", ("ok.pdf", io.BytesIO(PDF), "application/pdf"))])
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["detail"], "select the case type before submitting the case")
        # The pipeline's own path names are not what a DDO files under; the sheet's columns are.
        r = self.client.post("/api/v2/cases", headers=police, data={"case_type": "SUPERANNUATION_PENSION"},
                             files=[("files", ("ok.pdf", io.BytesIO(PDF), "application/pdf"))])
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("unknown case type", r.json()["detail"])
        # A checklist column other than the type's own is refused, not quietly accepted.
        r = self.client.post("/api/v2/cases", headers=police, data={"case_type": "FRESH_SELF", "variant": "WIDOW"},
                             files=[("files", ("ok.pdf", io.BytesIO(PDF), "application/pdf"))])
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("not a kind of Fresh – Self", r.json()["detail"])
        self.assertEqual(self.client.get("/api/v2/cases?case_type=NOPE", headers=police).status_code, 422)

    def test_the_declared_type_is_stored_reaches_the_run_and_the_reading_comes_back(self) -> None:
        self.report_to_write = self.TYPED_REPORT
        police = self.login("punjab-police", "punjab-police")
        made = self.create(police, case_type="WIDOW")["case"]
        self.assertEqual((made["case_type"], made["case_type_source"], made["variant"]), ("WIDOW", "DECLARED", "WIDOW"))
        self.assertEqual(made["events"][0]["payload"]["case_type"], "WIDOW")
        # The office type is its own checklist column, set without being asked.
        auto = self.create(police, case_type="FRESH_SELF")["case"]
        self.assertEqual(auto["variant"], "FRESH_SELF")

        reviewer = self.sa()
        run_id = self.verify(reviewer, made["id"])["run_id"]
        intake = json.loads((runs.ARTIFACTS / f"run-{run_id}" / "intake.json").read_text())
        self.assertEqual(intake["declared_case_type"], "WIDOW")
        self.assertEqual(intake["variant"], "WIDOW")
        case = self.client.get(f"/api/v2/cases/{made['id']}", headers=reviewer).json()
        # The declaration stands; what the AI read is recorded beside it, for the AG only.
        self.assertEqual((case["case_type"], case["case_type_source"]), ("WIDOW", "DECLARED"))
        self.assertEqual(case["detected_case_type"], "FAMILY_PENSION_DEATH_AFTER_RETIREMENT")
        self.assertEqual(case["detected_case_type_confidence"], 0.98)
        seen = self.client.get(f"/api/v2/cases/{made['id']}", headers=police).json()
        self.assertEqual(seen["case_type"], "WIDOW")
        self.assertIsNone(seen["detected_case_type"])
        # The list filters and the listing carries the type.
        rows = self.client.get("/api/v2/cases?case_type=FRESH_SELF", headers=reviewer).json()
        self.assertEqual([r["id"] for r in rows], [auto["id"]])
        kinds = self.client.get("/api/v2/case-types", headers=police).json()["case_types"]
        self.assertEqual([k["id"] for k in kinds], ["FRESH_SELF", "FRESH_INVALID", "REVISED", "DEATH_IN_SERVICE", "WIDOW",
                                                     "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER",
                                                     "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"])   # the sheet's columns
        widow = next(k for k in kinds if k["id"] == "WIDOW")
        self.assertEqual(widow["label"], "Widow / Widower")
        self.assertTrue(any("widow certificate" in d["requirement"].lower() for d in widow["documents"]))
        self.assertEqual(next(k for k in kinds if k["id"] == "FRESH_SELF")["pipeline_types"], ["SUPERANNUATION_PENSION", "RETIRING_PENSION"])

    def test_the_department_changes_its_declaration_before_forwarding_and_the_ag_corrects_with_a_remark(self) -> None:
        self.report_to_write = self.TYPED_REPORT
        police = self.login("punjab-police", "punjab-police")
        reviewer = self.sa()
        case_id = self.create(police, case_type="DEATH_IN_SERVICE")["case"]["id"]
        # Filed means forwarded: the department can no longer change it ...
        r = self.client.post(f"/api/v2/cases/{case_id}/case-type", headers=police, json={"case_type": "FRESH_SELF"})
        self.assertEqual(r.status_code, 409, r.text)
        # ... until the AG sends it back.
        self.verify(reviewer, case_id)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/return", headers=reviewer,
                                          json={"remark": "wrong papers for the type declared"}).status_code, 200)
        r = self.client.post(f"/api/v2/cases/{case_id}/case-type", headers=police, json={"case_type": "PARENT"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["case_type"], r.json()["case_type_source"], r.json()["variant"]), ("PARENT", "DECLARED", "PARENT"))
        self.assertEqual(r.json()["events"][-1]["action"], "SET_CASE_TYPE")
        self.assertEqual(r.json()["events"][-1]["payload"], {"from": "DEATH_IN_SERVICE", "to": "PARENT", "source": "DECLARED", "variant": "PARENT"})
        self.assertEqual(r.json()["status"], "RETURNED")          # the status is untouched
        # The same again is a no-op, refused.
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/case-type", headers=police, json={"case_type": "PARENT"}).status_code, 409)
        # The AG needs a remark; the correction is audited with before and after.
        r = self.client.post(f"/api/v2/cases/{case_id}/case-type", headers=reviewer, json={"case_type": "FRESH_INVALID"})
        self.assertEqual(r.status_code, 422, r.text)
        r = self.client.post(f"/api/v2/cases/{case_id}/case-type", headers=reviewer,
                             json={"case_type": "FRESH_INVALID", "remark": "Form B-IV and the medical board's finding are on file"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["case_type"], r.json()["case_type_source"], r.json()["variant"]), ("FRESH_INVALID", "CORRECTED", "FRESH_INVALID"))
        self.assertEqual(r.json()["events"][-1]["payload"]["detected_case_type"], "FAMILY_PENSION_DEATH_AFTER_RETIREMENT")
        admin = self.login("admin", "ag")
        log = self.client.get("/api/v2/admin/audit-log", headers=admin).json()
        entry = next(e for e in log if e["action"] == "CASE_TYPE_CORRECTED")
        self.assertEqual(entry["before"]["case_type"], "PARENT")
        self.assertEqual(entry["after"], {"case_type": "FRESH_INVALID", "case_type_source": "CORRECTED", "variant": "FRESH_INVALID"})
        self.assertEqual(entry["reason"], "Form B-IV and the medical board's finding are on file")
        # A department sees the event but not what the AI read.
        seen = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()
        self.assertNotIn("detected_case_type", seen["events"][-1]["payload"])
        # The corrected type steers the next verification, once the department has resubmitted.
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/documents", headers=police,
                                          files=[("files", ("more.pdf", io.BytesIO(PDF2), "application/pdf"))]).status_code, 201)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/forward", headers=police, json={"remark": "resubmitted"}).status_code, 200)
        run_id = self.verify(reviewer, case_id)["run_id"]
        intake = json.loads((runs.ARTIFACTS / f"run-{run_id}" / "intake.json").read_text())
        self.assertEqual(intake["declared_case_type"], "FRESH_INVALID")

    def test_a_case_without_a_declared_type_takes_the_detected_one(self) -> None:
        self.report_to_write = self.TYPED_REPORT
        police = self.login("punjab-police", "punjab-police")
        reviewer = self.sa()
        case_id = self.create(police, case_type="FRESH_SELF")["case"]["id"]
        conn = db.connect()
        conn.execute("UPDATE cases SET case_type = NULL, case_type_source = NULL, variant = NULL WHERE id = ?", (case_id,))   # filed before 29 Sep
        conn.close()
        self.verify(reviewer, case_id)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        # A D-II reading with the claimant column detected lands on that column of the sheet.
        self.assertEqual((case["case_type"], case["case_type_source"], case["variant"]), ("WIDOW", "DETECTED", "WIDOW"))
        self.assertEqual(case["detected_case_type"], "FAMILY_PENSION_DEATH_AFTER_RETIREMENT")
        # ... and the start-up backfill does the same from the last report, once, and converts a
        # case still typed by a pipeline path onto the office's column.
        conn = db.connect()
        conn.execute("UPDATE cases SET case_type = NULL, case_type_source = NULL, variant = NULL WHERE id = ?", (case_id,))
        self.assertEqual(case_runs.backfill_case_types(conn), 1)
        self.assertEqual(case_runs.backfill_case_types(conn), 0)
        row = conn.execute("SELECT case_type, case_type_source FROM cases WHERE id = ?", (case_id,)).fetchone()
        self.assertEqual(tuple(row), ("WIDOW", "DETECTED"))
        conn.execute("UPDATE cases SET case_type = 'FAMILY_PENSION_DEATH_IN_SERVICE', variant = NULL WHERE id = ?", (case_id,))
        self.assertEqual(case_runs.backfill_case_types(conn), 1)
        row = conn.execute("SELECT case_type, variant FROM cases WHERE id = ?", (case_id,)).fetchone()
        conn.close()
        self.assertEqual(tuple(row), ("DEATH_IN_SERVICE", "DEATH_IN_SERVICE"))

    def test_departments_carry_their_pension_section_and_the_sections_add_up(self) -> None:
        """AG Review groups departments by the Pension section that works them (29 Sep 2026)."""
        from api.departments import DEPARTMENTS, LEGACY_DEPARTMENT, PENSION_SECTION_ORDER
        reviewer = self.login("fatima.hameed", "ag")                    # across every wing: the Deputy AG
        police = self.login("punjab-police", "punjab-police")
        edu = self.login("school-education", "school-education")
        self.create(police); self.create(police); self.create(edu)
        depts = self.client.get("/api/v2/departments", headers=reviewer).json()
        self.assertEqual(len(depts), len(DEPARTMENTS))
        self.assertTrue(all(d["pension_section"] in PENSION_SECTION_ORDER for d in depts), "every department is in a section")
        self.assertEqual(next(d for d in depts if d["code"] == "PUNJAB_POLICE")["pension_section"], "Pension-V")
        self.assertEqual(next(d for d in depts if d["code"] == "SCHOOL_EDUCATION")["pension_section"], "Pension-III")
        counts = self.client.get("/api/v2/departments/counts", headers=reviewer).json()
        by_section: dict[str, int] = {}
        for c in counts:
            by_section[c["pension_section"] or LEGACY_DEPARTMENT[0]] = by_section.get(c["pension_section"] or LEGACY_DEPARTMENT[0], 0) + c["total"]
        self.assertEqual(sum(by_section.values()), sum(c["total"] for c in counts))
        self.assertEqual((by_section.get("Pension-V"), by_section.get("Pension-III")), (2, 1))
        # The list and the statistics narrow to a section; a case carries its section.
        rows = self.client.get("/api/v2/cases?pension_section=Pension-V", headers=reviewer).json()
        self.assertEqual({r["department_code"] for r in rows}, {"PUNJAB_POLICE"})
        self.assertEqual({r["pension_section"] for r in rows}, {"Pension-V"})
        self.assertEqual(self.client.get("/api/v2/stats?pension_section=Pension-III", headers=reviewer).json()["total"], 1)
        self.assertEqual(self.client.get("/api/v2/stats", headers=reviewer).json()["total"], 3)
        self.assertEqual(self.client.get("/api/v2/cases?pension_section=Pension-IX", headers=reviewer).status_code, 422)
        self.assertEqual(self.client.get("/api/v2/cases?pension_section=LEGACY", headers=reviewer).json(), [])

    def test_every_case_system_route_needs_a_session(self) -> None:
        """Every /api/v2 route except sign-in and the public portal list answers 401 without a
        token -- cases, documents, stats, findings, admin. Walks the router so a new route cannot
        be added open by mistake."""
        from api.v2 import router
        # Sign-out only clears the GP Fund frame cookie, and must work after the session has gone.
        open_paths = {"/api/v2/auth/login", "/api/v2/portals", "/api/v2/auth/logout"}
        seen = 0
        for route in router.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", None) or set()
            if not path or path in open_paths:
                continue
            concrete = path.replace("{case_id}", "nope").replace("{doc_id}", "nope").replace("{run_id}", "nope") \
                           .replace("{flag_id}", "nope").replace("{item_id}", "nope").replace("{user_id}", "nope") \
                           .replace("{page}", "1").replace("{n}", "1")
            import re
            concrete = re.sub(r"\{[^}]+\}", "x", concrete)
            for method in methods - {"HEAD", "OPTIONS"}:
                r = self.client.request(method, concrete)
                self.assertEqual(r.status_code, 401, f"{method} {concrete} answered {r.status_code}")
                self.assertEqual(r.headers.get("cache-control"), "no-store", f"{method} {concrete} is cacheable")
                seen += 1
        self.assertGreater(seen, 20)
        # A document by direct address, with and without a session token on the query string.
        police = self.login("punjab-police", "punjab-police")
        made = self.create(police)
        case_id = made["case"]["id"] if "case" in made else made["id"]
        doc = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()["documents"][0]
        url = f"/api/v2/cases/{case_id}/documents/{doc['id']}"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url + "?token=" + police["Authorization"].split()[1]).status_code, 200)

    def test_only_the_admin_reads_the_credentials_sheet_and_it_is_audited(self) -> None:
        admin = self.login("admin", "ag")
        police = self.login("punjab-police", "punjab-police")
        self.assertEqual(self.client.get("/api/v2/admin/credentials", headers=police).status_code, 403)
        self.assertEqual(self.client.get("/api/v2/admin/credentials").status_code, 401)
        r = self.client.get("/api/v2/admin/credentials", headers=admin)
        self.assertEqual(r.status_code, 200)
        self.assertIn("sign-in credentials", r.text)
        log = self.client.get("/api/v2/admin/audit-log", headers=admin).json()
        self.assertEqual(log[0]["action"], "CREDENTIALS_VIEWED")

    def test_admin_creates_a_user_who_can_log_in(self) -> None:
        admin = self.login("admin", "ag")
        r = self.client.post("/api/v2/admin/users", headers=admin,
                             json={"username": "edu.two", "display_name": "Second SED officer", "role": "DEPT_OFFICER",
                                   "department_code": "SCHOOL_EDUCATION", "password": "Copper-Harbour-Falcon-47"})
        self.assertEqual(r.status_code, 201, r.text)
        from api.departments import SINGLE_PORTAL
        self.assertEqual(r.json()["portal"], "ag" if SINGLE_PORTAL else "school-education")
        # The fixture's seed password is "Pension@2026", which the password rule (5 Oct 2026) now
        # refuses for a new account; this one gets a strong password and signs in with it.
        signed = self.client.post("/api/v2/auth/login", headers={"X-Portal": "ag" if SINGLE_PORTAL else "school-education"},
                                  json={"username": "edu.two", "password": "Copper-Harbour-Falcon-47"})
        self.assertEqual(signed.status_code, 200, signed.text)
        users = self.client.get("/api/v2/admin/users", headers=admin).json()
        self.assertNotIn("password_hash", users[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
