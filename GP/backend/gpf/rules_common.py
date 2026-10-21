"""Rule catalogue, part 1: checks that apply across case families.

`ref` names the circular item and/or the office clarification (R1-R15, AG
Punjab, 15-09-2026). `code` is what prints on the rejection form. A run() may
return one result or a list; list items carry a `sub` key so each keeps a
stable id across reprocessing. Faithful port of rules_common.js.
"""
from __future__ import annotations

import re

from .doa import DOA, doa_lookup, doa_status_text
from .format import ADVANCES, FINALS, D, KIND, digits, ev, fmt
from .registry import check, verified, verified_result


# ── R1, R8, R11: SAP extracts ────────────────────────────────────────────────
def _sap_payslip(F):
    p = F.get("sap") and F["sap"].get("payslip")
    if p:
        frm = ("found in the case at page " + str(p.get("page"))
               if F["sap"].get("source") == "case"
               else "uploaded from SAP (" + str(F["sap"].get("file")) + ")")
        return {"status": "ok",
                "finding": ("Pay slip for " + (p.get("month") or "the month shown")
                            + ", personnel no. " + str(p.get("persNo")) + ", " + frm + "."),
                "evidence": [ev(p.get("page"), "SAP pay slip")] if p.get("page") else []}
    return {"status": "sap",
            "finding": ("No SAP pay slip is in the case. Pull it from SAP against personnel no. "
                        + (F.get("personnelNo") or "(not stated)") + " and upload it on the SAP extracts step."),
            "remedy": "Action for this section. Not a defect of the department.",
            "cure": {"kind": "sap"}}


check(id="SAP-PAYSLIP", group="sap", ref="R1 · R8", checklist="SAP",
      title="SAP pay slip of the subscriber", applies=lambda F: True, run=_sap_payslip)


def _sap_recalc(F):
    r = F.get("sap") and F["sap"].get("recalc")
    if KIND(F, *FINALS):
        need = "Required with the pay slip for a final payment (R11)."
    elif KIND(F, *ADVANCES):
        need = "Needed to establish the balance for the 80% test and the advance position."
    else:
        need = "Shows whether the months in question are already credited."
    if r and r.get("rows"):
        last = r["rows"][-1]
        frm = ("found in the case at page " + str(r.get("page"))
               if F["sap"].get("source") == "case"
               else "uploaded from SAP (" + str(F["sap"].get("file")) + ")")
        return {"status": "ok",
                "finding": ("Report " + ("dated " + r["reportDate"] + ", " if r.get("reportDate") else "")
                            + frm + ". Last period " + last["start"] + " to " + last["end"]
                            + ", closing balance Rs " + fmt(last["closing"]) + ". " + need),
                "evidence": [ev(r.get("page"), "GPF Final Re-calculation Report")] if r.get("page") else []}
    return {"status": "sap",
            "finding": "No GPF Final Re-calculation Report is in the case. " + need,
            "remedy": ("Pull the report from SAP against personnel no. "
                       + (F.get("personnelNo") or "(not stated)") + " and upload it."),
            "cure": {"kind": "sap"}}


check(id="SAP-RECALC", group="sap", ref="R1 · R11", checklist="SAP",
      title="GPF Final Re-calculation Report from SAP", applies=lambda F: True, run=_sap_recalc)


def _sap_identity(F):
    want = digits(F.get("personnelNo"))
    bad = []
    for label, x in (("pay slip", F["sap"].get("payslip")),
                     ("re-calculation report", F["sap"].get("recalc"))):
        if x and x.get("persNo") and want and digits(x["persNo"]) != want:
            bad.append("the " + label + " is for personnel no. " + str(x["persNo"]))
    if bad:
        return {"status": "hard", "code": "R1",
                "finding": ("The case is for personnel no. " + str(F.get("personnelNo"))
                            + " but " + " and ".join(bad) + "."),
                "remedy": "Pull the extract for the correct personnel number.",
                "cure": {"kind": "sap"}}
    return {"status": "ok", "finding": "Personnel no. " + str(F.get("personnelNo")) + " on every SAP extract."}


check(id="SAP-IDENTITY", group="identity", ref="R1", title="SAP extract belongs to this subscriber",
      applies=lambda F: bool(F.get("sap") and (F["sap"].get("payslip") or F["sap"].get("recalc"))),
      run=_sap_identity)


