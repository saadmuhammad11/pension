"""What the engine refuses to be told, and what it records about what it was told.

    python3 -m unittest tests.test_engine_input_integrity -v

Two things an audit depends on, neither of which is a pension figure:

  * ``inputs`` is the block an auditor recomputes a determination FROM (SOP §8.5). A figure
    recorded there that is not the figure used makes the recomputation disagree with the
    determination beside it, which is the one thing the block exists to prevent.
  * ``pension_kind`` decides whether the December 2024 reduction for voluntary retirement
    applies. It reaches the engine as a string and is compared by equality, so an
    unrecognised value used to mean "no reduction" -- silently, and in favour of the payment.

Both were entries in ``test_known_defects.py`` and moved in when they started passing.
Standard library only; no GPU, no network, no clock.
"""

from __future__ import annotations

import sys
from pathlib import Path

# So the file runs directly as well as under `-m unittest` from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest
from datetime import date, datetime
from decimal import Decimal

from rules import select_pack
from rules.emoluments import AnnualPay, reckon_average
from rules.engine import SELF_PENSION_KINDS, SelfPensionCase, determine_self_pension
from rules.money import rupees

COMPUTED_AT = datetime(2026, 6, 3, 10, 0, 0)


def _pack():
    return select_pack(effective_date=date(2026, 2, 18))


class TheRecordedInputsAreTheInputsUsed(unittest.TestCase):
    """``inputs`` wrote ``int(emol.reckonable_total)``, which truncates.

    Under the December 2024 amendment the base is a three-year mean and so routinely
    fractional. FMT-01 requires half-up rounding everywhere else, and ``int()`` truncated --
    so an auditor recomputing from ``inputs`` got a different answer.
    """

    def _case(self):
        years = [AnnualPay(y, Decimal(a)) for y, a in
                 ((2023, "100000"), (2024, "100001"), (2025, "100001"))]
        pack = _pack()
        emol = reckon_average(years, pack, retirement=date(2026, 2, 18))
        case = SelfPensionCase(
            case_ref="FMT-01", date_of_birth=date(1966, 2, 19),
            date_of_first_entry=date(1993, 12, 8), date_of_retirement=date(2026, 2, 18),
            emoluments=emol, bps=19, base_is_three_year_average=True,
        )
        return determine_self_pension(case, pack, COMPUTED_AT), emol

    def test_the_base_really_is_fractional(self):
        """Establishes that the rounding below has something to bite on."""
        _, emol = self._case()
        self.assertNotEqual(emol.reckonable_total, int(emol.reckonable_total))

    def test_the_recorded_base_is_rounded_not_truncated(self):
        det, emol = self._case()
        self.assertEqual(det.inputs["pension_base"], rupees(emol.reckonable_total))

    def test_it_rounds_up_where_half_up_requires_it(self):
        """100000.666... truncates to 100000 and rounds to 100001. The two differ."""
        _, emol = self._case()
        self.assertEqual(rupees(emol.reckonable_total), 100001)
        det, _ = self._case()
        self.assertEqual(det.inputs["pension_base"], 100001)

    def test_the_recorded_base_stays_json_serialisable(self):
        """``inputs`` is written straight to case_report.json; a Decimal has no encoder."""
        import json

        det, _ = self._case()
        json.dumps(det.inputs)
        self.assertIsInstance(det.inputs["pension_base"], int)

    def test_the_family_path_rounds_its_emoluments_the_same_way(self):
        from rules.engine import (
            DeathInServiceCase,
            determine_family_pension_death_in_service,
        )

        pack = _pack()
        years = [AnnualPay(y, Decimal(a)) for y, a in
                 ((2023, "100000"), (2024, "100001"), (2025, "100001"))]
        emol = reckon_average(years, pack, retirement=date(2026, 2, 18))
        case = DeathInServiceCase(
            case_ref="FMT-01-FAM", date_of_birth=date(1966, 2, 19),
            date_of_first_entry=date(1993, 12, 8), date_of_death=date(2021, 6, 1),
            emoluments=emol, bps=19, base_is_three_year_average=True,
        )
        det = determine_family_pension_death_in_service(case, pack, COMPUTED_AT)
        self.assertEqual(det.inputs["reckonable_emoluments"],
                         rupees(emol.reckonable_total))


