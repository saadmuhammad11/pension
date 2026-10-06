# AI Management Information System — the centralised case system

One backend, one database, one address. Every one of the 86 departments (61 civil departments
and 25 Punjab Police units) has its own login and files its pension cases at
**http://<server>:5184/**; the AG Pension Wing reviews everything in one queue at the same address;
an administrator oversees users, cases and overrides. What a user sees follows from the account,
enforced by the backend (decision of 25 Sep 2026: one port, unique logins, role-based access). The AI document verification is
the existing pipeline, unchanged. Every page carries "Powered by TMC".

## Screens (28 Sep 2026)

The look follows the `pension-portal.html` mockup at the project root, ported into the source
rather than patched on top: a full-width sign-in page (brand panel, form), status colour that
means one thing everywhere (blue = with the Accountant General, green = approved, red =
rejected, amber = sent back, grey = not yet submitted), the dashboard's figures (decisions,
filings per week, every department's caseload with the awaiting part in blue, the pending
queue by age, time to decision against the 7-day target), the register's filter bar (status,
department, kind of pension) with the kind of case and days waiting on each row, and a case
screen that shows one action once, confidence in words, national ID numbers masked until asked
for, and no hashes or model versions. Two things in the mockup were left out on purpose: the
department sidebar stays (the mockup dropped it), and each department keeps its own colours.
Demo-only parts of the mockup (synthetic cases, a remember-me box, a password link with no
reset behind it) were not ported.

The second mockup of the same day (`pension-portal rd new.html`, "the final features") added
the modern layer, also ported: Geist type (bundled in `src/shared/styles/fonts/`), flat
surfaces with a hairline, sentence-case labels, the four tiles as one ledger strip, one green
ramp in the figures, underlined header navigation, no decorative motion, and a
**Dashboard | Cases** switch in the header for the AG reviewer and the departments (`#/` and
`#/cases`: the same screen in two views, the sidebar in both; a tile on the dashboard opens
the cases with that filter set). The greys every palette shares live in `api/themes.py`.

To see a screen as a signed-in user without a browser at hand:

```bash
node screenshot.mjs ag.reviewer / /tmp/ag-home.png 1440 2400     # see the header of screenshot.mjs
```

## Ports

| Port | Portal | Who signs in |
|---|---|---|
| 5184 | **the** portal: department registers, the AG review queue, administration | every account: the 86 department usernames, `ag.reviewer`, `admin` |
| 5180–5267 | per-department ports — **off by default**; `PENSION_DEPARTMENT_PORTS=1` before start switches them on (5184 and 5201 skipped) | the department's username |
| 8110 | backend API (existing `/api/*` plus the case system's `/api/v2/*`) | — |
| 5300 | development server only (`./run.sh dev`) | — |

Print the full port map with usernames and themes:

```bash
python3 -m api.departments
```

The portal is served by **one process**, `api/portal_server.py`, which binds :5184 (and the
department ports when switched on), serves the built frontend from `portals/dist/`, tells the page
which portal it is (`window.__PORTAL__`), and proxies `/api/*` to the backend with an `X-Portal` header. A port that
another service holds is skipped with a warning; `http://<server>:5184/__portals` lists what is
bound.

## Credentials

Every account has its own password, stored hashed. **While the system is being tried out every
account uses `1234`** (asked for on 25 Sep 2026; `python3 -m api.db set-all-passwords 1234` re-applies
it, and `PENSION_SEED_PASSWORD=1234` in `run.sh` gives new accounts the same). Without that, each
account gets a unique generated password (four words and two digits). The plaintext exists in one place:

```
artifacts/credentials/credentials.html    the sign-in sheet: searchable, sorted by department
artifacts/credentials/credentials.csv     the same as data (portal, department, username, password, port, url)
```

The sheet is also shown at **http://<server>:5184/start.html** (the AG portal's port only; decision
of 25 Sep 2026 — anyone who can reach that port can read every password, so keep the server on the
office network) and, for the administrator, at `/api/v2/admin/credentials` with an admin token. The
files themselves are owner-readable only and are not part of any build. To reset one department's
password (a new one is generated and the sheet updates at once):

```bash
python3 -m api.db reset-department-password <username>
python3 -m api.db set-all-passwords 1234  # one password for every account (trial period)
python3 -m api.db credentials             # re-render the HTML from the CSV
```

`PENSION_SEED_PASSWORD=<one password>` before the first start gives every seeded account that
password instead (demos, tests).

## Two products behind one portal (28 Sep 2026)

After sign-in every account sees two options: **Submit pension documents** and **Submit GP Fund
documents** (for the AG: the pension queue and the GP Fund queue). Each product has its own
dashboard, register and filing form (`#/pension`, `#/gpf`, `…/cases`, `…/new`); a case screen
is `#/cases/<id>` whichever product it belongs to (`cases.product`, migration 0004).

