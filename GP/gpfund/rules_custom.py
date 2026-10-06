"""Case-specific checks. Build specification §5, last paragraph.

    Case-specific checks (anomalies that only one case shows, such as a double posting in
    SAP) use the same contract and are attached by the reading stage.

They are not a back door. Each has an id, a ref and a code like any other check, and each is
registered here rather than composed at run time -- so §14 rule 2 holds: nothing is raised
outside the circular, the Rules or the office clarifications without a recorded justification,
and a check whose ``code`` is ``OFF_LIST`` carries that justification in its ``ref`` and in
its finding.

Most of them are §12 reconciliation findings on one particular ledger, and every one of them
is a VERIFICATION TASK rather than a department defect, because §12 is explicit: "An anomaly
that the section must resolve in SAP is a verification task, not a department defect, and it
blocks payment."
"""

from __future__ import annotations

from typing import Any

from .contracts import CONF, HARD, OK, SAP, Facts
from .engine import custom_check, ev, fmt, num, verified, verified_result


def _pending(facts: Facts, vid: str, ok_text: str, bad_text: str) -> dict[str, Any] | None:
    """The recorded verification, if the officer has already made this decision."""
    record = verified(facts, vid)
    return verified_result(record, ok_text, bad_text) if record else None


# -- refundable advance ---------------------------------------------------------------------

custom_check(
    id="REF-PAYROLL-UNIT", group="identity", ref="R4 · B1-ii (outside the list, justified)",
    code="OFF_LIST", title="Sanctioning office and SAP payroll unit",
    applies=lambda facts: bool(facts.sap_payslip),
    run=lambda facts: _pending(
        facts, "REF-PAYROLL-UNIT",
        "Subscriber’s unit at the sanction date confirmed, and DIG Operations Lahore was competent.",
        "The sanctioning office was not the competent authority for the unit on whose payroll "
        "the subscriber is borne.") or {
        "status": CONF,
        "finding": ("The sanction and Form 05 place the subscriber under the DIG Operations Lahore "
                    "(DDO LO5313, Constable No. 7156). The SAP pay slip for August 2026 places him "
                    "under LO0056 DIG Special Protection Unit (Buckle 6033/SC). Identity is not in "
                    "doubt; the competence of the sanctioning authority depends on which "
                    "establishment he is borne on."),
        "remedy": ("Confirm the subscriber’s unit and DDO at the sanction date. Justification "
                   "for raising: B1-ii requires sanction by the authority competent under "
                   "delegation."),
        "evidence": [ev(5, "SAP pay slip header", "refundable_p005_payslip_left_header_ddo.png"),
                     ev(4, "Form 05 DDO code", "refundable_p004_form05_ddo_personal_no_name.png")],
        "cure": {"kind": "verify", "vid": "REF-PAYROLL-UNIT"}},
)


# -- non-refundable advance -----------------------------------------------------------------

custom_check(
    id="NR-OFFICE-ANNOT", group="balance", ref="Section working", code="OFF_LIST",
    title="Office annotation of Rs 12,274 on Form 06",
    applies=lambda facts: True,
    run=lambda facts: _pending(
        facts, "NR-OFFICE-ANNOT",
        "Basis of the Rs 12,274 deduction confirmed in the section’s records.",
        "Basis of the Rs 12,274 deduction not confirmed.") or {
        "status": CONF,
        # §4.1 naming traps and §16.3: handwriting in the AG office's own hand on a department
        # form is SECTION_WORKING and must never be read as a department entry. Revision 1
        # read this as the department striking Rs 12,274 off its own sanction.
        "finding": ("The accounts office wrote \"490955/- 12274/-\" and \"Rs=478681/-\" on Form 06. "
                    "Rs 12,274 is 2.5% of Rs 490,955 and the \"Other\" box reads 2½, so this "
                    "looks like the office’s own 2.5% deduction (probably Zakat). The SAP report "
                    "posts the full Rs 490,955 with no adjustment. Not a department defect."),
        "remedy": "Section to confirm the basis of the deduction.",
        "evidence": [ev(4, "Office annotation", "non-refundable_p004_office_annotations_12274.png")],
        "cure": {"kind": "verify", "vid": "NR-OFFICE-ANNOT"}},
)


