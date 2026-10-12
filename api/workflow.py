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

Three tiers inside the AG (scope change C3, 9 Oct 2026): a department's case lands with the
**Senior Auditor** of its pension wing, who runs the verification and either returns the case to
the department or forwards it to the **Assistant Accounts Officer**, who forwards it to the
**Accounts Officer**, who approves or rejects (default Q1: the AO is final). Returns go one tier
down at a time. Who holds the case is the ``holder_tier`` column (SENIOR_AUDITOR | ASSISTANT_AO |
AO), not a new status, so every status keeps its meaning; a tier officer sees and acts on their
own wing's cases only (``PENSION_SECTION_OF``). The Deputy AG overrides from anywhere and is not
part of the chain (Q2). AG_REVIEWER is the Accountant General's own desk (decision of 9 Oct 2026,
afternoon, replacing the Q5 default): it acts at every tier in every wing and overrides like the
Deputy AG; the senior officers of the office share that one login.

Standard library only, in the manner of ``api.desks``: the HTTP layer turns
:class:`WorkflowError` into 403 (not this user's to do) or 409 (not from this status).
"""
from __future__ import annotations

import json
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

#: The tiers inside the AG's pension wing (C3), in the order a case climbs them.
SENIOR_AUDITOR = "SENIOR_AUDITOR"
ASSISTANT_AO = "ASSISTANT_AO"
AO = "AO"
TIERS = (SENIOR_AUDITOR, ASSISTANT_AO, AO)
TIER_LABELS = {SENIOR_AUDITOR: "Senior Auditor", ASSISTANT_AO: "Assistant Accounts Officer", AO: "Accounts Officer"}
TIER_OF_ROLE = {"AG_SENIOR_AUDITOR": SENIOR_AUDITOR, "AG_ASSISTANT_AO": ASSISTANT_AO, "AG_AO": AO}
ROLE_OF_TIER = {t: r for r, t in TIER_OF_ROLE.items()}
TIER_ROLES = tuple(TIER_OF_ROLE)
NEXT_TIER = {SENIOR_AUDITOR: ASSISTANT_AO, ASSISTANT_AO: AO}
PREVIOUS_TIER = {AO: ASSISTANT_AO, ASSISTANT_AO: SENIOR_AUDITOR}
#: How far up the chain each tier sits. A pension case reaches the Assistant AO only when the Senior
#: Auditor forwards it, and the AO only when the Assistant AO does; until then it is not on their
#: screens at all (12 Oct 2026). Once it has reached a tier it stays visible there for the rest of
#: that filing, a return down the chain included, so the officer can follow what became of it; a
#: fresh filing by the department starts the climb again. ``cases.reached_tier`` (migration 0016).
TIER_RANK = {SENIOR_AUDITOR: 0, ASSISTANT_AO: 1, AO: 2}

#: Who acts on each side of a case. The administrator is on neither (business decision G6, 7 Oct
#: 2026): the IT administrator manages users and reads the audit log, and takes no case action in
#: pension or GP Fund. The override belongs to the Deputy AG and to the AG's desk (AG_REVIEWER),
#: which may act at any tier in any wing (9 Oct 2026).
DEPARTMENT_SIDE = ("DEPT_OFFICER",)
#: The roles bound to no wing and no tier: they act wherever the case is.
ANY_TIER = ("AG_DAG", "AG_REVIEWER")
AG_SIDE = TIER_ROLES + ANY_TIER
#: Every role that reads AG-side material: the acting roles and the administrator.
AG_READERS = AG_SIDE + ("ADMIN",)

#: action -> (roles, from-statuses, to-status). ``None`` as the target means "unchanged".
TRANSITIONS: dict[str, tuple[tuple[str, ...], frozenset[str], str | None]] = {
    "ADD_DOCS":     (DEPARTMENT_SIDE, frozenset({DRAFT, AI_CHECKED, RETURNED, DOCS_REQUESTED}), None),
    # A paper put in place of one already filed (30 Sep 2026); the old one stays on file, superseded.
    "REPLACE_DOC":  (DEPARTMENT_SIDE, frozenset({DRAFT, AI_CHECKED, RETURNED, DOCS_REQUESTED}), None),
    "FORWARD":      (DEPARTMENT_SIDE, frozenset({DRAFT, AI_CHECKED, RETURNED, DOCS_REQUESTED}), FORWARDED),
    # The verification is the Senior Auditor's (C3); the Deputy AG and the AG's desk may run it too.
    "RUN_CHECK":    (("AG_SENIOR_AUDITOR",) + ANY_TIER, frozenset({FORWARDED, AI_FAILED, UNDER_REVIEW}), AI_CHECKING),
    "CHECK_DONE":   ((), frozenset({AI_CHECKING}), UNDER_REVIEW),    # by the system: findings for the AG
    "CHECK_FAILED": ((), frozenset({AI_CHECKING}), AI_FAILED),       # by the system: verify again
    # Retired 9 Oct 2026 (no automatic return in pension or GP Fund): neither the system nor any
    # role may perform these now; the rows stay so history written before that day still resolves.
    "AUTO_RETURN":  ((), frozenset(), RETURNED),                      # was: by the system, documents missing
    "GPF_RETURN":   ((), frozenset(), RETURNED),                      # was: on the officer's return in the GP Fund module
    "TAKE_UP":      (("AG_SENIOR_AUDITOR",) + ANY_TIER, frozenset({FORWARDED}), UNDER_REVIEW),
    # Up the chain: Senior Auditor -> Assistant AO -> AO; and one tier back down, with a remark.
    # The status stays UNDER_REVIEW; the holder (holder_tier) moves. Internal to the AG: a DDO
    # never sees these rows.
    "FORWARD_TIER": (("AG_SENIOR_AUDITOR", "AG_ASSISTANT_AO") + ANY_TIER, frozenset({UNDER_REVIEW}), None),
    "RETURN_TIER":  (("AG_ASSISTANT_AO", "AG_AO") + ANY_TIER, frozenset({UNDER_REVIEW}), None),
    # The decision is the Accounts Officer's (Q1); the return to the department is the Senior
    # Auditor's, who is the tier that talks to the department.
    "APPROVE":      (("AG_AO",) + ANY_TIER, frozenset({UNDER_REVIEW, FORWARDED, AI_FAILED}), APPROVED),
    "REJECT":       (("AG_AO",) + ANY_TIER, frozenset({UNDER_REVIEW, FORWARDED, AI_FAILED}), REJECTED),
    "RETURN":       (("AG_SENIOR_AUDITOR",) + ANY_TIER, frozenset({UNDER_REVIEW, FORWARDED, AI_FAILED}), RETURNED),
    "REQUEST_DOCS": (("AG_SENIOR_AUDITOR",) + ANY_TIER, frozenset({UNDER_REVIEW, FORWARDED, AI_FAILED}), DOCS_REQUESTED),
    "OVERRIDE":     (ANY_TIER, frozenset(STATUSES), None),           # target given by the Deputy AG or the AG's desk (G6)
    # The case type (29 Sep 2026): a department may change its declaration while the case is on
    # its side; the AG and the administrator may correct it at any point, with a remark.
    "SET_CASE_TYPE": (DEPARTMENT_SIDE + AG_SIDE, frozenset(STATUSES), None),
}

#: The moves between tiers: never shown to the department (C3).
INTERNAL_ACTIONS = frozenset({"FORWARD_TIER", "RETURN_TIER"})
#: Actions a tier may take only while it holds the case.
HOLDER_ACTIONS = frozenset({"RUN_CHECK", "TAKE_UP", "FORWARD_TIER", "RETURN_TIER", "APPROVE", "REJECT",
                            "RETURN", "REQUEST_DOCS"})

#: Where a department may still change what it declared: the same statuses it may add papers in.
CASE_TYPE_EDITABLE_BY_DEPARTMENT = frozenset({DRAFT, AI_CHECKED, RETURNED, DOCS_REQUESTED})

#: What the system may do on its own: record a verification's outcome. Never approve (M1, 7 Oct
#: 2026) and never return (9 Oct 2026): every move of a case is an officer's decision.
SYSTEM_ACTIONS = frozenset({"CHECK_DONE", "CHECK_FAILED"})

#: Actions whose remark is required whatever the case looks like.
REMARK_REQUIRED = frozenset({"APPROVE", "REJECT", "RETURN", "REQUEST_DOCS", "OVERRIDE", "RETURN_TIER"})

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


def owns_side(user_role: str, user_department: str | None, case: db.Row | dict) -> bool:
    """May this user act on the department's side of this case?

    A department officer, on their own department's cases. Nobody else (the administrator acts
    on no case, G6).
    """
    if user_role == "DEPT_OFFICER":
        return case["department_code"] == user_department
    return False


def wing_of_case(case: db.Row | dict) -> str | None:
    """The pension wing a case belongs to: its department's section (None for the legacy bucket)."""
    from api.departments import PENSION_SECTION_OF
    return PENSION_SECTION_OF.get(case["department_code"])


