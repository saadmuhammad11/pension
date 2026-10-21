"""The proforma for qualifying service (scope change C2; decided by the user 12 Oct 2026, S3).

    /home/tmc/vllm_env/bin/python3 -m unittest tests.test_qualifying_service_proforma -v

The AG office's "Proposed Performa for Qualifying Service for Pension" is a document type of its
own, recognised by its printed title and confirmed by OCR (a vision claim alone is not enough).
Either it or the service book satisfies AG-10, for every case from now on, and it is a service
record for gazetted and non-gazetted servants alike. Its date of birth, personnel number and CNIC
join the existing cross-document checks; its appointment and retirement dates are compared by a
check of their own. No figures from the office's sample (a real servant's) appear here.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: The printed title as the office's sample spells it: "PERFORMA", and "SEVICE" for "service".
SAMPLE_HEAD = ("PROPOSED PERFORMA FOR QUALIFYING SEVICE FOR PENSION\n"
               "(For Use in the Administrative/Attached Department/Office)\nPARTICULARS OF EMPLOYEE")
#: Form B-I's clause 3, which also says "qualifying service for pension" and must not match.
FORM_B_I_CLAUSE = ("His Date of Birth is 01-01-1966 Date of 1st entry into government service is "
                   "01-01-1990. Total length of qualifying service for pension is 36 years")


def _value(v):
    return {"value": v, "confidence": 1.0, "unreadable_reason": None if v else "blank"}


class Recognition(unittest.TestCase):
    def test_the_type_its_gloss_and_its_schema_exist(self) -> None:
        from extraction.schemas import DOCUMENT_TYPE_GLOSS, DOCUMENT_TYPES, SCHEMAS
        self.assertIn("QUALIFYING_SERVICE_PROFORMA", DOCUMENT_TYPES)
        self.assertIn("QUALIFYING SERVICE FOR PENSION", DOCUMENT_TYPE_GLOSS["QUALIFYING_SERVICE_PROFORMA"])
        self.assertIn("QUALIFYING_SERVICE_PROFORMA", SCHEMAS)
        from pipeline.extract import _IDENTIFIER_DOCS, _SCHEMA_FOR
        self.assertIn("QUALIFYING_SERVICE_PROFORMA", _IDENTIFIER_DOCS)          # read in stage 6
        self.assertEqual(_SCHEMA_FOR["QUALIFYING_SERVICE_PROFORMA"], "QUALIFYING_SERVICE_PROFORMA")

    def test_the_title_is_matched_as_printed_and_not_on_form_b_i(self) -> None:
        from extraction.identify import titles_on_page
        self.assertEqual(titles_on_page(SAMPLE_HEAD), ("QUALIFYING_SERVICE_PROFORMA",))
        self.assertIn("QUALIFYING_SERVICE_PROFORMA",
                      titles_on_page("PROFORMA FOR QUALIFYING SERVICE FOR PENSION"))
        # OCR "corrects" the sample's spelling back as PERFORMANCE (12 Oct 2026, real read).
        self.assertIn("QUALIFYING_SERVICE_PROFORMA",
                      titles_on_page("PROPOSED PERFORMANCE FOR QUALIFYING SERVICE FOR PENSION"))
        self.assertNotIn("QUALIFYING_SERVICE_PROFORMA", titles_on_page(FORM_B_I_CLAUSE))

    def _ident(self, doc_type: str = "QUALIFYING_SERVICE_PROFORMA"):
        from extraction.identify import PageIdentity
        import dataclasses
        fields = {f.name for f in dataclasses.fields(PageIdentity)}
        base = dict(page=3, document_type=doc_type, confidence=0.98, evidence="heading",
                    is_first_page=True, signed_by_psa=False, attested=False)
        return PageIdentity(**{k: v for k, v in base.items() if k in fields})

    def test_ocr_confirms_a_proforma_claim_by_its_title(self) -> None:
        from extraction import identify
        from extraction.ocr import PageText
        with mock.patch("extraction.ocr.ocr_page", return_value=PageText(3, SAMPLE_HEAD, "t")):
            kept = identify._verify_proforma_claim(self._ident(), "p3.png")
        self.assertEqual(kept.document_type, "QUALIFYING_SERVICE_PROFORMA")

    def test_a_claim_ocr_cannot_corroborate_is_denied_and_asked_again(self) -> None:
        from extraction import identify
        from extraction.ocr import PageText
        with mock.patch("extraction.ocr.ocr_page", return_value=PageText(3, FORM_B_I_CLAUSE, "t")), \
             mock.patch.object(identify, "identify_page", return_value=self._ident("OTHER")) as again:
            out = identify._verify_proforma_claim(self._ident(), "p3.png")
        self.assertEqual(out.document_type, "OTHER")
        self.assertEqual(out.downgraded_from, "QUALIFYING_SERVICE_PROFORMA")
        self.assertIn("QUALIFYING_SERVICE_PROFORMA", again.call_args.kwargs["extra_instruction"])

    def test_an_ocr_failure_keeps_the_claim(self) -> None:
        from extraction import identify
        with mock.patch("extraction.ocr.ocr_page", side_effect=OSError("ocr down")):
            out = identify._verify_proforma_claim(self._ident(), "p3.png")
        self.assertEqual(out.document_type, "QUALIFYING_SERVICE_PROFORMA")


#: The particulars block as OCR transcribes it, with synthetic values.
OCR_BLOCK = ("PROPOSED PERFORMANCE FOR QUALIFYING SERVICE FOR PENSION\n"
             "III. CNIC Number: 35202-1234567-1\n"
             "VIII. Personnel Number (if applicable): 30001234\n"
             "IX. Date of Birth: 01-07-1966\n"
             "X. Date of Appointment: 13-6-1989\n"
             "XI. Date of Supernuation: 130-06-2026\n"
             "XII. Date of Retirement / Death: 30-6-2026\n")


class Facts(unittest.TestCase):
    def _data(self, **over):
        base = {"employee_name": "Test Servant", "cnic": "35202-1234567-1", "personnel_no": "30001234",
                "date_of_birth": "1966-07-01", "date_of_appointment": "13-06-1989",
                "date_of_retirement_or_death": "2026-06-30"}
        base.update(over)
        return {k: _value(v) for k, v in base.items()}

    def test_facts_both_readers_agree_on_become_assertions(self) -> None:
        from pipeline.extract import proforma_assertions
        got = {(a["field"], a["value"]) for a in proforma_assertions(self._data(), 4, OCR_BLOCK)}
        self.assertEqual(got, {("date_of_birth", "1966-07-01"), ("date_first_entry", "1989-06-13"),
                               ("date_of_retirement", "2026-06-30"), ("personnel_no", "30001234"),
                               ("cnic", "3520212345671")})
        cnic = next(a for a in proforma_assertions(self._data(), 4, OCR_BLOCK) if a["field"] == "cnic")
        self.assertEqual((cnic["person"], cnic["role"], cnic["page"]), ("Test Servant", "employee", 4))

    def test_a_fact_the_readers_disagree_on_is_left_out(self) -> None:
        # The office's sample: the vision model read the year of birth wrong, twice; OCR read it right.
        from pipeline.extract import proforma_assertions
        got = {a["field"] for a in proforma_assertions(self._data(date_of_birth="01-07-1968"), 4, OCR_BLOCK)}
        self.assertNotIn("date_of_birth", got)
        self.assertIn("date_first_entry", got)

    def test_nothing_is_kept_without_the_second_reader(self) -> None:
        from pipeline.extract import proforma_assertions
        self.assertEqual(proforma_assertions(self._data(), 4, None), [])
        self.assertEqual(proforma_assertions(self._data(), 4, ""), [])

    def test_misreads_are_dropped_not_reported(self) -> None:
        from pipeline.extract import proforma_assertions
        data = self._data(cnic="35202-12345-1", personnel_no="12", date_of_birth="1st July",
                          date_of_appointment=None, date_of_retirement_or_death=None)
        self.assertEqual(proforma_assertions(data, 4, OCR_BLOCK), [])


def _record(docs: tuple[str, ...], assertions=(), bps: int | None = None, variant: str = "FRESH_SELF"):
    from rules import CaseRecord, Document
    from rules.caserecord import Assertion, Source
    return CaseRecord(
        case_ref="T-PROFORMA", case_type="SELF_PENSION",
        documents=tuple(Document(t, (n + 1,)) for n, t in enumerate(docs)),
        assertions=tuple(Assertion(f, v, Source(p, d)) for f, v, p, d in assertions),
        pay_scale_bps=bps, case_variant=variant,
    )


class Checklist(unittest.TestCase):
    def _item(self, record, item_id: str, variant: str):
        from rules.checklist import run_checklist
        return next(i for i in run_checklist(record, variant=variant).items if i.id == item_id)

    def test_ag_10_is_not_on_the_sheet_at_all(self) -> None:
        """The office removed the requirement on 20 Oct 2026 and the LINE on 21 Oct. An empty
        bundle used to make AG-10 MISSING, then NOT_REQUIRED; now it is not printed at all.
        What the office asks for instead is AG-26, Performa for Qualifying Service."""
        from rules.checklist import run_checklist
        items = [i.id for i in run_checklist(_record((), bps=4), variant="FRESH_SELF").items]
        self.assertNotIn("AG-10", items)
        self.assertIn("AG-26", items)

    def test_a_filed_proforma_is_cited_against_ag_26(self) -> None:
        """It used to be acknowledged against AG-10 as FOUND_NOT_REQUIRED. AG-10 is off the
        sheet from 21 Oct 2026, and the proforma now answers a line that is actually required:
        AG-26, PRESENT, with the page it was found on."""
        from rules.checklist import PRESENT
        item = self._item(_record(("QUALIFYING_SERVICE_PROFORMA",), bps=4), "AG-26", "FRESH_SELF")
        self.assertEqual(item.status, PRESENT)
        self.assertTrue(item.located, "the page carrying it must be cited")
        self.assertEqual(item.requirement, "Performa for Qualifying Service")

    def test_a_filed_service_book_no_longer_answers_anything(self) -> None:
        """The book satisfied AG-10, and AG-10 is gone. A bundle carrying a service book and no
        proforma leaves AG-26 MISSING: the office asked for the proforma instead, and a book is
        not one. This is the whole point of the change -- the department must file the new paper."""
        from rules.checklist import MISSING
        item = self._item(_record(("SERVICE_BOOK",), bps=4), "AG-26", "FRESH_SELF")
        self.assertEqual(item.status, MISSING)

    def test_the_proforma_is_a_service_record_for_every_servant(self) -> None:
        # CL-09 is the FD checklist's service-record line (death in service), which runs where
        # no office-sheet column is selected; it asks the same of gazetted and non-gazetted.
        from dataclasses import replace
        from rules.checklist import PRESENT, run_checklist
        for bps in (4, 18):                                    # non-gazetted and gazetted
            rec = replace(_record(("QUALIFYING_SERVICE_PROFORMA",), bps=bps, variant=None),
                          case_type="FAMILY_PENSION_DEATH_IN_SERVICE")
            item = next(i for i in run_checklist(rec).items if i.id == "CL-09")
            self.assertEqual(item.status, PRESENT, bps)


class Checks(unittest.TestCase):
    def _flags(self, record):
        from rules.flags import run_battery
        from rules.loader import select_pack
        return run_battery(record, select_pack(effective_date=date(2026, 10, 12)))

    def test_a_different_appointment_date_is_raised_for_the_officer(self) -> None:
        from rules.flags import CONTRA_SERVICE, MEDIUM
        rec = _record(("QUALIFYING_SERVICE_PROFORMA", "SALARY_STATEMENT"), assertions=(
            ("date_first_entry", "1989-06-13", 1, "QUALIFYING_SERVICE_PROFORMA"),
            ("date_first_entry", "1988-06-13", 2, "SALARY_STATEMENT")))
        found = [f for f in self._flags(rec) if f.flag_class == CONTRA_SERVICE]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, MEDIUM)
        self.assertIn("date of appointment", found[0].title)
        from rules.flag_curation import summary
        self.assertTrue(summary(found[0]).startswith("Appointment date on the service proforma differs"))

    def test_agreeing_dates_and_bundles_without_a_proforma_raise_nothing(self) -> None:
        from rules.flags import check_proforma_service_dates
        from rules.loader import select_pack
        pack = select_pack(effective_date=date(2026, 10, 12))
        same = _record(("QUALIFYING_SERVICE_PROFORMA", "SALARY_STATEMENT"), assertions=(
            ("date_first_entry", "1989-06-13", 1, "QUALIFYING_SERVICE_PROFORMA"),
            ("date_first_entry", "1989-06-13", 2, "SALARY_STATEMENT")))
        self.assertEqual(check_proforma_service_dates(same, pack), [])
        without = _record(("LPC", "SALARY_STATEMENT"), assertions=(
            ("date_first_entry", "1989-06-13", 1, "LPC"),
            ("date_first_entry", "1988-06-13", 2, "SALARY_STATEMENT")))
        self.assertEqual(check_proforma_service_dates(without, pack), [])

    def test_its_date_of_birth_joins_the_identity_check(self) -> None:
        from rules.flags import CONTRA_IDENTITY
        rec = _record(("QUALIFYING_SERVICE_PROFORMA", "SALARY_STATEMENT"), assertions=(
            ("date_of_birth", "1966-07-01", 1, "QUALIFYING_SERVICE_PROFORMA"),
            ("date_of_birth", "1965-07-01", 2, "SALARY_STATEMENT")))
        titles = [f.title for f in self._flags(rec) if f.flag_class == CONTRA_IDENTITY]
        self.assertTrue(any(t.startswith("Date-of-birth mismatch") for t in titles), titles)


if __name__ == "__main__":
    unittest.main()
