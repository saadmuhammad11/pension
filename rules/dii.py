"""Family pension on the death of a PENSIONER. Form D-II / Proforma D-II.

This is the other family-pension path, and it is arithmetically unrelated to the one in
``engine.py``. A death IN SERVICE accrues a fresh pension from pay and qualifying service
(``base x years x 7/300``). A death AFTER RETIREMENT does not: the pensioner already had a
sanctioned pension, was drawing it, and the family takes a share of it. Running the D-I
accrual on a D-II case would produce a plausible figure from the wrong inputs under the
wrong rule, which is the most dangerous output this system can make -- so the two never
share a code path, and ``classify_case`` below refuses rather than guessing between them.

NOTHING IS COMPUTED FROM A LITERAL HERE. Every share, base definition and commencement rule
is read from ``rules/family_pension_dii.yaml``. The values there are PROVISIONAL -- taken from
the project's documentation, not confirmed by AG Punjab -- and a determination that uses one
says so on its face: ``provisional``, engaging ``BLOCKING-07``, with the unconfirmed keys and
their source in the caveats. A value becomes confirmed through ``rules/confirmations.py``,
where an authorised desk records it with its authority; the engine then computes the same
figure as final. A key still UNSET where the arithmetic needs one figure raises ``RuleNotSet``
naming the key; where UNSET can be handled honestly -- the base, by emitting both figures the
form prints as two readings; the re-grant commencement, by stating the dates and no
commencement -- it is handled that way instead. There is no interpolation and no fallback to
the D-I arithmetic.

Standard library only, like the rest of ``rules``. The config is parsed by a deliberately
restricted reader (``_parse_config``) rather than PyYAML: BUILD §6.2 requires an auditor to
recompute a determination years later with this package and a Python interpreter, and a
dependency is one more thing that has to still exist and still behave identically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from .confirmations import AUTHORISED_DESKS, confirmed_values
from .money import exact, money, rupees
from .types import Ambiguity, Determination, Reading, Step

CONFIG_PATH = Path(__file__).parent / "family_pension_dii.yaml"

#: The bare word a value carries until AG Punjab has confirmed it.
UNSET = "UNSET"


class DIIError(ValueError):
    """Base for every refusal on this path. Each subclass states a distinct cause."""


class RuleNotSet(DIIError):
    """A rule value required for this determination has not been confirmed.

    Distinct from every other refusal on purpose. "Not computed" covering an unimplemented
    case type, a missing rule, a failed extraction and an absent document alike is what sent
    a day's work chasing an OCR bug for a case type that was never built.
    """


class CaseTypeNotDetermined(DIIError):
    """The bundle does not say which family-pension path applies."""


class CaseTypeNotImplemented(DIIError):
    """The path is known and this build has no calculator for it."""


class InputMissing(DIIError):
    """A figure the rules need could not be read from the prescribed form."""


# ==============================================================================================
# Case classification
# ==============================================================================================

DEATH_IN_SERVICE = "DEATH_IN_SERVICE"
DEATH_AFTER_RETIREMENT = "DEATH_AFTER_RETIREMENT"
REGRANT_AFTER_WIDOW_DEATH = "REGRANT_AFTER_WIDOW_DEATH"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CaseClass:
    """Which path a bundle takes, and the evidence for it.

    ``evidence`` is not decoration: the class decides which arithmetic runs, so an officer
    reading the determination has to be able to see what the decision rested on.
    """

    case: str
    evidence: str
    prescribed_form: str | None = None

    @property
    def determinable(self) -> bool:
        return self.case in (DEATH_IN_SERVICE, DEATH_AFTER_RETIREMENT,
                             REGRANT_AFTER_WIDOW_DEATH)


def _name_key(name: str | None) -> str:
    """A name reduced to its letters, honorifics dropped, for equality only."""
    text = re.sub(r"[^a-z ]+", " ", (name or "").casefold())
    words = [w for w in text.split()
             if w not in ("mst", "mr", "mrs", "ms", "miss", "late", "mohtarma", "musammat")]
    return " ".join(words)


def vet_prior_pensioner(
    *,
    claimant_name: str | None,
    deceased_name: str | None,
    prior_name: str | None,
    prior_death: date | None,
    other_dates: tuple[date | None, ...] = (),
) -> tuple[str | None, date | None, str | None]:
    """Keep the prior-family-pensioner fields only where they can be what they claim to be.

    Returns ``(name, death, note)``: the fields as vetted, and where they were discarded, the
    sentence saying why. Exists because the vision model filled these fields on every one of
    five real D-II bundles with the CLAIMANT'S OWN NAME and a date copied from elsewhere on
    the form -- the pensioner's death, his retirement, her divorce -- so a living widow was
    reported as having died and every first grant became a re-grant computed under the
    re-grant rule. The vet is deterministic: a prior family pensioner is somebody other than
    the claimant and the deceased, and she died on a date that is not one of the other dated
    events on the form. Where either fails the fields are dropped, not corrected.
    """
    if not prior_name and prior_death is None:
        return None, None, None
    reasons: list[str] = []
    if prior_name and _name_key(prior_name) == _name_key(claimant_name):
        reasons.append(f"the extraction names the claimant herself ({prior_name!r}) as the "
                       f"prior family pensioner")
    if prior_name and _name_key(prior_name) == _name_key(deceased_name):
        reasons.append(f"the extraction names the deceased pensioner ({prior_name!r}) as the "
                       f"prior family pensioner")
    if prior_death is not None and any(d is not None and d == prior_death for d in other_dates):
        reasons.append(f"the prior pensioner's date of death {prior_death.isoformat()} is "
                       f"another dated event on the form")
    if prior_death is None:
        reasons.append("no date of death is read for the prior family pensioner")
    if not reasons:
        return prior_name, prior_death, None
    return None, None, (
        "The prior-family-pensioner fields were read but not relied on: "
        + "; ".join(reasons)
        + ". The case is treated as a first grant. Where the papers do describe a widow who "
          "was drawing the family pension and has since died, an officer classes the case "
          "as a re-grant and fixes the commencement."
    )


def classify_case(
    *,
    prescribed_form: str | None,
    date_of_retirement: date | None = None,
    date_of_death: date | None = None,
    prior_pensioner_death: date | None = None,
) -> CaseClass:
    """Decide which family-pension path this bundle is on. Never guesses.

    The form is the primary evidence and the dates corroborate it:

    * Form D-I is the in-service form. The servant was serving when they died.
    * Form D-II is the death-of-a-pensioner form. They had retired and were drawing.
    * A D-II bundle that ALSO records the death of a prior family pensioner -- the widow who
      was herself drawing -- is a re-grant, which is a further rule again.

    Returns ``UNKNOWN`` where the evidence does not settle it. ``UNKNOWN`` refuses downstream;
    it never falls through to a default path.
    """
    if prescribed_form == "FORM_D_I":
        return CaseClass(DEATH_IN_SERVICE,
                         "Form D-I is the prescribed form for a death in service.",
                         "FORM_D_I")

    if prescribed_form == "FORM_D_II":
        if prior_pensioner_death is not None:
            return CaseClass(
                REGRANT_AFTER_WIDOW_DEATH,
                f"Form D-II, and the form records a prior family pensioner who died on "
                f"{prior_pensioner_death.isoformat()}, so this is a re-grant rather than a "
                f"first grant.",
                "FORM_D_II",
            )
        return CaseClass(
            DEATH_AFTER_RETIREMENT,
            "Form D-II is the prescribed form for the death of a pensioner.",
            "FORM_D_II",
        )

    # No prescribed form. The dates can still settle it where both are readable, but only in
    # the direction that is safe to infer: a death AFTER a retirement date is not a death in
    # service. The reverse is not inferred -- a missing retirement date is not evidence of
    # service, it is a missing date.
    if date_of_retirement and date_of_death and date_of_death > date_of_retirement:
        return CaseClass(
            DEATH_AFTER_RETIREMENT,
            f"No prescribed form was identified, but the papers state a retirement on "
            f"{date_of_retirement.isoformat()} and a death on {date_of_death.isoformat()}. "
            f"A servant who has retired is not in service.",
            None,
        )

    return CaseClass(
        UNKNOWN,
        "No prescribed form (D-I or D-II) was identified and the dates do not settle whether "
        "the servant died in service or after retirement. The two are computed under "
        "different rules, so the case is not classified rather than assumed.",
        None,
    )


# ==============================================================================================
# The config
# ==============================================================================================

_KEY = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$")


def _parse_config(text: str) -> dict[str, Any]:
    """Read the restricted subset ``family_pension_dii.yaml`` is written in.

    Supports exactly what the file uses: ``key: value``, two-space nesting one level deep,
    ``#`` comments and blank lines. Anything else raises, because a config reader that
    silently ignores what it does not understand turns a typo into a missing rule and a
    missing rule into a wrong pension.
    """
    root: dict[str, Any] = {}
    section: dict[str, Any] | None = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        m = _KEY.match(line)
        if not m:
            raise DIIError(f"{CONFIG_PATH.name}:{lineno}: cannot read {raw.strip()!r}")
        indent, key, value = len(m.group(1)), m.group(2), m.group(3)
        if indent == 0:
            if value == "":
                section = {}
                root[key] = section
            else:
                root[key] = value
                section = None
        elif indent == 2:
            if section is None:
                raise DIIError(f"{CONFIG_PATH.name}:{lineno}: {key!r} is indented under nothing")
            section[key] = value
        else:
            raise DIIError(f"{CONFIG_PATH.name}:{lineno}: unexpected indent of {indent}")
    return root


@dataclass(frozen=True)
class DIIRules:
    """The rule values in force, which of them are confirmed, and which this run has used.

    ``values`` is the yaml with every confirmation in force overlaid on it. ``shipped`` is
    the yaml as written, kept so a screen can show what the file says beside what an
    authorised desk has since confirmed. ``used`` accumulates every value the engine read,
    with whether it was confirmed -- that list is what makes a determination provisional.
    """

    values: dict[str, Any]
    source: str
    shipped: dict[str, Any] = field(default_factory=dict)
    confirmed_keys: frozenset[str] = frozenset()
    used: list[tuple[str, str, bool]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None,
             confirmations: list[dict] | None = None) -> "DIIRules":
        """The yaml, with the confirmations log overlaid.

        ``confirmations`` is the list of log entries to apply; ``None`` reads the default
        log. A test that must not see the office's real confirmations passes ``[]``.
        """
        p = path or CONFIG_PATH
        shipped = _parse_config(p.read_text(encoding="utf-8"))
        values = {k: (dict(v) if isinstance(v, dict) else v) for k, v in shipped.items()}
        if confirmations is None:
            in_force = confirmed_values()
        else:
            in_force = {}
            for entry in confirmations:
                if entry.get("key"):
                    in_force[entry["key"]] = entry
        confirmed: set[str] = set()
        for dotted, entry in in_force.items():
            section, _, name = dotted.partition(".")
            if not name:
                continue
            values.setdefault(section, {})
            if isinstance(values[section], dict):
                values[section][name] = str(entry.get("value"))
                confirmed.add(dotted)
        return cls(values=values, source=p.name, shipped=shipped,
                   confirmed_keys=frozenset(confirmed))

    @property
    def file_confirmed(self) -> bool:
        """Whether the yaml itself is marked confirmed throughout. Only AG Punjab writes that."""
        return str(self.values.get("status", "provisional")).strip().casefold() == "confirmed"

    def is_confirmed(self, *keys: str) -> bool:
        return self.file_confirmed or ".".join(keys) in self.confirmed_keys

    def optional(self, *keys: str) -> str | None:
        """A value, or ``None`` where the file leaves it UNSET. Records nothing.

        For the keys whose absence the engine can handle honestly. The caller that gets
        ``None`` is responsible for saying, on the determination, what it did instead.
        """
        try:
            value = self._raw(*keys)
        except RuleNotSet:
            return None
        return None if value in (UNSET, "") else str(value)

    @property
    def provisional_used(self) -> tuple[str, ...]:
        """The dotted keys this run read that no authority has confirmed, in order of use."""
        seen: list[str] = []
        for key, _value, confirmed in self.used:
            if not confirmed and key not in seen:
                seen.append(key)
        return tuple(seen)

    def _raw(self, *keys: str) -> Any:
        node: Any = self.values
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                raise RuleNotSet(
                    f"{self.source} has no value at {'.'.join(keys)}. The rules for a family "
                    f"pension on the death of a pensioner are not loaded, and this engine "
                    f"will not substitute the death-in-service arithmetic for them."
                )
            node = node[k]
        return node

    def require(self, *keys: str) -> str:
        """A value the arithmetic needs, or a refusal naming exactly what AG Punjab must supply.

        Records the use, and whether the value was confirmed, so the determination can say.
        """
        value = self._raw(*keys)
        if value == UNSET or value == "":
            raise RuleNotSet(
                f"the rule value '{'.'.join(keys)}' has not been confirmed by AG Punjab "
                f"(it is {UNSET} in {self.source}). This determination cannot be computed "
                f"until it is. No default is applied: a family pension paid on a guessed "
                f"share is wrong for the life of the claimant, and nothing on the page "
                f"would show it."
            )
        self.used.append((".".join(keys), str(value), self.is_confirmed(*keys)))
        return str(value)

    def percent(self, *keys: str) -> Decimal:
        value = self.require(*keys)
        try:
            return money(value)
        except Exception as exc:                          # noqa: BLE001
            raise RuleNotSet(
                f"the rule value '{'.'.join(keys)}' reads {value!r}, which is not a "
                f"percentage this engine can use."
            ) from exc

    @property
    def is_configured(self) -> bool:
        """Whether ANY value has been confirmed. Used only to report, never to branch."""
        def walk(node: Any) -> bool:
            if isinstance(node, dict):
                return any(walk(v) for v in node.values())
            return node not in (UNSET, "")
        return walk(self.values.get("share", {}))


# ==============================================================================================
# Inputs
# ==============================================================================================

@dataclass(frozen=True)
class Provenance:
    """Where one input came from. Required by the Annual Certification Audit.

    Every figure on a determination has to be traceable to the page it was read from and the
    rule that consumed it, years later, without re-running a model.
    """

    field: str
    value: str
    page: int | None = None
    document: str | None = None
    source: str = "extracted"

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "value": self.value, "page": self.page,
                "document": self.document, "source": self.source}


@dataclass(frozen=True)
class DeathAfterRetirementCase:
    """Inputs for a family pension on the death of a pensioner. Inputs only.

    No derived amounts: the share, the base and the commencement are the engine's job.
    """

    case_ref: str
    #: What the deceased pensioner was drawing, as the prescribed form states it beside
    #: "drawing pension @" -- the pension in payment.
    sanctioned_pension: Decimal | None
    claimant_relation: str
    #: The "Net Pension" line, where the form prints one. On the Khan Bahadur form it is
    #: Rs. 1,066 against a pension in payment of Rs. 50,000: the original net pension before
    #: twenty-eight years of increases. Which of the two the share applies to is BLOCKING-07.
    net_pension: Decimal | None = None
    #: The "Total pension" line, where printed. Recorded for the trail; not a base candidate
    #: on its own, because on both sample forms it restates the pension in payment.
    total_pension: Decimal | None = None
    date_of_death_of_pensioner: date | None = None
    date_of_retirement: date | None = None
    #: Set only on a re-grant: the family pensioner who was drawing before this claimant.
    prior_pensioner_name: str | None = None
    prior_pensioner_death: date | None = None
    #: Where the claimant is a divorced daughter, the date the divorce took effect. Her
    #: eligibility cannot precede it, so the commencement is not asserted without a rule.
    date_of_divorce: date | None = None
    #: Where each of the above was read from.
    provenance: tuple[Provenance, ...] = field(default_factory=tuple)
    extra_caveats: tuple[str, ...] = field(default_factory=tuple)


def determine_family_pension_death_after_retirement(
    case: DeathAfterRetirementCase,
    rules: DIIRules,
    case_class: CaseClass,
    computed_at: datetime,
) -> Determination:
    """Compute the family pension payable on the death of a pensioner.

    Refuses, with a distinct and specific message, on each of:

    * a case class this function is not the calculator for;
    * a rule value AG Punjab has not confirmed;
    * a base figure that could not be read off the prescribed form.

    It never produces a figure by any other route.
    """
    if case_class.case not in (DEATH_AFTER_RETIREMENT, REGRANT_AFTER_WIDOW_DEATH):
        raise CaseTypeNotImplemented(
            f"this calculator computes a family pension on the death of a PENSIONER, and "
            f"the case is classified {case_class.case}. {case_class.evidence}"
        )

    steps: list[Step] = []
    ambiguities: list[Ambiguity] = []
    trail: list[Provenance] = list(case.provenance)
    regrant = case_class.case == REGRANT_AFTER_WIDOW_DEATH

    # -- 1. the base ---------------------------------------------------------------------
    # Two figures can be on the form: the pension in payment ("drawing pension @") and the
    # "Net Pension" line. Where base.definition is confirmed, that figure is the base. Where
    # it is UNSET and both are printed and differ, the engine will not choose: the family
    # pension is emitted on each as a labelled reading (BLOCKING-07). Where only one figure
    # is printed, it is the base and the step says which.
    drawn, net = case.sanctioned_pension, case.net_pension
    definition = rules.optional("base", "definition")
    if drawn is None and net is None:
        raise InputMissing(
            "the pension the deceased was drawing could not be read from the prescribed "
            "form. It is printed on Form D-II beside 'drawing pension/family pension @'. An "
            "officer must supply it or transcribe the page; it is not inferred from the "
            "pension slip, which may state a different figure on a different basis."
        )
    candidates: list[tuple[str, Decimal, str]] = []
    if definition is not None:
        rules.require("base", "definition")          # records the use and its status
        want_net = definition == "net_pension"
        chosen = net if want_net else drawn
        if chosen is None:
            raise InputMissing(
                f"the rules take the share on the '{definition}' of the deceased pensioner, "
                f"and that figure is not printed on this form."
            )
        candidates.append((definition, money(chosen),
                           f"base.definition = {definition} ({rules.source})"))
        trail.append(Provenance("base.definition", definition, source=f"rule:{rules.source}"))
    else:
        if drawn is not None:
            candidates.append(("pension_in_payment", money(drawn),
                               "the figure beside 'drawing pension @' on the prescribed form"))
        if net is not None and (drawn is None or money(net) != money(drawn)):
            candidates.append(("net_pension", money(net),
                               "the 'Net Pension' line on the prescribed form"))
        rules.used.append(("base.definition", UNSET, False))
        trail.append(Provenance("base.definition", UNSET, source=f"rule:{rules.source}"))

    for label, amount, basis in candidates:
        steps.append(Step(
            rule_id="FAM-AR-01",
            description=f"Pension of the deceased pensioner: {label.replace('_', ' ')}",
            computation_shown=f"{exact(amount)} as stated on the prescribed form",
            amount=amount,
            note=basis,
        ))

    # -- 2. the share --------------------------------------------------------------------
    if regrant:
        key = ("share", "regrant_daughter_percent")
        rule_id = "FAM-AR-03"
        what = (f"Re-grant to {case.claimant_relation or 'the claimant'} after the death of "
                f"{case.prior_pensioner_name or 'the prior family pensioner'}")
    else:
        key = ("share", _share_key_for(case.claimant_relation))
        rule_id = "FAM-AR-02"
        what = f"Family pension for {case.claimant_relation or 'the claimant'}"

    percent = rules.percent(*key)
    trail.append(Provenance(".".join(key), str(percent), source=f"rule:{rules.source}"))
    share_note = f"Share read from {rules.source} at {'.'.join(key)}."
    if not rules.is_confirmed(*key):
        share_note += " PROVISIONAL - not confirmed by AG Punjab (BLOCKING-07)."

    if len(candidates) == 1:
        _label, base, _basis = candidates[0]
        payable = base * percent / 100
        steps.append(Step(
            rule_id=rule_id,
            description=what,
            computation_shown=f"{exact(base)} x {exact(percent)}% = {exact(payable)}",
            amount=payable,
            note=share_note,
        ))
    else:
        # BLOCKING-07, the base half. Two figures on the form, no confirmed rule saying which
        # the share applies to, and on the sample forms they differ by an order of magnitude
        # -- so both readings are carried and no single figure exists. See rules/types.py.
        readings = tuple(
            Reading(
                label=f"on_{label}",
                amount=base * percent / 100,
                computation_shown=(
                    f"{exact(base)} x {exact(percent)}% = {exact(base * percent / 100)}"),
                basis=f"{what}, taking the share on {basis}.",
            )
            for label, base, basis in candidates
        )
        ambiguities.append(Ambiguity(
            rule_id=rule_id,
            blocking_id="BLOCKING-07",
            question=(
                "Does the family take its share of the pension in payment (after every "
                "increase since retirement) or of the net pension as originally sanctioned?"
            ),
            readings=readings,
            resolve_with=(
                "Confirm base.definition (pension_in_payment | net_pension) with the Punjab FD "
                "notification fixing the family-pension base; a "
                f"{AUTHORISED_DESKS['DAG_PENSION']} or the "
                f"{AUTHORISED_DESKS['REFERENCE_ADMIN']} records it in the portal."
            ),
        ))

    # -- 3. commencement -----------------------------------------------------------------
    which = "on_regrant" if regrant else "on_death_of_pensioner"
    anchor = case.prior_pensioner_death if regrant else case.date_of_death_of_pensioner
    commencement_rule = rules.optional("commencement", which)
    # on_death_of_pensioner is the SPOUSE's rule: the widow's entitlement arises on the death
    # itself. A daughter's arises on her own event -- the divorce, the widowhood, the death of
    # the widow who was drawing -- which on the divorced-daughter bundle is thirteen years
    # after the pensioner died. Asserting "day after death" for her would date a family
    # pension from 2010 for an eligibility that began in 2023, so for any claimant who is
    # not the spouse the rule is not applied and the dates are stated instead.
    spouse_rule_not_hers = (not regrant
                            and _share_key_for(case.claimant_relation) != "widow_percent")
    if spouse_rule_not_hers:
        commencement_rule = None
    if commencement_rule is not None:
        rules.require("commencement", which)
        trail.append(Provenance("commencement", commencement_rule, source=f"rule:{rules.source}"))
        if anchor is None:
            raise InputMissing(
                f"the commencement rule is '{commencement_rule}', and the date it runs from "
                f"could not be read from the papers."
            )
        steps.append(Step(
            rule_id="FAM-AR-05",
            description="Family pension commences",
            computation_shown=f"{commencement_rule} from {anchor.isoformat()}",
            amount=None,
            unit="date",
            note=None if rules.is_confirmed("commencement", which)
            else "PROVISIONAL - commencement rule not confirmed by AG Punjab (BLOCKING-07).",
        ))
    else:
        # The rule is open. State the dates the papers carry and no commencement, rather than
        # pick one: on the divorced-daughter bundle the widow's death, the divorce and the
        # application are years apart, and arrears turn on which.
        rules.used.append((f"commencement.{which}", UNSET, False))
        dates = [
            f"death of pensioner {case.date_of_death_of_pensioner.isoformat()}"
            if case.date_of_death_of_pensioner else None,
            f"death of prior family pensioner {case.prior_pensioner_death.isoformat()}"
            if case.prior_pensioner_death else None,
            f"divorce of claimant {case.date_of_divorce.isoformat()}"
            if case.date_of_divorce else None,
        ]
        why = (
            f"commencement.{which} applies to the spouse, and the claimant is "
            f"{case.claimant_relation!r}; her entitlement arises on her own event and no "
            f"rule for it is confirmed"
            if spouse_rule_not_hers else
            f"commencement.{which} is UNSET in {rules.source}"
        )
        steps.append(Step(
            rule_id="FAM-AR-05",
            description="Family pension commences",
            computation_shown=(
                f"not determined: {why}. Dates on the papers: "
                f"{'; '.join(d for d in dates if d) or 'none read'}."
            ),
            amount=None,
            unit="date",
            note="An officer fixes the commencement until the rule is confirmed (BLOCKING-07).",
        ))

    # -- 3b. how long the spouse draws, FAM-AR-06 ---------------------------------------
    # Rule 4.10(1) as substituted by FD.SR-III-4-244/2023(B) on 2 December 2024: the spouse
    # for ten years or until re-marriage, whichever is earlier; an issueless spouse for life.
    # Stated for the spouse only -- a daughter's or parent's cessation is UNSET -- and only
    # where the pensioner died on or after the date the yaml carries, because the notification
    # takes "immediate effect" and says nothing about earlier deaths.
    is_spouse = (not regrant and _share_key_for(case.claimant_relation) == "widow_percent")
    if is_spouse and case.date_of_death_of_pensioner is not None:
        steps.extend(_spouse_term_steps(case, rules, commencement_rule, anchor))

    # -- 4. what is provisional, said on the face of the determination -------------------
    provisional_keys = rules.provisional_used
    engaged: tuple[str, ...] = ("BLOCKING-07",) if (provisional_keys or ambiguities) else ()

    caveats = [
        "AI extracted the inputs; this determination was computed by the rules engine with "
        "no model in the causal chain of any figure.",
        f"Computed on the Form D-II rules in {rules.source}. Every value used is recorded in "
        "the provenance block and can be traced to its rule.",
    ]
    if provisional_keys:
        used_values = {k: v for k, v, _ok in rules.used}
        shown = ", ".join(f"{k} = {used_values.get(k, UNSET)}" for k in provisional_keys)
        caveats.append(
            f"PROVISIONAL (BLOCKING-07): {shown}. Source: "
            f"{rules.values.get('provisional_source', 'the project documentation')}. Not "
            f"confirmed by AG Punjab. A {AUTHORISED_DESKS['DAG_PENSION']} or the "
            f"{AUTHORISED_DESKS['REFERENCE_ADMIN']} confirms each value in the portal, citing "
            f"the notification, and the determination is then recomputed as final. No FPPO "
            f"may issue on a provisional figure."
        )
    caveats.append(
        "AI recommendation only - the determination rests with the Auditor / Accountant "
        "General."
    )
    caveats.extend(case.extra_caveats)

    return Determination(
        case_ref=case.case_ref,
        rule_pack_id=str(rules.values.get("id", "PB-DII-UNSET")),
        effective_date=anchor or case.date_of_death_of_pensioner or computed_at.date(),
        computed_at=computed_at,
        steps=tuple(steps),
        ambiguities=tuple(ambiguities),
        unverified_engaged=engaged,
        caveats=tuple(caveats),
        inputs={
            "case_class": case_class.case,
            "case_class_evidence": case_class.evidence,
            "prescribed_form": case_class.prescribed_form,
            "claimant_relation": case.claimant_relation,
            "sanctioned_pension": None if drawn is None else rupees(money(drawn)),
            "net_pension": None if net is None else rupees(money(net)),
            "total_pension": (None if case.total_pension is None
                              else rupees(money(case.total_pension))),
            "date_of_death_of_pensioner": (
                case.date_of_death_of_pensioner.isoformat()
                if case.date_of_death_of_pensioner else None),
            "prior_pensioner_name": case.prior_pensioner_name,
            "prior_pensioner_death": (case.prior_pensioner_death.isoformat()
                                      if case.prior_pensioner_death else None),
            "provisional_keys": list(provisional_keys),
            "provenance": [p.to_dict() for p in trail],
        },
    )



def _add_years(on: date, years: int) -> date:
    """The same calendar date ``years`` later; 29 February falls back to 28 February."""
    try:
        return on.replace(year=on.year + years)
    except ValueError:
        return on.replace(year=on.year + years, day=28)


def _spouse_term_steps(case: DeathAfterRetirementCase, rules: DIIRules,
                       commencement_rule: str | None, anchor: date | None) -> list[Step]:
    """The FAM-AR-06 step: when the spouse's family pension ceases, or why no term is stated.

    Reads ``cessation.spouse_term_years`` and ``cessation.spouse_term_applies_to_deaths_from``
    through ``require`` where they decide the step, so a determination that rests on them is
    provisional until an authorised desk confirms them (BLOCKING-07). Where the yaml leaves
    either UNSET the step says so and applies nothing.
    """
    death = case.date_of_death_of_pensioner
    assert death is not None
    applies_from_raw = rules.optional("cessation", "spouse_term_applies_to_deaths_from")
    years_raw = rules.optional("cessation", "spouse_term_years")
    if applies_from_raw is None or years_raw is None:
        rules.used.append(("cessation.spouse_term_years", UNSET, False))
        return [Step(
            rule_id="FAM-AR-06",
            description="Family pension to the spouse ceases",
            computation_shown=(
                f"not determined: cessation.spouse_term_years or "
                f"cessation.spouse_term_applies_to_deaths_from is UNSET in {rules.source}."
            ),
            amount=None, unit="date",
            note="An officer states the term until the rule is confirmed (BLOCKING-07).",
        )]
    try:
        applies_from = date.fromisoformat(applies_from_raw)
        years = int(years_raw)
    except ValueError as exc:
        raise DIIError(
            f"{rules.source}: cessation values are not readable "
            f"({applies_from_raw!r}, {years_raw!r}): {exc}"
        ) from None
    if death < applies_from:
        rules.used.append(("cessation.spouse_term_applies_to_deaths_from",
                           applies_from_raw,
                           rules.is_confirmed("cessation", "spouse_term_applies_to_deaths_from")))
        return [Step(
            rule_id="FAM-AR-06",
            description="Family pension to the spouse ceases",
            computation_shown=(
                f"no term applied: the pensioner died {death.isoformat()}, before the "
                f"{years}-year spouse term of rule 4.10(1) as substituted on 2 December 2024 "
                f"(FD.SR-III-4-244/2023(B)) took effect; that notification is applied to "
                f"deaths from {applies_from.isoformat()}."
            ),
            amount=None, unit="date",
            note=("The rule in force at the death governs the term and is not on file; the "
                  "officer states it. Whether the amendment reaches earlier deaths is for "
                  "AG Punjab to confirm (BLOCKING-07)."),
        )]
    rules.require("cessation", "spouse_term_applies_to_deaths_from")
    years = int(rules.require("cessation", "spouse_term_years"))
    remarriage = (rules.optional("cessation", "spouse_term_ends_on_remarriage") or "").casefold() == "true"
    issueless = (rules.optional("cessation", "issueless_spouse_for_life") or "").casefold() == "true"
    if anchor is not None and commencement_rule is not None:
        start = anchor + timedelta(days=1) if commencement_rule == "day_after_death" else anchor
        ends = _add_years(start, years)
        shown = f"{start.isoformat()} + {years} years = {ends.isoformat()}"
    else:
        shown = f"{years} years from the commencement (not yet fixed above)"
    if remarriage:
        shown += ", or the date of re-marriage if earlier"
    notes = []
    if issueless:
        notes.append("Where the pensioner left no issue, the spouse draws for life or until "
                     "re-marriage; the officer reads whether there is issue from the NADRA FRC.")
    notes.append("Where the pensioner left more than one widow, the pension is divided equally "
                 "among them. Rule 4.10(1) as substituted by FD.SR-III-4-244/2023(B), "
                 "2 December 2024.")
    confirmed = (rules.is_confirmed("cessation", "spouse_term_years")
                 and rules.is_confirmed("cessation", "spouse_term_applies_to_deaths_from"))
    if not confirmed:
        notes.append("PROVISIONAL - the date from which the amendment is applied is not "
                     "confirmed by AG Punjab (BLOCKING-07).")
    return [Step(
        rule_id="FAM-AR-06",
        description="Family pension to the spouse ceases",
        computation_shown=shown,
        amount=None, unit="date",
        note=" ".join(notes),
    )]


#: Claimant relations, as the prescribed forms word them. The forms are not consistent:
#: "widow", "Widow / Widower", "w/o Khan Bahadur", "divorce daughter", "divorced daughter",
#: "widow daughter of late Muhammad Bashir" all occur on real bundles. The daughter classes
#: are tested FIRST: "widow daughter" contains "widow", and reading it as the spouse paid a
#: widowed daughter the widow's share under the widow's commencement rule.
_SPOUSE = ("widow", "widower", "spouse", "wife", "husband", "w/o", "h/o")
_CHILD = ("daughter", "daughters", "son", "sons", "child", "children", "d/o", "s/o")
_DAUGHTER_REGRANT = ("divorc", "widowed", "widow daughter", "widow-daughter")


def _share_key_for(relation: str | None) -> str:
    """Which share governs this claimant. Raises rather than defaulting to the widow's."""
    text = (relation or "").strip().casefold()
    if not text:
        raise InputMissing(
            "the claimant's relation to the deceased pensioner could not be read from the "
            "prescribed form, and the share depends on it. A widow, a divorced daughter and "
            "a parent are not paid alike."
        )
    # Whole tokens, not substrings: "wife of Hassan" must not read as a son.
    tokens = set(re.findall(r"[a-z]+(?:/[a-z]+)?", text))
    if tokens & set(_CHILD) or any(t.startswith("daughter") for t in tokens):
        if "disabled" in text or "disable" in text:
            return "disabled_child_percent"
        if any(n in text for n in _DAUGHTER_REGRANT):
            return "regrant_daughter_percent"
        return "unmarried_child_percent"
    if any(n in text for n in _SPOUSE):
        return "widow_percent"
    if any(n in text for n in ("father", "mother", "parent")):
        return "parent_percent"
    if "sister" in text:
        return "sister_percent"
    raise CaseTypeNotImplemented(
        f"the prescribed form states the claimant's relation as {relation!r}, which matches "
        f"no class of claimant this build knows. It is not treated as a widow."
    )
