"""A GP Fund examination is not failed by a poll that got no answer (audit 6 Oct 2026, Medium).

    python3 -m unittest tests.test_gpf_poll_resilience -v

The reconciler polls the module's reading job every few seconds with a 10 s timeout. Any error --
the module busy reading, restarting, briefly down -- failed the examination for good while the
module went on reading, and the case it then opened was never linked. Now only an answer fails
it (the job errored, or the module no longer knows it); silence fails it only after a deadline.
"""
from __future__ import annotations

import unittest
from unittest import mock

from api import case_runs, db, gpf_bridge
from tests import test_api_v2 as _v2


class PollResilience(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def _module(self, answers: list):
        """The module stubbed; each poll takes the next answer (an error, or a job view)."""
        view = _v2.V2Test._gpf_view(conf=True)

        def job(job_id):
            answer = answers.pop(0) if answers else {"jobId": job_id, "state": "done", "result": {"id": "gpf-case-1"}}
            if isinstance(answer, Exception):
                raise answer
            return answer
        for p in (mock.patch.object(gpf_bridge, "start_examination", lambda *a, **k: {"jobId": "job-1", "state": "running"}),
                  mock.patch.object(gpf_bridge, "job", job),
                  mock.patch.object(gpf_bridge, "case", lambda cid: view),
                  mock.patch.object(gpf_bridge, "health", lambda: {"ok": True})):
            p.start()
            self.addCleanup(p.stop)

    def _case(self, case_id: str) -> dict:
        conn = db.connect()
        try:
            case_runs.sync_run_states(conn)
            return dict(conn.execute("SELECT status, gpf_case_id FROM cases WHERE id = ?", (case_id,)).fetchone())
        finally:
            conn.close()

    def _start(self) -> str:
        case_id = self.create(self.login("punjab-police", "punjab-police"), product="GPF", gpf_kind="refundable")["case"]["id"]
        self.verify(self.sa(), case_id)
        return case_id

    def test_a_module_that_does_not_answer_for_a_while_is_waited_for(self) -> None:
        busy = gpf_bridge.GpfError(502, "the GP Fund module is not reachable (timed out)")
        answers = [busy, busy, busy]
        self._module(answers)
        case_id = self._start()
        seen = []
        for _ in range(10):                       # every sweep polls once; the module answers on the 4th
            seen.append(self._case(case_id)["status"])
            if seen[-1] != "AI_CHECKING":
                break
        self.assertEqual(answers, [], "every unanswered poll was made")
        self.assertNotIn("AI_FAILED", seen)
        case = self._case(case_id)
        self.assertEqual(case["status"], "UNDER_REVIEW")
        self.assertEqual(case["gpf_case_id"], "gpf-case-1")

    def test_a_job_the_module_no_longer_knows_fails_at_once(self) -> None:
        self._module([gpf_bridge.GpfError(404, "No such reading job")] * 5)
        case_id = self._start()
        self.assertEqual(self._case(case_id)["status"], "AI_FAILED")

    def test_silence_past_the_deadline_fails_with_the_reason(self) -> None:
        busy = gpf_bridge.GpfError(502, "the GP Fund module is not reachable")
        self._module([busy] * 10)
        case_id = self._start()
        conn = db.connect()
        conn.execute("UPDATE case_runs SET started_at = '2000-01-01T00:00:00' WHERE case_id = ?", (case_id,))
        conn.commit()
        conn.close()
        self.assertEqual(self._case(case_id)["status"], "AI_FAILED")
        conn = db.connect()
        error = conn.execute("SELECT error FROM case_runs WHERE case_id = ?", (case_id,)).fetchone()[0]
        conn.close()
        self.assertIn("has not confirmed the reading", error)


if __name__ == "__main__":
    unittest.main()
