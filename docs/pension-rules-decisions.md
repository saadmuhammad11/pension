# Pension rules: decisions needed before go-live

**For:** the pension rules owner (AG Punjab, Pension Wing)
**From:** the production audit of 6 October 2026
**Status:** decisions pending. No code has been changed for any item on this sheet.

Each item below is a place where the system computes a pension or makes a decision in a way that may be wrong, and where the correct behaviour is a matter of rule or office practice rather than programming. For each item the sheet gives:

- what the code does now;
- a worked example;
- the possible correct behaviours;
- the rule it touches;
- a recommendation.

Mark one option in the **Decision** line. Code follows once a decision is recorded.

The rule IDs (`QS-07`, `CALC-01` and so on) are those in the rule packs (`rules/packs/PB-2024.12.json`, `PB-2026.02.json`) and the domain brief (`01-QWEN-DOMAIN-BRAIN-ag-punjab-pension.md`, cited as BRAIN §).

---

## Summary

| # | Item | Effect today | Recommended |
|---|---|---|---|
| 1 | Auto-approval ignores the engine's verdict | Cases the engine put on HOLD, or for which it computed no pension, are approved with no officer | Approve automatically only on a clean FORWARD verdict with a computed pension |
| 2 | Qualifying service at the 6-month mark | Loses a whole year (about 3.3% of pension for life) | Count the end date as served; then apply QS-07 |
| 3 | Two reads of a page disagree | The second read's figures are used anyway | Do not use any figure from that page; route to an officer |
| 4 | Pay lines from several documents | Different amounts for the same component are added together | Take the base from one authoritative document; refuse on conflict |
| 5 | Form D-I dates not checked against each other | A misread date of birth starts family pension before the death | Refuse unless entry < death ≤ notional superannuation; apply QS-02 |
| 6 | Voluntary retirement at 59 | Paid as superannuation, without the 2% reduction | Superannuation only if retirement falls on the superannuation date |
| 7 | Re-grant to a second family member | 75% may be applied to a pension that is already 75% | Never take the base from a family-pension PPO; route to an officer |
| 8 | Family pension relations and eligibility | Grandchildren, in-laws and adult sons paid 75%; a "wife d/o" read as a child | Recognise spouse first; refuse relations not in the rules; route sons |
| 9 | Zero or negative pay base | Rs 0 pension computed, and can be auto-approved | Refuse |
| 10 | Waivers tied to finding numbers | After a recompute, an old waiver can clear a different finding | Tie each waiver to what the finding says; clear waivers on recompute |
| 11 | Waivers carried into a resubmission (already traceable) | A resubmission can be approved with no new officer action | Policy decision (see Appendix) |

---

## 1. Auto-approval ignores the rules engine's verdict

**What the code does now.** When a verification finishes, `api/case_runs.py → outcome()` decides where the case goes. It approves the case automatically when nothing on the checklist is missing, there are no flags, and a checklist was applied. It never looks at:

- the engine's own verdict (`FORWARD` / `HOLD` / `RETURN_FOR_CORRECTION`);
- whether a pension was computed at all, or why not;
- whether any pages could not be identified;
- any engaged `BLOCKING-*` item.

The engine itself (`rules/verdict.py → recommend()`) never says FORWARD while a HIGH flag or a blocking item stands. It is only this last step that ignores it. The same gate (`calculation_gate`) is used when an officer clears the last finding, and it treats a case with no checklist as "nothing missing".