A GP Fund claim follows the same lifecycle as a pension case, examined by the **GP Fund
pre-audit module** in `GP/backend` (its own FastAPI app on :8201, started by `./run.sh` through
`GP/run.sh`). "Examine with AI" on the AG's screen renders the department's PDFs to pages and
hands them to the module's reader (`api/gpf_bridge.py`); the module opens its own case; hard
stops the department can cure with a document send the claim back with the list, a clean
examination approves it, and anything else waits for the Accountant General, who works in the
module's own screens framed inside the case (`/gpf/` on the portal's port proxies the module,
`?embed=1` hides its header and fixes the officer). Passing the claim for payment there, or
clearing everything, approves the case; returning it sends it back to the department. The
department never sees the module's reading.

## The case lifecycle (decision of 28 Sep 2026)

The AI verification belongs to the Accountant General. A department attaches the papers and
files the case, and filing submits it (`FORWARDED`). At the AG a case arrives with one button,
**Verify case with AI**; the outcome moves the case by itself:

| Outcome of the verification | Case goes to | Who sees what |
|---|---|---|
| a required document is missing or defective | `RETURNED` to the department, with the list (`AUTO_RETURN` in the history) | the department sees the list and attaches the papers, then **Resubmit** |
| nothing missing, no finding | `APPROVED` (`AUTO_APPROVE`) | the department sees Approved |
| findings | `UNDER_REVIEW` at the AG | the AG clears each finding; clearing the last one approves the case |
| pages the reader could not identify, and a paper reported missing | `UNDER_REVIEW` | the AG names the pages first, so a case is never returned for a paper that is in the bundle |
| the verification did not complete | `AI_FAILED`, on the AG's desk | the AG verifies again |

The AG may still return, request documents, reject or approve by hand, but only once a
verification has completed on the papers as submitted (29 Sep 2026: every action on a case
rests on a completed examination; a resubmission needs its own). An approval over an uncleared
finding needs a written reason. Before the examination the only thing on the AG's desk is the
examination itself; the administrator's audited override is the one exception. The findings, verdicts
and flag counts are shown at the AG only: the department's screens and the API's answers to a
department carry the status, the history and the list of missing documents, nothing else
(`_redact` in `api/v2.py`; run artefacts answer 403 to a department).

## The case type (29 Sep 2026)

A pension case is filed under a **case type**, chosen first at intake and mandatory: the intake
screen blocks the documents and the submit button until one is chosen, and the API refuses a
pension case without one (`422 select the case type before submitting the case`). The types are
the eleven columns of the AG office's own document sheet (`Document Checklist.pdf`): Fresh – Self,
Fresh – Invalid, Revised, Death during service, Widow / Widower, Unmarried daughter / son, Widowed
daughter, Divorced daughter, Disabled son / daughter / sister, Parent, Unmarried / widowed /
divorced sister. Each is also the checklist column the case runs on, and maps to the pipeline
path(s) the rules classify by (Fresh – Self is Form B-I, superannuation or retiring). The list is
`config/case_types.json` at the repository root, the one file both sides read: `rules/case_type.py`
derives its tables from it and the portal imports it (`src/shared/caseTypes.ts`), so the drop-down
and the rules cannot drift apart. As soon as a type is chosen the intake shows the documents the
sheet ticks for that column (`GET /api/v2/case-types`).

What the declaration does:

- **In the pipeline** it selects the checklist column and the rules directly (`case_type` on the
  run, `declared_case_type` in the run's `intake.json`), instead of waiting for the classifier
  to derive the type from the papers. The papers are still classified; the report carries both
  (`case_type.source` = `declared` or `detected`, `case_type.detected`, `case_type_detected`).
- **When the papers disagree** the verification raises the finding *Declared case type may not
  match documents* (`DECLARED-TYPE-MISMATCH`): HIGH when a prescribed form of another path is
  in the file, MEDIUM when the reading was only inferred. The type is never switched silently.
- **On the case** `case_type` and `case_type_source` (`DECLARED`, `CORRECTED` by the AG, or
  `DETECTED` for a case filed before the declaration existed) plus `detected_case_type` from the
  last verification, shown to the AG only. The register, the case screen, the AG review and the
  administrator's list show the type; the AG register filters and searches by it.
- **Changing it**: a department changes its declaration while the case is on its side (not yet
  forwarded, or sent back); the AG and the administrator correct it at any point with a remark,
  recorded as a `SET_CASE_TYPE` event and a `CASE_TYPE_CORRECTED` audit entry. A correction takes
  effect at the next verification. `POST /api/v2/cases/{id}/case-type`.

## The department's register (29 Sep 2026)

A DDO opens a product on its register, not on charts: the tiles, then every case with a
**timeline on its row** -- Sent, Processing at the Accountant General, Outcome -- with the
outcome named as Returned (red, "attach and resubmit"), Approved or Rejected, and the date of
the current step. The charts follow below and have their own tab (`#/pension/dashboard`). The
AG and the administrator keep the dashboard-first order.

## Pension sections in the AG Review sidebar (29 Sep 2026)

The AG office works departments in five Pension sections. Each department record carries its
section (`Department.pension_section`, from `PENSION_SECTIONS` in `api/departments.py`; the seed
writes it to `departments.pension_section`, migration 0007). The AG Review sidebar shows "All
departments" and then Pension-I to Pension-V as collapsible groups (expanded by default, the
folded state kept for the session), each header with the section's own awaiting/total counts;
pressing a header narrows the dashboard, KPI cards, charts and the case table to that section
(`?pension_section=` on `/api/v2/cases` and `/api/v2/stats`), pressing a department narrows to
it. The search box runs across all groups, opens the groups that match and hides the others.
Cases of the legacy bucket, and of any retired department code, sit below the groups. The case
table filters by section and shows it under the department; the case screen shows it in the
particulars.

## Access rules (enforced by the backend on every call)

The department-side account is the department's **DDO** (Drawing and Disbursing Officer), the
officer who files the department's cases; the role code stays `DEPT_OFFICER`. (Wording of 29 Sep 2026.)

