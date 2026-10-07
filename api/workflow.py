"""The case lifecycle: statuses, who may move a case between them, and the history it leaves.

Decision of 28 Sep 2026: the AI verification belongs to the Accountant General. A department
files the papers and the case goes straight to the AG; the AG presses "Verify case with AI";
the outcome moves the case by itself.

    DRAFT --submit--> FORWARDED --verify (AG)--> AI_CHECKING --.
      ^                  |                         |            |-> RETURNED    (documents missing: the list travels back)
      |                  |                         |            '-> UNDER_REVIEW (the AG clears the findings and decides:
      |                  |                         '-> AI_FAILED (verify again)   APPROVED / REJECTED / RETURNED, by hand)
      '--add documents-- RETURNED / DOCS_REQUESTED <-- return, request docs (AG, by hand)

No case is approved by the system (business decision M1, 7 Oct 2026). Until then a clean
verification, or the officer's last clearance, approved the case by itself (AUTO_APPROVE); that
action name remains in histories written before, and in nothing else.

Every transition is a row in ``case_events`` -- who, when, from what to what, with the remark
-- and that table is append-only. The department sees every AG remark through it, and the list
of missing documents an automatic return carries; the admin's overrides are in it too, and
additionally in ``audit_log`` with the before/after of the case row. AI_CHECKED remains a status
name for the histories written before 28 Sep 2026; nothing moves into it now.

Standard library only, in the manner of ``api.desks``: the HTTP layer turns
:class:`WorkflowError` into 403 (not this user's to do) or 409 (not from this status).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from api import db

DRAFT = "DRAFT"
AI_CHECKING = "AI_CHECKING"
AI_FAILED = "AI_FAILED"
AI_CHECKED = "AI_CHECKED"
FORWARDED = "FORWARDED"
UNDER_REVIEW = "UNDER_REVIEW"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
RETURNED = "RETURNED"
DOCS_REQUESTED = "DOCS_REQUESTED"

STATUSES = (DRAFT, AI_CHECKING, AI_FAILED, AI_CHECKED, FORWARDED, UNDER_REVIEW,
            APPROVED, REJECTED, RETURNED, DOCS_REQUESTED)

#: What the screens print for each status.
STATUS_LABELS = {
    DRAFT: "Not yet submitted", AI_CHECKING: "AI verification in progress", AI_FAILED: "AI verification incomplete",
    AI_CHECKED: "AI checked", FORWARDED: "Submitted to AG", UNDER_REVIEW: "Under review at AG",
    APPROVED: "Approved", REJECTED: "Rejected", RETURNED: "Returned to department",
    DOCS_REQUESTED: "Documents requested",
}

#: Statuses in which the department's side holds the case.
DEPARTMENT_HOLDS = frozenset({DRAFT, AI_CHECKED, RETURNED, DOCS_REQUESTED})
#: Statuses in which the AG holds the case (the verification runs on the AG's desk).
AG_HOLDS = frozenset({FORWARDED, AI_CHECKING, AI_FAILED, UNDER_REVIEW})
#: Statuses after which adding documents opens a new round of papers.
SENT_BACK = frozenset({RETURNED, DOCS_REQUESTED})

DEPARTMENT_SIDE = ("DEPT_OFFICER", "ADMIN")
AG_SIDE = ("AG_REVIEWER", "AG_DAG", "ADMIN")   # ADMIN leaves this tuple with decision G6

#: action -> (roles, from-statuses, to-status). ``None`` as the target means "unchanged".
TRANSITIONS: dict[str, tuple[tuple[str, ...], frozenset[str], str | None]] = {
    "ADD_DOCS":     (DEPARTMENT_SIDE, frozenset({DRAFT, AI_CHECKED, RETURNED, DOCS_REQUESTED}), None),
    # A paper put in place of one already filed (30 Sep 2026); the old one stays on file, superseded.
    "REPLACE_DOC":  (DEPARTMENT_SIDE, frozenset({DRAFT, AI_CHECKED, RETURNED, DOCS_REQUESTED}), None),
    "FORWARD":      (DEPARTMENT_SIDE, frozenset({DRAFT, AI_CHECKED, RETURNED, DOCS_REQUESTED}), FORWARDED),
    "RUN_CHECK":    (AG_SIDE, frozenset({FORWARDED, AI_FAILED, UNDER_REVIEW}), AI_CHECKING),
    "CHECK_DONE":   ((), frozenset({AI_CHECKING}), UNDER_REVIEW),    # by the system: findings for the AG
    "CHECK_FAILED": ((), frozenset({AI_CHECKING}), AI_FAILED),       # by the system: verify again
    "AUTO_RETURN":  ((), frozenset({AI_CHECKING}), RETURNED),        # by the system: documents missing
    "TAKE_UP":      (AG_SIDE, frozenset({FORWARDED}), UNDER_REVIEW),
    "APPROVE":      (AG_SIDE, frozenset({UNDER_REVIEW, FORWARDED, AI_FAILED}), APPROVED),
    "REJECT":       (AG_SIDE, frozenset({UNDER_REVIEW, FORWARDED, AI_FAILED}), REJECTED),
    "RETURN":       (AG_SIDE, frozenset({UNDER_REVIEW, FORWARDED, AI_FAILED}), RETURNED),
    "REQUEST_DOCS": (AG_SIDE, frozenset({UNDER_REVIEW, FORWARDED, AI_FAILED}), DOCS_REQUESTED),
    "OVERRIDE":     (("ADMIN",), frozenset(STATUSES), None),         # target given by the admin
    # The case type (29 Sep 2026): a department may change its declaration while the case is on
    # its side; the AG and the administrator may correct it at any point, with a remark.
    "SET_CASE_TYPE": (("DEPT_OFFICER", "AG_REVIEWER", "AG_DAG", "ADMIN"), frozenset(STATUSES), None),
}

#: Where a department may still change what it declared: the same statuses it may add papers in.
CASE_TYPE_EDITABLE_BY_DEPARTMENT = frozenset({DRAFT, AI_CHECKED, RETURNED, DOCS_REQUESTED})

#: What the system may do on its own: record a verification's outcome, and return a case whose
#: documents are missing. Never approve (M1, 7 Oct 2026).
SYSTEM_ACTIONS = frozenset({"CHECK_DONE", "CHECK_FAILED", "AUTO_RETURN"})

#: Actions whose remark is required whatever the case looks like.
REMARK_REQUIRED = frozenset({"APPROVE", "REJECT", "RETURN", "REQUEST_DOCS", "OVERRIDE"})

#: An approval against the engine's own reading needs a written reason of at least this
#: length -- the same bar ``api.decisions`` sets for the old portal (MIN_JUSTIFICATION).
MIN_OVERRIDE_REMARK = 15


class WorkflowError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


def allowed_actions(role: str, status: str) -> list[str]:
    """The user-performable actions that move a case, for this role in this status. Setting the
    case type is not a movement and has its own rules (the case-type route), so it is not listed."""
    return [a for a, (roles, froms, _) in TRANSITIONS.items()
            if roles and role in roles and status in froms and a != "SET_CASE_TYPE"]


def check(role: str, status: str, action: str) -> None:
    """Refuse an action this role may not take, or that this status does not allow."""
    if action not in TRANSITIONS:
        raise WorkflowError(422, f"unknown action {action!r}")
    roles, froms, _ = TRANSITIONS[action]
    if roles and role not in roles:
        raise WorkflowError(403, f"a {role.replace('_', ' ').lower()} may not {action.lower().replace('_', ' ')} a case")
    if status not in froms:
        can = allowed_actions(role, status) if role else []
        raise WorkflowError(
            409, f"a case in status {status} cannot be {action.lower().replace('_', ' ')}ed"
                 + (f"; from here you may: {', '.join(can)}" if can else ""))


def owns_side(user_role: str, user_department: str | None, case: sqlite3.Row | dict) -> bool:
    """May this user act on the department's side of this case?

    A department officer, on their own department's cases. An admin, on any.
    """
    if user_role == "ADMIN":
        return True
    if user_role == "DEPT_OFFICER":
        return case["department_code"] == user_department
    return False


def may_see(user_role: str, user_department: str | None, case: sqlite3.Row | dict) -> bool:
    """Reads: the department's side sees its own; AG Review and Admin see everything."""
    if user_role in ("AG_REVIEWER", "AG_DAG", "ADMIN"):
        return True
    return owns_side(user_role, user_department, case)