def tier_of(role: str | None) -> str | None:
    return TIER_OF_ROLE.get(role or "")


def holder_label(case: db.Row | dict) -> str | None:
    """"With Senior Auditor, Pension-III" while the AG holds the case; None otherwise."""
    if case["status"] not in AG_HOLDS:
        return None
    tier = (case["holder_tier"] if "holder_tier" in case.keys() else None) or SENIOR_AUDITOR
    wing = wing_of_case(case)
    return f"With {TIER_LABELS[tier]}" + (f", {wing}" if wing else "")


def may_see(user_role: str, user_department: str | None, case: db.Row | dict, user_wing: str | None = None) -> bool:
    """Reads: the department's side sees its own; a tier officer their own wing's cases; the
    Deputy AG, the AG's desk and the administrator everything."""
    if user_role in ("AG_REVIEWER", "AG_DAG", "ADMIN"):
        return True
    if user_role in TIER_ROLES:
        wing = wing_of_case(case)
        return wing is not None and wing == user_wing and has_reached(case, TIER_OF_ROLE[user_role])
    return owns_side(user_role, user_department, case)


def reached_tier(case: db.Row | dict) -> str:
    """The highest tier this filing of the case has been sent to; the Senior Auditor's until forwarded."""
    keys = case.keys()
    return (case["reached_tier"] if "reached_tier" in keys else None) or SENIOR_AUDITOR


