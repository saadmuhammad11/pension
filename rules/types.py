"""Determination value types, and the ambiguity mechanism. BRAIN §6.3, BUILD §6.1/§6.3.

BUILD §6.3 says to build this before the rules that need it, and §15 rule 3 restates it:
"Two readings get emitted as two readings." This module is that instruction expressed as
types, so that emitting one figure for an ambiguous rule is not a discipline the caller has
to remember -- it is a thing the code will not let you do.

The mechanism exists for ``BLOCKING-06``. On the golden case the gratuity for a death in
service is either Rs. 33,605 (literal: 25% of one month's gross) or Rs. 4,989,130
(capitalised: 25% x gross x 12 x age factor). Both readings are defensible from the
documents. They differ by 148.5x. Picking one silently would, across every in-service-death
case, either underpay bereaved families by roughly five million rupees each or overpay by
the same -- invisibly, until an audit years later.

So ``Ambiguity`` has no scalar value and no ``__int__``. There is no accessor that returns
"the" figure, because there is no such figure. A caller that wants a number has to choose a
reading by name, in code, in the open.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .money import Numeric, exact, fmt, money, rupees


class AmbiguityCollapseError(RuntimeError):
    """Something tried to reduce an unresolved ambiguity to a single figure.

    Raised by ``Ambiguity.__int__``/``__float__``/``__index__``. If you are seeing this,
    the calling code is treating a disputed rule as settled -- which is exactly the
    failure ``BLOCKING-06`` exists to prevent.
    """


@dataclass(frozen=True)
class Reading:
    """One defensible interpretation of a disputed rule.

    ``basis`` is not decoration. When AG Punjab eventually resolves the item, whoever does
    it needs to see which reading rested on which argument, and a determination already
    issued needs to say which one it used.
    """

    label: str
    amount: Decimal
    basis: str
    computation_shown: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))

    @property
    def presented(self) -> int:
        """The reading's own figure, rounded per ``FMT-01``."""
        return rupees(self.amount)


@dataclass(frozen=True)
class Ambiguity:
    """A rule with more than one defensible reading and no authority to choose between them.

    Carries every reading. Deliberately exposes no single value: see the module docstring.
    """

    rule_id: str
    blocking_id: str
    question: str
    readings: tuple[Reading, ...]
    resolve_with: str

    def __post_init__(self) -> None:
        if len(self.readings) < 2:
            raise ValueError(
                f"{self.rule_id}: an Ambiguity needs at least two readings; "
                f"got {len(self.readings)}. A rule with one reading is not ambiguous -- "
                "emit it as a Step."
            )
        labels = [r.label for r in self.readings]
        if len(set(labels)) != len(labels):
            raise ValueError(f"{self.rule_id}: reading labels must be distinct, got {labels}")

    # -- the guard rails -------------------------------------------------------------------
    def __int__(self) -> int:
        raise AmbiguityCollapseError(self._refusal())

    def __float__(self) -> float:
        raise AmbiguityCollapseError(self._refusal())

    def __index__(self) -> int:
        raise AmbiguityCollapseError(self._refusal())

    def _refusal(self) -> str:
        spread = self.spread_statement()
        return (
            f"{self.rule_id} ({self.blocking_id}) has {len(self.readings)} unresolved "
            f"readings and cannot be reduced to one figure. {spread} "
            f"Choose a reading explicitly by label, or resolve {self.blocking_id} with: "
            f"{self.resolve_with}"
        )

    # -- reporting -------------------------------------------------------------------------
    def reading(self, label: str) -> Reading:
        """Fetch one reading by name. The only way to get a number out of an Ambiguity.

        Deliberately verbose at the call site: choosing a reading is a decision with a
        rupee consequence and should read like one.
        """
        for r in self.readings:
            if r.label == label:
                return r
        raise KeyError(
            f"{self.rule_id}: no reading {label!r}; have {[r.label for r in self.readings]}"
        )

    def spread_statement(self) -> str:
        """State the difference between the extreme readings, in the engine's own words.

        BRAIN §14.1 requires the difference to be *stated*, not merely implied by printing
        two numbers next to each other.
        """
        amounts = sorted((r.presented for r in self.readings))
        low, high = amounts[0], amounts[-1]
        if low == 0:
            return f"Readings range from {fmt(low)} to {fmt(high)}."
        ratio = (money(high) / money(low)).quantize(Decimal("0.1"))
        return f"Readings differ by {ratio}x: {fmt(low)} against {fmt(high)}."

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "blocking_id": self.blocking_id,
            "question": self.question,
            "difference": self.spread_statement(),
            "resolve_with": self.resolve_with,
            "readings": [
                {
                    "label": r.label,
                    "amount": r.presented,
                    "computation_shown": r.computation_shown,
                    "basis": r.basis,
                }
                for r in self.readings
            ],
        }


