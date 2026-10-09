"""Cases run on the old single-case portal, brought into the case system once.

Before 25 Sep 2026 the AI Pension Portal had no departments and no users: a case was a run
directory under ``artifacts/run-<id>/`` with a report and, where an officer decided, a
``decisions.jsonl``. Those cases are still real work the office did, so they appear in the new
portal under one department, "Legacy — AI Pension Portal", visible to AG reviewers and the
administrator, with their reports and decisions intact.

Idempotent: a run already linked to a case is skipped, so this can run at every start-up. A
run taken off the old register (``removed.json``) is not imported. Runs the new portal itself
started (``source.kind == "portal_v2"``) are its own and are skipped too.
"""
from __future__ import annotations

import json
from pathlib import Path

from api import db, workflow
from api.departments import LEGACY_DEPARTMENT

#: The account legacy cases are recorded under. Inactive: nobody signs in as it.
IMPORT_USER = ("legacy.import", "AI Pension Portal (imported cases)", "DEPT_OFFICER")

_STATUS_FOR_DECISION = {
    "FORWARD": workflow.APPROVED,
    "RETURN_FOR_CORRECTION": workflow.RETURNED,
    "HOLD": workflow.UNDER_REVIEW,
}
_ACTION_FOR_DECISION = {"FORWARD": "APPROVE", "RETURN_FOR_CORRECTION": "RETURN", "HOLD": "TAKE_UP"}


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _decisions(run_dir: Path) -> list[dict]:
    path = run_dir / "decisions.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


class _Actor:
    """A named officer from an old decision, for the history row."""

    def __init__(self, name: str, role: str, uid: str | None) -> None:
        self.display_name, self.role, self.id, self.department_code = name, role, uid, None


def _office_type(summary: dict) -> str | None:
    from rules.case_type import canonical_office_type, office_type_for
    declared = canonical_office_type(summary.get("declared_case_type"))
    return declared or office_type_for(summary.get("case_type"), summary.get("case_variant"))