def has_reached(case: db.Row | dict, tier: str) -> bool:
    """Whether the case has been sent up to ``tier``. The tiers are pension's alone (Q3): a GP Fund
    case is seen by its wing's officers as before."""
    if "product" in case.keys() and (case["product"] or "PENSION") != "PENSION":
        return True
    return TIER_RANK[reached_tier(case)] >= TIER_RANK[tier]


def next_reached(action: str, case: db.Row | dict, holder: str | None | object) -> str | object:
    """The case's ``reached_tier`` after ``action``; ``KEEP`` when the move does not change it.

    A filing by the department starts the climb again at the Senior Auditor; any move that hands
    the case to a higher tier (a forward, or the Deputy AG's override) raises it; nothing lowers it."""
    if action == "FORWARD":
        return SENIOR_AUDITOR
    if holder in TIER_RANK and TIER_RANK[holder] > TIER_RANK[reached_tier(case)]:      # type: ignore[index]
        return holder                                                                   # type: ignore[return-value]
    return KEEP


def may_see_user(user: Any, case: db.Row | dict) -> bool:
    return may_see(getattr(user, "role", ""), getattr(user, "department_code", None), case,
                   getattr(user, "pension_wing", None))


def check_holder(actor: Any, case: db.Row | dict, action: str) -> None:
    """A tier officer acts only on their own wing's case, and only while their tier holds it.

    The Deputy AG and the AG's desk are bound by neither (Q2; 9 Oct 2026). A case the AG holds with no holder recorded (filed
    before 0014 and not migrated, which the migration prevents) counts as the Senior Auditor's."""
    role = getattr(actor, "role", "")
    tier = tier_of(role)
    if tier is None:
        return
    if wing_of_case(case) != getattr(actor, "pension_wing", None):
        raise WorkflowError(403, "this case belongs to another pension wing")
    if action in HOLDER_ACTIONS and case["status"] in AG_HOLDS:
        holder = (case["holder_tier"] if "holder_tier" in case.keys() else None) or SENIOR_AUDITOR
        if holder != tier:
            raise WorkflowError(409, f"the case is with the {TIER_LABELS[holder]}; it is not yours to move")


def check_one_tier_per_case(conn: db.Connection, actor: Any, case: db.Row | dict) -> None:
    """Maker-checker across tiers (C3): an account that acted on this case at one tier may not act
    at another, whatever its role is now."""
    role = getattr(actor, "role", "")
    tier = tier_of(role)
    actor_id = getattr(actor, "id", None)
    if tier is None or not actor_id:
        return
    for r in conn.execute("SELECT DISTINCT actor_role FROM case_events WHERE case_id = ? AND actor_id = ?",
                          (case["id"], actor_id)):
        other = tier_of(r["actor_role"])
        if other and other != tier:
            raise WorkflowError(403, f"you acted on this case as {TIER_LABELS[other]}; one account acts at one tier on a case")