# ── R3: covering letter is never an observation ───────────────────────────────
def _cover(F):
    c = D(F).get("covering") or {}
    if c.get("present"):
        what = ((c.get("nature") or "Forwarding instrument")
                + (" from " + c["author"] if c.get("author") else "")
                + (", page " + str(c["page"]) if c.get("page") else "") + ".")
    else:
        what = "No separate letter on file."
    return {"status": "ok",
            "finding": (what + " Accepted under office practice: the covering letter is the "
                        "authority's notice to process the case and is not examined further (R3)."),
            "evidence": [ev(c["page"], "Covering letter", c.get("crop"))] if c.get("page") else []}


check(id="COVER", group="checklist", ref="A2-i · A3-ii · A4-i · R3", title="Covering / forwarding letter",
      checklist=lambda F: "A3-ii" if KIND(F, "balance_transfer") else ("A4-i" if KIND(F, "missing_credits") else "A2-i"),
      applies=lambda F: not KIND(F, *ADVANCES), run=_cover)


# ── R5: attestation of CNIC copies and pay slips is not required ─────────────
def _cnic_attest(F):
    out = []
    for i, c in enumerate(F["docs"]["cnics"]):
        who = c.get("whose") or "subscriber"
        typ = "smart card" if c.get("type") == "smart" else "older card"
        if c.get("attested"):
            out.append({"sub": i, "status": "ok", "doc": "CNIC copy, " + who,
                        "finding": ("Copy of " + who + "'s CNIC (" + typ + ", page " + str(c["page"])
                                    + ") is attested" + (" by " + c["attestedBy"] if c.get("attestedBy") else "") + "."),
                        "evidence": [ev(c["page"], "CNIC copy", c.get("crop"))]})
        else:
            extra = ", and this is a smart card whose QR code is checked below" if c.get("type") == "smart" else ""
            out.append({"sub": i, "status": "adv", "code": "R5", "doc": "CNIC copy, " + who,
                        "finding": ("The copy of " + who + "'s CNIC at page " + str(c["page"])
                                    + " is not attested. Attestation is not required" + extra + ", so this is noted only."),
                        "remedy": "None required. Noted for the department's record.",
                        "evidence": [ev(c["page"], "CNIC copy", c.get("crop"))]})
    return out


check(id="CNIC-ATTEST", group="identity", ref="R5", title="Attestation of CNIC copies",
      applies=lambda F: len((D(F).get("cnics") or [])) > 0, run=_cnic_attest)


def _payslip_attest(F):
    p = F["sap"]["payslip"]
    return {"status": "adv", "code": "R5",
            "finding": ("The pay slip copy at page " + str(p["page"]) + " is not attested. "
                        "A pay slip does not need attestation, so this is noted only."),
            "remedy": "None required.", "evidence": [ev(p["page"], "Pay slip")]}


check(id="PAYSLIP-ATTEST", group="identity", ref="R5", title="Attestation of pay slip copy",
      applies=lambda F: bool(F.get("sap") and F["sap"].get("source") == "case"
                             and F["sap"].get("payslip") and F["sap"]["payslip"].get("attested") is False),
      run=_payslip_attest)


