"""The determination engine. ``CALC-01``, ``FAM-IS-*``, ``ADD-02``. BRAIN §9, BUILD §6.

No model calls, no network, no randomness, no system clock. ``computed_at`` and
``effective_date`` are arguments, so the same inputs and the same pack reproduce the same
output byte for byte, forever (BUILD §6.2 requirement 1). That is what lets an auditor
recompute a 2026 determination in 2031 with nothing but this package and the pack id
recorded on the case.

Two of the steps here are deliberately not numbers. Gratuity on death in service
(``FAM-IS-04`` / ``BLOCKING-06``) and the medical-allowance base (``ADD-02`` /
``BLOCKING-03``) are unresolved, so they are emitted as ``Ambiguity`` objects carrying every
reading. The engine will not collapse them, and ``Determination.amount()`` raises if asked
to. See ``types.py``.
"""

from __future__ import annotations

from rules import scope

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from .emoluments import Emoluments
from .loader import RulePack, UnknownReferenceValue
from .money import exact, money, rupees
from .service import (
    _add_years,
    ServiceLength,
    qualifies_for_monthly_pension,
    reckoned_years,
    span,
    superannuation_date,
)
from .types import Ambiguity, Determination, Reading, Step


#: Engaged, in place of a BLOCKING id, when the reckonable components sum to a figure the
#: prescribed form's printed total does not agree with. Not an open rule item -- a defect in
#: this case's papers -- but it makes the determination provisional by the same mechanism,
#: which is where BRAIN §14.1 wants that fact: on the face of the figure, not in a footnote.
EMOL_RECONCILE = "EMOL-RECONCILE"


@dataclass(frozen=True)
class DeathInServiceCase:
    """Inputs for a family-pension determination on a death in service.

    Inputs only. BRAIN §6.1 invariant 2: no derived amounts here -- no gross pension, no
    family pension, no gratuity. Those are the engine's job, and a caller that could supply
    them could also supply a wrong one.
    """

    case_ref: str
    date_of_birth: date
    date_of_first_entry: date
    date_of_death: date
    emoluments: Emoluments
    bps: int
    #: Where the department states its own figure, it is recorded for comparison but never used.
    stated_qualifying_service: str | None = None
    notional_superannuation: date | None = None
    eol_days: int = 0
    #: Whether ``emoluments`` was built from the three-year average the December 2024
    #: amendment requires, rather than from a single last-drawn pay record. Defaults to
    #: False so a caller that has not thought about it gets a refusal, not a wrong pension.
    base_is_three_year_average: bool = False
    extra_caveats: tuple[str, ...] = field(default_factory=tuple)



#: What every pre-amendment pack said about how long the spouse draws. Kept verbatim so the
#: golden determination (death 2021, pack PB-2026.02) stays byte-identical.
SPOUSE_FOR_LIFE_CAVEAT = (
    "Family pension is payable to the widow/widower for life, subject to the biannual "
    "life certificate (Form C) and, where applicable, the non-marriage certificate "
    "(Form C-1)."
)


def add_years(on: date, years: int) -> date:
    """The same calendar date ``years`` later; 29 February falls back to 28 February."""
    try:
        return on.replace(year=on.year + years)
    except ValueError:
        return on.replace(year=on.year + years, day=28)


def spouse_term(pack: RulePack, commencement: date) -> tuple[Step | None, str]:
    """How long the spouse draws the family pension, on the pack in force.

    FD.SR-III-4-244/2023(B) of 2 December 2024 substituted rule 4.10(1): the spouse's family
    pension runs for ten years or until re-marriage, whichever is earlier; an issueless spouse
    draws it for life or until re-marriage; more than one widow share equally. A pack that
    carries ``family_pension_duration`` is one written on or after that notification, and the
    term is stated as a dated step. A pack without it is pre-amendment and the determination
    says what those packs always said: for life. Nothing is defaulted between the two --
    the pack selected by the date of the event decides, which is the same footing the base
    and the commutation ceiling stand on (BLOCKING-21).

    Returns the step (or ``None`` on a pre-amendment pack) and the caveat sentence to carry.
    """
    try:
        years = int(str(pack.ref("family_pension_duration", "spouse_years")))
    except UnknownReferenceValue:
        return None, SPOUSE_FOR_LIFE_CAVEAT
    try:
        remarriage = bool(pack.ref("family_pension_duration", "spouse_ends_on_remarriage"))
    except UnknownReferenceValue:
        remarriage = False
    try:
        issueless_for_life = bool(pack.ref("family_pension_duration",
                                           "issueless_spouse_for_life"))
    except UnknownReferenceValue:
        issueless_for_life = False
    ends = add_years(commencement, years)
    shown = f"{commencement.isoformat()} + {years} years = {ends.isoformat()}"
    if remarriage:
        shown += ", or the date of re-marriage if earlier"
    notes = []
    if issueless_for_life:
        notes.append(
            "Where the deceased left no issue, the spouse draws for life or until re-marriage "
            "(FAM-DUR-02); the officer reads whether there is issue from the NADRA FRC."
        )
    notes.append(
        "Where the deceased left more than one widow, the pension is divided equally among "
        "them (FAM-DUR-03)."
    )
    step = Step(
        rule_id="FAM-DUR-01",
        description="Family pension to the spouse runs until",
        computation_shown=shown,
        amount=None,
        unit="date",
        note=" ".join(notes),
    )
    caveat = (
        f"Family pension is payable to the widow/widower for {years} years from "
        f"{commencement.isoformat()}"
        + (" or until re-marriage, whichever is earlier" if remarriage else "")
        + " (rule 4.10(1) as substituted by FD.SR-III-4-244/2023(B), 2 December 2024)"
        + ("; an issueless spouse draws for life or until re-marriage" if issueless_for_life
           else "")
        + ". Subject to the biannual life certificate (Form C) and, where applicable, the "
        "non-marriage certificate (Form C-1)."
    )
    return step, caveat