class AnUnrecognisedPensionKindIsRefused(unittest.TestCase):
    """The reduction is applied by equality against ``{"RETIRING_PENSION"}``.

    Any other string -- a typo one letter out, a case type the engine has not been taught,
    or a family-pension type from a caller that supplied annual pay on the wrong bundle --
    selected the unreduced branch. Same discipline as the commutation step one function
    later, where a missing age factor raises because "a missing factor is not a zero
    factor" (BLOCKING-19).
    """

    def _case(self, kind: str, date_of_birth: date = date(1965, 1, 1)):
        pack = _pack()
        retirement = date(2025, 1, 1)
        emol = reckon_average(
            [AnnualPay(y, Decimal("100000")) for y in (2022, 2023, 2024)],
            pack, retirement=retirement,
        )
        return SelfPensionCase(
            case_ref="KIND", date_of_birth=date_of_birth,
            date_of_first_entry=date(1995, 1, 1), date_of_retirement=retirement,
            emoluments=emol, bps=17, pension_kind=kind,
            base_is_three_year_average=True,
        ), pack

    def test_every_known_kind_is_accepted(self):
        for kind in sorted(SELF_PENSION_KINDS):
            with self.subTest(kind=kind):
                case, pack = self._case(kind)
                try:
                    det = determine_self_pension(case, pack, COMPUTED_AT)
                except Exception as exc:                    # noqa: BLE001
                    # A known kind may still be refused on the FACTS of this synthetic case
                    # (a 60-year-old cannot take an invalid pension at the superannuation
                    # age). What it must never be refused for is the kind itself.
                    self.assertNotIn("is not a self pension", str(exc))
                else:
                    self.assertTrue(det.steps)

    def test_an_unrecognised_kind_is_refused_rather_than_treated_as_involuntary(self):
        case, pack = self._case("RETIRING_PENSON")          # one letter out
        with self.assertRaises(ValueError):
            determine_self_pension(case, pack, COMPUTED_AT)

    def test_the_refusal_names_the_kinds_it_knows(self):
        """BRAIN §15.2: say so precisely. An officer has to be able to act on the message."""
        case, pack = self._case("RETIRING_PENSON")
        with self.assertRaises(ValueError) as caught:
            determine_self_pension(case, pack, COMPUTED_AT)
        message = str(caught.exception)
        self.assertIn("RETIRING_PENSON", message)
        for kind in SELF_PENSION_KINDS:
            self.assertIn(kind, message)

    def test_a_family_pension_type_does_not_compute_as_a_self_pension(self):
        """``pipeline.report`` builds a self-pension case whenever annual pay was keyed at
        intake. On a family bundle that used to compute an unreduced self pension."""
        case, pack = self._case("FAMILY_PENSION_DEATH_IN_SERVICE")
        with self.assertRaises(ValueError):
            determine_self_pension(case, pack, COMPUTED_AT)

    def test_an_empty_kind_is_refused(self):
        case, pack = self._case("")
        with self.assertRaises(ValueError):
            determine_self_pension(case, pack, COMPUTED_AT)

    def test_the_reduction_still_applies_to_the_kind_it_is_for(self):
        """The guard must not have shut the reduction off."""
        from rules.engine import VOLUNTARY_RETIREMENTS

        self.assertLessEqual(VOLUNTARY_RETIREMENTS, SELF_PENSION_KINDS)
        # Age 58: inside the ages the amendment's reduction table states. At 60 the table
        # has no factor and the engine rightly raises instead of paying unreduced.
        case, pack = self._case("RETIRING_PENSION", date_of_birth=date(1967, 1, 1))
        det = determine_self_pension(case, pack, COMPUTED_AT)
        self.assertLess(det.step("VOL-RED-01").amount, det.step("CALC-01").amount)


if __name__ == "__main__":
    unittest.main()
