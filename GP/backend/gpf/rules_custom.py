"""Case-specific checks (CUSTOM_CHECKS).

Anomalies that only one case shows (a double posting in SAP, an office
annotation, a personnel number one digit off) use the same check contract and
are attached to a case by its facts (`F["custom"]`). Faithful port of the
CUSTOM_CHECKS blocks in the facts_case_*.js fixtures.
"""
from __future__ import annotations

import re

from .format import KIND, ev, fmt
from .registry import check, verified, verified_result


# ── Refundable: sanctioning office vs SAP payroll unit ────────────────────────
def _ref_payroll_unit(F):
    v = verified(F, "REF-PAYROLL-UNIT")
    if v:
        return verified_result(
            v, "Subscriber's unit at the sanction date confirmed, and DIG Operations Lahore was competent.",
            "The sanctioning office was not the competent authority for the unit on whose payroll the subscriber is borne.")
    return {"status": "conf",
            "finding": ("The sanction and Form 05 place the subscriber under the DIG Operations Lahore (DDO LO5313, "
                        "Constable No. 7156). The SAP pay slip for August 2026 places him under LO0056 DIG Special "
                        "Protection Unit (Buckle 6033/SC). Identity is not in doubt; the competence of the sanctioning "
                        "authority depends on which establishment he is borne on."),
            "remedy": ("Confirm the subscriber's unit and DDO at the sanction date. Justification for raising: B1-ii "
                       "requires sanction by the authority competent under delegation."),
            "evidence": [ev(5, "SAP pay slip header", "refundable_p005_payslip_left_header_ddo.png"),
                         ev(4, "Form 05 DDO code", "refundable_p004_form05_ddo_personal_no_name.png")],
            "cure": {"kind": "verify", "vid": "REF-PAYROLL-UNIT"}}


check(custom_id="REF-PAYROLL-UNIT", id="REF-PAYROLL-UNIT", group="identity",
      ref="R4 · B1-ii (outside the list, justified)", code="OFF_LIST",
      title="Sanctioning office and SAP payroll unit",
      applies=lambda F: bool(F.get("sap") and F["sap"].get("payslip")), run=_ref_payroll_unit)


# ── Non-refundable: office annotation of Rs 12,274 on Form 06 ─────────────────
def _nr_office_annot(F):
    v = verified(F, "NR-OFFICE-ANNOT")
    if v:
        return verified_result(v, "Basis of the Rs 12,274 deduction confirmed in the section's records.",
                               "Basis of the Rs 12,274 deduction not confirmed.")
    return {"status": "conf",
            "finding": ("The accounts office wrote \"490955/- 12274/-\" and \"Rs=478681/-\" on Form 06. Rs 12,274 is 2.5% "
                        "of Rs 490,955 and the \"Other\" box reads 2 1/2, so this looks like the office's own 2.5% deduction "
                        "(probably Zakat). The SAP report posts the full Rs 490,955 with no adjustment. Not a department defect."),
            "remedy": "Section to confirm the basis of the deduction.",
            "evidence": [ev(4, "Office annotation", "non-refundable_p004_office_annotations_12274.png")],
            "cure": {"kind": "verify", "vid": "NR-OFFICE-ANNOT"}}


check(custom_id="NR-OFFICE-ANNOT", id="NR-OFFICE-ANNOT", group="balance", ref="Section working", code="OFF_LIST",
      title="Office annotation of Rs 12,274 on Form 06", applies=lambda F: True, run=_nr_office_annot)


# ── Non-gazetted final payment: adjustments, period, scale ────────────────────
def _ng_adjust(F):
    v = verified(F, "NG-ADJUST")
    if v:
        return verified_result(v, "Adjustments explained; no missing credits.",
                               "Missing credits confirmed; to be processed with missing-credit documents first.")
    return {"status": "conf",
            "finding": ("(a) Adjustment of Rs 670 in 2004-05. (b) Adjustment of Rs 1,420 less in 2025-26, one month's "
                        "subscription. (c) Temporary advances of Rs 49,600 against recoveries of Rs 49,100: Rs 500 not "
                        "credited back. (d) 1998-99 subscription Rs 550 against Rs 600 in the years either side. Every row "
                        "is arithmetically consistent."),
            "remedy": ("Confirm whether these are genuine adjustments or missing credits. If missing credits, they are "
                       "processed first with a DDO certificate or bank-stamped, Treasury-verified challans (R14)."),
            "cure": {"kind": "verify", "vid": "NG-ADJUST"}}


check(custom_id="NG-ADJUST", id="NG-ADJUST", group="balance", ref="B2-vi", code="B2-vi",
      title="Adjustments and possible missing credits in the re-calculation report",
      applies=lambda F: bool(F.get("sap") and F["sap"].get("recalc")), run=_ng_adjust)


