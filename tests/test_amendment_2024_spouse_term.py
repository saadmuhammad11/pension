"""Rule 4.10(1) as substituted by FD.SR-III-4-244/2023(B), 2 December 2024: the spouse's
family pension runs for ten years or until re-marriage, an issueless spouse for life, more
than one widow share equally. The notification is on file as "Amendmant Rules.pdf".

Both family-pension calculators state the term, each on its own footing:

* Form D-I (death in service) reads it from the effective-dated rule pack. A pack written
  before the amendment has no ``family_pension_duration`` and the determination says what it
  always said: for life. That keeps the golden case byte-identical.
* Form D-II (death of a pensioner) reads it from the provisional yaml and applies it only to
  deaths on or after the date the yaml carries, saying so on the face of the step either way.

Standard library only; no GPU and no network.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class DeathInServiceTerm(unittest.TestCase):
    def test_the_amended_pack_states_a_ten_year_term(self):
        from rules.engine import spouse_term
        from rules.loader import load_pack
        step, caveat = spouse_term(load_pack("PB-2024.12"), date(2026, 2, 19))
        self.assertIsNotNone(step)
        self.assertEqual(step.rule_id, "FAM-DUR-01")
        self.assertEqual(step.unit, "date")
        self.assertIn("2026-02-19 + 10 years = 2036-02-19", step.computation_shown)
        self.assertIn("re-marriage", step.computation_shown)
        self.assertIn("no issue", step.note)
        self.assertIn("more than one widow", step.note)
        self.assertIn("FD.SR-III-4-244/2023(B)", caveat)
        self.assertNotIn("for life, subject", caveat)

    def test_a_pre_amendment_pack_says_for_life_verbatim(self):
        from rules.engine import SPOUSE_FOR_LIFE_CAVEAT, spouse_term
        from rules.loader import load_pack
        step, caveat = spouse_term(load_pack("PB-2026.02"), date(2026, 2, 19))
        self.assertIsNone(step)
        self.assertEqual(caveat, SPOUSE_FOR_LIFE_CAVEAT)
        self.assertTrue(caveat.startswith("Family pension is payable to the widow/widower for life"))

    def test_leap_day_commencement_falls_back_to_28_february(self):
        from rules.engine import add_years
        self.assertEqual(add_years(date(2028, 2, 29), 10), date(2038, 2, 28))
        self.assertEqual(add_years(date(2025, 9, 18), 10), date(2035, 9, 18))


def _widow(**over):
    from rules.dii import DeathAfterRetirementCase
    base = dict(case_ref="T-TERM", sanctioned_pension=Decimal("2512"),
                claimant_relation="widow", date_of_death_of_pensioner=date(2025, 9, 17))
    base.update(over)
    return DeathAfterRetirementCase(**base)


def _determine(case):
    from rules.dii import (DIIRules, classify_case,
                           determine_family_pension_death_after_retirement)
    return determine_family_pension_death_after_retirement(
        case, DIIRules.load(confirmations=[]), classify_case(prescribed_form="FORM_D_II"),
        datetime(2026, 6, 3, 10, 0, 0),
    )


class DeathAfterRetirementTerm(unittest.TestCase):
    def _step(self, det):
        found = [s for s in det.steps if s.rule_id == "FAM-AR-06"]
        self.assertEqual(len(found), 1, [s.rule_id for s in det.steps])
        return found[0]

    def test_a_death_after_the_amendment_gets_a_dated_term(self):
        det = _determine(_widow())
        step = self._step(det)
        # commencement is day_after_death in the shipped yaml: 2025-09-18, so the term
        # ends on 2035-09-18 unless she re-marries first.
        self.assertIn("2025-09-18 + 10 years = 2035-09-18", step.computation_shown)
        self.assertIn("re-marriage", step.computation_shown)
        self.assertIn("no issue", step.note)
        self.assertIn("PROVISIONAL", step.note)
        self.assertIn("cessation.spouse_term_years",
                      det.inputs["provisional_keys"])
        self.assertIn("BLOCKING-07", det.unverified_engaged)

    def test_a_death_on_the_day_of_the_notification_is_inside_it(self):
        step = self._step(_determine(_widow(date_of_death_of_pensioner=date(2024, 12, 2))))
        self.assertIn("2024-12-03 + 10 years = 2034-12-03", step.computation_shown)

    def test_a_death_before_the_amendment_applies_no_term_and_says_why(self):
        step = self._step(_determine(_widow(date_of_death_of_pensioner=date(2018, 3, 1))))
        self.assertTrue(step.computation_shown.startswith("no term applied"))
        self.assertIn("2018-03-01", step.computation_shown)
        self.assertIn("2024-12-02", step.computation_shown)
        self.assertNotIn("2028-03-02", step.computation_shown)

    def test_a_daughter_gets_no_spouse_term(self):
        det = _determine(_widow(claimant_relation="divorced daughter",
                                date_of_divorce=date(2025, 1, 5)))
        self.assertEqual([s for s in det.steps if s.rule_id == "FAM-AR-06"], [])

    def test_confirming_both_keys_makes_the_step_final(self):
        from rules.dii import (DIIRules, classify_case,
                               determine_family_pension_death_after_retirement)
        rules = DIIRules.load(confirmations=[
            {"key": "cessation.spouse_term_years", "value": "10"},
            {"key": "cessation.spouse_term_applies_to_deaths_from", "value": "2024-12-02"},
        ])
        det = determine_family_pension_death_after_retirement(
            _widow(), rules, classify_case(prescribed_form="FORM_D_II"),
            datetime(2026, 6, 3, 10, 0, 0))
        step = self._step(det)
        self.assertNotIn("PROVISIONAL", step.note)
        self.assertNotIn("cessation.spouse_term_years", det.inputs["provisional_keys"])


class TheDeskCanConfirmTheTerm(unittest.TestCase):
    def test_the_new_keys_are_confirmable_and_validated(self):
        from rules.confirmations import ConfirmationError, _validate_value
        self.assertEqual(_validate_value("BLOCKING-07", "cessation.spouse_term_years", "10"), "10")
        self.assertEqual(_validate_value("BLOCKING-07",
                                         "cessation.spouse_term_applies_to_deaths_from",
                                         "2024-12-02"), "2024-12-02")
        with self.assertRaises(ConfirmationError):
            _validate_value("BLOCKING-07", "cessation.spouse_term_years", "ten")
        with self.assertRaises(ConfirmationError):
            _validate_value("BLOCKING-07", "cessation.spouse_term_applies_to_deaths_from",
                            "02-12-2024")


if __name__ == "__main__":
    unittest.main()
