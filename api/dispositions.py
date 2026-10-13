"""An officer's decision on ONE finding, and the gate that decision opens. SOP §6.4.

A case report raises findings; the engine will not compute a pension while any of them is
open. That is the office's rule, not the engine's preference: a determination shown beside
an unresolved contradiction is a figure somebody may act on, and the contradiction is
exactly the reason it might be wrong.

So each finding is disposed of individually, and the calculation is gated on all of them
being disposed and the checklist being complete. Three dispositions:

*   ``UPHOLD``  -- the finding stands. The case cannot proceed; the department must correct it.
*   ``WAIVE``   -- the officer is satisfied the finding does not prevent payment. A ground
                   and an authority are required, because waiving a HIGH finding is the one
                   act here that lets money move past a check that was designed to stop it.
*   ``HOLD``    -- parked for the exceptional-case lane. Neither cleared nor upheld.

Append-only, like ``api.decisions``: a finding waived, then upheld on second thoughts, has
two entries and the order is the record. Nothing is rewritten.

**Tied to the exact finding** (business decision H8, 7 Oct 2026). A disposition is recorded
against the finding's fingerprint -- its rule, the documents it cites, and the title and
finding text that carry the field and the value (``rules.flags.finding_fingerprint``) -- not
against its running number, which a recompute or a resubmission reassigns. ``in_force`` applies
a disposition to whichever finding now carries that fingerprint; a disposition whose finding
has changed or disappeared is ``lapsed``: it stays on the record, and the finding (if still
raised) is open again for a fresh decision. Dispositions written before 7 Oct 2026 carry no
fingerprint and are honoured only while the finding under their number still has the same title.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rules.flags import finding_fingerprint

DISPOSITIONS_LOG = "flag_dispositions.jsonl"

#: What an officer may decide about one finding.
ACTIONS = ("UPHOLD", "WAIVE", "HOLD")

#: Dispositions that CLEAR a finding out of the way of a determination. Upholding does not:
#: an upheld finding is one the officer agrees with, and agreeing that a case is defective
#: is not a reason to compute its pension.
CLEARING = ("WAIVE",)

#: Long enough to say why. The same threshold the case-level override uses, for the same
#: reason: a one-word ground on a waiver is the same as no ground.
#: Characters of reason every disposition carries. Ten, and one box: the officer approves or
#: rejects the finding and says why, and nothing else is asked (13 Oct 2026). Both decisions are
#: recorded against the officer's own name, so both are given a reason -- until then only a
#: waiver was.
MIN_GROUND = 10


class DispositionError(ValueError):
    """The disposition was not recordable. Never written to the log."""


def record(
    run_dir: str | Path,
    *,
    run_id: str,
    flag_id: str,
    action: str,
    officer: str,
    role: str,
    ground: str = "",
    flag: dict | None = None,
) -> dict:
    """Record one officer's disposition of one finding, or raise."""
    from api.roles import RoleError, require

    if action not in ACTIONS:
        raise DispositionError(f"unknown action {action!r}; expected one of {list(ACTIONS)}")
    officer = (officer or "").strip()
    if not officer:
        raise DispositionError("the deciding officer must be named; a disposition has an author")
    try:
        require(role or None, "decide_case")
    except RoleError as exc:
        raise DispositionError(str(exc)) from None

    ground = (ground or "").strip()
    flag = flag or {}
    if len(ground) < MIN_GROUND:
        what = ("approving" if action == "WAIVE" else "rejecting" if action == "UPHOLD" else "holding")
        raise DispositionError(
            f"{what} {flag_id}"
            + (f" — {flag.get('title')}" if flag.get("title") else "")
            + f" needs a reason of at least {MIN_GROUND} characters, and it is recorded "
            f"against your name."
        )

    entry = {
        "run_id": run_id,
        "flag_id": flag_id,
        "action": action,
        "officer": officer,
        "role": role,
        "ground": ground,
        "at": datetime.now().isoformat(timespec="seconds"),
        # What the officer was looking at when they decided. Copied, not referenced: the
        # report is rebuilt whenever the case is re-read, and an audit two years from now
        # has to answer "what did this finding say when it was waived".
        "flag_severity": flag.get("severity"),
        "flag_class": flag.get("class"),
        "flag_title": flag.get("title"),
        "flag_finding": flag.get("finding"),
        "flag_documents": sorted({str(e.get("doc") or "") for side in ("asserted", "contradicted_by")
                                  for e in (flag.get("evidence") or {}).get(side) or []}),
        "blocks_ppo": flag.get("blocks_ppo"),
        # The exact finding this decision is about (H8). Computed here when the report predates
        # the key, so every new disposition is tied, whatever report it was made on.
        "fingerprint": flag.get("fingerprint") or (finding_fingerprint(flag) if flag else None),
    }
    path = Path(run_dir) / DISPOSITIONS_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def history(run_dir: str | Path) -> list[dict]:
    """Every disposition recorded on this case, oldest first."""
    path = Path(run_dir) / DISPOSITIONS_LOG
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"unreadable": line[:200]})
    return out