class ImpossibleDates(ValueError):
    """The dates a Form D-I states cannot all be true: a hard stop (business decision H3,
    7 Oct 2026). Nothing is computed on them; the contradiction is named for the department."""


#: The youngest age at which a person can have entered Government service; an entry before it
#: is a misread date, not a fact about the servant.
MIN_ENTRY_AGE_YEARS = 15


def death_in_service_date_defects(date_of_birth: date | None, date_of_first_entry: date | None,
                                  date_of_death: date | None, pack: RulePack) -> list[str]:
    """The ways a Form D-I's three dates contradict each other, in plain words; empty when
    they can all be true. Death before birth, entry after the death, entry before the birth
    (or before the servant was {MIN_ENTRY_AGE_YEARS}), and a death-in-service after the
    notional superannuation date -- by then the servant was no longer in service -- are each
    a hard stop (H3). A missing date is not a defect here: the readers report that separately.
    """
    out: list[str] = []
    if date_of_birth and date_of_death and date_of_death <= date_of_birth:
        out.append(f"the date of death ({date_of_death.isoformat()}) is not after the date of birth ({date_of_birth.isoformat()})")
    if date_of_first_entry and date_of_death and date_of_first_entry >= date_of_death:
        out.append(f"the date of first entry ({date_of_first_entry.isoformat()}) is not before the date of death ({date_of_death.isoformat()})")
    if date_of_birth and date_of_first_entry:
        if date_of_first_entry <= date_of_birth:
            out.append(f"the date of first entry ({date_of_first_entry.isoformat()}) is not after the date of birth ({date_of_birth.isoformat()})")
        elif date_of_first_entry < _add_years(date_of_birth, MIN_ENTRY_AGE_YEARS):
            out.append(f"the servant would have entered service before the age of {MIN_ENTRY_AGE_YEARS} "
                       f"(born {date_of_birth.isoformat()}, entered {date_of_first_entry.isoformat()})")
    if date_of_birth and date_of_death:
        try:
            notional = superannuation_date(date_of_birth, pack)
        except Exception:                                    # noqa: BLE001 -- a pack without the age says nothing here
            notional = None
        if notional is not None and date_of_death > notional:
            out.append(f"the death ({date_of_death.isoformat()}) falls after the notional superannuation date "
                       f"({notional.isoformat()}): a servant retired by then did not die in service")
    return out


