"""Who may do what, by desk. SOP §4 (roles and responsibilities), BUILD §11.1.

The documentation names nine desks and gives each a purpose: the department submits, the
PSA signs, the Pension Facilitation Centre scans and receives, the Auditor of the Pension Wing
selects the variant, supplies the pay figures and records the decision, the Determining Officer
determines, the DAG (Pension) supervises, the Audit Office reads, the reference-data
administrator maintains the rules and the system administrator runs the deployment. Until now
the portal asked which desk a person was at and then let every desk do everything; the desk
was a label on the log entry and nothing more.

This module is the server-side answer. Every state-changing call names the action it
performs, and the desk stated on the request must be one the SOP gives that action to.
Reads are open to every desk -- the Audit Office's whole function is reading (SOP §4.7).

**Bound to the sign-in (5 Oct 2026).** Every ``/api/*`` route needs a case-system token
(``api.server``), and the desk a request acts at must be one the signed-in ACCOUNT holds
(:data:`ACCOUNT_DESKS`, :func:`desk_for_account`). The ``X-Desk`` header, or ``role`` in a body,
may still choose among the account's own desks; it can no longer name a desk the account does
not hold, and where it names none the account's desk for the action is used. The officer
recorded is the account's name, never one typed into the request. Before this the desk was a
claim nothing verified (docs/DEPLOYMENT.md F2).

Standard library only, so the tests run without FastAPI: the HTTP layer turns
:class:`DeskNotAuthorised` into a 403.
"""
from __future__ import annotations

from typing import Iterable

#: The desks, by id, with the label the portal shows and stores. Mirror of ``DESKS`` in
#: the retired old portal's ``identity.ts`` (removed 7 Oct 2026) once mirrored this; the case system's
#: screens take the desk from the account. ``rules/confirmations.py`` keeps its own
#: two-entry map for the desks that confirm rule values; the labels there must match these.
DESKS: dict[str, str] = {
    "AG_REVIEWER": "Auditor, Pension wing (AG / DAO)",
    "AG_DETERMINING": "Determining officer, Pension wing (AG / DAO)",
    "DAG_PENSION": "Deputy Accountant General (Pension)",
    "AD_SUBMITTER": "Submitting officer, Administrative Department",
    "PSA": "Pension Sanctioning Authority",
    "PFC_OPERATOR": "Pension Facilitation Centre operator",
    "AUDITOR": "Auditor (log and certification review)",
    "REFERENCE_ADMIN": "Reference-data administrator",
    "SYSTEM_ADMIN": "System administrator",
}

#: Each state-changing action, the desks the SOP gives it to, and where the SOP says so.
#: Reads are not listed: every desk may read (SOP §4.7 gives the Audit Office nothing else).
PERMISSIONS: dict[str, dict[str, object]] = {
    "intake": {
        "what": "submit a scanned case file",
        "desks": ("AD_SUBMITTER", "PFC_OPERATOR", "AG_REVIEWER"),
        "cite": ("SOP §4.1(3) the department forwards the case; §4.3 the Pension Facilitation "
                 "Centre receives and scans it; §4.4 the Auditor, Pension Wing, takes it up"),
    },
    "intake_choices": {
        "what": "select the case variant or supply pay or commutation figures at intake",
        "desks": ("AG_REVIEWER",),
        "cite": ("SOP §4.4(1) the Auditor, Pension Wing, selects the case variant at intake; "
                 "§4.4(2) supplies the three annual basic pay figures"),
    },
    "decide": {
        "what": "record a decision of FORWARD, RETURN FOR CORRECTION or HOLD",
        "desks": ("AG_REVIEWER", "DAG_PENSION"),
        "cite": ("SOP §4.4(6) the Auditor, Pension Wing, records the decision under the "
                 "officer's own name and desk; §4.6 the DAG (Pension) exercises supervisory "
                 "sign-off"),
    },
    "recompute": {
        "what": "recompute a case on the rules now in force",
        "desks": ("AG_REVIEWER", "AG_DETERMINING", "DAG_PENSION", "REFERENCE_ADMIN",
                  "SYSTEM_ADMIN"),
        "cite": ("SOP §4.4(3) the Auditor reviews the findings; §4.5 the Determining Officer "
                 "determines; §4.8 the reference-data administrator maintains the rule packs "
                 "a case catches up with"),
    },
    "confirm_rule": {
        "what": "confirm an open rule value",
        "desks": ("DAG_PENSION", "REFERENCE_ADMIN"),
        "cite": ("SOP §7.3(5) a question of interpretation goes to the DAG (Pension); §4.8 "
                 "the reference-data administrator records the authority for every reference "
                 "value"),
    },
}


