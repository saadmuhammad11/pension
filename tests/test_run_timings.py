"""Every run's time is kept in the database, per stage and per model call (perf/pipeline, 7 Oct 2026).

    python3 -m unittest tests.test_run_timings -v
"""
from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from api import db
from pipeline import timing


class RunTimings(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(); self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "portal.sqlite3"
        self._p = mock.patch.object(db, "DB_PATH", self.path); self._p.start(); self.addCleanup(self._p.stop)
        timing._conn, timing._conn_path = None, None            # a fresh connection on the test database
        db.migrate()

    def _rows(self, run_id: str) -> list[sqlite3.Row]:
        conn = db.connect()
        try:
            return conn.execute("SELECT * FROM run_timings WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        finally:
            conn.close()

    def test_the_migration_creates_the_table(self) -> None:
        conn = db.connect()
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(run_timings)")}
        finally:
            conn.close()
        self.assertTrue({"run_id", "kind", "stage", "page", "duration_s", "queue_s", "pages", "status", "detail_json"} <= cols)

    def test_stages_and_model_calls_are_recorded_under_the_bound_run(self) -> None:
        with timing.bind("r-1"):
            with timing.stage("identify", pages=3) as t:
                t["detail"]["note"] = "x"
                timing.model_call("vision", started=time.time() - 1.5, ended=time.time(), schema="PAGE_IDENTITY", page=7,
                                  detail={"prompt_tokens": 10})
            try:
                with timing.stage("extract"):
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
        rows = self._rows("r-1")
        self.assertEqual([(r["kind"], r["stage"], r["status"]) for r in rows],
                         [("model", "vision", "ok"), ("stage", "identify", "ok"), ("stage", "extract", "error")])
        self.assertEqual((rows[0]["page"], rows[0]["name"]), (7, "PAGE_IDENTITY"))
        self.assertGreaterEqual(rows[0]["duration_s"], 1.4)
        self.assertEqual(rows[1]["pages"], 3)
        self.assertIn("boom", rows[2]["detail_json"])

    def test_nothing_is_written_outside_a_run_and_a_database_error_never_raises(self) -> None:
        timing.model_call("vision", started=time.time(), ended=time.time())
        self.assertEqual(self._rows("none"), [])
        with mock.patch.object(timing, "_connection", lambda: None), timing.bind("r-2"):
            with timing.stage("identify"):
                pass                                                   # no exception
        self.assertEqual(self._rows("r-2"), [])

    def test_pool_workers_carry_the_run_and_their_queue_wait(self) -> None:
        def work(page: int) -> str:
            time.sleep(0.05)
            timing.model_call("vision", started=time.time() - 0.05, ended=time.time(), page=page)
            return timing.current()
        with timing.bind("r-3"), ThreadPoolExecutor(max_workers=1) as pool:
            futures = [pool.submit(timing.carry(work, stage="identify", page=p), p) for p in (1, 2)]
            self.assertEqual([f.result() for f in futures], ["r-3", "r-3"])
        rows = self._rows("r-3")
        self.assertEqual([r["page"] for r in rows], [1, 2])
        self.assertGreaterEqual(rows[1]["queue_s"], 0.04)               # the second page waited for the worker

    def test_the_slot_wait_and_the_summary(self) -> None:
        timing.record("queue", "slot", started=time.time() - 2, ended=time.time(), queue_s=2.0, run_id="r-4")
        with timing.bind("r-4"):
            with timing.stage("identify", pages=2):
                timing.model_call("vision", started=time.time() - 0.5, ended=time.time(), page=1)
                timing.model_call("ocr", started=time.time() - 0.2, ended=time.time(), page=1)
        s = timing.summary("r-4")
        self.assertAlmostEqual(s["slot_wait_s"], 2.0, places=1)
        self.assertIn("identify", s["stages"])
        self.assertEqual(s["models"]["vision"]["calls"], 1)
        self.assertEqual(s["models"]["ocr"]["calls"], 1)

    def test_page_numbers_come_from_the_image_name(self) -> None:
        self.assertEqual(timing.page_of("artifacts/run-x/pages/p041.png"), 41)
        self.assertEqual(timing.page_of("artifacts/run-x/pages/p004-04.png"), 4)      # the pipeline's own naming
        self.assertEqual(timing.page_of("/tmp/p9.png"), 9)
        self.assertIsNone(timing.page_of("signature.jpg"))

    def test_the_executor_times_every_stage_and_the_model_clients_record(self) -> None:
        """The hooks exist where the audit of the pipeline says the time goes."""
        root = Path(__file__).resolve().parents[1]
        runs = (root / "api/runs.py").read_text()
        for stage in ("ingest", "identify", "verify", "assemble", "classify", "extract", "assertions", "signatures", "determine", "report"):
            self.assertIn(f'timing.stage("{stage}"', runs, stage)
        self.assertIn('timing.record("queue", "slot"', runs)
        self.assertIn('timing.model_call("vision"', (root / "extraction/client.py").read_text())
        self.assertIn('timing.model_call("ocr"', (root / "extraction/ocr.py").read_text())
        self.assertIn("timing.carry(identify_page", (root / "pipeline/run.py").read_text())
        # Stage 6's pooled read is wrapped in timing.carry so its queue wait is recorded. The
        # callable is `reader` -- the per-run read cache's confirmed() or, with no cache,
        # extract_page_confirmed directly (extraction.readcache, perf/read-cache).
        self.assertIn("timing.carry(reader", (root / "pipeline/extract.py").read_text())
        gp = (root / "GP/backend/gpf").read_text if False else None
        self.assertIn("timing.model_call(model", (root / "GP/backend/gpf/clients/model_client.py").read_text())
        self.assertIn('timing.stage("classify"', (root / "GP/backend/gpf/reading/pipeline.py").read_text())


if __name__ == "__main__":
    unittest.main()