# -- final payment, non-gazetted ------------------------------------------------------------

custom_check(
    id="NG-ADJUST", group="balance", ref="B2-vi", code="B2-vi",
    title="Adjustments and possible missing credits in the re-calculation report",
    applies=lambda facts: bool(facts.sap_recalc),
    run=lambda facts: _pending(
        facts, "NG-ADJUST", "Adjustments explained; no missing credits.",
        "Missing credits confirmed; to be processed with missing-credit documents first.") or {
        "status": CONF,
        "finding": ("(a) Adjustment of Rs 670 in 2004-05. (b) Adjustment of Rs 1,420 less in "
                    "2025-26, one month’s subscription. (c) Temporary advances of Rs 49,600 "
                    "against recoveries of Rs 49,100: Rs 500 not credited back. (d) 1998-99 "
                    "subscription Rs 550 against Rs 600 in the years either side. Every row is "
                    "arithmetically consistent."),
        "remedy": ("Confirm whether these are genuine adjustments or missing credits. If missing "
                   "credits, they are processed first with a DDO certificate or bank-stamped, "
                   "Treasury-verified challans (R14)."),
        "cure": {"kind": "verify", "vid": "NG-ADJUST"}},
)

custom_check(
    id="NG-PERIOD", group="checklist", ref="B2-ii", code="B2-ii",
    title="Subscription period against service",
    applies=lambda facts: bool(facts.sap_recalc),
    run=lambda facts: _pending(
        facts, "NG-PERIOD", "Subscription period reconciled with the date of appointment.",
        "Subscription period does not reconcile with service.") or {
        "status": CONF,
        "finding": ("SAP credits subscriptions from 1988-89 (Rs 75, about three months) to June "
                    "2026. The pay slip prints 38 years 10 months of service, which points to "
                    "appointment around August 1987. The Service Book pages supplied do not show "
                    "the date of first appointment."),
        "remedy": ("Reconcile the start of subscription with the date of appointment in the "
                   "Service Book."),
        "cure": {"kind": "verify", "vid": "NG-PERIOD"}},
)

custom_check(
    id="NG-SCALE", group="identity", ref="Outside the list", code="OFF_LIST",
    title="Scale on the retirement order",
    applies=lambda facts: True,
    # Recorded, not raised. The scale does not affect a GP Fund final payment, which is
    # computed from SAP balances, and it is not on the circular's list -- so raising it would
    # breach §14 rule 2. It is reported as satisfied so the office record shows it was looked at.
    run=lambda facts: {
        "status": OK,
        "finding": ("Noted only: the retirement order describes the subscriber as Driver (BS-05); "
                    "Form 06 and the SAP pay slip give 06. It does not affect a GP Fund final "
                    "payment, which is computed from SAP balances, and it is not on the "
                    "circular’s list, so it is not raised."),
        "evidence": [ev(2, "Office order"), ev(8, "SAP pay slip")]},
)


# -- final payment, death -------------------------------------------------------------------

custom_check(
    id="DEATH-PERSNO", group="identity", ref="R6 · identity", code="R6",
    title="Personnel number on Form 06",
    applies=lambda facts: True,
    run=lambda facts: _pending(
        facts, "DEATH-PERSNO",
        "Personnel number on the original Form 06 confirmed as 90000417.",
        "Form 06 carries the wrong personnel number (30890417); a corrected Form 06 is needed "
        "before posting.") or {
        "status": CONF,
        # One digit, and the consequence is the whole finding: posting against 30890417 would
        # reach a different account. Not a hard stop, because the name, grade and DDO code all
        # match and the form plainly concerns the right person -- the original is checked first.
        "finding": ("Form 06 reads 30890417: the third box holds a closed double-loop 8, unlike "
                    "the 9 beside it. SAP, the GPF-10 and the re-calculation report all give "
                    "90000417, and the name, grade and DDO code match, so the form concerns the "
                    "right person but carries a number one digit off. Posting against 30890417 "
                    "would reach the wrong account."),
        "remedy": ("Check the original. If it reads 30890417, the department sends a corrected "
                   "Form 06 (upload it here)."),
        "evidence": [ev(12, "Personnel number boxes", "fp-death_p012_personal_number_boxes.png")],
        "cure": {"kind": "verify", "vid": "DEATH-PERSNO"}},
)


