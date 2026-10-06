"""Missing credits, and balance transfer. Build specification §5.4, §5.5.

Both families were judged too harshly in revision 1 and the office corrected both (§16.3).

**Missing credits.** R14 and R15: challans carrying the bank's stamp and the Treasury's
verification stand in for the DDO certificate (non-gazetted period) and the AG Office
certificate (gazetted period). Revision 1 declared the case unactionable because neither
certificate was on file and the gazetted status was unknown. Both certificates are now
evaluated and BOTH are satisfied by the same challan evidence, which is why an unknown
gazetted status does not block -- and why Rule 1.40(3)'s split at BS-16 rather than at
gazetted status is open item GPF-O21.

**Balance transfer.** In the SAP era the personnel number keys the GP Fund account, so a
personnel number in the new-account column, confirmed by the respective DAO, satisfies the
particular. Revision 1 raised four hard stops on a one-page proforma that was substantially
correct.
"""

from __future__ import annotations

from typing import Any

from .contracts import ADV, CONF, HARD, OK, SAP, SUB, Facts
from .engine import check, digits, ev, fmt, num


def _doc_cure(doc_type: str, apply: str, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"kind": "doc", "docType": doc_type, "apply": apply, "fields": fields or []}


# -- missing credits, §5.4 ------------------------------------------------------------------

check(
    id="MC-PERIOD", group="checklist", checklist="A4-ii", ref="A4-ii",
    title="Period of missing months",
    applies=lambda facts: facts.is_kind("missing_credits"),
    run=lambda facts: _mc_period(facts),
)


def _mc_period(facts: Facts) -> dict[str, Any]:
    challans = facts.doc("challans") or {}
    if challans.get("period"):
        return {"status": OK, "finding": f"Period stated: {challans['period']}."}
    return {"status": HARD, "code": "A4-ii",
            "finding": "The period of the missing months is not stated.",
            "remedy": "State the period.",
            "cure": _doc_cure("Letter stating the period", "set-period", [
                {"k": "period", "label": "Period", "type": "text"}])}


def challan_substitute(facts: Facts) -> dict[str, Any]:
    """Whether the challans can stand in for a certificate. R14, R15.

    Three conditions, all of them the office's: every attached challan carries the bank's
    stamp, the covering letter carries the Treasury Office verification, and there is at
    least one challan. A challan whose stamp is merely FAINT still counts -- the stamp is
    present, and MC-STAMP raises the legibility separately as an observation.
    """
    challans = facts.doc("challans") or {}
    copies = list(challans.get("copies") or [])
    unstamped = [c for c in copies if not c.get("bankStamp")]
    scheduled = ((challans.get("schedule") or {}).get("items") or [])
    missing = [item for item in scheduled
               if not any(str(c.get("sr")) == str(item.get("sr")) for c in copies)]
    return {
        "ok": bool(copies) and not unstamped and bool(challans.get("toVerified")),
        "unstamped": unstamped, "missing": missing, "copies": copies, "challans": challans,
    }


