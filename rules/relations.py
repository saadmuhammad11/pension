"""The eligible family-pension relations, and the proof each needs. Business decision H6, 7 Oct 2026.

DRAFT, for the pension rules owner to confirm (docs/pension-rules-decisions.md, Appendix B).
Drawn from the entitlement rules the domain brief cites (ENT-01 to ENT-07) and the office
checklist's conditional items (AG-14 to AG-17, AG-21): the spouse first; sons to a prescribed
age (BLOCKING-08, draft 21); unmarried daughters until marriage; widowed or divorced daughters
while dependent and without a regular income; disabled children on a Medical Board certificate;
dependent parents; sisters as the office's checklist column has them. Anything else --
grandchildren, in-laws, nephews and nieces, brothers -- is not on the list, and a claim under it
is a finding, never a share.

``parse_relation`` reads the relation as the prescribed form words it. The forms are not
consistent: "widow", "Widow / Widower", "w/o Khan Bahadur", "Wife d/o Ali Ahmad", "divorce
daughter", "widow daughter of late Muhammad Bashir", "Son, Disable" all occur on real bundles.
A relation word beside a parentage marker ("Wife d/o ...") is the relation; the marker is the
parentage. A marker alone ("d/o Muhammad Munir") is the relation. "Wife d/o" used to read as a
daughter, because child markers were tested first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: The age until which a son draws, per the draft list. BLOCKING-08: the office has not
#: confirmed the prescribed age; the finding that uses it says so.
SON_AGE_LIMIT_YEARS = 21


@dataclass(frozen=True)
class Proof:
    """One thing the claim must prove, and the documents that prove it as the reader names them."""

    kind: str                      # relationship | marital_status | age | income | disability | dependency
    documents: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class EligibleRelation:
    key: str
    label: str
    rule: str
    share_key: str                 # the share class in rules/family_pension_dii.yaml
    variant: str                   # the office checklist column (config/case_types.json)
    limit: str                     # how long the entitlement runs, as the rules put it
    proofs: tuple[Proof, ...]
    confirm: str                   # what the rules owner must confirm before this row is final


_FRC = ("NADRA_FRC",)
_FRC_OR_NIKAH = ("NIKAH_NAMA", "NADRA_FRC")
_AGE = ("CNIC", "CNIC_CLAIMANT", "NADRA_FRC", "MATRIC_CERTIFICATE")
_INCOME = ("NO_REGULAR_INCOME_CERTIFICATE",)

ELIGIBLE_RELATIONS: tuple[EligibleRelation, ...] = (
    EligibleRelation(
        key="spouse", label="Widow / widower", rule="ENT-01", share_key="widow_percent", variant="WIDOW",
        limit="For life; ends on remarriage (ENT-01). The spouse precedes every other class (ENT-07).",
        proofs=(Proof("relationship", _FRC_OR_NIKAH, "the marriage: Nikah Nama, or the NADRA FRC showing the spouse"),
                Proof("marital_status", ("NON_REMARRIAGE_CERTIFICATE",), "not remarried (Form C-1 / non-remarriage certificate, AG-15)")),
        confirm="that a widower is paid on the same terms as a widow",
    ),
    EligibleRelation(
        key="son", label="Son", rule="ENT-02", share_key="unmarried_child_percent", variant="UNMARRIED_CHILD",
        limit=f"Until the prescribed age (draft {SON_AGE_LIMIT_YEARS}; BLOCKING-08).",
        proofs=(Proof("relationship", _FRC, "named as a son on the NADRA FRC"),
                Proof("age", _AGE, "date of birth from the CNIC / B-form, the FRC or the matriculation certificate")),
        confirm=f"the age limit ({SON_AGE_LIMIT_YEARS}?) and whether it extends while in full-time education",
    ),
    EligibleRelation(
        key="unmarried_daughter", label="Unmarried daughter", rule="ENT-03", share_key="unmarried_child_percent", variant="UNMARRIED_CHILD",
        limit="Until marriage (ENT-03).",
        proofs=(Proof("relationship", _FRC, "named as a daughter on the NADRA FRC"),
                Proof("marital_status", _FRC, "recorded unmarried on the NADRA FRC")),
        confirm="whether an unmarried daughter's entitlement is for life under the current rules",
    ),
    EligibleRelation(
        key="widowed_daughter", label="Widowed daughter", rule="ENT-03", share_key="regrant_daughter_percent", variant="WD_DAUGHTER",
        limit="While widowed and dependent, without a regular income (ENT-03).",
        proofs=(Proof("relationship", _FRC, "named as a daughter on the NADRA FRC"),
                Proof("marital_status", ("NADRA_FRC", "NADRA_DEATH_CERTIFICATE"), "widowed: the FRC's status, or the husband's death certificate"),
                Proof("income", _INCOME, "no regular source of income (AG-17)")),
        confirm="the dependency and income conditions",
    ),
    EligibleRelation(
        key="divorced_daughter", label="Divorced daughter", rule="ENT-03", share_key="regrant_daughter_percent", variant="DIVORCED_DAUGHTER",
        limit="While divorced and dependent, without a regular income (ENT-03); from the divorce.",
        proofs=(Proof("relationship", _FRC, "named as a daughter on the NADRA FRC"),
                Proof("marital_status", ("DIVORCE_CERTIFICATE",), "the divorce deed / certificate (AG-21)"),
                Proof("income", _INCOME, "no regular source of income (AG-17)")),
        confirm="the dependency and income conditions, and the divorce-timing rule",
    ),
    EligibleRelation(
        key="disabled_child", label="Disabled son / daughter", rule="ENT-04", share_key="disabled_child_percent", variant="DISABLED_CHILD_SIBLING",
        limit="For life, while the disability lasts (ENT-04).",
        proofs=(Proof("relationship", _FRC, "named as a child on the NADRA FRC"),
                Proof("disability", ("MEDICAL_BOARD_CERTIFICATE",), "Medical Board certificate of permanent disability (AG-14)")),
        confirm="which Board's certificate the office accepts",
    ),
    EligibleRelation(
        key="parent", label="Dependent father / mother", rule="ENT-05", share_key="parent_percent", variant="PARENT",
        limit="While dependent, where no spouse or eligible child survives (ENT-05, ENT-07).",
        proofs=(Proof("relationship", _FRC, "named as a parent on the NADRA FRC"),
                Proof("dependency", _INCOME, "dependent on the deceased; no regular income (AG-17)")),
        confirm="the dependency test the office applies",
    ),
    EligibleRelation(
        key="sister", label="Unmarried / widowed / divorced sister", rule="office column", share_key="sister_percent", variant="SISTER",
        limit="As the office's checklist column has it; the rules cited name no sister.",
        proofs=(Proof("relationship", _FRC, "named as a sister on the NADRA FRC"),
                Proof("marital_status", ("NADRA_FRC", "DIVORCE_CERTIFICATE", "NADRA_DEATH_CERTIFICATE"), "unmarried, widowed or divorced"),
                Proof("income", _INCOME, "no regular source of income (AG-17)")),
        confirm="WHETHER a sister is eligible at all, and on what conditions",
    ),
    EligibleRelation(
        key="child", label="Child (son or daughter, sex not stated)", rule="ENT-02 / ENT-03", share_key="unmarried_child_percent", variant="UNMARRIED_CHILD",
        limit="As a son or an unmarried daughter, once the form says which.",
        proofs=(Proof("relationship", _FRC, "named as a child on the NADRA FRC"),
                Proof("age", _AGE, "date of birth"),
                Proof("marital_status", _FRC, "marital status on the NADRA FRC")),
        confirm="(none: resolves to son or daughter on the FRC)",
    ),
)
BY_KEY = {r.key: r for r in ELIGIBLE_RELATIONS}

#: Every assumption the list rests on, numbered, with the rule or document it was drawn from, so the
#: rules owner can confirm them one by one (owner's request of 7 Oct 2026). Change a row here and the
#: decision sheet's Appendix B follows (``appendix_markdown``).
ASSUMPTIONS: tuple[tuple[int, str, str], ...] = (
    (1, "The spouse (widow or widower) precedes every other class; the entitlement is for life and ends on remarriage.",
     "ENT-01, ENT-07 (domain brief)"),
    (2, "A widower is paid on the same terms as a widow.", "ENT-01 (to confirm: the rule text says widow)"),
    (3, f"A son draws until the age of {SON_AGE_LIMIT_YEARS}; whether it extends while in full-time education is not settled.",
     "ENT-02; BLOCKING-08 (prescribed age unconfirmed)"),
    (4, "An unmarried daughter draws until marriage; whether it is for life under the current rules is not settled.",
     "ENT-03"),
    (5, "A widowed or divorced daughter draws while dependent and without a regular income; the divorce is proved by the deed, "
        "the widowhood by the FRC or the husband's death certificate, the income by the no-regular-income certificate.",
     "ENT-03; office checklist AG-17, AG-21; family_pension_dii.yaml eligibility.daughter_requires_no_source_of_income (UNSET)"),
    (6, "A disabled son or daughter draws for life while the disability lasts, on a Medical Board certificate.",
     "ENT-04; office checklist AG-14"),
    (7, "A dependent father or mother draws only where no spouse or eligible child survives, and while dependent "
        "(no regular income).", "ENT-05, ENT-07; office checklist AG-17"),
    (8, "An unmarried, widowed or divorced sister is eligible at all, on the same dependency and income conditions.",
     "office checklist column SISTER only; no ENT rule names a sister"),
    (9, "The relationship is proved by the NADRA FRC naming the claimant, else (for the spouse) by the Nikah Nama.",
     "ENT-06 (Form C / C-1); office checklist item 22"),
    (10, "The claimant's marital status is taken from the NADRA FRC, falling back to Annex-A.",
     "domain brief §8.3 (NADRA above the department's declaration)"),
    (11, "The claimant's age is taken from the FRC's year of birth, else the CNIC / B-form or the matriculation certificate.",
     "CNIC / FRC as the age documents; no rule text names the proof"),
    (12, "The spouse's not having remarried is proved by the non-remarriage certificate (Form C-1).",
     "ENT-06; office checklist AG-15"),
    (13, "Grandchildren, sons- and daughters-in-law, nephews and nieces, brothers, uncles, aunts, cousins and step-relations "
         "are not eligible.", "not named in ENT-01 to ENT-07"),
    (14, "A relation the papers do not state (form, FRC applicant, FRC row, Annex-A) is a check for the reviewer, not a bar.",
     "owner's decision of 7 Oct 2026 (advisory list)"),
)

#: Words that name a relation the rules do not pay, whatever else the text says.
NOT_ELIGIBLE_WORDS = frozenset({"grandson", "granddaughter", "grand", "grandfather", "grandmother", "nephew", "niece",
                                "brother", "brothers", "uncle", "aunt", "cousin", "law", "step"})
_SPOUSE_WORDS = frozenset({"widow", "widower", "spouse", "wife", "husband"})
_SPOUSE_MARKS = frozenset({"w/o", "h/o"})
_DAUGHTER_WORDS = frozenset({"daughter", "daughters", "dgt", "dst", "dtr"})
_SON_WORDS = frozenset({"son", "sons"})
_CHILD_WORDS = frozenset({"child", "children"})
_PARENT_WORDS = frozenset({"father", "mother", "parent", "parents"})
_TOKEN = re.compile(r"[a-z]+(?:/[a-z]+)?")


@dataclass(frozen=True)
class ParsedRelation:
    key: str | None               # an ELIGIBLE_RELATIONS key, or None
    reason: str                   # why, in words an officer can read
    words: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return self.key is not None

    @property
    def entry(self) -> EligibleRelation | None:
        return BY_KEY.get(self.key) if self.key else None


def parse_relation(text: str | None) -> ParsedRelation:
    """The claimant's relation as the form words it, read against the fixed list."""
    raw = (text or "").strip().casefold()
    tokens = tuple(_TOKEN.findall(raw))
    if not tokens:
        return ParsedRelation(None, "the claimant's relation to the deceased is not stated", tokens)
    tset = set(tokens)
    if tset & NOT_ELIGIBLE_WORDS:
        return ParsedRelation(None, f"'{text.strip()}' names a relation the pension rules do not pay", tokens)
    disabled = any(t.startswith("disab") for t in tset)
    daughter = bool(tset & _DAUGHTER_WORDS)
    son = bool(tset & _SON_WORDS)
    child = bool(tset & _CHILD_WORDS)
    spouse = bool(tset & _SPOUSE_WORDS)
    parent = bool(tset & _PARENT_WORDS)
    sister = "sister" in tset or "sisters" in tset
    # A relation word beside a parentage marker is the relation; the marker is the parentage.
    # Only where NO relation word is present does the marker speak for itself.
    if not (daughter or son or child or spouse or parent or sister):
        if tset & _SPOUSE_MARKS:
            spouse = True
        elif "d/o" in tset:
            daughter = True
        elif "s/o" in tset:
            son = True
    if daughter or son or child:
        if disabled:
            return ParsedRelation("disabled_child", "a disabled child (ENT-04)", tokens)
        if daughter:
            if "divorc" in raw or "divorce" in raw:
                return ParsedRelation("divorced_daughter", "a divorced daughter (ENT-03)", tokens)
            if "widow" in raw:                       # "widow daughter", "widowed daughter"
                return ParsedRelation("widowed_daughter", "a widowed daughter (ENT-03)", tokens)
            return ParsedRelation("unmarried_daughter", "a daughter (ENT-03)", tokens)
        if son:
            return ParsedRelation("son", "a son (ENT-02)", tokens)
        return ParsedRelation("child", "a child, sex not stated", tokens)
    if spouse:
        return ParsedRelation("spouse", "the widow or widower (ENT-01)", tokens)
    if parent:
        return ParsedRelation("parent", "a parent (ENT-05)", tokens)
    if sister:
        return ParsedRelation("sister", "a sister (office column; eligibility to be confirmed)", tokens)
    return ParsedRelation(None, f"'{text.strip()}' matches no relation on the list", tokens)


