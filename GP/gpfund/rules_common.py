"""Checks that apply across case families. Build specification §5.1.

Eleven checks, and several of them exist to STOP the module raising something. R3 keeps the
covering letter off the observation list; R5 reduces an unattested CNIC or pay slip to an
observation; R10 makes an unreadable code an observation rather than a defect; R7 stops the
module claiming anything at all about a thumb impression. The office's review of revision 1
found each of those raised too hard, and §16.3 keeps them as permanent regression cases.
"""

from __future__ import annotations

from typing import Any

from .contracts import ADV, CONF, FINALS, HARD, NA, OK, SAP, Facts
from .doa import active_register
from .engine import check, digits, ev, fmt, verified, verified_result

ADVANCES = ("refundable", "nonrefundable")


# -- R1, R8, R11: the SAP extracts ----------------------------------------------------------
#
# The office's first clarification, and the one that reframed the whole module: the pay slip
# and the re-calculation report are ticked off if present and PULLED BY THIS SECTION if not.
# A missing extract is therefore never a department defect -- it is `sap`, an action for the
# office, which is why the status vocabulary has a seventh entry at all (§4.4, §6.1).

def _sap_need(facts: Facts) -> str:
    if facts.is_kind(*FINALS):
        return "Required with the pay slip for a final payment (R11)."
    if facts.is_kind(*ADVANCES):
        return "Needed to establish the balance for the limit test and the advance position."
    return "Shows whether the months in question are already credited."


check(
    id="SAP-PAYSLIP", group="sap", ref="R1 · R8", checklist="SAP",
    title="SAP pay slip of the subscriber",
    applies=lambda facts: True,
    run=lambda facts: _sap_payslip(facts),
)


def _sap_payslip(facts: Facts) -> dict[str, Any]:
    payslip = facts.sap_payslip
    if payslip:
        where = (f"found in the case at page {payslip.get('page')}"
                 if facts.sap_source == "case"
                 else f"uploaded from SAP ({(facts.sap or {}).get('file')})")
        return {
            "status": OK,
            "finding": (f"Pay slip for {payslip.get('month') or 'the month shown'}, personnel "
                        f"no. {payslip.get('persNo')}, {where}."),
            "evidence": [ev(payslip.get("page"), "SAP pay slip")] if payslip.get("page") else [],
        }
    return {
        "status": SAP,
        "finding": (f"No SAP pay slip is in the case. Pull it from SAP against personnel no. "
                    f"{facts.personnel_no or '(not stated)'} and upload it on the SAP extracts step."),
        "remedy": "Action for this section. Not a defect of the department.",
        "cure": {"kind": "sap"},
    }


check(
    id="SAP-RECALC", group="sap", ref="R1 · R11", checklist="SAP",
    title="GPF Final Re-calculation Report from SAP",
    applies=lambda facts: True,
    run=lambda facts: _sap_recalc(facts),
)


def _sap_recalc(facts: Facts) -> dict[str, Any]:
    recalc = facts.sap_recalc
    rows = facts.recalc_rows
    need = _sap_need(facts)
    if recalc and rows:
        last = rows[-1]
        where = (f"found in the case at page {recalc.get('page')}"
                 if facts.sap_source == "case"
                 else f"uploaded from SAP ({(facts.sap or {}).get('file')})")
        dated = f"dated {recalc.get('reportDate')}, " if recalc.get("reportDate") else ""
        return {
            "status": OK,
            "finding": (f"Report {dated}{where}. Last period {last.get('start')} to "
                        f"{last.get('end')}, closing balance Rs {fmt(last.get('closing'))}. {need}"),
            "evidence": ([ev(recalc.get("page"), "GPF Final Re-calculation Report")]
                         if recalc.get("page") else []),
        }
    return {
        "status": SAP,
        "finding": f"No GPF Final Re-calculation Report is in the case. {need}",
        "remedy": (f"Pull the report from SAP against personnel no. "
                   f"{facts.personnel_no or '(not stated)'} and upload it."),
        "cure": {"kind": "sap"},
    }