def determine_family_pension_death_in_service(
    case: DeathInServiceCase,
    pack: RulePack,
    computed_at: datetime,
) -> Determination:
    """Compute the family-pension determination for a death in service.

    Follows ``FAM-IS-01``: the deceased's pay continues to the family until the notional
    superannuation date, and the family pension commences the day after. Qualifying service
    therefore runs to that notional date, not to the date of death -- which on the golden
    case is the difference between ~28 years and the 30-year cap.

    Refuses outright (``ImpossibleDates``) where the form's dates contradict each other
    (business decision H3, 7 Oct 2026): nothing is computed on a date that cannot be true.
    """
    defects = death_in_service_date_defects(case.date_of_birth, case.date_of_first_entry, case.date_of_death, pack)
    if defects:
        raise ImpossibleDates("the dates on Form D-I cannot all be true: " + "; ".join(defects)
                              + ". Nothing was computed; the department corrects the form (H3).")
    steps: list[Step] = []
    ambiguities: list[Ambiguity] = []
    engaged: list[str] = []

    def engage(*rule_ids: str) -> None:
        for item in pack.engages(*rule_ids):
            if item not in engaged:
                engaged.append(item)

    # -- 0. is this engine entitled to compute on this pack at all? ------------------------
    # The December 2024 amendment substituted rule 4.4(4): the base became the average basic
    # pay INCLUDING PERSONAL PAY over the last three years, taken from 1 July of each. This
    # engine sums the components of ONE pay record. Given three years of rising pay those
    # are different numbers, and the single record is always the larger -- so computing
    # anyway would overstate a pension for life, on every case, silently.
    #
    # Refusing is the same discipline as EMOL-BASE's reconciliation and the ambiguity
    # collapse: where the engine cannot compute the figure the rules require, it says so.
    try:
        base_method = pack.ref("pension_base", "method")
    except Exception:                                    # noqa: BLE001
        base_method = "last_drawn"
    base_is_not_the_required_average = (
        base_method == "average_last_3_years" and not case.base_is_three_year_average)
    # The refusal stands only while this release publishes a figure. It does not
    # (rules.scope.CALCULATIONS_IN_SCOPE is False, business decision of 7 Oct 2026, and
    # scrub_report removes every computed amount from the report, the API and the screens),
    # so an overstated base cannot reach anybody -- and refusing instead cost the officer the
    # checks that DO reach them: the dates, the rule pack, the BLOCKING items, the inputs read.
    #
    # Every self-pension bundle hit this, 21 runs out of 21 on 20 Oct 2026, because the three
    # 1 July figures are keyed at intake (SOP 5.8) and were not. The guard returns the moment
    # calculations come back into scope, which is what the flag is for.
    if base_is_not_the_required_average and scope.CALCULATIONS_IN_SCOPE:
        raise ValueError(
            f"rule pack {pack.id} requires the pension base to be the average basic pay "
            f"including personal pay over the last three years, reckoned from 1 July of "
            f"each (FD notification of 2 December 2024, substituting rule 4.4(4)). This "
            f"case supplies a single pay record, and a last-drawn figure is not that "
            f"average -- on a rising pay scale it is larger. Supply the basic and personal "
            f"pay in force on 1 July in each of the three years before retirement, or route "
            f"the case to manual determination."
        )
    if base_is_not_the_required_average:
        engaged.append("BLOCKING-23")

    # -- 1. reckonable emoluments ----------------------------------------------------------
    emol = case.emoluments
    if emol.unknown:
        raise ValueError(
            "refusing to determine on emoluments that cannot be summed: "
            f"{emol.finding()} (BRAIN §8.4 -- an unclassified or disputed line is a base "
            "nobody can state, and a determination on top of one is a wrong pension)"
        )
    engage("EMOL-BASE")
    # A base that SUMS but disagrees with the total the form prints is not refused. It is
    # computed on the pay records -- §8.3 puts payroll and the AG's own pay certificate above
    # a total the department typed onto the sanction form -- and the determination says so on
    # its face: provisional, engaging EMOL-RECONCILE, with the difference stated in the step.
    # The flag battery raises the same discrepancy HIGH, which is what sends the form back.
    # Refusing produced no figure at all on the OSD-post case, over a Rs. 750
    # qualification-pay line the form had left out of its own total.
    mismatched = emol.printed_total is not None and not emol.reconciled
    if mismatched and EMOL_RECONCILE not in engaged:
        engaged.append(EMOL_RECONCILE)
    steps.append(
        Step(
            rule_id="EMOL-BASE",
            description="Reckonable emoluments (last drawn)",
            computation_shown=emol.computation_shown,
            amount=emol.reckonable_total,
            # The note says which of the two checks actually ran. `needs_human` above lets a
            # base through when NO printed total was extracted -- there was nothing to
            # disagree with -- and `reckon_average` never carries one at all, so a flat claim
            # of "reconciled" was false on every determination the current pack can produce.
            # BRAIN §8.4 calls this the highest-value arithmetic check in the system; an audit
            # record that asserts it happened when it did not is worse than one that admits
            # it was skipped, because only the second sends anyone to look.
            note=(
                ("Reconciled against the form's printed total. "
                 if emol.reconciled else
                 (f"NOT reconciled: {emol.finding()} Computed on the pay records, which "
                  f"BRAIN §8.3 puts above the sanction form on pay; the form's total must be "
                  f"corrected before a PPO issues. ")
                 if mismatched else
                 "NOT reconciled: no printed total was extracted, so the component sum "
                 "could not be independently checked (BRAIN §8.4). ")
                + f"Excluded (non-reckonable) allowances: {exact(emol.excluded_total)}."
            ),
        )
    )

    # -- 2. qualifying service -------------------------------------------------------------
    notional = case.notional_superannuation or superannuation_date(case.date_of_birth, pack)
    convention = pack.ref("qualifying_service", "day_counting")
    length, eol_step = _service_net_of_eol(
        case.eol_days, case.date_of_first_entry, notional, convention
    )
    rounded, capped, qs_shown = reckoned_years(length, pack)
    engage("QS-16")
    if eol_step is not None:
        engage("QS-05")
        steps.append(eol_step)
    steps.append(
        Step(
            rule_id="QS-01",
            description=(
                f"Qualifying service, {case.date_of_first_entry.isoformat()} to "
                f"{notional.isoformat()} (notional superannuation, FAM-IS-01)"
            ),
            computation_shown=qs_shown,
            amount=None,
            unit="years",
            note=(
                f"{length.iso}, {convention} day-counting (QS-16). "
                + (
                    f"Department states {case.stated_qualifying_service}."
                    if case.stated_qualifying_service
                    else ""
                )
            ).strip(),
        )
    )
    steps.append(
        Step(
            rule_id="QS-08",
            description="Qualifying service reckoned for pension",
            computation_shown=f"min({rounded}, {pack.ref('qualifying_service', 'max_years_reckoned')}) = {capped}",
            amount=None,
            unit="years",
            note=None if capped == rounded else f"{rounded - capped} year(s) earned but not reckonable.",
        )
    )

    # -- 3. gross pension, CALC-01 ---------------------------------------------------------
    num = pack.amount("gross_pension", "numerator")
    den = pack.amount("gross_pension", "denominator")
    gross = emol.reckonable_total * capped * num / den
    steps.append(
        Step(
            rule_id="CALC-01",
            description="Gross pension",
            computation_shown=(
                f"{exact(emol.reckonable_total)} x {capped} x {exact(num)} / {exact(den)} "
                f"= {exact(gross)}"
            ),
            amount=gross,
        )
    )

    # -- 4. family pension, FAM-IS-03 ------------------------------------------------------
    fp_num = pack.amount("family_pension_death_in_service", "rate_numerator")
    fp_den = pack.amount("family_pension_death_in_service", "rate_denominator")
    family_pension = gross * fp_num / fp_den
    steps.append(
        Step(
            rule_id="FAM-IS-03",
            description="Family pension",
            computation_shown=(
                f"{exact(gross)} x {exact(fp_num)} / {exact(fp_den)} = {exact(family_pension)}"
            ),
            amount=family_pension,
        )
    )

    # -- 5. gratuity, FAM-IS-04 -- UNRESOLVED, two readings --------------------------------
    ambiguities.append(_gratuity_ambiguity(gross, case, pack))
    engage("FAM-IS-04")

    # -- 6. medical allowance, ADD-02 -- UNRESOLVED base -----------------------------------
    ambiguities.append(_medical_allowance_ambiguity(gross, family_pension, case, pack))
    engage("ADD-02")

    # -- 7. commencement, FAM-IS-05 --------------------------------------------------------
    commencement = notional + timedelta(days=1)
    steps.append(
        Step(
            rule_id="FAM-IS-05",
            description="Family pension commences",
            computation_shown=f"{notional.isoformat()} + 1 day = {commencement.isoformat()}",
            amount=None,
            unit="date",
            note="Pay continued to the family up to the notional superannuation date (FAM-IS-01).",
        )
    )

    # -- 8. duration, FAM-DUR-01/02/03 -- only on a pack that carries the December 2024 term
    duration_step, duration_caveat = spouse_term(pack, commencement)
    if duration_step is not None:
        steps.append(duration_step)
        engage("FAM-DUR-01", "FAM-DUR-02", "FAM-DUR-03")

    caveats = [
        "AI extracted the inputs; this determination was computed by the rules engine "
        f"({pack.id}) with no model in the causal chain of any figure.",
        "Pension increases (ADD-01) are not applied here - the AG applies the notifications "
        "in force at the date the PPO issues.",
        "GPF, Benevolent Fund and Group Insurance are separate streams and are not part of "
        "this determination (BRAIN §9.11).",
        duration_caveat,
        *case.extra_caveats,
    ]

    return Determination(
        case_ref=case.case_ref,
        rule_pack_id=pack.id,
        effective_date=notional,
        computed_at=computed_at,
        steps=tuple(steps),
        ambiguities=tuple(ambiguities),
        unverified_engaged=tuple(engaged),
        caveats=tuple(caveats),
        inputs={
            "date_of_birth": case.date_of_birth.isoformat(),
            "date_of_first_entry": case.date_of_first_entry.isoformat(),
            "date_of_death": case.date_of_death.isoformat(),
            "notional_superannuation": notional.isoformat(),
            # rupees(), not int(). FMT-01 rounds half up everywhere else, and under the
            # December 2024 amendment the base is a three-year mean and so routinely
            # fractional -- int() truncated it, and an auditor recomputing from `inputs`
            # got a different answer from the determination beside it, which is precisely
            # what this block exists to prevent.
            "reckonable_emoluments": rupees(emol.reckonable_total),
            "excluded_allowances": rupees(emol.excluded_total),
            "bps": case.bps,
            "eol_days": case.eol_days,
        },
    )


