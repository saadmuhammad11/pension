"""Final payments: fresh, death, dismissal and residual. Build specification §5.3, §12.

Two ideas run through this module, and both came out of the office's review (§16.3).

**A partial scan is not a missing document.** Where the forwarding letter says the original
Service Book is attached but it is not in the scan, or only its cover is, the entries are
checked on the ORIGINAL and the result is a verification task. Revision 1 made that a hard
stop and sent a department a shortcoming for a book it had sent.

**The corpus is retrospective, so SAP already posts the claim.** All three final payments show
a permanent advance in the report equal to the claim, because the reports were pulled on
10-09-2026 after the office had processed the cases. §12 is explicit that such a posting *is*
the claim, confirmed by its pay order, and never a double-payment accusation.
"""

from __future__ import annotations

from typing import Any

from .contracts import ADV, CONF, FINALS, HARD, NA, OK, SAP, Facts
from .engine import check, digits, ev, fmt, num, verified, verified_result
from .params import CLAIM_TOLERANCE


def _doc_cure(doc_type: str, apply: str, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"kind": "doc", "docType": doc_type, "apply": apply, "fields": fields or []}


# -- the checklist items, A2-ii to A2-vii ---------------------------------------------------

check(
    id="FP-GPF10", group="checklist", checklist="A2-ii", ref="A2-ii · B2-i", code="B2-i",
    title="G.P.F. Form 10, properly filled and signed",
    applies=lambda facts: facts.is_kind(*FINALS),
    run=lambda facts: _fp_gpf10(facts),
)


def _fp_gpf10(facts: Facts) -> dict[str, Any]:
    """Form 10, and the identifiers SAP already holds.

    A missing IDENTIFIER on the form reduces to an observation where SAP holds it: §16.3
    overturned revision 1's hard stop on the non-gazetted case, whose Form 10 omits the old
    account number that Form 06, the Service Book cover and the SAP pay slip all carry. A
    missing SIGNATURE is not in that class and stays a hard stop.
    """
    form = facts.doc("gpf10")
    if not form or not form.get("present"):
        residual = facts.is_kind("residual")
        return {"status": HARD,
                "finding": ("G.P.F. Form 10 is not on file"
                            + (", and nothing in the case substitutes for it."
                               if residual else ".")),
                "remedy": ("Submit Form 10 signed by the DDO and the subscriber or claimant"
                           + (", or the officer confirms that the Form 10 filed with the original "
                              "final payment covers the residual." if residual else ".")),
                "cure": _doc_cure("G.P.F. Form 10", "add-gpf10", [
                    {"k": "accountNo", "label": "GP Fund account no.", "type": "text",
                     "expect": facts.personnel_no},
                    {"k": "signed", "label": "Signed by subscriber or claimant", "type": "yesno"},
                    {"k": "ddoSigned", "label": "Signed by DDO", "type": "yesno"}])}
    missing = list(form.get("missing") or [])
    if not missing:
        note = f" {form.get('note')}" if form.get("note") else ""
        return {"status": OK,
                "finding": (f"Form 10 at page {form.get('page')}, account no. "
                            f"{form.get('accountNo') or ''}, signed.{note}"),
                "evidence": [ev(form.get("page"), "Form 10", form.get("crop"))]}
    payslip = facts.sap_payslip
    only_identifiers = all(
        any(word in str(item).lower() for word in ("account", "a/c", "personnel"))
        for item in missing)
    sap_covers = bool(payslip and only_identifiers
                      and (payslip.get("oldGpfNo") or payslip.get("persNo")))
    held = (form.get("corroboration") or "The missing identifiers are held in SAP")
    return {"status": ADV if sap_covers else HARD,
            "finding": (f"Form 10 at page {form.get('page')} does not state: "
                        f"{', '.join(missing)}."
                        + (f" {held}, so this is noted only." if sap_covers else "")),
            "remedy": f"Complete Form 10: {', '.join(missing)}.",
            "evidence": [ev(form.get("page"), "Form 10", form.get("crop"))],
            "cure": _doc_cure("Completed G.P.F. Form 10", "gpf10-complete", [
                {"k": f"m{index}", "label": f"{item} now filled in", "type": "yesno"}
                for index, item in enumerate(missing)])}


