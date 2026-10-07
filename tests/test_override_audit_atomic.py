"""An administrator's override and its audit row are one transaction (audit 6 Oct 2026, C2).

    python3 -m unittest tests.test_override_audit_atomic -v

The audit row used to be written after the status change had committed, so a crash or a refused
insert between the two left a case moved by hand with no audit line saying who moved it or why.
Now the row is written inside the override's own transaction: if it cannot be written, the case
does not move either.
"""
from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from api import workflow
from tests import test_api_v2 as _v2


class OverrideAuditAtomic(unittest.TestCase):
    report_to_write = _v2.FLAGS_ONLY_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def _case_waiting_for_the_ag(self) -> tuple[str, dict]:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.login("syed.haider", "ag")
        self.verify(reviewer, case_id)
        admin = self.login("admin", "ag")
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=admin).json()["status"], "UNDER_REVIEW")
        return case_id, admin

    def test_a_refused_audit_row_rolls_the_override_back(self) -> None:
        case_id, admin = self._case_waiting_for_the_ag()
        real_audit = workflow.audit

        def refusing_audit(conn: sqlite3.Connection, **kw):
            if kw.get("action") == "CASE_OVERRIDE":
                raise sqlite3.OperationalError("database or disk is full")
            return real_audit(conn, **kw)

        with mock.patch.object(workflow, "audit", refusing_audit):
            with self.assertRaises(sqlite3.OperationalError):
                self.client.post(f"/api/v2/cases/{case_id}/override", headers=admin,
                                 json={"to_status": "RETURNED", "reason": "Filed against the wrong claimant."})
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=admin).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")                 # the move did not happen...
        self.assertNotIn("OVERRIDE", [e["action"] for e in case["events"]])   # ...and left no history row
        log = self.client.get("/api/v2/admin/audit-log", headers=admin).json()
        self.assertNotIn("CASE_OVERRIDE", [row["action"] for row in log])

    def test_a_completed_override_still_carries_its_audit_row(self) -> None:
        case_id, admin = self._case_waiting_for_the_ag()
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=admin,
                             json={"to_status": "RETURNED", "reason": "Filed against the wrong claimant."})
        self.assertEqual(r.status_code, 200, r.text)
        log = self.client.get("/api/v2/admin/audit-log", headers=admin).json()
        self.assertEqual(log[0]["action"], "CASE_OVERRIDE")
        self.assertEqual((log[0]["before"], log[0]["after"]), ({"status": "UNDER_REVIEW"}, {"status": "RETURNED"}))
        self.assertEqual(log[0]["reason"], "Filed against the wrong claimant.")


if __name__ == "__main__":
    unittest.main()