def _certificate_check(item: str, clarification: str, title: str, period: str):
    """Register one of the two certificate checks. They differ only in which period they are
    for, and both are satisfied by the same evidence, which is R14 and R15 in one sentence."""

    def applies(facts: Facts) -> bool:
        return facts.is_kind("missing_credits") and facts.gazetted in (period, "mixed", "unknown")

    def run(facts: Facts) -> dict[str, Any]:
        state = challan_substitute(facts)
        challans = state["challans"]
        certificate = challans.get("certificate") or {}
        if certificate.get(period):
            return {"status": OK, "finding": "Certificate on file."}
        if state["ok"]:
            whichever = (", whichever period type applies."
                         if facts.gazetted == "unknown" else ".")
            not_covered = ""
            if state["missing"]:
                srs = ", ".join(f"Sr. {m.get('sr')}" for m in state["missing"])
                not_covered = f" Schedule {srs} is not covered; see A4-v."
            return {"status": SUB,
                    "finding": (f"No certificate, but every one of the {len(state['copies'])} "
                                f"challans attached carries the bank’s stamp and the covering "
                                f"letter carries the Treasury Office verification (page "
                                f"{challans.get('toPage')}). Accepted in place of the certificate "
                                f"({clarification}){whichever}{not_covered}"),
                    "evidence": [ev(challans.get("toPage"), "Treasury verification",
                                    challans.get("toCrop"))]}
        why: list[str] = []
        if state["unstamped"]:
            plural = "s" if len(state["unstamped"]) > 1 else ""
            verb = "y" if len(state["unstamped"]) > 1 else "ies"
            pages = ", ".join(str(c.get("page")) for c in state["unstamped"])
            why.append(f"challan{plural} at page {pages} carr{verb} no bank stamp")
        if not challans.get("toVerified"):
            why.append("the covering letter carries no Treasury Office verification")
        if not state["copies"]:
            why.append("no challans are attached")
        if state["unstamped"]:
            cure = _doc_cure("Challan copy with bank stamp", "challan-stamp", [
                {"k": "page", "label": "Replaces challan at page", "type": "select",
                 "options": [str(c.get("page")) for c in state["unstamped"]]},
                {"k": "bankStamp", "label": "Bank stamp present on the new copy", "type": "yesno"}])
        else:
            cure = _doc_cure("Treasury-verified covering letter", "to-verified", [
                {"k": "toVerified", "label": "Treasury Office verification stamp present",
                 "type": "yesno"}])
        also = (" and obtain Treasury Office verification on the covering letter"
                if not challans.get("toVerified") else "")
        return {"status": HARD,
                "finding": (f"No certificate, and the challans cannot yet stand in for it: "
                            f"{'; '.join(why)}."),
                "remedy": (f"Produce challan copies carrying the bank’s stamp{also}, or the "
                           f"certificate itself."),
                "cure": cure}

    check(id=f"MC-{'DDO' if period == 'non-gazetted' else 'AG'}-CERT", group="checklist",
          checklist=item, ref=f"{item} · {clarification}", code=item, title=title,
          applies=applies, run=run)


_certificate_check(
    "A4-iii", "R14",
    "Manual deduction certificate by DDO, with bills and acquaintance roll (non-gazetted period)",
    "non-gazetted")
_certificate_check(
    "A4-iv", "R15",
    "Manual deduction certificate by AG Office (gazetted period)",
    "gazetted")


check(
    id="MC-STAMP", group="checklist", ref="R14 · R15", code="R14",
    title="Bank stamps legible on each challan",
    applies=lambda facts: bool(
        facts.is_kind("missing_credits")
        and any(c.get("stampFaint") for c in ((facts.doc("challans") or {}).get("copies") or []))),
    run=lambda facts: [
        {"sub": f"p{c.get('page')}", "status": ADV,
         "doc": f"Challan Sr. {c.get('sr')} (page {c.get('page')})",
         "finding": (f"The bank stamp is present but too faint to read the bank, branch or date. "
                     f"{c.get('stampNote') or ''}"),
         "remedy": "Confirm against the original, or upload a clearer copy.",
         "evidence": [ev(c.get("page"), "Bank stamp", c.get("crop"))],
         "cure": _doc_cure(f"Clearer copy of challan Sr. {c.get('sr')}", "challan-stamp-clear", [
             {"k": "page", "label": "Challan page", "type": "select",
              "options": [str(c.get("page"))]},
             {"k": "legible", "label": "Bank stamp and date now legible", "type": "yesno"}])}
        for c in ((facts.doc("challans") or {}).get("copies") or []) if c.get("stampFaint")],
)


check(
    id="MC-CHALLANS", group="checklist", checklist="A4-v", ref="A4-v", code="A4-v",
    title="Challans verified by Treasury, as scheduled",
    applies=lambda facts: facts.is_kind("missing_credits"),
    run=lambda facts: _mc_challans(facts),
)