check(
    id="FP-NOTIF", group="checklist", checklist="A2-iii", ref="A2-iii",
    title="Retirement, dismissal or obituary notification",
    applies=lambda facts: facts.is_kind(*FINALS),
    run=lambda facts: _fp_notif(facts),
)


def _fp_notif(facts: Facts) -> dict[str, Any]:
    notif = facts.doc("notification")
    if notif and notif.get("present"):
        note = f" {notif.get('note')}" if notif.get("note") else ""
        return {"status": OK,
                "finding": (f"{notif.get('label') or 'Notification'} No. "
                            f"{notif.get('no') or '(not stated)'} dated "
                            f"{notif.get('date') or '(not stated)'}, page {notif.get('page')}.{note}"),
                "evidence": [ev(notif.get("page"), notif.get("label") or "Notification",
                                notif.get("crop"))]}
    which = ("obituary" if facts.is_kind("death")
             else "dismissal" if facts.is_kind("dismissal") else "retirement")
    return {"status": HARD, "code": "A2-iii",
            "finding": f"The {which} notification is not on file.",
            "remedy": "Attach a copy of the notification.",
            "cure": _doc_cure("Notification", "add-notification", [
                {"k": "no", "label": "Notification no.", "type": "text"},
                {"k": "date", "label": "Date", "type": "text"}])}


check(
    id="FP-CNIC", group="checklist", checklist="A2-iv", ref="A2-iv · R5",
    title="Copy of CNIC of the subscriber",
    applies=lambda facts: facts.is_kind(*FINALS),
    run=lambda facts: _fp_cnic(facts),
)


def _fp_cnic(facts: Facts) -> dict[str, Any]:
    card = next((c for c in facts.cnics
                 if any(word in str(c.get("whose") or "subscriber")
                        for word in ("subscriber", "deceased"))), None)
    if card:
        return {"status": OK,
                "finding": (f"CNIC copy of the {card.get('whose') or 'subscriber'} at page "
                            f"{card.get('page')}, no. {card.get('number')}. Attestation is not "
                            f"required (R5)."),
                "evidence": [ev(card.get("page"), "CNIC", card.get("crop"))]}
    return {"status": HARD, "code": "A2-iv",
            "finding": "No copy of the subscriber’s CNIC is on file.",
            "remedy": "Attach a copy of the subscriber’s CNIC.",
            "cure": _doc_cure("CNIC copy", "add-cnic", [
                {"k": "number", "label": "CNIC number", "type": "text"},
                {"k": "type", "label": "Card type", "type": "select",
                 "options": ["smart", "old"]}])}


check(
    id="FP-FORM06", group="checklist", checklist="A2-v", ref="A2-v · B2-iii · B2-v",
    title="Change Form-06 signed by DDO and subscriber",
    applies=lambda facts: facts.is_kind(*FINALS),
    run=lambda facts: _fp_form06(facts),
)


