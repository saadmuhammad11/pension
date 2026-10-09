# Task: four scope changes requested on 9 Oct 2026

You are working on the AG Punjab AI Pension Portal in `/home/tmc/Desktop/pension` (git, branch `main` at
`8b01d04` or later; PostgreSQL 16 via `PENSION_DATABASE_URL`, see `deploy/postgres.env.example`). Read
`docs/STATUS.md`, `docs/pension-rules-decisions.md` and `docs/DEPLOYMENT.md` first: they hold the system's
history, the business decisions in force and the conventions this work follows.

## The system, in one paragraph

Two products behind one portal. **Pension:** a department's DDO (`DEPT_OFFICER`) files a case; the AG side runs
an AI verification (page identification, OCR form check, double reads, cross-document checks, signature block
read beside the specimen on file) and decides. **GP Fund:** a separate FastAPI module (`GP/backend`, loopback
:8201) pre-audits claims; the AG side sees its examination in a frame. Decisions in force: no pension amount is
computed or shown (`rules/scope.py`); **no automatic approval and no automatic return** (9 Oct 2026); departments
**never see AI output** (`api/v2.py` `_redact`); named logins only; a Deputy AG role (`AG_DAG`) for overrides and
GP Fund hard stops. 86 departments are grouped into five Pension sections, Pension-I to Pension-V
(`api/departments.py` `PENSION_SECTIONS`).

## Ground rules

1. Coordinate before editing: another developer works in this tree. Check `git log` and `git status` first.
2. **Prerequisite, before C1:** the GP Fund defects listed in `docs/FIX-PROMPT-frontend-review.md` Part C
   (C1 SAP trailing-minus deductions read as negative, C2 unread advance balance treated as nil) must be fixed
   first or alongside: C1 below builds GP Fund screens on top of that code.
3. **Before any migration touches the live database:** take a `pg_dump` and confirm it restores into a scratch
   database. There is no scheduled backup on the trial box yet; propose one (a systemd timer or cron running
   `pg_dump -Fc` nightly to `artifacts/backups/`, 14 kept) as part of this work.
4. One commit per change (C1–C4), each with tests that fail before and pass after. Run `tools/run-tests.sh` (pension +
   GP Fund engine on the `pension_test` database), `GP/backend/run.sh test`, and
   `cd portals && npx tsc --noEmit -p . && npx vite build --outDir <scratch>`. Never weaken a test.
5. Migrations go in `api/migrations/` with a PostgreSQL override in `api/migrations/postgres/` where the DDL differs
   (follow 0010/0011). Never edit an applied migration.
6. Record every business decision you implement in `docs/pension-rules-decisions.md` (dated, who decided), and add a
   row per change to `docs/STATUS.md`.
7. Do not touch the live trial (no restart, no migration on the live database, no portal rebuild into `portals/dist`)
   without asking. Before any restart, confirm no verification is running.
8. Do not install into `/home/tmc/vllm_env`; do not touch `~/Desktop/Pension-AG`.

## Open questions: use these defaults, mark each in code and STATUS as "assumed, awaiting confirmation"

| # | Question | Default until answered |
|---|---|---|
| Q1 | Who gives the final approve/reject: Assistant AO or AO? | **AO is final.** Senior Auditor → Assistant AO → AO |
| Q2 | Where does the Deputy AG sit? | Unchanged: overrides any status (remark ≥15 chars, audited) and clears GP Fund hard stops. Not part of the normal chain |
| Q3 | Does the three-tier flow apply to GP Fund claims too? | **Pension only.** GP Fund keeps its own disposal rules; map tiers to GP Fund levels: Senior Auditor → `da`, Assistant AO → `ao`, AO → `ao`, Deputy AG → `dag` |
| Q4 | One user per tier per wing, or several? | **One or more.** Cases go to the wing's queue for that tier, not to a named person |
| Q5 | What becomes of the existing `AG_REVIEWER` account(s) (`syed.haider`)? | Kept as a legacy role, able to read only; the administrator reassigns each to a tier and wing |
| Q6 | Do DDOs see the specimen signatures? | **No.** Specimens are shown to AG-side roles only (Senior Auditor and above). The DDO submits the papers and cannot be their checker |
| Q7 | Service book → new proforma: from what date, and are old service books still accepted? | Blocked on the AG office supplying the proforma and its notification (C2) |