check(
    id="SAP-IDENTITY", group="identity", ref="R1",
    title="SAP extract belongs to this subscriber",
    applies=lambda facts: bool(facts.sap and (facts.sap_payslip or facts.sap_recalc)),
    run=lambda facts: _sap_identity(facts),
)


def _sap_identity(facts: Facts) -> dict[str, Any]:
    """An extract for another employee is a hard stop, not a warning.

    §6.1: "An extract whose personnel number differs from the case is rejected with the
    reason, and the rejection is logged." It reaches here as well as the upload gate because
    an extract that came in the bundle never passed that gate -- and §16.1 records that the
    refundable case's own CNIC page carries a fragment of a different employee's SAP report.
    """
    want = digits(facts.personnel_no)
    wrong: list[str] = []
    for label, part in (("pay slip", facts.sap_payslip), ("re-calculation report", facts.sap_recalc)):
        if part and part.get("persNo") and want and digits(part.get("persNo")) != want:
            wrong.append(f"the {label} is for personnel no. {part.get('persNo')}")
    if wrong:
        return {
            "status": HARD, "code": "R1",
            "finding": (f"The case is for personnel no. {facts.personnel_no} but "
                        f"{' and '.join(wrong)}."),
            "remedy": "Pull the extract for the correct personnel number.",
            "cure": {"kind": "sap"},
        }
    return {"status": OK,
            "finding": f"Personnel no. {facts.personnel_no} on every SAP extract."}


# -- R3: the covering letter is never an observation -----------------------------------------

check(
    id="COVER", group="checklist", ref="A2-i · A3-ii · A4-i · R3",
    title="Covering / forwarding letter",
    checklist=lambda facts: ("A3-ii" if facts.is_kind("balance_transfer")
                             else "A4-i" if facts.is_kind("missing_credits") else "A2-i"),
    applies=lambda facts: not facts.is_kind(*ADVANCES),
    run=lambda facts: _cover(facts),
)


def _cover(facts: Facts) -> dict[str, Any]:
    """Recorded, never examined. R3.

    The office's third clarification is flat: the covering letter is always correct and is
    never an observation. It is still RECORDED, because §13.1 has an "all checks" list that
    is the office record of what was checked -- including what passed.
    """
    letter = facts.doc("covering") or {}
    if letter.get("present"):
        what = (f"{letter.get('nature') or 'Forwarding instrument'}"
                + (f" from {letter.get('author')}" if letter.get("author") else "")
                + (f", page {letter.get('page')}" if letter.get("page") else "") + ".")
    else:
        what = "No separate letter on file."
    return {
        "status": OK,
        "finding": (f"{what} Accepted under office practice: the covering letter is the "
                    f"authority’s notice to process the case and is not examined further (R3)."),
        "evidence": ([ev(letter.get("page"), "Covering letter", letter.get("crop"))]
                     if letter.get("page") else []),
    }


# -- R5: attestation of CNIC copies and pay slips is not required ---------------------------

check(
    id="CNIC-ATTEST", group="identity", ref="R5", title="Attestation of CNIC copies",
    applies=lambda facts: len(facts.cnics) > 0,
    run=lambda facts: _cnic_attest(facts),
)


def _cnic_attest(facts: Facts) -> list[dict[str, Any]]:
    """One result per card, keyed by the PAGE it is on rather than its position.

    §4.4 wants an id a disposition can hang on across re-evaluations. A list index is not
    that: the `add-cnic` cure appends a card, and any future rule that filtered or reordered
    the cards would silently move every id after it. The page a card sits on is what an
    officer sees and does not move.
    """
    out: list[dict[str, Any]] = []
    for index, card in enumerate(facts.cnics):
        key = f"p{card.get('page')}" if card.get("page") is not None else f"i{index}"
        whose = card.get("whose") or "subscriber"
        kind = "smart card" if card.get("type") == "smart" else "older card"
        if card.get("attested"):
            by = f" by {card.get('attestedBy')}" if card.get("attestedBy") else ""
            out.append({
                "sub": key, "status": OK, "doc": f"CNIC copy, {whose}",
                "finding": (f"Copy of {whose}’s CNIC ({kind}, page {card.get('page')}) "
                            f"is attested{by}."),
                "evidence": [ev(card.get("page"), "CNIC copy", card.get("crop"))],
            })
            continue
        aside = (", and this is a smart card whose QR code is checked below"
                 if card.get("type") == "smart" else "")
        out.append({
            "sub": key, "status": ADV, "code": "R5", "doc": f"CNIC copy, {whose}",
            "finding": (f"The copy of {whose}’s CNIC at page {card.get('page')} is not "
                        f"attested. Attestation is not required{aside}, so this is noted only."),
            "remedy": "None required. Noted for the department’s record.",
            "evidence": [ev(card.get("page"), "CNIC copy", card.get("crop"))],
        })
    return out