def _service_net_of_eol(
    eol_days: int,
    start: date,
    end: date,
    convention: str,
) -> tuple[ServiceLength, Step | None]:
    """Qualifying service with extraordinary leave without pay taken out. ``QS-05``.

    BRAIN §9.1 ``QS-05``: "EOL (extraordinary leave without pay) is excluded unless
    specifically allowed". ``eol_days`` is therefore the number of days to EXCLUDE. Where a
    period of EOL has been specifically allowed to count, it is allowed by an order on the
    file and reaches the engine as nil -- that is a decision on the papers, and not one this
    engine is entitled to make either way.

    The deduction moves the end anchor back by the days availed rather than subtracting from
    a years/months/days triple. Taking 365 days off "32y 2m 10d" has no single answer -- a
    month is 28, 30 or 31 days depending which one you take it from -- while shortening the
    span is exactly what the office does and reproduces identically forever.

    Returns the net span and, where any leave was deducted, the step that shows the working.
    The step is the point of the exercise: the figure was already being recorded in
    ``inputs`` as though it had been applied, which reads as a deduction that was made.
    """
    if eol_days < 0:
        raise ValueError(
            f"extraordinary leave cannot be a negative {eol_days} days; a negative "
            f"deduction would ADD service that was never served"
        )
    gross = span(start, end, convention)
    if eol_days == 0:
        return gross, None
    net_end = end - timedelta(days=eol_days)
    if net_end < start:
        raise ValueError(
            f"{eol_days} days of extraordinary leave is longer than the whole service from "
            f"{start.isoformat()} to {end.isoformat()}. One of the two is misread; the "
            f"leave account in the service book settles it."
        )
    net = span(start, net_end, convention)
    return net, Step(
        rule_id="QS-05",
        description=f"Extraordinary leave without pay excluded ({eol_days} days)",
        computation_shown=(
            f"{gross.human} gross service, less {eol_days} days extraordinary leave "
            f"(end anchor {end.isoformat()} -> {net_end.isoformat()}) = {net.human}"
        ),
        amount=None,
        unit="years",
        note=(
            "QS-05: extraordinary leave without pay does not count towards qualifying "
            "service unless it has been specifically allowed to. Where an order on the file "
            "allows any part of it, the allowed days are not excluded and the case must be "
            "recomputed on the reduced figure."
        ),
    )


def _gratuity_ambiguity(
    gross: Decimal, case: DeathInServiceCase, pack: RulePack
) -> Ambiguity:
    """``FAM-IS-04`` / ``BLOCKING-06``. Two defensible readings, 148.5x apart.

    The literal reading takes the relief-package table at its word: gratuity is 25% of the
    gross pension, a one-time payment of a quarter of one month's pension. The capitalised
    reading treats that 25% as a commutation of the pension the deceased never drew, which
    is arithmetically the commutation formula and is how gratuity is often computed in
    practice.

    The capitalised reading needs an age factor, and the loaded table is incomplete
    (``BLOCKING-05``). Where the factor is missing the reading is omitted rather than
    interpolated -- but then only one reading survives, and an ``Ambiguity`` with one
    reading is not an ambiguity, so the engine raises instead of quietly presenting the
    literal figure as settled.
    """
    g_num = pack.amount("family_pension_death_in_service", "gratuity_rate_numerator")
    g_den = pack.amount("family_pension_death_in_service", "gratuity_rate_denominator")

    literal_amount = gross * g_num / g_den
    literal = Reading(
        label="literal",
        amount=literal_amount,
        computation_shown=(
            f"{exact(gross)} x {exact(g_num)} / {exact(g_den)} = {exact(literal_amount)}"
        ),
        basis=(
            "The relief-package table states, literally, Gratuity = Gross Pension x 25/100. "
            "A one-time payment of 25% of one month's gross pension."
        ),
    )

    age_next_birthday = _age_next_birthday(case.date_of_birth, _service_end(case, pack))
    months = pack.amount("commutation", "months_multiplier")
    factor = pack.age_factor(age_next_birthday)  # raises if the age is not in the table
    capitalised_amount = gross * g_num / g_den * months * factor
    capitalised = Reading(
        label="capitalised",
        amount=capitalised_amount,
        computation_shown=(
            f"{exact(gross)} x {exact(g_num)} / {exact(g_den)} x {exact(months)} x "
            f"{exact(factor)} (age next birthday {age_next_birthday}) = "
            f"{exact(capitalised_amount)}"
        ),
        basis=(
            "Treats the 25% as a commutation of the pension the deceased never drew, "
            "applying the commutation formula COMM-03. Arithmetically identical to a 25% "
            "commutation, and the basis used in the AG office's own sample determination."
        ),
    )

    return Ambiguity(
        rule_id="FAM-IS-04",
        blocking_id="BLOCKING-06",
        question=(
            "Is gratuity on death in service the literal 25% of gross pension, or the "
            "capitalised value of that 25%?"
        ),
        readings=(literal, capitalised),
        resolve_with=(
            "FD-SR-II-4-108/2010(D) dated 15-07-2010, together with AG Punjab's own "
            "determination practice. No PPO may issue on a gratuity figure while this is open."
        ),
    )


