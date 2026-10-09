"""A re-verification is never overtaken by the previous run's result (audit 6 Oct 2026, High finding).

    python3 -m unittest tests.test_reverify_race -v

start_check moved the case to AI_CHECKING in one transaction and recorded the new run in a later
one. The reconciler's sweep runs every 3 s and on almost every read; landing in that gap, it found
the case in AI_CHECKING still pointing at the OLD finished run and applied that run's outcome --
CHECK_FAILED from a failed run -- and when the new run finished, the case was no longer in
AI_CHECKING, so its result was never applied: the case stayed failed. Here the sweep is made to
run exactly in the gap, every time.
"""
from __future__ import annotations

import unittest
from unittest import mock

from api import case_runs, db
from tests import test_api_v2 as _v2


class SweepInTheStartGap(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def _sweep_during_start(self):
        real_start, real_gpf = case_runs._start, case_runs._start_gpf
        swept = []

        def sweep_then(real):
            def run(*args, **kwargs):
                conn = db.connect()
                try:
                    swept.append(case_runs.sync_run_states(conn))   # the reconciler, mid-start
                finally:
                    conn.close()
                return real(*args, **kwargs)
            return run
        return swept, mock.patch.multiple(case_runs, _start=sweep_then(real_start), _start_gpf=sweep_then(real_gpf))

    def test_verifying_again_after_a_failure_applies_the_new_result(self) -> None:
        self.fail_runs = True
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        self.verify(reviewer, case_id)
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()["status"], "AI_FAILED")

        self.fail_runs = False
        swept, patch = self._sweep_during_start()
        with patch:
            self.verify(reviewer, case_id)
        self.assertEqual(len(swept), 1, "the sweep ran inside the start gap")
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        actions = [e["action"] for e in case["events"]]
        after_restart = actions[len(actions) - 1 - actions[::-1].index("RUN_CHECK"):]
        self.assertNotIn("CHECK_FAILED", after_restart, actions)
        self.assertEqual(case["status"], "UNDER_REVIEW", case["events"][-1])     # clean: the AG decides (M1)

    def test_a_first_verification_is_not_failed_while_it_is_still_starting(self) -> None:
        # No old run at all: the sweep used to fail any AI_CHECKING case with no run row once two
        # minutes had passed, even while a slow start (a GP Fund upload) was still in progress.
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        conn = db.connect()
        conn.execute("UPDATE cases SET updated_at = '2000-01-01T00:00:00' WHERE id = ?", (case_id,))
        conn.commit()
        conn.close()
        real_transition = case_runs.workflow.transition

        def aged_transition(conn, case, action, *a, **k):
            out = real_transition(conn, case, action, *a, **k)
            if action == "RUN_CHECK":                          # as if the start had taken ten minutes
                conn.execute("UPDATE cases SET updated_at = '2000-01-01T00:00:00' WHERE id = ?", (case["id"],))
            return out
        swept, patch = self._sweep_during_start()
        with patch, mock.patch.object(case_runs.workflow, "transition", aged_transition):
            self.verify(reviewer, case_id)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        self.assertNotIn("CHECK_FAILED", [e["action"] for e in case["events"]])
        self.assertEqual(case["status"], "UNDER_REVIEW", case["events"][-1])


if __name__ == "__main__":
    unittest.main()