def _ng_period(F):
    v = verified(F, "NG-PERIOD")
    if v:
        return verified_result(v, "Subscription period reconciled with the date of appointment.",
                               "Subscription period does not reconcile with service.")
    return {"status": "conf",
            "finding": ("SAP credits subscriptions from 1988-89 (Rs 75, about three months) to June 2026. The pay slip "
                        "prints 38 years 10 months of service, which points to appointment around August 1987. The Service "
                        "Book pages supplied do not show the date of first appointment."),
            "remedy": "Reconcile the start of subscription with the date of appointment in the Service Book.",
            "cure": {"kind": "verify", "vid": "NG-PERIOD"}}


check(custom_id="NG-PERIOD", id="NG-PERIOD", group="checklist", ref="B2-ii", code="B2-ii",
      title="Subscription period against service",
      applies=lambda F: bool(F.get("sap") and F["sap"].get("recalc")), run=_ng_period)


def _ng_scale(F):
    return {"status": "ok",
            "finding": ("Noted only: the retirement order describes the subscriber as Driver (BS-05); Form 06 and the SAP "
                        "pay slip give 06. It does not affect a GP Fund final payment, which is computed from SAP balances, "
                        "and it is not on the circular's list, so it is not raised."),
            "evidence": [ev(2, "Office order"), ev(8, "SAP pay slip")]}


check(custom_id="NG-SCALE", id="NG-SCALE", group="identity", ref="Outside the list", code="OFF_LIST",
      title="Scale on the retirement order", applies=lambda F: True, run=_ng_scale)


# ── Death case: personnel number, claim, post-death credits, period ───────────
def _death_persno(F):
    v = verified(F, "DEATH-PERSNO")
    if v:
        return verified_result(v, "Personnel number on the original Form 06 confirmed as 90000417.",
                               "Form 06 carries the wrong personnel number (30890417); a corrected Form 06 is needed before posting.")
    return {"status": "conf",
            "finding": ("Form 06 reads 30890417: the third box holds a closed double-loop 8, unlike the 9 beside it. SAP, "
                        "the GPF-10 and the re-calculation report all give 90000417, and the name, grade and DDO code match, "
                        "so the form concerns the right person but carries a number one digit off. Posting against 30890417 "
                        "would reach the wrong account."),
            "remedy": "Check the original. If it reads 30890417, the department sends a corrected Form 06 (upload it here).",
            "evidence": [ev(12, "Personnel number boxes", "fp-death_p012_personal_number_boxes.png")],
            "cure": {"kind": "verify", "vid": "DEATH-PERSNO"}}


check(custom_id="DEATH-PERSNO", id="DEATH-PERSNO", group="identity", ref="R6 · identity", code="R6",
      title="Personnel number on Form 06", applies=lambda F: True, run=_death_persno)


def _death_claim(F):
    rows = F.get("sap") and F["sap"].get("recalc") and F["sap"]["recalc"].get("rows")
    p = F.get("sap") and F["sap"].get("payslip")
    if not rows:
        return {"status": "sap",
                "finding": "The claim of Rs 92,482 cannot be tested without the GPF Final Re-calculation Report.",
                "remedy": "Pull the report for personnel no. 90000417.", "cure": {"kind": "sap"}}
    base = next((r for r in rows if re.search(r"30\.06\.2025", r["end"])), None)
    sub = (p and p.get("gpfSubscription")) or 1060
    if not base:
        return {"status": "conf", "finding": "The report has no row closing on 30-06-2025 to test the claim against.",
                "cure": {"kind": "verify", "vid": "DEATH-CLAIM"}}
    expected = base["closing"] + 5 * sub
    if expected == F["claim"]["amount"]:
        return {"status": "ok",
                "finding": ("Rs " + fmt(F["claim"]["amount"]) + " claimed = SAP closing balance at 30-06-2025 of Rs "
                            + fmt(base["closing"]) + " + five months at Rs " + fmt(sub) + ". The unrecovered Rs 60,000 of "
                            "the 2023-24 advance is already netted in the SAP balance."),
                "evidence": [ev(13, "Re-calculation report", "fp-death_p013_recalc_table.png")]}
    return {"status": "hard", "code": "B2-vi",
            "finding": ("Rs " + fmt(F["claim"]["amount"]) + " claimed, but the SAP closing balance at 30-06-2025 plus five "
                        "months gives Rs " + fmt(expected) + "."),
            "remedy": "Department to correct the claim to the SAP figure.",
            "evidence": [ev(13, "Re-calculation report")]}