def record_event(conn: sqlite3.Connection, case_id: str, *, action: str, from_status: str | None,
                 to_status: str, actor: Any, remark: str = "", payload: dict | None = None,
                 run_id: str | None = None) -> dict:
    """Append one history row. Caller holds the transaction."""
    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM case_events WHERE case_id = ?",
                       (case_id,)).fetchone()[0]
    entry = {
        "id": db.new_id(), "case_id": case_id, "seq": seq, "action": action,
        "from_status": from_status, "to_status": to_status,
        "actor_id": getattr(actor, "id", None), "actor_name": getattr(actor, "display_name", None),
        "actor_role": getattr(actor, "role", None) or ("SYSTEM" if actor is None else None),
        "actor_department": getattr(actor, "department_code", None),
        "remark": remark or "", "payload_json": json.dumps(payload or {}, ensure_ascii=False),
        "run_id": run_id, "at": db.now(),
    }
    conn.execute(
        "INSERT INTO case_events(id, case_id, seq, action, from_status, to_status, actor_id, "
        "actor_name, actor_role, actor_department, remark, payload_json, run_id, at) "
        "VALUES (:id, :case_id, :seq, :action, :from_status, :to_status, :actor_id, :actor_name, "
        ":actor_role, :actor_department, :remark, :payload_json, :run_id, :at)", entry)
    # The submission-round record (api.rounds, 30 Sep 2026) rides on the history row, in the
    # same transaction; a fault there is logged and never blocks the decision.
    from api import rounds
    rounds.on_event(conn, case_id, action, entry, payload, actor)
    return entry


