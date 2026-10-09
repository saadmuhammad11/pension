"""Rule catalogue, part 2: rules by case family, plus advance limits and cures.

Faithful port of rules_family.js. Advance limits are the limits the Punjab GP
Fund Rules 1978 (Compendium 2008) actually set, by clause; the office's flat
80% is shown beside every result and flagged (R9, open item GPF-O15).
"""
from __future__ import annotations

import math
import re

from .format import ADVANCES, FINALS, D, KIND, digits, ev, fmt, num, same_name, yes
from .registry import check, verified, verified_result

PARAMS = {"officeCapPct": 80, "claimTolerance": 1}

# pct: share of the balance; months: months of pay; combine: which governs.
ADV_LIMITS = {
    "1.14(1)(c)(i)": {"label": "Temporary advance, general purposes (illness, passage, ceremonies, Haj, other)",
                      "pct": 50, "months": 3, "combine": "min", "src": "Rule 1.14(1)(c)(i)",
                      "relaxable": "only for special reasons recorded in writing, never for purpose (a)(vi)"},
    "1.14(1)(d)(i)": {"label": "Temporary advance for a plot or house", "pct": 80, "months": 24,
                      "combine": "min", "src": "Rule 1.14(1)(d)(i)"},
    "1.14(1)(e)(i)-car": {"label": "Temporary advance for a car", "pct": 50, "months": 12,
                          "combine": "min", "src": "Rule 1.14(1)(e)(i)"},
    "1.14(1)(e)(i)-motorcycle": {"label": "Temporary advance for a scooter or motorcycle", "pct": 50,
                                 "months": 6, "combine": "min", "src": "Rule 1.14(1)(e)(i)"},
    "1.14(1)(e)(i)-bicycle": {"label": "Temporary advance for a bicycle", "pct": 50, "months": 4,
                             "combine": "min", "src": "Rule 1.14(1)(e)(i)"},
    "1.15(a)": {"label": "Non-refundable advance after 50, building or altering a house", "pct": 80,
                "months": 24, "combine": "min", "src": "Rule 1.15(a) with 1.14(1)(d)(i)", "minAge": 50},
    "1.15(b)": {"label": "Non-refundable advance after 50, buying a house", "pct": 80,
                "src": "Rule 1.15(b)(1)", "minAge": 50},
    "1.15(c)": {"label": "Non-refundable advance after 50, agricultural land from Government", "pct": 80,
                "src": "Rule 1.15(c)(1)", "minAge": 50},
    "1.15(d)": {"label": "Non-refundable advance after 50, illness, passage, education, ceremonies",
                "pct": 80, "months": 12, "combine": "max", "src": "Rule 1.15(d)(1)", "minAge": 50},
    "1.16": {"label": "Non-refundable advance at 50 or over, no reason needed", "pct": 100,
             "src": "Rule 1.16 (substituted 12-12-2002)", "minAge": 50},
    "1.18": {"label": "Non-refundable advance at 45 or over, building a house", "pct": 80, "months": 24,
             "combine": "min", "src": "Rule 1.18 with 1.15(a)", "minAge": 45},
}


def _doc_cure(doc_type, apply, fields=None):
    return {"kind": "doc", "docType": doc_type, "apply": apply, "fields": fields or []}


# ── Advances: refundable and non-refundable ───────────────────────────────────
def _adv_sanction(F):
    s = D(F).get("sanction")
    if s and s.get("present"):
        return {"status": "ok",
                "finding": ("Sanction No. " + (s.get("orderNo") or "(not stated)") + " dated "
                            + (s.get("date") or "(not stated)") + " of "
                            + (s.get("printedAuthority") or s.get("dept") or "the competent authority")
                            + ", page " + str(s.get("page")) + ", for Rs " + fmt(s.get("amount"))
                            + ". The signatory is checked against the DOA register."),
                "evidence": [ev(s.get("page"), "Sanction", s.get("crop"))]}
    return {"status": "hard", "finding": "No original sanction is on file.",
            "remedy": "Produce the original sanction of the competent authority.",
            "cure": _doc_cure("Original sanction", "add-sanction",
                              [{"k": "orderNo", "label": "Order no.", "type": "text"},
                               {"k": "date", "label": "Date", "type": "text"},
                               {"k": "amount", "label": "Amount sanctioned (Rs)", "type": "number"},
                               {"k": "rule", "label": "Rule quoted", "type": "text"}])}


check(id="ADV-SANCTION", group="checklist", checklist="A1-i", ref="A1-i · B1-ii", code="B1-ii",
      title="Original sanction of the competent authority",
      applies=lambda F: KIND(F, *ADVANCES), run=_adv_sanction)


def _adv_rule(F):
    s = D(F)["sanction"]
    code = "B1-iv" if KIND(F, "refundable") else "B2-ix"
    need_reason = KIND(F, "refundable")
    if s.get("rule") and (not need_reason or s.get("reason")):
        no_reason = " Under Rule 1.16 no reason is needed." if s.get("limitClause") == "1.16" else ""
        return {"status": "ok", "code": code,
                "finding": ("Rule quoted: " + s["rule"] + (". Reason: " + s["reason"] + "." if s.get("reason") else ".") + no_reason),
                "evidence": [ev(s.get("page"), "Sanction")]}
    return {"status": "hard", "code": code,
            "finding": ("The sanction does not quote the rule under which the advance is granted."
                        if not s.get("rule") else "The sanction does not state the reason for the advance."),
            "remedy": ("Obtain a sanction quoting the rule" + (" and the reason for the advance." if need_reason else ".")),
            "evidence": [ev(s.get("page"), "Sanction")],
            "cure": _doc_cure("Revised sanction", "set-sanction-rule",
                              [{"k": "rule", "label": "Rule quoted", "type": "text"},
                               {"k": "reason", "label": "Reason stated", "type": "text"}])}


check(id="ADV-RULE", group="checklist", ref="B1-iv · B2-ix", code="B1-iv",
      title="Rule and reason quoted on the sanction",
      applies=lambda F: KIND(F, *ADVANCES) and D(F).get("sanction") and D(F)["sanction"].get("present"),
      run=_adv_rule)


def _adv_cnic(F):
    c = next((x for x in (D(F).get("cnics") or []) if (x.get("whose") or "subscriber") == "subscriber"), None)
    if c:
        return {"status": "ok",
                "finding": ("CNIC copy at page " + str(c["page"]) + ", no. " + str(c.get("number"))
                            + ". Attestation is not required (R5)."),
                "evidence": [ev(c["page"], "CNIC", c.get("crop"))]}
    return {"status": "hard", "code": "A1-ii", "finding": "No copy of the subscriber's CNIC is on file.",
            "remedy": "Obtain a copy of the subscriber's CNIC. Attestation is not required.",
            "cure": _doc_cure("CNIC copy", "add-cnic",
                              [{"k": "number", "label": "CNIC number", "type": "text"},
                               {"k": "type", "label": "Card type", "type": "select", "options": ["smart", "old"]}])}


check(id="ADV-CNIC", group="checklist", checklist="A1-ii", ref="A1-ii · R5",
      title="Copy of CNIC of the subscriber", applies=lambda F: KIND(F, *ADVANCES), run=_adv_cnic)


def _adv_form(F):
    cf = D(F).get("changeForm")
    want = "05" if KIND(F, "refundable") else "06"
    name = "Form 5 (FORM PAY 05)" if KIND(F, "refundable") else "Form 6-B (FORM PAY 06)"
    code = "B1-v" if KIND(F, "refundable") else "B2-iii"
    cure = _doc_cure(name, "add-form",
                     [{"k": "personalNo", "label": "Personal number on the form", "type": "text", "expect": F.get("personnelNo")},
                      {"k": "signed", "label": "Signed by the subscriber", "type": "yesno"},
                      {"k": "ddoSigned", "label": "Signed and stamped by the DDO", "type": "yesno"}])
    if not cf or not cf.get("present"):
        return {"status": "hard", "code": code, "finding": name + " is not attached.",
                "remedy": "Attach " + name + " with the subscriber's personal number and signature.", "cure": cure}
    if want not in str(cf.get("label")):
        return {"status": "hard", "code": code,
                "finding": "The form attached is " + cf["label"] + ", not " + name + ".",
                "remedy": "Attach " + name + ".", "evidence": [ev(cf["page"], cf["label"])], "cure": cure}
    return {"status": "ok",
            "finding": (name + " at page " + str(cf["page"]) + ". Only the personal number and signatures are "
                        "mandatory; the loan details box is not examined (R6)."),
            "evidence": [ev(cf["page"], cf["label"])]}


check(id="ADV-FORM", group="checklist", checklist="A1-iii", ref="A1-iii · R6",
      title="Form 5 (refundable) or Form 6-B (non-refundable)",
      applies=lambda F: KIND(F, *ADVANCES), run=_adv_form)


