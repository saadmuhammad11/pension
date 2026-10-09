# Pension rules: decisions needed before go-live

**For:** the pension rules owner (AG Punjab, Pension Wing)
**From:** the production audit of 6 October 2026
**Status:** **decided 7 October 2026** by the pension rules owner; recorded below under each item and implemented on `fix/high-findings` (see `docs/STATUS.md` for the commit of each).

**Scope decision (7 Oct 2026).** This release does **no pension calculations**. The system parses, checks and reviews the documents of a case; every computed amount (pension, commutation, gratuity, family-pension share, qualifying service as a payable figure, the emoluments base) is removed from the portal, the reports, the exports, the API and the AG's view. The rules engine may run internally only where its output is never shown or stored as a result. Items 2, 6, 7 and 9 (and the day-counting note, N10) are therefore **closed as out of scope** for this release and stay on this sheet for the release that computes.

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

| # | Item | Effect today | Recommended | Decision (7 Oct 2026) |
|---|---|---|---|---|
| 1 | Auto-approval ignores the engine's verdict | Cases the engine put on HOLD, or for which it computed no pension, are approved with no officer | Approve automatically only on a clean FORWARD verdict with a computed pension | C — no automatic approval |
| 2 | Qualifying service at the 6-month mark | Loses a whole year (about 3.3% of pension for life) | Count the end date as served; then apply QS-07 | Closed, out of scope |
| 3 | Two reads of a page disagree | The second read's figures are used anyway | Do not use any figure from that page; route to an officer | A |
| 4 | Pay lines from several documents | Different amounts for the same component are added together | Take the base from one authoritative document; refuse on conflict | B — LPC governs; never sum |
| 5 | Form D-I dates not checked against each other | A misread date of birth starts family pension before the death | Refuse unless entry < death ≤ notional superannuation; apply QS-02 | B — hard stop; <10 y finding |
| 6 | Voluntary retirement at 59 | Paid as superannuation, without the 2% reduction | Superannuation only if retirement falls on the superannuation date | Closed, out of scope |
| 7 | Re-grant to a second family member | 75% may be applied to a pension that is already 75% | Never take the base from a family-pension PPO; route to an officer | Closed, out of scope |
| 8 | Family pension relations and eligibility | Grandchildren, in-laws and adult sons paid 75%; a "wife d/o" read as a child | Recognise spouse first; refuse relations not in the rules; route sons | B — fixed list (Appendix B) |
| 9 | Zero or negative pay base | Rs 0 pension computed, and can be auto-approved | Refuse | Closed, out of scope |
| 10 | Waivers tied to finding numbers | After a recompute, an old waiver can clear a different finding | Tie each waiver to what the finding says; clear waivers on recompute | C — exact finding |
| 11 | Waivers carried into a resubmission (already traceable) | A resubmission can be approved with no new officer action | Policy decision (see Appendix) | Follows item 10 |

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

**Decision (7 Oct 2026):** ☒ **C** — automatic approval is removed completely. Every case, including one with no findings, needs a human decision. Automatic *return* of a case with missing or defective documents stays.

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

**Decision (7 Oct 2026):** **Closed — out of scope.** No qualifying service is computed or shown in this release. Reopen with the calculation release.

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

**Decision (7 Oct 2026):** ☒ **A** — when two reads of a page disagree, no figure from that page is used; a finding is raised for human review.

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

**Decision (7 Oct 2026):** ☒ **B** — the LPC is the source of truth for pay components. A different amount for the same component on another document raises a finding. Amounts are never summed across documents. Order of authority: **LPC** first; nothing else supplies a component.

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

**Decision (7 Oct 2026):** ☒ **B** — on Form D-I an impossible set of dates (death before birth, family pension starting before the death, entry after the death, and the like) is a hard stop. Service under 10 years raises a finding for the reviewer (no computation of the entitlement in this release).

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

**Decision (7 Oct 2026):** **Closed — out of scope.** No pension is computed, so no reduction is applied or shown. Reopen with the calculation release.

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

