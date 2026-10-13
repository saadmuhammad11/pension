# Full system audit — Pension and GP Fund

**Date:** 13 October 2026
**Scope:** backend API, AI document pipeline, shared React portal, both products (Pension and GP Fund), the GP Fund module and the bridge between them.
**Code audited:** working tree on branch `perf/read-cache` at `f946a1e`; `main` at `d99968e` used for comparison.
**Live system:** API `127.0.0.1:8110`, portal `0.0.0.0:5184`, GP Fund module `127.0.0.1:8201`, PostgreSQL 16 on `127.0.0.1:5433`. All were running throughout and were **not** restarted or stopped.

## How this audit was done

Code was read end to end and the running system was used: signed in as an administrator, an AG reviewer, a department DDO and all three AG tiers (Senior Auditor, Assistant AO, AO), with the APIs called directly and the authorisation boundaries probed. Every finding below was verified before it was written down. Three claims raised during the audit were tested and **discarded as false** (see "Checked and found sound").

**What was deliberately not done,** to honour the "change nothing" instruction:

- No state-changing POST was sent to a live case. Authorisation on write endpoints was tested with a body that cannot pass validation, so a request that got past the permission check would stop at the validator without writing. Where that was ambiguous, the check was confirmed by reading the code instead.
- The production build was run to a scratch directory, not over `portals/dist`, so the live portal was untouched.
- Direct SQL against the live database was refused by this environment's sandbox. Database findings below come from reading the migrations and the query sites, except where a figure is marked as read through the API.
- The GP Fund backend test suite was not run in the first pass, because `pytest` is absent from the services' interpreter. **Corrected on 13 Oct 2026:** it lives in its own virtual environment at `~/.cache/gpf-test-venv`, and the suite passes, 112 tests (see L-05).

**One side effect to be aware of:** testing the login rate limit locked the `admin` account for 60 seconds from this host only, at about 10:20. The lock is keyed per account **and** per address, so no other machine was affected, and it has long since expired. Nothing else was altered.

---

# Status of the go-live fixes (13 October 2026)

Eleven findings are done on branch `fix/audit-13oct-blockers`, cut from `main` at `d99968e`, and
are marked **FIXED** in the headings below. H-06 is marked **PARTLY FIXED**: the half that was
stopping verifications in the office is fixed, and the half that is not is written out under the
heading. Nothing else in this report has been changed.

**First pass** — five findings, each of which turned a failure of our own reading into either a
clean report or a shortcoming letter to a department that had filed correctly:

| Finding | What changed |
|---|---|
| C-03 | A stage 6 failure now records a gap, and `check_cross_checks_ran` raises a HIGH finding from it, so a failed run can no longer read as a clean case. |
| H-02 | `PsaSignature.unreadable` is carried into the rules; an unread signature block is now an AG-owned "could not be read" finding instead of a shortcoming letter to the department. |
| H-04 | `page_ocr_text` returns `None` on failure rather than `""`; the pages whose heading could not be read are recorded and raised as a HIGH finding instead of the document being reported MISSING. |
| H-05 | A copy no second reader reached is left unjudged, so a single flaky vision read no longer raises ATTEST-MISSING against a department. |
| H-07 | The revoked-token expiry is written in the same clock the sweep compares against, so signing out lasts as long as the token. |
| M-12 | Both screens now ask the service who may waive, so no button is offered that the service would refuse. In GP Fund the office also opened the waiver to every examining tier (decision of 13 Oct 2026). |

Pinned by `tests/test_audit_fixes_13oct.py`, including an end-to-end check that the golden
fixture is **not** accused of C-03 and that a recorded stage 6 failure **is**.

**Second pass** — the remaining blocker and the four items behind it:

| Finding | What changed |
|---|---|
| C-04 | Every `/api` request to the GP Fund module now carries a shared key, set by the portal's proxy and by the bridge and checked by a middleware; without it the module answers 401. A browser's own `X-GPF-Key` is stripped before the portal sets its own. `/api/health` is the one open path. |
| M-03 | `db.target()` is inside `_connection`'s guard, so the timing recorder keeps its promise of silence. A completed run is no longer reported failed. |
| H-06 | *(partly)* With M-03 guarded, a run no longer dies holding a verification slot, and `tests/test_run_concurrency.py` passes on this box. The queued-run deadline and the absolute per-stage deadline are still open. |
| H-08 | Migration 0017 indexes `case_runs(run_id)`, and all six queries on that column take `ORDER BY started_at DESC, submission_no DESC, id DESC LIMIT 1`, so the approval gate is decided the same way every time. `started_at` is stamped to the microsecond now, because at second precision a resubmission verified within a second of the previous run read as the older of the two. The index is not unique: the live table already holds duplicates, and which row is the real run is the office's decision. |
| M-07 | Migration 0017 indexes `audit_log(entity_id, action)`, the two queries every sign-in runs. |

Pinned by `tests/test_audit_fixes_13oct.py`, `tests/test_portal_holds_the_gpf_key.py` and
`GP/backend/tests/test_module_needs_the_portals_key.py`. Migration 0017 was applied to the live
trial database on 13 Oct 2026; both indexes are additive, and nothing reads differently for them.

**Also on the branch, not audit findings:** the module's `/docs` pages now obey `GPF_API_DOCS`
either way instead of being forced on whenever production mode is off, and `run.sh` closes both
products' description pages on the trial box without turning on production mode, which the office
cannot have yet (it keeps the shared passwords and the sign-in sheet — C-01, C-02, H-01).

# Critical

## C-01 — The sign-in sheet, with every username and password, is served to anyone on the network

**Severity:** Critical · **Area:** both · **Category:** Security / access control
**Where:** `api/portal_server.py:199` (route), `api/portal_server.py:256-270` (handler), `api/db.py:583` (generator)

**What is wrong.** The portal serves `/start.html`, an HTML page listing every account in the system with its password in clear text. There is no token, no cookie and no role check. The only condition is that the request arrives on port 5184 and that the server is not in production mode. The portal binds `0.0.0.0`, so the page is readable from any host on the office network.

**Reproduce.**
```
curl -s http://10.170.1.143:5184/start.html | head -40
```

**Evidence (measured today).** The page returns HTTP 200 from all three of this box's addresses — `10.170.1.143`, `192.168.100.11`, `192.168.101.11`. It lists **105 accounts** and the string `1234` appears **103 times**. The accounts include `admin` (Administrator), `ag.reviewer` (the AG desk), all fifteen tier accounts and every department DDO. The file on disk is correctly `0600`; this route is what defeats that.

**Suggested fix.** Delete the route, or put it behind the same check `/api/v2/admin/credentials` already uses (`require_roles("ADMIN")`, with each read audited). This was item 1 of the 12 October audit and is still open.

## C-02 — Every account shares the password `1234`, and nothing forces a change

**Severity:** Critical · **Area:** both · **Category:** Security / credentials
**Where:** `run.sh:33`, `api/db.py:412-415`, `api/auth.py:299`, `api/settings.py:36-42`

**What is wrong.** The seed password defaults to `1234` and is applied to every account. Two defences exist and both are switched off outside production: the weak-password refusal in `authenticate` is wrapped in `if settings.production()`, and `force_password_change()` returns `production()`, so `must_change_password` is 0 on every seeded account.

**Reproduce.** Six accounts across four different roles were signed in with `1234` during this audit: `admin`, `ag.reviewer`, `agriculture`, `sa.pension1`, `aao.pension1`, `ao.pension1`. All six returned a valid 12-hour token.

**Evidence.** `run.sh:33` — `export PENSION_SEED_PASSWORD="${PENSION_SEED_PASSWORD:-1234}"`. Live confirmation above.

**Suggested fix.** Reset the accounts to generated passwords, drop the `1234` default from `run.sh`, and make the weak-password refusal unconditional rather than production-only. Taken with C-01, any machine on the network can read the account list and sign in as the administrator.

## C-03 — When the cross-document stage fails, the case is reported clean  **[FIXED]**

**Severity:** Critical · **Area:** Pension · **Category:** AI pipeline / correctness
**Where:** `api/runs.py:641-642`, `pipeline/report.py:794-799`

**What is wrong.** Stage 6 is the only producer of cross-document facts. If it raises, the handler writes a transient warning event and nothing else. The stage beside it, `extract`, calls `_record_gap` in the identical situation (`api/runs.py:620-621`); the stage 6 handler does not. No gap is recorded, so nothing reaches the one artefact the report surfaces.

`assertions.json` is then missing and the report builds over an empty fact set. The code says so itself:

```python
# pipeline/report.py:794-796
# Per-document assertions, where stage 6 has collected them. Without these the battery
# runs over nothing and reports a clean case: a contradiction needs two documents.
```