def _fp_form06(facts: Facts) -> dict[str, Any]:
    form = facts.doc("changeForm")
    if not form or not form.get("present"):
        return {"status": HARD, "code": "B2-iii", "finding": "Change Form-06 is not attached.",
                "remedy": "Attach Change Form-06 signed by the DDO and the subscriber.",
                "cure": _doc_cure("Change Form-06", "add-form", [
                    {"k": "personalNo", "label": "Personal number on the form", "type": "text",
                     "expect": facts.personnel_no},
                    {"k": "signed", "label": "Signed or thumbed by subscriber/claimant",
                     "type": "yesno"},
                    {"k": "ddoSigned", "label": "Signed and stamped by the DDO", "type": "yesno"}])}
    gaps: list[str] = []
    if not form.get("ddoSigned"):
        gaps.append("the DDO")
    if not form.get("sigKind") or form.get("sigKind") == "none":
        gaps.append("the claimant" if facts.is_kind("death") else "the subscriber")
    if gaps:
        return {"status": HARD, "code": "B2-v",
                "finding": (f"Change Form-06 at page {form.get('page')} is not signed by "
                            f"{' or '.join(gaps)}."),
                "remedy": "Obtain the missing signature.",
                "evidence": [ev(form.get("page"), "Form 06")],
                "cure": _doc_cure("Signed Change Form-06", "form-signatures", [
                    {"k": "ddoSigned", "label": "Signed and stamped by the DDO", "type": "yesno"},
                    {"k": "signed", "label": "Signed or thumbed by subscriber/claimant",
                     "type": "yesno"}])}
    # A thumb impression IS a signature for this purpose. R7 handles whose thumb it is; the
    # form is not defective for carrying one.
    how = "thumbed" if form.get("sigKind") == "thumb" else "signed"
    whose = "claimant" if facts.is_kind("death") else "subscriber"
    note = f" {form.get('note')}" if form.get("note") else ""
    return {"status": OK,
            "finding": (f"Change Form-06 at page {form.get('page')}, signed by the DDO and {how} "
                        f"by the {whose}.{note}"),
            "evidence": [ev(form.get("page"), "Form 06", form.get("crop"))]}


check(
    id="FP-OLDAC", group="identity", ref="B2-vii", code="B2-vii",
    title="Old GP Fund account no. on the change form",
    applies=lambda facts: bool(facts.is_kind(*FINALS)
                               and (facts.doc("changeForm") or {}).get("present")),
    run=lambda facts: _fp_oldac(facts),
)


def _fp_oldac(facts: Facts) -> dict[str, Any]:
    """The manual-era account number, or the reason there is none.

    §16.3, lesson 3: in the SAP era the personnel number keys the GP Fund account, and a
    ledger that OPENS AT NIL proves there was no manual-era account to quote. Revision 1
    raised a hard stop on the residual case for an account number that never existed.
    """
    form = facts.doc("changeForm") or {}
    payslip = facts.sap_payslip
    rows = facts.recalc_rows
    sap_old = (payslip.get("oldGpfNo")
               if payslip and payslip.get("oldGpfNo") and len(digits(payslip.get("oldGpfNo"))) > 3
               else None)
    form_old = form.get("oldGpfNo")

    if form_old and len(digits(form_old)) > 3:
        if sap_old and digits(sap_old) != digits(form_old):
            return {"status": HARD,
                    "finding": (f"Old A/c {form_old} on the form; SAP pay slip Old # reads "
                                f"{sap_old}."),
                    "remedy": "Reconcile the old account number."}
        agrees = f", agreeing with SAP Old # {sap_old}." if sap_old else "."
        return {"status": OK, "finding": f"Old GP Fund A/c {form_old} on the form{agrees}"}

    state = form.get("oldGpfNoState") or "blank"
    if sap_old:
        return {"status": ADV,
                "finding": (f"The old account number is not written on the form ({state}), but "
                            f"SAP holds it as {sap_old}. Noted; the office settles it from SAP."),
                "remedy": "None needed to process."}
    if not payslip:
        return {"status": SAP,
                "finding": ("The old account number is not written on the form. The SAP pay slip "
                            "may carry it."),
                "cure": {"kind": "sap"}}
    first = rows[0] if rows else None
    if first and not num(first.get("opening")):
        return {"status": OK,
                "finding": (f"Field 16 is {state}, but SAP holds no old number and the SAP ledger "
                            f"opens at nil in {first.get('start')} to {first.get('end')}, so there "
                            f"is no manual-era account to quote.")}
    opening = (f", but the SAP ledger opens with Rs {fmt(first.get('opening'))}, so a manual-era "
               f"account may exist." if first else ".")
    return {"status": CONF,
            "finding": f"Field 16 is {state} and SAP holds no old number{opening}",
            "remedy": "Confirm the manual-era account number from the AG ledger.",
            "cure": {"kind": "verify", "vid": "FP-OLDAC"}}


