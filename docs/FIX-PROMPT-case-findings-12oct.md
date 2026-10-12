# Task: four fixes from a fresh self-pension case (12 Oct 2026)

You are working on the AG Punjab AI Pension Portal in `/home/tmc/Desktop/pension` (git; PostgreSQL 16
via `PENSION_DATABASE_URL`, see `deploy/postgres.env`). Read `docs/STATUS.md`,
`docs/pension-rules-decisions.md`, `docs/PIPELINE-OPTIMIZATION.md` and this file before you start.

These four items came from one real run the user made on 12 Oct 2026:

- **Run:** `artifacts/run-a825399965b6` — case `PC-2026-000100`, department SGAD, intake variant
  **`FRESH_SELF`** (self-pension), submitted by `sa.pension2`.
- What the user saw: *"FRC was present but it said it's not found; the Annex B-I form was present but
  it was considered as 'list of family members'; the PSA form considered present; the service book is
  now replaced by a proforma (page 2, heading 'proposed performa for qualifying service for pension')
  that the backend doesn't know; and in self-pension cases the Last Payment Certificate should be
  required for non-gazetted and not required for gazetted."*

## The system, in one paragraph

A department's DDO files a pension case; the AG side runs an AI pipeline — stage 3 identifies each
page (vision model + an OCR title check), stage 4 reads the determination-critical forms, stage 6
collects cross-document facts — then a deterministic rules layer builds the checklist, flags and
case type. No pension amount is computed or shown (`rules/scope.py`); no automatic approval or return
(9 Oct 2026); departments never see AI output. Page identification is the usual root cause of a
"present but not found" finding (`docs/STATUS.md`; memory: *checklist verified against the office
sheet — the misses were page-identification bugs*).

## Ground rules

1. **Coordinate — the working tree is shared and dirty.** As of 12 Oct it carries another
   developer's uncommitted work (the C2 qualifying-service proforma, and tier-visibility, migration
   `0016_reached_tier.sql`) **and** an in-progress `perf/read-cache` change. `git status` and
   `git log` first; build on the current working tree, not on a clean `main`; do not revert or
   clobber either stream. Put this work on its own branch/commits.
2. **One commit per item**, message in the house style (full-sentence comments explaining *why*),
   each with a test that fails before and passes after. Never weaken a test.
3. **Do not touch the live trial** without asking: no restart, no migration on the live database, no
   `portals/dist` rebuild, while a verification is running. Before any restart confirm no run is in
   flight (`GET /api/runs` as admin shows nothing `queued`/`running`; no case in `AI_CHECKING`).
4. **The golden case must not regress.** Item 2 and 4 touch identification and the checklist, which
   decide the golden case's 16/16. Re-run it and keep it identical (`tools/bench_compare.py`, the
   golden fixtures).
5. Gate before "done": `tools/run-tests.sh` (pension + GP engine on `pension_test`),
   `GP/backend/run.sh test`, and `cd portals && npx tsc --noEmit -p .`.
6. Record every business-rule decision in `docs/pension-rules-decisions.md` (dated, who decided =
   the user, 12 Oct 2026) and add a row per change to `docs/STATUS.md`.
7. File:line anchors below are as of 12 Oct; confirm them before editing (`grep`), as the shared
   tree moves under you.

---

## Change 1 — FRC reported "not found" on a self-pension case

**Evidence.** In the run, stage 3 **did** identify the FRC (`identities.json`: pages 19–20 =
`NADRA_FRC`) and stage 6 **did** read it (`case_report.json` → `extracted.frc_family` has six
members). So this is **not** an identification miss — it is a checklist/record linkage gap:

- The office-matrix line for the FRC is **AG-06** (`rules/checklist.py`, ~line 690,
  `"NADRA Family Registration Certificate/s…"`), whose `applies_to` is the **family-pension**
  variants only — `DEATH_IN_SERVICE, WIDOW, UNMARRIED_CHILD, WD_DAUGHTER, DIVORCED_DAUGHTER,
  DISABLED_CHILD_SIBLING, PARENT, SISTER`. It does **not** include the self-pension variants
  (`FRESH_SELF, FRESH_INVALID, REVISED`), so on this `FRESH_SELF` case AG-06 never runs and the FRC
  that is in the bundle is neither shown as satisfied nor acknowledged — it reads as absent.
- `CL-15` (the FD family-death list) also references `NADRA_FRC`, but that list governs family-death
  cases, not self-pension.

