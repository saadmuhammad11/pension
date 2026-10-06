# Audit status — `fix/high-findings`

Reconciled status of every audit item, as of **6 October 2026** (evening). Statuses describe the
code on the branch `fix/high-findings` plus the data-handling work done on this box today. Nothing
on the branch is pushed, merged or deployed yet (see N1), so none of the FIXED rows is live until it is.

Severity and numbering follow the audit report of 6 October 2026: M = critical findings, H = high,
S/R/C/G/D/L = medium and low by area, N = new items raised while fixing. The last re-check against the
code ran all three suites: pension 777 OK, GP backend 83 passed, GP Fund engine OK.

**Totals.** Earlier audit (69 items): 25 fixed, 3 partly fixed, 15 need a business decision, 26 not
fixed. New items (11): 5 fixed, 1 needs a business decision, 5 not fixed.

## Real claimant data (M8 / N2 / N4 / N6)

- **Code and history: clean.** All 21 commits pass `deploy/check-release-pii.py`; none of the 128
  real values appears anywhere in local history. The local object store (1,145 blobs) was scanned
  blob by blob on 6 Oct: no hit.
- **GitHub: clean.** The repository was deleted and recreated on 6 Oct. `main` there is `f329438`;
  the pre-scrub commit `63185d3` returns "No commit found" from the GitHub API.
- **Local copies: removed.** On 6 Oct the leftover copies were shredded (`shred -u`, 306 MB): the
  scrub backup (`originals.tar`, `pre-scrub.bundle`), the `pension-1.0.0-rc1` tarball and its
  unpacked copy, two session scratchpads, the 9 Sep home-folder backup, the flags/OCR and e-diary
  archives, the two helpdesk dumps and three portal-database backups. A fresh release build then
  passed the CNIC check.
- **Still on this box, by design:** the trial system's own data (`artifacts/run-*`, `artifacts/cases`,
  `artifacts/portal.sqlite3`, `artifacts/golden`, `GP/backend/data`, `GP/agofficegpfund/_wip-*`, the
  root case PDFs, `SacnCases.rar`, `agofficegpfund (2).zip`). All of it is git-ignored, excluded by
  `deploy/build-release.sh`, owned by `tmc` (the user every service runs as) and set to owner-only
  access (700/600). The single-file demos (N6) and the Claude session transcripts (N11) are the two
  remaining copies that need handling.

## Status table