**Worked example.** A clean Form D-I (death in service) case, golden-case figures: gross pension Rs 134,421, family pension Rs 100,816.
- The engine returns HOLD, because the gratuity is unresolved (`BLOCKING-06`). It is either Rs 33,605 (25% of one month's gross, the literal reading) or Rs 4,989,130 (capitalised by the commutation table). The medical allowance band is also open (`BLOCKING-03`).
- With no flags and no missing paper, `outcome()` returns AUTO_APPROVE. The case is approved with no officer having seen it, on a gratuity the system itself says it cannot determine.

Nine cases in the trial data have exactly this shape: HOLD, 0 flags, 0 missing. Examples are `run-94fe91578dec`, `run-60b775ea26a2` and `run-1298bb27c89d`; these HOLD on the provisional D-II rate (`BLOCKING-07`), which per the 16 Sep decision needs DAG confirmation.

A case where the engine **refused** to compute is also approved if the checklist is complete and there are no flags. Examples of refusals:
- a pay figure unreadable;
- a pre-2017 death the pack does not cover;
- the 2024 pack refusing a D-I without the three-year average.

**Possible correct behaviours.**
- **A.** Auto-approve only when the verdict is FORWARD, a pension was computed, no blocking item is engaged, every page is identified, and the checklist is complete. Everything else goes to the AG for review (CHECK_DONE).
- **B.** As A, but allow auto-approval with a provisional figure when the only open item is one the office has decided may proceed provisionally (for example `BLOCKING-07`, decided 16 Sep). The PPO is marked provisional and the DAG confirms later.
- **C.** Turn auto-approval off entirely for go-live: every case is approved by an officer, and the system only recommends.

**Rule / section.**
- SOP §6 (AI assists, the officer decides);
- BRAIN §9.7 and the `BLOCKING-06` warning ("No PPO may issue on a gratuity figure while this is open");
- the 16 Sep decision that `BLOCKING-07` needs DAG confirmation;
- the 28 Sep decision that a clean case auto-approves.

**Recommendation.** **A** for go-live, with **C** as a fallback if the office prefers a period of full manual approval to build confidence. B only after the provisional-PPO process is written down.

**Decision:** ☐ A ☐ B ☐ C ☐ Other: ____________________

---

## 2. Qualifying service loses a year at the 6-month mark (QS-07)

**What the code does now.** `rules/service.py → span()` counts service with the end date not counted as served (the "exclusive" convention, `BLOCKING-16`). `reckoned_years()` then applies QS-07: 6 months or more rounds up, less than 6 months is ignored. For a servant who joins on the 1st of a month and leaves on the last day of a month, exclusive counting falls one day short of a whole month. That one day decides the rounding.

The domain brief says the convention is "immaterial at year granularity after QS-07 rounding". It is not, at the 6-month boundary.

**Worked example.** (Run on the engine, 6 Oct 2026.)

| | Entry → retirement | Engine says | Actually served | Reckoned now | Should be |
|---|---|---|---|---|---|
| Case 1 | 01-03-1996 → 31-08-2025 | 29y 5m 30d | 29y 6m | **29 years** | 30 years |
| Case 2 | 01-01-2016 → 30-06-2025 | 9y 5m 30d | 9y 6m | **9 years: no monthly pension (QS-02)** | 10 years: monthly pension |

On a base of Rs 100,000 (`CALC-01`: base × years × 7/300):
- Case 1: Rs 67,667 a month instead of Rs 70,000, which is **Rs 2,333 a month less, for life** (3.3%). The commutation and the family pension that follow are lower in proportion.
- Case 2: the servant is refused a monthly pension altogether and gets only service gratuity (QS-03).

The "inclusive" option in the code does not fix it either: it adds one day without carrying it into months (29y 5m 31d), so it still rounds down.

**Possible correct behaviours.**
- **A. Inclusive counting:** the retirement or death date is a day served. Service is entry to (end + 1 day), normalised into years, months and days, then QS-07. Case 1 gives 29y 6m 0d, so 30 years.
- **B. Exclusive counting, as now,** confirmed by the office as the Punjab practice. Case 1 stays 29 years; the office accepts the result.
- **C. Count in calendar months:** a part month at either end counts as a whole month if more than 15 days, then QS-07.

**Rule / section.**
- `QS-07` (Punjab Civil Services Pension Rules; BRAIN §9.1);
- `BLOCKING-16` (day-counting convention, open);
- `QS-02`/`QS-03` (10-year minimum);
- `CALC-01`.

**Recommendation.** **A.** The servant was in service on the day of retirement (retirement takes effect in the afternoon, `QS-10`), and the department's own figure in the golden case counts that day (32y 2m 11d against the engine's 32y 2m 10d). Ask the office to confirm against two or three past determinations that sat at the 6-month mark.

**Decision:** ☐ A ☐ B ☐ C ☐ Other: ____________________

---

## 3. Two reads of a page disagree, and the figures are used anyway

**What the code does now.** Money pages are read twice and compared (`extraction/client.py → extract_page_confirmed`). Its own documentation says it "raises if the two reads disagree on any amount". It does not: it returns the second read with a note, `READ-DISAGREEMENT … No figure from this page may be used`. Nothing downstream reads that note. `pipeline/extract.py → stage_extract` uses the page's pay lines, dates and pension figures as if the reads had agreed, and no flag is raised.

**Worked example.** Two reads of an AG pay certificate: read 1 gives Adhoc Relief 2025 = Rs 19,203, read 2 gives Rs 15,203. This is the exact misread seen on the golden case, page 29, reported at confidence 1.00. Today the second read's Rs 15,203 goes into the pay base and the pension is computed on it. Only the agreement note, which nobody reads, records the disagreement.