check(
    id="PAYSLIP-ATTEST", group="identity", ref="R5", title="Attestation of pay slip copy",
    applies=lambda facts: bool(
        facts.sap and facts.sap_source == "case" and facts.sap_payslip
        and facts.sap_payslip.get("attested") is False),
    run=lambda facts: {
        "status": ADV, "code": "R5",
        "finding": (f"The pay slip copy at page {(facts.sap_payslip or {}).get('page')} is not "
                    f"attested. A pay slip does not need attestation, so this is noted only."),
        "remedy": "None required.",
        "evidence": [ev((facts.sap_payslip or {}).get("page"), "Pay slip")],
    },
)


# -- R10: every QR code is scanned and its content checked -----------------------------------

check(
    id="QR", group="qr", ref="R10 · B1-iii", title="QR codes",
    applies=lambda facts: len(facts.qr) > 0,
    run=lambda facts: [_one_code(facts, code) for code in facts.qr],
)


def _one_code(facts: Facts, code: dict[str, Any]) -> dict[str, Any]:
    """One code. R10, and §9 for what each outcome means.

    The gradient matters and is the office's, not ours (§9.2): a decoded payload that
    DISAGREES with the document on identity or money is a hard stop; a code that cannot be
    read, a card side that was not supplied, or a portal that will not answer is an
    OBSERVATION. And a non-QR symbology that will not decode is recorded only, because R10
    covers QR codes -- raising an unreadable 1-D barcode on a photocopied notice would put a
    defect on the department for the quality of a scanner.
    """
    page = code.get("page")
    symbology = code.get("symbology") or "QR code"
    base: dict[str, Any] = {
        "sub": code.get("id"),
        "doc": f"QR code, {code.get('doc')} (page {page})",
        "evidence": [ev(page, "QR code", code.get("crop"))],
    }
    record = verified(facts, f"QR:{code.get('id')}")

    if code.get("notSupplied"):
        if record:
            return {**base, **verified_result(
                record, "Missing side supplied and its code checked.",
                "Code on the supplied side does not agree with the document.")}
        return {**base, "status": ADV, "code": "R10",
                "finding": (f"{code['notSupplied']} The {symbology} on it cannot be scanned, "
                            f"so it is flagged as an observation."),
                "remedy": code.get("remedy") or
                          "Upload the missing side; the code is then scanned and checked.",
                "cure": {"kind": "qr", "qid": code.get("id")}}

    why = f" ({code.get('why')})" if code.get("why") else ""
    readable = (f" The printed text beside it reads {code.get('readable')}."
                if code.get("readable") else "")

    if not code.get("decoded") and "qr" not in symbology.lower():
        return {**base, "status": NA,
                "doc": f"{symbology}, {code.get('doc')} (page {page})",
                "finding": (f"A {symbology} is printed on the {code.get('doc')} but could not be "
                            f"read from this copy{why}. It is not a QR code, so it is recorded "
                            f"only and not raised (R10 covers QR codes).{readable}")}

    if not code.get("decoded"):
        if record:
            return {**base, **verified_result(
                record, f"{symbology} checked on the original.",
                f"{symbology} on the original does not verify the document.")}
        return {**base, "status": ADV, "code": "R10",
                "finding": (f"A {symbology} is printed on the {code.get('doc')} but could not be "
                            f"read from this copy{why}. Its content cannot be checked against the "
                            f"document, so it is flagged as an observation.{readable}"),
                "remedy": code.get("remedy") or
                          ("Upload a clearer copy, or scan the original with the office reader; "
                           "the case is then re-checked."),
                "cure": {"kind": "qr", "qid": code.get("id")}}

    comparisons = code.get("compare") or []
    disagreements = [c for c in comparisons if c.get("match") is False]
    agreements = [c for c in comparisons if c.get("match") is True]

    if disagreements:
        detail = "; ".join(
            f"{c.get('field')} reads {c.get('qrVal')} in the QR code but {c.get('docVal')} "
            f"on the {c.get('docLabel')}" for c in disagreements)
        return {**base, "status": HARD, "code": code.get("codeOnMismatch") or "R10",
                "finding": f"QR code decoded. It disagrees with the document: {detail}.",
                "remedy": code.get("remedyOnMismatch") or
                          "Obtain a corrected document that agrees with the QR record.",
                "payload": code.get("payload")}

    if code.get("route") == "online":
        if record:
            return {**base, **verified_result(
                record,
                "Decoded link opened on the verification terminal; the portal record matches the document.",
                "Portal record does not match the document.")}
        portal = code.get("portal") or {}
        host = code.get("host")
        if portal.get("ok") is True:
            return {**base, "status": OK, "payload": code.get("payload"),
                    "finding": (f"QR code decoded to {host} and verified on the issuing portal on "
                                f"{portal.get('checkedOn')}: {portal.get('result')}")}
        if portal.get("ok") is False:
            # NADRA does not answer requests from outside its network (§9.3). That is a fact
            # about the portal, so the office instruction of 15-09-2026 makes it an
            # observation curable by a verification, never a defect in the certificate.
            return {**base, "status": ADV, "code": "R10", "payload": code.get("payload"),
                    "finding": (f"QR code decoded to a verification link on {host}, but the portal "
                                f"would not return the record ({portal.get('result')}). The document "
                                f"is not verified, so it is flagged as an observation."),
                    "remedy": (f"Verify on the office terminal with access to {host}, or obtain the "
                               f"verified printout, and record the result."),
                    "cure": {"kind": "verify", "vid": f"QR:{code.get('id')}"}}
        agrees = "Its reference agrees with the document. " if agreements else ""
        return {**base, "status": CONF, "payload": code.get("payload"),
                "finding": (f"QR code decoded to a verification link on {host}. {agrees}The portal "
                            f"page itself has to be opened to complete verification, which cannot be "
                            f"done from inside the air-gapped system."),
                "remedy": ("Open the link on the office verification terminal and record whether the "
                           "portal record matches."),
                "cure": {"kind": "verify", "vid": f"QR:{code.get('id')}"}}

    checked = (", ".join(f"{c.get('field')} {c.get('qrVal')}" for c in agreements) + " agree."
               if agreements else "content recorded.")
    return {**base, "status": OK, "payload": code.get("payload"),
            "finding": f"QR code decoded and checked against the document: {checked}"}


