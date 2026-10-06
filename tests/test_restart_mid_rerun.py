"""A restart in the middle of a re-run never presents the previous report as its result
(audit 6 Oct 2026, Medium).

    python3 -m unittest tests.test_restart_mid_rerun -v

Verifying unchanged papers again re-runs under the same run id, in the same folder. The old
case_report.json stayed there while the new run worked; if the API restarted before the run
finished, adopt_from_disk took that old report as the finished run, and the reconciler then
approved or returned the case on it -- possibly computed under older rules.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api import case_runs, runs


class RestartMidRerun(unittest.TestCase):
    def test_the_old_report_is_not_adopted_after_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            artifacts = Path(d)
            run_id = "0123456789ab"
            run_dir = artifacts / f"run-{run_id}"
            run_dir.mkdir()
            (run_dir / "manifest.json").write_text(json.dumps({"pages": []}))
            (run_dir / "case_report.json").write_text(json.dumps({"recommendation": {"verdict": "FORWARD"}}))
            with mock.patch.object(runs, "ARTIFACTS", artifacts), \
                    mock.patch.object(runs, "UPLOADS", artifacts / "uploads"), \
                    mock.patch.dict(runs.RUNS, clear=True):
                # The re-run starts, and the process dies before it writes a report: here, it
                # fails at once (its case file is not on disk), which leaves the folder exactly
                # as a crash after the first stage would.
                run = runs.Run(run_id=run_id, pdf_path=artifacts / "uploads" / "missing.pdf",
                               bundle_path=None, source={}, run_dir=run_dir)
                runs.execute(run)
                self.assertFalse((run_dir / "case_report.json").exists())
                self.assertTrue((run_dir / "case_report.previous.json").exists(), "the old report is kept")
                # The restart: nothing in memory.
                runs.RUNS.clear()
                self.assertIsNone(runs.adopt_from_disk(run_id))
                state, error = case_runs._run_state(run_id)
                self.assertEqual(state, "failed")
                self.assertIn("restarted", error)


if __name__ == "__main__":
    unittest.main()
