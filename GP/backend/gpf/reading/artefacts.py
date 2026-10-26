"""Artefact taxonomy (spec §4.1).

Documents are classified by LAYOUT and CONTENT, never by file name. Several
forms share numbers with unrelated compendium forms; the naming traps below
must be respected or the module raises the wrong observation (the first
prototype did exactly this on the dismissal case).
"""
from __future__ import annotations

from enum import Enum


class Artefact(str, Enum):
    COVERING_LETTER = "COVERING_LETTER"            # forwarding notice (recorded, never examined: R3)
    GPF_FORM_10 = "GPF_FORM_10"                    # application for final payment (Revised G.P.F.-10)
    FORM_PAY_05 = "FORM_PAY_05"                    # Temporary Loans/Advances ("Form 5")
    FORM_PAY_06 = "FORM_PAY_06"                    # Permanent Loans/Advances ("Change Form-06", "Form 6-B")
    SANCTION_ORDER = "SANCTION_ORDER"
    SANCTION_ORDER_QR = "SANCTION_ORDER_QR"        # QR-coded sanction (Health, Education, Police)
    RETIREMENT_NOTIF = "RETIREMENT_NOTIF"
    PUNISHMENT_ORDER = "PUNISHMENT_ORDER"          # dismissal/removal order; may carry a QR
    OBITUARY_NOTIF = "OBITUARY_NOTIF"
    NADRA_DEATH_CERT = "NADRA_DEATH_CERT"
    NADRA_FRC = "NADRA_FRC"                        # family registration certificate (QR to e-FRC)
    NADRA_DECLINE_CERT = "NADRA_DECLINE_CERT"      # succession decline (QR, Code 39)
    SUCCESSION_PETITION = "SUCCESSION_PETITION"    # court application (not a grant)
    SUCCESSION_CERT = "SUCCESSION_CERT"            # granted by a court
    AFFIDAVIT_WIDOW = "AFFIDAVIT_WIDOW"
    UNDERTAKING_STAMP_PAPER = "UNDERTAKING_STAMP_PAPER"   # NOT an affidavit for lawful widow
    E_STAMP_AFFIDAVIT = "E_STAMP_AFFIDAVIT"        # Punjab e-stamp (QR to e-Stamp portal)
    CNIC_SMART_FRONT = "CNIC_SMART_FRONT"          # chip, holder signature, no fingerprint
    CNIC_SMART_BACK = "CNIC_SMART_BACK"            # QR (card number + CNIC)
    CNIC_OLD_FRONT = "CNIC_OLD_FRONT"
    CNIC_OLD_BACK = "CNIC_OLD_BACK"                # may carry a printed thumbprint + PDF417
    SERVICE_BOOK_PAGE = "SERVICE_BOOK_PAGE"
    FP_PROFORMA = "FP_PROFORMA"                    # "Proforma for GP Fund final payment"
    SAP_PAYSLIP = "SAP_PAYSLIP"
    SAP_GPF_RECALC_REPORT = "SAP_GPF_RECALC_REPORT"
    BALANCE_TRANSFER_PROF = "BALANCE_TRANSFER_PROF"
    CHALLAN_32A = "CHALLAN_32A"                    # Treasury Challan Form 32-A (bank stamp + Treasury mark)
    MANUAL_DEDUCTION_CERT = "MANUAL_DEDUCTION_CERT"
    ACQUAINTANCE_ROLL = "ACQUAINTANCE_ROLL"
    SECTION_WORKING = "SECTION_WORKING"            # AG office's own hand on a department form (NOT a dept entry)
    UNKNOWN = "UNKNOWN"                            # escalate to a person


#: Human-readable classification hints handed to the vision model (stage 3).
CLASSIFY_HINTS = {
    Artefact.SECTION_WORKING: "Handwriting in the AG office's own hand on a department form "
                              "(pre-audit computations, tokens, dates) is SECTION_WORKING, never a department entry.",
    Artefact.GPF_FORM_10: "Compendium Form P.F.10 (house-purchase agreement, Rule 1.15(b)) is NOT the final-payment Form 10.",
    Artefact.FORM_PAY_06: "Compendium Form P.F.6 (insurance assignment) is NOT FORM PAY 06.",
    Artefact.UNDERTAKING_STAMP_PAPER: "An undertaking on stamp paper is NOT an affidavit for lawful widow.",
    Artefact.SUCCESSION_PETITION: "A court application for a succession certificate is NOT a granted certificate.",
    # 26 Oct 2026, PC-2026-000073: page 1 was the proforma and no class described it, so the
    # classifier had nothing to call it and the claim reported no service book at all. The two
    # are easy to confuse and the department sends the proforma INSTEAD of the book, so the
    # legend separates them by what is actually on the page.
    Artefact.FP_PROFORMA: "A typed office form headed PROFORMA FOR GP FUND FINAL PAYMENT, filled in by hand and "
                          "signed by the Drawing and Disbursing Officer: PARTICULARS OF EMPLOYEE (name, CNIC, "
                          "designation, personnel number, dates of birth / appointment / retirement, type of "
                          "retirement) and SERVICE RECORD SUMMARY (suspension, EOL, study leave, deputation, "
                          "penalties), mostly NIL. It is NOT a page of a Service Book, which is a bound register "
                          "in columns with service entries signed over many years, and NOT the GPF Form 10.",
}