def _adv_form_ddo(F):
    cf = D(F)["changeForm"]
    code = "B1-vii" if KIND(F, "refundable") else "B2-v"
    if cf.get("ddoSigned"):
        return {"status": "ok", "code": code,
                "finding": "Signed and stamped by " + (cf.get("ddoStamp") or "the DDO") + ".",
                "evidence": [ev(cf["page"], "DDO signature", cf.get("ddoCrop"))]}
    return {"status": "hard", "code": code,
            "finding": "The " + cf["label"] + " is not signed by the Drawing and Disbursing Officer.",
            "remedy": "Obtain the DDO's signature and stamp on the form.",
            "evidence": [ev(cf["page"], cf["label"])],
            "cure": _doc_cure(cf["label"] + " signed by DDO", "ddo-signed",
                              [{"k": "ddoSigned", "label": "Signed and stamped by the DDO", "type": "yesno"}])}


check(id="ADV-FORM-DDO", group="checklist", ref="B1-vii · B2-v", title="Form signed by the DDO",
      applies=lambda F: KIND(F, *ADVANCES) and D(F).get("changeForm") and D(F)["changeForm"].get("present"),
      run=_adv_form_ddo)


def _adv_persno(F):
    cf = D(F)["changeForm"]
    p = F.get("sap") and F["sap"].get("payslip")

    def cure(exp):
        return _doc_cure(cf["label"], "set-form-persno",
                         [{"k": "personalNo", "label": "Personal number on the corrected form", "type": "text", "expect": exp}])
    if not cf.get("personalNo"):
        return {"status": "hard",
                "finding": "The personal number is not filled in on the " + cf["label"] + ". It is a mandatory field.",
                "remedy": "Enter the personal number on the form.",
                "evidence": [ev(cf["page"], cf["label"])], "cure": cure(F.get("personnelNo"))}
    if not p:
        return {"status": "sap",
                "finding": "Personal number " + str(cf["personalNo"]) + " on the form. The SAP pay slip is needed to tally it.",
                "cure": {"kind": "sap"}}
    if digits(cf["personalNo"]) == digits(p.get("persNo")):
        return {"status": "ok",
                "finding": "Personal number " + str(cf["personalNo"]) + " on the " + cf["label"] + " tallies with the SAP pay slip.",
                "evidence": [ev(cf["page"], cf["label"]), ev(p.get("page"), "Pay slip")]}
    return {"status": "hard",
            "finding": ("The " + cf["label"] + " gives personal number " + str(cf["personalNo"])
                        + "; the SAP pay slip gives " + str(p.get("persNo")) + "."),
            "remedy": "Correct the personal number on the form.",
            "evidence": [ev(cf["page"], cf["label"]), ev(p.get("page"), "Pay slip")], "cure": cure(p.get("persNo"))}


check(id="ADV-PERSNO", group="identity", ref="R6", code="R6",
      title="Personal number on the form tallies with the pay slip",
      applies=lambda F: KIND(F, *ADVANCES) and D(F).get("changeForm") and D(F)["changeForm"].get("present"),
      run=_adv_persno)


def _adv_applicant(F):
    cf = D(F)["changeForm"]
    p = F.get("sap") and F["sap"].get("payslip")
    card = next((c for c in (D(F).get("cnics") or []) if (c.get("whose") or "subscriber") == "subscriber"), None)
    refs = []
    if p and p.get("name"):
        refs.append(["SAP pay slip", p["name"], same_name(cf.get("name"), p["name"])])
    if card and card.get("name"):
        refs.append(["CNIC", card["name"], same_name(cf.get("name"), card["name"])])
    if not refs:
        return {"status": "sap",
                "finding": "Name on the form: " + (cf.get("name") or "(not filled in)") + ". Nothing yet to compare it with.",
                "cure": {"kind": "sap"}}
    variants = F.get("nameVariants") or []
    bad = [r for r in refs if r[2] is False and r[1] not in variants]
    if bad:
        return {"status": "hard",
                "finding": ("Name on the " + cf["label"] + " is " + str(cf.get("name")) + "; "
                            + "; ".join(r[0] + " reads " + r[1] for r in bad) + "."),
                "remedy": "Confirm the applicant and correct the form."}
    return {"status": "ok",
            "finding": ("Name " + str(cf.get("name")) + " agrees with "
                        + " and ".join(r[0] + " (" + r[1] + ")" for r in refs) + "."
                        + (" " + F["nameNote"] if F.get("nameNote") else ""))}


check(id="ADV-APPLICANT", group="identity", ref="R6", code="R6",
      title="Applicant on the form is the subscriber",
      applies=lambda F: KIND(F, *ADVANCES) and D(F).get("changeForm") and D(F)["changeForm"].get("present"),
      run=_adv_applicant)


def _adv_form_cnic(F):
    cf = D(F)["changeForm"]
    card = next((c for c in D(F)["cnics"] if (c.get("whose") or "subscriber") == "subscriber" and c.get("number")), None)
    if digits(cf["cnic"]) == digits(card["number"]):
        return {"status": "ok", "finding": "CNIC " + str(card["number"]) + " on the form agrees with the card."}
    return {"status": "adv",
            "finding": ("The " + cf["label"] + " records CNIC " + str(cf["cnic"]) + "; the card, the SAP pay slip and "
                        "the QR codes read " + str(card["number"]) + ". The applicant is otherwise confirmed by personal "
                        "number and name, and the CNIC field is not mandatory on this form (R6), so this is noted only."),
            "remedy": "DDO to correct the CNIC on the form for the department's record.",
            "evidence": [ev(cf["page"], cf["label"], cf.get("cnicCrop")), ev(card["page"], "CNIC", card.get("crop"))],
            "cure": _doc_cure("Corrected " + cf["label"], "set-form-cnic",
                              [{"k": "cnic", "label": "CNIC on the corrected form", "type": "text", "expect": card["number"]}])}


check(id="ADV-FORM-CNIC", group="identity", ref="R6", code="R6", title="CNIC number written on the form",
      applies=lambda F: (KIND(F, *ADVANCES) and D(F).get("changeForm") and D(F)["changeForm"].get("cnic")
                         and any((c.get("whose") or "subscriber") == "subscriber" and c.get("number")
                                 for c in (D(F).get("cnics") or []))),
      run=_adv_form_cnic)


def fund_position(F) -> dict:
    """The GP Fund balance and the advance (loan) balance, as the papers print them. 30 Sep 2026.

    Extracted, never calculated (office instruction): both are the figures printed on the SAP pay
    slip -- its LOAN/FUND block, "GPF#" row and GPF-advance row (reading.payslip_text) -- with the
    page and month they were read from. Where the pay slip does not print a figure it is reported
    as not printed; nothing is worked out in its place. The re-calculation report's own printed
    closing balance is shown beside it for reference only.
    """
    sap = F.get("sap") or {}
    ps = sap.get("payslip") or {}
    rows = (sap.get("recalc") or {}).get("rows") or []
    where = {"page": ps.get("page"), "month": ps.get("month")}
    out: dict = {"gpf": None, "loan": None, "reportClosing": None, "payslip": bool(ps)}
    if ps.get("gpfBalance") is not None:
        out["gpf"] = {"value": ps["gpfBalance"], "source": "payslip", **where}
    if ps.get("loanBalance") is not None:
        out["loan"] = {"value": ps["loanBalance"], "source": "payslip", **where}
    if rows and rows[-1].get("closing") is not None:
        out["reportClosing"] = {"value": rows[-1]["closing"], "asOf": rows[-1].get("end")}
    return out


def balance_before(F):
    """Balance before the advance under examination (see spec §6.5)."""
    if F.get("balanceBasis"):
        return F["balanceBasis"]
    s = D(F).get("sanction")
    amt = s and s.get("amount")
    rc = F.get("sap") and F["sap"].get("recalc")
    ps = F.get("sap") and F["sap"].get("payslip")
    if rc and rc.get("rows"):
        col = "tempAdvance" if KIND(F, "refundable") else "permanentAdvance"
        row = next((r for r in reversed(rc["rows"]) if amt and r.get(col) and abs(r[col] - amt) <= 1), None)
        if row:
            return {"value": row["opening"], "posted": True,
                    "explanation": ("This advance (Rs " + fmt(amt) + ") is already posted in the SAP re-calculation "
                                    "report for " + row["start"] + " to " + row["end"] + ", so the pay slip balance is "
                                    "after it. The balance before it is the opening balance of that year, Rs "
                                    + fmt(row["opening"]) + ".")}
        last = rc["rows"][-1]
        return {"value": last["closing"],
                "explanation": ("Closing balance Rs " + fmt(last["closing"]) + " for " + last["start"] + " to "
                                + last["end"] + " in the SAP re-calculation report. This advance is not yet posted.")}
    if ps and ps.get("gpfBalance") is not None:
        return {"value": ps["gpfBalance"], "provisional": True,
                "explanation": ("GPF balance Rs " + fmt(ps["gpfBalance"]) + " on the pay slip for " + str(ps.get("month"))
                                + ". Without the re-calculation report it cannot be confirmed whether this advance is "
                                "already deducted.")}
    return None