def transition(conn: sqlite3.Connection, case: sqlite3.Row, action: str, actor: Any, *,
               remark: str = "", payload: dict | None = None, run_id: str | None = None,
               to_status: str | None = None,
               within: Callable[[sqlite3.Connection, dict], None] | None = None) -> dict:
    """Move the case and write the history row, inside one transaction.

    ``actor`` is an ``api.auth.User`` or None for the system (the reconciler). The permission
    check is skipped for the system, whose actions are the SYSTEM_ACTIONS and nothing else.

    ``within`` runs inside the same transaction, after the history row, with the new event: for
    rows that must exist if and only if the move happened (the override's audit row, audit
    6 Oct 2026). If it raises, the move is rolled back with it.
    """
    role = getattr(actor, "role", "")
    if actor is not None:
        check(role, case["status"], action)
    elif action not in SYSTEM_ACTIONS:
        raise WorkflowError(403, "the system may only record the outcome of a verification")
    roles, froms, target = TRANSITIONS[action]
    if case["status"] not in froms:
        raise WorkflowError(409, f"a case in status {case['status']} cannot be {action.lower()}ed")
    if action in REMARK_REQUIRED and not (remark or "").strip():
        raise WorkflowError(422, f"{action.replace('_', ' ').title()} needs a remark")
    if action == "OVERRIDE":
        if to_status not in STATUSES:
            raise WorkflowError(422, f"override needs a target status from {list(STATUSES)}")
        if to_status == AI_CHECKING:
            raise WorkflowError(422, "a case cannot be put into 'AI verification in progress' by hand; "
                                     "set it to DRAFT and run the verification")
        target = to_status
    new_status = target or case["status"]
    with db.transaction(conn):
        # Conditional on the status this decision was taken against: two officers deciding at
        # once, or the reconciler racing an override, cannot both win.
        # A new verification forgets the previous run in the same statement. Otherwise the sweep,
        # finding the case in AI_CHECKING still pointing at the old finished run, applied that
        # run's outcome to it before the new run was recorded, and the new run's result was then
        # never applied: the case stayed where the old one put it (audit 6 Oct 2026).
        forget_run = ", current_run_id = NULL" if action == "RUN_CHECK" else ""
        cur = conn.execute(f"UPDATE cases SET status = ?, updated_at = ?{forget_run} WHERE id = ? AND status = ?",
                           (new_status, db.now(), case["id"], case["status"]))
        if cur.rowcount != 1:
            raise WorkflowError(409, "the case changed while you were working on it; reload and try again")
        entry = record_event(conn, case["id"], action=action, from_status=case["status"],
                             to_status=new_status, actor=actor, remark=remark, payload=payload,
                             run_id=run_id)
        if within is not None:
            within(conn, entry)
    return entry


def audit(conn: sqlite3.Connection, *, actor: Any, action: str, entity_type: str, entity_id: str,
          before: dict | None, after: dict | None, reason: str = "", ip: str | None = None) -> None:
    """One append-only audit row. Caller holds the transaction (or none: autocommit)."""
    conn.execute(
        "INSERT INTO audit_log(id, at, actor_id, actor_name, actor_role, action, entity_type, "
        "entity_id, before_json, after_json, reason, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (db.new_id(), db.now(), getattr(actor, "id", None), getattr(actor, "display_name", None),
         getattr(actor, "role", None), action, entity_type, entity_id,
         json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
         json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
         reason or "", ip))