custom_check(
    id="DEATH-CLAIM", group="balance", ref="R11", code="R11",
    title="Claim against the SAP re-calculation report",
    applies=lambda facts: True,
    run=lambda facts: _death_claim(facts),
)


def _death_claim(facts: Facts) -> dict[str, Any]:
    """Rs 92,482 = closing at 30-06-2025 plus five months' subscription. §12, §16.3.

    Revision 1 said the figure was "not derivable" and that the unrecovered advance had never
    been set off. The SAP report now in the case supplies the basis and already nets the
    Rs 60,000, which is why the claim reconciles exactly. Computed rather than asserted, so
    the arithmetic is on the record.
    """
    rows = facts.recalc_rows
    payslip = facts.sap_payslip
    claim = facts.claim or {}
    if not rows:
        return {"status": SAP,
                "finding": ("The claim of Rs 92,482 cannot be tested without the GPF Final "
                            "Re-calculation Report."),
                "remedy": "Pull the report for personnel no. 90000417.",
                "cure": {"kind": "sap"}}
    base = next((r for r in rows if "30.06.2025" in str(r.get("end"))), None)
    subscription = num((payslip or {}).get("gpfSubscription")) or 1060
    if not base:
        return {"status": CONF,
                "finding": "The report has no row closing on 30-06-2025 to test the claim against.",
                "cure": {"kind": "verify", "vid": "DEATH-CLAIM"}}
    expected = (num(base.get("closing")) or 0) + 5 * subscription
    amount = num(claim.get("amount"))
    if expected == amount:
        return {"status": OK,
                "finding": (f"Rs {fmt(amount)} claimed = SAP closing balance at 30-06-2025 of "
                            f"Rs {fmt(base.get('closing'))} + five months at Rs "
                            f"{fmt(subscription)}. The unrecovered Rs 60,000 of the 2023-24 "
                            f"advance is already netted in the SAP balance."),
                "evidence": [ev(13, "Re-calculation report", "fp-death_p013_recalc_table.png")]}
    return {"status": HARD, "code": "B2-vi",
            "finding": (f"Rs {fmt(amount)} claimed, but the SAP closing balance at 30-06-2025 plus "
                        f"five months gives Rs {fmt(expected)}."),
            "remedy": "Department to correct the claim to the SAP figure.",
            "evidence": [ev(13, "Re-calculation report")]}


custom_check(
    id="DEATH-POSTDEATH", group="balance", ref="B2-vi · R14", code="B2-vi",
    title="Subscriptions after the death",
    applies=lambda facts: bool(facts.sap_recalc),
    run=lambda facts: _pending(
        facts, "DEATH-POSTDEATH",
        "Post-death subscriptions and interest checked against the SAP pay history.",
        "Post-death credits are not reconciled; to be corrected before payment.") or {
        "status": CONF,
        "finding": ("SAP credits no subscription in 2024-25 and six months (Rs 6,360) in 2025-26, "
                    "after the death on 03-04-2024, and the forms note \"1060/- 03/26\". This fits "
                    "pay drawn against the OSD post. The Rules say nothing on subscriptions after "
                    "death, and interest may be capped under Rule 1.13(4) once the balance became "
                    "payable."),
        "remedy": ("Check the SAP pay history for the OSD post and confirm which post-death "
                   "credits and interest are admissible (open item GPF-O17)."),
        "evidence": [ev(13, "Re-calculation report", "fp-death_p013_recalc_last_rows.png")],
        "cure": {"kind": "verify", "vid": "DEATH-POSTDEATH"}},
)