# ── R10: every QR code is scanned and its content checked ─────────────────────
def _qr(F):
    out = []
    for q in F["qr"]:
        base = {"sub": q["id"], "doc": "QR code, " + q["doc"] + " (page " + str(q["page"]) + ")",
                "evidence": [ev(q["page"], "QR code", q.get("crop"))]}
        v = verified(F, "QR:" + q["id"])
        sym = q.get("symbology") or "QR code"
        if q.get("notSupplied"):
            if v:
                out.append({**base, **verified_result(v, "Missing side supplied and its code checked.",
                                                       "Code on the supplied side does not agree with the document.")})
                continue
            out.append({**base, "status": "adv", "code": "R10",
                        "finding": (q["notSupplied"] + " The " + sym + " on it cannot be scanned, so it is flagged as an observation."),
                        "remedy": q.get("remedy") or "Upload the missing side; the code is then scanned and checked.",
                        "cure": {"kind": "qr", "qid": q["id"]}})
            continue
        if not q.get("decoded") and not re.search(r"QR", sym, re.I):
            why = (" (" + q["why"] + ")") if q.get("why") else ""
            readable = (" The printed text beside it reads " + q["readable"] + ".") if q.get("readable") else ""
            out.append({**base, "status": "na", "doc": sym + ", " + q["doc"] + " (page " + str(q["page"]) + ")",
                        "finding": ("A " + sym + " is printed on the " + q["doc"] + " but could not be read from this copy"
                                    + why + ". It is not a QR code, so it is recorded only and not raised "
                                    "(R10 covers QR codes)." + readable)})
            continue
        if not q.get("decoded"):
            if v:
                out.append({**base, **verified_result(v, sym + " checked on the original.",
                                                      sym + " on the original does not verify the document.")})
                continue
            why = (" (" + q["why"] + ")") if q.get("why") else ""
            readable = (" The printed text beside it reads " + q["readable"] + ".") if q.get("readable") else ""
            out.append({**base, "status": "adv", "code": "R10",
                        "finding": ("A " + sym + " is printed on the " + q["doc"] + " but could not be read from this copy"
                                    + why + ". Its content cannot be checked against the document, so it is flagged as an observation." + readable),
                        "remedy": q.get("remedy") or "Upload a clearer copy, or scan the original with the office reader; the case is then re-checked.",
                        "cure": {"kind": "qr", "qid": q["id"]}})
            continue
        bad = [c for c in (q.get("compare") or []) if c.get("match") is False]
        good = [c for c in (q.get("compare") or []) if c.get("match") is True]
        if bad:
            detail = "; ".join(c["field"] + " reads " + c["qrVal"] + " in the QR code but "
                               + c["docVal"] + " on the " + c["docLabel"] for c in bad)
            out.append({**base, "status": "hard", "code": q.get("codeOnMismatch") or "R10",
                        "finding": "QR code decoded. It disagrees with the document: " + detail + ".",
                        "remedy": q.get("remedyOnMismatch") or "Obtain a corrected document that agrees with the QR record.",
                        "payload": q.get("payload")})
            continue
        if q.get("route") == "online":
            if v:
                out.append({**base, **verified_result(
                    v, "Decoded link opened on the verification terminal; the portal record matches the document.",
                    "Portal record does not match the document.")})
                continue
            portal = q.get("portal")
            if portal and portal.get("ok"):
                out.append({**base, "status": "ok", "payload": q.get("payload"),
                            "finding": ("QR code decoded to " + q.get("host", "") + " and verified on the issuing portal on "
                                        + portal["checkedOn"] + ": " + portal["result"])})
                continue
            if portal and portal.get("ok") is False:
                out.append({**base, "status": "adv", "code": "R10", "payload": q.get("payload"),
                            "finding": ("QR code decoded to a verification link on " + q.get("host", "")
                                        + ", but the portal would not return the record (" + portal["result"]
                                        + "). The document is not verified, so it is flagged as an observation."),
                            "remedy": ("Verify on the office terminal with access to " + q.get("host", "")
                                       + ", or obtain the verified printout, and record the result."),
                            "cure": {"kind": "verify", "vid": "QR:" + q["id"]}})
                continue
            out.append({**base, "status": "conf", "payload": q.get("payload"),
                        "finding": ("QR code decoded to a verification link on " + q.get("host", "") + ". "
                                    + ("Its reference agrees with the document. " if good else "")
                                    + "The portal page itself has to be opened to complete verification, which cannot be done "
                                    "from inside the air-gapped system."),
                        "remedy": "Open the link on the office verification terminal and record whether the portal record matches.",
                        "cure": {"kind": "verify", "vid": "QR:" + q["id"]}})
            continue
        out.append({**base, "status": "ok", "payload": q.get("payload"),
                    "finding": ("QR code decoded and checked against the document: "
                                + (", ".join(c["field"] + " " + c["qrVal"] for c in good) + " agree."
                                   if good else "content recorded."))})
    return out


# QR CHECKING IS OUT OF SCOPE (office decision, 21 Oct 2026). Neither check below is
# registered, so no examination raises a QR finding of any kind.
#
# It never worked. The reading pipeline is wired to NullBarcodeDecoder, which returns nothing,
# so F["qr"] was always empty: the QR check never fired, and QR-SANCTION fell through to its
# other branch and told the officer the sanction "carries no QR code" -- a statement of fact
# about a page nothing had looked at. On a sanction that does carry one, that is the opposite
# of the truth, printed with the authority of a check (audit of 13 Oct 2026, H-13).
#
# Offered and declined: wiring the real decoder. zxingcpp IS installed now, so it is a one-line
# change -- but a check that has never run against a real scan is not evidence, and the office
# chose to drop the claim rather than to start making a new one.
#
# WHAT THIS COSTS: rule B1-iii is not evaluated. It applies only to a QR-coded sanction a
# department has not verified, and nothing here can tell whether a sanction is QR-coded. The
# bodies of both checks are kept, unregistered, so restoring this is wiring the decoder and
# putting the two check() calls back -- not writing the rules again.
#
# check(id="QR", group="qr", ref="R10 · B1-iii", title="QR codes",
#       applies=lambda F: len((F.get("qr") or [])) > 0, run=_qr)


