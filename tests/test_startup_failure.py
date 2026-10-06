"""Production does not serve on a half-migrated database (audit 6 Oct 2026, Medium).

    python3 -m unittest tests.test_startup_failure -v

A failure in migrate() or seed() at start-up was printed and the API went on serving. And the
GP Fund module records migration 0005 itself, so the two starting together on a fresh database
could make the pension side's plain INSERT fail and abort every migration after it.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api import case_runs, db

GOOD_SECRET = "s" * 20 + "Q7vX2pL9mR4tW8yB3nD6"


class Migrations(unittest.TestCase):
    def test_a_version_recorded_by_the_gp_module_meanwhile_does_not_stop_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as d, mock.patch.object(db, "DB_PATH", Path(d) / "portal.sqlite3"):
            real_apply = db._apply_migration

            def apply_while_gp_records_0005(conn, sql):
                real_apply(conn, sql)
                if "gpf_cases" in sql:                     # 0005, which gpf/store.py also records
                    conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                                 "VALUES ('0005_gpf_cases', 'now')")
            with mock.patch.object(db, "_apply_migration", apply_while_gp_records_0005):
                applied = db.migrate()
            later = sorted(p.stem for p in db.MIGRATIONS.glob("*.sql") if p.stem > "0005")
            self.assertTrue(later)
            for version in later:
                self.assertIn(version, applied)


class StartUp(unittest.TestCase):
    def _start(self, env: dict) -> None:
        from fastapi.testclient import TestClient
        from api.server import app
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {**env, "PENSION_JWT_SECRET": GOOD_SECRET}), \
                mock.patch.object(db, "DB_PATH", Path(d) / "portal.sqlite3"), \
                mock.patch.object(db, "migrate", side_effect=RuntimeError("disk full")), \
                mock.patch.object(case_runs, "start_reconciler", lambda *a, **k: None):
            with TestClient(app):
                pass

    def test_production_refuses_to_serve_after_a_failed_start_up(self) -> None:
        with self.assertRaises(RuntimeError):
            self._start({"PENSION_ENV": "production"})

    def test_the_trial_still_comes_up(self) -> None:
        self._start({"PENSION_ENV": ""})


if __name__ == "__main__":
    unittest.main()
