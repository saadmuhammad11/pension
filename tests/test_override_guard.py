"""The Deputy AG's override needs a written reason and, to approve, a verified case (audit 7 Oct 2026).

    python3 -m unittest tests.test_override_guard -v

The override skips the workflow, so it was the one way a case with papers nobody had examined
could reach APPROVED, with a one-character reason. It is now held to the same bar as approving
against the findings. The GP Fund return is recorded as a system action under the module's
officer, never as a pseudo-officer without an account.
"""
from __future__ import annotations

import unittest

from api import workflow
from tests import test_api_v2 as _v2


class OverrideGuard(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def test_an_unverified_case_cannot_be_overridden_to_approved(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        dag = self.login("fatima.hameed", "ag")
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=dag,
                             json={"to_status": "APPROVED", "reason": "Approved on the AG's direction of today."})
        self.assertEqual(r.status_code, 409, r.text)
        # "examine", not "verify", since 24 Oct 2026: the machine examines a case and an
        # officer verifies a finding (tests/test_one_word_per_act.py).
        self.assertIn("examine the case", r.json()["detail"])
        # A return by override needs no examination, but it does need a real reason.
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=dag, json={"to_status": "RETURNED", "reason": "x"})
        self.assertEqual(r.status_code, 422, r.text)
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=dag,
                             json={"to_status": "RETURNED", "reason": "Filed under the wrong department; returned."})
        self.assertEqual(r.status_code, 200, r.text)

    def test_a_verified_case_can_be_overridden_to_approved_with_a_reason(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer, dag = self.sa(), self.login("fatima.hameed", "ag")
        self.verify(reviewer, case_id)
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=dag,
                             json={"to_status": "APPROVED", "reason": "Approved on the AG's direction of today."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["case"]["status"], "APPROVED")

    def test_the_system_returns_no_case_and_has_no_pseudo_officer(self) -> None:
        # 9 Oct 2026: no automatic return in pension or GP Fund. The retired actions stay in the
        # table for old history rows, but nobody may perform them.
        self.assertNotIn("GPF_RETURN", workflow.SYSTEM_ACTIONS)
        self.assertNotIn("AUTO_RETURN", workflow.SYSTEM_ACTIONS)
        self.assertFalse(any(workflow.TRANSITIONS[a][2] == workflow.RETURNED for a in workflow.SYSTEM_ACTIONS))
        self.assertEqual(workflow.TRANSITIONS["GPF_RETURN"][:2], ((), frozenset()))
        from api import case_runs
        self.assertFalse(hasattr(case_runs, "_SystemOfficer"))


if __name__ == "__main__":
    unittest.main()