**Decide with the user, then build.** The question is a business rule: **is an FRC part of the
self-pension checklist, and if so is it required or only acknowledged when present?** (Self-pension =
the pensioner is alive and claiming their own pension, so an FRC may be optional.) Options:

- If it belongs on the self-pension checklist, add the self-pension variants to AG-06's `applies_to`
  (or add a self-pension FRC line), so a present FRC shows satisfied and a missing one reads per the
  office rule.
- If it does **not** apply to self-pension, the fix is to make the finding say **"not applicable to a
  self-pension case"** rather than "not found", so the user is not told a present document is missing.

**Tests:** a `FRESH_SELF` fixture with an FRC in the bundle produces the agreed outcome (satisfied, or
explicitly not-applicable), never a bare "missing".

---

## Change 2 — the self-pension prescribed form (Form B-I) read as "list of family members"

**This is the central bug and the reason the case fell to `ROUTE_MANUAL`.**

**Evidence.** `case_type.json` for the run: `case_type = null`, `route = ROUTE_MANUAL`, evidence
*"No PSA-prescribed form (B-I/B-II/B-III/B-IV/D-I/D-II) was located in the bundle."* Yet the user
says the "Annex B-I" form was present and was taken as a "list of family members". Page
classification (`identities.json`): p5 `PENSION_APPLICATION`, **p6/p7/p8 = `ANNEX_A` (conf 1.00)**,
and **no `FORM_B_I` anywhere**. The system knows Form B-I (`extraction/identify.py:164`
`"FORM_B_I": ("B-I", "B1")`; `rules/case_type.py:124` maps it to superannuation/retiring pension,
the self-pension path), so a missing B-I on a self-pension case means it was mislabelled.

The likely mechanism: `extraction/identify.py:431` maps the heading
`list\s+of\s+family\s+members|descriptive\s+roll` → `ANNEX_A`. A page of the self-pension form (or a
genuine Annexure B-I family-members list) printing "list of family members" is swallowed into
`ANNEX_A`, so the prescribed form is never recognised.

