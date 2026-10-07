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

import re
from typing import Any

#: The release scope. Flipping this does nothing by itself; it names the decision in one place
#: and lets a later release that computes find every site that honours it.
CALCULATIONS_IN_SCOPE = False

#: Determination step fields that are a computed figure or its working. ``exact_before_rounding``
#: is the figure to the paisa (audit of 7 Oct 2026: it survived the first scrub).
_STEP_COMPUTED = ("amount", "computation_shown", "unit", "exact_before_rounding", "rounding")
#: Emoluments fields the engine computes (the components themselves are read off documents).
_EMOLUMENTS_COMPUTED = ("reckonable_total", "excluded_total", "reconciled")
#: The pension-rule classification of a pay line (reckonable for pension or not).
_COMPONENT_COMPUTED = ("reckonable",)
#: Determination inputs that are themselves sums the engine made (the rest are dates, grades and
#: figures read off the documents or keyed by the officer).
_INPUTS_COMPUTED = ("reckonable_emoluments", "excluded_allowances", "pension_base")

#: Money in prose: "Rs. 192,030", "Rs 750", a comma-grouped figure, or a bare run of five digits or
#: more (a year is four). Engine notes and refusal texts carry sums in words; this takes them out
#: where the text itself must be kept (which rule ran, why it refused).
_MONEY = re.compile(r"Rs\.?\s*[\d,]+(?:\.\d+)?"                                  # Rs. 90,280 / Rs 750.50
                    r"|(?<![\d.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)(?!\.\d)"       # 161,765 / 1,234.50
                    r"|(?<![\d.\-/])\d{5,}(?:\.\d+)?(?![\d\-/])(?!\.\d)")          # 161765 (a bare run; a year is four digits)
WITHHELD = "[amount withheld]"


def strip_money(text: str | None) -> str | None:
    """The text with every rupee figure replaced by ``[amount withheld]``. Dates, rule ids and
    page numbers survive; a figure the engine summed does not."""
    if not text:
        return text
    return _MONEY.sub(WITHHELD, str(text))


def scrub_determination(det: dict[str, Any] | None) -> dict[str, Any] | None:
    """The determination as a record of checks: which rules ran, what was provisional, what was
    read -- with every computed figure and its working removed."""
    if not det:
        return det
    out = dict(det)
    out["steps"] = [{**{k: v for k, v in s.items() if k not in _STEP_COMPUTED},
                     **({"note": strip_money(s["note"])} if s.get("note") else {})}
                    for s in det.get("steps", [])]
    out["ambiguities"] = [
        {**{k: v for k, v in a.items() if k not in ("difference",)},
         "readings": [{k: v for k, v in r.items() if k not in ("amount", "computation_shown")}
                      for r in a.get("readings", [])]}
        for a in det.get("ambiguities", [])
    ]
    out["inputs"] = {k: v for k, v in (det.get("inputs") or {}).items() if k not in _INPUTS_COMPUTED}
    out["caveats"] = [strip_money(c) for c in det.get("caveats", [])]
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
    # The engine's refusal and the stage's gap quote its arithmetic ("components sum to Rs ...").
    for key in ("self_pension_error",):
        if out.get(key):
            out[key] = strip_money(out[key])
    if isinstance(out.get("determination_gap"), dict):
        out["determination_gap"] = {k: strip_money(v) if isinstance(v, str) else v for k, v in out["determination_gap"].items()}
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
    for k in _INPUTS_COMPUTED:
        if k in (det.get("inputs") or {}):
            found.append(f"determination.inputs.{k}")
    for i, s in enumerate(det.get("steps", [])):
        if s.get("note") and _MONEY.search(str(s["note"])):
            found.append(f"determination.steps[{i}].note(money)")
    for i, c in enumerate(det.get("caveats", [])):
        if _MONEY.search(str(c)):
            found.append(f"determination.caveats[{i}](money)")
    if (report or {}).get("self_pension_error") and _MONEY.search(str(report["self_pension_error"])):
        found.append("self_pension_error(money)")
    emol = (report or {}).get("emoluments") or {}
    for k in _EMOLUMENTS_COMPUTED:
        if k in emol:
            found.append(f"emoluments.{k}")
    for i, c in enumerate(emol.get("components", [])):
        for k in _COMPONENT_COMPUTED:
            if k in c:
                found.append(f"emoluments.components[{i}].{k}")
    return found
