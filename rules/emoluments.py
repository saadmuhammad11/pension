"""Reckonable emoluments and the reconciliation against the form. ``EMOL-*``. BRAIN §9.3.

BRAIN §8.4 calls the reconciliation here "the single highest-value arithmetic check in the
system", and the golden case shows why: the servant's reckonable pay is Rs. 192,030 while the
*excluded* allowances total Rs. 161,765 -- 84% of the pensionable amount sitting right beside
it on the same page. Moving one line across that boundary changes a pension for life, so the
engine does two independent things and requires them to agree:

  1. sums the components the classifier marked reckonable, and
  2. compares that sum against the total the form itself prints.

Two sources agreeing is evidence. One source is an assertion. Where they disagree the engine
does not pick a side -- it returns the discrepancy for a flag, because either the extraction
misread a line or the department's own arithmetic is wrong, and those need different letters.

An ``unknown`` component is never summed and never assumed non-reckonable. Silently dropping
an unrecognised allowance understates a pension; silently including it overstates one. It
raises a finding instead (``needs_human``), matching ``extraction/classify.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .loader import RulePack
from .money import Numeric, exact, fmt, money


class EmolumentsError(ValueError):
    """The base could not be established. Never defaulted around."""


@dataclass(frozen=True)
class PayComponent:
    """One line of the pay statement, after classification.

    ``component`` is a canonical name from ``extraction.classify`` (``basic_pay``,
    ``non_reckonable_allowance``, ``unknown``...), not the printed label. ``printed_label``
    is kept because an auditor checking the reckonable/non-reckonable call needs to see the
    words that were actually on the page.
    """

    printed_label: str
    component: str
    amount: Decimal
    page: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))


@dataclass(frozen=True)
class Emoluments:
    """The reckonable total, what was excluded, and whether the form agrees."""

    reckonable_total: Decimal
    excluded_total: Decimal
    reckonable: tuple[PayComponent, ...]
    excluded: tuple[PayComponent, ...]
    unknown: tuple[PayComponent, ...]
    printed_total: Decimal | None
    computation_shown: str

    @property
    def reconciled(self) -> bool:
        """Whether the summed lines match the total printed on the form.

        ``None`` printed total means there was nothing to reconcile against, which is not
        the same as agreement -- hence the explicit ``False``.
        """
        if self.printed_total is None:
            return False
        return money(self.reckonable_total) == money(self.printed_total)

    @property
    def discrepancy(self) -> Decimal | None:
        if self.printed_total is None:
            return None
        return money(self.reckonable_total) - money(self.printed_total)

    @property
    def needs_human(self) -> bool:
        """Any unclassified line, or a failed reconciliation, must reach an officer."""
        return bool(self.unknown) or (self.printed_total is not None and not self.reconciled)

    def finding(self) -> str | None:
        """A one-line statement of what is wrong, or ``None`` if the emoluments are clean."""
        if self.unknown:
            labels = ", ".join(repr(c.printed_label) for c in self.unknown)
            return (
                f"{len(self.unknown)} pay line(s) could not be summed: {labels}. Either the "
                f"label matches no rule (EMOL-08) or the component's reckonability is "
                f"disputed (BLOCKING-18, orderly allowance). An officer must decide."
            )
        if self.printed_total is None:
            return (
                "No printed total was extracted, so the component sum could not be "
                "independently checked (BRAIN §8.4)."
            )
        if not self.reconciled:
            return (
                f"Reckonable components sum to {fmt(self.reckonable_total)} but the form "
                f"prints {fmt(self.printed_total)}, a difference of "
                f"{fmt(abs(self.discrepancy))}."
            )
        return None


def reckon(
    components: list[PayComponent],
    pack: RulePack,
    printed_total: Numeric | None = None,
) -> Emoluments:
    """Sum the reckonable set and reconcile against the form's own total. ``EMOL-01``..``EMOL-08``.

    ``printed_total`` is the figure the prescribed form states (Form D-I "Total Pay"), which
    is an independent witness to the same fact and is what makes this a check rather than a
    restatement.
    """
    reckonable_names = set(pack.ref("reckonable_components"))
    try:
        disputed_names = set(pack.ref("reckonable_disputed"))
    except Exception:                      # a pack predating BLOCKING-18
        disputed_names = set()

    reckonable: list[PayComponent] = []
    excluded: list[PayComponent] = []
    unknown: list[PayComponent] = []

    for c in components:
        # A DISPUTED component is treated exactly like an unclassified one: never summed,
        # never quietly dropped, always routed to a human. Orderly allowance is reckonable
        # under BRAIN §9.3 and sits outside "Total pay" on the prescribed form itself
        # (BLOCKING-18). Summing it overstates a pension for life; excluding it understates
        # one. Neither is a decision this engine is entitled to make.
        if c.component == "unknown" or c.component in disputed_names:
            unknown.append(c)
        elif c.component in reckonable_names:
            reckonable.append(c)
        else:
            excluded.append(c)

    total = sum((c.amount for c in reckonable), Decimal(0))
    excluded_total = sum((c.amount for c in excluded), Decimal(0))

    if reckonable:
        # Use exact() rather than stripping zeros by hand: rstrip("0") on "178440.000000"
        # eats the real trailing zero too and renders 178,440 as 17,844 in the audit record.
        # The total stayed correct, which is exactly what made it hard to see.
        shown = " + ".join(exact(c.amount) for c in reckonable) + f" = {exact(total)}"
    else:
        shown = "no reckonable components extracted"

    return Emoluments(
        reckonable_total=total,
        excluded_total=excluded_total,
        reckonable=tuple(reckonable),
        excluded=tuple(excluded),
        unknown=tuple(unknown),
        printed_total=None if printed_total is None else money(printed_total),
        computation_shown=shown,
    )

@dataclass(frozen=True)
class AnnualPay:
    """Basic pay including personal pay, as it stood on 1 July of one year.

    ``source`` records where the figure came from -- a service-book pay-fixation entry, a
    pay slip, or an officer reading one of those. A base that decides a pension for life
    must say who supplied each of its three numbers.
    """

    year: int
    amount: Decimal
    source: str = "officer entry"

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))


def average_years_for(retirement: date, count: int) -> list[int]:
    """The ``count`` years whose 1 July anchors the average, oldest first. ``EMOL-BASE``.

    Rule 4.4(4) reckons "from first day of July of last 03 years prior to retirement", so
    the anchors are the most recent 1 July falling on or before the retirement date, and
    the two before that. A servant retiring 18-02-2026 averages 1 July 2023, 2024 and 2025;
    one retiring 30-09-2026 has passed 1 July 2026, so theirs are 2024, 2025 and 2026.

    The "on or before" boundary is a reading, not a quotation: the rule does not say what
    happens to someone retiring on 1 July itself. Taking that July as reckonable uses the
    pay in force on the day they left, which is the figure the rest of the case is built
    on. It is stated here rather than left implicit so it can be corrected in one place.
    """
    passed_july = (retirement.month, retirement.day) >= (7, 1)
    last = retirement.year if passed_july else retirement.year - 1
    return list(range(last - count + 1, last + 1))


def reckon_average(
    years: list[AnnualPay],
    pack: RulePack,
    retirement: date | None = None,
) -> Emoluments:
    """The three-year average base the December 2024 amendment requires. ``EMOL-BASE``.

    Rule 4.4(4), as substituted: "The last 03 years average basic pay, including personal
    pay, of the Government servant starting from first day of July of last 03 years prior to
    retirement shall be considered for pension calculation."

    The count is not assumed. A pack that asks for three years and is given two would, on a
    naive mean, produce a HIGHER base than the rule allows -- the missing year is always the
    earliest and therefore the lowest -- so a short list raises instead of averaging.

    Rounding is left to the end: the average is carried unrounded into the gross-pension
    step, and only the monthly pension is rounded (FMT-01). Rounding the base first moves
    every figure downstream.
    """
    wanted = int(pack.ref("pension_base", "years_averaged"))
    if len(years) != wanted:
        raise EmolumentsError(
            f"rule pack {pack.id} averages the base over {wanted} years and {len(years)} "
            f"were supplied. The missing year is the earliest and so the lowest, and a mean "
            f"of the remainder overstates the pension. Supply basic pay including personal "
            f"pay as at 1 July in each of the {wanted} years before retirement."
        )
    if len({y.year for y in years}) != wanted:
        raise EmolumentsError(
            f"the {wanted} pay figures must be for {wanted} different years; "
            f"{sorted(y.year for y in years)} were supplied."
        )

    # WHICH years, not merely how many. The count check above passes three figures for any
    # three distinct years, and the figures reach this function as officer-typed year
    # labels -- so three years of a different servant's career, or the three years before
    # TODAY rather than before this retirement, average silently into a pension for life.
    # A base built on the wrong window is wrong in the same way a two-year mean is wrong,
    # and is refused for the same reason. Checked only where the caller supplies the
    # retirement date: without it there is nothing to check against, and inventing one
    # from the clock is the very failure this guards.
    if retirement is not None:
        expected = average_years_for(retirement, wanted)
        supplied = sorted(y.year for y in years)
        if supplied != expected:
            raise EmolumentsError(
                f"rule 4.4(4) averages the basic pay in force on 1 July of the {wanted} "
                f"years before retirement. This servant retired on "
                f"{retirement.isoformat()}, so the figures required are for "
                f"{', '.join(str(y) for y in expected)}; {', '.join(str(y) for y in supplied)} "
                f"were supplied. Supply the pay as at 1 July in each of the required years, "
                f"or route the case to manual determination."
            )

    ordered = sorted(years, key=lambda y: y.year)
    total = sum((y.amount for y in ordered), Decimal(0))
    average = total / wanted
    shown = (
        " + ".join(f"{exact(y.amount)} (1 Jul {y.year})" for y in ordered)
        + f" = {exact(total)} / {wanted} = {exact(average)}"
    )
    components = tuple(
        PayComponent(printed_label=f"basic pay incl. personal pay, 1 Jul {y.year}",
                     component="basic_pay", amount=y.amount)
        for y in ordered
    )
    return Emoluments(
        reckonable_total=average,
        excluded_total=Decimal(0),
        reckonable=components,
        excluded=(),
        unknown=(),
        printed_total=None,
        computation_shown=shown,
    )