**Open question for the user — resolve before coding (see "Open questions"):** on pages 6–8, which
page is the **Form B-I** (the prescribed self-pension form, clause 3 "Total length of qualifying
service for pension") and which, if any, is a **separate Annexure B-I** that genuinely is a family
list? They are different documents with different consequences.

**Build (per the answer):**

- **If a page is Form B-I:** it must be identified as `FORM_B_I`, not `ANNEX_A`, so case-type
  detection finds the prescribed form and the case leaves `ROUTE_MANUAL`. Strengthen the form-code
  read (`extraction/identify.py` around the prescribed-form logic, ~line 52 and ~line 164) so a B-I
  page is not out-competed by the generic "list of family members" title; the prescribed-form
  heading/clause must win over `ANNEX_A`. Confirm with `rules/case_type.py` that a detected `FORM_B_I`
  routes the `FRESH_SELF` variant correctly.
- **If a page is a genuine Annexure B-I** (a distinct family-members list, not Form B-I): add an
  `ANNEX_B_I` document type (`extraction/schemas.py` label + `extraction/schemas.py:628` description;
  `portals/src/shared/labels.ts`) with its own title pattern placed in `DOCUMENT_TITLES`
  (`extraction/identify.py:430`) **before** the generic `list of family members → ANNEX_A` entry, so
  the specific form wins; wire it to whatever checklist line it satisfies.
- **PSA form "considered present":** the user also noted the PSA form is marked present — confirm with
  them whether that is correct (good) or itself wrong; do not change it without that confirmation.

**Tests:** the self-pension bundle (or a fixture of it) identifies the B-I as `FORM_B_I`, case type is
no longer `ROUTE_MANUAL`, and the "list of family members" page is classified as the user confirms;
the golden case is unchanged.

---

## Change 3 — qualifying-service proforma: already built, confirm it's live and detected

**Do not re-build this.** The proforma was added on 12 Oct 2026 (another developer, scope change C2):
document type `QUALIFYING_SERVICE_PROFORMA`, title regex `PROFORMA_TITLE`
(`extraction/identify.py:428`, matches "pro/per/pre…form… for qualifying se… for pension", tolerant of
the office's "PERFORMA"/"SEVICE" typos), accepted by checklist lines **AG-10** and **CL-09**
(`rules/checklist.py` ~720 and ~397). Memory and `docs/pension-rules-decisions.md` record it as **not
live until the services are restarted**.

**Why the user's run missed it:** in `run-a825399965b6`, **page 2 was classified `OTHER` (conf 1.00)**,
not `QUALIFYING_SERVICE_PROFORMA` — consistent with the run having used the pre-restart code. Note the
title reconciliation (`titles_on_page`) only re-reads `OTHER`/`AFFIDAVIT` pages (`GENERIC_LABELS`,
`extraction/identify.py:446`), so page 2 being `OTHER` is exactly the page the proforma title check
should catch **once the new code is running**.

**Do:**
1. Confirm no verification is in flight, then (with the user's OK) restart the services onto the
   current tree and **re-run this case**. Confirm page 2 now identifies as
   `QUALIFYING_SERVICE_PROFORMA` and AG-10/CL-09 read satisfied.
2. If it still misses, capture page 2's OCR text (`artifacts/run-*/ocr_text.json` or re-OCR) and check
   it against `PROFORMA_TITLE`. The reported heading "proposed performa for qualifying service for
   pension" should match via **"performa"** (`per`+`forma`); if the real OCR differs, widen the regex
   with a test, and do not break the guard that stops Form B-I's clause-3 wording from matching it.

---

## Change 4 — self-pension LPC: required for non-gazetted, not for gazetted

**Decision (user, 12 Oct 2026):** in self-pension cases the Last Payment Certificate is **required for
non-gazetted** servants and **not required for gazetted** servants.

**Today.** The office-matrix line is **AG-08** (`rules/checklist.py`, ~line 707): *"Last Pay
Certificate (DDO for non-gazetted, Audit/Payrolls for gazetted)"*, `applies_to = {FRESH_SELF,
FRESH_INVALID, REVISED, DEATH_IN_SERVICE}`, with **no** gazetted gating — it is required for all of
them.

**Build.** Gate AG-08 for the **self-pension variants only**, using the existing pattern:

- There is already a gazetted/non-gazetted decision helper, `_service_record_pair(record)`
  (`rules/checklist.py:224`, gazetted at `GAZETTED_FROM_BPS = 16`), and the `not_applicable_when=`
  hook is already used this way by AG-09 (`_service_statement_not_issued`) and AG-10
  (`_service_book_not_kept`).
- Add `not_applicable_when=_lpc_not_required_when_gazetted`, a helper that returns a reason **only
  when** the variant is in `SELF_PENSION_VARIANTS` **and** `_service_record_pair` says gazetted
  (e.g. *"a self-pension gazetted officer's last pay is certified by Audit/Payrolls; the LPC is not a
  separate requirement for them"*), and `None` otherwise. It must **not** change AG-08 for
  `DEATH_IN_SERVICE` (that is family pension, outside this decision), and must leave LPC required for
  non-gazetted self-pension.

**Tests:** gazetted `FRESH_SELF` → AG-08 not-applicable; non-gazetted `FRESH_SELF` → AG-08 required;
`DEATH_IN_SERVICE` → AG-08 unchanged. Record the decision in `docs/pension-rules-decisions.md`.

---

## Open questions (get the user's answer before coding the dependent item)

1. **(Change 2)** On pages 6–8 of this bundle, which is the **Form B-I** prescribed self-pension form
   and which (if any) is a **separate Annexure B-I** family list? What is the exact printed heading of
   each? (Decides whether the fix is "classify as `FORM_B_I`" or "add an `ANNEX_B_I` type".)
2. **(Change 1)** Is the FRC part of the **self-pension** checklist — required, optional-when-present,
   or genuinely not applicable? (Decides AG-06's `applies_to` vs a "not applicable" message.)
3. **(Change 2)** Is the PSA form being "considered present" correct, or is that also wrong?
4. **(Change 4)** Confirm the gazetted cut-off is BPS-16 for this rule (it is the system default).

## Verification checklist (before calling it done)

- [ ] Re-run `run-a825399965b6` (or its fixture): case type is no longer `ROUTE_MANUAL`; the FRC,
      the B-I/Annex page, and the page-2 proforma each read as agreed.
- [ ] Golden case still 16/16 (`tools/bench_compare.py`).
- [ ] `tools/run-tests.sh`, `GP/backend/run.sh test`, `cd portals && npx tsc --noEmit -p .` all green.
- [ ] Decisions recorded in `docs/pension-rules-decisions.md`; rows added to `docs/STATUS.md`.
- [ ] One commit per change; the shared tree's other uncommitted work is untouched.