## C1. Signatory master data with specimen signatures (pension and GP Fund)

**Today:** pension keeps one specimen authority in a JSON file (`rules/specimens/register.json`, loaded by
`rules/specimens.py`: S&GAD Additional Secretary (Admn), three images, in force from 2025-09-09). GP Fund keeps a
**provisional** delegation-of-authority register with no specimens (`GP/backend/gpf/doa.py`, persisted to
`GPF_DATA_DIR/doa.json`; API `/api/doa`, `/api/doa/specimens`, `/api/doa/signatories`, `/api/doa/finalize`). A
provisional match yields a verification task, never a hard stop. There is no screen to maintain either.

**Build:**
- **One master-data store** in PostgreSQL for signing authorities, used by both products:
  - The authority: department (from `api/departments.py`), post/designation, officer name, scope (for example
    "PSA for ex-PCS/PSS & PMS BS-17"; GP Fund: what they may sanction), effective from/to dates, the authorising
    letter's number and date, and a scan of that letter.
  - 1–5 specimen images per authority.
  - Entries are never deleted: they are closed with an end date, and every change is audited.
  - Import the existing S&GAD entry and the GP Fund provisional register (keep its provisional flag).
- **An administrator screen** (`portals/src/shared/screens/admin/`):
  - Add, edit and close authorities; upload specimens and the authorising letter.
  - Filter by department and post.
  - Mark the GP Fund register final (replaces `doa_finalize`).
- **Show specimens where the check happens, to AG-side roles only:**
  - **Pension (stage 6b, `pipeline/signatory.py`):** look up by the case's department and the post read off the form.
  - **GP Fund "Signatories and delegation of authority" tasks:** show the signature as read beside the specimens
    of the matching authority for **the case's department** (for example S&GAD), in force on the document's date.
  - When none is on file, say "No specimen on file for <department>, <post>" and keep it a verification task.
  - **The comparison stays the officer's:** no model compares signatures (see `pipeline/signatory.py` notes).
- **Security:**
  - Serve specimen images only to AG-side roles, never to `DEPT_OFFICER` (extend `_redact` and the image routes).
  - No caching; audit every specimen view.
- **Tests:**
  - Lookup by department, post and date, including a closed entry.
  - A DDO is refused the specimen image.
  - The GP Fund task shows the S&GAD specimen for an S&GAD case.
  - The import is idempotent.

## C2. Service book replaced by the new proforma (pension)

**Today:** the checklist line AG-10 is "service book / Character & Service Roll" (`rules/checklist.py`, around
lines 228–236 for the gazetted/non-gazetted rule); page identification knows `SERVICE_BOOK` and
`SERVICE_STATEMENT` (`extraction/schemas.py:587, 636-721`).

**Blocked until the AG office supplies:**
- a blank and a filled sample of the new proforma;
- its notification and effective date;
- whether old service books remain acceptable (for which cases);
- whether it also replaces the Character & Service Roll for gazetted officers.

Do not guess a form layout.

