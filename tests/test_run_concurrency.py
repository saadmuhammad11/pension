"""No more verifications on the models at once than the limit (audit 6 Oct 2026, Medium).

    python3 -m unittest tests.test_run_concurrency -v

Every "Verify" started its own thread straight onto the GPU; with a dozen at once the model
servers queued them all and each ran into its timeout. Runs past PENSION_MAX_CONCURRENT_RUNS
now wait, still "queued", and their progress stream says so.
"""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from api import runs
from tests.test_api_v2 import PDF


class AtMostTwoAtOnce(unittest.TestCase):
    def test_runs_past_the_limit_wait_their_turn(self) -> None:
        release = threading.Event()
        running, peak, lock = [0], [0], threading.Lock()

        def slow_execute(run):
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            run.state = "running"
            release.wait(10)
            with lock:
                running[0] -= 1
            run.state = "done"

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(runs, "ARTIFACTS", Path(d)), \
                mock.patch.object(runs, "UPLOADS", Path(d) / "uploads"), \
                mock.patch.object(runs, "execute", slow_execute), \
                mock.patch.object(runs, "_RUN_SLOTS", threading.BoundedSemaphore(2)), \
                mock.patch.dict(runs.RUNS, clear=True):
            ids = [runs.start_run(PDF + f"-{i}".encode(), f"case{i}.pdf")["run_id"] for i in range(5)]
            time.sleep(0.5)
            states = [runs.RUNS[i].state for i in ids]
            self.assertEqual(states.count("running"), 2, states)
            self.assertEqual(states.count("queued"), 3, states)
            waiting = [i for i in ids if runs.RUNS[i].state == "queued"]
            self.assertTrue(all(any(e.get("stage") == "queue" for e in runs.RUNS[i].events) for i in waiting))
            release.set()
            for _ in range(100):
                if all(runs.RUNS[i].state == "done" for i in ids):
                    break
                time.sleep(0.05)
            self.assertEqual([runs.RUNS[i].state for i in ids], ["done"] * 5)
            self.assertEqual(peak[0], 2)


if __name__ == "__main__":
    unittest.main()