def appendix_markdown() -> str:
    """The draft list as the decision sheet prints it (Appendix B)."""
    lines = ["| Relation | Rule | Entitlement runs | Proof needed (documents the reader names) | To confirm |",
             "|---|---|---|---|---|"]
    for r in ELIGIBLE_RELATIONS:
        proofs = "<br>".join(f"**{p.kind.replace('_', ' ')}** — {p.note} (`{'`, `'.join(p.documents)}`)" for p in r.proofs)
        lines.append(f"| {r.label} | {r.rule} | {r.limit} | {proofs} | {r.confirm} |")
    lines.append("")
    lines.append(f"Not on the list, and therefore a check for the reviewer: grandchildren, sons- and daughters-in-law, nephews "
                 f"and nieces, brothers, uncles, aunts, cousins, step-relations, and any relation the papers do not state. "
                 f"Sons' age limit used in the draft: {SON_AGE_LIMIT_YEARS} (BLOCKING-08).")
    lines.append("")
    lines.append("### Assumptions behind the list, to confirm one by one")
    lines.append("")
    lines.append("| # | Assumption | Drawn from | Confirmed |")
    lines.append("|---|---|---|---|")
    for n, text, source in ASSUMPTIONS:
        lines.append(f"| {n} | {text} | {source} | ☐ |")
    return "\n".join(lines)
