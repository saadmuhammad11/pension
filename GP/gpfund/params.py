"""Effective-dated parameter tables. Build specification §11.1, §4.5, §13.2, §15.

Every number in this file is a parameter with an authority behind it, not a constant someone
chose. §15 makes the point about versioning: the rule set has four parts, and one of them is
"the parameter tables (advance limits, confidence thresholds, delegation bands)". §11.2 adds
that "the percentage and months parameters are effective-dated configuration with their
source recorded".

So each entry carries its source. Where the office's practice and the Rules disagree, BOTH
are kept and the disagreement is reported -- see :data:`OFFICE_CAP_PCT` and GPF-O15. The
module never resolves that by choosing; §11.2 has it apply the Rules and flag the difference.
"""

from __future__ import annotations

from dataclasses import dataclass

# -- advance limits, §11.1 ------------------------------------------------------------------


@dataclass(frozen=True)
class AdvanceLimit:
    """One clause of the Rules and the ceiling it sets.

    ``pct`` is the share of the balance. ``months`` is the months-of-pay cap where the clause
    sets one. ``combine`` says which of the two governs -- and it is not always the lesser:
    Rule 1.15(d) says "whichever is more", and that clause carries an unexplained amendment
    mark, which is part of open item GPF-O15.
    """

    label: str
    pct: int
    src: str
    months: int | None = None
    combine: str | None = None          # "min" | "max" | None
    min_age: int | None = None
    relaxable: str | None = None

    def ceiling(self, balance: int, basic_pay: int | None) -> tuple[int, int, int | None]:
        """``(limit, by_percentage, by_months)`` for this balance and pay.

        Floors rather than rounds: a ceiling is a figure the sanction must not exceed, and
        rounding one up would admit an advance the clause does not.
        """
        by_pct = balance * self.pct // 100
        if self.months and basic_pay:
            by_pay = basic_pay * self.months
            limit = max(by_pct, by_pay) if self.combine == "max" else min(by_pct, by_pay)
            return limit, by_pct, by_pay
        return by_pct, by_pct, None


#: Keyed by the normalised clause the sanction quotes. The reading stage normalises
#: "Rule 1.14(1)(a)(iv)(d)(i)" to "1.14(1)(d)(i)" (§4.2, ``limit_clause``); an unmatched
#: clause is a verification task, never a guess at which ceiling applies (§11.2).
ADVANCE_LIMITS: dict[str, AdvanceLimit] = {
    "1.14(1)(c)(i)": AdvanceLimit(
        label="Temporary advance, general purposes (illness, passage, ceremonies, Haj, other)",
        pct=50, months=3, combine="min", src="Rule 1.14(1)(c)(i)",
        relaxable="only for special reasons recorded in writing, never for purpose (a)(vi)"),
    "1.14(1)(d)(i)": AdvanceLimit(
        label="Temporary advance for a plot or house",
        pct=80, months=24, combine="min", src="Rule 1.14(1)(d)(i)"),
    "1.14(1)(e)(i)-car": AdvanceLimit(
        label="Temporary advance for a car",
        pct=50, months=12, combine="min", src="Rule 1.14(1)(e)(i)"),
    "1.14(1)(e)(i)-motorcycle": AdvanceLimit(
        label="Temporary advance for a scooter or motorcycle",
        pct=50, months=6, combine="min", src="Rule 1.14(1)(e)(i)"),
    "1.14(1)(e)(i)-bicycle": AdvanceLimit(
        label="Temporary advance for a bicycle",
        pct=50, months=4, combine="min", src="Rule 1.14(1)(e)(i)"),
    "1.15(a)": AdvanceLimit(
        label="Non-refundable advance after 50, building or altering a house",
        pct=80, months=24, combine="min", src="Rule 1.15(a) with 1.14(1)(d)(i)", min_age=50),
    "1.15(b)": AdvanceLimit(
        label="Non-refundable advance after 50, buying a house",
        pct=80, src="Rule 1.15(b)(1)", min_age=50),
    "1.15(c)": AdvanceLimit(
        label="Non-refundable advance after 50, agricultural land from Government",
        pct=80, src="Rule 1.15(c)(1)", min_age=50),
    "1.15(d)": AdvanceLimit(
        label="Non-refundable advance after 50, illness, passage, education, ceremonies",
        pct=80, months=12, combine="max", src="Rule 1.15(d)(1)", min_age=50),
    "1.16": AdvanceLimit(
        label="Non-refundable advance at 50 or over, no reason needed",
        pct=100, src="Rule 1.16 (substituted 12-12-2002)", min_age=50),
    "1.18": AdvanceLimit(
        label="Non-refundable advance at 45 or over, building a house",
        pct=80, months=24, combine="min", src="Rule 1.18 with 1.15(a)", min_age=45),
}

#: The office's stated practice of 15-09-2026 (R9): a sanctioned advance at most 80% of the
#: SAP balance. NOT applied in place of the Rules. §11.1 sets out why: it agrees with the
#: Rules for house and land advances, is LOOSER than the Rules for general temporary and
#: conveyance advances (which cap at half the balance), and is STRICTER than Rule 1.16 (100%
#: at age 50). The compendium carries no notification raising the temporary ceiling to 80%.
#: Every limit test shows both figures and flags the difference -- open item GPF-O15.
OFFICE_CAP_PCT = 80