def _mc_challans(facts: Facts) -> dict[str, Any]:
    """The comparison that finds the defect. §16.3, lesson 4.

    "Comparison still finds the strongest defects: the missing challan equals the variance."
    Seven challans are scheduled and Treasury-verified for Rs 79,600; six are attached for
    Rs 71,640; the variance is Rs 7,960, which is exactly challan Sr. 4. Stating that
    identity is what turns a discrepancy into an instruction.
    """
    challans = facts.doc("challans") or {}
    copies = list(challans.get("copies") or [])
    schedule = challans.get("schedule") or {}
    attached = sum(num(c.get("amount")) or 0 for c in copies)
    scheduled_total = num(schedule.get("total"))
    items = schedule.get("items") or []
    missing = [item for item in items
               if not any(str(c.get("sr")) == str(item.get("sr")) for c in copies)]

    if not missing and (not scheduled_total or abs(attached - scheduled_total) <= 1):
        return {"status": OK,
                "finding": (f"{len(copies)} challans attached, total Rs {fmt(attached)}, agreeing "
                            f"with the Treasury-verified schedule of Rs {fmt(scheduled_total)}.")}

    variance = (scheduled_total or 0) - attached
    detail = ""
    if missing:
        parts = []
        for item in missing:
            cheque = f", cheque {item.get('cheque')}" if item.get("cheque") else ""
            parts.append(f"Sr. {item.get('sr')} ({item.get('period')}, "
                         f"Rs {fmt(item.get('amount'))}{cheque})")
        detail = f"Missing: {'; '.join(parts)}. "
    plural = "s" if len(missing) > 1 else ""
    cure = None
    if missing:
        first = missing[0]
        cure = _doc_cure(f"Challan Form 32-A, Sr. {first.get('sr')}", "add-challan", [
            {"k": "sr", "label": "Schedule Sr.", "type": "text", "expect": str(first.get("sr"))},
            {"k": "amount", "label": "Amount (Rs)", "type": "number",
             "expect": str(first.get("amount"))},
            {"k": "bankStamp", "label": "Bank stamp present", "type": "yesno"}])
    return {"status": HARD,
            "calc": {"attached": attached, "scheduled": scheduled_total, "variance": variance},
            "finding": (f"The schedule lists {len(items)} challans for Rs {fmt(scheduled_total)}, "
                        f"verified by the Treasury; {len(copies)} are attached for "
                        f"Rs {fmt(attached)}. {detail}Variance Rs {fmt(variance)}, exactly the "
                        f"missing challan{plural}."),
            "remedy": ("Attach the paid copy of the missing challan with the bank’s stamp and "
                       "the Treasury verification mark, or amend the schedule and the Treasury "
                       "verification."),
            "evidence": ([ev(challans.get("schedulePage"), "Schedule of challans",
                             challans.get("scheduleCrop"))]
                         if challans.get("schedulePage") else []),
            "cure": cure}


check(
    id="MC-GAZ", group="sap", ref="A4-iii · A4-iv · R1",
    title="BPS and gazetted status of the subscriber",
    applies=lambda facts: bool(
        facts.is_kind("missing_credits") and facts.gazetted == "unknown"
        and not (facts.sap_payslip and facts.sap_payslip.get("bps"))),
    run=lambda facts: {
        "status": SAP,
        "finding": (f"Neither BPS nor gazetted status is stated in the case "
                    f"({facts.data.get('gazettedEvidence') or ''}). It does not block: the "
                    f"challans satisfy both R14 and R15. Record it from the SAP pay slip."),
        "cure": {"kind": "sap"}},
)


# -- balance transfer, §5.5 -----------------------------------------------------------------