**Possible correct behaviours.**
- **A.** Any disagreement on an amount: no figure from that page is used. The determination is refused for that input with a HIGH flag naming the page, and the officer keys or confirms the figure.
- **B.** Read the page a third time and take the majority. Refuse only if all three differ.
- **C.** Use the read whose total reconciles with the page's own printed total (see item 4). Refuse if neither does.

**Rule / section.**
- BRAIN §5.3 (extraction discipline: a doubtful read is not used);
- §8.4 (money checks);
- the client's own contract in `extract_page_confirmed`.

**Recommendation.** **A** now, since it is what the code was meant to do. C is a good refinement once item 4 is in.

**Decision:** ☐ A ☐ B ☐ C ☐ Other: ____________________

---

## 4. Pay lines from several documents are added together; the §8.4 total check never runs

**What the code does now.** `pipeline/extract.py` builds the pay base by merging the pay lines from Form D-I, the salary statement and the first LPC. It removes duplicates only where the component **and** the amount are identical, so the same component with two different amounts is counted twice. The per-page check that the lines add up to the page's own printed total (`reconcile_pay_components` / `reconcile_gross` in `extraction/client.py`) exists but is never called. A HIGH flag catches the problem only if the form's printed total happened to be read.

**Worked example.** (Run on the engine.)

| Source | Line | Amount |
|---|---|---|
| Form D-I, p.41 | Basic pay | 98,000 |
| Salary statement, p.42 | Basic pay | 100,000 |
| Old transfer LPC, p.7 | Basic pay | 5,200 |

Reckoned basic pay: **Rs 203,200**, marked as needing no human. The true figure is one of 98,000 or 100,000. At 30 years a base of Rs 203,200 gives Rs 142,240 a month instead of about Rs 70,000.

**Possible correct behaviours.**
- **A.** Take the base from one authoritative document in a fixed order: Form D-I (or the B-series sanction), else the AG salary statement, else the last LPC. Use other documents only to corroborate. A component with conflicting amounts across documents is refused and routed to the officer.
- **B.** As A, and also run the §8.4 reconciliation on every page: a page whose lines do not add up to its printed total is not used.
- **C.** Keep merging, but refuse whenever the same component appears with different amounts.

**Rule / section.**
- BRAIN §8.4 ("The reckonable total on the form equals the sum of the components … the single highest-value arithmetic check in the system");
- §8.3 (precedence hierarchy);
- `EMOL-BASE`, `EMOL-NOTE-*`.

**Recommendation.** **B.** Please also confirm the order of authority for the base document.

**Decision:** ☐ A ☐ B ☐ C ☐ Other: ____________________  Order of authority: ____________________

---

## 5. Form D-I (death in service): dates are not checked against each other

**What the code does now.** The Form D-I path in `rules/engine.py` computes from the date of birth, entry and death as read, without checking them against each other. The self-pension path does have such a check (`check_retirement_against_birth`). The 10-year minimum (`QS-02`) is also not applied on this path.

**Worked example.** Golden-case pattern, with the date of birth misread by one pen stroke: 19-02-1956 instead of 19-02-1966. Entry 08-12-1993, death 29-07-2021.

| | Correct (DOB 1966) | As computed (DOB misread 1956) |
|---|---|---|
| Notional superannuation | 18-02-2026 | 18-02-2016 |
| Family pension commences | 19-02-2026 | **19-02-2016, five years before the death** |
| Service reckoned | 30 (capped) | 22 |
| Family pension | **Rs 100,816** | **Rs 73,932**, no refusal |

A second example: entry date 01-01-2022 after a death on 29-07-2021. The engine computes 4 years of service and Rs 13,442, with no refusal.

**Possible correct behaviours.**
- **A.** Refuse (route to the officer) unless entry < death ≤ notional superannuation. Apply QS-02: under 10 years gives no monthly family pension through this path, so route it.
- **B.** As A, and also cross-check the date of birth against the CNIC and FRC (the §8.4 identity checks) before computing.
- **C.** Flag HIGH but still compute.

**Rule / section.**
- BRAIN §8.4 ("Date of death before the notional superannuation date, for an in-service death");
- `FAM-IS-01`, `FAM-IS-05`, `QS-01`, `QS-02`, `QS-10`.

**Recommendation.** **B.**

**Decision:** ☐ A ☐ B ☐ C ☐ Other: ____________________

---

## 6. Voluntary retirement at 59 is paid as superannuation (VOL-RED-01)

**What the code does now.** When a department declares a fresh self-pension and the papers don't settle which kind, `rules/case_type.py` falls back to superannuation, and so does `pipeline/report.py` when no type is set. The age check accepts any retirement at 59 or later as superannuation, so the voluntary-retirement reduction is never applied to a 59-year-old.