| # | Sev | Item | Status | Evidence / what remains |
|---|---|---|---|---|
| M1 | Critical | Auto-approval ignores the engine's verdict | **NEEDS BUSINESS DECISION** | `outcome()` still has no verdict check. Decision sheet item 1 |
| M2 | Critical | `CHANGE_ME`/short JWT secret accepted | **FIXED** | `2280c44`. `tests/test_production_hardening.py` F11 (4 tests, including the real process exiting with code 1) |
| M3 | Critical | Qualifying service loses a year at 6 months | **NEEDS BUSINESS DECISION** | Re-run today: still `29y 5m 30d`. Decision sheet item 2 |
| M4 | Critical | Every GP Fund scan read crashed (NameError) | **FIXED** | `b519e24`. `GP/backend/tests/test_scan_read_e2e.py` (failed before, passes after). The running GP module hasn't been restarted |
| M5 | Critical | TIFF/GIF image bomb runs the server out of memory | **FIXED** | `d3577df`. `tests/test_image_limits.py` (200-frame bomb refused; 133 MB peak) |
| M6 | Critical | LibreOffice fetches addresses / reads local files | **FIXED** | `5dcd43b`. `tests/test_office_conversion.py` (live listener receives no requests). Content checks; no sandbox is possible on this box |
| M7 | Critical | Model servers open to the network, no key, run from another developer's folder | **PARTLY FIXED** (stop-gap live 6 Oct 2026) | Files fixed in `957fcfb`; tests `tests/test_model_endpoints.py` and `GP/backend/tests/test_model_key.py`. **Live:** `deploy/lock-model-ports.sh` (`5e15060`) applied and persisted on the trial box (`/usr/local/sbin/lock-model-ports.sh`, `pension-model-ports.service`): 8011/8012/8093 answer on loopback (HTTP 200) and time out from a laptop. The lasting fix, `--host 127.0.0.1` plus an API key in `infra/*.service`, rolls out at deploy (checklist §8.1) |
| M8 | Critical | Real CNICs and names in code and history | **FIXED** (6 Oct 2026) | Code: `f329438`, plus `deploy/check-release-pii.py` (passes on all 21 commits and on every blob in the local object store). History rewritten; GitHub recreated clean, `63185d3` no longer served (N2). Local copies shredded (N4). Remaining copies: the demos (N6) and the session transcripts (N11) |
| H1 | High | Two reads of a page disagree, figures used anyway | **NEEDS BUSINESS DECISION** | The agreement result is stored but never read. Item 3 |
| H2 | High | Pay lines from several documents summed; §8.4 check never called | **NEEDS BUSINESS DECISION** | `reconcile_*` still has no callers. Item 4 |
| H3 | High | Form D-I dates not cross-checked; no 10-year minimum | **NEEDS BUSINESS DECISION** | Item 5 |
| H4 | High | Voluntary retirement at 59 paid as superannuation | **NEEDS BUSINESS DECISION** | Item 6 |
| H5 | High | Re-grant may apply 75% twice | **NEEDS BUSINESS DECISION** | Item 7 |
| H6 | High | Family relations misread; no eligibility checks | **NEEDS BUSINESS DECISION** | Item 8 |
| H7 | High | Zero pay base gives a Rs 0 pension | **NEEDS BUSINESS DECISION** | Re-run today: an empty pay list gives Rs 0 with "needs human" false. Item 9 |
| H8 | High | Waivers tied to finding numbers that change | **NEEDS BUSINESS DECISION** | Still keyed by `flag_id`. Item 10 |
| H9 | High | Re-verify race (old run's result applied) | **FIXED** | `ef18463`. `tests/test_reverify_race.py` (fails without the fix) |
| H10 | High | Waivers and approvals not on the audit trail | **FIXED** | `fab85f4`. `tests/test_clearance_audit.py`. Waivers carried into a resubmission are a policy question (item 11) |
| H11 | High | GP Fund actions on rejected or returned cases | **FIXED** | `a861ade`. `tests/test_gpf_actions_follow_status.py` |
| N1 | High | **New:** none of today's fixes is live | **NOT FIXED** | API and GP module started 5 Oct; portal bundle not rebuilt; branches not merged or pushed |
| N2 | High | **New:** GitHub still serves the pre-scrub commit | **FIXED** (6 Oct 2026) | Repository deleted and recreated. `git ls-remote origin main` = `f329438`; `gh api repos/…/commits/63185d3` → "No commit found for SHA" (HTTP 422) |
| N3 | High | **New:** HTML renamed `.doc`/`.rtf` and `.docx` linked images also made LibreOffice fetch | **FIXED** | `5dcd43b`. `tests/test_office_conversion.py` |
| S1 | Medium | Session tokens written to nginx's access log | **NOT FIXED** | No `log_format` change. No longer blocked: the `deploy/` edits are committed (N5) |
| S2 | Medium | Uploaded HTML/SVG opens on the portal's address | **FIXED** | `ae9ce8b`. `tests/test_documents_cannot_run.py` |
| S3 | Medium | GP Fund uploads served inline (`.html`/`.js`) | **FIXED** | `0afba15`. `GP/backend/tests/test_scan_types.py` |
| S4 | Medium | GP Fund cookie survives sign-out | **FIXED** | `dd2acef`. `tests/test_signout_clears_gpf.py`. Takes effect on the next portal rebuild |
| S5 | Medium | AI output reaches departments | **FIXED** | `fd0c172`. `tests/test_ddo_sees_no_ai_output.py` |
| R1 | Medium | Upload handlers block the server; whole upload in memory; files written under the DB lock | **FIXED** | `39d9437`. `tests/test_upload_streaming.py` (200 MB upload, 4.3 MB peak) |
| R2 | Medium | Size guard dead behind the proxy (A-15 regression); anonymous uploads parsed | **FIXED** | `6e2491b`. `tests/test_upload_early_refusals.py` |
| R3 | Medium | Zip page-cap bypass; `pdftoppm` has no timeout | **FIXED** | `b7e5aae`. `tests/test_pdf_limits.py` |
| R4 | Medium | One slow GP Fund status check fails the examination | **FIXED** | `2965d29`. `tests/test_gpf_poll_resilience.py` |
| R5 | Medium | Restart during re-verify approves on the old report | **FIXED** | `ad09087`. `tests/test_restart_mid_rerun.py` |
| R6 | Medium | Failed migration doesn't stop the server | **FIXED** | `2c1f512`. `tests/test_startup_failure.py` |
| R7 | Medium | No limit on runs reaching the GPU | **PARTLY FIXED** | Cap in `6d6679a`, `tests/test_run_concurrency.py`. Still no overall run deadline, and the in-memory run list grows without bound |
| R8 | Medium | No disk quota or cleanup of old runs | **NOT FIXED** | |
| C1 | Medium | No maker-checker; shared `ag.reviewer` account | **NEEDS BUSINESS DECISION** | `ADMIN` is still on both sides |
| C2 | Medium | Admin override's audit row written outside its transaction | **NOT FIXED** | |
| C3 | Medium | Old `/api` recompute can change the report behind an approved case | **NOT FIXED** | No status guard |
| G1 | Medium | Accounts Officer clears a hard stop with "correct" | **NEEDS BUSINESS DECISION** | Still allowed from level 2 (AO) |
| G2 | Medium | GP Fund waivers stay attached after the amount changes | **NOT FIXED** | |
| G3 | Medium | SAP trailing minus read as positive | **NOT FIXED** | `num("1,234.00-")` gives 1234 today |
| G4 | Medium | Unread advance balance means "no advance outstanding" | **NOT FIXED** | |
| G5 | Medium | Signature-authority register lost on restart | **NOT FIXED** | |
| G6 | Medium | One made-up officer per role; IT admin gets DAG powers | **NEEDS BUSINESS DECISION** | `"ADMIN": "dag"` unchanged |
| G7 | Medium | No locking on GP Fund case state | **NOT FIXED** | |
| D1 | Medium | Release files owned by uid 1000 | **NOT FIXED** | |
| D2 | Medium | PyJWT 2.13 advisories | **PARTLY FIXED** | Pinned to 2.15.0 in `8011f41` (HS256 with a string `sub`: compatible). 2.13.0 is still installed in the services' venv; install and restart are on the deploy checklist (§8.1) |
| D3 | Medium | `numpy`/`opencv`/`zxingcpp` missing from requirements | **NOT FIXED** | |
| N4 | Medium | **New:** local copies of real data remain | **FIXED** (6 Oct 2026) | 306 MB shredded: `artifacts/backup-pii-scrub-20261006/` (`originals.tar`, `pre-scrub.bundle`), `dist-release/pension-1.0.0-rc1.tgz`, two session scratchpads under `/tmp/claude-1000`, `~/pension_check-backup-2026-09-09.tgz`, `artifacts/backup-flags-ocr-20260925/`, `artifacts/archive-ediary-bridge-20260925/`, both `ediary-hesk-*.sql`, `backup-portal-db-2026092{5,9}/` and `-20260930/`. Re-check after: repo clean, `/tmp/claude-1000` clean, fresh release build passes the CNIC check; only the live trial data (above) is still flagged. Live data is git-ignored, excluded from the release, and set to 700/600 |
| N5 | Medium | **New:** uncommitted `deploy/` edits of unknown owner | **FIXED** (6 Oct 2026) | Owner found: the audit session of 6 Oct (13:18–13:21). Reviewed and all three kept, committed separately: nginx redirect `e5018b9`, PyJWT pin `8011f41`, firewall script `5e15060` |
| N6 | Medium | **New:** single-file demos contain real CNICs | **NOT FIXED** | `pension-portal.html`, `pension-portal rd new.html`, `demo/pension-demo.html` and `portals/dist-demo/` each embed real scans; the CNIC check finds 7 real numbers in each (28 hits). Untracked, git-ignored, never shipped; the scans can't be faked. **Do not share these files outside the team.** |
| L1 | Low | 2-digit years read as 20xx | **NOT FIXED** | Fails safe |
| L2 | Low | GP Fund cookie never gets `Secure` | **NOT FIXED** | |
| L3 | Low | nginx and the app send conflicting headers | **NOT FIXED** | |
| L4 | Low | Re-enabled trial account keeps its 1234 password | **NOT FIXED** | |
| L5 | Low | 3-second poll still fires after sign-out | **NOT FIXED** | |
| L6 | Low | Zip member name collisions | **NOT FIXED** | |
| L7 | Low | GP bridge doesn't escape upload filenames | **NOT FIXED** | |
| L8 | Low | GP tests write into the live data folder | **FIXED** | `b519e24` (`run.sh` unsets `GPF_DATA_DIR`); full GP suite run wrote 0 files. No unit test |
| L9 | Low | Admin password reset uses `window.prompt` | **NOT FIXED** | |
| L10 | Low | systemd/nginx hardening gaps | **NOT FIXED** | |
| L11 | Low | GP Fund sign-in check cached 30 s | **NOT FIXED** | |
| L12 | Low | Old API accepts the session token on the URL for writes | **NOT FIXED** | |
| N7 | Low | **New:** reranker/guard units still on `0.0.0.0` | **NOT FIXED** | Out of scope for item 7 |
| N8 | Low | **New:** new settings missing from `pension.env.example` | **NOT FIXED** | `PENSION_MAX_BUNDLE_PAGES`, `PENSION_MAX_CONCURRENT_RUNS`, `PENSION_PDF_TOOL_TIMEOUT`, `PENSION_GPF_JOB_DEADLINE_MIN` |
| N9 | Low | **New:** `docs/*.md` not tracked in git | **FIXED** (6 Oct 2026) | `docs/STATUS.md`, `docs/DEPLOYMENT.md` and `docs/pension-rules-decisions.md` tracked on `fix/high-findings`; `.gitignore` whitelists `docs/*.md` |
| N10 | Low | **New:** domain brief wrongly says day-counting is "immaterial" | **NEEDS BUSINESS DECISION** | Settled together with M3 |
| N11 | Low | **New:** Claude session transcripts hold real CNICs | **NOT FIXED** (deliberate) | `~/.claude/projects/-home-tmc-Desktop-pension/` (~2,060 hits in 50 transcripts, 293 MB) plus a few in neighbouring project folders. `~/.claude` set to owner-only (700/600) on 6 Oct. **Purge the transcripts after the fix work is complete**; they are the working history of the fixes until then |

## Action items

1. Merge and deploy the two branches (N1); until then, none of the FIXED rows is live.
2. At deploy: `pip install PyJWT==2.15.0` into the services' venv and restart them (D2); switch the model units to `--host 127.0.0.1` plus the API key (M7). Both are on the go-live checklist, `docs/DEPLOYMENT.md` §8.1.
3. Settle the business-decision items (decision sheet: `docs/pension-rules-decisions.md`).
4. When the fix work is complete, purge the session transcripts (N11) and decide what to do with the demos (N6).