def current(run_dir: str | Path) -> dict[str, dict]:
    """The disposition in force for each finding -- the LAST one recorded for it."""
    out: dict[str, dict] = {}
    for e in history(run_dir):
        if e.get("flag_id"):
            out[e["flag_id"]] = e
    return out


def _fingerprint_of(flag: dict) -> str:
    return flag.get("fingerprint") or finding_fingerprint(flag)


def in_force(report: dict, run_dir: str | Path) -> dict[str, dict]:
    """The disposition that applies to each finding the report raises NOW, keyed by the
    finding's current id. A disposition follows its finding's fingerprint, whatever number the
    finding carries today; a legacy entry (no fingerprint) follows its number while the title
    under that number is unchanged."""
    latest_by_fp: dict[str, dict] = {}
    legacy_by_id: dict[str, dict] = {}
    for e in history(run_dir):
        if not e.get("flag_id"):
            continue
        if e.get("fingerprint"):
            latest_by_fp[e["fingerprint"]] = e
        else:
            legacy_by_id[e["flag_id"]] = e
    out: dict[str, dict] = {}
    for f in report.get("flags") or []:
        fid = f.get("id")
        hit = latest_by_fp.get(_fingerprint_of(f))
        if hit is None:
            old = legacy_by_id.get(fid)
            if old is not None and (old.get("flag_title") or "") == (f.get("title") or ""):
                hit = old
        if hit is not None:
            out[fid] = {**hit, "applies_to": fid}
    return out


def lapsed(report: dict, run_dir: str | Path) -> list[dict]:
    """Dispositions whose finding has changed or disappeared since they were recorded: the
    latest per original finding, each with why it no longer applies. Kept for the record;
    the finding they were about, if still raised, is open again."""
    flags = report.get("flags") or []
    now_fps = {_fingerprint_of(f) for f in flags}
    titles_by_id = {f.get("id"): f.get("title") for f in flags}
    latest: dict[str, dict] = {}
    for e in history(run_dir):
        if e.get("flag_id"):
            latest[e.get("fingerprint") or f"id:{e['flag_id']}"] = e
    out = []
    for key, e in latest.items():
        if e.get("fingerprint"):
            if e["fingerprint"] in now_fps:
                continue
            why = ("the finding it was given against is no longer raised"
                   if not any((f.get("class") == e.get("flag_class")) for f in flags)
                   else "the finding has changed since the decision (its figures, dates, names or documents differ)")
        else:
            if titles_by_id.get(e["flag_id"]) == (e.get("flag_title") or ""):
                continue
            why = "the finding under that number is not the one the decision was about"
        out.append({"flag_id": e.get("flag_id"), "action": e.get("action"), "officer": e.get("officer"),
                    "at": e.get("at"), "flag_title": e.get("flag_title"), "ground": e.get("ground"), "why": why})
    return out


def calculation_gate(report: dict, run_dir: str | Path) -> dict:
    """May the pension be calculated on this case yet, and if not, what is in the way?

    Two conditions, both the office's:

    *   Every finding is disposed of, and disposed of in a way that clears it. An upheld
        finding is one the officer AGREES with, so it blocks; a waived one has been
        considered and set aside on a recorded ground.
    *   The checklist has nothing missing. A pension computed on a bundle that is missing
        papers is computed on what happens to have been filed.

    Returns the gate rather than enforcing it, so the report can say plainly what is
    outstanding instead of presenting an empty Calculation tab with no reason.
    """
    disposed = in_force(report, run_dir)
    flags = report.get("flags") or []
    checklist = report.get("checklist") or {}
    gone = lapsed(report, run_dir)

    open_flags = [
        {"id": f["id"], "severity": f.get("severity"), "title": f.get("title"),
         "disposition": (disposed.get(f["id"]) or {}).get("action")}
        for f in flags
        if (disposed.get(f["id"]) or {}).get("action") not in CLEARING
    ]
    missing = int(checklist.get("missing") or 0)

    return {
        "open": not open_flags and not missing,
        "flags_total": len(flags),
        "flags_cleared": len(flags) - len(open_flags),
        "open_flags": open_flags,
        "checklist_missing": missing,
        # Decisions that no longer apply because their finding changed or went (H8): on the
        # record, and shown, so the officer knows a fresh decision is wanted.
        "lapsed": gone,
        "reason": (
            None if not open_flags and not missing else
            "; ".join(filter(None, [
                (f"{len(open_flags)} finding(s) not yet cleared: "
                 + ", ".join(f["id"] for f in open_flags)) if open_flags else None,
                f"{missing} checklist item(s) missing" if missing else None,
                (f"{len(gone)} earlier decision(s) lapsed because the finding changed") if gone else None,
            ]))
        ),
    }