**Worked example.** Date of birth 15-09-1966 (superannuation 14-09-2026). Retires 31-03-2026 at 59. Base Rs 100,000, 30 years.

| | As superannuation (now) | As voluntary retirement |
|---|---|---|
| Gross pension | Rs 70,000 | Rs 68,600 (2% reduction at 59) |
| Commutation ceiling (25%) | Rs 17,500 | Rs 17,150 |

**Rs 1,400 a month overpaid, for life.**

**Possible correct behaviours.**
- **A.** Superannuation only if retirement falls on the superannuation date (the afternoon before the 60th birthday), allowing for month-end practice. Anything earlier is voluntary retirement, and `VOL-RED-01` applies.
- **B.** If the type is not declared and the dates do not match superannuation, refuse and route to the officer.
- **C.** Keep the fallback but raise a HIGH flag whenever retirement precedes superannuation.

**Rule / section.**
- `VOL-RED-01` (FD notification 2 Dec 2024, rule 4.4(1) proviso: 59 years 2% … 55 years 10%; marked unverified, `BLOCKING-19`);
- `QS-04` (25 years for voluntary retirement);
- `QS-10`.

**Recommendation.** **A + B**: decide from the dates when they are clear, and route when they are not. Please also confirm the reduction table (`BLOCKING-19`).

**Decision:** ☐ A ☐ B ☐ A+B ☐ C ☐ Other: ____________________

---

## 7. A re-grant may apply 75% to a pension that is already 75%

**What the code does now.** For a death after retirement (Form D-II), `pipeline/extract.py` can take the base pension from a PPO or FPPO found in the file, which overrides the form's figure (§8.3 makes the PPO the authority). The extractor reads whether a PPO is itself a family-pension order (`is_family_pension`), but nothing uses that. On a re-grant, for example to a daughter after the widow's death, the strongest document is often the late widow's FPPO, whose figure is already 75% of the original pension.

**Worked example.** Original pensioner's pension Rs 80,000.
- The widow's FPPO shows Rs 60,000 (75%).
- On the daughter's re-grant, the FPPO is taken as the base and 75% applied again: **Rs 45,000** (56.25% of the original).
- The correct figure under `FAM-AR-02`, as provisionally decided, is about Rs 60,000.

This is likely rather than confirmed end to end; the path is confirmed in code.

**Possible correct behaviours.**
- **A.** Never take the base from a family-pension order. Use the original pensioner's PPO, or the figure the family pension was computed from.
- **B.** On a re-grant, carry the existing family pension over unchanged to the next eligible member (no new 75%).
- **C.** Route every re-grant to an officer.

**Rule / section.**
- `FAM-AR-01` (from the pension in payment on the PPO/FPPO and Form D-II);
- `FAM-AR-02` / `BLOCKING-07` (rate and base unresolved);
- BRAIN §8.3.

**Recommendation.** **C** until the rate and base are confirmed (`BLOCKING-07`), then **B** if office practice confirms that a re-grant continues the same amount.

**Decision:** ☐ A ☐ B ☐ C ☐ Other: ____________________

---

## 8. Family pension: relations misread, and no eligibility checks (Form D-II)

**What the code does now.** `rules/dii.py → _share_key_for` maps the relation text on the form to an entitlement. Two problems:
- It recognises child words before spouse words, so "wife d/o Ali" is read as a child, and the spouse's 10-year term (`FAM-AR-06`, 2024 amendment) is left out.
- Relations outside the rules ("daughter-in-law", "grand daughter", "widow of deceased son") and an adult "son" are treated as an eligible child and paid 75%.

The eligibility steps (age, marriage, income) exist in the rule file but are left unset and are not used.

**Worked examples.** Pensioner's pension Rs 80,000.

| Relation as written | Treated as | Paid now | Under ENT-* |
|---|---|---|---|
| "wife d/o Ali" | child | Rs 60,000, no end date | spouse: Rs 60,000 for 10 years or until remarriage (FAM-AR-06) |
| "grand daughter" | unmarried child | Rs 60,000 | not an entitled relation: nil |
| "daughter-in-law" | unmarried child | Rs 60,000 | not entitled: nil |
| "son", age 34 | child | Rs 60,000 | not entitled unless disabled (ENT-04) or within the age limit (ENT-02, `BLOCKING-08`) |