check(
    id="QR-SANCTION", group="qr", ref="B1-iii · R10", code="B1-iii",
    title="QR-coded sanction (Health, Education, Police)",
    applies=lambda facts: bool(
        facts.is_kind(*ADVANCES)
        and (facts.doc("sanction") or {}).get("present")
        and _is_qr_department((facts.doc("sanction") or {}).get("dept"))),
    run=lambda facts: _qr_sanction(facts),
)


def _is_qr_department(dept: Any) -> bool:
    text = str(dept or "").lower()
    return any(word in text for word in ("health", "education", "police"))


def _qr_sanction(facts: Facts) -> dict[str, Any] | None:
    """B1-iii concerns a QR-coded sanction the department has not verified.

    §9.2, last sentence, and §16.3: a sanction that carries NO QR code does not trigger it.
    Revision 1 raised B1-iii on the Police sanction for not having a code, which is a defect
    the department could not cure because the code never existed.
    """
    sanction = facts.doc("sanction") or {}
    code = next((c for c in facts.qr if c.get("id") == sanction.get("qrId")), None)
    if code and code.get("decoded") and not any(
            c.get("match") is False for c in (code.get("compare") or [])):
        return {"status": OK,
                "finding": ("The sanction carries a QR code. It was decoded and agrees with the "
                            "order (see QR codes)."),
                "evidence": [ev(code.get("page"), "Sanction QR", code.get("crop"))]}
    if code:
        return None                      # the QR check above carries the finding
    return {"status": NA,
            "finding": (f"The {sanction.get('dept')} sanction at page {sanction.get('page')} carries "
                        f"no QR code. B1-iii applies only to a QR-coded sanction that the department "
                        f"has not verified, so nothing is raised."),
            "evidence": [ev(sanction.get("page"), "Sanction")]}


