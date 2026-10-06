"""Who cleared a case is on the audit trail by account (audit 6 Oct 2026, High finding).

    python3 -m unittest tests.test_clearance_audit -v

Waiving a finding or a checklist item is what lets a case approve itself, and those acts were
kept only in the run folder's .jsonl files under a display name and a fixed role -- no account,
no address, editable on disk -- while the approval they triggered was logged as the SYSTEM.
Now each act is an append-only audit_log row of the account that did it, and the approval names
that account in the case history and on the audit trail. Sent with the case NUMBER rather than
its id, the last clearance also approves the case now (it never did).
"""
from __future__ import annotations

import json
import unittest

from api import db
from tests import test_api_v2 as _v2

MISSING_PAPER_REPORT = {
    "claimant_name": "Fozia Akhtar", "flags": [], "pages_unaccounted": [5],
    "checklist": {"checklist_id": "AG_OFFICE_2026:DEATH_IN_SERVICE", "result": "INCOMPLETE", "required": 1,
                  "present": 0, "missing": 1, "defective": 0, "satisfied": 0,
                  "result_line": "CHECKLIST INCOMPLETE - 1 missing (A3).",
                  "items": [{"id": "A3", "requirement": "Family Registration Certificate", "status": "MISSING",
                             "located": []}]},
    "recommendation": {"verdict": "HOLD", "blocking_flags": []},
}


class _Fixture(unittest.TestCase):
    report_to_write = _v2.FLAGS_ONLY_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def _under_review(self):
        made = self.create(self.login("punjab-police", "punjab-police"))
        reviewer = self.login("ag.reviewer", "ag")
        run_id = self.verify(reviewer, made["case"]["id"])["run_id"]
        case = self.client.get(f"/api/v2/cases/{made['case']['id']}", headers=reviewer).json()
        self.assertEqual(case["status"], "UNDER_REVIEW", case["events"][-1])
        return case, run_id, reviewer

    def _audit(self, case_id: str) -> list:
        conn = db.connect()
        try:
            return conn.execute("SELECT a.*, u.username FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id "
                                "WHERE a.entity_id = ? ORDER BY a.rowid", (case_id,)).fetchall()
        finally:
            conn.close()

    def _assert_approved_by_reviewer(self, case_no: str, reviewer: dict, action: str) -> None:
        case = self.client.get(f"/api/v2/cases/{case_no}", headers=reviewer).json()
        self.assertEqual(case["status"], "APPROVED", case["events"][-1])
        last = case["events"][-1]
        self.assertEqual(last["action"], "AUTO_APPROVE")
        self.assertEqual(last["payload"]["cleared_by"]["username"], "ag.reviewer")
        rows = self._audit(case["id"])
        acts = [(r["action"], r["username"]) for r in rows]
        self.assertIn((action, "ag.reviewer"), acts)
        self.assertIn(("CASE_APPROVED_ON_CLEARANCE", "ag.reviewer"), acts)
        act = next(r for r in rows if r["action"] == action)
        self.assertTrue(act["ip"], "the address is recorded")
        self.assertTrue(act["reason"], "the ground is recorded")


class FindingWaiver(_Fixture):
    def test_a_waiver_sent_by_case_number_is_audited_and_approves(self) -> None:
        case, run_id, reviewer = self._under_review()
        r = self.client.post(f"/api/v2/cases/{case['case_no']}/runs/{run_id}/dispositions", headers=reviewer,
                             json={"flag_id": "F-1", "action": "WAIVE",
                                   "ground": "Recovery verified by hand against the LPC."})
        self.assertEqual(r.status_code, 201, r.text)
        self._assert_approved_by_reviewer(case["case_no"], reviewer, "FINDING_WAIVE")
        row = next(r for r in self._audit(case["id"]) if r["action"] == "FINDING_WAIVE")
        after = json.loads(row["after_json"])
        self.assertEqual((after["run_id"], after["flag_id"]), (run_id, "F-1"))
        self.assertEqual(after["flag_title"], "Unrecorded recovery")


class ChecklistWaiver(_Fixture):
    report_to_write = MISSING_PAPER_REPORT

    def test_a_checklist_waiver_by_run_id_is_audited_and_approves(self) -> None:
        case, run_id, reviewer = self._under_review()
        r = self.client.post(f"/api/v2/runs/{run_id}/checklist-actions", headers=reviewer,
                             json={"action": "WAIVE", "item_id": "A3",
                                   "ground": "FRC seen in the original file at the counter on 6 Oct."})
        self.assertEqual(r.status_code, 201, r.text)
        self._assert_approved_by_reviewer(case["case_no"], reviewer, "CHECKLIST_WAIVE")


if __name__ == "__main__":
    unittest.main()