check(custom_id="DEATH-CLAIM", id="DEATH-CLAIM", group="balance", ref="R11", code="R11",
      title="Claim against the SAP re-calculation report", applies=lambda F: True, run=_death_claim)


def _death_postdeath(F):
    v = verified(F, "DEATH-POSTDEATH")
    if v:
        return verified_result(v, "Post-death subscriptions and interest checked against the SAP pay history.",
                               "Post-death credits are not reconciled; to be corrected before payment.")
    return {"status": "conf",
            "finding": ("SAP credits no subscription in 2024-25 and six months (Rs 6,360) in 2025-26, after the death on "
                        "03-04-2024, and the forms note \"1060/- 03/26\". This fits pay drawn against the OSD post. The Rules "
                        "say nothing on subscriptions after death, and interest may be capped under Rule 1.13(4) once the "
                        "balance became payable."),
            "remedy": ("Check the SAP pay history for the OSD post and confirm which post-death credits and interest are "
                       "admissible (open item GPF-O17)."),
            "evidence": [ev(13, "Re-calculation report", "fp-death_p013_recalc_last_rows.png")],
            "cure": {"kind": "verify", "vid": "DEATH-POSTDEATH"}}


check(custom_id="DEATH-POSTDEATH", id="DEATH-POSTDEATH", group="balance", ref="B2-vi · R14", code="B2-vi",
      title="Subscriptions after the death",
      applies=lambda F: bool(F.get("sap") and F["sap"].get("recalc")), run=_death_postdeath)


def _death_period(F):
    v = verified(F, "DEATH-PERIOD")
    if v:
        return verified_result(v, "Subscription period reconciled with service.",
                               "Subscription period does not reconcile with service.")
    return {"status": "conf",
            "finding": ("Service began on 02-11-2008, but SAP subscriptions start in 2009-10 with only Rs 650. That may be "
                        "the first-year exemption, low early rates or missing credits. The Service Book is not on file to check."),
            "remedy": "Compare with the Service Book once it is produced.",
            "cure": {"kind": "verify", "vid": "DEATH-PERIOD"}}


check(custom_id="DEATH-PERIOD", id="DEATH-PERIOD", group="checklist", ref="B2-ii", code="B2-ii",
      title="Subscription period against service",
      applies=lambda F: bool(F.get("sap") and F["sap"].get("recalc")), run=_death_period)


# ── Dismissal case: appeal, credits, interest ────────────────────────────────
def _dis_appeal(F):
    v = verified(F, "DIS-APPEAL")
    if v:
        return verified_result(v, "No appeal or review pending against the dismissal.",
                               "An appeal or review is pending; the balance is held until final orders.")
    return {"status": "conf",
            "finding": ("Under Rule 1.13(6) Explanation 1, a dismissed subscriber who has appealed is not paid until final "
                        "orders. The affidavit of 22-04-2026 says he does not wish to rejoin and has deposited his other dues, "
                        "but does not say expressly that no appeal is pending."),
            "remedy": ("Decide whether the affidavit is enough, or obtain a department certificate that no appeal or review "
                       "is pending."),
            "cure": {"kind": "verify", "vid": "DIS-APPEAL"}}


check(custom_id="DIS-APPEAL", id="DIS-APPEAL", group="checklist", ref="Rule 1.13(6) Explanation 1", code="OFF_LIST",
      title="No appeal pending against the dismissal", applies=lambda F: True, run=_dis_appeal)


def _dis_credits(F):
    v = verified(F, "DIS-CREDITS")
    if v:
        return verified_result(v, "The 2013-14 shortfall is explained (leave without pay, suspension or absence).",
                               "Missing credits confirmed; to be processed first.")
    return {"status": "conf",
            "finding": ("The 2013-14 subscription is Rs 6,860, about five months at Rs 1,372, against Rs 16,464 (twelve "
                        "months) in the years either side: about seven months (Rs 9,604) not credited, unless he was on leave "
                        "without pay or suspended. 2016-17 does not split into whole months, and 2023-24 carries an "
                        "unexplained adjustment of Rs 6,052."),
            "remedy": ("Check the Service Book for leave without pay or suspension in 2013-14. If deductions were made but "
                       "not credited, treat as a missing-credit claim (R14)."),
            "evidence": [ev(9, "Re-calculation report")],
            "cure": {"kind": "verify", "vid": "DIS-CREDITS"}}


check(custom_id="DIS-CREDITS", id="DIS-CREDITS", group="balance", ref="B2-vi · B2-ii", code="B2-vi",
      title="Possible missing credits in 2013-14",
      applies=lambda F: bool(F.get("sap") and F["sap"].get("recalc")), run=_dis_credits)