def _qr_sanction(F):
    s = F["docs"]["sanction"]
    q = next((x for x in (F.get("qr") or []) if x["id"] == s.get("qrId")), None)
    if q and q.get("decoded") and not any(c.get("match") is False for c in (q.get("compare") or [])):
        return {"status": "ok",
                "finding": "The sanction carries a QR code. It was decoded and agrees with the order (see QR codes).",
                "evidence": [ev(q["page"], "Sanction QR", q.get("crop"))]}
    if q:
        return None  # the QR rule above carries the finding
    return {"status": "na",
            "finding": ("The " + s.get("dept", "") + " sanction at page " + str(s.get("page"))
                        + " carries no QR code. B1-iii applies only to a QR-coded sanction that the department "
                        "has not verified, so nothing is raised."),
            "evidence": [ev(s.get("page"), "Sanction")]}


# check(id="QR-SANCTION", group="qr", ref="B1-iii · R10", code="B1-iii",
#       title="QR-coded sanction (Health, Education, Police)",
#       applies=lambda F: (KIND(F, *ADVANCES) and D(F).get("sanction") and D(F)["sanction"].get("present")
#                          and bool(re.search(r"health|education|police", D(F)["sanction"].get("dept") or "", re.I))),
#       run=_qr_sanction)


# ── R4: signatories against the delegation of authority register ──────────────
_SIG_ROLES = ("sanctioning", "ddo", "certifying")


def _doa(F):
    out = []
    for g in [g for g in F["signatures"] if g["role"] in _SIG_ROLES]:
        m = doa_lookup(g["authority"], g["signedBy"])
        base = {"sub": g["id"], "doc": g["roleLabel"] + ", " + g["doc"] + " (page " + str(g["page"]) + ")",
                "evidence": [ev(g["page"], "Signature and stamp", g.get("crop"))], "doa": m, "sig": g}
        code = ("B1-ii" if KIND(F, "refundable") else "B2-iv") if g["role"] == "sanctioning" else "R4"
        v = verified(F, "DOA:" + g["id"])
        who = g["signedBy"] + (" for " + g["authority"] if g.get("forMarker") else "")
        if v:
            res = verified_result(v, who + ": authority and signature confirmed against the DOA register.",
                                  who + ": not an approved signatory, or the signature does not match the specimen.")
            out.append({**base, **res, **({} if v.get("ok") else {"code": code})})
            continue
        if m["status"] == "signatory_not_listed" and DOA["status"] == "final":
            out.append({**base, "status": "hard", "code": code,
                        "finding": doa_status_text(m) + " Signed by " + who + ".",
                        "remedy": "Obtain the document under the signature of an approved signatory."})
            continue
        prov = "" if DOA["status"] == "final" else " The register is provisional until the office supplies its DOA list."
        # The specimens on file for this department and post, from the shared master store (C1,
        # 9 Oct 2026), shown beside the signature as read; the comparison stays the officer's.
        from .signatories import specimens_for
        on_file = specimens_for((m.get("authority") or {}).get("dept") or g["authority"], g["signedBy"] or g["authority"], None)
        has_specimen = bool(on_file["specimens"]) or m["status"] == "listed_with_specimen"
        remedy = ("Compare the signature with the specimen and record the result."
                  if has_specimen
                  else "Confirm the signatory's authority, and add the specimen to the register when received.")
        out.append({**base, "status": "conf",
                    "finding": "Signed by " + who + ". " + doa_status_text(m) + prov
                    + ("" if on_file["specimens"] else " " + on_file["message"] + "."),
                    "specimens": on_file["specimens"], "specimen_authority": on_file["authority"],
                    "remedy": remedy, "cure": {"kind": "verify", "vid": "DOA:" + g["id"]}})
    return out