Every finding that needs two documents to disagree — personnel-number mismatch, undeclared recovery, CNIC expiry, attestation, Annex-A against the FRC — silently does not fire. The run ends `done` and the verdict can be FORWARD. The only trace is an in-memory event line that is discarded after 60 minutes.

**Reproduce.** Point the OCR endpoint at a closed port so the attestation reader raises outside stage 6's per-page handler, then verify a case with a known mismatch. The report shows no findings.

**Suggested fix.** Call `_record_gap(run, "assertions", str(exc))` in that handler; raise a HIGH flag in `build_report` when `assertions.json` is absent but `documents.json` is not; promote the existing `assertions.json.partial` checkpoint so partial facts still reach the rules.

## C-04 — The GP Fund module enforces no authentication at all  **[FIXED]**

**Severity:** Critical · **Area:** GP Fund · **Category:** Security / access control
**Where:** `GP/backend/gpf/api.py:5-7`, `GP/backend/gpf/api.py:138-144`, `GP/backend/gpf/api.py:507`

**What is wrong.** The GP Fund FastAPI app has no authentication dependency on any route. Every mutating endpoint trusts an `officer` string taken from the request body, overridden by a header if one is present. Its own module docstring states it: *"there is no real auth in the MVP; wire SSO/LDAP in front in production"*. The bridge sends no credential either — only a display name.

The module therefore relies entirely on its loopback bind. Any process on this host, running as any user, has full GP Fund rights, including acting as the Deputy AG. `/api/cases/{id}/pages/{n}` additionally serves page images out of the **pension** artefact tree.

**Reproduce.**
```
curl -s http://127.0.0.1:8201/api/cases      # 200, the full list of claims, no credential
curl -s http://127.0.0.1:8201/api/acting     # {"officer":null,"name":null}
```
Both were confirmed returning 200 with real claim data during this audit.

**Mitigation that currently holds.** The module binds `127.0.0.1` only, and the portal's `/gpf/` proxy does require a signed-in AG-side frame cookie — verified: `/gpf/api/cases` returns 401 without one, from the loopback and from a network address. So this is not reachable off the box today. Setting `GPF_BIND=0.0.0.0`, or any local code execution, removes that single protection.

**Suggested fix.** Require a shared secret on every `/api/*` route of the GP app, set by the portal and the bridge, and refuse when it is absent. A loopback bind is a deployment property, not an access control.

---

# High


**Fixed (13 Oct 2026).** Every `/api` request to the module carries a shared key, set by the portal's
`/gpf/` proxy and by the reconciler's bridge and checked by a middleware on the GP app; without it the
module answers 401 and reads nothing from the request. `/api/health` is the one open path, and it names
no claimant. A browser's own `X-GPF-Key` is stripped at the proxy before the portal sets its own, so a
page in the frame cannot forge it. The key is `GPF_API_KEY` where the two run on different hosts, and
otherwise `artifacts/.gpf_api_key`, created on first use `0600` and resolved once per process.
`GP/backend/gpf/apikey.py`, `api/gpf_bridge.api_key`, `api/portal_server.gpf_proxy`.
`GP/backend/tests/test_module_needs_the_portals_key.py`, `tests/test_portal_holds_the_gpf_key.py`.
The loopback bind stays, but it is no longer the only thing holding.

## H-01 — The live box is not running in production mode, which is what enables C-01 and C-02

**Severity:** High · **Area:** both · **Category:** Configuration
**Where:** `run.sh` (never exports `PENSION_ENV`), `api/settings.py:45-48`, `GP/backend/gpf/api.py:112-117`

**What is wrong.** `PENSION_ENV` is absent from the environment of all three live processes (checked in `/proc/<pid>/environ` for the API, the portal and the GP module). Consequently: the credentials page is served (C-01), the weak-password rules are off (C-02), `/docs` and `/openapi.json` are public on both 8110 and 8201, `/__portals` is public, and `PENSION_JWT_SECRET` falls back to a generated file rather than being required.

**Evidence.** `GET /docs` → 200 and `GET /openapi.json` → 200 on 8110, and the same on 8201, both without a token.

**Suggested fix.** Set `PENSION_ENV=production` on the box. This one change closes C-01, most of C-02 and several Medium items below. It is the single highest-value action in this report.

## H-02 — An unreadable signature block is reported as an unsigned sanction  **[FIXED]**

**Severity:** High · **Area:** Pension · **Category:** AI pipeline / correctness
**Where:** `pipeline/signatory.py:113-137`, `pipeline/report.py:702-705`, `rules/caserecord.py:166-178`, `rules/flags.py:2036-2039`

**What is wrong.** When the signature block cannot be read, the error is stored as `entry["unreadable"]`, but the entry is still built from an empty block, so `signature_present` and `stamp_present` come out `False`. The `PsaSignature` record the rules consume has **no** `unreadable` field and the builder never passes one, so the marker is dropped. "We could not read this page" reaches the rules as "this form carries no signature and no stamp", which raises AUTH-DEFECT against a department whose form is in fact signed.

Where the department has no specimen on file the flag is skipped instead, so the read failure vanishes entirely rather than being reported.

**Related, same place.** `read_block` is a single `extract_page` call, not the confirming double read, in a module whose own docstring records that the model reads the same stamp differently between runs.

**Suggested fix.** Carry `unreadable` into `PsaSignature`; emit "the signature block could not be read", owned by the AG, instead of the "no signature" wording; use the confirming double read for the block.

## H-03 — Stage 6 throws away the result of its own confirming double read

**Severity:** High · **Area:** Pension · **Category:** AI pipeline / correctness
**Where:** `pipeline/extract.py:1775`, `pipeline/extract.py:1819`, `pipeline/report.py:192-194`

**What is wrong.** Stage 6 reads identifier pages twice precisely because a single misread digit invents a personnel-number mismatch, which is a HIGH flag. Both call sites discard the agreement:

```python
ext, _ = reader(image_for[page], schema_name=schema)      # :1775
data = future.result()[0].data                            # :1819
```

On disagreement the reader has already blanked the disputed fields, and the only record of why was in the discarded agreement. The report builds `disputed_reads` exclusively from stage 4's artefact, so for any page stage 6 reads that stage 4 did not — service statement, bank form, NDC, FRC, Annex-A, CNIC cards — a disagreement silently removes the figures and no one is told. The H1 decision ("the report raises it for a person to read") is not honoured on those pages.

**Suggested fix.** Record each stage 6 agreement into the result and have the disputed-reads reader consume it.

## H-04 — An OCR outage deletes documents from the case and raises MISSING against the department  **[FIXED]**

**Severity:** High · **Area:** Pension · **Category:** AI pipeline / error handling
**Where:** `pipeline/extract.py:797-808`, `pipeline/run.py:285-286`

**What is wrong.** `page_ocr_text` converts any OCR failure into `""`. Not caching that is correct and deliberate; returning it to callers that cannot tell it from a genuinely blank page is not. `documents_named_by_their_own_heading` — the function that exists to stop the checklist reporting a filed document as missing — consumes it with no guard and runs outside any error handling. With OCR down, no document is identified by its printed heading, those documents never enter `documents.json`, and the checklist reports them MISSING with no error recorded anywhere.

**Reproduce.** Point the OCR endpoint at a closed port and run a bundle containing a page headed "LIST OF FAMILY MEMBERS". The checklist reports it missing; the run state is `done`; no flag is raised.

**Suggested fix.** Return a sentinel that distinguishes "failed" from "empty", and record the failure as a run gap so the unreadable-document check fires.

## H-05 — One flaky vision read can accuse a department of filing unattested copies  **[FIXED]**

**Severity:** High · **Area:** Pension · **Category:** AI pipeline / correctness
**Where:** `pipeline/extract.py:1639-1642`, `pipeline/report.py:744-756`, `rules/flags.py:1950-1966`

**What is wrong.** The design is explicit that the vision model's `attested` answer flips between runs and on its own cannot accuse a department, so a second reader confirms it. That second reader's failure is swallowed per page (`except Exception: continue`), and the report then leaves the single read standing when no second opinion exists. If OCR is down for the whole run the correction block is skipped entirely, so every page the vision model called unattested becomes ATTEST-MISSING owned by the department.

**Suggested fix.** When no second reading exists, set `attested` to unknown rather than leaving the single read in force, and record the second reader's failure as an unreadable finding.

## H-06 — A queued verification has no deadline and can hold a slot indefinitely  **[PARTLY FIXED]**

**Severity:** High · **Area:** Pension · **Category:** Reliability / concurrency
**Where:** `api/runs.py:120-122`, `api/runs.py:783-794`, `api/case_runs.py:465-469`

