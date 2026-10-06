"""Who is using the module, and what that lets them do. SOP §4.

The SOP names two parties and gives them different jobs. §4.1 the Administrative Department
submits the case, is *responsible for shortcomings* in it, and resubmits after putting them
right. §4.2 the Accounts Office receives the case, processes it against the rules and the
checklist, and **approves or rejects** it.

That division is the point of the document, so it is enforced here rather than drawn on the
screen. A portal that merely hides the approve button from the submitting department leaves
the endpoint open, and the audit trail then cannot answer "who was entitled to sign this".

There is no authentication in this build. A role is a CLAIM, exactly as ``officer`` is a
claim -- recorded as asserted, never as proven. What this module guarantees is narrower and
still worth having: a decision carries the role that was claimed when it was made, and a
department claiming its own role cannot record an approval at all. Wiring these claims to
real identities belongs in whatever fronts this later, and the shape is ready for it.
"""

from __future__ import annotations

#: SOP §4.1. Submits the case after completing codal formalities; answerable for the
#: documents in it; resubmits a returned case once the shortcomings are removed.
ADMIN_DEPARTMENT = "ADMIN_DEPARTMENT"

#: SOP §4.2. Receives cases from the module, processes them under the pension rules and the
#: approved checklist, and approves or rejects them within the timelines.
ACCOUNTS_OFFICE = "ACCOUNTS_OFFICE"

ROLES = (ADMIN_DEPARTMENT, ACCOUNTS_OFFICE)

LABELS = {
    ADMIN_DEPARTMENT: "Administrative Department",
    ACCOUNTS_OFFICE: "Accounts Office",
}

#: What each role may do. Read as "the SOP gives this party this job".
PERMISSIONS: dict[str, tuple[str, ...]] = {
    # §4.1: submit, and resubmit after removal of shortcomings. Sees its own cases and the
    # shortcomings found in them -- that is the whole point of returning a case -- but has
    # no part in deciding one.
    ADMIN_DEPARTMENT: ("submit_case", "view_case", "view_shortcomings", "resubmit_case"),
    # §4.2: everything the department may do except submit on its behalf, plus the decision.
    ACCOUNTS_OFFICE: ("view_case", "view_shortcomings", "decide_case", "view_audit_trail"),
}


class RoleError(PermissionError):
    """The claimed role does not carry the action attempted. Nothing is recorded."""


def label(role: str) -> str:
    return LABELS.get(role, role)


def may(role: str, action: str) -> bool:
    return action in PERMISSIONS.get(role, ())


def require(role: str | None, action: str) -> str:
    """Check a claimed role against an action, or raise. Returns the role when it passes."""
    if not role:
        raise RoleError(
            f"no role was claimed for {action!r}. Under SOP §4 every action belongs to a "
            f"named party: {', '.join(LABELS[r] for r in ROLES)}."
        )
    if role not in PERMISSIONS:
        raise RoleError(f"unknown role {role!r}; the SOP names {list(ROLES)}")
    if not may(role, action):
        raise RoleError(
            f"the {label(role)} may not {action.replace('_', ' ')}. Under SOP §4.2 a pension "
            f"case is approved or rejected by the {LABELS[ACCOUNTS_OFFICE]}; the "
            f"{LABELS[ADMIN_DEPARTMENT]} submits it and answers for shortcomings in it "
            f"(§4.1)."
        )
    return role
