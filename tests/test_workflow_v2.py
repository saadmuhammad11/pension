"""The case lifecycle table, and the two append-only tables. Standard library only.

    python3 -m unittest tests.test_workflow_v2 -v
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api import db, workflow
from api.auth import hash_password, verify_password


class Actor:
    def __init__(self, role: str, dept: str | None = None) -> None:
        self.id, self.display_name, self.role, self.department_code = f"u-{role}", role.title(), role, dept


class TransitionTable(unittest.TestCase):
    def test_every_status_is_reachable_and_named(self) -> None:
        targets = {t for _, (_, _, t) in workflow.TRANSITIONS.items() if t}
        for s in workflow.STATUSES:
            self.assertIn(s, workflow.STATUS_LABELS)
            if s not in (workflow.DRAFT, workflow.AI_CHECKED):      # AI_CHECKED: histories before 28 Sep 2026 only
                self.assertIn(s, targets, s)

    def test_department_side_cannot_decide_and_ag_cannot_forward(self) -> None:
        with self.assertRaises(workflow.WorkflowError) as cm:
            workflow.check("DEPT_OFFICER", workflow.UNDER_REVIEW, "APPROVE")
        self.assertEqual(cm.exception.status, 403)
        with self.assertRaises(workflow.WorkflowError) as cm:
            workflow.check("AG_REVIEWER", workflow.AI_CHECKED, "FORWARD")
        self.assertEqual(cm.exception.status, 403)

    def test_the_department_submits_and_the_ag_verifies(self) -> None:
        workflow.check("DEPT_OFFICER", workflow.DRAFT, "FORWARD")        # no raise: filing is submission
        with self.assertRaises(workflow.WorkflowError) as cm:
            workflow.check("DEPT_OFFICER", workflow.FORWARDED, "RUN_CHECK")
        self.assertEqual(cm.exception.status, 403)                       # the verification is the AG's
        workflow.check("AG_REVIEWER", workflow.FORWARDED, "RUN_CHECK")   # no raise
        with self.assertRaises(workflow.WorkflowError) as cm:
            workflow.check("DEPT_OFFICER", workflow.FORWARDED, "ADD_DOCS")
        self.assertEqual(cm.exception.status, 409)                       # the AG holds it now
        self.assertIn(workflow.RETURNED, workflow.TRANSITIONS["AUTO_RETURN"][1] | {workflow.RETURNED})
        self.assertNotIn("AUTO_APPROVE", workflow.TRANSITIONS)             # no automatic approval (M1, 7 Oct 2026)
        self.assertNotIn("AUTO_APPROVE", workflow.SYSTEM_ACTIONS)
        self.assertTrue(all(workflow.TRANSITIONS[a][2] != workflow.APPROVED for a in workflow.SYSTEM_ACTIONS))

    def test_admin_may_override_from_anywhere_and_only_admin(self) -> None:
        for s in workflow.STATUSES:
            workflow.check("ADMIN", s, "OVERRIDE")
        with self.assertRaises(workflow.WorkflowError):
            workflow.check("AG_REVIEWER", workflow.APPROVED, "OVERRIDE")

    def test_scoping(self) -> None:
        police_case = {"department_code": "PUNJAB_POLICE", "created_via": "DEPARTMENT"}
        other_case = {"department_code": "AGRICULTURE", "created_via": "DEPARTMENT"}
        self.assertTrue(workflow.may_see("DEPT_OFFICER", "PUNJAB_POLICE", police_case))
        self.assertFalse(workflow.may_see("DEPT_OFFICER", "SCHOOL_EDUCATION", police_case))
        self.assertTrue(workflow.may_see("AG_REVIEWER", None, police_case))
        self.assertTrue(workflow.owns_side("ADMIN", None, other_case))
        self.assertFalse(workflow.owns_side("AG_REVIEWER", None, other_case))
        self.assertFalse(workflow.owns_side("DEPT_OFFICER", "PUNJAB_POLICE", other_case))


class Database(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-db-")
        self._patch = mock.patch.object(db, "DB_PATH", Path(self._tmp.name) / "portal.sqlite3")
        self._patch.start()
        self._patches = [mock.patch.object(db, "SEED_PASSWORD", "Pension@2026"),
                         mock.patch.object(db, "CREDENTIALS_CSV", Path(self._tmp.name) / "c.csv"),
                         mock.patch.object(db, "CREDENTIALS_HTML", Path(self._tmp.name) / "c.html")]
        for p in self._patches: p.start()
        self.conn = db.connect()
        db.migrate(self.conn)
        db.seed(self.conn, quiet=True)

    def tearDown(self) -> None:
        self.conn.close()
        for p in self._patches: p.stop()
        self._patch.stop()
        self._tmp.cleanup()

    def _case(self, status: str = workflow.DRAFT) -> sqlite3.Row:
        user = self.conn.execute("SELECT id FROM users WHERE username = 'punjab-police'").fetchone()
        now = db.now()
        self.conn.execute(
            "INSERT INTO cases(id, case_no, department_code, created_via, created_by, status, submission_no, "
            "created_at, updated_at) VALUES ('c1', 'PC-2026-000001', 'PUNJAB_POLICE', 'DEPARTMENT', ?, ?, 1, ?, ?)",
            (user["id"], status, now, now))
        return self.conn.execute("SELECT * FROM cases WHERE id = 'c1'").fetchone()

    def test_migrate_is_idempotent_and_seed_creates_one_officer_per_department(self) -> None:
        self.assertEqual(db.migrate(self.conn), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 88)   # 86 + reviewer + admin
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM departments WHERE active = 1 AND code != 'LEGACY'").fetchone()[0], 86)
        self.assertEqual(self.conn.execute("SELECT port FROM departments WHERE code = 'PUNJAB_POLICE'").fetchone()[0], 5180)
        self.assertEqual(db.seed(self.conn, quiet=True)["users_created"], [])

    def test_passwords_round_trip_and_do_not_leak(self) -> None:
        h = hash_password("Pension@2026")
        self.assertTrue(h.startswith("scrypt$"))
        self.assertTrue(verify_password("Pension@2026", h))
        self.assertFalse(verify_password("pension@2026", h))
        self.assertNotEqual(h, hash_password("Pension@2026"))       # salted

    def test_a_transition_writes_one_history_row_and_moves_the_case(self) -> None:
        case = self._case(workflow.AI_CHECKED)
        entry = workflow.transition(self.conn, case, "FORWARD", Actor("DEPT_OFFICER", "PUNJAB_POLICE"),
                                    remark="forwarding despite the FRC", payload={"verdict": "HOLD"})
        self.assertEqual(entry["to_status"], workflow.FORWARDED)
        row = self.conn.execute("SELECT status FROM cases WHERE id = 'c1'").fetchone()
        self.assertEqual(row["status"], workflow.FORWARDED)
        events = self.conn.execute("SELECT * FROM case_events WHERE case_id = 'c1'").fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["remark"], "forwarding despite the FRC")

    def test_ag_decisions_need_a_remark(self) -> None:
        case = self._case(workflow.UNDER_REVIEW)
        with self.assertRaises(workflow.WorkflowError) as cm:
            workflow.transition(self.conn, case, "RETURN", Actor("AG_REVIEWER"), remark="  ")
        self.assertEqual(cm.exception.status, 422)
        self.assertEqual(self.conn.execute("SELECT status FROM cases WHERE id='c1'").fetchone()[0],
                         workflow.UNDER_REVIEW)

    def test_the_system_may_only_record_check_outcomes(self) -> None:
        case = self._case(workflow.AI_CHECKING)
        workflow.transition(self.conn, case, "CHECK_DONE", None, remark="done")
        case = self.conn.execute("SELECT * FROM cases WHERE id = 'c1'").fetchone()
        self.assertEqual(case["status"], workflow.UNDER_REVIEW)
        with self.assertRaises(workflow.WorkflowError):
            workflow.transition(self.conn, case, "RETURN", None, remark="x")
        with self.assertRaises(workflow.WorkflowError):                 # the system never approves (M1)
            workflow.transition(self.conn, case, "AUTO_APPROVE", None, remark="cleared")
        with self.assertRaises(workflow.WorkflowError):
            workflow.transition(self.conn, case, "APPROVE", None, remark="cleared")
        self.assertEqual(self.conn.execute("SELECT status FROM cases WHERE id='c1'").fetchone()[0], workflow.UNDER_REVIEW)

    def test_history_and_audit_are_append_only(self) -> None:
        case = self._case(workflow.AI_CHECKED)
        workflow.transition(self.conn, case, "FORWARD", Actor("ADMIN"), remark="x")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE case_events SET remark = 'edited'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM case_events")
        workflow.audit(self.conn, actor=Actor("ADMIN"), action="X", entity_type="case", entity_id="c1",
                       before={"status": "A"}, after={"status": "B"}, reason="because")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM audit_log")


if __name__ == "__main__":
    unittest.main(verbosity=2)