@dataclass(frozen=True)
class Step:
    """One settled computation, showing its work. BUILD §6.2 requirement 3.

    ``computation_shown`` is the arithmetic as a string -- "192030 x 30 x 7 / 300" -- and it
    drives both the reviewer UI (§9.6 tab 5) and the audit record. A step whose work cannot
    be shown is a step an auditor cannot check.
    """

    rule_id: str
    description: str
    computation_shown: str
    amount: Decimal | None = None
    unit: str = "Rs./month"
    note: str | None = None

    def __post_init__(self) -> None:
        if self.amount is not None:
            object.__setattr__(self, "amount", money(self.amount))

    @property
    def presented(self) -> int | None:
        return None if self.amount is None else rupees(self.amount)

    @property
    def rounded(self) -> bool:
        """Whether ``FMT-01`` actually changed this figure. ``FMT-03`` wants this stated."""
        return self.amount is not None and money(self.amount) != money(self.presented)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "rule_id": self.rule_id,
            "description": self.description,
            "computation_shown": self.computation_shown,
            "amount": self.presented,
            "unit": self.unit,
        }
        if self.rounded:
            d["exact_before_rounding"] = exact(self.amount)
            d["rounding"] = "FMT-01 half-up"
        if self.note:
            d["note"] = self.note
        return d


@dataclass(frozen=True)
class Determination:
    """The engine's output for one case.

    ``provisional`` is derived, never set by a caller: any engaged BLOCKING item or any
    ambiguity makes the determination provisional, and BRAIN §14.1 requires that to appear
    "on its face, not in a footnote".
    """

    case_ref: str
    rule_pack_id: str
    effective_date: date
    computed_at: datetime
    steps: tuple[Step, ...] = ()
    ambiguities: tuple[Ambiguity, ...] = ()
    unverified_engaged: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    inputs: dict[str, Any] = field(default_factory=dict)

    @property
    def provisional(self) -> bool:
        return bool(self.ambiguities) or bool(self.unverified_engaged)

    def step(self, rule_id: str) -> Step:
        for s in self.steps:
            if s.rule_id == rule_id:
                return s
        raise KeyError(f"no step {rule_id!r}; have {[s.rule_id for s in self.steps]}")

    def ambiguity(self, rule_id: str) -> Ambiguity:
        for a in self.ambiguities:
            if a.rule_id == rule_id:
                return a
        raise KeyError(
            f"no ambiguity {rule_id!r}; have {[a.rule_id for a in self.ambiguities]}"
        )

    def amount(self, rule_id: str) -> int | None:
        """The presented figure for a settled step.

        Raises ``AmbiguityCollapseError`` if asked for a rule that is unresolved, rather
        than returning one of the readings.
        """
        for a in self.ambiguities:
            if a.rule_id == rule_id:
                raise AmbiguityCollapseError(a._refusal())
        return self.step(rule_id).presented

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_ref": self.case_ref,
            "rule_pack_id": self.rule_pack_id,
            "effective_date": self.effective_date.isoformat(),
            "computed_at": self.computed_at.isoformat(),
            "provisional": self.provisional,
            "unverified_rules_engaged": list(self.unverified_engaged),
            "steps": [s.to_dict() for s in self.steps],
            "ambiguities": [a.to_dict() for a in self.ambiguities],
            "caveats": list(self.caveats),
            "inputs": dict(self.inputs),
        }


@dataclass(frozen=True)
class Rule:
    """A rule as it appears in a pack: an id, what it does, and the authority behind it.

    ``FMT-04`` requires every presented figure to carry its rule ID and the notification
    behind it, which means the citation has to be data travelling with the pack, not a
    comment in the code.
    """

    id: str
    description: str
    citation: str
    unverified: str | None = None
