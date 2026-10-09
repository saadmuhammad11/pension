# Pension pipeline — optimization analysis (9 Oct 2026)

Analysis of where the pension pipeline spends its time, which steps are redundant, and how much
can realistically be recovered. Grounded in `docs/PERF-BASELINE.md` (the 7 Oct 2026 baseline,
`tools/bench.py --label baseline`, commit `87542c0`) and the code on `main` at `10d45d5`.

**Scope:** read-only review. No code was changed. The optimization pass itself ("Phase 2") is
not started — see §5.

---

## 1. State of the performance work

The dedicated effort (`perf/pipeline`) is **fully merged into `main`** (main 14 ahead, branch 0
ahead) and covers **Phase 1 — measurement only**. The optimization pass is parked pending a go.

**Completed — measurement infrastructure** (`493ff63`, `e48c0b3`):

- Per-stage, per-model-call and queue-wait timing in the database (`run_timings`, migration 0011),
  via `pipeline/timing.py`.
- `tools/bench.py` — fixed four-case benchmark; `tools/bench_compare.py` — holds every later change
  to the baseline (proves findings stay identical).
- `docs/PERF-BASELINE.md` — the baseline itself.

**Completed — speed-ups already in the pipeline** (pre-date the perf branch; `api/runs.py`,
`pipeline/`):

- `identify` batches 4 pages at once (`IDENTIFY_CONCURRENCY`) — fixed a run that spent six minutes
  with three quarters of the vision server idle.
- `assertions` batches documents (submit-then-fold, `ASSERTION_CONCURRENCY=2`), priority-ordered so
  flag-deciding documents (Form D-I/II, LPC) are read before the corroborating NDCs.
- OCR text cached in `ocr_text.json` — a recompute never re-OCRs a page.
- **Carryover / resubmission reuse** (`pipeline/carryover.py`) — on a resubmission only the *new*
  pages are re-read; carried pages reuse the earlier round's reads.
- Per-page (identify) and per-document (assertions) checkpoints — a crash re-runs the page, not the
  whole stage.
- `extract` scoped to determination-critical documents only, not the whole bundle.

---

## 2. Where the time goes (baseline)

Per-case wall time: `large 1461.9s · medium 655.1s · small 439.2s · gpf 110.0s`.

| Stage | Share | What it does | Model |
|---|---:|---|---|
| **assertions** | **59%** | re-reads identifier pages to collect the same fact (date / name / office) from each document, for the cross-document flags | vision, double read |
| **extract** | 21% | reads determination-critical forms for the figures | vision, double read |
| identify | 7% | classifies every page's document type | vision, single read |
| reading | 4% | GP Fund only | OCR |
| assemble / verify / ingest / signatures / determine / report | ~10% | mostly pure code + targeted OCR | — |

**The governing constraint: the GPU is already 89–96% utilized.** The box is compute-bound, not
queue-bound. More parallelism buys almost nothing — the only real lever is **doing less vision
work**.

Most expensive vision schemas (sum over cases):

| Schema | Calls | Total s | Mean s |
|---|---:|---:|---:|
| `GENERIC_PAGE` | 44 | 1472.2 | 33.5 |
| `AG_PAY_CERTIFICATE` | 15 | 729.1 | 48.6 |
| `PAGE_IDENTITY` | 85 | 706.4 | 8.3 |
| `FORM_D_I` | 10 | 417.8 | 41.8 |
| `FORM_D_II` | 6 | 296.0 | 49.3 |

---

## 3. Redundant steps (confirmed)

**The same page is read by vision in `identify`, then `extract` (×2), then `assertions` (×2)** —
each stage reparses the full image independently, and both `extract` and `assertions` run their own
confirming double read. There is **no shared per-page read cache within a single run**; the only
reuse is across resubmission *rounds*.

Worst offenders on the large case (`docs/PERF-BASELINE.md`, "same schema repeated"):

- page 41 `FORM_D_I` read **6×** (≈ three double-reads of one page)
- page 42 `AG_PAY_CERTIFICATE` **4×**, page 7 `AG_PAY_CERTIFICATE` **4×**, page 29 **3×**

At the measured means, those four pages alone waste **~410s of the large case's 1461.9s (≈28%)** on
reads that return the same page under the same schema.

Secondary findings:

- `GENERIC_PAGE` is the single most expensive bucket (44 calls, 1472s, mean 33.5s): non-form pages
  (NDCs, letters) read with the full vision model purely for corroboration. The code itself notes
  the NDCs "can wait" — they only add weight to F-1.
- Stale comment: `pipeline/run.py:76` says the vision server runs `--max-num-seqs 4`; the live
  server runs `--max-num-seqs 16`, while the code caps `IDENTIFY_CONCURRENCY=4` and
  `ASSERTION_CONCURRENCY=2`.

---

## 4. How much can be recovered

Because the GPU is saturated, wall time tracks **number × cost of vision calls**. Savings come from
removing or cheapening reads, not from more threads.

| Lever | Est. saving (pension cases) | Risk |
|---|---|---|
| **Per-`(page, schema)` read cache** shared across `extract` + `assertions`; collapse the 3–6× same-schema reads to the one double read | **~25–35%** wall on large/medium (less on small) | Low — reuses identical reads; H1 double read preserved |
| **Unify `extract` + `assertions` reads** — one richer read per page serving both figures and identifiers, instead of two schema passes | additional **~10–15%** | Medium — schema work; prove identical findings with `bench_compare` |
| **Cheapen `GENERIC_PAGE` / NDC reads** — OCR (7.6s) or read only enough NDCs to corroborate, instead of full vision (33.5s) on all | **~10–20%** on NDC-heavy bundles | Medium — a rules/scope decision (how much corroboration is required) |
| Raise concurrency to `--max-num-seqs 16` | small today (GPU-bound); matters only after per-call cost is cut | Low |

**Bottom line: roughly a 35–50% wall-time reduction on real pension cases looks achievable**,
almost entirely by eliminating the redundant re-reads — without touching the **H1 double read**
(which must stay) or any business rule.

---

## 5. Recommended next pass (Phase 2), lowest-risk first

1. **Shared read cache** keyed on image-hash + schema, reused across `extract` and `assertions`
   within a run. Keep the double read (two calls fill the cache); every later request for the same
   (page, schema) is served from it. Prove no finding changes with `tools/bench_compare.py`.
2. Measure against the baseline; record the delta here and in `docs/PERF-BASELINE.md`.
3. Only then consider schema unification and the `GENERIC_PAGE`/NDC question (the latter needs a
   rules-owner decision, like the other scope items in `docs/pension-rules-decisions.md`).

**Invariants to hold throughout:** the H1 disagreeing-double-read guard stays (commit `4af79ea`);
no business rule changes; `bench_compare` green on every commit; the live trial is not touched
(no restart mid-verification).
