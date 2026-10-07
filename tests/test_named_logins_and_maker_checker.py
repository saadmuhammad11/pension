"""Named logins for every reviewer, and maker-checker on approval (business decision C1, 7 Oct 2026).

    python3 -m unittest tests.test_named_logins_and_maker_checker -v

All AG reviewers shared one "ag.reviewer" login, so a decision was recorded under a desk, not a
person, and one administrator account could file a case for any department and approve it. The
seed now renames the shared login in place to the named officer, production refuses to start with
a shared login active, reviewers (and the Deputy AG, role AG_DAG) are created by name, and the
user who submitted a case -- whoever they are, administrators included -- cannot approve it.
"""
from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from api import db
from tests import test_api_v2 as _v2


class NamedLogins(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login

    def test_the_seed_creates_the_named_reviewer_and_no_shared_login(self) -> None:
        conn = db.connect()
        try:
            names = {r["username"] for r in conn.execute("SELECT username FROM users WHERE role != 'DEPT_OFFICER'")}
        finally:
            conn.close()
        self.assertIn("syed.haider", names)
        self.assertNotIn("ag.reviewer", names)
        self.assertEqual(self.login("syed.haider", "ag")["Authorization"][:7], "Bearer ")

    def test_an_old_database_s_shared_login_is_renamed_in_place(self) -> None:
        conn = db.connect()
        try:
            row = conn.execute("SELECT id, password_hash FROM users WHERE username = 'syed.haider'").fetchone()
            conn.execute("UPDATE users SET username = 'ag.reviewer', token_version = 3 WHERE id = ?", (row["id"],))
            conn.commit()
            db.seed(conn, quiet=True)
            after = conn.execute("SELECT username, token_version, password_hash FROM users WHERE id = ?", (row["id"],)).fetchone()
        finally:
            conn.close()
        self.assertEqual(after["username"], "syed.haider")             # same account: same id, same password
        self.assertEqual(after["password_hash"], row["password_hash"])
        self.assertEqual(after["token_version"], 4)                     # its sessions ended

    def test_production_refuses_to_start_with_a_shared_login_active(self) -> None:
        from api import auth, server
        conn = db.connect()
        try:
            conn.execute("INSERT INTO users(id, username, display_name, password_hash, role, department_code, active, "
                         "token_version, must_change_password, created_at, updated_at) VALUES "
                         "('x1', 'ag.reviewer', 'Desk', 'scrypt$x$y', 'AG_REVIEWER', NULL, 1, 1, 0, '2026', '2026')")
            conn.commit()
            self.assertEqual(auth.shared_logins(conn), ["ag.reviewer"])
        finally:
            conn.close()
        with self.assertRaises(SystemExit) as cm:
            server._production_startup_checks()
        self.assertEqual(cm.exception.code, 1)
        conn = db.connect()
        try:
            conn.execute("UPDATE users SET active = 0 WHERE username = 'ag.reviewer'"); conn.commit()
            self.assertEqual(auth.shared_logins(conn), [])
        finally:
            conn.close()
        server._production_startup_checks()                             # nothing shared: starts

    def test_a_reviewer_and_the_deputy_ag_are_created_by_name(self) -> None:
        conn = db.connect()
        try:
            pw = db.add_reviewer("ayesha.khan", "Ayesha Khan (Auditor, Pension Wing)", conn=conn)
            pw_dag = db.add_reviewer("fatima.hameed", "Fatima Hameed (DAG Pension)", dag=True, conn=conn)
            with self.assertRaises(ValueError):
                db.add_reviewer("dag", "Desk", dag=True, conn=conn)          # a desk, not a name
            with self.assertRaises(ValueError):
                db.add_reviewer("ayesha.khan", "Again", conn=conn)
        finally:
            conn.close()
        for username, password, role in (("ayesha.khan", pw, "AG_REVIEWER"), ("fatima.hameed", pw_dag, "AG_DAG")):
            r = self.client.post("/api/v2/auth/login", json={"username": username, "password": password}, headers={"X-Portal": "ag"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["user"]["role"], role)
            self.assertTrue(r.json()["capabilities"]["review"])
            self.assertTrue(r.json()["capabilities"]["dispose"])
            self.assertFalse(r.json()["capabilities"]["manage_users"])


class MakerChecker(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def test_the_submitter_cannot_approve_but_a_second_officer_can(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.login("syed.haider", "ag")
        self.verify(reviewer, case_id)
        # Make the reviewer the maker: the case's creator and submitter (as one person at a desk
        # with both roles would be). The rule is about the person, not the role.
        conn = db.connect()
        try:
            me = conn.execute("SELECT id FROM users WHERE username = 'syed.haider'").fetchone()["id"]
            conn.execute("UPDATE cases SET created_by = ? WHERE id = ?", (me, case_id))   # case_events is append-only
            conn.commit()
        finally:
            conn.close()
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertNotIn("APPROVE", case["allowed_actions"])
        self.assertIn("RETURN", case["allowed_actions"])
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=reviewer, json={"remark": "Complete and in order; approved."})
        self.assertEqual(r.status_code, 403, r.text)
        self.assertIn("maker-checker", r.json()["detail"])
        # A second, named officer approves.
        conn = db.connect()
        try:
            pw = db.add_reviewer("ayesha.khan", "Ayesha Khan (Auditor)", conn=conn)
        finally:
            conn.close()
        other = {"Authorization": "Bearer " + self.client.post("/api/v2/auth/login", json={"username": "ayesha.khan", "password": pw},
                                                                 headers={"X-Portal": "ag"}).json()["token"]}
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=other).json()
        self.assertIn("APPROVE", case["allowed_actions"])
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=other, json={"remark": "Complete and in order; approved."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["case"]["status"], "APPROVED")

    def test_an_administrator_who_filed_the_case_cannot_approve_it_by_override(self) -> None:
        admin = self.login("admin", "ag")
        case_id = self.create(admin, department_code="PUNJAB_POLICE")["case"]["id"]
        reviewer = self.login("syed.haider", "ag")
        self.verify(reviewer, case_id)
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=admin,
                             json={"to_status": "APPROVED", "remark": "Override to approved by the person who filed it."})
        self.assertEqual(r.status_code, 403, r.text)
        self.assertIn("maker-checker", r.json()["detail"])
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=admin,
                             json={"to_status": "RETURNED", "remark": "Override to returned; not an approval."})
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
