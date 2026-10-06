"""The periodic statement the DAG (Pension) places before the Accountant General. SOP §8.4.

Pure aggregation over the run directories: the case report each run produced and the
append-only decision log beside it. Nothing here decides anything; it counts what the
office decided and says why the engine could not compute where it could not. Standard
library only, so it is testable without the web server and reproducible from the artefacts
alone (SOP §8.5).

What the SOP asks the statement to show, and where each figure comes from:

*   cases disposed of, returned and held  -- the decision in force on each case
    (``api.decisions.current_decision``), with undecided cases shown separately because a
    case nobody has decided is not a disposed case;
*   the number of overrides and the grounds  -- every decision entry with
    ``overrides_recommendation`` true, with its grounds and justification;
*   the cases that could not be determined and the reason in each class  -- every case
    report whose ``determination`` is null, grouped by case type, with the engine's own
    stated reason (``determination_gap``).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from api.decisions import current_decision, decisions_for

UNDECIDED = "UNDECIDED"


def _report(run_dir: Path) -> dict | None:
    path = run_dir / "case_report.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def disposal_statement(run_dirs: Iterable[Path]) -> dict:
    """SOP §8.4: disposed / returned / held, overrides with grounds, undetermined with reasons."""
    by_decision: Counter = Counter()
    by_verdict: Counter = Counter()
    overrides: list[dict] = []
    undetermined: dict[str, list[dict]] = defaultdict(list)
    cases: list[dict] = []
    for run_dir in sorted(run_dirs):
        report = _report(run_dir)
        if report is None:
            continue
        run_id = report.get("case_ref") or run_dir.name
        decision = current_decision(run_dir)
        action = (decision or {}).get("action") or UNDECIDED
        verdict = (report.get("recommendation") or {}).get("verdict") or "NO_RECOMMENDATION"
        by_decision[action] += 1
        by_verdict[verdict] += 1
        case_type = (report.get("case_type") or {}).get("case_type") or "UNCLASSIFIED"
        cases.append({
            "run_id": run_id,
            "case_type": case_type,
            "case_variant": report.get("case_variant"),
            "claimant_name": report.get("claimant_name"),
            "recommended": verdict,
            "decision": action,
            "decided_by": (decision or {}).get("officer"),
            "desk": (decision or {}).get("role"),
            "decided_at": (decision or {}).get("at"),
        })
        for entry in decisions_for(run_dir):
            if entry.get("overrides_recommendation"):
                overrides.append({
                    "run_id": run_id,
                    "officer": entry.get("officer"),
                    "desk": entry.get("role"),
                    "at": entry.get("at"),
                    "recommended": entry.get("recommended_verdict"),
                    "grounds": entry.get("override_grounds"),
                    "justification": entry.get("justification"),
                })
        if not report.get("determination"):
            gap = report.get("determination_gap") or {}
            reason = (gap.get("determine") or gap.get("extract")
                      or report.get("checklist_gap") or report.get("rule_pack_gap")
                      or ((report.get("case_type") or {}).get("case_type_evidence")
                          if not (report.get("case_type") or {}).get("case_type") else None)
                      or "no reason recorded")
            if report.get("awaiting_pay_figures"):
                reason = "awaiting the three annual basic pay figures at intake (SOP §5.8)"
            undetermined[case_type].append({"run_id": run_id, "reason": reason})
    return {
        "sop": "§8.4 periodic statement",
        "cases": len(cases),
        "by_decision": {
            "FORWARD": by_decision.get("FORWARD", 0),
            "RETURN_FOR_CORRECTION": by_decision.get("RETURN_FOR_CORRECTION", 0),
            "HOLD": by_decision.get("HOLD", 0),
            UNDECIDED: by_decision.get(UNDECIDED, 0),
        },
        "by_recommendation": dict(by_verdict),
        "overrides": {"count": len(overrides), "entries": overrides},
        "undetermined": {
            "count": sum(len(v) for v in undetermined.values()),
            "by_class": {k: v for k, v in sorted(undetermined.items())},
        },
        "case_list": cases,
    }