def _adv_limit(F):
    s = D(F)["sanction"]
    L = ADV_LIMITS.get(s.get("limitClause"))
    b = balance_before(F)
    if not L:
        return {"status": "conf",
                "finding": ("The clause under which Rs " + fmt(s.get("amount")) + " was sanctioned ("
                            + (s.get("rule") or "not quoted") + ") could not be matched to a limit in the Rules."),
                "remedy": "Identify the clause; the limit is then applied.",
                "cure": {"kind": "verify", "vid": "ADV-LIMIT"}}
    if not b:
        return {"status": "sap",
                "finding": "Sanctioned Rs " + fmt(s.get("amount")) + " under " + L["src"] + ". The SAP balance is needed to test the limit.",
                "cure": {"kind": "sap"}}
    pay = (F.get("sap") and F["sap"].get("payslip") and F["sap"]["payslip"].get("basicPay")) or s.get("basicPay") or None
    by_pct = math.floor(b["value"] * L["pct"] / 100)
    limit = by_pct
    by_pay = None
    if L.get("months") and pay:
        by_pay = pay * L["months"]
        limit = max(by_pct, by_pay) if L.get("combine") == "max" else min(by_pct, by_pay)
    office = math.floor(b["value"] * PARAMS["officeCapPct"] / 100)
    calc = {"amount": s.get("amount"), "balance": b["value"], "rule": L["src"], "label": L["label"],
            "pct": L["pct"], "months": L.get("months"), "combine": L.get("combine"), "pay": pay,
            "byPct": by_pct, "byPay": by_pay, "ruleLimit": limit, "office": office, "officePct": PARAMS["officeCapPct"]}
    if L.get("months"):
        which = ("the greater of " if pay and L.get("combine") == "max" else ("the lesser of " if pay else ""))
        months_part = (" and " + str(L["months"]) + " months' pay (Rs " + fmt(pay) + " a month)"
                       if pay else " (months of pay not known, so the percentage alone is applied)")
    else:
        which, months_part = "", ""
    rule_text = (L["src"] + " (" + L["label"].lower() + ") allows " + which + str(L["pct"]) + "% of the balance"
                 + months_part + ": Rs " + fmt(limit) + ".")
    flag = ((" Flag: the office's stated practice of " + str(PARAMS["officeCapPct"]) + "% gives Rs " + fmt(office)
             + " for this balance, which differs from the Rules; the Rules are applied and the difference is listed "
             "under Rules in force.") if limit != office else "")
    stated = ((" The sanction itself states a balance of Rs " + fmt(s["balanceStated"]) + ", which does not reconcile to SAP.")
              if (s.get("balanceStated") and abs(s["balanceStated"] - b["value"]) > 1) else "")
    age = ""
    if L.get("minAge") and s.get("ageAtSanction"):
        a = s["ageAtSanction"]
        if a["y"] >= L["minAge"]:
            age = (" Age " + str(a["y"]) + " years " + str(a.get("m") or 0) + " months at sanction; the rule needs "
                   + str(L["minAge"]) + ".")
        else:
            age = None
    if age is None:
        return {"status": "hard", "calc": calc,
                "finding": (L["src"] + " needs the subscriber to be " + str(L["minAge"]) + " or over; the subscriber was "
                            + str(s["ageAtSanction"]["y"]) + " at sanction."),
                "remedy": "Obtain a sanction under the rule that applies to the subscriber's age."}
    basis = " Balance used: " + b["explanation"]
    if s["amount"] > limit:
        would = " The office's 80% practice would have passed it; the Rules govern." if s["amount"] <= office else ""
        relax = (", or record special reasons in writing (" + L["relaxable"] + ")") if L.get("relaxable") else ""
        return {"status": "hard", "calc": calc,
                "finding": ("Rs " + fmt(s["amount"]) + " exceeds the limit. " + rule_text + " Excess Rs "
                            + fmt(s["amount"] - limit) + "." + basis + stated + would),
                "remedy": "Reduce the sanction to Rs " + fmt(limit) + " or less" + relax + "."}
    if b.get("provisional"):
        return {"status": "conf", "calc": calc,
                "finding": "Rs " + fmt(s["amount"]) + " is within the limit on the pay slip balance. " + rule_text + basis + flag,
                "remedy": "Upload the re-calculation report to confirm the balance basis.", "cure": {"kind": "sap"}}
    if s["amount"] > office:
        return {"status": "adv", "calc": calc,
                "finding": ("Rs " + fmt(s["amount"]) + " is within the Rules. " + rule_text + " It is above the office's "
                            "stated " + str(PARAMS["officeCapPct"]) + "% practice (Rs " + fmt(office)
                            + "), so it is flagged for the office to confirm which applies." + basis + stated + age),
                "remedy": ("None under the Rules. The office to confirm whether its 80% practice overrides " + L["src"] + ".")}
    return {"status": "ok", "calc": calc,
            "finding": "Rs " + fmt(s["amount"]) + " is within the limit. " + rule_text + basis + stated + age + flag}


check(id="ADV-LIMIT", group="balance", ref="GPF Rules 1.14 to 1.18 · R9 · B1-i", code="B1-i",
      title="Advance within the limit set by the GP Fund Rules",
      applies=lambda F: KIND(F, *ADVANCES) and D(F).get("sanction") and D(F)["sanction"].get("present"),
      run=_adv_limit)


def _adv_active(F):
    s = D(F).get("sanction") or {}
    rc = F.get("sap") and F["sap"].get("recalc")
    p = F.get("sap") and F["sap"].get("payslip")
    if not (rc and rc.get("rows")):
        if not p:
            return {"status": "sap",
                    "finding": "The SAP pay slip and re-calculation report are needed to see any advance still outstanding.",
                    "cure": {"kind": "sap"}}
        # An advance balance nobody could read is not "no advance outstanding" (audit 6 Oct 2026, G4;
        # ported to the served rules 9 Oct 2026, review C2): unread is a verification task with the
        # SAP cure, until the figure is on the case. A read zero still passes.
        outstanding = num(p.get("loanBalance"))
        if outstanding is None:
            return {"status": "conf",
                    "finding": ("The pay slip's GPF advance balance could not be read, so it cannot be said whether "
                                "an earlier advance is still outstanding."),
                    "cure": {"kind": "sap"}}
        if not outstanding:
            return {"status": "ok", "finding": "The SAP pay slip shows no GPF advance outstanding."}
        return {"status": "conf",
                "finding": ("The SAP pay slip shows a GPF advance balance of Rs " + fmt(outstanding)
                            + ". Without the re-calculation report it cannot be told whether this is the advance under examination."),
                "cure": {"kind": "sap"}}
    rows = rc["rows"]
    idx = -1
    for i in range(len(rows) - 1, -1, -1):
        if s.get("amount") and rows[i].get("tempAdvance") and abs(rows[i]["tempAdvance"] - s["amount"]) <= 1:
            idx = i
            break
    before = rows[0:(idx if idx >= 0 else len(rows))]
    drawn = rec = 0
    last_rec = None
    for r in before:
        drawn += r.get("tempAdvance") or 0
        rec += r.get("recTempAdvance") or 0
        if r.get("recTempAdvance"):
            last_rec = r
    if idx >= 0:
        if p and p.get("loanBalance"):
            posted = (" The advance under examination is already posted in " + rows[idx]["start"] + " to "
                      + rows[idx]["end"] + "; the pay slip advance balance of Rs " + fmt(p["loanBalance"])
                      + " is this advance being recovered (Rs " + fmt(s["amount"]) + " less Rs "
                      + fmt(s["amount"] - p["loanBalance"]) + ").")
        else:
            posted = (" The advance under examination is already posted in " + rows[idx]["start"] + " to "
                      + rows[idx]["end"] + ".")
    else:
        posted = ""
    if drawn - rec > 1:
        return {"status": "hard",
                "finding": ("Earlier refundable advances of Rs " + fmt(drawn) + " show recoveries of only Rs " + fmt(rec)
                            + " in SAP: Rs " + fmt(drawn - rec) + " still outstanding when this advance was sanctioned." + posted),
                "remedy": ("The earlier advance must be fully recovered before a new one (Rule 1.14(1)(c) proviso). "
                           "A new advance may be settled only after the month in which it reached zero.")}
    if not drawn:
        return {"status": "ok", "finding": "No earlier refundable advance in SAP since " + rows[0]["start"] + "." + posted}
    return {"status": "ok",
            "finding": ("Earlier refundable advances of Rs " + fmt(drawn) + " were fully recovered, the last recovery in "
                        + last_rec["start"] + " to " + last_rec["end"] + "." + posted)}


check(id="ADV-ACTIVE", group="balance", ref="R12 · Rule 1.14(1)(c) proviso", code="R12",
      title="No other refundable advance outstanding",
      applies=lambda F: KIND(F, "refundable"), run=_adv_active)