**What is wrong.** The watchdog exempts queued runs (`if run.state != "running" ... return False`), and the reconciler skips anything queued or running. A queued run therefore has no time bound at all and the case stays in AI_CHECKING with no grace period. The socket timeout on model calls is per read, not a total deadline, so a model server that accepts the connection and trickles bytes never times out. With the concurrency limit at 2, two such hangs stop every verification in the office with no visible failure.

**Corroborating evidence — a failing test.** `tests/test_run_concurrency.py` asserts the documented guarantee that runs past the limit wait their turn and then run. It fails on this box:

```
AssertionError: Lists differ:
  ['done', 'done', 'queued', 'queued', 'queued'] != ['done', 'done', 'done', 'done', 'done']
```

Three of five runs never started after the slots were freed. This reproduces on `main` (`d99968e`) as well as on the current branch, so it is pre-existing and not introduced by the read-cache work.

**Suggested fix.** Stamp a queued-at time and extend the deadline check to cover it; add a watchdog that releases a slot whose run has passed its deadline; give each stage an absolute deadline rather than relying on the socket timeout.


**Partly fixed (13 Oct 2026).** The cause of the slot loss seen on this box was M-03: the timing
recorder raised between acquiring a slot and the `try/finally` that returns it, so the run died
holding it. With that guarded, `tests/test_run_concurrency.py` passes here — the five runs that
stuck at `['done', 'done', 'queued', 'queued', 'queued']` now all complete.

**Still open:** a queued run still has no deadline of its own, and the model calls still have a
per-read socket timeout rather than an absolute one. A model server that accepts the connection
and trickles bytes can still hold a slot for as long as it keeps trickling. The queued-at stamp,
the watchdog over it and the per-stage deadline are not written.

## H-07 — Signing out stops working about five hours before the token expires  **[FIXED]**

**Severity:** High · **Area:** both · **Category:** Security / database
**Where:** `api/v2.py:230`, `api/v2.py:235`, `api/db.py:141-142`

**What is wrong.** Logout writes the revoked token's expiry as a **UTC** wall-clock string, then sweeps the table against `db.now()`, which is **naive local** time (UTC+5):

```python
expires = datetime.fromtimestamp(int(claims.get("exp", 0)), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
...
conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (db.now(),))
```

A 12-hour token revoked at 11:26 local carries an expiry stamp 7 hours later rather than 12. The sweep then deletes the revocation row five hours early, the `jti` check finds nothing, and a signed-out session works again. The shared `ag.reviewer` desk login is exactly the case the revocation table was added to handle.

**Suggested fix.** Store the expiry in the same clock as `db.now()`, or compare the sweep against UTC. The durable fix is `timestamptz` columns.

## H-08 — `case_runs.run_id` has no unique constraint, no index and no deterministic ordering  **[FIXED]**

**Severity:** High · **Area:** both · **Category:** Database
**Where:** `api/migrations/0001_init.sql:82-83`, `api/v2.py:1565-1566`, `api/v2.py:688`

**What is wrong.** The table carries only `(case_id, started_at)` and `(state)` indexes — confirmed by grepping every migration, SQLite and PostgreSQL. Nothing prevents two rows sharing a `run_id`. Seven call sites nevertheless treat it as a key with `.fetchone()` and no `ORDER BY`, including the one that decides whether an approval demands a written justification:

```python
latest = conn.execute("SELECT * FROM case_runs WHERE run_id = ?", (run_id or "",)).fetchone()
against = latest is None or (latest["verdict"] or "") != "FORWARD" or (latest["high_flags"] or 0) > 0
```

Which row comes back is arbitrary, so the approval gate is non-deterministic. `_case_dict` selects the latest run with `ORDER BY started_at DESC LIMIT 1` and no tiebreaker. Every artefact route also does a sequential scan on this column.

**Suggested fix.** De-duplicate, add `CREATE UNIQUE INDEX case_runs_case_run ON case_runs(case_id, run_id)`, and give every `LIMIT 1` a deterministic tiebreaker such as `ORDER BY started_at DESC, id DESC`.


**Fixed (13 Oct 2026),** except the de-duplication. Migration `0017_hot_path_indexes.sql` adds
`case_runs_run` on `case_runs(run_id)`, and all six queries on that column take
`ORDER BY started_at DESC, submission_no DESC, id DESC LIMIT 1` — the approval gate among them, so whether an
approval must carry a written justification is decided the same way every time. `_case_dict`'s latest-run query
has the same order.

`started_at` was written at second precision and `id` is a uuid4, so ordering on those two alone was
deterministic but *arbitrary*: a resubmission verified within a second of the run before it showed the
previous run as the case's latest. `tests/test_api_v2.py` caught it intermittently. `case_runs.started_at` is
now stamped to the microsecond (`db.stamp()`, which sorts after a second-precision stamp of the same second as
text, so the existing rows keep their places), and `submission_no` — the real sequence — breaks the tie for the
rows already written.

**Not done, deliberately:** the index is *not* unique. The live table already holds rows that share
a `run_id`, so a unique index would fail to build, and choosing which of two recorded runs is the
real one is the office's decision, not ours. Until they make it, the ordering decides it
consistently. `tests/test_audit_fixes_13oct.py`.

## H-09 — Every case list issues three extra queries per case and has no pagination

**Severity:** High · **Area:** both · **Category:** Performance / database
**Where:** `api/v2.py:751-752`, `api/v2.py:688-699`, `portals/src/shared/data/inventory.ts:46`

**What is wrong.** The list query selects every row with no `LIMIT`, then `_case_dict` runs three more queries per row: the latest run, the latest event and a document count. That is 3N+1 queries per render. The register polls the inventory version every 3 seconds per open browser, and the version check itself runs three unbounded `COUNT(*)`s. At 109 cases this is roughly 330 round trips per list render and it grows linearly with the caseload. There is also no index on `cases.updated_at`, which is the sort column.

**Suggested fix.** Fetch the three aggregates set-based, keyed by `case_id IN (…)`; add an index on `updated_at`; paginate the list; derive the version token from maxima rather than counts.

## H-10 — "Awaiting decision" is defined four different ways on the same screen

**Severity:** High · **Area:** both · **Category:** Data consistency / UI
**Where:** `portals/src/shared/PortalShell.tsx:43`, `portals/src/shared/screens/CaseRegister.tsx:55`, `api/workflow.py:69`, `api/v2.py:516`

**What is wrong.** Four places count the same words over different status sets:

| Shown as | Statuses counted |
|---|---|
| KPI tile above the table | FORWARDED, AI_FAILED, UNDER_REVIEW (3) |
| Status chip on the same screen | FORWARDED, AI_CHECKING, AI_FAILED, UNDER_REVIEW (4) |
| Sidebar badge (server `AG_HOLDS`) | FORWARDED, AI_CHECKING, AI_FAILED, UNDER_REVIEW (4) |
| Department caseload chart (`/stats`) | FORWARDED, UNDER_REVIEW (2) |

The tile omits AI_CHECKING; the chart omits both AI_CHECKING and AI_FAILED. So the tile, the sidebar badge and the chart can show three different numbers for one label, and pressing the chip lists more cases than the tile counted.

**Current live state.** All four agree **today** (14 each for Pension) only because no case is in AI_CHECKING or AI_FAILED right now. The divergence appears exactly when a verification is running or has failed — which is when an officer is most likely to be watching the screen.

**Suggested fix.** One exported status-group table, ideally served from `workflow.AG_HOLDS`, consumed by the shell, the register, the sidebar and `/stats`.

## H-11 — Re-verifying a case leaves the analysis screen showing the previous run

**Severity:** High · **Area:** both · **Category:** UI / correctness
**Where:** `portals/src/shared/screens/CaseDetail.tsx:333`, `portals/src/shared/screens/AnalysisLive.tsx:57,77-84`

**What is wrong.** The analysis component takes the run id as a prop with no React `key`, and never clears its event list when the run id changes:

```tsx
{verifying && run && <AnalysisLive runId={run.run_id} onDone={analysisDone} />}
```

When the screen switches to a new run, the new run's events are dropped as duplicates of the old run's sequence numbers, and the start time stays pinned to the old run. The progress bar does not restart and the technical log keeps showing the previous run's lines.

**Reproduce.** Open a case under verification and leave the findings tab open; have a second officer press "Verify the case again". Within four seconds the poll swaps the run id and the screen is wrong.

**Suggested fix.** Add `key={run.run_id}`, and reset the events, start time and page in an effect on the run id.

## H-12 — The progress bar's "resume where it really is" is a 2.5-second race