#: Rupees of slack allowed when matching a claim to a posting in the re-calculation report.
#: One rupee, because the figures are whole rupees and the match must be an identity, not an
#: approximation: §12 uses it to decide that a posting IS the claim.
CLAIM_TOLERANCE = 1

#: Months that must pass after a refundable advance reaches zero before another is settled.
#: R12 as the office states it; Rule 1.14(1)(c)(ii) adds a twelve-month gap unless the earlier
#: advance was within two-thirds of the admissible amount. Carried as configuration and
#: reported as an advisory until the office decides -- open item GPF-O16 (§11.4).
SECOND_REFUNDABLE_GAP_MONTHS = 0

#: Gap before a second NON-refundable advance. Default 0 per Rule 1.17 (2003), switchable to
#: 12 per the older proviso (§11.4). Non-refundable advances are not blocked by R12.
SECOND_NONREFUNDABLE_GAP_MONTHS = 0


# -- confidence thresholds, §4.5 ------------------------------------------------------------
#
# Unchanged from revision 1 of the specification. A field below its threshold goes to a
# person: §0 rule 3 and §14 rule 10 -- "the model never guesses an account number, CNIC, date
# or amount", and a below-threshold extraction is never accepted silently.

CONFIDENCE_THRESHOLDS: dict[str, float] = {
    "financial": 0.95,      # account numbers, CNIC, amounts, dates
    "identity": 0.85,
    "structural": 0.90,     # signature present, stamp present
    "narrative": 0.70,
    "service_book": 0.98,   # every Service Book field in v1
}

#: Which threshold a field is judged against. Anything unlisted falls to ``narrative``, which
#: is the loosest, so a new financially material field must be added here deliberately rather
#: than inheriting a lenient default by accident.
FIELD_THRESHOLD_CLASS: dict[str, str] = {
    "persNo": "financial", "personalNo": "financial", "accountNo": "financial",
    "oldGpfNo": "financial", "gpfNo": "financial", "cnic": "financial", "number": "financial",
    "amount": "financial", "gpfBalance": "financial", "basicPay": "financial",
    "gpfSubscription": "financial", "loanBalance": "financial", "loanInstalment": "financial",
    "opening": "financial", "closing": "financial", "interest": "financial",
    "date": "financial", "orderNo": "financial", "month": "financial",
    "name": "identity", "father": "identity", "designation": "identity", "whose": "identity",
    "ddoSigned": "structural", "sigKind": "structural", "attested": "structural",
    "bankStamp": "structural", "present": "structural",
}


def threshold_for(field_name: str) -> float:
    """The accept threshold for one extracted field. §4.5."""
    return CONFIDENCE_THRESHOLDS[FIELD_THRESHOLD_CLASS.get(field_name, "narrative")]


# -- delegation bands inside this office, §13.2 ---------------------------------------------
#
# Configuration, and open item GPF-O13: these are the bands the specification sets out, to be
# confirmed by the office. The bands decide who may DISPOSE, never what the rules find.

#: The three desks, weakest first. ``level`` is what the bands compare.
DESKS: tuple[dict[str, object], ...] = (
    {"id": "DA", "label": "Dealing Assistant, GP Fund-I", "grade": "BS-16", "level": 1},
    {"id": "AO", "label": "Accounts Officer, GP Fund-I", "grade": "BS-17/18", "level": 2},
    {"id": "DAG", "label": "Deputy Accountant General (Funds)", "grade": "BS-20", "level": 3},
)

#: Minimum desk level per action. ``waive`` and ``return_case`` are split by severity and by
#: whether it is the second return, which para 3 of the circular reserves to the DAG (Funds).
MIN_LEVEL: dict[str, int] = {
    "uphold": 1,
    "upload_document": 1,
    "refer_upward": 1,
    "settle_in_office": 2,
    "waive_advisory": 2,
    "record_verification": 2,
    "upload_specimen": 2,
    "pass_for_payment": 2,
    "pass_for_part_payment": 2,
    "return_case": 1,
    "hold_pending_verification": 1,
    "waive_hard": 3,
    "second_return": 3,
    "add_signatory": 3,
    "finalise_register": 3,
}

#: Minimum characters of written justification on an override. The circular requires the
#: ground and the authority; the length is this office's floor against a one-word reason.
MIN_JUSTIFICATION = 15


def desk(desk_id: str) -> dict[str, object]:
    for entry in DESKS:
        if entry["id"] == desk_id:
            return dict(entry)
    raise KeyError(f"unknown desk {desk_id!r}; the office has {[d['id'] for d in DESKS]}")


def may(desk_id: str, action: str) -> bool:
    """Whether that desk may take that action. §13.2."""
    if action not in MIN_LEVEL:
        raise KeyError(f"unknown action {action!r}; known actions are {sorted(MIN_LEVEL)}")
    return int(desk(desk_id)["level"]) >= MIN_LEVEL[action]


def who_may(action: str) -> str:
    """The weakest desk that may take the action, for a message an officer can act on."""
    need = MIN_LEVEL[action]
    for entry in DESKS:
        if int(entry["level"]) >= need:
            return str(entry["label"])
    return "no desk in this office"