custom_check(
    id="DEATH-PERIOD", group="checklist", ref="B2-ii", code="B2-ii",
    title="Subscription period against service",
    applies=lambda facts: bool(facts.sap_recalc),
    run=lambda facts: _pending(
        facts, "DEATH-PERIOD", "Subscription period reconciled with service.",
        "Subscription period does not reconcile with service.") or {
        "status": CONF,
        "finding": ("Service began on 02-11-2008, but SAP subscriptions start in 2009-10 with only "
                    "Rs 650. That may be the first-year exemption, low early rates or missing "
                    "credits. The Service Book is not on file to check."),
        "remedy": "Compare with the Service Book once it is produced.",
        "cure": {"kind": "verify", "vid": "DEATH-PERIOD"}},
)


# -- final payment, dismissal ---------------------------------------------------------------

custom_check(
    id="DIS-APPEAL", group="checklist", ref="Rule 1.13(6) Explanation 1", code="OFF_LIST",
    title="No appeal pending against the dismissal",
    applies=lambda facts: True,
    run=lambda facts: _pending(
        facts, "DIS-APPEAL", "No appeal or review pending against the dismissal.",
        "An appeal or review is pending; the balance is held until final orders.") or {
        "status": CONF,
        # The one substantive question a dismissal raises that a retirement does not. Open
        # item GPF-O5 asks the office how pending appeals should be treated.
        "finding": ("Under Rule 1.13(6) Explanation 1, a dismissed subscriber who has appealed is "
                    "not paid until final orders. The affidavit of 22-04-2026 says he does not wish "
                    "to rejoin and has deposited his other dues, but does not say expressly that no "
                    "appeal is pending."),
        "remedy": ("Decide whether the affidavit is enough, or obtain a department certificate that "
                   "no appeal or review is pending."),
        "cure": {"kind": "verify", "vid": "DIS-APPEAL"}},
)

custom_check(
    id="DIS-CREDITS", group="balance", ref="B2-vi · B2-ii", code="B2-vi",
    title="Possible missing credits in 2013-14",
    applies=lambda facts: bool(facts.sap_recalc),
    run=lambda facts: _pending(
        facts, "DIS-CREDITS",
        "The 2013-14 shortfall is explained (leave without pay, suspension or absence).",
        "Missing credits confirmed; to be processed first.") or {
        "status": CONF,
        "finding": ("The 2013-14 subscription is Rs 6,860, about five months at Rs 1,372, against "
                    "Rs 16,464 (twelve months) in the years either side: about seven months "
                    "(Rs 9,604) not credited, unless he was on leave without pay or suspended. "
                    "2016-17 does not split into whole months, and 2023-24 carries an unexplained "
                    "adjustment of Rs 6,052."),
        "remedy": ("Check the Service Book for leave without pay or suspension in 2013-14. If "
                   "deductions were made but not credited, treat as a missing-credit claim (R14)."),
        "evidence": [ev(9, "Re-calculation report")],
        "cure": {"kind": "verify", "vid": "DIS-CREDITS"}},
)

custom_check(
    id="DIS-INTEREST", group="balance", ref="R11 · Rule 1.13(4)", code="R11",
    title="Interest in the section’s working against SAP",
    applies=lambda facts: bool(facts.sap_recalc),
    run=lambda facts: _pending(
        facts, "DIS-INTEREST", "Interest reconciled and one clean computation recorded.",
        "Interest not reconciled.") or {
        "status": CONF,
        "finding": ("The section’s working on Form 06 adds interest of Rs 16,900; SAP credits "
                    "Rs 17,968 for 2023-24, a difference of Rs 1,068. The 2024-25 row shows "
                    "interest of Rs 2,239 not carried to the closing balance. Under Rule 1.13(4) "
                    "interest stops six months after the balance became payable when the claim is "
                    "late. This is the section’s own working, not a department defect."),
        "remedy": ("Reconcile interest, explain the Rs 6,052 adjustment and record one clean, "
                   "initialled computation."),
        "evidence": [ev(1, "Section working", "fp-dismissal_p001_office_computation_sheet.png")],
        "cure": {"kind": "verify", "vid": "DIS-INTEREST"}},
)


# -- missing credits ------------------------------------------------------------------------

custom_check(
    id="MC-NAME", group="identity", ref="R1", title="Name spelling against SAP",
    applies=lambda facts: True,
    run=lambda facts: _mc_name(facts),
)


