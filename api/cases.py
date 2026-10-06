"""The case register: every case the office has seen, and where each one stands. SOP §4.2.

``GET /api/runs`` lists the in-memory registry, which is empty the moment the server is
restarted. That is fine for watching a run in progress and useless as a record: the SOP asks
the Accounts Office to monitor cases "for proper disposal" and to keep the status updated in
the module, and a register that forgets yesterday cannot do either.

So this reads the artefacts on disk. A case exists because its run directory exists; its
status comes from the report and the decision log inside it, both of which outlive the
process. Live runs are merged in on top, because a case being read right now is also a case
the officer wants to see.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: What the register shows for a case, in the order a case moves through them.
RUNNING = "RUNNING"                     # the pipeline is reading it now
FAILED = "FAILED"                       # the pipeline stopped on an error
AWAITING_REVIEW = "AWAITING_REVIEW"     # read, reported, nobody has decided yet
APPROVED = "APPROVED"                   # §4.2 approved and forwarded
RETURNED = "RETURNED"                   # §4.1 sent back for removal of shortcomings
ON_HOLD = "ON_HOLD"                     # §6.2 exceptional-case lane

_STATUS_FOR_ACTION = {
    "FORWARD": APPROVED,
    "RETURN_FOR_CORRECTION": RETURNED,
    "HOLD": ON_HOLD,
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


#: Written by ``POST /api/runs/{id}/remove`` -- the register's "×". The case is taken off the
#: lists and nothing else: its files, report and decisions stay where they are.
REMOVED = "removed.json"


def is_removed(run_dir: Path, live: dict | None = None) -> bool:
    """Taken off the register, and not brought back since.

    A case being read right now is always shown. A case read again after it was removed (the
    same papers uploaded or pulled again) writes a newer report, and that brings it back: the
    office took it up again, so it is on the register again.
    """
    marker = run_dir / REMOVED
    if not marker.exists():
        return False
    if live and live.get("state") in ("queued", "running"):
        return False
    report = run_dir / "case_report.json"
    try:
        return not report.exists() or marker.stat().st_mtime >= report.stat().st_mtime
    except OSError:
        return False


def _decisions(run_dir: Path) -> list[dict]:
    path = run_dir / "decisions.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def summarise(run_dir: Path, live: dict | None = None) -> dict | None:
    """One row of the register. ``None`` where the directory holds no case at all."""
    run_id = run_dir.name.removeprefix("run-")
    report = _read_json(run_dir / "case_report.json")
    if report:
        # The checklist as the officer has settled it (api.checklist_actions), not only as read.
        from api.checklist_actions import apply
        report = apply(report, run_dir)
    if report is None and live is None:
        return None

    report = report or {}
    checklist = report.get("checklist") or {}
    rec = report.get("recommendation") or {}
    flags = report.get("flags") or []
    history = _decisions(run_dir)
    latest = history[-1] if history else None

    # A live run's state wins while it is running: the report on disk is the previous one.
    if live and live.get("state") in ("queued", "running"):
        status = RUNNING
    elif live and live.get("state") == "failed":
        status = FAILED
    elif latest:
        status = _STATUS_FOR_ACTION.get(latest.get("action", ""), AWAITING_REVIEW)
    elif report:
        status = AWAITING_REVIEW
    else:
        status = RUNNING

    source = report.get("source") or {}
    # The claimant is the name an officer looks for; the file name is what they uploaded.
    # Both are shown because a bundle whose claimant could not be read still has to be
    # findable, and "— not read —" in a list is a finding in itself.
    return {
        "run_id": run_id,
        "status": status,
        "file": source.get("file") or (live or {}).get("file") or "",
        "pages": source.get("source_pages"),
        "claimant": report.get("claimant_name"),
        "case_type": (report.get("case_type") or {}).get("case_type"),
        "case_variant": report.get("case_variant"),
        "checklist_result": checklist.get("result"),
        "checklist_satisfied": checklist.get("satisfied"),
        "checklist_required": checklist.get("required"),
        "flags": len(flags),
        "blocking_flags": sum(1 for f in flags if f.get("blocks_ppo")),
        "recommended_verdict": rec.get("verdict"),
        "decision": latest.get("action") if latest else None,
        "decided_by": latest.get("officer") if latest else None,
        "decided_role": latest.get("role") if latest else None,
        "decided_at": latest.get("at") if latest else None,
        "decisions": len(history),
        "started_at": (live or {}).get("started_at") or "",
        # Cheap, and the only ordering that means anything across restarts.
        "updated_at": _mtime(run_dir),
        "error": (live or {}).get("error"),
    }


def _mtime(run_dir: Path) -> float:
    newest = 0.0
    for name in ("decisions.jsonl", "case_report.json", "manifest.json"):
        p = run_dir / name
        if p.exists():
            newest = max(newest, p.stat().st_mtime)
    return newest or run_dir.stat().st_mtime


def register(artifacts: Path, live_runs: dict | None = None) -> list[dict]:
    """Every case on disk, newest first, with live runs merged over the top."""
    live_runs = live_runs or {}
    rows: list[dict] = []
    for run_dir in sorted(artifacts.glob("run-*")):
        if not run_dir.is_dir():
            continue
        live = live_runs.get(run_dir.name.removeprefix("run-"))
        if is_removed(run_dir, live):
            continue
        row = summarise(run_dir, live)
        if row:
            rows.append(row)
    # A live run whose directory has not been created yet still belongs in the list.
    known = {r["run_id"] for r in rows}
    for run_id, live in live_runs.items():
        if run_id not in known and not is_removed(artifacts / f"run-{run_id}", live):
            rows.append({
                "run_id": run_id, "status": RUNNING, "file": live.get("file") or "",
                "pages": None, "claimant": None, "case_type": None, "case_variant": None,
                "checklist_result": None, "checklist_satisfied": None,
                "checklist_required": None, "flags": 0, "blocking_flags": 0,
                "recommended_verdict": None, "decision": None, "decided_by": None,
                "decided_role": None, "decided_at": None, "decisions": 0,
                "started_at": live.get("started_at") or "", "updated_at": 0.0,
                "error": live.get("error"),
            })
    rows.sort(key=lambda r: (r["updated_at"], r["started_at"]), reverse=True)
    return rows
