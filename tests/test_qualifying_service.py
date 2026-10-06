"""Qualifying service: the calendar arithmetic and the EOL exclusion. ``QS-01``, ``QS-05``, ``QS-16``.

    python3 -m unittest tests.test_qualifying_service -v

Standard library only, no GPU, no network, no clock. BUILD §6.2 requires this layer to be
recomputable "forever", and qualifying service is the input that the 30-year cap and the
QS-07 six-month boundary both turn on -- a span one month out can cost or credit a whole
year of pension for life.

Both classes here were entries in ``test_known_defects.py`` and moved in when they started
passing, which is what that file asks for.
"""

from __future__ import annotations

import sys
from pathlib import Path

# So the file runs directly as well as under `-m unittest` from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest
from datetime import date
from decimal import Decimal

from rules import select_pack
from rules.emoluments import AnnualPay, reckon_average
from rules.engine import SelfPensionCase, determine_self_pension
from rules.service import span

COMPUTED_AT = __import__("datetime").datetime(2026, 6, 3, 10, 0, 0)


def _pack():
    return select_pack(effective_date=date(2026, 2, 18))


class SpanBorrowsAMonthOnlyWhenOneIsOwed(unittest.TestCase):
    """``span`` used to borrow a month whenever ``end.day < start.day``.

    ``_add_months`` clamps to the last day of a shorter month, so 31 August plus one month
    is 30 September: the anchor lands exactly on the end date and no borrow is due. The
    borrow happened anyway and the span was reported one month short and ~30 days long --
    on the commonest shape a retirement takes, month end to month end.
    """

    def test_a_month_end_to_month_end_span_is_whole_months(self):
        length = span(date(1993, 8, 31), date(2025, 9, 30))
        self.assertEqual((length.years, length.months, length.days), (32, 1, 0))

    def test_january_31_to_february_29_is_one_month(self):
        length = span(date(2020, 1, 31), date(2020, 2, 29))
        self.assertEqual((length.years, length.months, length.days), (0, 1, 0))

    def test_january_31_to_february_28_in_a_common_year_is_one_month(self):
        length = span(date(2021, 1, 31), date(2021, 2, 28))
        self.assertEqual((length.years, length.months, length.days), (0, 1, 0))

    def test_the_total_still_adds_up(self):
        """The days were never lost -- they were attributed to the wrong unit."""
        self.assertEqual(span(date(1993, 8, 31), date(2025, 9, 30)).years, 32)

    def test_the_remainder_never_goes_negative(self):
        """The regression the borrow was written for. 31 January to 1 March is a 30-day
        shortfall against a 28-day month, and the remainder must not come out as -1:
        "P32Y1M-1D" in an audit record fails BRAIN §6.1 invariant 7."""
        length = span(date(2021, 1, 31), date(2021, 3, 1))
        self.assertEqual((length.years, length.months, length.days), (0, 1, 1))
        self.assertEqual(length.iso, "P0Y1M1D")

    def test_the_golden_case_span_is_unchanged(self):
        """08-12-1993 to notional superannuation 18-02-2026. BRAIN §9.1 states the
        exclusive reading as 32y 2m 10d, and the fix must not have moved it."""
        length = span(date(1993, 12, 8), date(2026, 2, 18))
        self.assertEqual(length.iso, "P32Y2M10D")

    def test_every_month_end_in_a_year_reconstructs_its_end_date(self):
        """The invariant behind all of the above: start + years + months + days == end."""
        from rules.service import _add_months

        for month in range(1, 13):
            start = date(2020, month, 1)
            last = _add_months(start, 1) - __import__("datetime").timedelta(days=1)
            for end in (last, _add_months(last, 1), _add_months(last, 7)):
                length = span(start, end)
                anchor = _add_months(start, length.years * 12 + length.months)
                self.assertEqual(
                    anchor + __import__("datetime").timedelta(days=length.days), end,
                    f"{start} -> {end} reported {length.human}",
                )


class ExtraordinaryLeaveIsDeductedNotMerelyRecorded(unittest.TestCase):
    """``QS-05``: extraordinary leave without pay is excluded unless specifically allowed.

    ``eol_days`` was carried on both case types, written into the audit ``inputs`` as though
    it had been applied, and used by no step. A servant with a year of EOL was credited with
    a year they did not serve -- and recording the figure beside a determination that ignored
    it was the worse half, because it read as a deduction that had been made.
    """

    def _determine(self, eol_days: int):
        pack = _pack()
        retirement = date(2026, 1, 1)
        emol = reckon_average(
            [AnnualPay(y, Decimal("100000")) for y in (2023, 2024, 2025)],
            pack, retirement=retirement,
        )
        case = SelfPensionCase(
            case_ref="QS-05", date_of_birth=date(1966, 1, 1),
            date_of_first_entry=date(2005, 1, 1), date_of_retirement=retirement,
            emoluments=emol, bps=17, eol_days=eol_days,
            base_is_three_year_average=True,
        )
        return determine_self_pension(case, pack, COMPUTED_AT)

    def test_a_year_of_unpaid_leave_changes_the_pension(self):
        without = self._determine(0).step("CALC-01").presented
        with_leave = self._determine(365).step("CALC-01").presented
        self.assertNotEqual(without, with_leave)

    def test_the_deduction_goes_the_right_way(self):
        """Excluded service can only ever reduce a pension."""
        without = self._determine(0).step("CALC-01").amount
        with_leave = self._determine(365).step("CALC-01").amount
        self.assertLess(with_leave, without)

    def test_the_working_is_shown_as_its_own_step(self):
        """BRAIN §14.1/§8.1: an officer must be able to see the deduction, not infer it."""
        det = self._determine(365)
        step = det.step("QS-05")
        self.assertIn("365 days", step.computation_shown)
        self.assertIn("21y 0m 0d", step.computation_shown)   # 2005-01-01 -> 2026-01-01
        self.assertIn("20y 0m 0d", step.computation_shown)   # less 365 days, to 2025-01-01

    def test_nil_leave_adds_no_step(self):
        """A step that says "less 0 days" is noise in an audit record."""
        with self.assertRaises(KeyError):
            self._determine(0).step("QS-05")

    def test_the_figure_is_still_recorded(self):
        self.assertEqual(self._determine(365).inputs["eol_days"], 365)

    def test_leave_longer_than_the_service_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._determine(365 * 40)
        self.assertIn("longer than the whole service", str(caught.exception))

    def test_negative_leave_is_refused(self):
        """A negative deduction would ADD service that was never served."""
        with self.assertRaises(ValueError) as caught:
            self._determine(-30)
        self.assertIn("negative", str(caught.exception))

    def test_the_family_path_deducts_it_too(self):
        """The field is on both case types, so both must honour it."""
        from rules.engine import (
            DeathInServiceCase,
            determine_family_pension_death_in_service,
        )

        pack = _pack()
        def det(eol_days: int):
            emol = reckon_average(
                [AnnualPay(y, Decimal("100000")) for y in (2023, 2024, 2025)],
                pack, retirement=date(2026, 2, 18),
            )
            case = DeathInServiceCase(
                case_ref="QS-05-FAM", date_of_birth=date(1966, 2, 19),
                date_of_first_entry=date(2005, 1, 1), date_of_death=date(2021, 6, 1),
                emoluments=emol, bps=17, eol_days=eol_days,
                base_is_three_year_average=True,
            )
            return determine_family_pension_death_in_service(case, pack, COMPUTED_AT)

        self.assertLess(det(365).step("CALC-01").amount, det(0).step("CALC-01").amount)


if __name__ == "__main__":
    unittest.main()