**Possible correct behaviours.**
- **A.** Recognise spouse words first. Refuse relations not in ENT-01 to ENT-05. Route any son unless "disabled" with a Medical Board certificate, or an age within the limit, is on file.
- **B.** As A, and apply the eligibility checks: age for sons (once `BLOCKING-08` is settled), unmarried status for daughters (from the FRC or Form C-1), and dependency for parents.
- **C.** Compute nothing for D-II beyond the spouse case; route all others.

**Rule / section.**
- `ENT-01` to `ENT-07` (BRAIN §9.9);
- `FAM-AR-06` (2024 amendment, FD.SR-III-4-244/2023(B), on file as *Amendmant Rules.pdf*);
- `BLOCKING-08` (sons' age).

**Recommendation.** **A** now; **B** once `BLOCKING-08` is settled.

**Decision:** ☐ A ☐ B ☐ C ☐ Other: ____________________  Sons' age limit (BLOCKING-08): ________

---

## 9. A zero or negative pay base gives a Rs 0 pension

**What the code does now.** `rules/emoluments.py → reckon()` accepts an empty list of pay components and gives a total of 0, marked as needing no human. It also accepts negative amounts and adds them in, and the three-year average accepts zero or negative years. The calculation then produces gross Rs 0 and family pension Rs 0 with no refusal. Under item 1, such a case can be approved automatically.

**Worked example.** No pay table readable on any page, so no components and a base of Rs 0. `CALC-01` gives 0 × 30 × 7/300 = **Rs 0 gross, Rs 0 family pension**, presented as a determination.

**Possible correct behaviours.**
- **A.** Refuse whenever there is no reckonable component, or any amount is zero or negative. Route the case, naming the missing figure.
- **B.** As A, but allow a negative line only where it is a printed deduction the rules name (none are in the reckonable set today).

**Rule / section.** `EMOL-BASE`, `EMOL-NOTE-1/2`, `CALC-01`, BRAIN §9.3.

**Recommendation.** **A.**

**Decision:** ☐ A ☐ B ☐ Other: ____________________

---

## 10. Waivers are tied to finding numbers that change on recompute

**What the code does now.** An officer's waiver is stored against the finding's number (F-1, F-2, …) in `api/dispositions.py`. Findings are renumbered every time the report is rebuilt (`rules/flag_curation.py → curate()`), and a recompute (`api/runs.py → recompute`) rebuilds the report but keeps the waivers.

**Worked example.**
- Before a recompute, F-1 is a MEDIUM "attestation stamp unclear", and the officer waives it.
- After the recompute, a new HIGH "pay base does not reconcile" sorts first and becomes F-1.
- The old waiver now clears the HIGH finding, and the case can approve itself.

**Possible correct behaviours.**
- **A.** Tie each waiver to what the finding is (its class, title and source pages). A waiver no longer matching any finding lapses.
- **B.** Clear all waivers on any recompute, so the officer reviews again.
- **C.** A + B: tie waivers to content, and on recompute keep only those whose finding is unchanged, listing the lapsed ones for the officer.

**Rule / section.** SOP §6 (officer accountability); audit trail requirements.

**Recommendation.** **C.** This one is mostly technical, but it changes what an officer must re-do after a recompute, so it is listed for decision.

**Decision:** ☐ A ☐ B ☐ C ☐ Other: ____________________

---

## Appendix: High items already fixed, and the one policy question left

These were in the audit's High list, are technical, and are fixed in code on branch `fix/high-findings`, which is not yet merged:

| Item | Fixed in | Note |
|---|---|---|
| A re-verification could take the previous run's result | `ef18463` | No decision needed |
| Waivers and the approvals they trigger were not on the audit trail | `fab85f4` | Now recorded by officer account, address and ground |
| GP Fund actions were allowed on rejected or returned cases | `a861ade` | Only while under the AG's review |

**11. Policy question: carried waivers.** When a department resubmits after a return, findings an officer already waived in the earlier round are carried into the new round (`api/rounds.py → carry_decisions`). If nothing new is outstanding, the resubmission is approved with no fresh officer action. It is now recorded who made the original waivers, but whether this should happen at all is a policy matter.

- **A.** Keep: a waiver stands until the paper it concerned changes.
- **B.** Carried waivers are shown to the officer pre-ticked, but the officer must confirm them before the case can be approved.
- **C.** Never carry waivers; every round is reviewed afresh.

**Recommendation.** **B.**

**Decision:** ☐ A ☐ B ☐ C ☐ Other: ____________________

**Related, also policy.** There is no maker-checker today: one administrator account can file a case for any department and approve it, and all AG reviewers share one `ag.reviewer` login. The office should decide whether approvals need a second person, and should issue individual AG accounts before go-live.

---

*Recorded by:* ____________________  *Designation:* ____________________  *Date:* ____________
