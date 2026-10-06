"""Disposal, the gates that govern it, and the issue pack. Build specification §13.

Five disposals, and the gates are not advisory:

* **Return to the department** needs at least one observation to issue. A SECOND return needs
  the DAG (Funds) / DAO I under para 3 of the circular.
* **Pass for payment** needs no hard stop, no verification task and no SAP item open. §14
  rule 9 states it as a prohibition, and :func:`disposal_gate` is the single place it lives.
* **Pass for part payment** is the Accounts Officer's or above (Rule 1.35 Explanation).
* **Refer to the DAG (Funds)** and **hold pending verification** are always available.

And the rule that sits above all of them: *no case may be disposed of while any observation is
undisposed.* An officer must have said something about every observation -- uphold, waive,
settle or refer -- before the case leaves the desk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .casefile import CaseFile, NotPermitted
from .contracts import Result
from .engine import RULE_SET_VERSION
from .params import may, who_may

RETURN = "return_to_department"
PASS_FOR_PAYMENT = "pass_for_payment"
PASS_FOR_PART_PAYMENT = "pass_for_part_payment"
REFER_TO_DAG = "refer_to_dag"
HOLD = "hold_pending_verification"

DISPOSALS: tuple[str, ...] = (RETURN, PASS_FOR_PAYMENT, PASS_FOR_PART_PAYMENT, REFER_TO_DAG, HOLD)


@dataclass(frozen=True)
class Gate:
    """Whether a disposal is open, and if not, why not."""

    allowed: bool
    reason: str = ""
    needs_desk: str = ""

    def __bool__(self) -> bool:
        return self.allowed


def disposal_gate(case: CaseFile, disposal: str, desk: str) -> Gate:
    """Whether this desk may dispose of this case this way, now. §13.3."""
    if disposal not in DISPOSALS:
        return Gate(False, f"unknown disposal {disposal!r}; expected one of {list(DISPOSALS)}")
    position = case.position()
    current = case.lists

    # The rule above all the others.
    if position["undisposed"] and disposal != HOLD:
        return Gate(False,
                    f"{position['undisposed']} observation(s) have no disposition recorded. No "
                    f"case may be disposed of while any observation is undisposed (§13.3).")

    if disposal == RETURN:
        if not current.observations:
            return Gate(False, "There is no observation to issue, so there is nothing to return.")
        if case.returns >= 1 and not may(desk, "second_return"):
            return Gate(False,
                        f"This case has already been returned once. A second return needs "
                        f"{who_may('second_return')} (para 3 of the circular).",
                        needs_desk="DAG")
        if not may(desk, "return_case"):
            return Gate(False, f"{who_may('return_case')} or above may return a case.")
        return Gate(True)

    if disposal in (PASS_FOR_PAYMENT, PASS_FOR_PART_PAYMENT):
        permission = ("pass_for_payment" if disposal == PASS_FOR_PAYMENT
                      else "pass_for_part_payment")
        if not may(desk, permission):
            return Gate(False, f"{who_may(permission)} or above may pass a case for payment.")
        # §14 rule 9, in one place. A verification task or an SAP item open is as much a bar
        # as a hard stop: neither has been resolved, and the office's own pending work is not
        # a reason to pay.
        blocking: list[str] = []
        if position["hard"]:
            blocking.append(f"{position['hard']} hard stop(s)")
        if current.verifications:
            blocking.append(f"{len(current.verifications)} verification task(s)")
        if current.sap:
            blocking.append(f"{len(current.sap)} SAP item(s)")
        if blocking:
            return Gate(False,
                        f"Payment is blocked while {', '.join(blocking)} remain open (§13.3, and "
                        f"§14 rule 9).")
        if not reconciles(case):
            return Gate(False,
                        "The GPF Final Re-calculation Report does not reconcile. §12: never let a "
                        "case pass for payment on a report that does not reconcile.")
        return Gate(True)

    return Gate(True)          # refer and hold are always open


def reconciles(case: CaseFile) -> bool:
    """Whether the re-calculation report adds up, row by row. §12, first check.

    ``opening + subscription + adjustments - temporary advance + recovery - permanent advance
    + interest = closing``, and each opening equals the previous closing. §12 records that it
    holds on every row of the corpus except residual 2024-25 and dismissal 2024-25 -- and that
    a case must never pass for payment on a report that does not.

    A case with no report at all is not "reconciled": the SAP items are still open, which the
    gate above has already caught, and answering True here would make this look like a
    property the report has rather than one that was never tested.
    """
    return not recalc_breaks(case)


def recalc_breaks(case: CaseFile) -> tuple[dict[str, Any], ...]:
    """Every row of the report that does not add up, with the arithmetic shown. §12."""
    from .engine import num

    rows = case.facts.recalc_rows
    if not rows:
        return ()
    breaks: list[dict[str, Any]] = []
    previous_closing: int | None = None
    for index, row in enumerate(rows):
        opening = num(row.get("opening")) or 0
        expected = (opening
                    + (num(row.get("subscription")) or 0)
                    + (num(row.get("adjustments")) or 0)
                    - (num(row.get("tempAdvance")) or 0)
                    + (num(row.get("recTempAdvance")) or 0)
                    - (num(row.get("permanentAdvance")) or 0)
                    + (num(row.get("interest")) or 0))
        closing = num(row.get("closing"))
        if closing is not None and expected != closing:
            breaks.append({"row": index + 1, "period": f"{row.get('start')} to {row.get('end')}",
                           "expected": expected, "printed": closing,
                           "difference": closing - expected,
                           "why": "the row does not add up"})
        if previous_closing is not None and opening != previous_closing:
            breaks.append({"row": index + 1, "period": f"{row.get('start')} to {row.get('end')}",
                           "expected": previous_closing, "printed": opening,
                           "difference": opening - previous_closing,
                           "why": "the opening balance does not equal the previous closing"})
        previous_closing = closing
    return tuple(breaks)


def dispose(case: CaseFile, disposal: str, *, by: str, desk: str, at: str,
            note: str = "") -> dict[str, Any]:
    """Dispose of the case, or refuse and say why. §13.3."""
    gate = disposal_gate(case, disposal, desk)
    if not gate:
        raise NotPermitted(gate.reason)
    if disposal == RETURN:
        case.returns += 1
    case.case_decision = disposal
    case.case_note = note
    case.log("dispose-case", f"{disposal}" + (f" — {note}" if note else ""),
             by=by, desk=desk, at=at, after={"disposal": disposal, "returns": case.returns})
    return {"disposal": disposal, "returns": case.returns, "at": at, "by": by, "desk": desk}


# -- the issue pack, §13.4 -------------------------------------------------------------------

def issue_pack(case: CaseFile) -> dict[str, Any]:
    """Everything §13.4 requires the pack to carry.

    The rejection form and the advisory memorandum are SEPARATE lists: §5.1 of the SOP-side
    circular and §13.1 here both keep missing documents apart from defective ones, because
    the department does different things about each. The office copy carries the waived and
    settled observations with their grounds and authority, which is what makes an override
    auditable rather than merely recorded.
    """
    current = case.lists
    dispositions = case.dispositions
    waived = [d for d in dispositions.values() if d.action == "waive"]
    settled = [d for d in dispositions.values() if d.action == "settle"]

    def form_line(result: Result) -> dict[str, Any]:
        return {"id": result.id, "code": result.code, "ref": result.ref,
                "document": result.doc, "checklist": result.checklist,
                "finding": result.finding, "remedy": result.remedy,
                "evidence": [e.to_dict() for e in result.evidence]}

    return {
        "case_ref": case.case_ref,
        "version": case.version,
        "rule_set": dict(RULE_SET_VERSION),
        # What issues to the department, in ONE instance (circular para 2).
        "rejection_form": [form_line(r) for r in current.hard],
        "advisory_memorandum": [form_line(r) for r in current.advisory],
        # The office's own work. Never on the department's form (§6.1, §14 rule 9).
        "verifications_recorded": [
            {"id": r.id, "title": r.title, "finding": r.finding, "remedy": r.remedy}
            for r in current.verifications],
        "sap_items": [{"id": r.id, "title": r.title, "finding": r.finding} for r in current.sap],
        "office_copy": {
            "waived": [d.to_dict() for d in waived],
            "settled": [d.to_dict() for d in settled],
        },
        "all_checks": [{"id": r.id, "status": r.status, "title": r.title, "ref": r.ref}
                       for r in case.results],
        "uploads": [u.to_dict() for u in case.uploads],
        "sap_extracts": [{k: v for k, v in e.to_facts_fragment().items()
                          if k not in ("payslip", "recalc")} for e in case.sap_extracts],
        "case_history": [v.to_dict() for v in case.versions],
        "audit_trail": [e.to_dict() for e in case.audit],
        # Circular C(i) and para 2: the register entry and the portal comment.
        "payment_register_entry": _register_entry(case),
        "portal_comment": _portal_comment(case),
        "recalc_breaks": list(recalc_breaks(case)),
    }


def _register_entry(case: CaseFile) -> dict[str, Any]:
    """The GP Fund Payment Register entry. Circular C(i)."""
    claim = case.facts.claim or {}
    return {"case_ref": case.case_ref, "personnel_no": case.facts.personnel_no,
            "case_kind": case.facts.kind, "amount_claimed": claim.get("amount"),
            "disposal": case.case_decision, "case_version": case.version}


def _portal_comment(case: CaseFile) -> str:
    """The Employee Service Portal comment text. Circular para 2, and open item GPF-O3.

    Plain, and it never quotes a rejection code at a subscriber: the codes are the office's
    internal reference and mean nothing to the person waiting. What the subscriber needs to
    know is whether anything is required of them.
    """
    current = case.lists
    if case.case_decision == PASS_FOR_PAYMENT:
        return ("Your GP Fund case has been examined and passed for payment. Nothing further is "
                "required from you.")
    if case.case_decision == RETURN:
        count = len(current.observations)
        thing = "point" if count == 1 else "points"
        return (f"Your GP Fund case has been returned to your department for correction on "
                f"{count} {thing}. Your department has been told what to correct. You need do "
                f"nothing; the department will resubmit the case.")
    if current.sap or current.verifications:
        return ("Your GP Fund case is under examination in this office. Nothing is required from "
                "you at present.")
    return "Your GP Fund case is under examination in this office."