# ── Final payments ────────────────────────────────────────────────────────────
def _fp_gpf10(F):
    g = D(F).get("gpf10")
    if not g or not g.get("present"):
        extra = ", and nothing in the case substitutes for it." if KIND(F, "residual") else "."
        rem_extra = (", or the officer confirms that the Form 10 filed with the original final payment covers the residual."
                     if KIND(F, "residual") else ".")
        return {"status": "hard", "finding": "G.P.F. Form 10 is not on file" + extra,
                "remedy": "Submit Form 10 signed by the DDO and the subscriber or claimant" + rem_extra,
                "cure": _doc_cure("G.P.F. Form 10", "add-gpf10",
                                  [{"k": "accountNo", "label": "GP Fund account no.", "type": "text", "expect": F.get("personnelNo")},
                                   {"k": "signed", "label": "Signed by subscriber or claimant", "type": "yesno"},
                                   {"k": "ddoSigned", "label": "Signed by DDO", "type": "yesno"}])}
    miss = list(g.get("missing") or [])
    if not miss:
        return {"status": "ok",
                "finding": ("Form 10 at page " + str(g["page"]) + ", account no. " + (g.get("accountNo") or "")
                            + ", signed." + (" " + g["note"] if g.get("note") else "")),
                "evidence": [ev(g["page"], "Form 10", g.get("crop"))]}
    p = F.get("sap") and F["sap"].get("payslip")
    sap_covers = bool(p and all(re.search(r"account|a/c|personnel", m, re.I) for m in miss) and (p.get("oldGpfNo") or p.get("persNo")))
    corr = (" " + (g.get("corroboration") or "The missing identifiers are held in SAP") + ", so this is noted only.") if sap_covers else ""
    return {"status": "adv" if sap_covers else "hard",
            "finding": "Form 10 at page " + str(g["page"]) + " does not state: " + ", ".join(miss) + "." + corr,
            "remedy": "Complete Form 10: " + ", ".join(miss) + ".",
            "evidence": [ev(g["page"], "Form 10", g.get("crop"))],
            "cure": _doc_cure("Completed G.P.F. Form 10", "gpf10-complete",
                              [{"k": "m" + str(i), "label": m + " now filled in", "type": "yesno"} for i, m in enumerate(miss)])}


check(id="FP-GPF10", group="checklist", checklist="A2-ii", ref="A2-ii · B2-i", code="B2-i",
      title="G.P.F. Form 10, properly filled and signed",
      applies=lambda F: KIND(F, *FINALS), run=_fp_gpf10)


def _fp_notif(F):
    n = D(F).get("notification")
    if n and n.get("present"):
        return {"status": "ok",
                "finding": ((n.get("label") or "Notification") + " No. " + (n.get("no") or "(not stated)") + " dated "
                            + (n.get("date") or "(not stated)") + ", page " + str(n["page"]) + "."
                            + (" " + n["note"] if n.get("note") else "")),
                "evidence": [ev(n["page"], n.get("label") or "Notification", n.get("crop"))]}
    which = "obituary" if KIND(F, "death") else ("dismissal" if KIND(F, "dismissal") else "retirement")
    return {"status": "hard", "code": "A2-iii", "finding": "The " + which + " notification is not on file.",
            "remedy": "Attach a copy of the notification.",
            "cure": _doc_cure("Notification", "add-notification",
                              [{"k": "no", "label": "Notification no.", "type": "text"},
                               {"k": "date", "label": "Date", "type": "text"}])}


check(id="FP-NOTIF", group="checklist", checklist="A2-iii", ref="A2-iii",
      title="Retirement, dismissal or obituary notification",
      applies=lambda F: KIND(F, *FINALS), run=_fp_notif)


def _fp_cnic(F):
    c = next((x for x in (D(F).get("cnics") or []) if re.search(r"subscriber|deceased", x.get("whose") or "subscriber")), None)
    if c:
        return {"status": "ok",
                "finding": ("CNIC copy of the " + (c.get("whose") or "subscriber") + " at page " + str(c["page"])
                            + ", no. " + str(c.get("number")) + ". Attestation is not required (R5)."),
                "evidence": [ev(c["page"], "CNIC", c.get("crop"))]}
    return {"status": "hard", "code": "A2-iv", "finding": "No copy of the subscriber's CNIC is on file.",
            "remedy": "Attach a copy of the subscriber's CNIC.",
            "cure": _doc_cure("CNIC copy", "add-cnic",
                              [{"k": "number", "label": "CNIC number", "type": "text"},
                               {"k": "type", "label": "Card type", "type": "select", "options": ["smart", "old"]}])}


check(id="FP-CNIC", group="checklist", checklist="A2-iv", ref="A2-iv · R5",
      title="Copy of CNIC of the subscriber", applies=lambda F: KIND(F, *FINALS), run=_fp_cnic)


def _fp_form06(F):
    cf = D(F).get("changeForm")
    if not cf or not cf.get("present"):
        return {"status": "hard", "code": "B2-iii", "finding": "Change Form-06 is not attached.",
                "remedy": "Attach Change Form-06 signed by the DDO and the subscriber.",
                "cure": _doc_cure("Change Form-06", "add-form",
                                  [{"k": "personalNo", "label": "Personal number on the form", "type": "text", "expect": F.get("personnelNo")},
                                   {"k": "signed", "label": "Signed or thumbed by subscriber/claimant", "type": "yesno"},
                                   {"k": "ddoSigned", "label": "Signed and stamped by the DDO", "type": "yesno"}])}
    gaps = []
    if not cf.get("ddoSigned"):
        gaps.append("the DDO")
    if not cf.get("sigKind") or cf.get("sigKind") == "none":
        gaps.append("the claimant" if KIND(F, "death") else "the subscriber")
    if gaps:
        return {"status": "hard", "code": "B2-v",
                "finding": "Change Form-06 at page " + str(cf["page"]) + " is not signed by " + " or ".join(gaps) + ".",
                "remedy": "Obtain the missing signature.", "evidence": [ev(cf["page"], "Form 06")],
                "cure": _doc_cure("Signed Change Form-06", "form-signatures",
                                  [{"k": "ddoSigned", "label": "Signed and stamped by the DDO", "type": "yesno"},
                                   {"k": "signed", "label": "Signed or thumbed by subscriber/claimant", "type": "yesno"}])}
    signed = "thumbed" if cf.get("sigKind") == "thumb" else "signed"
    who = "claimant" if KIND(F, "death") else "subscriber"
    return {"status": "ok",
            "finding": ("Change Form-06 at page " + str(cf["page"]) + ", signed by the DDO and " + signed + " by the "
                        + who + "." + (" " + cf["note"] if cf.get("note") else "")),
            "evidence": [ev(cf["page"], "Form 06", cf.get("crop"))]}


check(id="FP-FORM06", group="checklist", checklist="A2-v", ref="A2-v · B2-iii · B2-v",
      title="Change Form-06 signed by DDO and subscriber",
      applies=lambda F: KIND(F, *FINALS), run=_fp_form06)


def _fp_oldac(F):
    cf = D(F)["changeForm"]
    p = F.get("sap") and F["sap"].get("payslip")
    rc = F.get("sap") and F["sap"].get("recalc")
    sap_old = p["oldGpfNo"] if (p and p.get("oldGpfNo") and len(digits(p["oldGpfNo"])) > 3) else None
    if cf.get("oldGpfNo") and len(digits(cf["oldGpfNo"])) > 3:
        if sap_old and digits(sap_old) != digits(cf["oldGpfNo"]):
            return {"status": "hard",
                    "finding": "Old A/c " + str(cf["oldGpfNo"]) + " on the form; SAP pay slip Old # reads " + str(sap_old) + ".",
                    "remedy": "Reconcile the old account number."}
        return {"status": "ok",
                "finding": ("Old GP Fund A/c " + str(cf["oldGpfNo"]) + " on the form"
                            + (", agreeing with SAP Old # " + str(sap_old) + "." if sap_old else "."))}
    if sap_old:
        return {"status": "adv",
                "finding": ("The old account number is not written on the form (" + (cf.get("oldGpfNoState") or "blank")
                            + "), but SAP holds it as " + str(sap_old) + ". Noted; the office settles it from SAP."),
                "remedy": "None needed to process."}
    if not p:
        return {"status": "sap", "finding": "The old account number is not written on the form. The SAP pay slip may carry it.",
                "cure": {"kind": "sap"}}
    first = rc["rows"][0] if (rc and rc.get("rows")) else None
    if first and not first.get("opening"):
        return {"status": "ok",
                "finding": ("Field 16 is " + (cf.get("oldGpfNoState") or "blank") + ", but SAP holds no old number and the "
                            "SAP ledger opens at nil in " + first["start"] + " to " + first["end"]
                            + ", so there is no manual-era account to quote.")}
    return {"status": "conf",
            "finding": ("Field 16 is " + (cf.get("oldGpfNoState") or "blank") + " and SAP holds no old number"
                        + (", but the SAP ledger opens with Rs " + fmt(first["opening"]) + ", so a manual-era account may exist."
                           if first else ".")),
            "remedy": "Confirm the manual-era account number from the AG ledger.",
            "cure": {"kind": "verify", "vid": "FP-OLDAC"}}