def _medical_allowance_ambiguity(
    gross: Decimal, family_pension: Decimal, case: DeathInServiceCase, pack: RulePack
) -> Ambiguity:
    """``ADD-02`` / ``BLOCKING-03``. The rate is settled; the base is not.

    20% for BPS 16 and above, 25% below -- that much is long-standing. Whether it applies to
    the gross pension or to the family pension is unresolved, and on the golden case that is
    Rs. 6,721 a month, for life.
    """
    rate = pack.amount(
        "medical_allowance",
        "bps_16_and_above" if case.bps >= 16 else "bps_1_to_15",
    )
    den = pack.amount("medical_allowance", "denominator")
    band = "BPS 16+" if case.bps >= 16 else "BPS 1-15"

    on_family = family_pension * rate / den
    on_gross = gross * rate / den

    return Ambiguity(
        rule_id="ADD-02",
        blocking_id="BLOCKING-03",
        question=(
            "Is medical allowance computed on the family pension or on the gross pension?"
        ),
        readings=(
            Reading(
                label="on_family_pension",
                amount=on_family,
                computation_shown=(
                    f"{exact(family_pension)} x {exact(rate)} / {exact(den)} "
                    f"= {exact(on_family)}"
                ),
                basis=f"{band} rate applied to the family pension. The basis used in the sample determination.",
            ),
            Reading(
                label="on_gross_pension",
                amount=on_gross,
                computation_shown=(
                    f"{exact(gross)} x {exact(rate)} / {exact(den)} = {exact(on_gross)}"
                ),
                basis=f"{band} rate applied to the gross pension before the 75% family-pension reduction.",
            ),
        ),
        resolve_with="Punjab FD notification, or AG Punjab's established practice.",
    )


def _service_end(case: DeathInServiceCase, pack: RulePack) -> date:
    return case.notional_superannuation or superannuation_date(case.date_of_birth, pack)


def _age_next_birthday(date_of_birth: date, on: date) -> int:
    """Age at the next birthday following ``on``. ``COMM-04``.

    A servant born 19-02-1966 whose service ends 18-02-2026 is 59 on that date and turns 60
    the following day, so the age next birthday is 60. Getting this off by one selects the
    wrong row of the commutation table.
    """
    had_birthday = (on.month, on.day) >= (date_of_birth.month, date_of_birth.day)
    age_now = on.year - date_of_birth.year - (0 if had_birthday else 1)
    return age_now + 1

# ==============================================================================================
# Self pension: superannuation, retiring, invalid and compulsory retirement.
# ==============================================================================================

#: Retirements the amendment's reduction factor applies to. Superannuation at 60 is not one
#: of them -- nobody chose it -- and neither is invalidation or a penalty.
VOLUNTARY_RETIREMENTS = frozenset({"RETIRING_PENSION"})

#: Every pension this engine knows how to compute for the servant themselves. The four
#: prescribed self-pension forms, B-I..B-IV, and nothing else.
#:
#: Checked rather than assumed because ``pension_kind`` reaches the engine as a string and
#: the reduction above is applied by EQUALITY against one member of it. Any other value --
#: a typo one letter out, a case type this engine has not been taught, or a family-pension
#: type passed in by a caller that supplied annual pay on the wrong bundle -- meant "no
#: reduction" and paid an unreduced pension. That is the same failure the commutation step
#: refuses to make one function later, where a missing age factor raises because "a missing
#: factor is not a zero factor" (BLOCKING-19): an absent rule is not a nil rule.
SELF_PENSION_KINDS = frozenset({
    "SUPERANNUATION_PENSION",            # B-I
    "RETIRING_PENSION",                  # B-I, voluntary -- the reduction applies
    "INVALID_PENSION",                   # B-IV
    "COMPULSORY_RETIREMENT_PENSION",     # B-IV
})


@dataclass(frozen=True)
class SelfPensionCase:
    """Inputs for a pension to the servant themselves. Inputs only, as with the family case."""

    case_ref: str
    date_of_birth: date
    date_of_first_entry: date
    date_of_retirement: date
    emoluments: Emoluments
    bps: int
    #: SUPERANNUATION_PENSION, RETIRING_PENSION, INVALID_PENSION, COMPULSORY_RETIREMENT_PENSION.
    #: Decides whether the voluntary-retirement reduction applies at all.
    pension_kind: str = "SUPERANNUATION_PENSION"
    stated_qualifying_service: str | None = None
    eol_days: int = 0
    base_is_three_year_average: bool = False
    #: True where the base is the "Average Basic pay" the sanction form itself prints, taken
    #: because the officer has not yet supplied the three 1 July figures. The engine computes
    #: on it and marks the determination PROVISIONAL (BLOCKING-23): the department's printed
    #: average is a claim to be checked against the service book, not the check.
    base_from_printed_average: bool = False
    #: The fraction of gross pension the pensioner elects to commute, as a percentage.
    #: ``None`` means no election is on the file, which is not the same as electing zero:
    #: the ceiling is still shown, but no commuted value is computed. Commutation is the
    #: pensioner's option (COMM-01), so assuming it would invent a payment nobody asked for.
    commutation_percent: Decimal | None = None
    #: An order extending service beyond superannuation, seen on the file. Absent one, a
    #: retirement past the superannuation age is a contradiction rather than an extension:
    #: absence of evidence never excuses a requirement.
    service_extension_evidenced: bool = False
    extra_caveats: tuple[str, ...] = field(default_factory=tuple)