**Then build:**
- **A new document type** (named after the proforma's printed title) in `extraction/schemas.py`. Describe it by
  the printed title and its distinctive fields, the way `SERVICE_BOOK` is described.
- **An OCR form-title check** for it, as for prescribed forms. It must be confirmed by OCR text, not by the vision
  model alone; see `extraction/ocr.py`, "a model cannot be its own witness".
- **The checklist line** relabelled and satisfied by the proforma, with the transition rule decided above (case
  date vs effective date).
- **Facts:** if the proforma states facts the checks use (dates of birth, appointment, retirement), read them with
  the double-read pattern; otherwise presence only.
- **Labels and checks** updated in the portal (`portals/src/shared/labels.ts`) and the flag checks.
- **Tests:**
  - The proforma satisfies AG-10.
  - An old service book after the cut-off date is handled as decided.
  - The golden cases still produce identical findings (`tools/bench_compare.py`).

## C3. Three-tier AG workflow per pension wing (pension)

**Today:** `api/workflow.py` has roles `DEPT_OFFICER`, `AG_REVIEWER`, `AG_DAG`, `ADMIN`. Statuses run DRAFT →
FORWARDED → AI_CHECKING → UNDER_REVIEW → APPROVED / REJECTED / RETURNED / DOCS_REQUESTED; the reviewer runs the AI
check and decides. Maker-checker forbids the filing account from approving.

**Build (defaults Q1–Q5):**
- **Roles:** `AG_SENIOR_AUDITOR`, `AG_ASSISTANT_AO`, `AG_AO` (keep `AG_DAG`, `ADMIN`, `DEPT_OFFICER`). Each AG user
  belongs to **one pension wing** (Pension-I … V), stored in its own column on `users`. **Not as a department.**
- **Routing:** a case belongs to the wing of its department (`PENSION_SECTIONS`). Each tier sees only its wing's
  cases (`may_see`, inventory, stats, register and review screens), the Deputy AG and administrator see all.
- **Flow:**
  1. The department submits. The case lands in the wing's **Senior Auditor** queue.
  2. The **Senior Auditor** runs the AI verification (RUN_CHECK is theirs alone) and reviews the findings and
     checklist.
     - With documents missing or defective, they **return to the department** with the list (no automatic return).
     - With everything present, they **forward to the Assistant AO**. Forwarding is refused while a checklist line
       is Missing or Defective, unless the officer has named the document on its pages or waived the line with
       grounds (`api/checklist_actions.py`).
  3. The **Assistant AO** reviews and either **forwards to the AO** or **returns to the Senior Auditor** (remark
     required).
  4. The **AO** **approves or rejects** (remark required) or **returns to the Assistant AO**.
  5. Returns go one tier down at a time: AO → Assistant AO → Senior Auditor → department.
- **Statuses:** add statuses (or a "holder tier" column; choose and justify) so that the register shows **who
  holds the case** ("With Senior Auditor, Pension-III"). Keep existing statuses readable for old cases (legacy
  labels, as `AI_CHECKED` is today).
- **Remarks:**
  - Remarks between AG tiers are **internal**: a DDO sees only the Senior Auditor's return remark and the final
    decision.
  - Extend `_redact` and the case history, and test it.
- **Maker-checker:** one account may act at only one tier on a given case; the filer can never approve.
- **The Deputy AG override** stays, with every tier's history kept.
- **Rounds** (`api/rounds.py`): a return to the department opens a round request as today. Internal returns do not
  open a department round.
- **Tests:**
  - The full happy path.
  - Each return step.
  - Forward refused with a missing line.
  - Wing isolation (a Pension-II officer cannot see or act on a Pension-IV case).
  - Internal remarks hidden from the DDO.
  - Maker-checker across tiers.
  - Migration of an existing UNDER_REVIEW case into the Senior Auditor queue.

## C4. User management for the wing tiers (super admin)

**Build:**
- **Admin users screen** (`portals/src/shared/screens/admin/Users.tsx`, `/api/v2/admin/users`):
  - Creating an AG user asks for **role** (Senior Auditor / Assistant AO / AO / Deputy AG) and **pension wing**
    (AG Pension Wing I–V; not required for the Deputy AG).
  - A DDO still picks a department.
  - The wing is a separate field. **Do not add the wings to the department list.**
  - Filters by role and wing.
  - Disable, enable and reset password as today; the reset requires a reason (closes STATUS N25).
- **Wing coverage:** a screen or warning showing, per wing, how many active users each tier has. Flag any tier with
  none, since that wing's cases would stop.
- **Accounts:** do not seed 15 named accounts; the administrator creates them from the AG office's list. Production
  refuses shared logins (`db.SHARED_LOGINS`).
- **Tests:** create a user per tier and wing; refuse a wing on a DDO and a department on a wing user; the coverage
  report.

## Done means

Each change committed separately with tests, all suites and the build green, decisions recorded, and STATUS rows
added. Say what remains assumed (Q1–Q7) and what is blocked (C2 until the proforma arrives). Then update the scope
lock document's sections 3–5 and 9 to match, and ask before touching the live trial.
