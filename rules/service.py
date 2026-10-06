"""Qualifying service. ``QS-01``, ``QS-07``, ``QS-08``, ``QS-10``, ``QS-16``. BRAIN §9.1.

Pure date arithmetic on the standard library. No dateutil, no relativedelta: BUILD §6.2
requires this to be recomputable "forever", and a dependency is one more thing that has to
still exist and still behave identically in 2031.

The day-counting convention is the subtle part. ``BLOCKING-16`` leaves inclusive-vs-exclusive
unresolved, and on the golden case the two differ by exactly one day -- the department states
32y 2m 11d, exclusive counting gives 32y 2m 10d. Both round to 32 years under ``QS-07`` and
both cap at 30 under ``QS-08``, so the determination is identical either way. That is *why*
the convention can be fixed by the pack rather than escalated: it is immaterial to the money
today, but a recomputation years from now must reproduce the same intermediate figure, so the
engine states which convention it used instead of leaving it implicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .loader import RulePack


@dataclass(frozen=True)
class ServiceLength:
    """A span of service, before and after the ``QS-07``/``QS-08`` transformations."""

    years: int
    months: int
    days: int
    convention: str

    @property
    def iso(self) -> str:
        """ISO-8601 duration, per BRAIN §6.1 invariant 7."""
        return f"P{self.years}Y{self.months}M{self.days}D"

    @property
    def human(self) -> str:
        return f"{self.years}y {self.months}m {self.days}d"


def span(start: date, end: date, convention: str = "exclusive") -> ServiceLength:
    """Calendar difference between two dates as years/months/days. ``QS-01``, ``QS-16``.

    ``exclusive`` counts the gap between the dates (the entry date is not itself a served
    day); ``inclusive`` counts the entry date too and so yields one more day.
    """
    if end < start:
        raise ValueError(f"service ends {end} before it starts {start}")
    if convention not in ("exclusive", "inclusive"):
        raise ValueError(f"unknown day-counting convention {convention!r}")

    # Whole months first, then the days actually left over. Taking the day difference on its
    # own and borrowing one month to cover a shortfall does not survive February: from
    # 31 January to 1 March the shortfall is 30 days against a 28- or 29-day month, and the
    # remainder stayed negative -- "P32Y1M-1D" in the audit record, against BRAIN §6.1
    # invariant 7. Anchoring on the date `total_months` after `start` and measuring the rest
    # with real date arithmetic cannot go negative, because the anchor never passes `end`.
    total_months = (end.year - start.year) * 12 + (end.month - start.month)
    # Borrow a month only where the anchor actually overshoots `end`. Testing
    # `end.day < start.day` borrowed on a day-number shortfall that `_add_months`'s clamp
    # to a shorter month has already absorbed: 31 August plus one month IS 30 September,
    # so a span ending 30 September owes nothing back, and the borrow reported 32y 0m 30d
    # where 32y 1m 0d was served. Month-end to month-end is the ordinary shape of a
    # retirement, so this was the common case, not the corner one -- and a span one month
    # short can lose a whole qualifying year at the QS-07 six-month boundary.
    if _add_months(start, total_months) > end:
        total_months -= 1
    days = (end - _add_months(start, total_months)).days
    years, months = divmod(total_months, 12)

    if convention == "inclusive":
        days += 1

    return ServiceLength(years=years, months=months, days=days, convention=convention)


def _add_months(d: date, months: int) -> date:
    """``d`` advanced by whole months, clamped to the last day of a shorter month.

    31 January plus one month is 28 or 29 February: there is no 31st to land on, and the
    clamp is what makes the month count and the day remainder add back up to the end date.
    """
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(d.day, _days_in_month(year, month)))


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31


def superannuation_date(date_of_birth: date, pack: RulePack) -> date:
    """The date of superannuation. ``QS-10``.

    Retirement takes effect on the **afternoon of the day preceding** the 60th birthday, so
    a servant born 19-02-1966 superannuates on 18-02-2026 (A/N) -- not on the birthday. The
    off-by-one here shifts the family-pension commencement date and, through the service
    span, potentially a whole qualifying year.
    """
    age = int(pack.ref("qualifying_service", "superannuation_age"))
    sixtieth = _add_years(date_of_birth, age)
    return sixtieth.fromordinal(sixtieth.toordinal() - 1)


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # 29 February in a non-leap target year.
        return d.replace(year=d.year + years, day=28)


def reckoned_years(length: ServiceLength, pack: RulePack) -> tuple[int, int, str]:
    """Apply ``QS-07`` rounding then the ``QS-08`` cap.

    Returns ``(rounded_years, capped_years, computation_shown)``. Both figures are returned
    because the determination has to show the cap doing its work: on the golden case the
    servant earned 32 years and is paid on 30, and an officer reading the determination
    needs to see the two years that were dropped rather than a bare "30".
    """
    round_from = int(pack.ref("qualifying_service", "round_up_from_months"))
    cap = int(pack.ref("qualifying_service", "max_years_reckoned"))

    rounded = length.years + (1 if length.months >= round_from else 0)
    capped = min(rounded, cap)

    if length.months >= round_from:
        shown = f"{length.human} -> {rounded} years (QS-07: {length.months}m >= {round_from}m rounds up)"
    else:
        shown = f"{length.human} -> {rounded} years (QS-07: {length.months}m < {round_from}m ignored)"
    if capped < rounded:
        shown += f", capped at {cap} (QS-08)"
    return rounded, capped, shown


def qualifies_for_monthly_pension(years: int, pack: RulePack) -> bool:
    """``QS-02``: a monthly pension needs at least 10 years."""
    return years >= int(pack.ref("qualifying_service", "min_years_for_monthly_pension"))