**Severity:** High · **Area:** both · **Category:** UI
**Where:** `portals/src/shared/screens/AnalysisLive.tsx:65,155-161`

**What is wrong.** On mount the bar may snap to the true position, but only inside a 2.5-second wall-clock window **and** only once events have arrived:

```tsx
if (target - v > 0.01 && Date.now() - mountedAt.current < 2500 && hasEvents) return target
return nextShown(v, target, finished)
```

Events cannot arrive until the media token resolves and the event stream connects and replays. On a loaded box that routinely exceeds 2.5 seconds. Past the window the only way forward is capped at 3% per second, so a refresh at 90% climbs from 0 and takes about 30 seconds to catch up. That is the reported "progress resets to 0", arriving slowly instead of instantly.

**Suggested fix.** Drop the time window and snap to the target on the first render where events exist, guarded by a "have we snapped" flag.

## H-13 — GP Fund: QR verification has never run, and it reports the opposite of the truth

**Severity:** High · **Area:** GP Fund · **Category:** AI pipeline / correctness
**Where:** `GP/backend/gpf/api.py:106`, `GP/backend/gpf/reading/barcodes.py:35-39`, `GP/backend/gpf/rules_common.py:237-257`

**What is wrong.** The reading pipeline is wired to the null decoder, which returns nothing, and the real decoder is never instantiated anywhere:

```python
reading_pipeline = ReadingPipeline(model_client, NullBarcodeDecoder())
```

`zxingcpp` is not installed in the runtime environment. The QR check never fires, and worse, the sanction rule then states a fact that is false: the officer is told the department's sanction *"carries no QR code"* when the page may well carry one.

**Suggested fix.** Install the decoder and wire it. Until then make the rule return a verification task saying QR decoding is unavailable on this build, never a factual claim about the page.

## H-14 — GP Fund: a Dealing Assistant can record an Accounts Officer's verification

**Severity:** High · **Area:** GP Fund · **Category:** Authorisation
**Where:** `GP/backend/gpf/service.py:275-276`, `GP/backend/gpf/service.py:291-292`, `GP/backend/gpf/engine.py:155-156`

**What is wrong.** The dedicated verify route checks the band (`may("verify", …)`, level 2 or above). The cure route performs the same action but checks `may("upload", …)`, which returns `True` for every band:

```python
if not may("upload", None, officer):          # engine.py:155-156 -> always True
    raise ServiceError("Not permitted to upload against this case.", 403)
...
elif kind == "verify":
    self._apply_verification(s, cure["vid"], bool(values.get("ok", True)), ...)
```

`ok` defaults to `True`. Many items carry `cure.kind == "verify"`, including the DOA signature check, the thumb impression and the death-claim check. The route is reachable through the portal by any AG-side role, and a Senior Auditor maps to band `da`, level 1. No test covers this path.

**Suggested fix.** Gate each branch of `cure` by the permission its own action needs.

## H-15 — GP Fund: a QR cure defaults to "it matches", and any band may send it

**Severity:** High · **Area:** GP Fund · **Category:** Authorisation / rules
**Where:** `GP/backend/gpf/service.py:326-337`, `GP/backend/gpf/rules_common.py:226-240`

**What is wrong.** The QR cure sets `decoded = True` and takes `agrees` with a default of `True`, producing a match with no disagreement recorded, which clears the sanction check. It runs under the same unguarded `may("upload")` as H-14, so level 1 with no written ground and no authority.

**Suggested fix.** Require `agrees` and the payload explicitly, and gate the cure at verification level with a recorded ground.

## H-16 — GP Fund: a rule that throws while deciding whether it applies disappears silently

**Severity:** High · **Area:** GP Fund · **Category:** Rules / error handling
**Where:** `GP/backend/gpf/engine.py:57-69`

**What is wrong.** The two halves of rule evaluation are asymmetric. A failure inside `run` becomes an honest verification task for a human; a failure inside `applies` is swallowed and the check vanishes with nothing logged and nothing shown:

```python
try:
    applies = bool(ch.applies(F))
except Exception:
    applies = False            # the check disappears
```

The `applies` predicates index facts freely, so a malformed fact object can make a hard stop disappear from a case that then reads clean.

**Suggested fix.** Treat an `applies` failure exactly as a `run` failure: emit a verification item naming the check, and log it.

## H-17 — GP Fund: a failed database write leaves the module and the database disagreeing

**Severity:** High · **Area:** GP Fund · **Category:** Persistence / reliability
**Where:** `GP/backend/gpf/service.py:417-430`, `GP/backend/gpf/store.py:254-263`, `api/dbcore.py:273-347`

**What is wrong.** The service mutates the in-memory case state first and persists afterwards, with no rollback. If the write raises, the caller gets a 500 but every later read keeps showing the disposal, the waiver and the verification — until the next restart, when it is gone. Nothing marks the case dirty and nothing retries.

Compounding it, the repository holds a single connection opened at import with no reconnect, so after a PostgreSQL restart every GP Fund write fails permanently until the module is restarted. The pension API opens a connection per request and is unaffected; the same tree already knows how to reconnect, in its own timing module.

**Suggested fix.** Write first and mutate memory only on success; reconnect on a dropped connection.

## H-18 — GP Fund: two rule engines exist for the same claims, and three fixes landed in only one

**Severity:** High · **Area:** GP Fund · **Category:** Duplication
**Where:** `GP/backend/gpf/` (deployed) versus `GP/gpfund/` (the office engine, 184 tests)

**What is wrong.** Both trees implement the same rule ids. The repository itself records the hazard: a test comment notes that the fix of 6 October went into `GP/gpfund/rules_advances.py`, *"which the served backend never imports"*. Three decided changes are present in the deployed engine and absent or stale in the other:

- **Only the Deputy AG may clear a hard stop** (decision G1). Enforced in `GP/backend/gpf/engine.py:146-152`; in `GP/gpfund/params.py:170-178` "settle in office" is level 2 regardless of severity, so an Accounts Officer can still clear a hard stop by recording it corrected.
- **Written grounds on every disposition** (G1). All four actions require them in `GP/backend/gpf/service.py:357-359`; `GP/gpfund/casefile.py:316-320` requires them only for a waiver.
- **A waiver lapses when its finding changes** (G2). `fingerprint` / `reconcile_dispositions` / `disposition_in_force` exist only in the deployed engine; grepping `GP/gpfund/` finds no implementation.

**Suggested fix.** Delete `GP/gpfund/` or make the deployed engine import it. Two engines that can reach two verdicts on one claim is the worst outcome for a system whose purpose is to be re-checkable years later.

## H-19 — GP Fund: a resubmission abandons every decision the officer made on the previous round

**Severity:** High · **Area:** GP Fund · **Category:** State machine
**Where:** `GP/backend/gpf/service.py:116`, `api/case_runs.py:478`, `api/rounds.py:151-178` versus `api/rounds.py:215-257`

**What is wrong.** Each GP submission opens a brand new module case id, and the portal link is overwritten to point at it. The pension path deliberately carries the officer's decisions forward — clearances of unchanged findings, checklist waivers, pages named — through `carry_decisions`. The GP twin records only page counts and request resolution; there is no carry at all. Every disposition, waiver, ground, authority and verification from the previous examination is abandoned, and the old examination becomes unreachable through the portal while remaining in the database.

**Evidence.** The sweep that read the database reported 61 GP cases of which **17** have no portal case pointing at them — abandoned examinations still holding claimant facts, unreachable and unauditable through the portal. (Read through the database; I could not re-run that query myself, see the note at the top.)

**Suggested fix.** Reuse one module case id per portal case and re-run the rules on the new facts, or port `carry_decisions` to the GP path.

---

# Medium

## M-01 — The admin "Cases" figure counts both products on a single-product screen, and never refreshes

**Severity:** Medium · **Area:** both · **Category:** Data consistency / UI
**Where:** `portals/src/shared/screens/admin/AdminHome.tsx:11,14,21`, `api/v2.py:2363-2371`

**What is wrong.** The overview endpoint counts every case with no product filter and no scope. The screen titles itself with the current product and puts a product-scoped donut directly beneath the figure. The effect has empty dependencies and no inventory tick, so a newly filed case never appears until the page is reloaded — which is one concrete form of "a new case missing from some tabs".

**Evidence (measured today).** `/api/v2/admin/overview` returns `cases = 109`, while the inventory returns 63 for Pension and 46 for GP Fund. On the screen headed "System overview — Pension" the figure reads 109.

**Suggested fix.** Take the total from the product-scoped inventory, and add the product and the inventory tick to the call.

## M-02 — Every legacy department row shares one key and one selection

**Severity:** Medium · **Area:** both · **Category:** UI
**Where:** `portals/src/shared/components/DeptSidebar.tsx:52,99`

