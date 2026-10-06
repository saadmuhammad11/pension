# GP Fund Pre-Audit — Backend + Web app

The production module for the Office of the Accountant General, Punjab: an
AI-assisted **pre-audit** for GP Fund claims. It reads a scanned case file,
extracts the facts, and runs a **deterministic rules engine** that maps every
defect to the office's standardised checklist/rejection codes — so the officer
disposes of the whole case in one instance.

```
scan ─► [READ: vision models] ─► facts ─► [RULES ENGINE: plain code] ─► results
                                   ▲                                        │
        SAP extract ───────────────┤                       observations · verification tasks
        uploaded document ─────────┘                       SAP items · satisfied checks
                                                                            │
                                                       officer disposes ─► issue pack
```

**Core principle (spec §0): the language model never decides anything — the
rules decide, from facts.** Everything under `gpf/` (except `gpf/clients/`) is
ordinary, deterministic, unit-tested code with **no model calls**. The models
and the SAP link plug in behind `gpf/clients/` without changing anything else.

## Run it

```bash
cd backend
./run.sh                                   # start;  also: stop | restart | status
```

Then open **http://localhost:8200/** — the full web app (intake → SAP extracts →
examination → cure-by-upload → DOA register → disposal → issue pack). One process
serves the API, the prototype assets and the UI.

There is no project-local virtualenv. `run.sh` runs on `/home/tmc/vllm_env`, the
same interpreter the AG Punjab pension portal next door uses — FastAPI, uvicorn and
python-multipart already live there. Nothing is ever installed into it from here.
Port 8200, not 8100: the pension portal's API holds 8100 on this machine and the two
are routinely up together. `PORT=... ./run.sh` overrides it.

CLI without the web layer:

```bash
/home/tmc/vllm_env/bin/python3 demo.py                 # list the eight corpus cases
/home/tmc/vllm_env/bin/python3 demo.py fp-death        # evaluate one case
/home/tmc/vllm_env/bin/python3 demo.py refundable --no-sap
```

The 62-test suite is pytest-based and `vllm_env` has no pytest, by the read-only rule
above. `./run.sh test` prints the throwaway-env recipe:

```bash
python3 -m venv /tmp/gpf-test && /tmp/gpf-test/bin/pip install -q -e ".[dev]"
/tmp/gpf-test/bin/python -m pytest
```

## Architecture