# -- R4: signatories against the delegation of authority register ---------------------------

_DOA_ROLES = ("sanctioning", "ddo", "certifying")

check(
    id="DOA", group="signature", ref="R4 · B1-ii · B1-vi · B2-iv",
    title="Signatories and delegation of authority",
    applies=lambda facts: any(s.get("role") in _DOA_ROLES for s in facts.signatures),
    run=lambda facts: [_one_signature(facts, s) for s in facts.signatures
                       if s.get("role") in _DOA_ROLES],
)


def _one_signature(facts: Facts, signature: dict[str, Any]) -> dict[str, Any]:
    register = active_register()
    match = register.lookup(signature.get("authority"), signature.get("signedBy"))
    base: dict[str, Any] = {
        "sub": signature.get("id"),
        "doc": f"{signature.get('roleLabel')}, {signature.get('doc')} (page {signature.get('page')})",
        "evidence": [ev(signature.get("page"), "Signature and stamp",
                        signature.get("crop"), signature.get("bbox"))],
        "doa": match.to_dict(),
    }
    # Which rejection reason prints depends on WHAT was signed, not on the register: B1-ii for
    # a refundable sanction, B2-iv for any other sanction, R4 for a DDO or certifying hand.
    code = ("B1-ii" if facts.is_kind("refundable") else "B2-iv") \
        if signature.get("role") == "sanctioning" else "R4"
    who = signature.get("signedBy", "")
    if signature.get("forMarker"):
        who = f"{who} for {signature.get('authority')}"

    record = verified(facts, f"DOA:{signature.get('id')}")
    if record:
        outcome = verified_result(
            record,
            f"{who}: authority and signature confirmed against the DOA register.",
            f"{who}: not an approved signatory, or the signature does not match the specimen.")
        return {**base, **outcome, **({} if record.get("ok") else {"code": code})}

    if register.raises_hard_stop(match):
        return {**base, "status": HARD, "code": code,
                "finding": f"{match.sentence()} Signed by {who}.",
                "remedy": "Obtain the document under the signature of an approved signatory."}

    provisional_note = "" if not register.is_provisional else \
        " The register is provisional until the office supplies its DOA list."
    remedy = ("Compare the signature with the specimen and record the result."
              if match.has_specimen else
              "Confirm the signatory’s authority, and add the specimen to the register when received.")
    return {**base, "status": CONF,
            "finding": f"Signed by {who}. {match.sentence()}{provisional_note}",
            "remedy": remedy,
            "cure": {"kind": "verify", "vid": f"DOA:{signature.get('id')}"}}


# -- R7: a thumb impression cannot be matched to a CNIC copy --------------------------------

check(
    id="THUMB", group="signature", ref="R7", title="Thumb impression in place of a signature",
    applies=lambda facts: len(facts.thumbs) > 0,
    run=lambda facts: [_one_thumb(facts, t) for t in facts.thumbs],
)