check(id="FP-OLDAC", group="identity", ref="B2-vii", code="B2-vii",
      title="Old GP Fund account no. on the change form",
      applies=lambda F: KIND(F, *FINALS) and D(F).get("changeForm") and D(F)["changeForm"].get("present"),
      run=_fp_oldac)


def _fp_sb(F):
    sb = D(F).get("serviceBook")
    cure = _doc_cure("Service Book pages", "add-servicebook",
                     [{"k": "dor", "label": "Date of retirement or event entered", "type": "yesno"},
                      {"k": "order", "label": "Order entered", "type": "yesno"},
                      {"k": "leave", "label": "Leave account present", "type": "yesno"}])
    if not sb or not sb.get("present"):
        if sb and sb.get("reportedAttached"):
            v = verified(F, "FP-SB")
            if v:
                if v.get("ok"):
                    return {"status": "ok",
                            "finding": ("Original Service Book received and entries checked by " + v["by"]
                                        + (": " + v["note"] if v.get("note") else "."))}
                return {"status": "hard",
                        "finding": "Original Service Book not received, or entries missing. " + (v.get("note") or ""),
                        "remedy": "Produce the original Service Book.", "cure": cure}
            return {"status": "conf",
                    "finding": (sb["reportedAttached"] + " It is not in the scanned case, so the entries (date of the "
                                "event, the order, leave account) cannot be checked from the file."),
                    "remedy": "Confirm the original Service Book is on hand and check the entries.",
                    "cure": {"kind": "verify", "vid": "FP-SB"}}
        return {"status": "hard", "finding": "No Service Book is on file for a non-gazetted subscriber.",
                "remedy": "Produce the original Service Book.", "cure": cure}
    e = sb.get("entries") or {}
    miss = []
    if not e.get("dor"):
        miss.append("date of retirement")
    if not e.get("order"):
        miss.append("order of retirement")
    if not e.get("leave"):
        miss.append("leave account")
    if not miss:
        return {"status": "ok", "finding": "Service Book carries the requisite entries."}
    v = verified(F, "FP-SB")
    if v:
        if v.get("ok"):
            return {"status": "ok",
                    "finding": ("Entries checked on the original Service Book by " + v["by"]
                                + (": " + v["note"] if v.get("note") else "."))}
        return {"status": "hard",
                "finding": "The original Service Book does not show: " + ", ".join(miss) + ". " + (v.get("note") or ""),
                "remedy": "Department to complete the Service Book entries.", "cure": cure}
    note = sb.get("note") or ("pages " + ", ".join(str(x) for x in (sb.get("pages") or [])))
    return {"status": "conf",
            "finding": ("Only " + note + " of the Service Book are in the scanned case, so the " + ", ".join(miss)
                        + " cannot be seen. That does not show they are missing from the original."),
            "remedy": ("Check the entries on the original Service Book and record the result. If they are missing, "
                       "the department completes them (B2-viii)."),
            "evidence": [ev(p, "Service Book") for p in (sb.get("pages") or [])],
            "cure": {"kind": "verify", "vid": "FP-SB"}}


check(id="FP-SB", group="checklist", checklist="A2-vii", ref="A2-vii · B2-viii", code="B2-viii",
      title="Original Service Book (non-gazetted)",
      applies=lambda F: KIND(F, "final", "death", "dismissal") and F.get("gazetted") == "non-gazetted",
      run=_fp_sb)


def posted_claim(F):
    rows = F.get("sap") and F["sap"].get("recalc") and F["sap"]["recalc"].get("rows")
    c = F.get("claim")
    if not rows or not c or not c.get("amount"):
        return None
    i = next((idx for idx, r in enumerate(rows)
              if r.get("permanentAdvance") and abs(r["permanentAdvance"] - c["amount"]) <= PARAMS["claimTolerance"]), -1)
    return None if i < 0 else {"row": rows[i], "last": rows[-1]}


def _fp_posted(F):
    p = posted_claim(F)
    rc = F["sap"]["recalc"]
    if not p:
        return {"status": "ok",
                "finding": "SAP posts no permanent advance equal to the claim, so nothing has been paid against it yet."}
    v = verified(F, "FP-POSTED")
    if v:
        return verified_result(v, "The SAP posting is this claim; pay order recorded.",
                               "The SAP posting is a separate earlier payment, so paying the claim would pay it twice.")
    basis = F["claim"].get("basis") or ("Rs " + fmt(F["claim"]["amount"]))
    return {"status": "conf",
            "finding": ("SAP already posts a permanent advance of Rs " + fmt(p["row"]["permanentAdvance"]) + " in "
                        + p["row"]["start"] + " to " + p["row"]["end"] + ", equal to the claim (" + basis + "). The report "
                        "was pulled after the office processed the case, so this is most likely the claim itself. If it were "
                        "a separate earlier payment, paying the claim would pay it twice."),
            "remedy": ("Before payment, confirm from the SAP ledger or the GP Fund Payment Register that the posting is "
                       "this claim, and record the pay order."),
            "evidence": [ev(rc["page"], "Re-calculation report")] if rc.get("page") else [],
            "cure": {"kind": "verify", "vid": "FP-POSTED"}}


check(id="FP-POSTED", group="balance", ref="R11", code="R11", title="Claim already posted in SAP",
      applies=lambda F: KIND(F, "final", "death", "dismissal") and bool(F.get("sap") and F["sap"].get("recalc") and F.get("claim")),
      run=_fp_posted)


def _fp_residual(F):
    p = posted_claim(F)
    left = p["last"]["closing"]
    rc = F["sap"]["recalc"]
    if not (left and left > 0):
        return {"status": "ok", "finding": "Nothing is left in SAP after the posting."}
    if F["claim"].get("residualNote"):
        return {"status": "na", "finding": "Rs " + fmt(left) + " is left in SAP after the posting. " + F["claim"]["residualNote"]}
    made = (": " + F["claim"]["residualMadeOf"]) if F["claim"].get("residualMadeOf") else ""
    who = "entitled family" if KIND(F, "death") else "subscriber"
    return {"status": "adv",
            "finding": ("After the Rs " + fmt(F["claim"]["amount"]) + " posting, SAP still holds Rs " + fmt(left) + made
                        + ". A residual payment appears due to the " + who + "."),
            "remedy": "Section to process the residual on a residual claim.",
            "evidence": [ev(rc["page"], "Re-calculation report")] if rc.get("page") else []}


check(id="FP-RESIDUAL", group="balance", ref="B2-vi", code="B2-vi",
      title="Balance left in SAP after the claim",
      applies=lambda F: KIND(F, "final", "death", "dismissal") and bool(posted_claim(F)),
      run=_fp_residual)


# ── Death cases (heirs, affidavit, succession, OSD) ──────────────────────────
def _death_heirs(F):
    heirs = D(F)["death"].get("heirs") or []
    miss = [h for h in heirs if not h.get("cnicCopy") and not h.get("minor")]
    if not heirs:
        return {"status": "conf", "finding": "The legal heirs could not be established from the case.",
                "cure": {"kind": "verify", "vid": "DEATH-HEIRS"}}
    if not miss:
        adults = ", ".join(h["name"] for h in heirs if not h.get("minor"))
        minors = [h for h in heirs if h.get("minor")]
        minor_txt = (" Minor heirs: " + ", ".join(h["name"] for h in minors)
                     + ", covered by the NADRA family registration certificate.") if minors else ""
        return {"status": "ok", "finding": "Copies on file for every adult legal heir: " + adults + "." + minor_txt}
    return {"status": "hard",
            "finding": "No CNIC copy for " + ", ".join(h["name"] + " (" + h["relation"] + ")" for h in miss) + ".",
            "remedy": "Attach CNIC copies for every adult legal heir.",
            "cure": _doc_cure("CNIC copy of legal heir", "add-heir-cnic",
                              [{"k": "name", "label": "Heir", "type": "select", "options": [h["name"] for h in miss]},
                               {"k": "number", "label": "CNIC number", "type": "text"}])}


check(id="DEATH-HEIRS", group="checklist", checklist="A2-iv", ref="A2-iv", code="A2-iv",
      title="CNIC copies of all legal heirs",
      applies=lambda F: KIND(F, "death") and D(F).get("death"), run=_death_heirs)


