"""A verification has a deadline, and the run registry does not grow without bound (audit 6 Oct 2026, R7).

    python3 -m unittest tests.test_run_deadline_and_registry -v

Every model call had a timeout, but a run is many calls, each retried, so a run could stay
"running" for hours, holding its slot and its case. And every run the process had ever seen
stayed in memory until a restart. Now a run past PENSION_RUN_DEADLINE_MIN is reported failed
by the reconciler and stops itself at its next stage boundary; finished runs leave the registry
after PENSION_RUN_REGISTRY_KEEP_MIN minutes and are rebuilt from disk when asked for.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from api import case_runs, runs


def _run(run_id: str, state: str, started: datetime, finished: datetime | None, root: Path) -> runs.Run:
    run_dir = root / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return runs.Run(run_id=run_id, pdf_path=root / f"{run_id}.pdf", run_dir=run_dir, state=state,
                    started_at=started.isoformat(timespec="seconds"),
                    finished_at=finished.isoformat(timespec="seconds") if finished else "")


class Deadline(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = dict(runs.RUNS)
        runs.RUNS.clear()
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-deadline-")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        runs.RUNS.clear()
        runs.RUNS.update(self._saved)
        self._tmp.cleanup()

    def test_the_reconciler_reports_a_run_past_its_deadline_as_failed(self) -> None:
        now = datetime.now()
        with mock.patch.dict("os.environ", {"PENSION_RUN_DEADLINE_MIN": "90"}):
            fresh = _run("a" * 12, "running", now - timedelta(minutes=30), None, self.root)
            stale = _run("b" * 12, "running", now - timedelta(minutes=95), None, self.root)
            runs.RUNS.update({fresh.run_id: fresh, stale.run_id: stale})
            self.assertEqual(case_runs._run_state(fresh.run_id), ("running", None))
            state, error = case_runs._run_state(stale.run_id)
        self.assertEqual(state, "failed")
        self.assertIn("deadline", error)

    def test_the_run_stops_itself_at_the_next_stage_boundary(self) -> None:
        now = datetime.now()
        with mock.patch.dict("os.environ", {"PENSION_RUN_DEADLINE_MIN": "90"}):
            stale = _run("c" * 12, "running", now - timedelta(minutes=95), None, self.root)
            with self.assertRaises(runs.RunDeadlineExceeded):
                stale.emit("verify", "stage 6 starting")
            stale.emit("error", "stopped")                  # the closing events are never refused
            stale.emit("end", "failed", state="failed")
            self.assertEqual([e["stage"] for e in stale.events], ["error", "end"])
            fresh = _run("d" * 12, "running", now - timedelta(minutes=5), None, self.root)
            fresh.emit("verify", "stage 6 starting")        # within the deadline: as before
            self.assertEqual(fresh.events[-1]["message"], "stage 6 starting")


class Registry(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = dict(runs.RUNS)
        runs.RUNS.clear()
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-registry-")
        self.root = Path(self._tmp.name)
        self._patches = [mock.patch.object(runs, "ARTIFACTS", self.root),
                         mock.patch.object(runs, "UPLOADS", self.root / "uploads")]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        runs.RUNS.clear()
        runs.RUNS.update(self._saved)
        self._tmp.cleanup()

    def test_old_finished_runs_leave_the_registry_and_come_back_from_disk(self) -> None:
        now = datetime.now()
        old_done = _run("1" * 12, "done", now - timedelta(hours=3), now - timedelta(hours=2), self.root)
        (old_done.run_dir / "case_report.json").write_text(json.dumps({"claimant_name": "x"}))
        new_done = _run("2" * 12, "done", now - timedelta(minutes=20), now - timedelta(minutes=10), self.root)
        old_failed = _run("3" * 12, "failed", now - timedelta(hours=3), now - timedelta(hours=2), self.root)
        running = _run("4" * 12, "running", now - timedelta(hours=3), None, self.root)
        for r in (old_done, new_done, old_failed, running):
            runs.RUNS[r.run_id] = r
        with mock.patch.dict("os.environ", {"PENSION_RUN_REGISTRY_KEEP_MIN": "60"}):
            dropped = runs.prune_registry(now)
        self.assertEqual(dropped, [old_done.run_id])
        self.assertEqual(set(runs.RUNS), {new_done.run_id, old_failed.run_id, running.run_id})
        # The dropped run is still there for anyone who asks: rebuilt from its artefacts.
        adopted = runs.adopt_from_disk(old_done.run_id)
        self.assertIsNotNone(adopted)
        self.assertEqual(adopted.state, "done")
        self.assertIn(old_done.run_id, runs.RUNS)
        # A failed run has no report to adopt, so it stays a day before it is dropped.
        with mock.patch.dict("os.environ", {"PENSION_RUN_REGISTRY_KEEP_MIN": "60"}):
            later = runs.prune_registry(now + timedelta(hours=21))          # failed run 23 h old: kept
            self.assertEqual(set(later), {new_done.run_id, old_done.run_id})
            self.assertEqual(set(runs.RUNS), {old_failed.run_id, running.run_id})
            self.assertEqual(runs.prune_registry(now + timedelta(hours=25)), [old_failed.run_id])
            self.assertEqual(set(runs.RUNS), {running.run_id})              # a running run is never dropped


if __name__ == "__main__":
    unittest.main()
