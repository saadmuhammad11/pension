"""No case is approved by the system; every approval is an officer's own (business decision M1, 7 Oct 2026).

    python3 -m unittest tests.test_no_automatic_approval -v

Until 7 Oct 2026 three paths approved a case with nobody deciding it: a clean verification
(AUTO_APPROVE from AI_CHECKING), the officer's last clearance (``settle``, from UNDER_REVIEW) and a
GP Fund examination that passed or had nothing open. All three now leave the case UNDER_REVIEW
for the Accountant General's decision. Automatic RETURN for missing documents stays. The
end-to-end behaviour is pinned in tests.test_api_v2, test_clearance_audit, test_reverify_race and
test_resubmission_rounds; this file pins the rule itself.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from api import case_runs, workflow

ROOT = Path(__file__).resolve().parents[1]
CLEAN = {"missing_checklist": [], "unidentified_pages": 0, "flags_total": 0, "checklist_present": True}


class TheOutcome(unittest.TestCase):
    def test_a_clean_verification_goes_to_the_ag_not_to_approved(self):
        self.assertEqual(case_runs.outcome(CLEAN), "CHECK_DONE")
        self.assertTrue(case_runs.nothing_outstanding(CLEAN))

    def test_findings_and_missing_papers_behave_as_before(self):
        self.assertEqual(case_runs.outcome({**CLEAN, "flags_total": 2}), "CHECK_DONE")
        self.assertEqual(case_runs.outcome({**CLEAN, "missing_checklist": [{"id": "AG-06"}]}), "AUTO_RETURN")
        self.assertEqual(case_runs.outcome({**CLEAN, "missing_checklist": [{"id": "AG-06"}], "unidentified_pages": 2}), "CHECK_DONE")
        self.assertFalse(case_runs.nothing_outstanding({**CLEAN, "flags_total": 1}))
        self.assertFalse(case_runs.nothing_outstanding({**CLEAN, "checklist_present": False}))

    def test_no_outcome_value_is_an_approval(self):
        for issues in (CLEAN, {**CLEAN, "flags_total": 1}, {**CLEAN, "missing_checklist": [{"id": "x"}]}):
            self.assertNotIn("APPROVE", case_runs.outcome(issues))


class TheWorkflow(unittest.TestCase):
    def test_the_system_has_no_way_to_approve(self):
        self.assertNotIn("AUTO_APPROVE", workflow.TRANSITIONS)
        self.assertNotIn("AUTO_APPROVE", workflow.SYSTEM_ACTIONS)
        for action in workflow.SYSTEM_ACTIONS:
            self.assertNotEqual(workflow.TRANSITIONS[action][2], workflow.APPROVED, action)
        roles, _, target = workflow.TRANSITIONS["APPROVE"]
        self.assertEqual(target, workflow.APPROVED)
        self.assertTrue(roles, "APPROVE needs a signed-in officer")
        self.assertIn("APPROVE", workflow.REMARK_REQUIRED)

    def test_the_api_never_asks_for_an_automatic_approval(self):
        """``AUTO_APPROVE`` may remain only as the name of a past action (histories, round backfill)."""
        offenders = []
        for path in sorted((ROOT / "api").glob("*.py")):
            for n, line in enumerate(path.read_text().splitlines(), start=1):
                if re.search(r'transition\([^)]*"AUTO_APPROVE"', line):
                    offenders.append(f"{path.name}:{n}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