def _death_affidavit(F):
    a = D(F)["death"].get("affidavit") or {}
    if a.get("present") and a.get("original"):
        return {"status": "ok", "finding": (a.get("label") or "Affidavit") + " at page " + str(a["page"]) + ".",
                "evidence": [ev(a["page"], "Affidavit")]}
    if a.get("present"):
        finding = (a.get("label") or "The document") + " at page " + str(a["page"]) + " is not an affidavit for lawful widow. " + (a.get("note") or "")
    else:
        finding = "No affidavit for lawful widow is on file."
    return {"status": "hard", "finding": finding,
            "remedy": "Produce the original affidavit for lawful widow.",
            "evidence": [ev(a["page"], a.get("label") or "Document")] if a.get("page") else [],
            "cure": _doc_cure("Original affidavit for lawful widow", "add-affidavit",
                              [{"k": "original", "label": "Original, on stamp paper, attested", "type": "yesno"}])}


check(id="DEATH-AFFIDAVIT", group="checklist", checklist="A2-vi", ref="A2-vi", code="A2-vi",
      title="Original affidavit for lawful widow",
      applies=lambda F: KIND(F, "death") and D(F).get("death") and D(F)["death"].get("widowClaim"),
      run=_death_affidavit)


def _death_succession(F):
    d = D(F)["death"]
    p = F.get("sap") and F["sap"].get("payslip")
    osd_sap = bool(p and p.get("osdPost") and re.search(r"yes|created|osd", str(p["osdPost"]), re.I))
    if osd_sap:
        return {"status": "ok",
                "finding": ("The SAP pay slip shows an OSD post created (" + str(p["osdPost"])
                            + "). A succession certificate is not required (R13).")}
    if d.get("successionCert") == "granted":
        return {"status": "ok", "finding": "Succession certificate granted, page " + str(d.get("successionPage")) + "."}
    if d.get("successionRequired") is False:
        return {"status": "ok",
                "finding": "Not required: " + (d.get("successionNote") or "one widow and heirs within the family.")}
    if not p:
        return {"status": "sap",
                "finding": ("Succession certificate: " + (d.get("successionNote") or "not on file")
                            + ". If SAP shows an OSD post created, it is not required (R13). Pull the pay slip first."),
                "cure": {"kind": "sap"}}
    if d.get("osdAnnotation"):
        v = verified(F, "DEATH-OSD")
        if v:
            if v.get("ok"):
                return {"status": "ok",
                        "finding": ("OSD post creation confirmed in SAP by " + v["by"] + (": " + v["note"] if v.get("note") else "")
                                    + ". Succession certificate not required (R13).")}
            return {"status": "hard",
                    "finding": "SAP does not show an OSD post, and no succession certificate is on file. " + (d.get("successionNote") or ""),
                    "remedy": "Produce the succession certificate granted by the court.",
                    "cure": _doc_cure("Succession certificate", "add-succession",
                                      [{"k": "granted", "label": "Certificate granted by the court", "type": "yesno"}])}
        oa = d["osdAnnotation"]
        return {"status": "conf",
                "finding": (oa["where"] + " is annotated \"" + oa["text"] + "\", but the SAP pay slip in the case carries "
                            "no OSD post indicator. " + (d.get("successionNote") or "")),
                "remedy": "Confirm in SAP whether an OSD post was created. If so no succession certificate is needed (R13).",
                "cure": {"kind": "verify", "vid": "DEATH-OSD"},
                "evidence": [ev(oa["page"], "OSD annotation", oa.get("crop"))]}
    return {"status": "hard", "finding": "No succession certificate. " + (d.get("successionNote") or ""),
            "remedy": "Produce the succession certificate, or evidence from SAP that an OSD post was created.",
            "cure": _doc_cure("Succession certificate", "add-succession",
                              [{"k": "granted", "label": "Certificate granted by the court", "type": "yesno"}])}


check(id="DEATH-SUCCESSION", group="checklist", checklist="A2-vi", ref="A2-vi · R13", code="A2-vi",
      title="Succession certificate, or OSD post created",
      applies=lambda F: KIND(F, "death") and D(F).get("death"), run=_death_succession)


# ── Missing credits ───────────────────────────────────────────────────────────
def _mc_period(F):
    ch = D(F).get("challans") or {}
    if ch.get("period"):
        return {"status": "ok", "finding": "Period stated: " + ch["period"] + "."}
    return {"status": "hard", "code": "A4-ii", "finding": "The period of the missing months is not stated.",
            "remedy": "State the period.",
            "cure": _doc_cure("Letter stating the period", "set-period",
                              [{"k": "period", "label": "Period", "type": "text"}])}


check(id="MC-PERIOD", group="checklist", checklist="A4-ii", ref="A4-ii", title="Period of missing months",
      applies=lambda F: KIND(F, "missing_credits"), run=_mc_period)


def challan_substitute(F):
    ch = D(F).get("challans") or {}
    copies = ch.get("copies") or []
    no_stamp = [c for c in copies if not c.get("bankStamp")]
    items = (ch.get("schedule") or {}).get("items") or []
    missing = [it for it in items if not any(str(c.get("sr")) == str(it["sr"]) for c in copies)]
    return {"ok": len(copies) > 0 and not no_stamp and ch.get("toVerified"),
            "noStamp": no_stamp, "missing": missing, "copies": copies, "ch": ch}


def _make_mc_cert(period, r, item):
    def run(F):
        x = challan_substitute(F)
        if x["ch"].get("certificate") and x["ch"]["certificate"].get(period):
            return {"status": "ok", "finding": "Certificate on file."}
        if x["ok"]:
            whichever = ", whichever period type applies." if F.get("gazetted") == "unknown" else "."
            missing_txt = ((" Schedule " + ", ".join("Sr. " + str(m["sr"]) for m in x["missing"])
                            + " is not covered; see A4-v.") if x["missing"] else "")
            return {"status": "sub",
                    "finding": ("No certificate, but every one of the " + str(len(x["copies"])) + " challans attached "
                                "carries the bank's stamp and the covering letter carries the Treasury Office verification "
                                "(page " + str(x["ch"].get("toPage")) + "). Accepted in place of the certificate (" + r + ")"
                                + whichever + missing_txt),
                    "evidence": [ev(x["ch"].get("toPage"), "Treasury verification", x["ch"].get("toCrop"))]}
        why = []
        if x["noStamp"]:
            plural = "s" if len(x["noStamp"]) > 1 else ""
            verb = "y" if len(x["noStamp"]) > 1 else "ies"
            why.append("challan" + plural + " at page " + ", ".join(str(c["page"]) for c in x["noStamp"])
                       + " carr" + verb + " no bank stamp")
        if not x["ch"].get("toVerified"):
            why.append("the covering letter carries no Treasury Office verification")
        if not x["copies"]:
            why.append("no challans are attached")
        extra_remedy = " and obtain Treasury Office verification on the covering letter" if not x["ch"].get("toVerified") else ""
        if x["noStamp"]:
            cure = _doc_cure("Challan copy with bank stamp", "challan-stamp",
                             [{"k": "page", "label": "Replaces challan at page", "type": "select", "options": [str(c["page"]) for c in x["noStamp"]]},
                              {"k": "bankStamp", "label": "Bank stamp present on the new copy", "type": "yesno"}])
        else:
            cure = _doc_cure("Treasury-verified covering letter", "to-verified",
                             [{"k": "toVerified", "label": "Treasury Office verification stamp present", "type": "yesno"}])
        return {"status": "hard",
                "finding": "No certificate, and the challans cannot yet stand in for it: " + "; ".join(why) + ".",
                "remedy": ("Produce challan copies carrying the bank's stamp" + extra_remedy + ", or the certificate itself."),
                "cure": cure}
    return run


for _id, _item, _r, _title, _period in [
    ["MC-DDO-CERT", "A4-iii", "R14", "Manual deduction certificate by DDO, with bills and acquaintance roll (non-gazetted period)", "non-gazetted"],
    ["MC-AG-CERT", "A4-iv", "R15", "Manual deduction certificate by AG Office (gazetted period)", "gazetted"],
]:
    check(id=_id, group="checklist", checklist=_item, ref=_item + " · " + _r, code=_item, title=_title,
          applies=(lambda period: (lambda F: KIND(F, "missing_credits")
                                    and (F.get("gazetted") == period or F.get("gazetted") in ("mixed", "unknown"))))(_period),
          run=_make_mc_cert(_period, _r, _item))


def _mc_stamp(F):
    out = []
    for c in D(F)["challans"]["copies"]:
        if not c.get("stampFaint"):
            continue
        out.append({"sub": "p" + str(c["page"]), "status": "adv", "doc": "Challan Sr. " + str(c["sr"]) + " (page " + str(c["page"]) + ")",
                    "finding": "The bank stamp is present but too faint to read the bank, branch or date. " + (c.get("stampNote") or ""),
                    "remedy": "Confirm against the original, or upload a clearer copy.",
                    "evidence": [ev(c["page"], "Bank stamp", c.get("crop"))],
                    "cure": _doc_cure("Clearer copy of challan Sr. " + str(c["sr"]), "challan-stamp-clear",
                                      [{"k": "page", "label": "Challan page", "type": "select", "options": [str(c["page"])]},
                                       {"k": "legible", "label": "Bank stamp and date now legible", "type": "yesno"}])})
    return out


