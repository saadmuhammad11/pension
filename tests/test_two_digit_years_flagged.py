"""A date written with a two-digit year is put to a person, never completed by the code (audit L1).

    python3 -m unittest tests.test_two_digit_years_flagged -v

Until 7 Oct 2026 three readers completed the century themselves: the "expired on" clause
(28-2-21 -> 2021), the signature date (02.10.25 -> 2025) and the report's date parser, whose
"%y" made 6/3/26 into 2026 and would have made a date of birth 6/3/66 into 2066. Each now
returns nothing for such a date, the pipeline says so where it matters, and the report carries a
DATE-AMBIGUOUS finding naming every such date for the officer to settle.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rules.caserecord import CaseRecord
from rules.flags import DATE_AMBIGUOUS, MEDIUM, check_ambiguous_dates, run_battery
from rules.loader import load_pack

ROOT = Path(__file__).resolve().parents[1]
PACK = load_pack("PB-2026.02")


class Readers(unittest.TestCase):
    def test_two_digit_year_detector(self):
        from rules import two_digit_year
        for text, want in (("28-2-21", "28-2-21"), ("6/3/26", "6/3/26"), ("02.10.25", "02.10.25"),
                           ("expired on 28-2-21 (cert)", "28-2-21"),
                           ("28-02-2021", None), ("2021-02-28", None), ("4th March, 2026", None),
                           ("", None), (None, None), ("31657835", None)):
            with self.subTest(text=text):
                self.assertEqual(two_digit_year(text), want)

    def test_the_signature_date_is_not_completed(self):
        from datetime import date
        from pipeline.signatory import _date
        self.assertEqual(_date("02/10/2025"), date(2025, 10, 2))
        self.assertEqual(_date("2025-10-02"), date(2025, 10, 2))
        self.assertIsNone(_date("02.10.25"))
        self.assertIsNone(_date("2-10-25"))

    def test_the_pipeline_tells_the_officer_about_the_death_date(self):
        """The caveat the Form D-II path adds where the clause has a two-digit year."""
        from rules.case_type import ambiguous_death_date_from_form, death_date_from_form
        text = "Mst. X expired on 28-2-21 (death certificate attached)"
        self.assertIsNone(death_date_from_form(text))
        self.assertEqual(ambiguous_death_date_from_form(text), "28-2-21")
        source = (ROOT / "pipeline/extract.py").read_text()
        self.assertIn("ambiguous_death_date_from_form(form_text)", source)
        self.assertIn("key it at intake", source)


class Finding(unittest.TestCase):
    def _record(self, *dates):
        return CaseRecord(case_ref="t", case_type="FAMILY_PENSION", ambiguous_dates=tuple(dates))

    def test_no_such_date_no_finding(self):
        self.assertEqual(check_ambiguous_dates(self._record(), PACK), [])

    def test_a_determination_date_raises_a_medium_finding_that_affects_the_determination(self):
        flags = check_ambiguous_dates(self._record(("FORM_D_II", 3, "28-2-21", "date_of_death_of_pensioner")), PACK)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f.severity, f.flag_class, f.owner), (MEDIUM, DATE_AMBIGUOUS, "AG"))
        self.assertTrue(f.affects_determination)
        self.assertIn("28-2-21", f.title)
        self.assertIn("date of death of pensioner", f.finding)
        self.assertIn("p.3", f.finding)
        self.assertIn("key it at intake", f.required_action)
        self.assertEqual([(s.page, s.document) for s in f.asserted], [(3, "FORM_D_II")])

    def test_document_dates_alone_do_not_affect_the_determination(self):
        flags = check_ambiguous_dates(self._record(("FORWARDING_LETTER", 1, "6/3/26", "document_date"),
                                                   ("NADRA_FRC", 7, "1/2/26", "document_date")), PACK)
        self.assertEqual(len(flags), 1)
        self.assertFalse(flags[0].affects_determination)
        self.assertIn("2 dates", flags[0].title)
        self.assertIn("6/3/26", flags[0].finding)
        self.assertIn("1/2/26", flags[0].finding)

    def test_it_is_in_the_battery_and_blocks_auto_approval(self):
        flags = run_battery(self._record(("FORM_D_II", 3, "28-2-21", "date_of_death_of_pensioner")), PACK)
        self.assertIn(DATE_AMBIGUOUS, [f.flag_class for f in flags])
        from api.case_runs import outcome
        self.assertEqual(outcome({"missing_checklist": [], "unidentified_pages": [], "flags_total": len(flags),
                                  "checklist_present": True}), "CHECK_DONE")

    def test_summary_label_and_order_know_the_class(self):
        from rules import flag_curation
        f = check_ambiguous_dates(self._record(("FORM_D_II", 3, "28-2-21", "date_of_death_of_pensioner")), PACK)[0]
        s = flag_curation.summary(f)
        self.assertIn("two-digit year", s)
        self.assertLessEqual(len(s.split()), flag_curation.MAX_WORDS + 2)
        self.assertIn(DATE_AMBIGUOUS, flag_curation._CLASS_ORDER)
        self.assertIn("'DATE-AMBIGUOUS'", (ROOT / "portals/src/shared/labels.ts").read_text())


class Collected(unittest.TestCase):
    def test_the_report_collects_them_from_fields_document_dates_and_cnic_cards(self):
        from pipeline.report import two_digit_year_dates
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "fields.json").write_text(json.dumps({"fields": [
                {"name": "date_of_birth", "value": "6/3/66", "page": 2, "document": "FORM_B_I"},
                {"name": "date_of_retirement", "value": "01-06-2026", "page": 2, "document": "FORM_B_I"},
                {"name": "pension_drawn_rs", "value": "12/3/45", "page": 2},          # not a date field
            ]}))
            facts = {"document_dates": [{"document": "FORWARDING_LETTER", "page": 1, "value": "6/3/26"},
                                        {"document": "ANNEX_A", "page": 4, "value": "18/03/2026"}],
                     "cnic_cards": [{"page": 9, "date_of_expiry": "12.02.31"},
                                    {"page": 10, "date_of_expiry": "LIFETIME"}]}
            got = two_digit_year_dates(run, facts)
        self.assertEqual(got, (("FORM_B_I", 2, "6/3/66", "date_of_birth"),
                               ("FORWARDING_LETTER", 1, "6/3/26", "document_date"),
                               ("CNIC", 9, "12.02.31", "date_of_expiry")))


if __name__ == "__main__":
    unittest.main()
