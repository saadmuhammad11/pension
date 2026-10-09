# Task: fix the findings of the frontend review (7 Oct 2026)

You are working on the AG Punjab AI Pension Portal in `/home/tmc/Desktop/pension` (git, branch
`fix/high-findings`, last reviewed commit `ef13f50`). Read `docs/STATUS.md` and `docs/DEPLOYMENT.md` §3.0
first: they describe the system, the audit history and the conventions this work must follow.

## The system, in one paragraph

A government pension and GP Fund verification system. A FastAPI API (`api/server.py`, `api/v2.py`) behind a
Starlette portal server/proxy (`api/portal_server.py`, port 5184) serves a React 18 + TypeScript portal
(`portals/src`, built with Vite). GP Fund is a separate FastAPI service (`GP/backend`, loopback :8201) whose
own vanilla-JS page (`GP/backend/web`) is shown to the AG inside an iframe at `/gpf/?embed=1`, signed in by an
HttpOnly cookie (`pension_gpf`, Path=/gpf). Roles: `DEPT_OFFICER` (a department's DDO — **must never see AI
output**), `AG_REVIEWER`, `ADMIN`. Users sit on slow office Wi-Fi (0.5–1.5 s round trips measured), on old
office PCs, uploading scanned PDFs up to 256 MB. `PENSION_ENV=production` switches the strict posture
(`api/settings.py`); the trial on this box runs without it.

## Ground rules

1. **Coordinate before editing.** Another developer works on this branch. Pull/check `git log` first, and
   do not rewrite their commits.
2. **One commit per item**, message ending `(frontend review F<n>)`, in the project's existing style: comments
   explain *why*, in full sentences, as the surrounding code does. Add or update the item's row in
   `docs/STATUS.md` (commit + test + what remains).
3. **Every behaviour change gets a test** that fails before the fix and passes after: Python tests in
   `tests/` (or `GP/backend/tests/`), frontend tests once F6 has added Vitest.
4. **Before saying an item is done**, run all of:
   `python3 -m unittest discover -s tests -t .` (with `/home/tmc/vllm_env/bin/python3`),
   `GP/backend/run.sh test`, `cd GP && python3 -m unittest discover -s gpfund/tests -t .`,
   `cd portals && npx tsc --noEmit -p . && npx vite build --outDir <a scratch folder>`.
   Report failures with their output; never weaken a test to pass.
5. **Do not touch the live trial** without asking: do not rebuild `portals/dist`, restart services or run
   migrations against `artifacts/portal.sqlite3`. If asked to restart, first confirm no verification is running
   (`GET /api/runs` as admin shows no `queued`/`running`; `cases.status='AI_CHECKING'` is empty) — restarting
   the API kills a running verification.