check(
    id="FP-SB", group="checklist", checklist="A2-vii", ref="A2-vii · B2-viii", code="B2-viii",
    title="Original Service Book (non-gazetted)",
    applies=lambda facts: (facts.is_kind("final", "death", "dismissal")
                           and facts.gazetted == "non-gazetted"),
    run=lambda facts: _fp_service_book(facts),
)


def _fp_service_book(facts: Facts) -> dict[str, Any]:
    """§5.3 FP-SB, and the sentence that governs it: *a partial scan is never a hard stop
    by itself.*

    Three situations. The book is not in the case but the forwarding letter says the original
    is attached -- a verification on the original. Only some pages are scanned -- the entries
    that are not on those pages cannot be SEEN, which does not show they are missing from the
    original. Nothing at all for a non-gazetted subscriber -- a hard stop, because the
    circular requires the book.
    """
    book = facts.doc("serviceBook")
    cure = _doc_cure("Service Book pages", "add-servicebook", [
        {"k": "dor", "label": "Date of retirement or event entered", "type": "yesno"},
        {"k": "order", "label": "Order entered", "type": "yesno"},
        {"k": "leave", "label": "Leave account present", "type": "yesno"}])

    if not book or not book.get("present"):
        if book and book.get("reportedAttached"):
            record = verified(facts, "FP-SB")
            if record:
                if record.get("ok"):
                    note = f": {record.get('note')}" if record.get("note") else "."
                    return {"status": OK,
                            "finding": (f"Original Service Book received and entries checked by "
                                        f"{record.get('by')}{note}")}
                return {"status": HARD,
                        "finding": (f"Original Service Book not received, or entries missing. "
                                    f"{record.get('note') or ''}"),
                        "remedy": "Produce the original Service Book.", "cure": cure}
            return {"status": CONF,
                    "finding": (f"{book['reportedAttached']} It is not in the scanned case, so the "
                                f"entries (date of the event, the order, leave account) cannot be "
                                f"checked from the file."),
                    "remedy": ("Confirm the original Service Book is on hand and check the "
                               "entries."),
                    "cure": {"kind": "verify", "vid": "FP-SB"}}
        return {"status": HARD,
                "finding": "No Service Book is on file for a non-gazetted subscriber.",
                "remedy": "Produce the original Service Book.", "cure": cure}

    entries = book.get("entries") or {}
    missing: list[str] = []
    if not entries.get("dor"):
        missing.append("date of retirement")
    if not entries.get("order"):
        missing.append("order of retirement")
    if not entries.get("leave"):
        missing.append("leave account")
    if not missing:
        return {"status": OK, "finding": "Service Book carries the requisite entries."}

    record = verified(facts, "FP-SB")
    if record:
        if record.get("ok"):
            note = f": {record.get('note')}" if record.get("note") else "."
            return {"status": OK,
                    "finding": (f"Entries checked on the original Service Book by "
                                f"{record.get('by')}{note}")}
        return {"status": HARD,
                "finding": (f"The original Service Book does not show: {', '.join(missing)}. "
                            f"{record.get('note') or ''}"),
                "remedy": "Department to complete the Service Book entries.", "cure": cure}
    what = book.get("note") or f"pages {', '.join(str(p) for p in (book.get('pages') or []))}"
    return {"status": CONF,
            "finding": (f"Only {what} of the Service Book are in the scanned case, so the "
                        f"{', '.join(missing)} cannot be seen. That does not show they are missing "
                        f"from the original."),
            "remedy": ("Check the entries on the original Service Book and record the result. If "
                       "they are missing, the department completes them (B2-viii)."),
            "evidence": [ev(page, "Service Book") for page in (book.get("pages") or [])],
            "cure": {"kind": "verify", "vid": "FP-SB"}}


# -- the claim against the SAP report, §12 ---------------------------------------------------