def next_holder(action: str, case: db.Row | dict, new_status: str, to_tier: str | None = None) -> str | None | object:
    """Who holds the case after ``action``; ``KEEP`` when the move does not touch it."""
    current = (case["holder_tier"] if "holder_tier" in case.keys() else None) or SENIOR_AUDITOR
    if action == "FORWARD":
        return SENIOR_AUDITOR                                   # the department's filing lands with the Senior Auditor
    if action == "FORWARD_TIER":
        if current not in NEXT_TIER:
            raise WorkflowError(409, f"the {TIER_LABELS[current]} is the last tier; approve or reject the case")
        return NEXT_TIER[current]
    if action == "RETURN_TIER":
        if current not in PREVIOUS_TIER:
            raise WorkflowError(409, "the Senior Auditor returns a case to the department (Return), not to a lower tier")
        return PREVIOUS_TIER[current]
    if action in ("APPROVE", "REJECT", "RETURN", "REQUEST_DOCS"):
        return None
    if action == "OVERRIDE":
        if new_status in AG_HOLDS:
            return to_tier if to_tier in TIERS else SENIOR_AUDITOR
        return None
    if action in ("RUN_CHECK", "TAKE_UP") and case["status"] in AG_HOLDS:
        return current
    return KEEP


KEEP = object()


def record_event(conn: db.Connection, case_id: str, *, action: str, from_status: str | None,
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


def transition(conn: db.Connection, case: db.Row, action: str, actor: Any, *,
               remark: str = "", payload: dict | None = None, run_id: str | None = None,
               to_status: str | None = None,
               within: Callable[[db.Connection, dict], None] | None = None) -> dict:
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
        check_holder(actor, case, action)
        if action != "SET_CASE_TYPE":
            check_one_tier_per_case(conn, actor, case)
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
    to_tier = (payload or {}).get("holder_tier") if action == "OVERRIDE" else None
    holder = next_holder(action, case, new_status, to_tier)
    if action in INTERNAL_ACTIONS:
        current = (case["holder_tier"] if "holder_tier" in case.keys() else None) or SENIOR_AUDITOR
        payload = {**(payload or {}), "from_tier": current, "to_tier": holder}
    with db.transaction(conn):
        # Conditional on the status this decision was taken against: two officers deciding at
        # once, or the reconciler racing an override, cannot both win.
        # A new verification forgets the previous run in the same statement. Otherwise the sweep,
        # finding the case in AI_CHECKING still pointing at the old finished run, applied that
        # run's outcome to it before the new run was recorded, and the new run's result was then
        # never applied: the case stayed where the old one put it (audit 6 Oct 2026).
        forget_run = ", current_run_id = NULL" if action == "RUN_CHECK" else ""
        set_holder = "" if holder is KEEP else ", holder_tier = ?"
        holder_args: tuple = () if holder is KEEP else (holder,)
        reached = next_reached(action, case, holder)
        set_reached = "" if reached is KEEP else ", reached_tier = ?"
        reached_args: tuple = () if reached is KEEP else (reached,)
        cur = conn.execute(f"UPDATE cases SET status = ?, updated_at = ?{forget_run}{set_holder}{set_reached} WHERE id = ? AND status = ?",
                           (new_status, db.now(), *holder_args, *reached_args, case["id"], case["status"]))
        if cur.rowcount != 1:
            raise WorkflowError(409, "the case changed while you were working on it; reload and try again")
        entry = record_event(conn, case["id"], action=action, from_status=case["status"],
                             to_status=new_status, actor=actor, remark=remark, payload=payload,
                             run_id=run_id)
        if within is not None:
            within(conn, entry)
    return entry


def audit(conn: db.Connection, *, actor: Any, action: str, entity_type: str, entity_id: str,
          before: dict | None, after: dict | None, reason: str = "", ip: str | None = None) -> None:
    """One append-only audit row. Caller holds the transaction (or none: autocommit).

    Stamped to the microsecond: the audit screen lists rows newest first, and two rows written in
    the same second (a sign-in, then the action) must keep their order on any engine."""
    conn.execute(
        "INSERT INTO audit_log(id, at, actor_id, actor_name, actor_role, action, entity_type, "
        "entity_id, before_json, after_json, reason, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (db.new_id(), db.stamp(), getattr(actor, "id", None), getattr(actor, "display_name", None),
         getattr(actor, "role", None), action, entity_type, entity_id,
         json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
         json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
         reason or "", ip))