6. **Do not change pension or GP Fund business rules** (those wait on `docs/pension-rules-decisions.md`), do
   not install into `/home/tmc/vllm_env`, and do not touch `~/Desktop/Pension-AG` (another developer's copy).
7. File:line references below are as of `ef13f50`; confirm them before editing. Where a finding turns out to be
   wrong, say so with evidence instead of "fixing" it.

## Step 1 — actions that can go wrong (do first)

**F1. GP Fund: Cancel must cancel.** `GP/backend/web/js/app.js:495` and `:600` do `prompt(...) || ''` and carry
on, so Cancel on "Record verified", Return, Refer or Hold still records the action. Treat `null` as abort.
Test: a jsdom/Vitest or Python-side test is acceptable; at minimum a small JS unit around the handler.

**F2. GP Fund: confirm disposals and stop double submits.** `app.js:596-608` disposes (Pass for payment, Part,
Return, Refer, Hold) with no confirmation, and its buttons stay enabled during the POST. Same double-submit gap
on the modal buttons `#w-go` (519), `#c-go` (540), `#q-go` (563), `#spec-go` (674). Add one helper that
disables the button and shows a busy state for the whole request, re-enabling on failure; add a confirm step
naming the case and the outcome for every disposal.

**F3. GP Fund action check bypass with `..` (server).** `api/v2.py:196-207` (`/auth/gpf-act-check`) matches the
case id on the raw path (`_GPF_CASE_ROUTE`) and allows the request when no portal case matches; the proxy
(`api/portal_server.py` `gpf_proxy`) then forwards through aiohttp/yarl, which collapses dot segments. So
`/gpf/api/cases/nonexistent/../REALID/dispose` passes the check on "nonexistent" and acts on REALID
(confirmed: `yarl.URL(...).path` → `/api/cases/REALID/dispose`; also for `%2e%2e`). Fix in the portal server:
percent-decode and normalise the sub-path once, reject (400) any path containing `..`, encoded dots, `//` or a
backslash, then use **the same normalised string** for both the check and the forwarded URL. Test both raw and
encoded forms against a case whose portal status is not under review (expect refusal).

**F4. Warn before the last finding approves the case.** Recording the last open finding approves and closes the
case (`portals/src/shared/screens/CaseFindings.tsx:321-325`, `onSettled`) with no warning. When the action
would clear the last blocking item (the gate is already on the client), show "This is the last open finding;
recording it approves the case" and require confirmation. Make the UPHOLD labels say what actually happens.

**F5. A failed report load is not "not yet verified".** `CaseDetail.tsx:68`: when `fetchReport` fails, the AI tab
says the case has not been verified and offers a 10–20 minute re-run. Keep a separate `reportError`, show
"Could not load the findings — Retry", never offer re-verification for a fetch error.

## Step 2 — before real users

**F6. Tooling first.** Add ESLint (typescript-eslint + `eslint-plugin-react-hooks`, `exhaustive-deps` on) and
Vitest + Testing Library to `portals/`, with `npm run lint` and `npm test`. Fix what lint reports in the files
you touch (do not mass-reformat others). This gives F7–F15 somewhere to put tests.

**F7. Timeouts and plain-language errors.** `portals/src/shared/api/client.ts:9-29`: no request timeout, raw
bodies shown (an nginx HTML error page becomes the message; "Failed to fetch"; "Request failed (401)").
Add an AbortController timeout (30 s for reads/actions; uploads exempt, see F8), keep `ApiError.status`, and map
network/0, 502, 503, 504 and timeouts to: "The connection is slow or the server is busy. Your work was not
saved. Try again." Never render an HTML body. Tests for each mapping.

**F8. Uploads: progress, no duplicates, no mid-upload sign-out.** `Upload.tsx:61-81`, `api/cases.ts:164`:
- Upload through XHR (or a streamed fetch) with a progress bar showing MB sent / total and a
  `beforeunload` guard while sending.
- Client-side check of each file's size (256 MB each, 512 MB total, 40 files) and type before sending; say so
  when a duplicate file is skipped (`Upload.tsx:52` drops it silently).
- **Idempotency:** send a client-generated `Idempotency-Key` on case creation and document upload; the server
  (`api/v2.py` create-case and documents routes) stores key → result per user for 24 h and returns the original
  result on a repeat. Test: two identical POSTs with one key create one case.
- Count an in-flight request as activity for the idle timer (see F9).

**F9. Idle timeout that sees real work.** `portals/src/shared/auth/AuthProvider.tsx:125` only hears events on the
parent window, so work inside the GP Fund frame signs the AG out after 30 minutes. In embed mode,
`GP/backend/web/js/app.js` posts a throttled `{gpfActivity: 1}` (to `location.origin`) on pointer/key events;
the portal accepts it only from its own origin and the frame's window and resets the timer. Pause the timer
while any request is in flight (a counter in `client.ts`). Announce the countdown at 2:00, 1:00 and 0:30 only,
not every second (`AuthProvider.tsx:140`, `aria-live="assertive"`), and add "unsaved text will be lost".

**F10. Short-lived image tokens and a real sign-out (security, Medium; closes STATUS N15).**
- `portals/src/shared/auth/session.ts:72-76` puts the full 12-hour session token on image and event-stream
  URLs; `shared/scan/ScanViewer.tsx:62` fetches them with `cache: 'force-cache'` and the server answers
  `Cache-Control: private, max-age=3600` (`api/v2.py:1552`), so tokens land in the browser's disk cache.
  Issue a separate short-lived **media** token (scope `media`, ~15 min, GET/HEAD only, accepted only on the
  page/signature/specimen/events routes) with `issue_scoped_token` (`api/auth.py:191`); refresh it before
  expiry; serve token-authenticated images with `Cache-Control: no-store` and drop `force-cache`.
- Sign-out (`AuthProvider.tsx:56` → `/api/v2/auth/logout`, `api/v2.py:154`) only clears the GP cookie. Send the
  bearer token and revoke **that token**: add a `jti` claim and a server-side denylist until its expiry.
  **Do not bump `token_version` for this** — the AG accounts are shared (STATUS C1), so bumping it would sign
  out every colleague on `ag.reviewer`.
- Tests: a media token is refused on a JSON route and on any write; a revoked token is refused; the other
  session of the same account keeps working.

**F11. The portal's "is the server up?" check.** `portals/src/shared/PortalShell.tsx:60-74` treats any non-OK
`/api/health` answer as an outage and gives up after three 3-second probes — too short for this Wi-Fi, and
since `77bf493` a degraded model or a low disk returns 503 and shows **every user** the outage screen. Treat any
HTTP response as "online"; show the outage screen only when every probe fails at network level; 10 s timeout.
Pair with the server change in Part C item C3.

**F12. Things that hang or fail silently** (each with a test where practical):
- `CaseDetail.tsx:373-382, 404, 462-464`: a failed `/auth/gpf-session` leaves "Opening the GP Fund module…"
  forever (the error banner renders only when `!state`). Show the error and a Retry whenever `frameSigned` is
  false. Give the 1.5 s `gpfState` tick (393-402) an in-flight guard (chained `setTimeout` + sequence number).
- `CaseDetail.tsx:138-145`: a failed first load shows only "Back"; add Retry and an automatic retry.
- `CaseDetail.tsx:55-62`: the `seq` guard drops every poll reply slower than the 4 s interval, freezing the
  live view on slow links; skip starting a poll while one is in flight instead of discarding late replies.
- `shared/data/inventory.ts:78-84`: an errored register entry retries only when the version moves; retry errored
  entries every tick and show a quiet "Connection lost — retrying" strip instead of a red "Failed to fetch".
- `DocumentList.tsx:31`, `PagePreview.tsx:106`: `.catch(() => {})` closes the blank tab and says nothing; write
  "Opening…" into the pre-opened tab and show the error.
- `AuditLog.tsx:36` shows "Loading…" on error; `Upload.tsx:36-37` shows "Loading the document list…" forever
  and an empty department list when their fetches fail.

**F13. GP Fund page hardening** (`GP/backend/web/js`):
- Escape every value put into HTML: `app.js:413-415` (`src`/`data-zoom` built from `e.url`, `e.crop`, `e.page`,
  `c.template`), `:463` (re-inserting `dataset.zoom`), `:35`, `:585`, `:688`. Replace the inline `onerror` at
  `:414` (the `/gpf` CSP blocks it anyway) with `addEventListener`.
- `api.js:28, 57-75`: `encodeURIComponent` every id put in a path.
- `boot()` (`app.js:25-26, 732`) has no catch — show an error with Retry instead of "Loading…" forever.
- `api.js:45-53`: one failed poll aborts the wait while the job keeps running (the officer re-uploads);
  tolerate 2–3 failures, cap the loop, stop on `hashchange`.
- `api.js:12`: on 401 post `{gpfExpired: 1}` to the parent; the portal re-signs the frame (F12) and reloads it.
- `app.js:64`: give `route()` a sequence token so a slow earlier render cannot overwrite a newer one; if the
  POST succeeded but the re-render failed, say the action was recorded.
- Modal (`index.html:63`): `role="dialog"`, `aria-modal`, focus moved in, trapped and returned; `#toast`
  (`:73`) gets `aria-live="polite"`.

## Step 3 — polish (after Step 2)

**F14. Confirmations and wording.** Confirm Enable user (`admin/Users.tsx:110`), Replace document
(`CaseDetail.tsx:125`) and Override (`components/ActionPanel.tsx:90` — show status labels from `STATUS_META`,
not raw codes, and "Setting from X to Y. This is audited."). Make the password minimum one source of truth: the
server tells the client its rule (e.g. in `/auth/me`), the admin form (`Users.tsx:84,139`, currently 8) and the
change screen (`Login.tsx:176`, says 10) both use it, with a live checklist and a Show toggle.

**F15. Accessibility.** Focus management for `PagePreview.tsx:76-113`; make "Replace" in `DocumentList.tsx:40-43`
a real button (the hidden input is not keyboard-reachable); `htmlFor`/`aria-label` on `Upload.tsx:223`,
`ActionPanel.tsx:88-110`, `AuditLog.tsx:29`; arrow keys + `aria-controls` on the tablists
(`CaseDetail.tsx:231`, `CaseRegister.tsx:182`).

**F16. Performance on old PCs and slow links.**
- `AnalysisLive.tsx:107-111, 186-200`: a 250 ms interval plus `requestAnimationFrame` re-render the whole screen
  with an unbounded log for 10–20 minutes. Memoise, keep the last 300 log lines, drive the bar with CSS.
- `CaseRegister.tsx:159-161`: page the list at ~50 rows on every width (phones already page at 12).
- Inventory poll (`inventory.ts:88`, `Dashboard.tsx:26-33`, `RegisterHome.tsx:26`): skip `useStats` on the cases
  view, back off to 10–15 s when the tab is hidden or idle, and stop refetching every view on unrelated changes
  if it can be done without breaking `python3 -m api.check_inventory`.

**F17. Small correctness items.** One `fmtDateTime` helper (dd Mon yyyy, HH:mm) for `DocumentList.tsx:49`,
`AuditLog.tsx:40`, `CaseFindings.tsx:216`, `CaseDetail.tsx:200,340`; one money helper ("Rs", the grouping the
office uses) shared by the portal (`en-PK`) and GP Fund (`ui.js:47`, `en-US`); `router/hash.ts:19` so "Back to the
register" after a deep-link sign-in stays in the portal; style the DDO's document links like the rest of the
portal; investigate "Claimant name not yet extracted" on GP Fund cases the AI has read (e.g. PC-2026-000095); give
the six identical GP Fund tasks "Signatories and delegation of authority" titles that say which form/signatory;
remove `GpfFindings.tsx` if nothing imports it; tighten the CSP to `object-src 'none'`
(`api/portal_server.py:103-118`).

## Part C — still open from the previous review (backend; not frontend, but unresolved and related)

These were found wrong on `ef13f50` and are not fixed yet. Do them if the other developer has not:

- **C1. G3 regression:** `GP/backend/gpf/format.py` `num()` now reads SAP deductions such as `1,150.00-` as
  **−1150**, so `gpfSubscription`/`loanInstalment` (`sap.py:25`) go negative and `rules_custom.py:139` computes
  a wrong expected closing; `-1,234-` reads as +1234; `50,000-` (OCR lost the slash) as −50000. Apply the sign
  only to balance/closing fields, take the absolute value for subscription/instalment/amount fields, reject a
  double sign.
- **C2. G4 not live:** the fix went into `GP/gpfund/rules_advances.py`, which the served backend never imports;
  `GP/backend/gpf/rules_family.py:391` still treats an unread (None) advance balance as "no advance". Port it:
  None → verification task with the SAP cure; 0 → satisfied.
- **C3. Health:** `api/health.py` returns 503 for a low disk (locks everyone out with F11 undone) and probes models
  and GP Fund sequentially on a cache miss (up to ~9 s, sync route). Return 200 with `degraded` for disk/models/GP
  Fund, 503 for the database only; refresh probes in the background (single-flight, parallel) and answer from the
  last result at once; do not return internal error text to unauthenticated callers in production.
- **C4. G5:** a corrupt `GPF_DATA_DIR/doa.json` silently falls back to the seed register (a final register becomes
  provisional and the unlisted-signatory hard stop disappears), and the next edit overwrites it. Fail loudly:
  keep `doa.json.corrupt-<timestamp>`, refuse to persist over it, log at error. Lock mutate-and-persist; unique
  temp name + fsync.
- **C5. L10:** `deploy/systemd/*.service` `SystemCallFilter=~@privileged @resources` without
  `SystemCallErrorNumber=EPERM` kills the process (SIGSYS) on a blocked call; add it, and smoke-test under the
  units: a .docx conversion, `/api/gpu`, one OCR page.

## Done means

Each item: committed separately with a failing-then-passing test, its STATUS row updated, all suites and the type
check/build green, and a short note of anything you could not verify. Finish with a summary table (item, commit,
test, verified how, anything left) and the exact steps needed to put it live — and ask before doing any of them.
