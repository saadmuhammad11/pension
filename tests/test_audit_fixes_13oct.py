"""The go-live blockers of the audit of 13 October 2026.

Five fixes, each of which turned a failure of our own reading into either a clean report or an
accusation against a department:

* C-03  a stage 6 failure left no gap and the battery reported the case clean
* H-02  an unreadable signature block reached the rules as "the form carries no signature"
* H-04  an OCR outage removed filed documents from the case and the checklist called them MISSING
* H-05  one flaky vision read called an attested copy unattested where no second reader ran
* H-07  the revoked-token sweep compared a UTC stamp against a local clock

    python3 -m unittest tests.test_audit_fixes_13oct -v
"""
from __future__ import annotations

import json
import tempfile
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


if __name__ == "__main__":
    unittest.main()
