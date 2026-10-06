"""Rules-in-force reference content for the 'Rules in force' screen (README, spec §5, §11, §18).

Static, versioned reference the UI shows the officer: the office clarifications
(R1-R15), the advance limits by clause with the office's 80% flagged, the
thumbprint finding, and the open items awaiting AG-office decisions.
"""
from __future__ import annotations

from .rules_family import ADV_LIMITS, PARAMS

RULESET_VERSION = {
    "circular": "Office Circular No. G.P. Fund-I (Coord)/TR/127 dated 21.12.2023",
    "rules": "Punjab General Provident Fund Rules 1978, Compendium 2008",
    "clarifications": "AG Punjab office clarifications R1-R15, effective 15-09-2026",
    "doaRegister": "versioned separately",
}

R_RULES = [
    ("R1", "SAP pay slip and re-calculation report: ticked if present; if not, the section pulls them from SAP by personnel number. Missing extracts are a section action, never a department defect."),
    ("R2", "Every issue must accept a document and be re-checked; the whole case is re-evaluated and versioned."),
    ("R3", "The covering letter is always correct and is never raised as an observation."),
    ("R4", "Delegation of authority for every department; every signature for or on behalf of an authority is looked up."),
    ("R5", "CNIC and pay slips need no attestation; unattested is an observation, not a defect."),
    ("R6", "Form 5 / Form 6-B: only the personal number tallies with the pay slip and signatures match the CNIC; the loan-details box is not examined."),
    ("R7", "Thumb impressions cannot be matched from the case papers; detected and routed to NADRA biometric verification."),
    ("R8", "Pay slip from SAP: manual upload now, SAP connector later; one data contract for both."),
    ("R9", "Office practice: a sanctioned advance at most 80% of the SAP balance. The module applies the limit the Rules set for the clause quoted and flags the 80% beside it."),
    ("R10", "Every QR code is decoded, compared with the document, and verified online where reachable; unreadable or unverifiable codes are observations."),
    ("R11", "Final payment needs the SAP re-calculation report with the pay slip; the claim is reconciled to the report."),
    ("R12", "One refundable advance at a time; a new one only after the month the earlier one reached zero."),
    ("R13", "An OSD post on the SAP pay slip removes the succession certificate (with the statutory guard of Rule 1.35 / PF Act s.4)."),
    ("R14", "Non-gazetted missing credits: bank-stamped, Treasury-verified challans replace the DDO certificate."),
    ("R15", "Gazetted missing credits: bank-stamped, Treasury-verified challans replace the AG certificate."),
]

THUMBPRINT_FINDING = {
    "conclusion": "Matching thumb impressions to the CNIC copy is not feasible from the case papers. Do not build it.",
    "why": [
        "Smart CNICs carry no fingerprint; NADRA holds the prints in its database and on the chip.",
        "The one printed print in the corpus is a degraded copy of a copy (21% usable ridge).",
        "Ink impressions are below forensic quality (~300-476 ppi; comparison needs ~500 ppi).",
        "An enhance-and-match pipeline could not separate same-person from different-person pairs.",
    ],
    "instead": "Detect and record every thumb impression; raise a verification task; cure by a NADRA biometric verification record or an attesting officer's certificate (open item GPF-O22).",
}

OPEN_ITEMS = [
    ("GPF-O14", "DOA register and specimen signatures for every department that signs GP Fund documents"),
    ("GPF-O15", "Advance limits: the notification (if any) that set 80% for temporary advances; whether 80% overrides Rule 1.16's 100% at age 50"),
    ("GPF-O16", "Second advance timing: R12 against the twelve-month gap in Rule 1.14(1)(c)(ii)"),
    ("GPF-O17", "OSD post: the instruction behind it and the SAP field that shows it; reconciling A.2(vi) with Rule 1.34 and the PF Act"),
    ("GPF-O18", "Confirm that 'Form 6-B' is FORM PAY 06 as it appears in the cases"),
    ("GPF-O19", "SAP access: RFC or OData rather than BDC; a read-only user; the reports for the pay slip, GPF report and monthly advance schedule"),
    ("GPF-O20", "QR verification route from the air-gapped system: gateway or verification terminal; NADRA e-FRC access"),
    ("GPF-O21", "Missing credits: gazetted status (circular) against BS-16 (Rule 1.40(3))"),
    ("GPF-O22", "Thumb impressions: NADRA biometric verification route as the accepted cure"),
    ("GPF-O23", "Death cases: whether the NADRA FRC substitutes for heirs' CNIC copies; post-death credits"),
    ("GPF-O24", "Service Book: how the section records that the original was physically received"),
    ("GPF-O25", "Missing credits: whether a Treasury-verified schedule row stands in for a missing challan copy"),
    ("GPF-O26", "Whether R4 reaches the signatory of a forwarding endorsement on a substantive form"),
]


def advance_limits_view() -> list[dict]:
    out = []
    for clause, L in ADV_LIMITS.items():
        out.append({
            "clause": clause, "label": L["label"], "rule": L["src"],
            "pct": L["pct"], "months": L.get("months"), "combine": L.get("combine"),
            "minAge": L.get("minAge"), "officePct": PARAMS["officeCapPct"],
            "flag": ("Office 80% differs from the Rules for this clause"
                     if L["pct"] != PARAMS["officeCapPct"] else ""),
        })
    return out


def rules_in_force() -> dict:
    return {
        "rulesetVersion": RULESET_VERSION,
        "officeClarifications": [{"code": c, "text": t} for c, t in R_RULES],
        "advanceLimits": advance_limits_view(),
        "officeCapPct": PARAMS["officeCapPct"],
        "thumbprintFinding": THUMBPRINT_FINDING,
        "openItems": [{"ref": r, "item": t} for r, t in OPEN_ITEMS],
    }