def import_legacy_runs(conn: db.Connection | None = None, artifacts: Path | None = None) -> int:
    """Import every finished old run not yet on a case. Returns how many were imported."""
    from api.runs import ARTIFACTS, _report_summary
    own = conn is None
    conn = conn or db.connect()
    root = artifacts or ARTIFACTS
    try:
        code, name, digital = LEGACY_DEPARTMENT
        with db.transaction(conn):
            conn.execute("INSERT OR IGNORE INTO departments(code, name, digital, active) VALUES (?, ?, ?, 1)",
                         (code, name, int(digital)))
            if not conn.execute("SELECT 1 FROM users WHERE username = ?", (IMPORT_USER[0],)).fetchone():
                from api.auth import hash_password
                import secrets
                stamp = db.now()
                conn.execute(
                    "INSERT INTO users(id, username, display_name, password_hash, role, department_code, "
                    "active, token_version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, ?)",
                    (db.new_id(), IMPORT_USER[0], IMPORT_USER[1], hash_password(secrets.token_urlsafe(24)),
                     IMPORT_USER[2], code, stamp, stamp))
        importer = conn.execute("SELECT * FROM users WHERE username = ?", (IMPORT_USER[0],)).fetchone()
        linked = {r["run_id"] for r in conn.execute("SELECT run_id FROM case_runs")}

        imported = 0
        for run_dir in sorted(root.glob("run-*"), key=lambda p: p.stat().st_mtime):
            run_id = run_dir.name[4:]
            if run_id in linked or not (run_dir / "case_report.json").exists():
                continue
            if (run_dir / "removed.json").exists():
                continue
            intake = _read(run_dir / "intake.json") or {}
            if (intake.get("source") or {}).get("kind") == "portal_v2":
                continue
            summary = _report_summary(run_dir)
            if summary.get("unreadable"):
                continue
            decisions = _decisions(run_dir)
            latest = decisions[-1] if decisions else None
            status = _STATUS_FOR_DECISION.get(latest["action"], workflow.FORWARDED) if latest else workflow.FORWARDED
            # Filed when the papers arrived: the manifest is written by the first stage, the
            # report by the last (and again on every recompute, which is why it is not used).
            filed_at = min((_iso_mtime(run_dir / n) for n in ("intake.json", "manifest.json") if (run_dir / n).exists()),
                           default=_iso_mtime(run_dir / "case_report.json"))
            report_at = _iso_mtime(run_dir / "case_report.json")
            case_id = db.new_id()
            uploads = sorted((root / "uploads").glob(f"{run_id}-*")) if (root / "uploads").exists() else []
            # A zip upload also leaves the case file the pipeline built from it; only the upload itself
            # is the department's document.
            if any(u.suffix.lower() == ".zip" for u in uploads):
                uploads = [u for u in uploads if not u.name.endswith("-case.pdf")]
            with db.transaction(conn):
                conn.execute(
                    "INSERT INTO cases(id, case_no, department_code, created_via, created_by, status, claimant_name, "
                    "variant, intake_json, submission_no, current_run_id, created_at, updated_at, "
                    "case_type, case_type_source, detected_case_type, detected_case_type_confidence) "
                    "VALUES (?, ?, ?, 'DEPARTMENT', ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
                    (case_id, f"LEGACY-{run_id}", code, importer["id"], status, summary.get("claimant_name"),
                     intake.get("variant") or summary.get("case_variant"),
                     json.dumps({k: v for k, v in intake.items() if k not in ("variant", "source", "declared_case_type")}),
                     run_id, filed_at, max((latest or {}).get("at") or "", report_at),
                     _office_type(summary),
                     ("DECLARED" if summary.get("declared_case_type") else "DETECTED") if _office_type(summary) else None,
                     summary.get("detected_case_type"), summary.get("detected_case_type_confidence")))
                import hashlib
                for i, up in enumerate(uploads, start=1):
                    conn.execute(
                        "INSERT INTO case_documents(id, case_id, submission_no, seq, filename, sha256, bytes, "
                        "stored_path, uploaded_by, uploaded_at) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
                        (db.new_id(), case_id, i, up.name.split("-", 1)[-1],
                         hashlib.sha256(up.read_bytes()).hexdigest(), up.stat().st_size,
                         str(up), importer["id"], filed_at))
                conn.execute(
                    "INSERT INTO case_runs(id, case_id, run_id, submission_no, started_by, started_at, finished_at, "
                    "state, verdict, high_flags, blocking_flags_json, checklist_result, auto_forward) "
                    "VALUES (?, ?, ?, 1, ?, ?, ?, 'done', ?, ?, ?, ?, 1)",
                    (db.new_id(), case_id, run_id, importer["id"], report_at, report_at, summary.get("verdict"),
                     summary.get("high_flags"), json.dumps(summary.get("blocking_flags") or []),
                     summary.get("checklist_result")))
                seq = [0]

                def ev(action: str, frm: str | None, to: str, actor, remark: str = "", at: str = report_at,
                       payload: dict | None = None) -> None:
                    seq[0] += 1
                    conn.execute(
                        "INSERT INTO case_events(id, case_id, seq, action, from_status, to_status, actor_id, actor_name, "
                        "actor_role, actor_department, remark, payload_json, run_id, at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                        (db.new_id(), case_id, seq[0], action, frm, to, getattr(actor, "id", None),
                         getattr(actor, "display_name", None), getattr(actor, "role", "SYSTEM"), remark,
                         json.dumps(payload or {}, ensure_ascii=False), run_id, at))

                importer_actor = _Actor(importer["display_name"], importer["role"], importer["id"])
                ev("CREATE", None, workflow.DRAFT, importer_actor,
                   "Imported from the AI Pension Portal, which had no departments or sign-in.",
                   at=filed_at, payload={"documents": [u.name for u in uploads], "legacy_run": run_id})
                ev("CHECK_DONE", workflow.AI_CHECKING, workflow.AI_CHECKED, None,
                   f"AI check on the old portal: verdict {summary.get('verdict') or 'none'}, "
                   f"{summary.get('high_flags') or 0} HIGH finding(s).")
                ev("FORWARD", workflow.AI_CHECKED, workflow.FORWARDED, importer_actor)
                current = workflow.FORWARDED
                for d in decisions:
                    action = _ACTION_FOR_DECISION.get(d.get("action"), "TAKE_UP")
                    officer = _Actor(d.get("officer") or "an officer", "AG_REVIEWER", None)
                    if current == workflow.FORWARDED:
                        ev("TAKE_UP", current, workflow.UNDER_REVIEW, officer, at=d.get("at") or report_at)
                        current = workflow.UNDER_REVIEW
                    if action != "TAKE_UP":
                        to = _STATUS_FOR_DECISION[d["action"]]
                        ev(action, current, to, officer, d.get("justification") or "", at=d.get("at") or report_at,
                           payload={"legacy_decision": d.get("action"), "override": bool(d.get("overrides_recommendation"))})
                        current = to
            imported += 1
        if imported:
            print(f"[legacy] imported {imported} case(s) from the old portal under {code}")
        return imported
    finally:
        if own:
            conn.close()


def _iso_mtime(path: Path) -> str:
    from datetime import datetime
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return db.now()