#: The desks each case-system account role may act at. The Pension Wing's accounts are the
#: Auditor, the Determining Officer and the DAG (Pension) -- one role in the case system; the
#: administrator runs the deployment and maintains the reference data; a DDO submits.
ACCOUNT_DESKS: dict[str, tuple[str, ...]] = {
    # The portal role on the left, the old register's desks on the right -- the two namespaces
    # share the spelling "AG_REVIEWER" and mean different things.
    "AG_REVIEWER": ("AG_REVIEWER", "AG_DETERMINING", "DAG_PENSION"),
    "AG_ADDL": ("AG_REVIEWER", "AG_DETERMINING", "DAG_PENSION"),
    # The three tiers of a pension wing (C3, 9 Oct 2026) act at the Auditor's and the Determining
    # Officer's desks of the SOP; the Deputy AG keeps the DAG desk.
    "AG_SENIOR_AUDITOR": ("AG_REVIEWER", "AG_DETERMINING"),
    "AG_ASSISTANT_AO": ("AG_REVIEWER", "AG_DETERMINING"),
    "AG_AO": ("AG_REVIEWER", "AG_DETERMINING", "DAG_PENSION"),
    # The Deputy AG (role AG_DAG, 7 Oct 2026) holds the DAG desk and may act at the desks below it.
    "AG_DAG": ("DAG_PENSION", "AG_DETERMINING", "AG_REVIEWER", "REFERENCE_ADMIN"),
    "ADMIN": ("SYSTEM_ADMIN", "REFERENCE_ADMIN"),
    "DEPT_OFFICER": ("AD_SUBMITTER",),
}


class DeskNotAuthorised(PermissionError):
    """The desk stated may not perform the action. Carries the SOP paragraph."""


#: The two SOP §4 parties the portal names, mapped onto the desk that acts for each.
#:
#: The portal states a party -- "the Accounts Office", "the Administrative Department" --
#: where this module expects the desk inside it. They are not competing vocabularies: §4.2
#: gives the Accounts Office's processing and decision to the Auditor of the Pension Wing, and
#: §4.1 gives the department's submission to its submitting officer. Reading one as the other
#: records the same person the SOP already names, which is why this is an alias and not a
#: widening: an alias resolves to a desk, and that desk is then checked for the action like
#: any other. A party with no desk of its own would resolve to None and be refused.
_PARTY_DESKS: dict[str, str] = {
    "ACCOUNTS_OFFICE": "AG_REVIEWER",
    "ADMIN_DEPARTMENT": "AD_SUBMITTER",
}


def resolve_desk(stated: str | None) -> str | None:
    """The desk id for what a request stated -- an id, the portal's label, or a §4 party."""
    text = (stated or "").strip().casefold()
    if not text:
        return None
    for desk_id, label in DESKS.items():
        if text in (desk_id.casefold(), label.casefold()):
            return desk_id
    for party, desk_id in _PARTY_DESKS.items():
        if text == party.casefold():
            return desk_id
    return None


def desks_for(action: str) -> tuple[str, ...]:
    return tuple(PERMISSIONS[action]["desks"])  # type: ignore[arg-type]


def labels(desk_ids: Iterable[str]) -> str:
    return " or ".join(DESKS[d] for d in desk_ids)


def require_desk(action: str, stated: str | None) -> str:
    """The desk id, where the stated desk may perform ``action``; raises otherwise.

    A request that states no desk is refused too: the SOP has every decision "under the
    officer's own name and desk" (§4.4(6)), and an action nobody's desk is recorded against is
    the gap the sign-in screen exists to close.
    """
    spec = PERMISSIONS[action]
    allowed = desks_for(action)
    desk = resolve_desk(stated)
    if desk is None:
        raise DeskNotAuthorised(
            f"no desk was stated for this request (X-Desk header or 'role'), so it cannot "
            f"{spec['what']}. Sign in at a desk the SOP gives this to: {labels(allowed)}. "
            f"{spec['cite']}."
            + (f" The desk stated, {stated!r}, is not one the portal knows."
               if (stated or "").strip() else "")
        )
    if desk not in allowed:
        raise DeskNotAuthorised(
            f"the desk {DESKS[desk]!r} may not {spec['what']}. The SOP gives this to the "
            f"{labels(allowed)}: {spec['cite']}."
        )
    return desk


def desk_for_account(action: str, account_role: str, stated: str | None) -> str:
    """The desk a signed-in account acts at for ``action``; raises DeskNotAuthorised.

    A stated desk must be one the account holds and one the SOP gives the action to. With none
    stated, the account's first desk that may perform the action is used.
    """
    held = ACCOUNT_DESKS.get(account_role, ())
    spec = PERMISSIONS[action]
    if (stated or "").strip():
        desk = resolve_desk(stated)
        if desk is not None and desk not in held:
            raise DeskNotAuthorised(
                f"this account ({account_role.replace('_', ' ').lower()}) does not hold the desk "
                f"{DESKS[desk]!r}; it may act as {labels(held) if held else 'no desk'}.")
        return require_desk(action, stated)
    for desk in held:
        if desk in desks_for(action):
            return desk
    raise DeskNotAuthorised(
        f"this account ({account_role.replace('_', ' ').lower()}) holds no desk that may "
        f"{spec['what']}. The SOP gives this to the {labels(desks_for(action))}: {spec['cite']}.")


def permissions_table() -> dict:
    """What GET /api/desks returns: the desks and the actions each may perform."""
    return {
        "desks": [{"id": d, "label": lbl,
                   "may": [a for a, s in PERMISSIONS.items()
                           if d in s["desks"]]}  # type: ignore[operator]
                  for d, lbl in DESKS.items()],
        "actions": {a: {"what": s["what"], "desks": list(s["desks"]),  # type: ignore[arg-type]
                        "cite": s["cite"]} for a, s in PERMISSIONS.items()},
        "authenticated": True,
        "account_desks": {role: list(ds) for role, ds in ACCOUNT_DESKS.items()},
        "note": ("Every request is signed in; the desk acted at must be one the signed-in "
                 "account holds (account_desks). X-Desk may choose among them."),
    }
