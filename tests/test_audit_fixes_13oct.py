"""The go-live blockers of the audit of 13 October 2026.

The first five each turned a failure of our own reading into either a clean report or an
accusation against a department:

* C-03  a stage 6 failure left no gap and the battery reported the case clean
* H-02  an unreadable signature block reached the rules as "the form carries no signature"
* H-04  an OCR outage removed filed documents from the case and the checklist called them MISSING
* H-05  one flaky vision read called an attested copy unattested where no second reader ran
* H-07  the revoked-token sweep compared a UTC stamp against a local clock

The rest of the batch:

* M-03 / H-06  the timing recorder broke its own promise of silence and failed completed runs,
               and a run that died there never gave its verification slot back
* H-08  ``case_runs.run_id`` is not unique, and six queries treated it as a key with no ordering
* M-07  every sign-in ran two sequential scans over an append-only ``audit_log``

C-04, the GP Fund module's missing authentication, is the one blocker of this batch whose tests
live elsewhere, on both sides of the key: ``tests/test_portal_holds_the_gpf_key.py`` and
``GP/backend/tests/test_module_needs_the_portals_key.py``.

    python3 -m unittest tests.test_audit_fixes_13oct -v
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


class StageSixFailureIsNeverACleanCase(unittest.TestCase):
    """C-03. Silence from a check that did not run is not a clean result."""

    def test_the_run_records_a_gap_when_the_stage_raises(self):
        """The handler must record the gap, as the extract stage beside it already does."""
        import inspect

        from api import runs
        source = inspect.getsource(runs._execute)
        after = source.split('run.emit("assertions", f"cross-document checks incomplete')[1]
        self.assertIn('_record_gap(run, "assertions"', after.split("# Stage 6b")[0])

    def test_a_record_with_no_cross_checks_raises_a_high_finding(self):
        from rules.caserecord import CaseRecord
        from rules.flags import HIGH, check_cross_checks_ran

        clean = CaseRecord(case_ref="PC-1", case_type="SELF_PENSION")
        self.assertEqual(check_cross_checks_ran(clean, None), [])

        failed = CaseRecord(case_ref="PC-1", case_type="SELF_PENSION", cross_checks_ran=False)
        raised = check_cross_checks_ran(failed, None)
        self.assertEqual(len(raised), 1)
        self.assertEqual(raised[0].severity, HIGH)
        self.assertTrue(raised[0].affects_determination)
        self.assertIn("did not run", raised[0].finding)

    def test_the_golden_fixture_is_not_accused_of_it(self):
        """A curated fixture has no assertions.json either, and is not a failed run. The signal
        is the gap the run records when the stage raises, never the absence of the file."""
        import shutil

        from pipeline.report import build_report
        from rules.flags import CROSS_CHECKS_NOT_RUN

        golden = Path(__file__).resolve().parents[1] / "artifacts" / "golden"
        if not (golden / "identities.json").exists():
            raise unittest.SkipTest("no golden artefacts")
        self.assertFalse((golden / "assertions.json").exists(), "fixture changed; revisit this test")

        with tempfile.TemporaryDirectory() as t:
            run = Path(t) / "golden"
            shutil.copytree(golden, run)
            clean = build_report(run, with_citations=False)
            self.assertFalse([f for f in clean["flags"] if f["class"] == CROSS_CHECKS_NOT_RUN])

            # Now the same artefacts, with the run's own record saying stage 6 refused.
            (run / "determination_gap.json").write_text(json.dumps({"assertions": "ocr is down"}))
            (run / "case_report.json").unlink(missing_ok=True)
            failed = build_report(run, with_citations=False)
            raised = [f for f in failed["flags"] if f["class"] == CROSS_CHECKS_NOT_RUN]
            self.assertEqual(len(raised), 1, "a failed stage 6 must not read as a clean case")
            self.assertEqual(raised[0]["severity"], "HIGH")

    def test_the_check_is_in_the_battery(self):
        from rules.flags import BATTERY, check_cross_checks_ran
        self.assertIn(check_cross_checks_ran, BATTERY)


class AnUnreadableSignatureBlockIsNotAnUnsignedForm(unittest.TestCase):
    """H-02. "We could not read the page" must not become a shortcoming letter."""

    def _record(self, **kw):
        from rules.caserecord import CaseRecord, PsaSignature
        return CaseRecord(case_ref="PC-1", case_type="SELF_PENSION",
                          psa_signatures=(PsaSignature(document="FORM_D_I", page=3, **kw),))

    def test_an_unread_block_is_raised_against_the_reading_not_the_department(self):
        from rules.flags import MEDIUM, check_psa_specimen

        raised = check_psa_specimen(self._record(unreadable="the model returned no answer"), None)
        self.assertEqual(len(raised), 1)
        flag = raised[0]
        self.assertEqual(flag.severity, MEDIUM)
        self.assertEqual(flag.owner, "AG_OFFICE")
        self.assertIn("could not be read", flag.title)
        # The wording that used to go to the department must not appear.
        self.assertNotIn("there is no signature", flag.finding)
        self.assertNotIn("no officer's stamp", flag.finding)

    def test_a_block_that_was_read_is_judged_as_before(self):
        """With no specimen for the department the check still says nothing, as it always did."""
        from rules.flags import check_psa_specimen
        self.assertEqual(check_psa_specimen(self._record(signature_present=True), None), [])

    def test_the_marker_survives_into_the_record(self):
        from rules.caserecord import PsaSignature
        self.assertIsNone(PsaSignature(document="FORM_D_I", page=1).unreadable)


class AnOcrOutageNeverRemovesAFiledDocument(unittest.TestCase):
    """H-04. A reader that did not answer is not a page with no heading on it."""

    def _rows(self, tmp: Path):
        (tmp / "manifest.json").write_text(json.dumps(
            {"pages": [{"page": 5, "image_path": "pages/p005.png"}]}))
        return [{"page": 5, "document_type": "AFFIDAVIT", "attested": True}]

    def test_a_failed_read_returns_none_rather_than_empty_text(self):
        from pipeline.extract import page_ocr_text
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            self._rows(tmp)
            with mock.patch("extraction.ocr.ocr_page", side_effect=OSError("ocr is down")):
                self.assertIsNone(page_ocr_text(tmp, 5))

    def test_the_page_is_recorded_unread_and_nothing_is_concluded_from_it(self):
        from pipeline.run import documents_named_by_their_own_heading
        from rules.caserecord import Document
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            rows = self._rows(tmp)
            unread: list[dict] = []
            with mock.patch("extraction.ocr.ocr_page", side_effect=OSError("ocr is down")):
                added = documents_named_by_their_own_heading(
                    tmp, rows, (Document("AFFIDAVIT", (5,)),), unread)
        self.assertEqual(added, ())                       # nothing invented
        self.assertEqual([u["page"] for u in unread], [5])
        self.assertIn("could not be read", unread[0]["reason"])

    def test_a_page_that_really_has_no_heading_is_not_recorded_unread(self):
        from pipeline.run import documents_named_by_their_own_heading
        from rules.caserecord import Document
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            rows = self._rows(tmp)
            (tmp / "ocr_text.json").write_text(json.dumps({"5": "nothing of interest here"}))
            unread: list[dict] = []
            added = documents_named_by_their_own_heading(
                tmp, rows, (Document("AFFIDAVIT", (5,)),), unread)
        self.assertEqual(added, ())
        self.assertEqual(unread, [])                      # read, and it said nothing

    def test_a_re_run_once_ocr_is_back_clears_the_old_refusal(self):
        """stage_assemble writes the file or removes it, never leaves a stale one behind."""
        import inspect

        from pipeline import run as pipeline_run
        source = inspect.getsource(pipeline_run.stage_assemble)
        self.assertIn('_write(run / "ocr_unread.json", unread)', source)
        self.assertIn('unlink(missing_ok=True)', source.split("else:")[-1])

    def test_the_report_raises_the_unread_page_as_a_finding(self):
        """The finding must reach the officer even when stage 6 never ran."""
        from rules.caserecord import CaseRecord
        from rules.flags import HIGH, check_unreadable_documents
        record = CaseRecord(case_ref="PC-1", case_type="SELF_PENSION",
                            unreadable=((5, "OTHER", "the page's printed heading could not be read"),))
        raised = check_unreadable_documents(record, None)
        self.assertEqual(len(raised), 1)
        self.assertEqual(raised[0].severity, HIGH)


class NoSecondReaderMeansUnjudged(unittest.TestCase):
    """H-05. One vision read on its own cannot call a copy unattested."""

    def test_a_page_no_second_reader_reached_is_left_unjudged(self):
        from dataclasses import replace
        from rules.caserecord import Document

        # The correction as build_report applies it, with an empty set of second readings.
        checked: dict = {}

        def attested(d: Document) -> Document:
            if d.attested is not False:
                return d
            seen = [checked[p] for p in d.pages if p in checked]
            if not seen:
                return replace(d, attested=None)
            return d

        doc = Document("CNIC", (4,), attested=False)
        self.assertIsNone(attested(doc).attested)

    def test_the_report_leaves_it_unjudged_when_nothing_was_checked(self):
        import inspect

        from pipeline import report
        source = inspect.getsource(report.build_report)
        block = source.split("def _attested(")[1].split("documents = tuple(")[0]
        # The "no second reading" arm must not hand the single read back unchanged.
        self.assertIn("if not seen:", block)
        self.assertIn("return replace(d, attested=None)", block.split("if not seen:")[1])

    def test_an_unjudged_copy_raises_no_attestation_finding(self):
        """check_attestation reports an explicit False only; None is "not judged"."""
        from rules.caserecord import CaseRecord, Document
        from rules.flags import check_attestation
        record = CaseRecord(case_ref="PC-1", case_type="SELF_PENSION",
                            documents=(Document("CNIC", (4,), present=True, attested=None),))
        self.assertEqual(check_attestation(record, None), [])


class SigningOutLastsAsLongAsTheToken(unittest.TestCase):
    """H-07. The revocation row and the sweep must read the same clock."""

    def test_the_expiry_is_written_in_the_same_clock_as_the_sweep(self):
        from api import db

        exp = int((datetime.now() + timedelta(hours=12)).timestamp())
        # As api.v2 writes it now.
        expires = datetime.fromtimestamp(exp).isoformat(timespec="seconds")
        # The sweep deletes every row whose expires_at is already past.
        self.assertGreater(expires, db.now(), "the revocation would be swept away at once")
        # And it is still there eleven hours from now.
        later = (datetime.now() + timedelta(hours=11)).isoformat(timespec="seconds")
        self.assertGreater(expires, later)

    def test_the_old_utc_form_would_have_been_swept_early(self):
        """The bug, pinned: a UTC stamp is behind local time wherever the offset is positive."""
        exp = int((datetime.now() + timedelta(hours=12)).timestamp())
        utc_form = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        local_form = datetime.fromtimestamp(exp).isoformat(timespec="seconds")
        offset = datetime.now().astimezone().utcoffset() or timedelta(0)
        if offset > timedelta(0):
            self.assertLess(utc_form, local_form)

    def test_api_v2_no_longer_builds_the_expiry_in_utc(self):
        import inspect

        from api import v2
        source = inspect.getsource(v2.logout)
        self.assertIn('datetime.fromtimestamp(int(claims.get("exp", 0))).isoformat', source)
        self.assertNotIn("tz=timezone.utc", source)


class TimingNeverFailsARunThatFinished(unittest.TestCase):
    """M-03 and H-06. ``record`` promises to be silent on any database error, and must be.

    ``db.target()`` raises when no database is configured. It was called outside the guard, so
    the exception left ``record``, left the ``stage`` context manager, and left the
    ``with timing.stage("run")`` that wraps a whole verification: a run that had finished was
    reported failed. Worse, the same call sits between acquiring a verification slot and the
    ``try/finally`` that gives it back, so a run that died there held its slot for the life of
    the process. Two of those stop every verification in the office.
    """

    def setUp(self) -> None:
        from pipeline import timing
        self.timing = timing
        timing._conn, timing._conn_path = None, None
        self.addCleanup(setattr, timing, "_conn", None)
        self.addCleanup(setattr, timing, "_conn_path", None)

    def _no_database(self):
        from api import db
        return mock.patch.object(db, "target", side_effect=RuntimeError(
            "no database: set PENSION_DATABASE_URL (PostgreSQL; deploy/postgres.env) or PENSION_DB"))

    def test_recording_a_row_with_no_database_is_silent(self) -> None:
        with self._no_database():
            self.timing.record("queue", "slot", started=time.time() - 1, ended=time.time(),
                               name="verification slot", run_id="r-no-db")

    def test_a_stage_that_succeeds_is_not_turned_into_a_failure(self) -> None:
        """The bug as the office saw it: a completed verification reported failed."""
        with self._no_database():
            with self.timing.bind("r-no-db"):
                with self.timing.stage("run"):
                    pass

    def test_a_stage_that_raises_still_raises_its_own_error(self) -> None:
        """Silence about the timing row is not silence about the run."""
        with self._no_database():
            with self.assertRaises(ValueError):
                with self.timing.bind("r-no-db"):
                    with self.timing.stage("run"):
                        raise ValueError("the run's own failure")

    def test_a_model_call_with_no_database_is_silent(self) -> None:
        with self._no_database():
            self.timing.model_call("vision", started=time.time() - 1, ended=time.time())

    def test_the_slot_is_given_back_even_if_its_row_cannot_be_written(self) -> None:
        """H-06. Nothing measured on the way past may cost the run its slot."""
        import inspect

        from api import runs
        source = inspect.getsource(runs._execute_when_free)
        acquire = source.index("_RUN_SLOTS.acquire()")
        record = source.index("timing.record")
        execute = source.index("execute(run)")
        self.assertLess(acquire, record)
        self.assertLess(record, execute)
        self.assertIn("except Exception:", source[record:execute])
        self.assertIn("finally:", source)


class ARunIdIsReadTheSameWayEveryTime(unittest.TestCase):
    """H-08. The column is not unique, so every query on it needs a deterministic order."""

    def test_no_query_on_a_run_id_is_left_to_chance(self) -> None:
        """Six call sites treat it as a key, including the approval gate."""
        source = (Path(__file__).resolve().parents[1] / "api" / "v2.py").read_text(encoding="utf-8")
        sites = [i for i in range(len(source)) if source.startswith("FROM case_runs WHERE run_id = ?", i)]
        self.assertGreaterEqual(len(sites), 6, "the call sites moved; re-check them")
        for at in sites:
            following = source[at:at + 400]
            self.assertIn("ORDER BY started_at DESC, submission_no DESC, id DESC", following,
                          f"no tiebreaker at {source.count(chr(10), 0, at) + 1}")
            self.assertIn("LIMIT 1", following)

    def test_the_latest_run_of_a_case_breaks_its_tie_too(self) -> None:
        """Two rows of one case can share ``started_at`` to the second."""
        from api import v2
        import inspect
        source = inspect.getsource(v2._case_dict)
        self.assertIn("ORDER BY started_at DESC, submission_no DESC, id DESC LIMIT 1", source)

    def test_a_run_started_in_the_same_second_as_the_one_before_is_still_the_later_one(self) -> None:
        """What the arbitrary tiebreaker actually cost: ``started_at`` was second-precision and
        ``id`` is a uuid4, so a resubmission verified within a second of the previous run showed
        the previous run as the case's latest. It is stamped to the microsecond now."""
        source = (Path(__file__).resolve().parents[1] / "api" / "case_runs.py").read_text(encoding="utf-8")
        at = source.index("INSERT INTO case_runs(id, case_id, run_id, submission_no, started_by, started_at")
        self.assertIn("db.stamp()", source[at:at + 500])
        self.assertNotIn("db.now()", source[at:at + 400])

    def test_a_microsecond_stamp_sorts_after_the_second_it_is_in(self) -> None:
        """The rows written before 13 Oct 2026 keep their places, because text order agrees."""
        from datetime import datetime
        t = datetime(2026, 10, 13, 15, 0, 1, 123456)
        self.assertGreater(t.isoformat(timespec="microseconds"), t.isoformat(timespec="seconds"))
        later = datetime(2026, 10, 13, 15, 0, 2)
        self.assertGreater(later.isoformat(timespec="seconds"), t.isoformat(timespec="microseconds"))

    def test_the_approval_gate_is_the_one_that_matters(self) -> None:
        """Which row comes back decides whether an approval must carry a written reason."""
        from api import v2
        import inspect
        source = inspect.getsource(v2._act)
        at = source.index("FROM case_runs WHERE run_id = ?")
        self.assertIn("ORDER BY started_at DESC, submission_no DESC, id DESC", source[at:at + 300])
        self.assertIn("against = latest is None", source[at:at + 500])


