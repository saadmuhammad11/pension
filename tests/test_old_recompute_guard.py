"""The old register's recompute cannot change the report behind a decided case (audit 6 Oct 2026, C3).

    python3 -m unittest tests.test_old_recompute_guard -v

``POST /api/runs/{id}/recompute`` rebuilds a run's determination and report from its artefacts.
It knew nothing of the case the run belongs to, so an administrator could rebuild the report
behind an approved or rejected case, or behind a run the case had already moved on from.
"""
from __future__ import annotations

import unittest
from unittest import mock

from api import runs
from tests import test_api_v2 as _v2


class RecomputeGuard(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def test_an_approved_case_s_run_is_not_rebuilt(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.login("ag.reviewer", "ag")
        run_id = self.verify(reviewer, case_id)["run_id"]
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=reviewer, json={"remark": "In order; approved by hand."})
        self.assertEqual(r.status_code, 200, r.text)                     # no automatic approval since M1
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()["status"], "APPROVED")
        with mock.patch.object(runs, "recompute", lambda run: {"rebuilt": True}) as _:
            r = self.client.post(f"/api/runs/{run_id}/recompute", headers=self.login("admin", "ag"))
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("approved", r.json()["detail"])

    def test_a_case_still_under_review_can_be_recomputed(self) -> None:
        self.report_to_write = _v2.FLAGS_ONLY_REPORT                 # a finding: the case waits for the AG
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.login("ag.reviewer", "ag")
        run_id = self.verify(reviewer, case_id)["run_id"]
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()["status"], "UNDER_REVIEW")
        with mock.patch.object(runs, "recompute", lambda run: {"rebuilt": True}):
            r = self.client.post(f"/api/runs/{run_id}/recompute", headers=self.login("admin", "ag"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"rebuilt": True})

    def test_a_run_the_case_has_moved_on_from_is_history(self) -> None:
        self.report_to_write = _v2.FLAGS_ONLY_REPORT
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.login("ag.reviewer", "ag")
        first = self.verify(reviewer, case_id)["run_id"]
        r = self.client.post(f"/api/v2/cases/{case_id}/return", headers=reviewer,
                             json={"remark": "Pay certificate missing.", "items": []})
        self.assertEqual(r.status_code, 200, r.text)
        # The department attaches a document and refiles; the AG verifies again: a new run.
        r = self.client.post(f"/api/v2/cases/{case_id}/documents", headers=police,
                             files=[("files", ("more.pdf", _v2.PDF, "application/pdf"))])
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/forward", headers=police, json={}).status_code, 200)
        second = self.verify(reviewer, case_id)["run_id"]
        self.assertNotEqual(first, second)
        admin = self.login("admin", "ag")
        with mock.patch.object(runs, "recompute", lambda run: {"rebuilt": True}):
            old = self.client.post(f"/api/runs/{first}/recompute", headers=admin)
            new = self.client.post(f"/api/runs/{second}/recompute", headers=admin)
        self.assertEqual(old.status_code, 409, old.text)
        self.assertIn("newer examination", old.json()["detail"])
        self.assertEqual(new.status_code, 200, new.text)


if __name__ == "__main__":
    unittest.main()