| Layer | Path | What it is |
|---|---|---|
| **Rules engine** | `gpf/engine.py` | `evaluate(facts) → results`, run diffing, versions, officer bands, `CaseState` |
| | `gpf/rules_common.py` · `rules_family.py` · `rules_custom.py` | the ~53 checks (circular A/B codes, R1–R15, custom anomalies) |
| | `gpf/doa.py` | Delegation-of-Authority register + signatory lookup |
| | `gpf/sap.py` | SAP extract parser + personnel-number identity gate |
| **Application service** | `gpf/service.py` | case lifecycle: intake, SAP upload, cure-by-upload, verify, dispositions, disposal gates, issue pack, DOA admin, audit |
| **Persistence** | `gpf/store.py` | `SqliteCaseRepository`: cases in the shared portal database (`../../artifacts/portal.sqlite3`, tables `gpf_cases`, `gpf_documents`, schema in `../../api/migrations/0005_gpf_cases.sql`) since 29 Sep 2026; `CaseRepository` (in-memory + JSON snapshots) for tests and stand-alone runs; `DocumentStore` (uploads by SHA-256, recorded in `gpf_documents`). Swap for Postgres behind the same interface |
| **Reading pipeline (§3)** | `gpf/reading/` | stages 1-5 (ingest → OCR → classify → extract → barcodes) + facts assembler; artefact taxonomy (§4.1) and per-artefact extraction schemas (§4.2) |
| **Clients (the seams)** | `gpf/clients/model_client.py` | `ModelClient`: `StubModelClient` / `ScriptedModelClient` / `VllmModelClient` (wired to vLLM's structured-output API) |
| | `gpf/clients/sap_connector.py` | `SapConnector`: `ManualUploadConnector` now / RFC + OData in phase 2 |
| **HTTP API** | `gpf/api.py` | FastAPI: full case lifecycle, DOA admin, rules-in-force; serves the SPA + corpus assets |
| **Frontend** | `web/` | buildless vanilla-ES-module SPA (no CDN, air-gap friendly) |
| **Fixtures** | `gpf/fixtures/cases.json` | the eight corpus cases as facts objects (the reading↔rules contract) |
| **Tests** | `tests/` | engine parity (spec §16.2), determinism, model-swap invariance, SAP, service, API |

## The skin is the pension portal's

`web/styles.css` carries the AI Pension Portal's palette, type scale and primitives,
transcribed from `portal/src/tokens.css` rather than re-derived — the same green
(`#1B4332`), gold, sage and severity ramp, the same Segoe UI stack and 11→30px type steps,
the same 14px cards, focus rings and print rules. The header uses the same drawn Punjab
crest and gold `PILOT` chip. The AG office has approved that skin, and the two systems sit
on the same desk: an officer moving from a pension case to a GP Fund case should not feel
they have changed building.

Two things are GP Fund's own, because the portal has no equivalent:

- **Verify** and **Awaiting SAP** are not severities — they are "someone must look" and
  "we are waiting on another system" — so they take hues outside the red/amber/green ramp
  (`--conf`, `--sap`), weighted to match so no row shouts louder than it should.
- A **zero count drains to grey** in the case status strip. What stays coloured is what
  actually needs the officer.

If the portal's tokens change, change them here too. They are a copy, not an import — the
portal is a Vite/React build and this is buildless ES modules served by FastAPI, so there is
nothing to share at runtime.

## Result status vocabulary (spec §4.4)

`ok` satisfied · `sub` satisfied by substitute · `hard` blocks (rejection form) ·
`adv` observation (advisory) · `conf` officer must verify (blocks payment) ·
`sap` awaiting SAP extract (section action) · `na` not applicable.

A case cannot pass for payment while any `hard`, `conf` or `sap` is open, or
while an observation is undisposed. A second return needs the DAG (Funds).

## What the tests guarantee (62 tests)

- **Engine parity** — per-check id→status for all 8 cases, with and without SAP,
  matches the prototype exactly and the headline counts in spec §16.2.
- **Determinism** & **model-swap invariance** (spec §0 rules 4–5).
- **SAP** — parsing, the identity gate (wrong personnel number rejected),
  cure-by-upload flips `sap` items to `ok`.
- **Service/API** — full lifecycle over HTTP, delegation authz (a Dealing
  Assistant cannot waive a hard stop), disposal gates, second-return escalation,
  document cure resolving a hard stop.

## The reading pipeline (build phase 6)

`gpf/reading/` turns scans into the facts object:

```
ingest ─► (OCR) ─► classify ─► extract ─► barcodes ─► ASSEMBLE ─► facts
  1          2          3          4          5
```

The model is used only in stages 3–4 (classify + extract) and only through
**schema-constrained** calls (`gpf/reading/schemas.py` builds the JSON Schema
handed to vLLM for guided decoding). Stage 5 (barcodes) is deterministic. Every
extracted field below its confidence threshold is flagged for a person — the
model never auto-accepts an account number, CNIC, date or amount (§0 rule 3).

It runs end-to-end **today** with a `ScriptedModelClient` (see
`tests/test_reading.py`, which reads a refundable case through the pipeline and
confirms the assembled facts pass the rules engine).

### Progress, because reading is slow

Stages 3 and 4 are one vision-model call per page each. Measured on the Spark with
`qwen3-vl-30b`, a page costs roughly 5–15s, so a thirteen-page file is well over a
minute. The endpoint used to hold the request open for all of it and the UI showed
nothing, which is indistinguishable from a hang.

So `ReadingPipeline.run()` takes an optional `on_progress(event)` callback — advisory,
never load-bearing, and covered by a test asserting the facts are identical with it and
without it. Over HTTP that becomes a job:

| | |
|---|---|
| `POST /api/cases/from-scans/start` | consumes the upload, starts the read on a worker thread, returns `202 {jobId}` |
| `GET  /api/reading/jobs/{jobId}` | `{state, stage, done, total, page, message, elapsed}`; `result` when done, `detail` + `statusCode` on failure |
| `POST /api/cases/from-scans` | unchanged — synchronous, for scripts and `eval_reading.py` |

Both paths call the same `_read_scans`, so they cannot drift into producing different
cases from the same scans. The registry (`gpf/reading/jobs.py`) is in-process and in-memory
with a 15-minute TTL: a job matters only while the page that started it is open. If this
ever needs to survive a restart or span workers it wants a real broker, not a bigger dict.

The UI polls at ~1s and draws a bar from `done/total` — pages actually finished, not a
timer pretending to be progress. A single page can hold that number still for fifteen
seconds, which is why the spinner, stage list and clock keep moving between ticks.

### Live model wiring (AG Punjab DGX Sparks)

The models run across the two Sparks exactly as the spec's §1 split intends, and
`VllmModelClient` uses one endpoint **per role**:

| Role | Model | Endpoint |
|---|---|---|
| Vision (classify + extract) | `qwen3-vl-30b-a3b-fp8` | `10.170.1.143:8011` |
| OCR | `paddleocr-vl-1.6` | `10.170.1.143:8012` |
| Embedding (citations) | `qwen3-embedding-4b` | `10.170.1.143:8093` |
| Reasoning (wording) | `qwen3.8-27b-fp8` | `10.170.0.240:8001` |

Launch wired to all four (roles are auto-discovered by `/v1/models`):

```bash
./run.sh                       # sets GPF_VLLM_URLS to the four endpoints
./run.sh status                # the resolved role board, before you open the UI
# or, by hand:
GPF_VLLM_URLS="http://10.170.1.143:8011,http://10.170.1.143:8012,http://10.170.1.143:8093,http://10.170.0.240:8001" \
  /home/tmc/vllm_env/bin/python3 -m uvicorn gpf.api:app --port 8200
```

`GET /api/model` shows the resolved roles and endpoint reachability. Then
`POST /api/cases/from-scans` (or the "Open from scanned pages" panel in the UI)
classifies each page, extracts fields, and opens the case. With no
`GPF_VLLM_URLS`/`GPF_VLLM_URL` set it uses the stub and `/from-scans` returns a
clear 503.

The SAP link swaps `ManualUploadConnector` → `SapRfcConnector` the same way
(phase 2, GPF-O19). Nothing above `gpf/clients/` and `gpf/reading/` changes.

## Configuration

- `GPF_DB` — the SQLite file the cases live in (default: the pension tree's `artifacts/portal.sqlite3`, shared with the case system). Set it empty to run on JSON snapshots under `GPF_DATA_DIR/cases` instead. Snapshots found there are imported into the database once, by id, when the module starts.
- `GPF_DATA_DIR` — where uploads are written (default `backend/data`).

## Production notes (not in the MVP)

- Put SSO/LDAP in front; the `officer` field is a stand-in for authenticated identity.
- Swap `CaseRepository` for Postgres (spec §1 puts it on Spark-1) behind the `Repository` protocol.
- The QR/barcode service (zxing-cpp + OpenCV, deterministic) and the vision pipeline are build phases 5–6.