class ServiceTooShort(ValueError):
    """Fewer reckonable years than a monthly pension requires. ``QS-02``.

    Raised rather than computed. The accrual formula returns a perfectly plausible figure
    for eight years of service, and nothing in it says the servant is not entitled to a
    monthly pension at all -- they are due a gratuity instead, on a different rule. A
    number that looks right is the most dangerous output this engine can produce.
    """


class RetirementDateMismatch(ValueError):
    """The date of birth and the date of retirement cannot both be right.

    Raised rather than reconciled. We cannot tell which of the two printed dates is wrong,
    and it matters which: the date of retirement selects the rule pack (BLOCKING-21), so a
    wrong one applies the wrong law to every figure below it. The case routes to a human.
    """


def check_retirement_against_birth(case: "SelfPensionCase", pack: RulePack) -> str | None:
    """Reconcile the two printed dates against the pack's superannuation age. ``QS-10``.

    Deliberately checks the *year*, not the day. The convention is retirement on the
    afternoon before the 60th birthday, but offices also write the last day of the month,
    and refusing over a few days would reject sound cases to catch nothing. A decade is
    what this is for: a case whose form says born 1956 and retired 2026 has served nearly
    ten years past superannuation, and one of those two numbers is a misprint.

    Returns a caveat to carry on the determination, or None. Raises on a contradiction.
    """
    superannuation_age = int(pack.ref("qualifying_service", "superannuation_age"))
    age = _age_at(case.date_of_birth, case.date_of_retirement)
    stated = (f"date of birth {case.date_of_birth.isoformat()} and date of retirement "
              f"{case.date_of_retirement.isoformat()} put this servant at {age}")

    if age > superannuation_age:
        if not case.service_extension_evidenced:
            raise RetirementDateMismatch(
                f"{stated}, past the superannuation age of {superannuation_age}. Service "
                f"beyond superannuation runs only on an order extending it, and no such "
                f"order is on the file. Either that order is missing or one of the two "
                f"dates is misprinted. The date of retirement selects the rule pack, so "
                f"the pension cannot be computed until it is settled."
            )
        return (f"Service ran to {age}, past superannuation at {superannuation_age}, on an "
                f"extension order on the file. An officer should confirm the order covers "
                f"the whole period to {case.date_of_retirement.isoformat()}.")

    # Retiring early is ordinary -- that is what a retiring, invalid or compulsory pension
    # is. It is only a superannuation pension that has to fall at the superannuation age.
    if case.pension_kind == "SUPERANNUATION_PENSION" and age < superannuation_age - 1:
        raise RetirementDateMismatch(
            f"{stated}, short of the superannuation age of {superannuation_age}. A "
            f"superannuation pension is the pension of a servant who reached that age; "
            f"leaving earlier is a retiring, invalid or compulsory pension and is computed "
            f"differently. Either the case is typed wrongly or one of the two dates is "
            f"misprinted."
        )
    return None


def _commutation_steps(
    case: "SelfPensionCase", pack: RulePack, gross: Decimal, engage,
) -> tuple[list[Step], Decimal]:
    """Commutation, and what is left in the monthly pension after it. ``COMM-01``/``COMM-03``.

    The ceiling is always stated, because an officer checking an election needs the limit
    whether or not one was made. The commuted VALUE is computed only where the pensioner
    elected a fraction: commutation is an option, and computing it unasked would put a
    lump sum on a determination nobody claimed.

    The age factor table holds four benchmark ages (BLOCKING-05) and ``pack.age_factor``
    refuses to interpolate. In practice age next birthday 60 is one of the four, so an
    ordinary superannuation case computes; anything else routes to a human, which is the
    right answer rather than a plausible one.
    """
    steps: list[Step] = []
    engage("COMM-01")
    ceiling_percent = pack.amount("commutation", "max_percent_of_gross")
    ceiling = gross * ceiling_percent / 100
    steps.append(Step(
        rule_id="COMM-01",
        description=f"Maximum commutable portion ({exact(ceiling_percent)}% of gross)",
        computation_shown=(f"{exact(gross)} x {exact(ceiling_percent)}% = {exact(ceiling)} "
                           f"per month of pension may be commuted"),
        amount=rupees(ceiling),
    ))

    elected = case.commutation_percent
    if elected is None:
        steps.append(Step(
            rule_id="COMM-01",
            description="Commutation elected",
            computation_shown="no commutation option recorded on the file",
            amount=None,
            note=("Commutation is the pensioner's option. Where no election is on file the "
                  "full gross pension is payable monthly and no lump sum arises."),
        ))
        return steps, gross

    if elected < 0 or elected > ceiling_percent:
        raise UnknownReferenceValue(
            f"a commutation of {exact(elected)}% was recorded, and the maximum permitted is "
            f"{exact(ceiling_percent)}% of gross pension (rule 8.1 as amended on 2 December "
            f"2024). The election cannot stand as recorded."
        )

    commuted_monthly = gross * elected / 100
    engage("COMM-TABLE")
    age_next = _age_next_birthday(case.date_of_birth, case.date_of_retirement)
    months = pack.amount("commutation", "months_multiplier")
    factor = pack.age_factor(age_next)          # raises where the table is silent
    lump_sum = commuted_monthly * months * factor
    steps.append(Step(
        rule_id="COMM-03",
        description=f"Commuted value (lump sum), age next birthday {age_next}",
        computation_shown=(f"{exact(gross)} x {exact(elected)}% = {exact(commuted_monthly)} "
                           f"x {exact(months)} x {exact(factor)} = {exact(lump_sum)}"),
        amount=rupees(lump_sum),
    ))

    net = gross - commuted_monthly
    steps.append(Step(
        rule_id="CALC-02",
        description="Net monthly pension after commutation",
        computation_shown=(f"{exact(gross)} - {exact(commuted_monthly)} = {exact(net)}"),
        amount=rupees(net),
    ))
    return steps, net