**What is wrong.** Legacy and retired departments all render with the key `section:LEGACY` — duplicate React keys inside one list — and clicking any of them selects the whole legacy bucket. All legacy rows highlight at once and no individual legacy department can be filtered. They are visible and counted, so nothing is hidden; they are just unusable individually.

**Suggested fix.** Key and select by department code, under a "Legacy" group header.

## M-03 — The timing recorder breaks its own promise and can fail a completed run  **[FIXED]**

**Severity:** Medium · **Area:** Pension · **Category:** Reliability
**Where:** `pipeline/timing.py:71`, `pipeline/timing.py:98-120`, `api/runs.py:519`

**What is wrong.** `record()` documents itself as *"Silent on any database error"* and wraps the insert in a try. But the connection is obtained **outside** that try, and `db.target()` raises when no database is configured. The exception escapes `record`, escapes the `stage()` context manager's `finally`, and escapes `with timing.stage("run")`, which wraps an entire verification — so a run that completed successfully can be reported as failed. The GP Fund tree handles the identical case correctly, returning `None`.

**Evidence.** This is what breaks `tests/test_restart_mid_rerun.py` in a bare environment:
```
RuntimeError: no database: set PENSION_DATABASE_URL ... or PENSION_DB for a SQLite file
  pipeline/timing.py:71 in _connection
```
It reproduces on `main` as well as the current branch, so it is pre-existing.

**Suggested fix.** Move the connection call inside the try, or catch in `_connection` as the GP module does.


**Fixed (13 Oct 2026).** `db.target()` is inside the guard in `_connection`, which returns `None`
when there is no database, as the GP Fund tree already did. A completed run is no longer reported
failed, a stage's own exception still propagates, and the slot in `_execute_when_free` is returned
whatever the recorder does. `tests/test_audit_fixes_13oct.py`.

## M-04 — The tier move is a read-modify-write that the optimistic guard does not cover

**Severity:** Medium · **Area:** Pension · **Category:** Database / concurrency
**Where:** `api/workflow.py:289-310`, `api/workflow.py:382-398`

**What is wrong.** The new holding tier is computed from a case row read **before** the transaction opens, while the conditional update guards `status` only. Forwarding and returning between tiers leave the status unchanged, so for those two moves the guard is a no-op. Two officers acting at once — an Assistant AO forwarding while the AG desk returns, which `check_holder` exempts — both read the same holder, both pass, the last write wins, and both history rows are appended. The advisory lock serialises the writes but not the reads that decided them.

**Suggested fix.** Add the holder to the update predicate for the tier moves, or re-select the case for update inside the transaction and recompute there.

## M-05 — The run reconciler commits round records outside the transaction that records the run

**Severity:** Medium · **Area:** both · **Category:** Database / transactions
**Where:** `api/case_runs.py:478-518`

**What is wrong.** The GP case link and the round "finished" record are committed before the guarded update of the run row runs. When that guard finds another worker got there first, the loop continues, leaving a round marked finished against a run another worker is still recording — and the round tables are append-only with a "finished is final" trigger, so it cannot be corrected. Moving the case on is a third separate transaction, so a crash in between leaves the case in AI_CHECKING with its run recorded `done`. A compensating sweep exists, which means the inconsistency is designed around rather than prevented.

**Suggested fix.** Bring the three into one transaction.

## M-06 — The login lockout counter is a read-modify-write with no lock

**Severity:** Medium · **Area:** both · **Category:** Security / concurrency
**Where:** `api/auth.py:253-264`

**What is wrong.** The failure count is read, incremented in Python and written back with `DO UPDATE SET failures = excluded.failures`, which overwrites rather than increments, with no transaction and no row lock. Concurrent wrong-password attempts all read the same value and all write the same `n+1`, so parallel requests can hold the lockout off.

**Note.** The surrounding design is otherwise good: the lockout is keyed per account **and** per address specifically so that nobody can lock an account for everyone, and five failures gave a 429 in testing.

**Suggested fix.** Increment in SQL and compute the lockout from the returned value.

## M-07 — `audit_log` has no index for the two queries every sign-in runs  **[FIXED]**

**Severity:** Medium · **Area:** both · **Category:** Database / performance
**Where:** `api/v2.py:118-120`, `api/migrations/0001_init.sql:121`

**What is wrong.** Every sign-in runs two queries filtered on `action` and `entity_id`. The only index on the table is on `at`, confirmed across every migration. Both are therefore sequential scans. The table is append-only and never pruned, so this degrades for the life of the system.

**Suggested fix.** `CREATE INDEX audit_log_entity ON audit_log(entity_id, action, at DESC)`.


**Fixed (13 Oct 2026).** Migration `0017_hot_path_indexes.sql` adds `audit_log_entity` on
`audit_log(entity_id, action)`. The suggested trailing `at DESC` is left off: both queries reduce
to a `MAX(at)` and an `at > ?` over the handful of rows one account has for one action, which the
two leading columns already isolate. `tests/test_audit_fixes_13oct.py`.

## M-08 — Every write in both products serialises on one global advisory lock

**Severity:** Medium · **Area:** both · **Category:** Database / performance
**Where:** `api/db.py:87`, `api/db.py:253-255`

**What is wrong.** A single advisory lock id covers the whole database and is shared with the GP Fund process. Every transaction queues behind it, including bulk backfills that hold it for a whole sweep. Two departments filing unrelated cases block each other. It also buys less than it appears to, because the reads that decide a write happen before the lock is taken — which is precisely the gap in M-04.

**Suggested fix.** Key the lock on the case, or drop it and rely on the conditional updates that already carry the correctness for status moves.

## M-09 — Migration 0016 is not safe to re-run

**Severity:** Medium · **Area:** Pension · **Category:** Database / migrations
**Where:** `api/db.py:330-336`, `api/migrations/0016_reached_tier.sql:15`

**What is wrong.** The migration commits before its version row is recorded, so a crash in between re-applies the file on the next start. The later statements in 0016 are guarded (`WHERE COALESCE(reached_tier,'SENIOR_AUDITOR') = 'SENIOR_AUDITOR'`), but the first one is not:

```sql
UPDATE cases SET reached_tier = holder_tier WHERE holder_tier IS NOT NULL;
```

The file's own header states that nothing may lower the reached tier, *"so an officer keeps sight of a case they passed on or returned"*. Re-running this line does lower it, hiding cases from officers who had already seen them.

**Suggested fix.** Record the version inside the same transaction as the migration, take a lock around the migration loop, and add `AND reached_tier IS NULL` to that statement.

## M-10 — A case is committed before its validation finishes

**Severity:** Medium · **Area:** both · **Category:** Database / transactions
**Where:** `api/v2.py:1115-1139`

**What is wrong.** The case row, its documents and its creation event commit, and only then does the code refuse a filing with no documents (422). That leaves a committed draft case holding a consumed case number with an append-only creation event. Separately, the forward that makes "filing is submission" true is a second transaction, so a failure there leaves the case in DRAFT against the stated contract.

**Suggested fix.** Validate before opening the transaction, and perform the forward inside it.

## M-11 — Signing out is best-effort; a failed request leaves the session alive for 12 hours

**Severity:** Medium · **Area:** both · **Category:** Security / UI
**Where:** `portals/src/shared/auth/AuthProvider.tsx:87-89`

**What is wrong.** The sign-out request is fired and ignored, and the UI signs out regardless. On a shared office machine with a dropped link, the server-side token remains valid for its full 12 hours and the GP Fund frame cookie is not cleared — which is the stated reason the call exists.

**Suggested fix.** Await the request with a short timeout and one retry, or tell the officer the session could not be fully ended.

## M-12 — Findings controls are offered to an officer who does not hold the case  **[FIXED]**

**Severity:** Medium · **Area:** Pension · **Category:** UI / authorisation
**Where:** `portals/src/shared/screens/CaseDetail.tsx:184`

**What is wrong.** The screen decides whether to show Waive, Uphold and "Approve without this paper" from a **role** capability alone. The server additionally requires the holding tier and a status of UNDER_REVIEW. An Assistant AO looking at a case still held by the Senior Auditor is therefore offered the controls, and every press returns 409. The case payload already carries the allowed actions and the holder, and the action panel beside it uses them correctly.

**Note.** This is the harmless direction. No case was found where the UI hides an action the API would still allow.

**Suggested fix.** Drive the findings controls from the server's `allowed_actions`.

## M-13 — Four fetch failures are swallowed and leave a silently wrong screen