**Decision (7 Oct 2026):** **Closed — out of scope.** No re-grant amount is computed in this release. Reopen with the calculation release.

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

**Decision (7 Oct 2026):** ☒ **B** — a fixed list of eligible family-pension relations, each with the proof it needs (age, marital status, income), drawn from the pension rules. A relation not on the list, or with its proof missing, raises a finding. The "Wife d/o" misread is fixed. **The draft list is in Appendix B below, for the rules owner to confirm before it is treated as final.** Sons' age limit (BLOCKING-08): as in the draft list, to be confirmed.

---

## 9. A zero or negative pay base gives a Rs 0 pension

**What the code does now.** `rules/emoluments.py → reckon()` accepts an empty list of pay components and gives a total of 0, marked as needing no human. It also accepts negative amounts and adds them in, and the three-year average accepts zero or negative years. The calculation then produces gross Rs 0 and family pension Rs 0 with no refusal. Under item 1, such a case can be approved automatically.

**Worked example.** No pay table readable on any page, so no components and a base of Rs 0. `CALC-01` gives 0 × 30 × 7/300 = **Rs 0 gross, Rs 0 family pension**, presented as a determination.

**Possible correct behaviours.**
- **A.** Refuse whenever there is no reckonable component, or any amount is zero or negative. Route the case, naming the missing figure.
- **B.** As A, but allow a negative line only where it is a printed deduction the rules name (none are in the reckonable set today).

**Rule / section.** `EMOL-BASE`, `EMOL-NOTE-1/2`, `CALC-01`, BRAIN §9.3.

**Recommendation.** **A.**

**Decision (7 Oct 2026):** **Closed — out of scope.** No pay base and no pension are computed in this release. Reopen with the calculation release.

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

**Decision (7 Oct 2026):** ☒ **C** — each waiver is tied to the exact finding: rule id, document, field and value. If that finding changes or disappears on a re-check the waiver lapses and the finding needs fresh human review.

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

**Decision (7 Oct 2026):** settled by item 10 — a carried waiver stands only while the exact finding it was given against is unchanged in the new round; otherwise it lapses and the officer reviews afresh. No approval follows from carried waivers alone, since item 1 removed automatic approval.

**Related, also policy — decided 7 Oct 2026.** Named logins for every reviewer; the shared `ag.reviewer` account is retired. Maker-checker: the user who submits a case cannot approve it, administrators included. The IT administrator manages users only and takes no case action in pension or GP Fund; every action is logged under the real user's name, never a role placeholder. In GP Fund only the DAG may clear a hard stop, and written grounds are mandatory.

## Decisions of 7 October 2026 (evening), recorded

Three further decisions by the rules owner, taken after the day's implementation:

| # | Decision | Effect in the code |
|---|---|---|
| E1 | **Automatic return stays** — *superseded 9 Oct 2026, see below.* A case whose required documents are missing or defective is still returned to the department automatically with the list; only automatic *approval* was removed (item 1). | `api/case_runs.py outcome()`: `AUTO_RETURN` kept, `AUTO_APPROVE` gone (`17f14fb`). |
| E2 | **GP Fund's check figures stay.** The module computes no payable amount; the figures it does compute (advance limit and excess, outstanding earlier advance, challan variance, balance-transfer sum, death-claim expected amount) are check results and remain as they are. | No change to `GP/`; the scope decision applies to pension amounts. |
| E3 | **H6 relations list goes live as advisory only.** The draft list is applied, its two findings are MEDIUM checks for the reviewer and never block a case, until the owner confirms Appendix B and its assumptions. | `9f941ce`; Appendix B below. |

**9 Oct 2026 — no automatic return, in pension and in GP Fund.** E1 is withdrawn. A verification that
finds required documents missing or defective now leaves the case with the Accountant General
(`UNDER_REVIEW`) with the list in the history row; the AG returns it with the Return button, naming the
papers. A return the officer makes inside the GP Fund module's own screens no longer moves the
pension-side case either; the AG returns that case the same way. The system's only actions are to
record a verification's outcome (`CHECK_DONE`, `CHECK_FAILED`). `AUTO_RETURN` and `GPF_RETURN` remain in
the transition table only so history written before that day still reads.