def _mc_name(facts: Facts) -> dict[str, Any]:
    """Two spellings, one personnel number. Matched against the SAP master name.

    The schedule spells "Numan Mushtaq, AP" and all six challans "Nauman Mushtaq, AP-II". The
    personnel number is the same throughout, so this is a spelling question SAP settles, not
    a defect for the department to cure.
    """
    payslip = facts.sap_payslip
    if not payslip or not payslip.get("name"):
        return {"status": SAP,
                "finding": ("The schedule spells the name \"Dr. Numan Mushtaq, AP\"; all six "
                            "challans spell it \"Dr. Nauman Mushtaq, AP-II\". The personnel number "
                            "is the same throughout. Match against the SAP master name."),
                "cure": {"kind": "sap"}}
    import re
    if re.search(r"n(a|ou)?u?man\s*mushtaq", str(payslip.get("name")), re.I):
        return {"status": OK,
                "finding": (f"SAP names personnel no. {payslip.get('persNo')} as "
                            f"{payslip.get('name')}. Both spellings refer to this subscriber.")}
    return {"status": HARD,
            "finding": (f"SAP names personnel no. {payslip.get('persNo')} as "
                        f"{payslip.get('name')}, not Nauman Mushtaq."),
            "remedy": "Department to confirm the identity of the subscriber."}


# -- residual payment -----------------------------------------------------------------------

custom_check(
    id="RES-RECON", group="balance", ref="B2-vi · R11", code="B2-vi",
    title="Residual reconciles with the SAP re-calculation report",
    applies=lambda facts: True,
    run=lambda facts: _res_recon(facts),
)


def _res_recon(facts: Facts) -> dict[str, Any]:
    """The double posting. §12, and the arithmetic that makes it visible.

    Rs 712,068 = 2 x 340,330 + 31,408. Stating that identity is what turns "the report looks
    wrong" into "this fits a double posting of the final payment", which is a thing the
    section can go and check in the ledger. And §12's last rule governs the outcome: never
    let a case pass for payment on a report that does not reconcile.
    """
    rows = facts.recalc_rows
    if not rows:
        return {"status": SAP,
                "finding": ("Rs 31,408 residual claimed. The SAP re-calculation report is needed "
                            "to reconcile it."),
                "cure": {"kind": "sap"}}
    last = rows[-1]
    closing = num(last.get("closing")) or 0
    recorded = _pending(facts, "RES-RECON", "Residual reconciled in SAP.",
                        "Residual could not be reconciled in SAP.")
    if recorded:
        return recorded
    # A corrected report the section uploads is allowed to settle it, which is the cure loop
    # working: the facts changed, and the same rule now closes what it raised.
    if facts.sap_source == "upload" and closing > 0:
        if abs(closing - 31408) <= 1:
            return {"status": OK,
                    "finding": (f"The uploaded report closes at Rs {fmt(closing)} in credit, equal "
                                f"to the residual claimed.")}
        return {"status": HARD,
                "finding": (f"The uploaded report closes at Rs {fmt(closing)}; Rs 31,408 is "
                            f"claimed."),
                "remedy": "Reconcile the claim with SAP."}
    return {"status": CONF,
            "calc": {"claim": 31408, "expected": closing,
                     "basis": f"closing balance for {last.get('start')} to {last.get('end')}"},
            "finding": ("The report does not show the residual at credit. Rs 31,408 appears as the "
                        "2024-25 adjustment, but the 2024-25 closing is printed Rs 340,330 debit. "
                        "Every earlier row follows opening + subscription + adjustment - advances "
                        "+ recoveries + interest; this row only does if the interest of Rs 20,807 "
                        "is left out. The permanent advance of Rs 712,068 equals exactly "
                        "2 x 340,330 + 31,408, which fits a double posting of the final payment. "
                        "Paying on this report risks paying against a debit, or paying twice."),
            "remedy": ("Before payment, the section pulls the SAP ledger postings for 2024-25, "
                       "corrects any double posting, and uploads the corrected report on the SAP "
                       "extracts step."),
            "evidence": [ev(6, "Report, last rows", "residual_p006_recalc_last_rows.png")],
            "cure": {"kind": "verify", "vid": "RES-RECON"}}
