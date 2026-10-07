"""What this release shows of the rules engine: checks, never computed amounts.

Business decision of 7 October 2026: this release does no pension calculations. The system
parses, checks and reviews the documents of a case. The engine may still run internally --
its date checks, its rule-pack selection, the provisional/BLOCKING items it engages and the
inputs it read are checks the officer needs -- but no computed figure (monthly pension, gross or
net pension, commutation, gratuity, a family-pension share, qualifying service as a payable
figure, the reckonable or excluded emoluments totals) is stored in the case report, served by
the API or shown on a screen.

``scrub_report`` is applied where the report is BUILT (pipeline.report) and again where it is
SERVED (api.artefacts, the old register's routes), so a report written before this decision
leaves the server scrubbed too. Values a document itself states -- a pay line as printed, the
form's own printed total, the pension in payment a PPO prints -- are readings, not
calculations, and stay.
"""
from __future__ import annotations

from typing import Any

#: The release scope. Flipping this does nothing by itself; it names the decision in one place
#: and lets a later release that computes find every site that honours it.
CALCULATIONS_IN_SCOPE = False

#: Determination step fields that are a computed figure or its working.
_STEP_COMPUTED = ("amount", "computation_shown", "unit")
#: Emoluments fields the engine computes (the components themselves are read off documents).
_EMOLUMENTS_COMPUTED = ("reckonable_total", "excluded_total", "reconciled")
#: The pension-rule classification of a pay line (reckonable for pension or not).
_COMPONENT_COMPUTED = ("reckonable",)


def scrub_determination(det: dict[str, Any] | None) -> dict[str, Any] | None:
    """The determination as a record of checks: which rules ran, what was provisional, what was
    read -- with every computed figure and its working removed."""
    if not det:
        return det
    out = dict(det)
    out["steps"] = [{k: v for k, v in s.items() if k not in _STEP_COMPUTED} for s in det.get("steps", [])]
    out["ambiguities"] = [
        {**{k: v for k, v in a.items() if k not in ("difference",)},
         "readings": [{k: v for k, v in r.items() if k not in ("amount", "computation_shown")}
                      for r in a.get("readings", [])]}
        for a in det.get("ambiguities", [])
    ]
    out["calculations"] = "not in this release"
    return out


def scrub_emoluments(emol: dict[str, Any] | None) -> dict[str, Any] | None:
    """The pay lines as the documents print them, with the engine's totals and its
    reckonable/excluded classification removed."""
    if not emol:
        return emol
    out = {k: v for k, v in emol.items() if k not in _EMOLUMENTS_COMPUTED}
    out["components"] = [{k: v for k, v in c.items() if k not in _COMPONENT_COMPUTED}
                         for c in emol.get("components", [])]
    return out


def scrub_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """A case report with no computed amount in it. Idempotent; safe on reports written
    before 7 Oct 2026 and on the checklist-applied copy alike."""
    if not report:
        return report
    out = dict(report)
    if "determination" in out:
        out["determination"] = scrub_determination(out.get("determination"))
    if "emoluments" in out:
        out["emoluments"] = scrub_emoluments(out.get("emoluments"))
    out["calculations_in_scope"] = CALCULATIONS_IN_SCOPE
    return out


def has_computed_amount(report: dict[str, Any] | None) -> list[str]:
    """Paths in a report that still carry a computed figure; empty when clean. For tests and
    for the release check."""
    found: list[str] = []
    det = (report or {}).get("determination") or {}
    for i, s in enumerate(det.get("steps", [])):
        for k in _STEP_COMPUTED:
            if k in s:
                found.append(f"determination.steps[{i}].{k}")
    for i, a in enumerate(det.get("ambiguities", [])):
        if "difference" in a:
            found.append(f"determination.ambiguities[{i}].difference")
        for j, r in enumerate(a.get("readings", [])):
            for k in ("amount", "computation_shown"):
                if k in r:
                    found.append(f"determination.ambiguities[{i}].readings[{j}].{k}")
    emol = (report or {}).get("emoluments") or {}
    for k in _EMOLUMENTS_COMPUTED:
        if k in emol:
            found.append(f"emoluments.{k}")
    for i, c in enumerate(emol.get("components", [])):
        for k in _COMPONENT_COMPUTED:
            if k in c:
                found.append(f"emoluments.components[{i}].{k}")
    return found