#: One-line description of each type, given to the classifier as a legend.
ARTEFACT_LEGEND = {
    Artefact.COVERING_LETTER: "a forwarding/covering letter from the department head",
    Artefact.GPF_FORM_10: "the printed 'G.P.F. 10' / 'Revised GPF-10' final-payment application form",
    Artefact.FORM_PAY_05: "the 'FORM PAY 05' / 'Change Form-05' temporary loans & advances form",
    Artefact.FORM_PAY_06: "the 'FORM PAY 06' / 'Change Form-06' / 'Form 6-B' permanent loans & advances form",
    Artefact.FP_PROFORMA: "the office's PROFORMA FOR GP FUND FINAL PAYMENT -- particulars of the employee and a "
                          "service record summary, signed by the DDO; sent in place of the original Service Book",
    Artefact.SANCTION_ORDER: "an official sanction ORDER of an advance (letterhead, order/memo no., 'sanctioned', amount, rule), even if it carries office diary stamps",
    Artefact.SANCTION_ORDER_QR: "a sanction order that prints a QR code (Health/Education/Police)",
    Artefact.RETIREMENT_NOTIF: "a retirement/superannuation notification or office order",
    Artefact.PUNISHMENT_ORDER: "a dismissal/removal/punishment order",
    Artefact.OBITUARY_NOTIF: "a death/obituary office order",
    Artefact.NADRA_DEATH_CERT: "a NADRA death registration certificate",
    Artefact.NADRA_FRC: "a NADRA family registration certificate (FRC)",
    Artefact.NADRA_DECLINE_CERT: "a NADRA succession-decline certificate",
    Artefact.SUCCESSION_PETITION: "a court application for a succession certificate (not a grant)",
    Artefact.SUCCESSION_CERT: "a succession certificate granted by a court",
    Artefact.AFFIDAVIT_WIDOW: "an affidavit for lawful widow",
    Artefact.UNDERTAKING_STAMP_PAPER: "a general undertaking on stamp paper (NOT an affidavit for lawful widow)",
    Artefact.E_STAMP_AFFIDAVIT: "a Punjab e-stamp paper / affidavit with an e-stamp QR",
    Artefact.CNIC_SMART_FRONT: "the FRONT of a smart CNIC card (photo, name, number, chip)",
    Artefact.CNIC_SMART_BACK: "the BACK of a smart CNIC card (QR code, card number)",
    Artefact.CNIC_OLD_FRONT: "the FRONT of an older non-chip CNIC card",
    Artefact.CNIC_OLD_BACK: "the BACK of an older CNIC (may show a thumbprint and a PDF417 barcode)",
    Artefact.SERVICE_BOOK_PAGE: "a Service Book page (cover, particulars, or entries)",
    Artefact.SAP_PAYSLIP: "an SAP pay slip / payroll register print (GPF balance, subscription, loan)",
    Artefact.SAP_GPF_RECALC_REPORT: "an SAP 'GPF Final Re-calculation Report' with yearly ledger rows",
    Artefact.BALANCE_TRANSFER_PROF: "a proforma for transfer of GP Fund balances",
    Artefact.CHALLAN_32A: "a Treasury Challan Form 32-A (bank stamp, Treasury verification)",
    Artefact.MANUAL_DEDUCTION_CERT: "a manual deduction certificate (by DDO or AG office)",
    Artefact.ACQUAINTANCE_ROLL: "an acquaintance roll or manual bill",
    Artefact.SECTION_WORKING: "a page that is WHOLLY the AG office's own pre-audit computation/working (not a department form that merely carries office annotations)",
    Artefact.UNKNOWN: "none of the above / cannot tell — escalate to a person",
}


#: Codes carried by each artefact type (informs stage 5 expectations).
CARRIES_QR = {
    Artefact.SANCTION_ORDER_QR, Artefact.E_STAMP_AFFIDAVIT, Artefact.NADRA_FRC,
    Artefact.NADRA_DEATH_CERT, Artefact.NADRA_DECLINE_CERT, Artefact.CNIC_SMART_BACK,
}

ALL_TYPES = [a.value for a in Artefact]
