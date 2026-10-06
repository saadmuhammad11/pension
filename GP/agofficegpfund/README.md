# AG Office Punjab: AI GP Fund Pre-Audit Module

Working knowledge base and prototype for the GP Fund pre-audit module, built for the Office of the Accountant General, Punjab.

**Status:** Prototype, revision 2 (15-09-2026), rebuilt after the AG Punjab office reviewed the first version. Prepared by TMC. Subject to AG Punjab validation.

---

## Run the prototype

```bash
cd prototype
python -m http.server 8099
```

Then open **http://localhost:8099/gp-fund-preaudit-poc.html**

One HTML file with its page images (`pages/`), evidence crops (`evidence/`) and SAP extract samples (`sap-samples/`) beside it. No internet, no build step.

---

## What changed after the office's review

The office found that the first prototype had judged every case without the SAP pay slip and the GPF Final Re-calculation Report, and gave fifteen clarifications. All are built in.

| | Clarification | In the prototype |
|---|---|---|
| R1 | SAP extracts ticked off if present, pulled by personnel number if not | **SAP extracts** step straight after initial processing |
| R2 | Every issue takes a document and is re-checked | **Upload document against this** on every item; whole case re-checked; versions kept |
| R3 | Covering letter never an observation | Recorded only |
| R4 | Delegation of authority for every department | **DOA register** with specimen upload; every signature for an authority looked up |
| R5 | Unattested CNIC or pay slip is only an observation | Advisory |
| R6 | Form 5 and Form 6-B: personal number and signature only | Only those examined; signatures shown beside the CNIC |
| R7 | Match thumb impressions to the CNIC, if feasible | **Tested: not feasible.** Routed to NADRA biometric verification |
| R8 | Pay slip from SAP, manual now, connector later | Upload now; connector interface specified |
| R9 | Advance at most 80% of SAP balance | **Flagged.** Limits applied as the Rules set them by clause, office 80% shown beside |
| R10 | Scan and validate QR codes | Decoded and compared; e-stamp verified on the portal; NADRA portals refused outside requests, so those and unreadable QR codes are observations. Other barcodes are recorded only |
| R11 | Re-calculation report with the pay slip for final payment | Required and reconciled |
| R12 | One refundable advance at a time | From the SAP advance history |
| R13 | OSD post removes the succession certificate | Implemented |
| R14, R15 | Bank-stamped, Treasury-verified challans replace the deduction certificates | Substitution rule |

---

## A walk through the prototype

1. **Intake.** Choose *Refundable Advance* and tick *Treat this case as received without its SAP pages*. Run initial processing.
2. **SAP extracts.** Upload `prototype/sap-samples/SAP_EXTRACT_90000227.txt`, or press *Use the extract saved for this prototype*. Five checks clear; one new question appears (the SAP payroll unit differs from the sanctioning office).
3. **Examination.** Observations, verification tasks with signatures side by side, and the advance limit worked out under Rule 1.14(1)(d)(i) with the office's 80% beside it.
4. **Cure by upload.** Open *Missing Credits*. Against the hard stop for challan Sr. 4, press *Upload document against this*, choose any image, confirm what it shows. The case is re-checked and the hard stop clears.
5. **DOA register** (top bar). Upload a specimen signature; the verification task in the case shows it beside the signature on the sanction.
6. **Disposal and issue.** Payment is blocked while any verification task or SAP item is open. Returning the case prints the claim rejection form; a second return needs the DAG (Funds).
7. **Rules in force** (top bar). The office clarifications, the advance limits by clause with the 80% flag, the thumbprint finding and the open items.

Switch *Signed in as* between Dealing Assistant, Accounts Officer and DAG (Funds) to see the delegation bands.

---

## Contents

| Path | What it contains |
|---|---|
| `prototype/gp-fund-preaudit-poc.html` | The working prototype, revision 2 |
| `prototype/pages/`, `prototype/evidence/`, `prototype/sap-samples/` | Case page images, evidence crops read from the cases, SAP extract samples transcribed from the case SAP pages |
| `prototype-src/` | Prototype source in parts, with `build.py` that assembles and syntax-checks the HTML |
| `instructions/GP-FUND-AI-MODULE-BUILD-SPEC.md` | **The handover document for the sovereign AI team**, revision 2 |
| `source-document/01-office-circular-gpfund-2023.md` | Transcription of the governing circular |
| `_wip-2026-09-15/` | Working material: reading results per case, QR sweep results, thumbprint measurements, the first prototype kept for reference |
| `assets/pages/` | Page images of the first, shorter corpus (superseded) |

---

## The corpus and what the module finds

Eight cases, 58 pages, plus the Punjab GP Fund Rules 1978 (Compendium 2008). SAP pages are in six of the eight cases.

| Case | Hard stops | Observations | Verification tasks | SAP items |
|---|---|---|---|---|
| Final payment, non-gazetted | 0 | 3 | 5 | 0 |
| Final payment, death | 4 | 4 | 7 | 0 |
| Final payment, dismissal | 0 | 4 | 6 | 0 |
| Missing credits | 1 | 1 | 1 | 4 |
| Residual payment | 1 | 1 | 2 | 0 |
| Refundable advance | 0 | 2 | 4 | 0 |
| Non-refundable advance | 0 | 2 | 4 | 0 |
| Balance transfer | 0 | 0 | 2 | 5 |

Several hard stops in the first prototype were wrong or are no longer wanted, and the handover document lists each one (§16.3). The main lessons: the AG office's own working written on a department form is not a department defect; an SAP balance pulled after an advance is posted already excludes it; in the SAP era the personnel number keys the GP Fund account; the corpus is retrospective, so SAP already posts each final payment, which the section confirms by pay order rather than treating as a double payment.

**Thumb impressions.** Smart CNICs carry no fingerprint, and even the clearest ink impressions did not separate same-person from different-person pairs. Matching from the case papers is not possible.

**The 80% flag.** The Rules set 80% only for house and land advances and some non-refundable advances. A general temporary advance is capped at half the balance or three months' pay, and Rule 1.16 allows 100% at age 50. The office should confirm which governs (GPF-O15).

---

## Open items for the AG Office

GPF-O14 DOA register and specimens · GPF-O15 advance limits (flag) · GPF-O16 second advance timing · GPF-O17 OSD post instruction · GPF-O18 Form 6-B · GPF-O19 SAP access (RFC or OData, not BDC) · GPF-O20 QR verification route · GPF-O21 gazetted vs BS-16 · GPF-O22 NADRA biometric route · GPF-O23 heirs and post-death credits · GPF-O24 Service Book receipt · GPF-O25 partial crediting · GPF-O26 R4 on forwarding endorsements · GPF-O1, O3, O4, O5, O6, O8, O11, O12, O13 carried over. Details in the handover document, §18.

---

## Reading order

1. `source-document/01-office-circular-gpfund-2023.md`, the governing circular
2. `prototype/gp-fund-preaudit-poc.html`, the module in use
3. `instructions/GP-FUND-AI-MODULE-BUILD-SPEC.md`, how to build it on the sovereign stack