check(id="DOA", group="signature", ref="R4 · B1-ii · B1-vi · B2-iv",
      title="Signatories and delegation of authority",
      applies=lambda F: any(g["role"] in _SIG_ROLES for g in (F.get("signatures") or [])),
      run=_doa)


# ── R7: thumb impressions cannot be matched to a CNIC copy ────────────────────
def _thumb(F):
    out = []
    for t in F["thumbs"]:
        base = {"sub": t["id"], "doc": "Thumb impression, " + t["doc"] + " (page " + str(t["page"]) + ")",
                "evidence": [ev(t["page"], "Thumb impression", t.get("crop"))]}
        v = verified(F, "THUMB:" + t["id"])
        if v:
            out.append({**base, **verified_result(
                v, "Identity of the person who thumbed (" + t["whose"] + ") confirmed.",
                "Identity of the person who thumbed could not be confirmed.")})
            continue
        out.append({**base, "status": "conf",
                    "finding": (t["whose"] + " has thumbed the " + t["doc"] + " instead of signing. The module does "
                                "not match thumb impressions to CNIC copies: smart cards carry no fingerprint, and the "
                                "scans are far below the resolution fingerprint comparison needs."),
                    "remedy": "Confirm identity through NADRA biometric verification or the attesting officer's certificate on the impression, and record which.",
                    "cure": {"kind": "verify", "vid": "THUMB:" + t["id"]}})
    return out


check(id="THUMB", group="signature", ref="R7", title="Thumb impression in place of a signature",
      applies=lambda F: len((F.get("thumbs") or [])) > 0, run=_thumb)


# ── R6: subscriber signature on the change form against the CNIC ──────────────
def _sig_cnic(F):
    cf = F["docs"]["changeForm"]
    card = next((c for c in (D(F).get("cnics") or []) if (c.get("whose") or "subscriber") == "subscriber"), None)
    pair = {"left": {"label": "Specimen signature, " + cf["label"] + " p" + str(cf["page"]), "crop": cf.get("sigCrop")},
            "right": {"label": "Holder's signature, CNIC p" + str(card["page"] if card else "?"),
                      "crop": card.get("sigCrop") if card else None}}
    if cf.get("sigKind") == "thumb":
        return {"status": "na", "finding": "Thumb impression used; see the thumb impression check (R7)."}
    if not cf.get("sigKind") or cf.get("sigKind") == "none":
        return {"status": "hard", "code": "B1-vii" if KIND(F, "refundable") else "B2-v",
                "finding": "The subscriber has not signed the " + cf["label"] + ".",
                "remedy": "Obtain the subscriber's signature on the form.",
                "evidence": [ev(cf["page"], cf["label"])],
                "cure": {"kind": "doc", "docType": cf["label"],
                         "fields": [{"k": "signed", "label": "Subscriber has signed", "type": "yesno"}],
                         "apply": "form-signed"}}
    if not card:
        return {"status": "hard", "code": "A1-ii",
                "finding": "No CNIC copy of the subscriber is on file to compare the signature against.",
                "remedy": "Obtain a copy of the subscriber's CNIC.",
                "cure": {"kind": "doc", "docType": "CNIC copy",
                         "fields": [{"k": "number", "label": "CNIC number on the copy", "type": "text", "expect": cf.get("cnic")}],
                         "apply": "add-cnic"}}
    v = verified(F, "SIG-CNIC")
    if v:
        res = verified_result(v, "Signature on the " + cf["label"] + " matches the holder's signature on the CNIC.",
                              "Signature on the " + cf["label"] + " does not match the CNIC.")
        return {**res, "pair": pair, "code": "R6"}
    return {"status": "conf", "pair": pair,
            "finding": ("Compare the subscriber's specimen signature on the " + cf["label"] + " with the holder's "
                        "signature on the CNIC. The module places them side by side; the officer decides."),
            "remedy": "Record whether the signatures match.",
            "cure": {"kind": "verify", "vid": "SIG-CNIC"},
            "evidence": [ev(cf["page"], cf["label"], cf.get("sigCrop")), ev(card["page"], "CNIC", card.get("sigCrop"))]}


check(id="SIG-CNIC", group="signature", ref="R6",
      title="Subscriber signature on the change form matches the CNIC",
      applies=lambda F: KIND(F, *ADVANCES) and D(F).get("changeForm") and D(F)["changeForm"].get("present"),
      run=_sig_cnic)