def _one_thumb(facts: Facts, thumb: dict[str, Any]) -> dict[str, Any]:
    """Detect, record, route to a person. Never claim a match or a mismatch. §10, §14 rule 5.

    The office asked for thumb impressions to be matched against the CNIC copy. It was tested
    on every impression and every card in the corpus and it cannot be done: smart cards carry
    no fingerprint at all, the one printed print is a copy of a copy with 21% of its ridges
    readable, and on the real scans same-person pairs scored 0.10 to 0.21 against
    different-person pairs at 0.08 to 0.28 -- ranges that overlap completely.

    So a module reporting "match" or "mismatch" would be guessing, and, as §10 puts it, a
    false mismatch could stop a widow's rightful claim. The cure is a NADRA biometric
    verification record or an attesting officer's certificate naming the person and CNIC.
    """
    base: dict[str, Any] = {
        "sub": thumb.get("id"),
        "doc": f"Thumb impression, {thumb.get('doc')} (page {thumb.get('page')})",
        "evidence": [ev(thumb.get("page"), "Thumb impression", thumb.get("crop"))],
    }
    record = verified(facts, f"THUMB:{thumb.get('id')}")
    if record:
        return {**base, **verified_result(
            record,
            f"Identity of the person who thumbed ({thumb.get('whose')}) confirmed.",
            "Identity of the person who thumbed could not be confirmed.")}
    return {**base, "status": CONF,
            "finding": (f"{thumb.get('whose')} has thumbed the {thumb.get('doc')} instead of "
                        f"signing. The module does not match thumb impressions to CNIC copies: "
                        f"smart cards carry no fingerprint, and the scans are far below the "
                        f"resolution fingerprint comparison needs."),
            "remedy": ("Confirm identity through NADRA biometric verification or the attesting "
                       "officer’s certificate on the impression, and record which."),
            "cure": {"kind": "verify", "vid": f"THUMB:{thumb.get('id')}"}}


# -- R6: the subscriber's signature on the change form against the CNIC ---------------------

check(
    id="SIG-CNIC", group="signature", ref="R6",
    title="Subscriber signature on the change form matches the CNIC",
    applies=lambda facts: bool(facts.is_kind(*ADVANCES)
                               and (facts.doc("changeForm") or {}).get("present")),
    run=lambda facts: _sig_cnic(facts),
)


def _sig_cnic(facts: Facts) -> dict[str, Any]:
    form = facts.doc("changeForm") or {}
    card = facts.cnic_of("subscriber")
    label = form.get("label")
    pair = {
        "left": {"label": f"Specimen signature, {label} p{form.get('page')}",
                 "crop": form.get("sigCrop")},
        "right": {"label": f"Holder’s signature, CNIC p{card.get('page') if card else '?'}",
                  "crop": card.get("sigCrop") if card else None},
    }
    if form.get("sigKind") == "thumb":
        return {"status": NA,
                "finding": "Thumb impression used; see the thumb impression check (R7)."}
    if not form.get("sigKind") or form.get("sigKind") == "none":
        return {"status": HARD,
                "code": "B1-vii" if facts.is_kind("refundable") else "B2-v",
                "finding": f"The subscriber has not signed the {label}.",
                "remedy": "Obtain the subscriber’s signature on the form.",
                "evidence": [ev(form.get("page"), label)],
                "cure": {"kind": "doc", "docType": label, "apply": "form-signed",
                         "fields": [{"k": "signed", "label": "Subscriber has signed",
                                     "type": "yesno"}]}}
    if not card:
        return {"status": HARD, "code": "A1-ii",
                "finding": ("No CNIC copy of the subscriber is on file to compare the signature "
                            "against."),
                "remedy": "Obtain a copy of the subscriber’s CNIC.",
                "cure": {"kind": "doc", "docType": "CNIC copy", "apply": "add-cnic",
                         "fields": [{"k": "number", "label": "CNIC number on the copy",
                                     "type": "text", "expect": form.get("cnic")}]}}
    record = verified(facts, "SIG-CNIC")
    if record:
        return {**verified_result(
            record,
            f"Signature on the {label} matches the holder’s signature on the CNIC.",
            f"Signature on the {label} does not match the CNIC."), "pair": pair, "code": "R6"}
    # The module places them side by side and says nothing about the ink. §8.4, §14 rule 6.
    return {"status": CONF, "pair": pair,
            "finding": (f"Compare the subscriber’s specimen signature on the {label} with the "
                        f"holder’s signature on the CNIC. The module places them side by side; "
                        f"the officer decides."),
            "remedy": "Record whether the signatures match.",
            "cure": {"kind": "verify", "vid": "SIG-CNIC"},
            "evidence": [ev(form.get("page"), label, form.get("sigCrop")),
                         ev(card.get("page"), "CNIC", card.get("sigCrop"))]}
