"""Request-path syncs with the pipeline are rate-limited (audit 6 Oct 2026, later report item 8).

    python3 -m unittest tests.test_sync_throttle -v

Every case read and the 3-second poll of every open browser called sync_run_states, and a sync
with a GP Fund examination pending asks the module (up to 10 s each), so 88 browsers could tie
the API up in GP Fund calls. Within SYNC_MIN_INTERVAL_S of the last sync a request-path call now
does nothing; the reconciler's own timer always syncs.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from api import case_runs, db
from tests import test_api_v2 as _v2


class _CountingConnection:
    """A connection that counts the pending-runs query; sqlite3.Connection cannot be patched."""
    def __init__(self, conn):
        self._conn = conn
        self.pending_queries = 0

    def execute(self, sql, *args, **kwargs):
        if "FROM case_runs cr JOIN cases" in sql:
            self.pending_queries += 1
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class SyncThrottle(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown

    def _conn(self) -> _CountingConnection:
        conn = db.connect()
        self.addCleanup(conn.close)
        return _CountingConnection(conn)

    def test_only_one_sync_per_interval_unless_forced(self) -> None:
        conn = self._conn()
        with mock.patch.object(case_runs, "SYNC_MIN_INTERVAL_S", 60.0), mock.patch.object(case_runs, "_LAST_SYNC", 0.0):
            case_runs.sync_run_states(conn)                 # first: syncs
            case_runs.sync_run_states(conn)                 # within the interval: nothing
            case_runs.sync_run_states(conn)
            self.assertEqual(conn.pending_queries, 1)
            case_runs.sync_run_states(conn, force=True)     # the reconciler: always
            self.assertEqual(conn.pending_queries, 2)

    def test_an_interval_of_zero_syncs_every_time(self) -> None:
        conn = self._conn()
        with mock.patch.object(case_runs, "SYNC_MIN_INTERVAL_S", 0.0):
            case_runs.sync_run_states(conn)
            case_runs.sync_run_states(conn)
            self.assertEqual(conn.pending_queries, 2)


class Default(unittest.TestCase):
    def test_the_default_interval_is_about_a_second(self) -> None:
        if os.environ.get("PENSION_SYNC_MIN_INTERVAL_S"):
            self.skipTest("interval set in this environment")
        self.assertGreater(case_runs.SYNC_MIN_INTERVAL_S, 0)
        self.assertLessEqual(case_runs.SYNC_MIN_INTERVAL_S, 3)


if __name__ == "__main__":
    unittest.main()