def posted_claim(facts: Facts) -> dict[str, Any] | None:
    """The report row whose permanent advance equals the claim, or ``None``. §12.

    Matching on an identity within one rupee, not an approximation: the whole inference is
    that this posting IS the claim, and a loose match would turn an unrelated payment into a
    confirmation.
    """
    rows = facts.recalc_rows
    claim = facts.claim
    amount = num(claim.get("amount")) if claim else None
    if not rows or not amount:
        return None
    for row in rows:
        posted = num(row.get("permanentAdvance"))
        if posted and abs(posted - amount) <= CLAIM_TOLERANCE:
            return {"row": row, "last": rows[-1]}
    return None


check(
    id="FP-POSTED", group="balance", ref="R11", code="R11", title="Claim already posted in SAP",
    applies=lambda facts: bool(facts.is_kind("final", "death", "dismissal")
                               and facts.sap_recalc and facts.claim),
    run=lambda facts: _fp_posted(facts),
)


def _fp_posted(facts: Facts) -> dict[str, Any]:
    """A posting equal to the claim is the claim. §12, §16.3 lesson 5.

    The office's reports were pulled after it processed the cases, so all three final payments
    already show the claim posted. The module says so, asks the section to record the pay
    order, and states the alternative plainly -- if it were a separate earlier payment, paying
    the claim would pay it twice. What it does not do is accuse anyone of a double payment.
    """
    posted = posted_claim(facts)
    recalc = facts.sap_recalc or {}
    if not posted:
        return {"status": OK,
                "finding": ("SAP posts no permanent advance equal to the claim, so nothing has "
                            "been paid against it yet.")}
    record = verified(facts, "FP-POSTED")
    if record:
        return verified_result(
            record, "The SAP posting is this claim; pay order recorded.",
            "The SAP posting is a separate earlier payment, so paying the claim would pay it twice.")
    row = posted["row"]
    claim = facts.claim or {}
    basis = claim.get("basis") or f"Rs {fmt(claim.get('amount'))}"
    return {"status": CONF,
            "finding": (f"SAP already posts a permanent advance of Rs "
                        f"{fmt(row.get('permanentAdvance'))} in {row.get('start')} to "
                        f"{row.get('end')}, equal to the claim ({basis}). The report was pulled "
                        f"after the office processed the case, so this is most likely the claim "
                        f"itself. If it were a separate earlier payment, paying the claim would "
                        f"pay it twice."),
            "remedy": ("Before payment, confirm from the SAP ledger or the GP Fund Payment "
                       "Register that the posting is this claim, and record the pay order."),
            "evidence": ([ev(recalc.get("page"), "Re-calculation report")]
                         if recalc.get("page") else []),
            "cure": {"kind": "verify", "vid": "FP-POSTED"}}


check(
    id="FP-RESIDUAL", group="balance", ref="B2-vi", code="B2-vi",
    title="Balance left in SAP after the claim",
    applies=lambda facts: bool(facts.is_kind("final", "death", "dismissal")
                               and posted_claim(facts)),
    run=lambda facts: _fp_residual(facts),
)


def _fp_residual(facts: Facts) -> dict[str, Any]:
    """What is left after the posting is a residual due to the family, not a discrepancy."""
    posted = posted_claim(facts)
    assert posted is not None
    left = num(posted["last"].get("closing")) or 0
    claim = facts.claim or {}
    recalc = facts.sap_recalc or {}
    if left <= 0:
        return {"status": OK, "finding": "Nothing is left in SAP after the posting."}
    if claim.get("residualNote"):
        return {"status": NA,
                "finding": (f"Rs {fmt(left)} is left in SAP after the posting. "
                            f"{claim['residualNote']}")}
    made_of = f": {claim.get('residualMadeOf')}" if claim.get("residualMadeOf") else ""
    whose = "entitled family" if facts.is_kind("death") else "subscriber"
    return {"status": ADV,
            "finding": (f"After the Rs {fmt(claim.get('amount'))} posting, SAP still holds "
                        f"Rs {fmt(left)}{made_of}. A residual payment appears due to the {whose}."),
            "remedy": "Section to process the residual on a residual claim.",
            "evidence": ([ev(recalc.get("page"), "Re-calculation report")]
                         if recalc.get("page") else [])}