## Appendix B: eligible family-pension relations — **Draft, pending rules-owner confirmation**

**Status: DRAFT, pending rules-owner confirmation.** The list the code applies since 7 Oct 2026 (`rules/relations.py`),
**as advisory only** (owner's decision of 7 Oct 2026): a claim under a relation not in this table, or with a proof
missing, raises a MEDIUM check for the reviewer ("Verify relation eligibility …", "Proof of … not found") and never
blocks a case; no share is computed in this release. **For the pension rules owner to confirm, row by row, before it
is treated as final.**

| Relation | Rule | Entitlement runs | Proof needed (documents the reader names) | To confirm |
|---|---|---|---|---|
| Widow / widower | ENT-01 | For life; ends on remarriage (ENT-01). The spouse precedes every other class (ENT-07). | **relationship** — the marriage: Nikah Nama, or the NADRA FRC showing the spouse (`NIKAH_NAMA`, `NADRA_FRC`)<br>**marital status** — not remarried (Form C-1 / non-remarriage certificate, AG-15) (`NON_REMARRIAGE_CERTIFICATE`) | that a widower is paid on the same terms as a widow |
| Son | ENT-02 | Until the prescribed age (draft 21; BLOCKING-08). | **relationship** — named as a son on the NADRA FRC (`NADRA_FRC`)<br>**age** — date of birth from the CNIC / B-form, the FRC or the matriculation certificate (`CNIC`, `CNIC_CLAIMANT`, `NADRA_FRC`, `MATRIC_CERTIFICATE`) | the age limit (21?) and whether it extends while in full-time education |
| Unmarried daughter | ENT-03 | Until marriage (ENT-03). | **relationship** — named as a daughter on the NADRA FRC (`NADRA_FRC`)<br>**marital status** — recorded unmarried on the NADRA FRC (`NADRA_FRC`) | whether an unmarried daughter's entitlement is for life under the current rules |
| Widowed daughter | ENT-03 | While widowed and dependent, without a regular income (ENT-03). | **relationship** — named as a daughter on the NADRA FRC (`NADRA_FRC`)<br>**marital status** — widowed: the FRC's status, or the husband's death certificate (`NADRA_FRC`, `NADRA_DEATH_CERTIFICATE`)<br>**income** — no regular source of income (AG-17) (`NO_REGULAR_INCOME_CERTIFICATE`) | the dependency and income conditions |
| Divorced daughter | ENT-03 | While divorced and dependent, without a regular income (ENT-03); from the divorce. | **relationship** — named as a daughter on the NADRA FRC (`NADRA_FRC`)<br>**marital status** — the divorce deed / certificate (AG-21) (`DIVORCE_CERTIFICATE`)<br>**income** — no regular source of income (AG-17) (`NO_REGULAR_INCOME_CERTIFICATE`) | the dependency and income conditions, and the divorce-timing rule |
| Disabled son / daughter | ENT-04 | For life, while the disability lasts (ENT-04). | **relationship** — named as a child on the NADRA FRC (`NADRA_FRC`)<br>**disability** — Medical Board certificate of permanent disability (AG-14) (`MEDICAL_BOARD_CERTIFICATE`) | which Board's certificate the office accepts |
| Dependent father / mother | ENT-05 | While dependent, where no spouse or eligible child survives (ENT-05, ENT-07). | **relationship** — named as a parent on the NADRA FRC (`NADRA_FRC`)<br>**dependency** — dependent on the deceased; no regular income (AG-17) (`NO_REGULAR_INCOME_CERTIFICATE`) | the dependency test the office applies |
| Unmarried / widowed / divorced sister | office column | As the office's checklist column has it; the rules cited name no sister. | **relationship** — named as a sister on the NADRA FRC (`NADRA_FRC`)<br>**marital status** — unmarried, widowed or divorced (`NADRA_FRC`, `DIVORCE_CERTIFICATE`, `NADRA_DEATH_CERTIFICATE`)<br>**income** — no regular source of income (AG-17) (`NO_REGULAR_INCOME_CERTIFICATE`) | WHETHER a sister is eligible at all, and on what conditions |
| Child (son or daughter, sex not stated) | ENT-02 / ENT-03 | As a son or an unmarried daughter, once the form says which. | **relationship** — named as a child on the NADRA FRC (`NADRA_FRC`)<br>**age** — date of birth (`CNIC`, `CNIC_CLAIMANT`, `NADRA_FRC`, `MATRIC_CERTIFICATE`)<br>**marital status** — marital status on the NADRA FRC (`NADRA_FRC`) | (none: resolves to son or daughter on the FRC) |

Not on the list, and therefore a check for the reviewer: grandchildren, sons- and daughters-in-law, nephews and nieces, brothers, uncles, aunts, cousins, step-relations, and any relation the papers do not state. Sons' age limit used in the draft: 21 (BLOCKING-08).

### Assumptions behind the list, to confirm one by one

| # | Assumption | Drawn from | Confirmed |
|---|---|---|---|
| 1 | The spouse (widow or widower) precedes every other class; the entitlement is for life and ends on remarriage. | ENT-01, ENT-07 (domain brief) | ☐ |
| 2 | A widower is paid on the same terms as a widow. | ENT-01 (to confirm: the rule text says widow) | ☐ |
| 3 | A son draws until the age of 21; whether it extends while in full-time education is not settled. | ENT-02; BLOCKING-08 (prescribed age unconfirmed) | ☐ |
| 4 | An unmarried daughter draws until marriage; whether it is for life under the current rules is not settled. | ENT-03 | ☐ |
| 5 | A widowed or divorced daughter draws while dependent and without a regular income; the divorce is proved by the deed, the widowhood by the FRC or the husband's death certificate, the income by the no-regular-income certificate. | ENT-03; office checklist AG-17, AG-21; family_pension_dii.yaml eligibility.daughter_requires_no_source_of_income (UNSET) | ☐ |
| 6 | A disabled son or daughter draws for life while the disability lasts, on a Medical Board certificate. | ENT-04; office checklist AG-14 | ☐ |
| 7 | A dependent father or mother draws only where no spouse or eligible child survives, and while dependent (no regular income). | ENT-05, ENT-07; office checklist AG-17 | ☐ |
| 8 | An unmarried, widowed or divorced sister is eligible at all, on the same dependency and income conditions. | office checklist column SISTER only; no ENT rule names a sister | ☐ |
| 9 | The relationship is proved by the NADRA FRC naming the claimant, else (for the spouse) by the Nikah Nama. | ENT-06 (Form C / C-1); office checklist item 22 | ☐ |
| 10 | The claimant's marital status is taken from the NADRA FRC, falling back to Annex-A. | domain brief §8.3 (NADRA above the department's declaration) | ☐ |
| 11 | The claimant's age is taken from the FRC's year of birth, else the CNIC / B-form or the matriculation certificate. | CNIC / FRC as the age documents; no rule text names the proof | ☐ |
| 12 | The spouse's not having remarried is proved by the non-remarriage certificate (Form C-1). | ENT-06; office checklist AG-15 | ☐ |
| 13 | Grandchildren, sons- and daughters-in-law, nephews and nieces, brothers, uncles, aunts, cousins and step-relations are not eligible. | not named in ENT-01 to ENT-07 | ☐ |
| 14 | A relation the papers do not state (form, FRC applicant, FRC row, Annex-A) is a check for the reviewer, not a bar. | owner's decision of 7 Oct 2026 (advisory list) | ☐ |

**Confirmation:** ☐ confirmed as drafted ☐ confirmed with the changes noted: ____________________  *Date:* ____________

---

*Recorded by:* the pension rules owner, through the project lead  *Date:* 7 October 2026
