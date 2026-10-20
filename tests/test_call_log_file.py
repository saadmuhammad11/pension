"""A run's calls are logged to a file in the run's own directory, not only to the database.

A log is append-only, read by eye and by grep, wants no schema, and should not compete with
case data for the database. run_timings stays for tools/bench.py, `python3 -m pipeline.timing`
and the GP Fund module's writer, which all read it -- PENSION_TIMING_DB=0 stops those writes
without touching the file log.

    python3 -m unittest tests.test_call_log_file -v
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from api import db
from pipeline import timing


class CallLogFile(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = unittest.mock.patch.object(db, "ROOT", Path(self.tmp.name))
        p.start(); self.addCleanup(p.stop)
        # the database half is exercised by tests.test_run_timings; keep this to the file
        q = unittest.mock.patch.object(timing, "TIMING_DB", False)
        q.start(); self.addCleanup(q.stop)

    def _lines(self, run_id: str) -> list[dict]:
        f = Path(self.tmp.name) / "artifacts" / f"run-{run_id}" / "calls.jsonl"
        if not f.exists():
            return []
        return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]

    def test_a_call_becomes_one_line_in_the_runs_directory(self) -> None:
        t = time.time()
        with timing.bind("abc123def456"):
            timing.record("model", "vision", started=t, ended=t + 2.5,
                          name="GENERIC_PAGE", page=7,
                          detail={"prompt_tokens": 2299, "completion_tokens": 1351})
        rows = self._lines("abc123def456")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["kind"], r["stage"], r["name"], r["page"]),
                         ("model", "vision", "GENERIC_PAGE", 7))
        self.assertAlmostEqual(r["duration_s"], 2.5, places=2)
        self.assertEqual(r["detail"]["completion_tokens"], 1351)
        self.assertEqual(r["status"], "ok")

    def test_each_run_gets_its_own_file(self) -> None:
        t = time.time()
        for rid in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):
            with timing.bind(rid):
                timing.record("stage", "ingest", started=t, ended=t + 1, pages=78)
        self.assertEqual(len(self._lines("aaaaaaaaaaaa")), 1)
        self.assertEqual(len(self._lines("bbbbbbbbbbbb")), 1)

    def test_calls_append_in_order(self) -> None:
        t = time.time()
        with timing.bind("cccccccccccc"):
            for i in range(5):
                timing.record("model", "ocr", started=t + i, ended=t + i + 0.5, page=i)
        rows = self._lines("cccccccccccc")
        self.assertEqual([r["page"] for r in rows], [0, 1, 2, 3, 4])

    def test_an_unbound_thread_writes_nothing(self) -> None:
        t = time.time()
        timing.record("model", "vision", started=t, ended=t + 1)
        self.assertEqual(self._lines(""), [])

    def test_the_log_can_be_turned_off(self) -> None:
        t = time.time()
        with unittest.mock.patch.object(timing, "CALL_LOG", False):
            with timing.bind("dddddddddddd"):
                timing.record("model", "vision", started=t, ended=t + 1)
        self.assertEqual(self._lines("dddddddddddd"), [])


if __name__ == "__main__":
    unittest.main()