class TheHotPathsHaveTheirIndexes(unittest.TestCase):
    """H-08 and M-07. Both were sequential scans over tables that only ever grow."""

    def setUp(self) -> None:
        from api import db
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-0017-")
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "portal.sqlite3"
        p = mock.patch.object(db, "DB_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)
        db.migrate()
        self.db = db

    def _indexes(self, table: str) -> set:
        conn = self.db.connect()
        try:
            return {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ?", (table,))}
        finally:
            conn.close()

    def test_the_migration_indexes_the_run_id(self) -> None:
        self.assertIn("case_runs_run", self._indexes("case_runs"))

    def test_the_migration_indexes_what_every_sign_in_reads(self) -> None:
        self.assertIn("audit_log_entity", self._indexes("audit_log"))

    def test_the_run_id_index_is_not_unique(self) -> None:
        """The live table already holds rows that share one; a unique index would not build."""
        conn = self.db.connect()
        try:
            row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'case_runs_run'").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertNotIn("UNIQUE", (row["sql"] or "").upper())

    def test_the_migration_can_be_run_again(self) -> None:
        """Every statement in 0017 is IF NOT EXISTS; re-running it changes nothing (cf. M-09)."""
        sql = (Path(__file__).resolve().parents[1] / "api" / "migrations"
               / "0017_hot_path_indexes.sql").read_text(encoding="utf-8")
        body = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
        statements = [s.strip() for s in body.split(";") if s.strip()]
        self.assertTrue(statements)
        for statement in statements:
            self.assertIn("IF NOT EXISTS", statement.upper())
        conn = self.db.connect()
        try:
            for statement in statements:
                conn.execute(statement)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