check(id="MC-STAMP", group="checklist", ref="R14 · R15", code="R14", title="Bank stamps legible on each challan",
      applies=lambda F: KIND(F, "missing_credits") and any(c.get("stampFaint") for c in ((D(F).get("challans") or {}).get("copies") or [])),
      run=_mc_stamp)


def _mc_challans(F):
    ch = D(F).get("challans") or {}
    copies = ch.get("copies") or []
    sch = ch.get("schedule") or {}
    attached = sum(c.get("amount") or 0 for c in copies)
    missing = [it for it in (sch.get("items") or []) if not any(str(c.get("sr")) == str(it["sr"]) for c in copies)]
    if not missing and (not sch.get("total") or abs(attached - sch["total"]) <= 1):
        return {"status": "ok",
                "finding": (str(len(copies)) + " challans attached, total Rs " + fmt(attached)
                            + ", agreeing with the Treasury-verified schedule of Rs " + fmt(sch.get("total")) + ".")}
    miss_txt = ("Missing: " + "; ".join("Sr. " + str(m["sr"]) + " (" + m["period"] + ", Rs " + fmt(m["amount"])
                                        + (", cheque " + m["cheque"] if m.get("cheque") else "") + ")" for m in missing) + ". ") if missing else ""
    plural = "s" if len(missing) > 1 else ""
    return {"status": "hard",
            "calc": {"attached": attached, "scheduled": sch.get("total"), "variance": (sch.get("total") or 0) - attached},
            "finding": ("The schedule lists " + str(len(sch.get("items") or [])) + " challans for Rs " + fmt(sch.get("total"))
                        + ", verified by the Treasury; " + str(len(copies)) + " are attached for Rs " + fmt(attached) + ". "
                        + miss_txt + "Variance Rs " + fmt((sch.get("total") or 0) - attached)
                        + ", exactly the missing challan" + plural + "."),
            "remedy": ("Attach the paid copy of the missing challan with the bank's stamp and the Treasury verification "
                       "mark, or amend the schedule and the Treasury verification."),
            "evidence": [ev(ch.get("schedulePage"), "Schedule of challans", ch.get("scheduleCrop"))] if ch.get("schedulePage") else [],
            "cure": (_doc_cure("Challan Form 32-A, Sr. " + str(missing[0]["sr"]), "add-challan",
                               [{"k": "sr", "label": "Schedule Sr.", "type": "text", "expect": str(missing[0]["sr"])},
                                {"k": "amount", "label": "Amount (Rs)", "type": "number", "expect": str(missing[0]["amount"])},
                                {"k": "bankStamp", "label": "Bank stamp present", "type": "yesno"}]) if missing else None)}


check(id="MC-CHALLANS", group="checklist", checklist="A4-v", ref="A4-v", code="A4-v",
      title="Challans verified by Treasury, as scheduled",
      applies=lambda F: KIND(F, "missing_credits"), run=_mc_challans)


def _mc_gaz(F):
    return {"status": "sap",
            "finding": ("Neither BPS nor gazetted status is stated in the case (" + (F.get("gazettedEvidence") or "")
                        + "). It does not block: the challans satisfy both R14 and R15. Record it from the SAP pay slip."),
            "cure": {"kind": "sap"}}


check(id="MC-GAZ", group="sap", ref="A4-iii · A4-iv · R1", title="BPS and gazetted status of the subscriber",
      applies=lambda F: (KIND(F, "missing_credits") and F.get("gazetted") == "unknown"
                         and not (F.get("sap") and F["sap"].get("payslip") and F["sap"]["payslip"].get("bps"))),
      run=_mc_gaz)


# ── Balance transfer ──────────────────────────────────────────────────────────
def _bt_proforma(F):
    pf = D(F).get("proforma") or {}
    p = F.get("sap") and F["sap"].get("payslip")
    rc = F.get("sap") and F["sap"].get("recalc")
    out = []
    E = [ev(pf.get("page"), "Proforma", pf.get("crop"))]

    def pers_only(v):
        return bool(re.search(r"personal|pers|p\s*#", v or "", re.I)) or digits(v) == digits(F.get("personnelNo"))

    if pf.get("name") and pf.get("father") and pf.get("designation"):
        out.append({"sub": "particulars", "status": "ok", "doc": "Name, father name, designation, personnel no.",
                    "finding": (pf["name"] + " s/o " + pf["father"] + ", " + pf["designation"] + ", personnel no. "
                                + str(F.get("personnelNo")) + "."), "evidence": E})
    else:
        out.append({"sub": "particulars", "status": "hard", "doc": "Name, father name, designation",
                    "finding": "Particulars missing from the proforma.", "remedy": "Complete the proforma.", "evidence": E})
    if pf.get("periods"):
        out.append({"sub": "periods", "status": "ok", "doc": "Period of posting",
                    "finding": "Stated in column 7: " + pf["periods"] + ".",
                    "evidence": [ev(pf.get("page"), "Periods", pf.get("periodsCrop"))]})
    else:
        out.append({"sub": "periods", "status": "hard", "doc": "Period of posting",
                    "finding": "The periods of posting are not stated.", "remedy": "State the periods of posting."})
    if pf.get("newAc") and pers_only(pf["newAc"]) and pf.get("daoConfirmed"):
        out.append({"sub": "dao-ac", "status": "ok", "doc": "GP Fund A/c No. in the DAO (column 5)",
                    "finding": ("Column 5 gives the personnel number, which keys the GP Fund account in SAP, and the "
                                "respective DAO has confirmed it: \"" + pf["daoConfirmed"] + "\"."),
                    "evidence": [ev(pf.get("page"), "DAO confirmation", pf.get("daoCrop"))]})
    elif pf.get("newAc"):
        out.append({"sub": "dao-ac", "status": "ok", "doc": "GP Fund A/c No. in the DAO (column 5)",
                    "finding": "Stated: " + pf["newAc"] + "."})
    else:
        out.append({"sub": "dao-ac", "status": "hard", "doc": "GP Fund A/c No. in the DAO (column 5)",
                    "finding": "Not stated, and not confirmed by the DAO.",
                    "remedy": "State the account number and obtain DAO confirmation.",
                    "cure": _doc_cure("Completed proforma", "proforma",
                                      [{"k": "newAc", "label": "New A/c no. (column 5)", "type": "text"}])})
    if pf.get("oldAc") and not pers_only(pf["oldAc"]) and len(digits(pf["oldAc"])) > 3:
        out.append({"sub": "old-ac", "status": "ok", "doc": "Old GP Fund A/c No. (column 4)", "finding": "Stated: " + pf["oldAc"] + "."})
    elif not p:
        out.append({"sub": "old-ac", "status": "sap", "doc": "Old GP Fund A/c No. (column 4)",
                    "finding": ("Column 4 repeats the personnel number. SAP carries any old manual account number (pay slip "
                                "Old #, re-calculation report), so the section reads it from the extract before treating it "
                                "as a department defect."), "cure": {"kind": "sap"}})
    elif p.get("oldGpfNo"):
        out.append({"sub": "old-ac", "status": "ok", "doc": "Old GP Fund A/c No. (column 4)",
                    "finding": "Column 4 repeats the personnel number; SAP holds the old number as " + str(p["oldGpfNo"]) + ". Settled from SAP."})
    elif rc and rc.get("rows") and not rc["rows"][0].get("opening"):
        out.append({"sub": "old-ac", "status": "ok", "doc": "Old GP Fund A/c No. (column 4)",
                    "finding": "SAP holds no old number and the ledger opens at nil in " + rc["rows"][0]["start"] + ", so no manual-era account exists."})
    else:
        out.append({"sub": "old-ac", "status": "hard", "doc": "Old GP Fund A/c No. (column 4)",
                    "finding": "Column 4 repeats the personnel number and SAP does not supply an old account number.",
                    "remedy": "Department to state the old GP Fund account number allotted by AG Punjab, or \"none allotted\".",
                    "cure": _doc_cure("Department statement of old A/c no.", "proforma",
                                      [{"k": "oldAc", "label": "Old A/c no.", "type": "text"}])})
    if pf.get("lastDeduction"):
        out.append({"sub": "last-ded", "status": "ok", "doc": "Treasury voucher and date of last deduction (column 6)",
                    "finding": "Stated: " + pf["lastDeduction"] + "."})
    elif rc and rc.get("rows"):
        last = next((r for r in reversed(rc["rows"]) if r.get("subscription")), None)
        where = (last["start"] + " to " + last["end"]) if last else "the report"
        out.append({"sub": "last-ded", "status": "ok", "doc": "Last fund deduction (column 6)",
                    "finding": "Column 6 is blank; SAP shows the last subscriptions posted in " + where + ". Read from SAP."})
    else:
        out.append({"sub": "last-ded", "status": "sap", "doc": "Last fund deduction (column 6)",
                    "finding": ("Column 6 is blank. The last GP Fund deduction is read from the SAP re-calculation report, "
                                "which the section pulls itself."), "cure": {"kind": "sap"}})
    if rc and rc.get("rows"):
        recent = [r for r in rc["rows"][-2:] if r.get("tempAdvance") or r.get("permanentAdvance")]
        if recent:
            detail = "; ".join(r["start"] + " to " + r["end"] + " (Rs " + fmt((r.get("tempAdvance") or 0) + (r.get("permanentAdvance") or 0)) + ")" for r in recent)
            out.append({"sub": "adv12", "status": "conf", "doc": "Advances in the last twelve months (column 7)",
                        "finding": "SAP shows advances in " + detail + ". Carry any outstanding recovery with the transfer.",
                        "cure": {"kind": "verify", "vid": "BT-ADV"}})
        else:
            out.append({"sub": "adv12", "status": "ok", "doc": "Advances in the last twelve months (column 7)", "finding": "Nil per SAP."})
    else:
        out.append({"sub": "adv12", "status": "sap", "doc": "Advances in the last twelve months (column 7)",
                    "finding": ("No figure or nil entered; column 7 was used for the posting periods. Any advance or "
                                "outstanding recovery is read from SAP before the balance is transferred."),
                    "cure": {"kind": "sap"}})
    return out


