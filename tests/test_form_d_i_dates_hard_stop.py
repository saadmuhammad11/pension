"""Form D-I: impossible dates are a hard stop; service under 10 years is a finding (business decision H3, 7 Oct 2026).

    python3 -m unittest tests.test_form_d_i_dates_hard_stop -v

The death-in-service engine computed from whatever three dates were read, so a misread date of
birth or an entry after the death yielded a plausible figure with no refusal, and no check
tested the dates against each other. Now the engine refuses (ImpossibleDates) before computing,
the report raises CONTRA-DATE (HIGH) for the department, and where the dates can all be true
but the service from first entry to the death is under the pack's minimum for a monthly
pension, SERVICE-SHORT (MEDIUM) for the reviewer.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path

from rules import select_pack
from rules.caserecord import CaseRecord
from rules.emoluments import reckon
from rules.engine import (DeathInServiceCase, ImpossibleDates, death_in_service_date_defects,
                          determine_family_pension_death_in_service)
from rules.flags import CONTRA_DATE, HIGH, MEDIUM, SERVICE_SHORT, check_form_d_i_dates, run_battery
from tests import golden_case as g

ROOT = Path(__file__).resolve().parents[1]
PACK = select_pack(effective_date=g.DATE_OF_DEATH)
BORN, ENTERED, DIED = date(1966, 2, 19), date(1993, 12, 8), date(2021, 7, 29)


class TheDefects(unittest.TestCase):
    def test_consistent_dates_have_none(self):
        self.assertEqual(death_in_service_date_defects(BORN, ENTERED, DIED, PACK), [])

    def test_each_impossibility_is_named(self):
        self.assertIn("not after the date of birth", death_in_service_date_defects(BORN, ENTERED, date(1960, 1, 1), PACK)[0])
        self.assertIn("not before the date of death", death_in_service_date_defects(BORN, date(2022, 1, 1), DIED, PACK)[0])
        self.assertIn("not after the date of birth", death_in_service_date_defects(BORN, date(1965, 1, 1), DIED, PACK)[0])
        self.assertIn("before the age of 15", death_in_service_date_defects(BORN, date(1975, 1, 1), DIED, PACK)[0])
        after_sixty = death_in_service_date_defects(date(1950, 1, 1), date(1975, 1, 1), DIED, PACK)
        self.assertTrue(any("notional superannuation" in d for d in after_sixty), after_sixty)

    def test_a_missing_date_is_not_a_defect_here(self):
        self.assertEqual(death_in_service_date_defects(None, ENTERED, DIED, PACK), [])
        self.assertEqual(death_in_service_date_defects(BORN, None, None, PACK), [])


class TheEngine(unittest.TestCase):
    def _case(self, **over):
        emol = reckon(g.PAY_COMPONENTS, PACK, printed_total=g.PRINTED_TOTAL_PAY)
        kw = dict(case_ref="t", date_of_birth=g.DATE_OF_BIRTH, date_of_first_entry=g.DATE_OF_FIRST_ENTRY,
                  date_of_death=g.DATE_OF_DEATH, emoluments=emol, bps=g.BPS, eol_days=0)
        kw.update(over)
        return DeathInServiceCase(**kw)

    def test_the_golden_case_still_computes(self):
        det = determine_family_pension_death_in_service(self._case(), PACK, datetime(2026, 6, 3, 10, 0, 0))
        self.assertTrue(det.steps)

    def test_a_death_before_the_birth_is_refused_before_anything_is_computed(self):
        with self.assertRaises(ImpossibleDates) as cm:
            determine_family_pension_death_in_service(self._case(date_of_death=date(1960, 1, 1)), PACK, datetime(2026, 6, 3))
        self.assertIn("cannot all be true", str(cm.exception))
        self.assertIn("Nothing was computed", str(cm.exception))

    def test_an_entry_after_the_death_is_refused(self):
        with self.assertRaises(ImpossibleDates):
            determine_family_pension_death_in_service(self._case(date_of_first_entry=date(2022, 1, 1)), PACK, datetime(2026, 6, 3))


class TheFindings(unittest.TestCase):
    def _record(self, dob=BORN, entry=ENTERED, death=DIED, doc="FORM_D_I"):
        dates = tuple((f, d, 41, doc) for f, d in (("date_of_birth", dob), ("date_first_entry", entry), ("date_of_death", death)) if d)
        return CaseRecord(case_ref="t", case_type="FAMILY_PENSION_DEATH_IN_SERVICE", form_dates=dates)

    def test_consistent_dates_and_enough_service_raise_nothing(self):
        self.assertEqual(check_form_d_i_dates(self._record(), PACK), [])
        self.assertEqual(check_form_d_i_dates(CaseRecord(case_ref="t", case_type="X"), PACK), [])

    def test_impossible_dates_are_a_high_hard_stop_for_the_department(self):
        flags = check_form_d_i_dates(self._record(death=date(1960, 1, 1)), PACK)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f.severity, f.flag_class, f.owner), (HIGH, CONTRA_DATE, "DEPARTMENT"))
        self.assertTrue(f.blocks_ppo and f.affects_determination)
        self.assertIn("hard stop", f.finding)
        self.assertEqual([(s.page, s.document) for s in f.asserted], [(41, "FORM_D_I")])
        self.assertIn(CONTRA_DATE, [x.flag_class for x in run_battery(self._record(death=date(1960, 1, 1)), PACK)])

    def test_service_under_ten_years_is_a_medium_finding_for_the_reviewer(self):
        flags = check_form_d_i_dates(self._record(entry=date(2015, 3, 1)), PACK)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f.severity, f.flag_class, f.owner), (MEDIUM, SERVICE_SHORT, "AG"))
        self.assertIn("may be under 10 years", f.title)
        # No length of service in the finding: the count is a computation this release does not
        # show (audit of 12 Oct 2026); the dates as read and the rule's minimum are what it says.
        self.assertNotRegex(f.title + " " + f.finding, r"\(\d+ years?\)|\d+y \d+m")
        self.assertIn("QS-02", f.finding)
        self.assertIn("No entitlement is computed", f.finding)

    def test_the_minimum_comes_from_the_pack(self):
        self.assertEqual(int(PACK.ref("qualifying_service", "min_years_for_monthly_pension")), 10)
        self.assertEqual(check_form_d_i_dates(self._record(entry=date(2011, 7, 1)), PACK), [])     # 10y 0m: enough

    def test_other_forms_dates_are_not_judged_as_a_death_in_service(self):
        self.assertEqual(check_form_d_i_dates(self._record(death=date(1960, 1, 1), doc="FORM_B_I"), PACK), [])


class TheReport(unittest.TestCase):
    def test_the_dates_are_taken_from_stage_4_s_form_fields(self):
        from pipeline.report import form_dates_from_fields
        fields = {"fields": [
            {"name": "date_of_birth", "value": "19-02-1966", "page": 41, "document": "FORM_D_I"},
            {"name": "date_first_entry", "value": "1993-12-08", "page": 41, "document": "FORM_D_I"},
            {"name": "date_of_death", "value": "29-7-21", "page": 41, "document": "FORM_D_I"},      # two-digit year: not a date here
            {"name": "deceased_name", "value": "Mst. X", "page": 41, "document": "FORM_D_I"},
            {"name": "date_of_birth", "value": "1966-02-19", "page": 9, "document": "CNIC"},         # not the form
        ]}
        self.assertEqual(form_dates_from_fields(fields), (("date_of_birth", date(1966, 2, 19), 41, "FORM_D_I"),
                                                          ("date_first_entry", date(1993, 12, 8), 41, "FORM_D_I")))
        self.assertEqual(form_dates_from_fields({}), ())

    def test_curated_labelled_and_cited(self):
        from pipeline.report import _FLAG_QUERY
        from rules import flag_curation
        for cls in (CONTRA_DATE, SERVICE_SHORT):
            self.assertIn(cls, _FLAG_QUERY)
            self.assertIn(f"'{cls}'", (ROOT / "portals/src/shared/labels.ts").read_text())
        self.assertIn(CONTRA_DATE, flag_curation._CLASS_ORDER)


if __name__ == "__main__":
    unittest.main()
