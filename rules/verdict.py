"""Routing verdict. BRAIN §12.3, §6.1 invariant 5.

Four verdicts, evaluated in a fixed order. The order is the whole content of this module:
the golden case engages ``BLOCKING-06``, which on its own would be ``HOLD``, *and* carries
three HIGH flags, which is ``RETURN_FOR_CORRECTION`` -- and the expected verdict is the
latter. Correcting the department's three defects is actionable today; the gratuity ambiguity
is not resolvable by anyone in the loop and must not strand a case that has a real, fixable
shortcoming list waiting to go out.

The engine recommends. The officer decides, may override any verdict, and the override plus
its justification is logged. That is correct and expected use, not a failure of the model.
"""

from __future__ import annotations

from dataclasses import dataclass

from .checklist import COMPLETE, DEFECTIVE, Checklist, MISSING
from .flags import HIGH, Flag
from .types import Determination

FORWARD = "FORWARD"
RETURN_FOR_CORRECTION = "RETURN_FOR_CORRECTION"
HOLD = "HOLD"
ROUTE_MANUAL = "ROUTE_MANUAL"


@dataclass(frozen=True)
class Recommendation:
    verdict: str
    blocking_flags: tuple[str, ...]
    rationale: str
    human_decision_required: bool = True

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "blocking_flags": list(self.blocking_flags),
            "rationale": self.rationale,
            "human_decision_required": self.human_decision_required,
        }


def _determination_facts(determination) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The two things a verdict needs from a determination, from either shape it comes in.

    ``build_report`` holds the determination as the dict ``Determination.to_dict()``
    produced -- it is read back from ``determination.json`` or returned already serialised
    by the self-pension path -- while the tests and the engine hold the object. Accepting
    both is what lets the pipeline pass the determination it actually has instead of
    passing ``None``, which is how every HOLD verdict came to be unreachable in production.

    Returns ``(blocking ids of unresolved ambiguities, BLOCKING ids engaged)``.
    """
    if determination is None:
        return (), ()
    if isinstance(determination, dict):
        ambiguities = tuple(
            a["blocking_id"]
            for a in (determination.get("ambiguities") or ())
            if a.get("blocking_id")
        )
        return ambiguities, tuple(determination.get("unverified_rules_engaged") or ())
    return (
        tuple(a.blocking_id for a in determination.ambiguities),
        tuple(determination.unverified_engaged),
    )


def recommend(
    checklist: Checklist,
    flags: tuple[Flag, ...],
    determination: "Determination | dict | None" = None,
) -> Recommendation:
    """Derive the verdict from the checklist, the flags and the determination.

    Invariant 5: any ``blocks_ppo`` flag forces ``RETURN_FOR_CORRECTION`` or ``HOLD``, never
    ``FORWARD``. Because ``blocks_ppo`` is itself derived from HIGH severity, there is no way
    to present a HIGH flag and still recommend forwarding.
    """
    blocking = tuple(f.id for f in flags if f.blocks_ppo)
    bad_items = [i for i in checklist.items if i.status in (MISSING, DEFECTIVE)]
    ambiguous_items, engaged_items = _determination_facts(determination)

    if blocking or bad_items:
        reasons = []
        if checklist.result == COMPLETE:
            reasons.append(f"Checklist complete ({checklist.satisfied}/{checklist.required})")
        else:
            reasons.append(f"{checklist.missing} checklist item(s) missing")
        if bad_items:
            defective = [i.id for i in bad_items if i.status == DEFECTIVE]
            if defective:
                reasons.append(f"defective: {', '.join(defective)}")
        if blocking:
            reasons.append(
                f"{len(blocking)} HIGH flag(s) must be corrected before PPO: "
                f"{', '.join(blocking)}"
            )
        if determination is not None and not bad_items:
            reasons.append("pension otherwise fully calculable")
        return Recommendation(
            verdict=RETURN_FOR_CORRECTION,
            blocking_flags=blocking,
            rationale=". ".join(reasons) + ".",
        )

    if ambiguous_items:
        items = ", ".join(sorted(set(ambiguous_items)))
        return Recommendation(
            verdict=HOLD,
            blocking_flags=(),
            rationale=(
                f"No checklist or consistency defect, but the determination engages "
                f"unresolved rule ambiguities material to this case ({items}). "
                "Exceptional-case lane, human determination."
            ),
        )

    if engaged_items:
        items = ", ".join(engaged_items)
        return Recommendation(
            verdict=HOLD,
            blocking_flags=(),
            rationale=(
                f"No defect found, but the determination engages open BLOCKING items "
                f"({items}) and is therefore provisional."
            ),
        )

    return Recommendation(
        verdict=FORWARD,
        blocking_flags=(),
        rationale=(
            f"Checklist complete ({checklist.satisfied}/{checklist.required}); no HIGH flag; "
            "no unresolved rule item engaged. Figures pre-filled for officer confirmation."
        ),
    )