**Severity:** Medium · **Area:** both · **Category:** Error handling / UI
**Where:** `portals/src/shared/components/RoundsPanel.tsx:22`, `portals/src/shared/screens/CaseFindings.tsx:354`, `portals/src/shared/screens/admin/Users.tsx:57`, `portals/src/shared/screens/admin/Signatories.tsx:42`

**What is wrong.** Each catches and discards. The consequences differ in seriousness: a failed rounds fetch renders "no submission rounds" on the screen the AG uses to see what changed between rounds; a failed dispositions fetch makes already-recorded waivers vanish so the officer re-decides settled findings; and a failed departments fetch leaves the create-user department list empty while the form still defaults to a real department code, so an administrator can file a DDO against the wrong department with no warning.

**Suggested fix.** Render an error state; for the user form, block submission until the list loads.

## M-14 — The audit log silently shows only the newest 200 entries

**Severity:** Medium · **Area:** both · **Category:** UI
**Where:** `portals/src/shared/api/admin.ts:56-62`, `api/v2.py:2320`

**What is wrong.** The client sends no limit, the server defaults to 200, and the screen renders the array under a heading describing a permanent, unalterable record. Past 200 entries the page truncates with no indication and no paging.

**Suggested fix.** Add paging or a date filter, and state "showing the newest 200 of N".

## M-15 — The register re-renders every three seconds and nothing is paged server-side

**Severity:** Medium · **Area:** both · **Category:** Performance / UI
**Where:** `api/v2.py:751`, `portals/src/shared/data/inventory.ts:46`, `portals/src/shared/screens/CaseRegister.tsx`

**What is wrong.** The list endpoint returns every row, and the store replaces the array on each 3-second poll, so every derived value recomputes and up to 50 rows plus their timelines re-render. Page size caps limit it today, but the growth is unbounded. The history timeline and document list render every entry with no cap.

**Suggested fix.** Page server-side and memoise on a stable row identity.

## M-16 — GP Fund: the `/gpf/` read gate covers only the case routes

**Severity:** Medium · **Area:** GP Fund · **Category:** Authorisation
**Where:** `api/portal_server.py:71`, `api/v2.py:290`, `GP/backend/gpf/reading/jobs.py:43-55`

**What is wrong.** The per-case wing and tier check applies to `/api/cases*` only. Other reads pass through the frame with any AG-side cookie, including `/api/reading/jobs/{id}`, which returns the entire examination of a claim, bypassing the ordinary visibility check. Job ids are 40 bits of randomness and the portal carries one as the run id, so this needs a known id rather than a guess.

**Suggested fix.** Extend the gate to the reading routes: resolve the job's case and apply the same visibility rule.

## M-17 — GP Fund: an unmapped role silently receives the Accounts Officer band

**Severity:** Medium · **Area:** GP Fund · **Category:** Authorisation
**Where:** `api/gpf_bridge.py:47-48`, used at `api/v2.py:256,1769,1804,1871`

**What is wrong.** The role-to-band map is read with a default: `OFFICER_FOR_ROLE.get(user.role, "ao")`. A role absent from the map becomes band `ao` at level 2, which may pass a claim for payment. Today the write routes exclude the only unmapped role, so it is latent rather than live. The map also contains a `DEPT_OFFICER` entry that is unreachable and should not exist in a map whose default grants powers.

**Suggested fix.** Index the map directly and refuse on a miss; drop the dead entry.

## M-18 — GP Fund: nothing prevents a second, contradictory disposal

**Severity:** Medium · **Area:** GP Fund · **Category:** State machine
**Where:** `GP/backend/gpf/service.py:406-432`, `api/case_runs.py:552-556`, `api/v2.py:1731-1741`

**What is wrong.** Disposal checks the available options but never consults whether the case has already been disposed. "Passed for payment", then "returned", then "passed for payment" is accepted, each writing a new disposal. The portal gate that was meant to close the window requires the case to be UNDER_REVIEW, but nothing moves a GP case out of UNDER_REVIEW on a disposal: the function that would do it has been a stub returning `None` since 9 October.

**Suggested fix.** Refuse a disposal when one is already recorded, unless it is an explicit, audited revision with a reason.

## M-19 — GP Fund: two of the five disposals are unrecognised, so a held claim reads as clean

**Severity:** Medium · **Area:** GP Fund · **Category:** Bridge logic
**Where:** `api/gpf_bridge.py:270-275`

**What is wrong.** The bridge recognises only "passed" and "returned". "Held pending verification" and "referred to the DAG (Funds)" fall through to the clean calculation, so a claim an officer deliberately held with nothing else open is reported clean, and the history line reads that every required document is present with no finding. Separately, once a disposal starts with "passed", a later upload that raises a new hard stop still yields clean.

**Note.** Nothing auto-approves on the back of this, because the outcome is fixed; the damage is a misleading verdict and history line.

**Suggested fix.** Map all five disposals explicitly, and let "passed" only confirm an already-clean position, never override it.

## M-20 — GP Fund: `mode: "vllm"` is reported whether or not any model answers, and a role can bind to the wrong model

**Severity:** Medium · **Area:** GP Fund · **Category:** Observability / pipeline
**Where:** `GP/backend/gpf/clients/model_client.py:152-154`, `GP/backend/gpf/clients/model_client.py:381-389`

**What is wrong.** The health check hard-codes `{"ok": True, "mode": "vllm"}` after swallowing per-endpoint errors, so the field cannot distinguish a healthy module from a dead one. That matters here because of the known model-boot race after a reboot. Worse, role discovery falls back rather than failing: `vision = vision or reason or catalog[0]`. With the vision server down at start-up, pages are classified and extracted by whatever model answers first while the module still reports it as the vision model. Discovery runs once at import and is never redone. Nothing records which model read a case, so a mis-read case is indistinguishable afterwards.

**On stub mode specifically:** a stub result **cannot** masquerade as a real one. The stub client raises and both routes map that to 503. The unsafe path is the mis-bound real client above.

**Suggested fix.** Report `ok` only when the role endpoints answer; refuse to bind a role to a model that does not match it; re-discover on failure; stamp the client and model onto the facts.

## M-21 — GP Fund: an OCR-derived rupee amount is injected just above the confidence gate

**Severity:** Medium · **Area:** GP Fund · **Category:** AI pipeline
**Where:** `GP/backend/gpf/clients/model_client.py:287-296`

**What is wrong.** A balance parsed by regex from OCR text is written in with a hard-coded confidence of 0.97, where the financial threshold is 0.95 — a number chosen to clear the gate. It also silently overrides the vision read. The specification these thresholds implement says the model never guesses an amount.

**Suggested fix.** Carry the real confidence, and mark the field for a human when the two readers disagree.

## M-22 — GP Fund accepts an upload on magic bytes alone, where Pension also checks the extension

**Severity:** Medium · **Area:** GP Fund · **Category:** Upload safety / duplication
**Where:** `GP/backend/gpf/api.py:297-318` versus `api/v2.py:799-817`

**What is wrong.** Both products implement the same 6 October fix differently. Pension requires the magic bytes **and** a matching extension, with a comment recording the exact attack that prompted it: a PDF header in front of HTML, saved as `.html`, served back as a web page on the portal's own origin. GP checks the magic bytes only and relies on `nosniff` and a sandbox CSP instead. The impact is lower, but one hazard is now guarded two ways in one product and only one of them is maintained.

**Suggested fix.** One shared helper for both products.

## M-23 — The whole upload is read into memory, and the pre-read cap can be bypassed

**Severity:** Medium · **Area:** both · **Category:** Reliability
**Where:** `api/server.py:378-385`, `api/server.py:853-858`

**What is wrong.** The file is fully read before its size is checked. The only cap applied beforehand is a Content-Length middleware set to 520 MB, so a well-formed request still materialises up to 520 MB before the 256 MB refusal, and a chunked request carrying no Content-Length skips the middleware entirely, leaving the read unbounded. The case bundle builder does the same, reading every document into one in-memory archive.

**Suggested fix.** Stream with a running counter and abort at the cap, or enforce it in the proxy.

## M-24 — Resuming stage 6 from its checkpoint can duplicate findings, including recoveries

**Severity:** Medium · **Area:** Pension · **Category:** AI pipeline
**Where:** `pipeline/extract.py:1756-1766`, `pipeline/extract.py:1992-1999`

**What is wrong.** Which pages are already done is inferred from one optional output, the document dates. A document that was read successfully but has no date — CNIC cards, bank forms, NDCs — is not counted as done, so on resume it is read again and every fact it produced is appended a second time. The vision-side recovery entry has no de-duplication, so the officer can be shown the same HIGH "unrecorded recovery" twice.

**Suggested fix.** Track completed pages explicitly, and de-duplicate on write.

## M-25 — Stage 6 queues every job up front and abandons them on failure