check(
    id="BT-PROFORMA", group="checklist", checklist="A3-i", ref="A3-i · R1", code="A3-i",
    title="Proforma particulars",
    applies=lambda facts: facts.is_kind("balance_transfer"),
    run=lambda facts: _bt_proforma(facts),
)


def _bt_proforma(facts: Facts) -> list[dict[str, Any]]:
    """One result per particular. §5.5.

    The read-from-SAP-first discipline is the point: the old manual account number, the last
    deduction and the advances in the last twelve months "are read from SAP by the section
    before anything is raised against the department". So where a column is blank and SAP has
    not been pulled, the particular is ``sap`` -- the office's own next step -- and not a
    defect in a one-page proforma.
    """
    proforma = facts.doc("proforma") or {}
    payslip = facts.sap_payslip
    rows = facts.recalc_rows
    page = proforma.get("page")
    base_evidence = [ev(page, "Proforma", proforma.get("crop"))]
    out: list[dict[str, Any]] = []

    def is_personnel_number(value: Any) -> bool:
        text = str(value or "").lower()
        return (any(word in text for word in ("personal", "pers", "p #", "p#"))
                or digits(value) == digits(facts.personnel_no))

    # 1 to 3: the particulars.
    if proforma.get("name") and proforma.get("father") and proforma.get("designation"):
        out.append({"sub": "particulars", "status": OK,
                    "doc": "Name, father name, designation, personnel no.",
                    "finding": (f"{proforma['name']} s/o {proforma['father']}, "
                                f"{proforma['designation']}, personnel no. "
                                f"{facts.personnel_no}."),
                    "evidence": base_evidence})
    else:
        out.append({"sub": "particulars", "status": HARD,
                    "doc": "Name, father name, designation",
                    "finding": "Particulars missing from the proforma.",
                    "remedy": "Complete the proforma.", "evidence": base_evidence})

    # Column 7 doubling as the posting periods is what revision 1 read as a missing advance
    # figure. It satisfies a required particular in its own right.
    if proforma.get("periods"):
        out.append({"sub": "periods", "status": OK, "doc": "Period of posting",
                    "finding": f"Stated in column 7: {proforma['periods']}.",
                    "evidence": [ev(page, "Periods", proforma.get("periodsCrop"))]})
    else:
        out.append({"sub": "periods", "status": HARD, "doc": "Period of posting",
                    "finding": "The periods of posting are not stated.",
                    "remedy": "State the periods of posting."})

    # Column 5, the new account: a personnel number confirmed by the DAO satisfies it.
    new_account = proforma.get("newAc")
    if new_account and is_personnel_number(new_account) and proforma.get("daoConfirmed"):
        out.append({"sub": "dao-ac", "status": OK,
                    "doc": "GP Fund A/c No. in the DAO (column 5)",
                    "finding": (f"Column 5 gives the personnel number, which keys the GP Fund "
                                f"account in SAP, and the respective DAO has confirmed it: "
                                f"\"{proforma['daoConfirmed']}\"."),
                    "evidence": [ev(page, "DAO confirmation", proforma.get("daoCrop"))]})
    elif new_account:
        out.append({"sub": "dao-ac", "status": OK,
                    "doc": "GP Fund A/c No. in the DAO (column 5)",
                    "finding": f"Stated: {new_account}."})
    else:
        out.append({"sub": "dao-ac", "status": HARD,
                    "doc": "GP Fund A/c No. in the DAO (column 5)",
                    "finding": "Not stated, and not confirmed by the DAO.",
                    "remedy": "State the account number and obtain DAO confirmation.",
                    "cure": _doc_cure("Completed proforma", "proforma", [
                        {"k": "newAc", "label": "New A/c no. (column 5)", "type": "text"}])})

    # Column 4, the old account. Read from SAP before it is raised against the department.
    old_account = proforma.get("oldAc")
    if old_account and not is_personnel_number(old_account) and len(digits(old_account)) > 3:
        out.append({"sub": "old-ac", "status": OK, "doc": "Old GP Fund A/c No. (column 4)",
                    "finding": f"Stated: {old_account}."})
    elif not payslip:
        out.append({"sub": "old-ac", "status": SAP, "doc": "Old GP Fund A/c No. (column 4)",
                    "finding": ("Column 4 repeats the personnel number. SAP carries any old manual "
                                "account number (pay slip Old #, re-calculation report), so the "
                                "section reads it from the extract before treating it as a "
                                "department defect."),
                    "cure": {"kind": "sap"}})
    elif payslip.get("oldGpfNo"):
        out.append({"sub": "old-ac", "status": OK, "doc": "Old GP Fund A/c No. (column 4)",
                    "finding": (f"Column 4 repeats the personnel number; SAP holds the old number "
                                f"as {payslip['oldGpfNo']}. Settled from SAP.")})
    elif rows and not num(rows[0].get("opening")):
        out.append({"sub": "old-ac", "status": OK, "doc": "Old GP Fund A/c No. (column 4)",
                    "finding": (f"SAP holds no old number and the ledger opens at nil in "
                                f"{rows[0].get('start')}, so no manual-era account exists.")})
    else:
        out.append({"sub": "old-ac", "status": HARD, "doc": "Old GP Fund A/c No. (column 4)",
                    "finding": ("Column 4 repeats the personnel number and SAP does not supply an "
                                "old account number."),
                    "remedy": ("Department to state the old GP Fund account number allotted by "
                               "AG Punjab, or \"none allotted\"."),
                    "cure": _doc_cure("Department statement of old A/c no.", "proforma", [
                        {"k": "oldAc", "label": "Old A/c no.", "type": "text"}])})

    # Column 6, the last deduction.
    if proforma.get("lastDeduction"):
        out.append({"sub": "last-ded", "status": OK,
                    "doc": "Treasury voucher and date of last deduction (column 6)",
                    "finding": f"Stated: {proforma['lastDeduction']}."})
    elif rows:
        last = next((r for r in reversed(rows) if num(r.get("subscription"))), None)
        when = (f"{last.get('start')} to {last.get('end')}" if last else "the report")
        out.append({"sub": "last-ded", "status": OK, "doc": "Last fund deduction (column 6)",
                    "finding": (f"Column 6 is blank; SAP shows the last subscriptions posted in "
                                f"{when}. Read from SAP.")})
    else:
        out.append({"sub": "last-ded", "status": SAP, "doc": "Last fund deduction (column 6)",
                    "finding": ("Column 6 is blank. The last GP Fund deduction is read from the SAP "
                                "re-calculation report, which the section pulls itself."),
                    "cure": {"kind": "sap"}})

    # Column 7, advances in the last twelve months.
    if rows:
        recent = [r for r in rows[-2:]
                  if num(r.get("tempAdvance")) or num(r.get("permanentAdvance"))]
        if recent:
            detail = "; ".join(
                f"{r.get('start')} to {r.get('end')} (Rs "
                f"{fmt((num(r.get('tempAdvance')) or 0) + (num(r.get('permanentAdvance')) or 0))})"
                for r in recent)
            out.append({"sub": "adv12", "status": CONF,
                        "doc": "Advances in the last twelve months (column 7)",
                        "finding": (f"SAP shows advances in {detail}. Carry any outstanding "
                                    f"recovery with the transfer."),
                        "cure": {"kind": "verify", "vid": "BT-ADV"}})
        else:
            out.append({"sub": "adv12", "status": OK,
                        "doc": "Advances in the last twelve months (column 7)",
                        "finding": "Nil per SAP."})
    else:
        out.append({"sub": "adv12", "status": SAP,
                    "doc": "Advances in the last twelve months (column 7)",
                    "finding": ("No figure or nil entered; column 7 was used for the posting "
                                "periods. Any advance or outstanding recovery is read from SAP "
                                "before the balance is transferred."),
                    "cure": {"kind": "sap"}})
    return out
