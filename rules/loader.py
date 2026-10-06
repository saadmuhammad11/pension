"""Loading and selecting effective-dated rule packs. BUILD §6.2 requirements 4, 5 and 7.

Three behaviours here carry rupee consequences, so each is enforced rather than documented:

1.  **JSON floats are refused at parse time.** ``json.load`` turns ``12.3719`` into a Python
    float, and a float commutation factor multiplied by a gross pension is precisely the
    precision loss ``FMT-02`` forbids. ``parse_float`` raises instead, which means a pack
    that drifts away from the string convention fails loudly on load rather than quietly in
    an arithmetic result.

2.  **Packs are selected by effective date, never by "latest".** Requirement 4: a 2021 death
    is determined on the pack in force in 2021, not on today's rates. ``select_pack`` takes
    the effective date as an argument; nothing in this module reads the system clock.

3.  **An unknown commutation age raises.** Requirement 7 and ``COMM-04``: only four
    benchmark factors are known (``BLOCKING-05``). Interpolating between 12.3719 at age 60
    and 7.8778 at age 70 would look reasonable and be fabricated. ``age_factor`` raises
    ``UnknownReferenceValue`` and the case routes to human determination.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from .money import money
from .types import Rule

PACK_DIR = Path(__file__).parent / "packs"


class PackError(RuntimeError):
    """A rule pack is malformed, missing, or ambiguous for the requested date."""


class UnknownReferenceValue(LookupError):
    """A reference value needed for the determination is not in the loaded pack.

    Raised rather than defaulted or interpolated. BUILD §6.2 requirement 7: "Unknown inputs
    raise; they do not default." The case routes to human determination.
    """


def _refuse_float(raw: str) -> Decimal:
    raise PackError(
        f"rule pack contains the bare JSON number {raw!r}. Numeric values must be quoted "
        "strings so they can be read as Decimal (FMT-02). Change it to \"" + raw + "\"."
    )


@dataclass(frozen=True)
class RulePack:
    """An effective-dated, jurisdiction-scoped set of rules and reference data."""

    id: str
    jurisdiction: str
    cohort: str
    effective_from: date
    effective_to: date | None
    rules: dict[str, Rule]
    reference_data: dict[str, Any]
    unverified: tuple[str, ...]

    # -- rules -----------------------------------------------------------------------------
    def rule(self, rule_id: str) -> Rule:
        try:
            return self.rules[rule_id]
        except KeyError:
            raise UnknownReferenceValue(
                f"rule {rule_id!r} is not in pack {self.id}. Available: "
                f"{sorted(self.rules)}"
            ) from None

    def covers(self, on: date) -> bool:
        if on < self.effective_from:
            return False
        return self.effective_to is None or on <= self.effective_to

    # -- reference data --------------------------------------------------------------------
    def ref(self, *path: str) -> Any:
        """Fetch a reference value by path, raising if absent or explicitly null.

        A ``null`` in the pack means "this authority has not been obtained" -- the minimum
        pension floors under ``BLOCKING-02``, the medical-allowance base under
        ``BLOCKING-03``. Returning ``None`` here would let a caller treat "unknown" as
        "zero" or "not applicable", so it raises instead.
        """
        node: Any = self.reference_data
        for key in path:
            if not isinstance(node, dict) or key not in node:
                raise UnknownReferenceValue(
                    f"{self.id}: no reference value at {'.'.join(path)}"
                )
            node = node[key]
        if node is None:
            raise UnknownReferenceValue(
                f"{self.id}: reference value {'.'.join(path)} is present but unresolved "
                f"(null). It awaits an authority; it must not be defaulted."
            )
        return node

    def amount(self, *path: str) -> Decimal:
        """A reference value as Decimal."""
        return money(self.ref(*path))

    def age_factor(self, age_next_birthday: int) -> Decimal:
        """Commutation age factor. ``COMM-04``. Never interpolates.

        Only four benchmark ages are loaded (``BLOCKING-05``). An age between them raises,
        naming the ages that *are* known so an officer can see how far off the case is.
        """
        table = self.ref("commutation", "age_factor_by_age_next_birthday")
        key = str(age_next_birthday)
        if key in table:
            return money(table[key])
        known = ", ".join(sorted(table, key=int))
        raise UnknownReferenceValue(
            f"{self.id}: no commutation factor for age next birthday {age_next_birthday}. "
            f"The loaded table is incomplete (BLOCKING-05) and holds only ages {known}. "
            "Interpolation is not permitted (COMM-04) - route to human determination."
        )

    def engages(self, *rule_ids: str) -> tuple[str, ...]:
        """The BLOCKING ids carried by the given rules, de-duplicated, in stable order.

        BRAIN §14.1 rule 2: "Name the item. Every affected output lists the BLOCKING IDs it
        engages." This is how a determination assembles that list from the rules it actually
        used, rather than from a hand-maintained constant that drifts.
        """
        seen: list[str] = []
        for rid in rule_ids:
            item = self.rules[rid].unverified if rid in self.rules else None
            if item and item not in seen:
                seen.append(item)
        return tuple(seen)


def _parse_pack(payload: dict[str, Any], source: Path) -> RulePack:
    try:
        rules = {
            rid: Rule(
                id=rid,
                description=body["description"],
                citation=body["citation"],
                unverified=body.get("unverified"),
            )
            for rid, body in payload["rules"].items()
        }
        eff_to = payload.get("effective_to")
        return RulePack(
            id=payload["id"],
            jurisdiction=payload["jurisdiction"],
            cohort=payload["cohort"],
            effective_from=date.fromisoformat(payload["effective_from"]),
            effective_to=date.fromisoformat(eff_to) if eff_to else None,
            rules=rules,
            reference_data=payload["reference_data"],
            unverified=tuple(payload.get("unverified", ())),
        )
    except KeyError as exc:
        raise PackError(f"{source.name}: missing required key {exc}") from exc


def load_all(pack_dir: Path | None = None) -> list[RulePack]:
    """Load every pack on disk. Order is by effective_from, then id, for determinism."""
    directory = pack_dir or PACK_DIR
    packs = []
    for path in sorted(directory.glob("*.json")):
        with path.open() as fh:
            payload = json.load(fh, parse_float=_refuse_float)
        packs.append(_parse_pack(payload, path))
    if not packs:
        raise PackError(f"no rule packs found in {directory}")
    return sorted(packs, key=lambda p: (p.effective_from, p.id))


def load_pack(pack_id: str, pack_dir: Path | None = None) -> RulePack:
    """Load one pack by id. Use when reproducing a determination that names its pack."""
    for pack in load_all(pack_dir):
        if pack.id == pack_id:
            return pack
    raise PackError(f"no rule pack with id {pack_id!r}")


def select_pack(
    effective_date: date,
    jurisdiction: str = "PUNJAB",
    cohort: str = "DEFINED_BENEFIT",
    pack_dir: Path | None = None,
) -> RulePack:
    """Select the pack in force on ``effective_date``. Requirement 4.

    ``effective_date`` is an argument, never ``date.today()``: the engine must produce the
    same answer for a 2021 case whenever it is run.
    """
    matches = [
        p
        for p in load_all(pack_dir)
        if p.jurisdiction == jurisdiction and p.cohort == cohort and p.covers(effective_date)
    ]
    if not matches:
        raise PackError(
            f"no {jurisdiction}/{cohort} rule pack in force on {effective_date.isoformat()}. "
            "A determination must never fall back to a pack from another period."
        )
    if len(matches) > 1:
        raise PackError(
            f"overlapping rule packs in force on {effective_date.isoformat()}: "
            f"{[p.id for p in matches]}. Effective ranges must not overlap."
        )
    return matches[0]