**Severity:** Medium · **Area:** Pension · **Category:** AI pipeline / performance
**Where:** `pipeline/extract.py:1809-1816`, `pipeline/extract.py:2001-2002`

**What is wrong.** All identifier jobs are submitted at once, so the careful priority ordering governs only consumption. On abort the pool is shut down without cancelling pending futures, so a run already declared failed keeps driving the GPU through its whole backlog while the next run waits for a slot. It also defeats the deadline, since the run cannot stop until the queue drains.

**Suggested fix.** Shut down with cancellation, and submit in bounded waves.

## M-26 — A failed run record leaves an untracked pipeline thread on the GPU

**Severity:** Medium · **Area:** both · **Category:** Reliability
**Where:** `api/case_runs.py:124-166`

**What is wrong.** The background thread starts before the database row is written. If that write fails, the case moves to CHECK_FAILED and the officer is told the verification could not start, while the thread keeps running, holding a slot and writing artefacts that nothing tracks.

**Suggested fix.** Insert the row before starting the thread.

## M-27 — Shared mutable state passes stage 2's result between concurrent runs

**Severity:** Medium · **Area:** Pension · **Category:** AI pipeline / concurrency
**Where:** `extraction/identify.py:443`, `pipeline/run.py:152-153`

**What is wrong.** Stage 2's form text is handed back through an attribute on a module-level function object and read back two statements later. Two runs execute concurrently by default, so if the second finishes between the first's write and its read, one case stamps another case's prescribed-form text into its own identities. That text drives the checklist column, the claimant name and the pay scale. The window is two statements, so this is unlikely to have fired, but there is no guard at all.

**Suggested fix.** Return the value as a tuple.

## M-28 — Browser arithmetic on timestamps that carry no timezone

**Severity:** Medium · **Area:** both · **Category:** Correctness
**Where:** `api/db.py:141-142`, `portals/src/shared/screens/AnalysisLive.tsx:72,81`, `portals/src/shared/screens/CaseRegister.tsx:25,65-67`

**What is wrong.** The server writes naive local timestamps with no offset and no `Z`. The browser parses them as browser-local. On a workstation in a different timezone the elapsed time is wrong by the offset: the progress bar either stalls and walks backwards or jumps to the top of its stage, and the SLA pills shift by a day at the boundary. It works today only because every clock involved is the same one.

**Suggested fix.** Serialise with an offset, or parse as UTC through one shared helper.

---

# Low

- **L-01 — `/api/v2/portals` is the one route in the v2 router with no authentication.** `api/v2.py:356`. Returns every department's name, code, slug, port and theme. Verified: 200 with no token. `/api/gpu` and `/api/variants` are likewise open by design and return live GPU figures and the checklist taxonomy. Add the ordinary dependency; the portal fetches it after sign-in anyway.
- **L-02 — `/api/health` returns the raw database exception text outside production.** `api/health.py:119`. A connection failure message carries host, port, database and user. Even healthy it discloses the engine, free disk and which model servers are up. Mask it unconditionally and keep the detail behind an admin role.
- **L-03 — A full session token is still accepted on the query string for GET.** `api/auth.py:386-409`, `api/server.py:877-880`. Mitigations are real and deliberate (no-referrer, no-store, access logging off, a 15-minute media-scoped token exists, writes refuse it), and the media token is correctly scope-checked — a media token used as a bearer on ordinary endpoints returned 401 in testing. Residual risk only: accept only the media scope on the query string.
- **L-04 — The portal answers 200 with its application shell for every unknown path.** Verified: `/credentials/credentials.csv` returns the shell, not a file. Harmless, but it makes a path probe look like a hit; return 404 for non-routes.
- **L-05 — CORRECTED, 13 Oct 2026.** The GP Fund backend suite *can* be run: `pytest` lives in a dedicated virtual environment at `~/.cache/gpf-test-venv`, not in the services' one, which is why the first sweep missed it. Run it with `~/.cache/gpf-test-venv/bin/pytest` from `GP/backend`. It passes, 112 tests. Worth recording in the deployment notes so the next person does not conclude the suite is unrunnable.
- **L-06 — Dead code and stale references in the portal.** The idle-timeout machinery in `AuthProvider.tsx:138-167` and its dialog are unreachable because `IDLE_MINUTES` is 0; `rememberNext`/`takeNext` write a value nothing reads, and `auth/session.ts:82` still documents a behaviour the code deliberately does not implement (see "Checked and found sound"); `router/hash.ts` exports two unused helpers; a block of CSS for an analysis screen that no longer exists.
- **L-07 — `productRoute` reads product slugs off the object prototype.** `portals/src/shared/PortalShell.tsx:79`. `#/__proto__` or `#/constructor` yields a truthy inherited value and the screen shows a 422 banner instead of redirecting home. Use a null-prototype map or an explicit comparison.
- **L-08 — "Undo" on a named page has no in-flight guard.** `portals/src/shared/components/ChecklistPanel.tsx:141-142`. A double-click writes two entries to the append-only action log. Every other critical action is guarded, several with an idempotency key.
- **L-09 — Statistics never load while the tab is hidden on first mount.** `portals/src/shared/screens/Dashboard.tsx:31`. There is no visibility listener, unlike the inventory store, so a dashboard opened in a background tab shows a skeleton until the 60-second timer happens to fire while visible.
- **L-10 — A side effect inside a state updater in the scan viewer.** `portals/src/shared/scan/ScanViewer.tsx:82` calls `setBack` inside the `setFront` updater, which React's strict mode double-invokes. Idempotent today, but it is the class of impurity that produces exactly the reported animation glitches.
- **L-11 — Unreferenced write routes left live on the unauthenticated GP surface.** `GP/backend/gpf/api.py:219,520,534,602`. Three are write surfaces with no caller anywhere. Combined with C-04 they are free attack surface.
- **L-12 — Orphan rows are possible on the round tables.** The actor columns carry no foreign key, and the function that reassigns a retired user's work covers cases, documents and runs but not the round tables. The database sweep found 2 such orphans.
- **L-13 — Status-like columns added after the first migration have no CHECK constraint.** `holder_tier`, `reached_tier`, `product`, `case_runs.state` and others are free strings. A value outside the three tiers would raise a `KeyError` and a 500 in `workflow.TIER_RANK`, and nothing in the database prevents one.
- **L-14 — The username uniqueness check sits outside its transaction.** `api/v2.py:2221-2228`. The unique constraint protects the data, so the race yields a 500 rather than the intended 409.
- **L-15 — A GP Fund database outage reads as "no specimen on file".** `GP/backend/gpf/signatories.py:51-56`. Any exception returns "none", whose message becomes an audit finding against the department.
- **L-16 — Fetching a GP Fund page image writes on a GET.** `api/v2.py:1913-1914` renders every document with `pdftoppm` on a cache miss, unbounded, on a read path.
- **L-17 — The GP Fund frame has a fixed minimum height of 1200 px.** `portals/src/shared/styles/portals.css:613` overrides the height the module reports, so a short page always occupies 1200 px, and the framed content is not responsive at phone width.

---

# Tests, type checks, linting and the production build

| Check | Result |
|---|---|
| Portal `tsc --noEmit` | **Pass**, no errors |
| Portal `eslint src` | **Pass**, no errors, no warnings |
| Portal `vitest run` | **Pass** |
| Portal production build | **Pass**, built to a scratch directory; the emitted bundle hash matches the one the live portal serves, so `dist` is current with source |
| GP Fund engine (`GP/gpfund/tests`) | **Pass** — 184 tests |
| Pension suite (`tests/`) | **1081 tests: 1 error, 1 failure**, 5 skipped, 1 expected failure, 454 s |
| GP Fund backend (`GP/backend`, pytest) | **Pass** — 112 tests, run with `~/.cache/gpf-test-venv/bin/pytest` (corrected 13 Oct, see L-05) |

Both pension failures were re-run against a clean export of `main` (`d99968e`) and **both reproduce there**, so neither was introduced by the current branch:

- `tests/test_restart_mid_rerun.py` errors with `RuntimeError: no database` raised from `pipeline/timing.py:71` — see M-03.
- `tests/test_run_concurrency.py` fails with three of five runs stuck `queued` after their slots were freed — see H-06.

---

# Checked and found sound

These were tested and are working. They are listed so they are not re-audited, and because three of them were raised as suspected defects during this audit and then disproved.