check(id="BT-PROFORMA", group="checklist", checklist="A3-i", ref="A3-i · R1", code="A3-i",
      title="Proforma particulars", applies=lambda F: KIND(F, "balance_transfer"), run=_bt_proforma)


# ═══════════════════════════════════════════════════════════════════════════════
# CURES: how a confirmed upload changes the facts. The rules then decide.
# ═══════════════════════════════════════════════════════════════════════════════
def _up(file):
    return "upload: " + str(file)


def _cure_add_sanction(F, v, f):
    s = F["docs"].get("sanction") or {}
    s.update({"present": True, "page": _up(f), "orderNo": v.get("orderNo"), "date": v.get("date"),
              "amount": num(v.get("amount")), "rule": v.get("rule")})
    F["docs"]["sanction"] = s


def _cure_set_sanction_rule(F, v, f=None):
    s = F["docs"]["sanction"]
    s["rule"] = v.get("rule") or s.get("rule")
    s["reason"] = v.get("reason") or s.get("reason")


def _cure_sanction_qr(F, v, f):
    F["qr"] = [q for q in (F.get("qr") or []) if q["id"] != "sanction-upload"]
    F["qr"].append({"id": "sanction-upload", "page": _up(f), "doc": "uploaded QR-coded sanction",
                    "symbology": "QR code", "decoded": True, "payload": v.get("payload"),
                    "compare": [{"field": "Content", "qrVal": v.get("payload") or "(not entered)",
                                 "docVal": "the printed sanction", "docLabel": "sanction", "match": yes(v.get("agrees"))}]})
    F["docs"]["sanction"]["qrId"] = "sanction-upload"


def _cure_add_cnic(F, v, f):
    F["docs"].setdefault("cnics", [])
    F["docs"]["cnics"].append({"page": _up(f), "whose": "subscriber", "type": v.get("type") or "smart",
                               "number": v.get("number"), "attested": False})


def _cure_add_form(F, v, f):
    lab = "FORM PAY 05" if KIND(F, "refundable") else "FORM PAY 06"
    cf = F["docs"].get("changeForm") or {}
    cf.update({"present": True, "label": lab, "page": _up(f), "personalNo": v.get("personalNo"),
               "sigKind": "signature" if yes(v.get("signed")) else "none", "ddoSigned": yes(v.get("ddoSigned"))})
    F["docs"]["changeForm"] = cf


def _cure_ddo_signed(F, v, f=None):
    F["docs"]["changeForm"]["ddoSigned"] = yes(v.get("ddoSigned"))


def _cure_form_signed(F, v, f=None):
    F["docs"]["changeForm"]["sigKind"] = "signature" if yes(v.get("signed")) else "none"


def _cure_form_signatures(F, v, f=None):
    cf = F["docs"]["changeForm"]
    if yes(v.get("ddoSigned")):
        cf["ddoSigned"] = True
    if yes(v.get("signed")) and (not cf.get("sigKind") or cf.get("sigKind") == "none"):
        cf["sigKind"] = "signature"


def _cure_set_form_persno(F, v, f=None):
    F["docs"]["changeForm"]["personalNo"] = v.get("personalNo")


def _cure_set_form_cnic(F, v, f=None):
    F["docs"]["changeForm"]["cnic"] = v.get("cnic")


def _cure_add_gpf10(F, v, f):
    missing = ([] if yes(v.get("signed")) else ["signature of subscriber or claimant"]) \
        + ([] if yes(v.get("ddoSigned")) else ["signature of DDO"]) \
        + ([] if v.get("accountNo") else ["GP Fund account no."])
    F["docs"]["gpf10"] = {"present": True, "page": _up(f), "accountNo": v.get("accountNo"), "missing": missing}


def _cure_gpf10_complete(F, v, f=None):
    g = F["docs"]["gpf10"]
    g["missing"] = [m for i, m in enumerate(g.get("missing") or []) if not yes(v.get("m" + str(i)))]


def _cure_add_notification(F, v, f):
    F["docs"]["notification"] = {"present": True, "page": _up(f), "no": v.get("no"), "date": v.get("date"), "label": "Notification"}


def _cure_set_oldac(F, v, f=None):
    F["docs"]["changeForm"]["oldGpfNo"] = v.get("oldGpfNo")


def _cure_add_servicebook(F, v, f):
    F["docs"]["serviceBook"] = {"present": True, "pages": [_up(f)],
                                "entries": {"dor": yes(v.get("dor")), "order": yes(v.get("order")), "leave": yes(v.get("leave"))},
                                "note": "uploaded pages"}


def _cure_add_heir_cnic(F, v, f=None):
    h = next((x for x in F["docs"]["death"]["heirs"] if x["name"] == v.get("name")), None)
    if h:
        h["cnicCopy"] = True


def _cure_add_affidavit(F, v, f):
    F["docs"]["death"]["affidavit"] = {"present": True, "original": yes(v.get("original")), "page": _up(f), "label": "Affidavit for lawful widow"}


def _cure_add_succession(F, v, f):
    if yes(v.get("granted")):
        F["docs"]["death"]["successionCert"] = "granted"
        F["docs"]["death"]["successionPage"] = _up(f)


def _cure_set_period(F, v, f=None):
    F["docs"]["challans"]["period"] = v.get("period")


def _cure_challan_stamp(F, v, f=None):
    c = next((x for x in F["docs"]["challans"]["copies"] if str(x["page"]) == str(v.get("page"))), None)
    if c and yes(v.get("bankStamp")):
        c["bankStamp"] = True


def _cure_challan_stamp_clear(F, v, f=None):
    c = next((x for x in F["docs"]["challans"]["copies"] if str(x["page"]) == str(v.get("page"))), None)
    if c and yes(v.get("legible")):
        c["stampFaint"] = False


def _cure_to_verified(F, v, f=None):
    F["docs"]["challans"]["toVerified"] = yes(v.get("toVerified"))


def _cure_add_challan(F, v, f):
    F["docs"]["challans"]["copies"].append({"page": _up(f), "sr": v.get("sr"), "amount": num(v.get("amount")), "bankStamp": yes(v.get("bankStamp"))})


def _cure_proforma(F, v, f=None):
    pf = F["docs"]["proforma"]
    pf["oldAc"] = v.get("oldAc") or pf.get("oldAc")
    pf["newAc"] = v.get("newAc") or pf.get("newAc")
    pf["lastDeduction"] = v.get("lastDeduction") or pf.get("lastDeduction")


CURES = {
    "add-sanction": _cure_add_sanction, "set-sanction-rule": _cure_set_sanction_rule, "sanction-qr": _cure_sanction_qr,
    "add-cnic": _cure_add_cnic, "add-form": _cure_add_form, "ddo-signed": _cure_ddo_signed, "form-signed": _cure_form_signed,
    "form-signatures": _cure_form_signatures, "set-form-persno": _cure_set_form_persno, "set-form-cnic": _cure_set_form_cnic,
    "add-gpf10": _cure_add_gpf10, "gpf10-complete": _cure_gpf10_complete, "add-notification": _cure_add_notification,
    "set-oldac": _cure_set_oldac, "add-servicebook": _cure_add_servicebook, "add-heir-cnic": _cure_add_heir_cnic,
    "add-affidavit": _cure_add_affidavit, "add-succession": _cure_add_succession, "set-period": _cure_set_period,
    "challan-stamp": _cure_challan_stamp, "challan-stamp-clear": _cure_challan_stamp_clear, "to-verified": _cure_to_verified,
    "add-challan": _cure_add_challan, "proforma": _cure_proforma,
}