- Everyone signs in at :5184 with their own username; the account decides the role and the
  department. (With per-department ports switched on, a department's officer signs in only at
  that department's port and the AG users only at :5184.)
- A department sees, files, verifies and submits only its own cases. Returns and document
  requests always go back to the department that filed the case.
- The AG reviewer sees every department; the sidebar lists them alphabetically with counts and a
  search box.
- The administrator sees everything, may override any decision with a reason (audit-logged), and
  manages user accounts.
- Five failed logins lock a username for a minute. The old `/api/*` routes now require a
  case-system token as well.

## Sessions (25 Sep 2026)

- Sign-in is required on every visit: the token is kept in `sessionStorage`, so a new tab or a
  reopened browser starts at the sign-in page; nothing is remembered across sessions.
- A session ends after **30 minutes without activity** (a warning appears 2 minutes before, with
  "Stay signed in"), on sign-out, and at once on any 401 from the API; the address returns to the
  sign-in page and the API answers with `Cache-Control: no-store`, so Back shows no case data.
- A page opened without a session (a deep link to a case) is opened after sign-in.
- Every `/api/v2` route except `auth/login` and `portals` answers 401 without a session
  (`tests/test_api_v2.py::test_every_case_system_route_needs_a_session` walks the router);
  document, page and event streams accept the session token on the query string only because
  `<img>` and `EventSource` cannot send headers. Server-side tokens expire after 12 hours.
- Hardening after the 25 Sep audit: five wrong passwords lock **that caller's address** out of the
  account for a minute (not the account for everyone); a wrong username costs the same time as a
  wrong password; the old `/api/*` routes are for the administrator only (the reviewer may read;
  departments are refused); the API keeps no access log, since document and event URLs carry the
  session token; documents open through an authenticated fetch, so the token never appears in an
  address bar or history, and the page sends no Referer; the portal server drops any `X-Portal` /
  `X-Forwarded-*` header a client sends; uploads are capped at 40 files, 256 MB each, 512 MB in all,
  and are written to disk outside the database lock; the reconciler sweeps cases left in
  "AI verification in progress" by a crash; the credentials sheet at `/api/v2/admin/credentials`
  takes the token in the header only.
- Audit fixes (25 Sep, late): the API listens on 127.0.0.1 only (`PENSION_API_BIND=0.0.0.0` to
  expose it), CORS is off unless `PENSION_CORS_ORIGINS` names a dev origin, every portal response
  carries `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`
  and a Content-Security-Policy (the injected portal-config script is the only inline script and
  carries a per-process nonce); `/api/specimens` needs a token; oversized requests are refused from
  their Content-Length; uploads must be PDF, image, Office, zip or plain text (422 names the file);
  a claimant's name is at most 120 printable characters; unknown `status_filter` values → 422; a
  department asking for another department's list → 403; a no-op admin override → 409; user-admin
  audit rows carry the caller's address. A re-run of a failed verification on unchanged papers is
  the same run row started afresh (never re-failed by the sweep); fresh papers after a failed check
  make a new draft; "run the verification on the current documents" is decided by the document
  set's hash (`case_runs.docs_sha`, migration 0003), not timestamps; failure remarks are one plain
  sentence. Register badge: green only when the verdict is FORWARD and the checklist complete;
  amber "Documents missing" otherwise.
- **`/start.html` on :5184 still lists every login in clear** (asked for during the trial). Remove
  it before going live: delete the `start_sheet` route in `api/portal_server.py`.

## Self-running demo

`demo/pension-demo.html` is the whole system in one file with a built-in stand-in for the backend:
double-click it in Chrome, pick a portal, sign in (any account, password 1234), file a case, watch
the verification, submit, then sign in as `ag.reviewer` or `admin`. Esc returns to the wall of
portals, F toggles full screen. Rebuild after UI changes:
`cd portals && npx vite build -c vite.demo.config.ts && python3 ../demo/build.py`.

## Start, stop, status

```bash
./run.sh start      # backend :8110 + the portal server (builds portals/dist if the source is newer)
./run.sh stop
./run.sh restart    # only when no AI verification is running (it would be killed)
./run.sh status     # shows how many ports are bound
./run.sh build      # type-check and rebuild the frontend bundle
./run.sh dev        # live-reload server on :5300; open http://localhost:5300/?portal=agriculture
```

First time only: `cd portals && npm ci`. The backend migrates and seeds its database
(`artifacts/portal.sqlite3`) at start-up: departments and portal particulars from
`api/departments.py`, one officer per department, the AG users, the credentials sheet, and the
import of cases from the old portal. The GP Fund module keeps its cases in the same file
(tables `gpf_cases` and `gpf_documents`, migration 0005, 29 Sep 2026), so one backup covers
both products.

## Configuration

- `api/departments.py` — **the** list: code, name, username/slug, port, theme, police flag.
  Add a department there (next free port from `python3 -c "from api.departments import next_free_port; print(next_free_port())"`), restart, and its officer account and credentials appear.
- `api/themes.py` — the colour palettes. Police units share `police` (sourced from
  punjabpolice.gov.pk); School Education has `education` (sourced from schools.punjab.gov.pk);
  other departments use a sector palette (`health`, `hospital`, `rescue`, `justice`, `finance`,
  `agriculture`, `infrastructure`, `secretariat`). Change a hex once and every department on that
  palette follows.

## Status flow

```
DRAFT ─verify─► AI_CHECKING ─► AI_CHECKED ─submit─► FORWARDED ─take up─► UNDER_REVIEW
                     │                                                      ├─► APPROVED
                     └─► AI_FAILED (verify again)                           ├─► REJECTED
                                                                            ├─► RETURNED ──────┐  attach documents (→ DRAFT, submission 2)
                                                                            └─► DOCS_REQUESTED ┘  → verify → submit → UNDER_REVIEW
```

Every transition is recorded with user, time and remarks (`case_events`, append-only); the
department sees every AG remark on its case. Approving against the AI findings needs reasons of
15+ characters. Findings can be acted on (waived, upheld, checklist items named) only while the
case is with the Accountant General.

## Legacy cases

The register was started fresh on 25 Sep 2026: runs from the old portal are **no longer imported**
at start-up. `PENSION_IMPORT_LEGACY=1` before `./run.sh start` brings them back under
**Legacy — AI Pension Portal** (`api/legacy.py`), numbered `LEGACY-<run id>`, with their AI report,
source file and decisions as history.

## Dashboards

Two charts per screen, from `GET /api/v2/stats` over the same scope as the list below them:
the AG's approved/rejected decisions by department and the cases filed by each department
(review queue, admin); with one department selected, its filings against decisions by week and the
documents its cases most often lack; a department sees the AG's decisions on its own cases and the
documents its cases most often lack. The case page charts the checklist and the time at each stage.

## Where things are

```
api/departments.py   the department/portal list     api/themes.py       palettes
api/portal_server.py the multi-port portal server    api/passwords.py    password generation
api/v2.py            the /api/v2 router              api/workflow.py     statuses and transitions
api/auth.py          login, tokens, portal rule      api/case_runs.py    the AI verification, run → case
api/db.py            SQLite, migrations, seed, credentials sheet          api/migrations/
portals/src/shared/  the one frontend (screens, components, charts, theme, router, auth)
portals/public/tmc-logo.png   the TMC mark (from tmcltd.com)             portals/e2e.py   live end-to-end pass
```

Tests: `python3 -m unittest discover -s tests -t .` (pipeline stubbed; no GPU). Type-check:
`cd portals && npm run typecheck`. Live end-to-end (real AI checks, ~1 h):
`python3 portals/e2e.py "Self Pension.pdf" "Family Pension.pdf" "Widow Daughter Case..pdf" "Document Checklist.pdf"`.