def _dis_interest(F):
    v = verified(F, "DIS-INTEREST")
    if v:
        return verified_result(v, "Interest reconciled and one clean computation recorded.", "Interest not reconciled.")
    return {"status": "conf",
            "finding": ("The section's working on Form 06 adds interest of Rs 16,900; SAP credits Rs 17,968 for 2023-24, a "
                        "difference of Rs 1,068. The 2024-25 row shows interest of Rs 2,239 not carried to the closing "
                        "balance. Under Rule 1.13(4) interest stops six months after the balance became payable when the "
                        "claim is late. This is the section's own working, not a department defect."),
            "remedy": "Reconcile interest, explain the Rs 6,052 adjustment and record one clean, initialled computation.",
            "evidence": [ev(1, "Section working", "fp-dismissal_p001_office_computation_sheet.png")],
            "cure": {"kind": "verify", "vid": "DIS-INTEREST"}}


check(custom_id="DIS-INTEREST", id="DIS-INTEREST", group="balance", ref="R11 · Rule 1.13(4)", code="R11",
      title="Interest in the section's working against SAP",
      applies=lambda F: bool(F.get("sap") and F["sap"].get("recalc")), run=_dis_interest)


# ── Missing credits: name spelling against SAP ───────────────────────────────
def _mc_name(F):
    p = F.get("sap") and F["sap"].get("payslip")
    if not p or not p.get("name"):
        return {"status": "sap",
                "finding": ("The schedule spells the name \"Dr. Numan Mushtaq, AP\"; all six challans spell it \"Dr. Nauman "
                            "Mushtaq, AP-II\". The personnel number is the same throughout. Match against the SAP master name."),
                "cure": {"kind": "sap"}}
    ok = bool(re.search(r"n(a|ou)?u?man\s*mushtaq", p["name"], re.I))
    if ok:
        return {"status": "ok",
                "finding": "SAP names personnel no. " + str(p["persNo"]) + " as " + p["name"] + ". Both spellings refer to this subscriber."}
    return {"status": "hard",
            "finding": "SAP names personnel no. " + str(p["persNo"]) + " as " + p["name"] + ", not Nauman Mushtaq.",
            "remedy": "Department to confirm the identity of the subscriber."}


check(custom_id="MC-NAME", id="MC-NAME", group="identity", ref="R1", title="Name spelling against SAP",
      applies=lambda F: True, run=_mc_name)


# ── Residual: reconcile with the SAP re-calculation report ───────────────────
def _res_recon(F):
    rc = F.get("sap") and F["sap"].get("recalc")
    if not (rc and rc.get("rows")):
        return {"status": "sap",
                "finding": "Rs 31,408 residual claimed. The SAP re-calculation report is needed to reconcile it.",
                "cure": {"kind": "sap"}}
    last = rc["rows"][-1]
    v = verified(F, "RES-RECON")
    if v:
        return verified_result(v, "Residual reconciled in SAP.", "Residual could not be reconciled in SAP.")
    if F["sap"].get("source") == "upload" and last["closing"] > 0:
        if abs(last["closing"] - 31408) <= 1:
            return {"status": "ok",
                    "finding": "The uploaded report closes at Rs " + fmt(last["closing"]) + " in credit, equal to the residual claimed."}
        return {"status": "hard",
                "finding": "The uploaded report closes at Rs " + fmt(last["closing"]) + "; Rs 31,408 is claimed.",
                "remedy": "Reconcile the claim with SAP."}
    return {"status": "conf",
            "calc": {"claim": 31408, "expected": last["closing"], "basis": "closing balance for " + last["start"] + " to " + last["end"]},
            "finding": ("The report does not show the residual at credit. Rs 31,408 appears as the 2024-25 adjustment, but "
                        "the 2024-25 closing is printed Rs 340,330 debit. Every earlier row follows opening + subscription + "
                        "adjustment - advances + recoveries + interest; this row only does if the interest of Rs 20,807 is "
                        "left out. The permanent advance of Rs 712,068 equals exactly 2 x 340,330 + 31,408, which fits a "
                        "double posting of the final payment. Paying on this report risks paying against a debit, or paying twice."),
            "remedy": ("Before payment, the section pulls the SAP ledger postings for 2024-25, corrects any double posting, "
                       "and uploads the corrected report on the SAP extracts step."),
            "evidence": [ev(6, "Report, last rows", "residual_p006_recalc_last_rows.png")],
            "cure": {"kind": "verify", "vid": "RES-RECON"}}


check(custom_id="RES-RECON", id="RES-RECON", group="balance", ref="B2-vi · R11", code="B2-vi",
      title="Residual reconciles with the SAP re-calculation report", applies=lambda F: True, run=_res_recon)