- **Cross-department access (IDOR): no holes found.** As the Agriculture DDO, seventeen read endpoints were called against a case belonging to another department — the case, its rounds, its GP view, and the report, status, events, bundle, dispositions and checklist actions of its run, by both the case-scoped and the run-only route. **All seventeen returned 403.** Every case-keyed route funnels through one helper into one visibility rule, and sub-resources are additionally bound to their parent.
- **Privilege escalation: none found.** The DDO was refused on approve, reject, return, override, request-docs, check, take-up, forward-tier and return-tier, and on every admin endpoint including user creation, disable, reset-password and role change. Listing, stats and inventory are correctly scoped: the DDO sees 33 cases, all its own, where the AG desk sees 109.
- **Tier visibility is correct, and a suspected bug here was disproved.** The AO and Assistant AO appeared to see cases still held by the Senior Auditor. Inspection showed **every** such row is a GP Fund case, and the tier gate is pension-only by design. Of the pension cases, the AO sees only those that have reached the AO. Senior Auditor 33, Assistant AO 22, AO 22 in Pension-I, which matches the rule.
- **Injection and error leakage: none found.** SQL metacharacters, path traversal, an over-long id and a dropped-table string in a filter all returned clean 404 or 422 answers quoting an allow-list. No traceback, no SQL, no file path appeared in any response.
- **Login rate limiting works.** Five wrong passwords produced 429, and the lock is keyed per account **and** per address specifically so nobody can lock an account for everyone.
- **JWT handling is sound.** HS256 with the algorithm pinned on every decode, no `verify=False`, expiry always set, 12-hour session, 2-hour frame, 15-minute media token, bound to the account's token version and to a session id, with revocation on sign-out and a scope check that blocks confusion between token types. The media token was tested as a bearer on four ordinary endpoints and refused each time. Production refuses to start without a strong secret. The one defect in this area is the sweep clock, H-07.
- **Document serving is hardened.** A fixed media-type allow-list that excludes anything a browser would execute, `nosniff`, a sandbox CSP, and the document bound to its case in the query.
- **The inventory is genuinely single-source.** The project's own consistency checker passes: `python3 -m api.check_inventory` → `OK: 8 users x 2 products compared`. Rows, tiles and sidebar all derive from one scope function. The remaining inconsistencies are the naming problem in H-10 and the admin figure in M-01, not the inventory itself.
- **No cross-site scripting sinks in the application.** No `dangerouslySetInnerHTML`, `innerHTML`, `eval` or `new Function` anywhere in the portal source except one static SVG string in the offline demo driver.
- **No TODO or FIXME markers** in any tracked source file across both products, and almost no swallowed exceptions outside the ones named above, nearly all of which carry a written justification.
- **Deep links after sign-in are discarded deliberately, not by accident.** This was raised as a defect and disproved: `AuthProvider.tsx:121-126` carries the decision of 29 September 2026 that every sign-in opens the main page, because the address bar may still hold a case from a previous session. Only the dead helper and its stale docstring remain (L-06).
- **Filing is idempotent.** This was raised as a defect and disproved: the retry key is stored at `api/v2.py:1087`, in the route; the sweep had read the inner helper that ends without it.
- **The "Powered by TMC" footer is on every page.** Rendered on all branches of the portal shell, and carried in the brand panel on the two screens that bypass the shell, where it survives the stacked layout below 980 px.
- **Responsiveness at 1920, 1366, 768 and 390 px.** No blocking defect. The register's fixed columns shrink, then scroll inside their card, then become a two-column stack below 900 px; the sidebar collapses to a drawer. The only note is the GP Fund frame, L-17.
- **Resubmission on the pension side is correct.** Carryover matches documents by hash, remaps page numbers, drops any fact citing a withdrawn page, and re-runs every comparison stage. Each round is its own row with its own findings, and carried decisions are gated on the finding's fingerprint. The GP Fund side is the one that is wrong — H-19.
- **Bad input is handled.** Page, pixel, member and expansion caps are enforced from the PDF's own page table before rendering; archive extraction is traversal-safe; multi-frame images are measured before decode.
- **Duplicate runs for one case are guarded** by a compare-and-swap on the case status plus de-duplication by run id. The residual holes are H-06 and M-26, not a missing lock.

---

# Summary

## Counts by severity

| Severity | Count |
|---|---|
| Critical | 4 |
| High | 19 |
| Medium | 28 |
| Low | 17 |
| **Total** | **68** |

## Counts by category

Counted over the 51 Critical, High and Medium findings. The 17 Low items are listed as one-liners and are not categorised.

| Category | Count |
|---|---|
| AI pipeline, rules and their error handling | 12 |
| Security, authentication and authorisation | 11 |
| Database, transactions and concurrency | 8 |
| UI and data consistency on screen | 8 |
| Reliability and performance | 5 |
| State machine | 2 |
| Duplication between the two products | 2 |
| Configuration | 1 |
| Cross-product bridge logic | 1 |
| Timestamp correctness | 1 |

## Counts by product

Counted over the same 51 findings.

| Area | Count |
|---|---|
| Both products | 23 |
| GP Fund only | 15 |
| Pension only | 13 |

The GP Fund share is high relative to the size of that module. Most of it traces back to two root causes: the module has no authentication of its own (C-04), and its rule logic exists twice (H-18).

## The previously reported problems

| Reported problem | Verdict | Why |
|---|---|---|
| Page-scanning animation glitches; page refreshing mid-analysis and progress resetting to 0 | **Partly fixed** | The event stream replays its backlog on reconnect, so a refresh does recover while the API is up. But the "snap to the real position" only applies inside a 2.5-second window that a slow connection misses, after which the bar crawls up from 0 at 3% per second (H-12). A side effect inside a state updater in the scan viewer remains (L-10). If the API restarts mid-run the history is gone entirely. |
| Navigating between Pension and GP Fund sends the user back to the main page | **Fixed** | Product links route directly to each product's register and the shell redirects only on a genuinely unknown path. One cosmetic residual on prototype-named paths (L-07). |
| Case inventory not in sync; counts differing between sidebar, KPI cards, charts and tables | **Mostly fixed** | The single inventory source is real and the project's own checker passes across 8 users and both products. Two genuine inconsistencies remain: "Awaiting decision" means four different things (H-10), and the admin figure counts both products and never refreshes (M-01). |
| AG sidebar grouping by Pension-I to V; every department mapped, counts adding up | **Fixed, with a usability defect** | Every department is mapped and the mapping is enforced at import, which raises rather than silently bucketing. Nothing is hidden and the counts add up. But all legacy rows share one key and one selection, so they cannot be filtered individually (M-02). |
| Sign-in required on every fresh visit and on deep links; session expiry; logout | **Mostly fixed** | A refresh in the same tab keeps the session, and an expired token produces a clear message rather than a silent failure. Discarding the deep link after sign-in is a deliberate decision, not a defect. Sign-out is still best-effort and can leave a session alive for 12 hours (M-11). |

## Recommended order of work

1. **Close the network exposure.** Set `PENSION_ENV=production` on the box (H-01). That one change removes the credentials page (C-01), turns on the weak-password rules (C-02) and closes the public documentation endpoints. Then reset the accounts off `1234` and remove the `/start.html` route outright so the fix does not depend on an environment variable.
2. **Authenticate the GP Fund module** (C-04). Everything else in GP Fund assumes the loopback bind holds, and that is a deployment property rather than a control.
3. **Stop the pipeline reporting a clean case when it failed** (C-03), then the four findings where a failed or single read becomes an accusation against a department or a silently dropped check: H-02, H-04, H-05, H-03.
4. **Fix the four GP Fund controls that can be cleared by the wrong person or vanish on their own:** H-14, H-15, H-16, H-13.
5. **Take the two correctness-of-record items:** the revocation clock (H-07) and the non-deterministic approval gate (H-08).
6. **Deal with the duplication**, which is what makes the rest recur: delete or merge the second GP Fund rule engine (H-18) and port the carry-forward of officer decisions to the GP path (H-19).
7. **Then the reliability and performance group:** the queued-run deadline (H-06) with its failing test, the N+1 list and its missing indexes (H-09, M-07), and the transaction boundaries (M-04, M-05, M-10).
8. **Finally the UI set**, which is cheap and highly visible: one definition of "Awaiting decision" (H-10), the analysis screen's run key (H-11) and progress snap (H-12), and the admin count (M-01).

## Caveats on this audit

- No state-changing request was sent to a live case, so the status transitions themselves were verified by reading the code and the guards rather than by driving a case through the workflow end to end. A follow-up pass on a scratch database would be worth doing for the transition matrix specifically.
- Direct SQL against the live database was blocked by this environment. Figures attributed to database queries (the 17 orphaned GP examinations, the 2 orphaned round rows, the duplicate run rows) come from the sweep that had access, and are marked as such; everything else was verified by reading code or by calling the API.
- The GP Fund backend's 95 tests were not run (L-05).
