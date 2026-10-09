"""The database runs on PostgreSQL or SQLite from the same statements (api.dbcore, 9 Oct 2026).

    python3 -m unittest tests.test_database_engines -v

The translation tests need no server. The round-trip tests run on whatever engine the suite is
pointed at (PENSION_TEST_DATABASE_URL, or the SQLite file), and the import test needs PostgreSQL.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api import db, dbcore


class Translation(unittest.TestCase):
    def t(self, sql: str, **kw) -> str | None:
        return dbcore.translate(sql, has_params=kw.pop("has_params", True), **kw)

    def test_question_marks_become_psycopg_placeholders_outside_literals(self) -> None:
        self.assertEqual(self.t("SELECT * FROM t WHERE a = ? AND b LIKE ?"), "SELECT * FROM t WHERE a = %s AND b LIKE %s")
        self.assertEqual(self.t("SELECT 'a?b', ? FROM t WHERE y = 'it''s' AND z LIKE 'PC-%'"),
                         "SELECT 'a?b', %s FROM t WHERE y = 'it''s' AND z LIKE 'PC-%%'")
        self.assertEqual(self.t('SELECT "weird?name" FROM t WHERE x = ?'), 'SELECT "weird?name" FROM t WHERE x = %s')

    def test_a_percent_is_left_alone_when_there_are_no_parameters(self) -> None:
        self.assertEqual(self.t("SELECT 'PC-%' FROM t", has_params=False), "SELECT 'PC-%' FROM t")

    def test_named_parameters(self) -> None:
        self.assertEqual(self.t("INSERT INTO e(id, at) VALUES (:id, :at) WHERE y = '12:30' AND z = x::text", named=True),
                         "INSERT INTO e(id, at) VALUES (%(id)s, %(at)s) WHERE y = '12:30' AND z = x::text")

    def test_insert_or_ignore_becomes_on_conflict_do_nothing(self) -> None:
        self.assertEqual(self.t("INSERT OR IGNORE INTO sm(version, applied_at) VALUES (?, ?)"),
                         "INSERT INTO sm(version, applied_at) VALUES (%s, %s) ON CONFLICT DO NOTHING")
        upsert = "INSERT INTO d(code) VALUES (?) ON CONFLICT(code) DO UPDATE SET name = excluded.name"
        self.assertEqual(self.t(upsert).count("ON CONFLICT"), 1)
        with self.assertRaises(NotImplementedError):
            self.t("INSERT OR REPLACE INTO t(a) VALUES (?)")

    def test_begin_immediate_and_pragmas(self) -> None:
        self.assertEqual(self.t("BEGIN IMMEDIATE", has_params=False), "BEGIN")
        self.assertIsNone(self.t("PRAGMA journal_mode=WAL", has_params=False))
        self.assertIn("information_schema.columns", self.t("PRAGMA table_info(run_timings)", has_params=False))
        self.assertEqual(self.t("PRAGMA foreign_keys=OFF", has_params=False), "SET session_replication_role = replica")
        self.assertEqual(self.t("PRAGMA foreign_keys=ON", has_params=False), "SET session_replication_role = DEFAULT")

    def test_ddl_for_postgres(self) -> None:
        self.assertEqual(dbcore.ddl_for_postgres("ALTER TABLE x ADD COLUMN y REAL;\nALTER TABLE x ADD COLUMN IF NOT EXISTS z TEXT;"),
                         "ALTER TABLE x ADD COLUMN IF NOT EXISTS y DOUBLE PRECISION;\nALTER TABLE x ADD COLUMN IF NOT EXISTS z TEXT;")

    def test_booleans_are_bound_as_integers(self) -> None:
        self.assertEqual(dbcore._params((True, False, 3, "x")), (1, 0, 3, "x"))
        self.assertEqual(dbcore._params({"a": True}), {"a": 1})

    def test_targets(self) -> None:
        self.assertTrue(dbcore.is_postgres("postgresql://u:p@h/d"))
        self.assertTrue(dbcore.is_postgres("postgres://u:p@h/d"))
        self.assertFalse(dbcore.is_postgres("/tmp/portal.sqlite3"))
        self.assertFalse(dbcore.is_postgres(Path("portal.sqlite3")))
        self.assertEqual(dbcore.masked("postgresql://pension:secret@127.0.0.1:5433/pension"),
                         "postgresql://pension:***@127.0.0.1:5433/pension")


class RowBehavesLikeSqliteRow(unittest.TestCase):
    def test_by_name_by_position_keys_dict_iteration(self) -> None:
        r = dbcore.Row(("id", "n"), ("a", 1))
        self.assertEqual((r["id"], r[1], r.keys(), dict(r), list(r), len(r)), ("a", 1, ["id", "n"], {"id": "a", "n": 1}, ["a", 1], 2))
        self.assertIn("n", r.keys())
        with self.assertRaises(IndexError):
            r["missing"]


class RoundTrip(unittest.TestCase):
    """The same statements on whichever engine the suite is pointed at."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-engines-"); self.addCleanup(self._tmp.cleanup)
        self._p = mock.patch.object(db, "DB_PATH", Path(self._tmp.name) / "portal.sqlite3"); self._p.start(); self.addCleanup(self._p.stop)
        db.migrate()
        self.conn = db.connect(); self.addCleanup(self.conn.close)

    def test_every_migration_is_recorded_and_the_tables_exist(self) -> None:
        versions = [r[0] for r in self.conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
        self.assertEqual(versions, sorted(p.stem for p in db.MIGRATIONS.glob("*.sql")))
        self.assertLessEqual(set(db.TABLES_IN_ORDER), dbcore.table_names(self.conn))

    def test_rows_come_back_by_name_and_position_on_either_engine(self) -> None:
        self.conn.execute("INSERT INTO departments(code, name, digital, active) VALUES (?, ?, ?, ?)", ("T1", "Test", True, 1))
        row = self.conn.execute("SELECT code, name, digital FROM departments WHERE code = ?", ("T1",)).fetchone()
        self.assertEqual((row["name"], row[0], row["digital"], dict(row)["code"]), ("Test", "T1", 1, "T1"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM departments WHERE code = ?", ("T1",)).fetchone()[0], 1)

    def test_transaction_rolls_back_and_upserts_hold(self) -> None:
        with self.assertRaises(RuntimeError):
            with db.transaction(self.conn):
                self.conn.execute("INSERT INTO departments(code, name) VALUES ('T2', 'x')")
                raise RuntimeError("abandon")
        self.assertIsNone(self.conn.execute("SELECT 1 FROM departments WHERE code = 'T2'").fetchone())
        self.conn.execute("INSERT OR IGNORE INTO departments(code, name) VALUES (?, ?)", ("T3", "first"))
        self.conn.execute("INSERT OR IGNORE INTO departments(code, name) VALUES (?, ?)", ("T3", "second"))
        self.assertEqual(self.conn.execute("SELECT name FROM departments WHERE code = 'T3'").fetchone()[0], "first")

    def test_the_append_only_rule_raises_the_shared_integrity_error(self) -> None:
        self.conn.execute("INSERT INTO audit_log(id, at, action, entity_type, entity_id) VALUES ('a', 't', 'X', 'case', 'c')")
        with self.assertRaises(db.IntegrityError):
            self.conn.execute("DELETE FROM audit_log")
        with self.assertRaises(db.IntegrityError):
            self.conn.execute("UPDATE audit_log SET reason = 'edited'")

    def test_table_info_works_on_either_engine(self) -> None:
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(cases)")}
        self.assertLessEqual({"id", "case_no", "status", "product", "case_type"}, cols)

    def test_health_names_the_engine(self) -> None:
        self.assertIn(db.backend(), ("postgres", "sqlite"))
        self.assertEqual(db.backend(), dbcore.backend_of(self.conn))


@unittest.skipUnless(db.TEST_DATABASE_URL, "needs PENSION_TEST_DATABASE_URL")
class ImportFromSqlite(unittest.TestCase):
    def test_a_sqlite_database_is_copied_whole(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agpb-import-") as tmp:
            src_path = Path(tmp) / "trial.sqlite3"
            src = dbcore.connect_sqlite(src_path)
            try:
                db.migrate(src)
                src.execute("INSERT INTO departments(code, name) VALUES ('D1', 'Dept')")
                src.execute("INSERT INTO users(id, username, display_name, password_hash, role, department_code, created_at, updated_at) "
                            "VALUES ('u1', 'ddo', 'DDO', 'h', 'DEPT_OFFICER', 'D1', 't', 't')")
                src.execute("INSERT INTO cases(id, case_no, department_code, created_via, created_by, status, created_at, updated_at) "
                            "VALUES ('c1', 'PC-2026-000001', 'D1', 'DEPARTMENT', 'u1', 'DRAFT', 't', 't')")
                src.execute("INSERT INTO case_events(id, case_id, seq, action, to_status, at) VALUES ('e1', 'c1', 1, 'CREATE', 'DRAFT', 't')")
                src.execute("INSERT INTO run_timings(id, run_id, kind, stage, started_at, ended_at, duration_s) VALUES (7, 'r', 'stage', 'x', 'a', 'b', 1.5)")
            finally:
                src.close()
            with mock.patch.object(db, "DB_PATH", Path(tmp) / "target.sqlite3"):
                db.migrate()
                counts = db.import_sqlite(src_path)
                self.assertEqual((counts["departments"], counts["users"], counts["cases"], counts["case_events"], counts["run_timings"]), (1, 1, 1, 1, 1))
                with self.assertRaises(RuntimeError):            # not empty any more
                    db.import_sqlite(src_path)
                counts = db.import_sqlite(src_path, replace=True)
                self.assertEqual(counts["cases"], 1)
                conn = db.connect()
                try:
                    self.assertEqual(dbcore.backend_of(conn), "postgres")
                    self.assertEqual(conn.execute("SELECT case_no FROM cases").fetchone()[0], "PC-2026-000001")
                    # the identity column carries on after the copied ids
                    conn.execute("INSERT INTO run_timings(run_id, kind, stage, started_at, ended_at, duration_s) VALUES ('r2', 'stage', 'y', 'a', 'b', 1)")
                    self.assertEqual([r[0] for r in conn.execute("SELECT id FROM run_timings ORDER BY id")], [7, 8])
                finally:
                    conn.close()


if __name__ == "__main__":
    unittest.main()
