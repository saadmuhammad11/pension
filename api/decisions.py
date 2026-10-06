"""The officer's decision on a case, and the audit trail behind it. SOP §6.4.

The engine produces a recommendation; a person decides. This module records what they decided,
against what the system was showing them at the time.

Three properties are deliberate:

*   **Append-only.** Every decision is written to ``decisions.jsonl`` and nothing is ever
    rewritten or removed. A case that was forwarded, returned, then forwarded again has three
    entries, in order. SOP §6.4 requires the module to "keep logs of each entry", and a log
    that can be edited is not a log.

*   **The recommendation is captured with the decision.** An audit two years later has to answer
    "what did the officer see when they signed this", and the report on disk by then may have
    been rebuilt against a newer rule pack. So the verdict, the blocking flags and the checklist
    result are copied into the record rather than referenced.

*   **Overriding a block requires a written reason, enforced here.** ``rules.verdict`` guarantees
    no HIGH flag can ever yield a FORWARD recommendation; this is the other half of that rule --
    a person may still forward such a case, but not silently. The UI asks for a justification;
    the UI is not what enforces it.

There is no authentication in this build, so ``officer`` and ``role`` are self-asserted. They
are recorded as claims, not as an identity, and that distinction belongs in whatever fronts this
later. The portal asks for both at sign-in and restricts nothing on the answer: the point is
that the log names a person and a desk instead of a constant compiled into the frontend.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DECISIONS_LOG = "decisions.jsonl"

#: What an officer may decide. FORWARD sends the case on to the AG determination queue;
#: RETURN_FOR_CORRECTION goes back to the department with the shortcoming list; HOLD parks it
#: in the exceptional-case lane (SOP §6.2) without either advancing or rejecting it.
ACTIONS = ("FORWARD", "RETURN_FOR_CORRECTION", "HOLD")

#: Long enough to say why, short enough not to be a wall. A one-word justification on an
#: override is the same as no justification.
MIN_JUSTIFICATION = 15


class DecisionError(ValueError):
    """The decision was not recordable. Never written to the log."""


def _blocked(report: dict) -> tuple[bool, str]:
    """Does the case, as reported, stand against being forwarded? And on what grounds."""
    rec = report.get("recommendation") or {}
    checklist = report.get("checklist") or {}
    reasons: list[str] = []
    blocking = list(rec.get("blocking_flags") or [])
    if blocking:
        reasons.append(f"blocking flags {', '.join(blocking)}")
    missing = int(checklist.get("missing") or 0)
    if missing:
        reasons.append(f"{missing} checklist item(s) missing")
    if (checklist.get("result") or "") == "INCOMPLETE" and not missing:
        reasons.append("checklist incomplete")
    # The engine's verdict is the authority on whether a case is forwardable, and deriving
    # that again from two fields disagreed with it three ways: a case that reached no
    # determination at all read as clean, so did a HOLD, and so did a RETURN_FOR_CORRECTION
    # whose items are DEFECTIVE rather than MISSING -- Checklist.result stays COMPLETE for a
    # defect by design. Anything the engine did not recommend forwarding is an override, and
    # §9.7 requires an override to carry a reason.
    verdict = rec.get("verdict")
    if verdict and verdict != "FORWARD":
        reasons.append(f"the engine recommends {verdict}")
    elif not rec and report:
        # A report with no recommendation is a case that routed to human before reaching a
        # determination. Nothing was checked, so nothing can vouch for it. The empty-report
        # case is left alone: that is a caller supplying no report, not an undetermined one.
        reasons.append("the case reached no determination; nothing was verified to forward on")
    return bool(reasons), "; ".join(reasons)


def record_decision(
    run_dir: str | Path,
    *,
    run_id: str,
    action: str,
    officer: str,
    role: str = "",
    justification: str = "",
    report: dict | None = None,
) -> dict:
    """Append one officer decision to the case's audit log, and return it.

    Raises :class:`DecisionError` rather than recording anything doubtful.
    """
    if action not in ACTIONS:
        raise DecisionError(f"unknown action {action!r}; expected one of {list(ACTIONS)}")
    officer = (officer or "").strip()
    if not officer:
        raise DecisionError("the deciding officer must be named; a decision has an author")
    # Unlike the name, the desk is not required: an entry written by a caller that has no
    # notion of desks is still a decision, and refusing it would lose the decision to gain a
    # label. Absent is recorded as absent rather than guessed at.
    role = (role or "").strip()

    report = report or {}
    blocked, grounds = _blocked(report)
    justification = (justification or "").strip()
    overrides = bool(action == "FORWARD" and blocked)

    if overrides and len(justification) < MIN_JUSTIFICATION:
        raise DecisionError(
            f"forwarding this case overrides the recommendation ({grounds}), so a written "
            f"justification of at least {MIN_JUSTIFICATION} characters is required. The "
            f"engine cannot recommend forwarding a case with a HIGH flag, and a person "
            f"overriding that must record why."
        )

    rec = report.get("recommendation") or {}
    checklist = report.get("checklist") or {}
    entry = {
        "run_id": run_id,
        "action": action,
        "officer": officer,
        "role": role,
        "justification": justification,
        "at": datetime.now().isoformat(timespec="seconds"),
        # What the officer was looking at. Copied, not referenced -- see the module docstring.
        "overrides_recommendation": overrides,
        "override_grounds": grounds if overrides else "",
        "recommended_verdict": rec.get("verdict"),
        "blocking_flags": list(rec.get("blocking_flags") or []),
        "checklist_result": checklist.get("result"),
        "checklist_satisfied": checklist.get("satisfied"),
        "checklist_required": checklist.get("required"),
        "case_variant": report.get("case_variant"),
    }

    path = Path(run_dir) / DECISIONS_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def decisions_for(run_dir: str | Path) -> list[dict]:
    """Every decision recorded on this case, oldest first. Empty where none has been made."""
    path = Path(run_dir) / DECISIONS_LOG
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            # A corrupt line is reported, not skipped in silence: this is an audit log, and
            # a reader must be able to see that part of it could not be read.
            out.append({"unreadable": line[:200]})
    return out


def current_decision(run_dir: str | Path) -> dict | None:
    """The decision in force -- the most recent one, or ``None`` if the case is undecided."""
    history = decisions_for(run_dir)
    return history[-1] if history else None