def determine_self_pension(
    case: SelfPensionCase,
    pack: RulePack,
    computed_at: datetime,
) -> Determination:
    """Compute a pension payable to the retiring servant.

    Same accrual as the family case -- base x service capped at 30 x 7/300 -- and the same
    refusals: an unreconciled base, or a pack that wants a three-year average it has not
    been given. What is different is the reduction the December 2024 amendment applies when
    a servant retires early, and the absence of the family-pension steps.

    Commutation is NOT computed. The amendment caps it at 25% of gross, but the age factor
    table holds four benchmark ages and the servant's is unlikely to be one of them
    (BLOCKING-05). The ceiling is stated as a caveat and the figure left to a human, rather
    than interpolated -- ``pack.age_factor`` raises for exactly this reason.
    """
    steps: list[Step] = []
    ambiguities: list[Ambiguity] = []
    engaged: list[str] = []

    def engage(*rule_ids: str) -> None:
        for item in pack.engages(*rule_ids):
            if item not in engaged:
                engaged.append(item)

    # Before anything is computed: is this a pension this engine determines at all? The
    # voluntary-retirement reduction below turns on `pension_kind` by equality, so an
    # unrecognised value silently selects the unreduced branch.
    if case.pension_kind not in SELF_PENSION_KINDS:
        raise ValueError(
            f"{case.pension_kind!r} is not a self pension this engine determines. The "
            f"kinds it knows are {', '.join(sorted(SELF_PENSION_KINDS))}. The kind decides "
            f"whether the December 2024 reduction for voluntary retirement applies, and an "
            f"unrecognised value would be treated as involuntary and paid unreduced. Settle "
            f"the case type, or route the case to manual determination."
        )

    try:
        base_method = pack.ref("pension_base", "method")
    except Exception:                                    # noqa: BLE001
        base_method = "last_drawn"
    base_is_not_the_required_average = (
        base_method == "average_last_3_years" and not case.base_is_three_year_average)
    # The refusal stands only while this release publishes a figure. It does not
    # (rules.scope.CALCULATIONS_IN_SCOPE is False, business decision of 7 Oct 2026, and
    # scrub_report removes every computed amount from the report, the API and the screens),
    # so an overstated base cannot reach anybody -- and refusing instead cost the officer the
    # checks that DO reach them: the dates, the rule pack, the BLOCKING items, the inputs read.
    #
    # Every self-pension bundle hit this, 21 runs out of 21 on 20 Oct 2026, because the three
    # 1 July figures are keyed at intake (SOP 5.8) and were not. The guard returns the moment
    # calculations come back into scope, which is what the flag is for.
    if base_is_not_the_required_average and scope.CALCULATIONS_IN_SCOPE:
        raise ValueError(
            f"rule pack {pack.id} requires the base to be the average basic pay including "
            f"personal pay over the last three years (rule 4.4(4) as substituted on "
            f"2 December 2024). A single last-drawn figure is larger on any rising scale."
        )
    if base_is_not_the_required_average:
        engaged.append("BLOCKING-23")
    if case.base_from_printed_average:
        # A fact about THIS case's inputs, not a rule the pack marks unverified. Engaging a
        # BLOCKING id is what makes the determination provisional and puts the case in the
        # exceptional lane (HOLD) until the Auditor keys the three figures (SOP §5.8).
        engaged.append("BLOCKING-23")

    # Before any figure is built on them, the two printed dates have to agree with each
    # other. Qualifying service runs off the date of retirement and the pack is chosen by
    # it, so a decade-wide error here is silently priced into everything below.
    engage("QS-10")
    age_caveat = check_retirement_against_birth(case, pack)

    emol = case.emoluments
    if emol.needs_human:
        raise ValueError(
            f"refusing to determine on unreconciled emoluments: {emol.finding()}"
        )
    engage("EMOL-BASE")
    steps.append(Step(
        rule_id="EMOL-BASE",
        description=("Average basic pay including personal pay, last 3 years"
                     if case.base_is_three_year_average else "Reckonable emoluments (last drawn)"),
        computation_shown=emol.computation_shown,
        amount=emol.reckonable_total,
    ))

    convention = pack.ref("qualifying_service", "day_counting")
    length, eol_step = _service_net_of_eol(
        case.eol_days, case.date_of_first_entry, case.date_of_retirement, convention
    )
    rounded, capped, qs_shown = reckoned_years(length, pack)
    engage("QS-16")
    if eol_step is not None:
        engage("QS-05")
        steps.append(eol_step)
    steps.append(Step(
        rule_id="QS-01",
        description=(f"Qualifying service, {case.date_of_first_entry.isoformat()} to "
                     f"{case.date_of_retirement.isoformat()}"),
        computation_shown=qs_shown,
        amount=None,
        unit="years",
        note=(f"Department states {case.stated_qualifying_service}."
              if case.stated_qualifying_service else None),
    ))
    if capped != rounded:
        steps.append(Step(
            rule_id="QS-08",
            description="Qualifying service reckoned for pension",
            computation_shown=f"{rounded} years served, capped at {capped}",
            amount=None, unit="years",
        ))

    # QS-02. Ten reckonable years buy a monthly pension; below that the entitlement is a
    # gratuity on a different rule, and the accrual formula below would answer anyway.
    engage("QS-02")
    if not qualifies_for_monthly_pension(capped, pack):
        floor = int(pack.ref("qualifying_service", "min_years_for_monthly_pension"))
        gratuity_floor = int(pack.ref("qualifying_service", "min_years_for_service_gratuity"))
        raise ServiceTooShort(
            f"{capped} reckonable years is short of the {floor} a monthly pension requires "
            f"(QS-02). This servant is due a service gratuity rather than a pension"
            + (f" ({gratuity_floor} years or more)" if capped >= gratuity_floor else
               f", and below {gratuity_floor} years neither arises")
            + ". The accrual formula would return a figure for this service regardless, "
              "which is why it is not run."
        )

    engage("CALC-01")
    numerator = int(pack.ref("gross_pension", "numerator"))
    denominator = int(pack.ref("gross_pension", "denominator"))
    gross = emol.reckonable_total * capped * numerator / denominator
    steps.append(Step(
        rule_id="CALC-01",
        description="Gross pension",
        computation_shown=(f"{exact(emol.reckonable_total)} x {capped} x "
                           f"{numerator} / {denominator} = {exact(gross)}"),
        amount=rupees(gross),
    ))

    payable = gross
    if case.pension_kind in VOLUNTARY_RETIREMENTS:
        age = _age_at(case.date_of_birth, case.date_of_retirement)
        engage("VOL-RED-01")
        # An age the table does not cover raises. A servant retiring voluntarily at 54 is
        # outside what the amendment states, and treating an absent factor as 0% would pay
        # a full pension where a reduced one is due (BLOCKING-19).
        table = pack.ref("voluntary_retirement_reduction_percent_by_age")
        key = str(age)
        if key not in table:
            raise UnknownReferenceValue(
                f"the December 2024 amendment states a voluntary-retirement reduction for "
                f"ages {sorted(table)} and this servant retires at {age}. A missing factor "
                f"is not a zero factor. Refer the case rather than pay an unreduced pension."
            )
        percent = money(table[key])
        reduction = gross * percent / 100
        payable = gross - reduction
        steps.append(Step(
            rule_id="VOL-RED-01",
            description=f"Reduction for voluntary retirement at {age}",
            computation_shown=(f"{exact(gross)} x {exact(percent)}% = {exact(reduction)}; "
                               f"{exact(gross)} - {exact(reduction)} = {exact(payable)}"),
            amount=rupees(payable),
        ))

    # FAM-IS-05's sibling for the servant's own pension: it begins the day after service ends.
    commencement = case.date_of_retirement + timedelta(days=1)
    steps.append(Step(
        rule_id="CALC-01",
        description="Pension commences",
        computation_shown=(f"{case.date_of_retirement.isoformat()} + 1 day = "
                           f"{commencement.isoformat()}"),
        amount=None,
        note="Service ends on the afternoon of the last day; the pension runs from the next.",
    ))

    commutation, payable = _commutation_steps(case, pack, payable, engage)
    steps.extend(commutation)

    caveats = list(case.extra_caveats)
    if base_is_not_the_required_average and not case.base_from_printed_average:
        caveats.append(
            "PROVISIONAL (BLOCKING-23): the three basic-pay figures as at 1 July of the last "
            "three years (rule 4.4(4) as substituted) have not been supplied at intake, so the "
            "base is not the average those rules require. This release publishes no computed "
            "figure, and the checks below ran on what the bundle states. No PPO may issue "
            "until the three figures are keyed and the case is recomputed."
        )
    if case.base_from_printed_average:
        caveats.append(
            "PROVISIONAL (BLOCKING-23): the pension base is the 'Average Basic pay' figure "
            "printed on the sanction form, because the three basic-pay figures as at 1 July of "
            "the last three years (rule 4.4(4) as substituted) have not yet been supplied at "
            "intake. The department's printed average is checked against the service book, "
            "not taken as the check. Supply the three figures and the case recomputes final; "
            "no PPO may issue on this figure."
        )
    if age_caveat:
        caveats.append(age_caveat)
    if case.commutation_percent is None:
        caveats.append(
            f"No commutation option is recorded on the file, so the whole gross pension is "
            f"shown as payable monthly. Up to "
            f"{pack.ref('commutation', 'max_percent_of_gross')}% may be commuted (rule 8.1 as "
            f"amended on 2 December 2024); if the pensioner has elected to, the election must "
            f"be entered for the lump sum and the reduced monthly pension to be computed."
        )
    caveats.append(
        "Medical allowance, the minimum-pension floor and annual increases are NOT included "
        "in the figure above. Their rates are notified separately and are not loaded "
        "(BLOCKING-02, BLOCKING-03, BLOCKING-20), so the monthly sum finally payable is "
        "higher than this and must be settled by an officer."
    )
    if case.base_is_three_year_average:
        caveats.append(
            "The base is the three-year average required by rule 4.4(4) as substituted on "
            "2 December 2024, built from figures supplied at intake rather than read from "
            "the papers. An officer should confirm each against the service book."
        )

    return Determination(
        case_ref=case.case_ref,
        rule_pack_id=pack.id,
        effective_date=case.date_of_retirement,
        computed_at=computed_at,
        steps=tuple(steps),
        ambiguities=tuple(ambiguities),
        unverified_engaged=tuple(engaged),
        caveats=tuple(caveats),
        inputs={
            # ISO strings, not date objects: ``inputs`` is written straight to
            # case_report.json, and json.dumps has no encoder for a date. The family
            # path above has always done this; this one did not, and a case that
            # actually carried pay figures failed at the write with nothing recorded.
            "date_of_birth": case.date_of_birth.isoformat(),
            "date_of_first_entry": case.date_of_first_entry.isoformat(),
            "date_of_retirement": case.date_of_retirement.isoformat(),
            "pension_kind": case.pension_kind,
            # rupees(), not int(): see the family path above. FMT-01 half-up, so the
            # figure recorded as the input is the figure the determination used.
            "pension_base": rupees(emol.reckonable_total),
            "bps": case.bps,
            "eol_days": case.eol_days,
        },
    )


def _age_at(date_of_birth: date, on: date) -> int:
    """Age in completed years. The reduction table is indexed by age at retirement."""
    return on.year - date_of_birth.year - ((on.month, on.day) < (date_of_birth.month, date_of_birth.day))