# -- death cases, §5.3 ----------------------------------------------------------------------

check(
    id="DEATH-HEIRS", group="checklist", checklist="A2-iv", ref="A2-iv", code="A2-iv",
    title="CNIC copies of all legal heirs",
    applies=lambda facts: bool(facts.is_kind("death") and facts.doc("death")),
    run=lambda facts: _death_heirs(facts),
)


def _death_heirs(facts: Facts) -> dict[str, Any]:
    """A copy for every ADULT heir; minors are covered by the NADRA certificate.

    Whether the QR-linked family registration certificate substitutes for an adult heir's
    copy, and whether an adult son who takes no share under Rule 1.34 must supply one at all,
    are open item GPF-O23. Until the office decides, the circular is followed as written.
    """
    heirs = (facts.doc("death") or {}).get("heirs") or []
    if not heirs:
        return {"status": CONF,
                "finding": "The legal heirs could not be established from the case.",
                "cure": {"kind": "verify", "vid": "DEATH-HEIRS"}}
    missing = [h for h in heirs if not h.get("cnicCopy") and not h.get("minor")]
    if not missing:
        adults = ", ".join(h.get("name") for h in heirs if not h.get("minor"))
        minors = [h.get("name") for h in heirs if h.get("minor")]
        tail = (f" Minor heirs: {', '.join(minors)}, covered by the NADRA family registration "
                f"certificate." if minors else "")
        return {"status": OK, "finding": f"Copies on file for every adult legal heir: {adults}.{tail}"}
    detail = ", ".join(f"{h.get('name')} ({h.get('relation')})" for h in missing)
    return {"status": HARD, "finding": f"No CNIC copy for {detail}.",
            "remedy": "Attach CNIC copies for every adult legal heir.",
            "cure": _doc_cure("CNIC copy of legal heir", "add-heir-cnic", [
                {"k": "name", "label": "Heir", "type": "select",
                 "options": [h.get("name") for h in missing]},
                {"k": "number", "label": "CNIC number", "type": "text"}])}


check(
    id="DEATH-AFFIDAVIT", group="checklist", checklist="A2-vi", ref="A2-vi", code="A2-vi",
    title="Original affidavit for lawful widow",
    applies=lambda facts: bool(facts.is_kind("death")
                               and (facts.doc("death") or {}).get("widowClaim")),
    run=lambda facts: _death_affidavit(facts),
)


def _death_affidavit(facts: Facts) -> dict[str, Any]:
    """An undertaking on stamp paper is not an affidavit for lawful widow. §4.1.

    Two distinct artefact types, and the corpus shows why the distinction is not pedantry:
    the document on file covers liability for Government dues, is worded for family pension,
    is undated, and the claimant has not signed it.
    """
    affidavit = (facts.doc("death") or {}).get("affidavit") or {}
    if affidavit.get("present") and affidavit.get("original"):
        return {"status": OK,
                "finding": f"{affidavit.get('label') or 'Affidavit'} at page {affidavit.get('page')}.",
                "evidence": [ev(affidavit.get("page"), "Affidavit")]}
    if affidavit.get("present"):
        finding = (f"{affidavit.get('label') or 'The document'} at page {affidavit.get('page')} is "
                   f"not an affidavit for lawful widow. {affidavit.get('note') or ''}")
    else:
        finding = "No affidavit for lawful widow is on file."
    return {"status": HARD, "finding": finding,
            "remedy": "Produce the original affidavit for lawful widow.",
            "evidence": ([ev(affidavit.get("page"), affidavit.get("label") or "Document")]
                         if affidavit.get("page") else []),
            "cure": _doc_cure("Original affidavit for lawful widow", "add-affidavit", [
                {"k": "original", "label": "Original, on stamp paper, attested", "type": "yesno"}])}


check(
    id="DEATH-SUCCESSION", group="checklist", checklist="A2-vi", ref="A2-vi · R13", code="A2-vi",
    title="Succession certificate, or OSD post created",
    applies=lambda facts: bool(facts.is_kind("death") and facts.doc("death")),
    run=lambda facts: _death_succession(facts),
)


def _death_succession(facts: Facts) -> dict[str, Any]:
    """R13: an OSD post on the SAP pay slip removes the succession certificate.

    An OSD annotation that is NOT on the pay slip is a verification task, not an acceptance:
    the annotation is a department's assertion and R13 turns on what SAP shows.

    The statutory guard §5.3 requires -- Rule 1.35 applying section 4 of the Provident Funds
    Act 1925, where a payee is neither family under Rule 1.2(1)(c) nor a dependant nominee,
    no nomination subsists and the balance exceeds Rs 5,000 -- is in
    :func:`gpfund.rules_statutory.statutory_guard`, raised as a separate officer-decision item
    so it can fire even when an OSD post exists.
    """
    death = facts.doc("death") or {}
    payslip = facts.sap_payslip
    osd_field = str((payslip or {}).get("osdPost") or "")
    osd_in_sap = bool(payslip and osd_field
                      and any(word in osd_field.lower() for word in ("yes", "created", "osd")))

    if osd_in_sap:
        return {"status": OK,
                "finding": (f"The SAP pay slip shows an OSD post created ({osd_field}). A "
                            f"succession certificate is not required (R13).")}
    if death.get("successionCert") == "granted":
        return {"status": OK,
                "finding": f"Succession certificate granted, page {death.get('successionPage')}."}
    if death.get("successionRequired") is False:
        return {"status": OK,
                "finding": (f"Not required: {death.get('successionNote') or 'one widow and heirs '
                            'within the family.'}")}
    if not payslip:
        return {"status": SAP,
                "finding": (f"Succession certificate: {death.get('successionNote') or 'not on file'}. "
                            f"If SAP shows an OSD post created, it is not required (R13). Pull the "
                            f"pay slip first."),
                "cure": {"kind": "sap"}}
    annotation = death.get("osdAnnotation")
    if annotation:
        record = verified(facts, "DEATH-OSD")
        if record:
            if record.get("ok"):
                note = f": {record.get('note')}" if record.get("note") else ""
                return {"status": OK,
                        "finding": (f"OSD post creation confirmed in SAP by {record.get('by')}"
                                    f"{note}. Succession certificate not required (R13).")}
            return {"status": HARD,
                    "finding": (f"SAP does not show an OSD post, and no succession certificate is "
                                f"on file. {death.get('successionNote') or ''}"),
                    "remedy": "Produce the succession certificate granted by the court.",
                    "cure": _doc_cure("Succession certificate", "add-succession", [
                        {"k": "granted", "label": "Certificate granted by the court",
                         "type": "yesno"}])}
        return {"status": CONF,
                "finding": (f"{annotation.get('where')} is annotated \"{annotation.get('text')}\", "
                            f"but the SAP pay slip in the case carries no OSD post indicator. "
                            f"{death.get('successionNote') or ''}"),
                "remedy": ("Confirm in SAP whether an OSD post was created. If so no succession "
                           "certificate is needed (R13)."),
                "cure": {"kind": "verify", "vid": "DEATH-OSD"},
                "evidence": [ev(annotation.get("page"), "OSD annotation", annotation.get("crop"))]}
    return {"status": HARD,
            "finding": f"No succession certificate. {death.get('successionNote') or ''}",
            "remedy": ("Produce the succession certificate, or evidence from SAP that an OSD post "
                       "was created."),
            "cure": _doc_cure("Succession certificate", "add-succession", [
                {"k": "granted", "label": "Certificate granted by the court", "type": "yesno"}])}
