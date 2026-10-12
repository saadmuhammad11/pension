# GP Fund AI Pre-Audit Module

Implementation of `agofficegpfund/instructions/GP-FUND-AI-MODULE-BUILD-SPEC.md` (revision 2,
15-09-2026), the handover document TMC prepared for the sovereign AI team at the Office of the
Accountant General, Punjab.

```
GP/
  backend/          THE SYSTEM — FastAPI app: API + web UI + the reading pipeline
  agofficegpfund/   the handover material, exactly as it arrived in the zip. Not modified.
  gpfund/           the standard-library rules engine, no web layer
  prototype -> agofficegpfund/prototype   (the backend expects this path)
  run.sh            one front door for all of it
```

There are two rule engines in this tree, and that is deliberate: `backend/gpf/` is the
production one the web app runs, and `gpfund/` is the standard-library port that needs no
interpreter beyond CPython and no services at all. Both implement the same specification.

---

## Run it

```bash
./run.sh                 # start the system (API + web UI) on :8201
./run.sh status          # what is up, including the four model services
./run.sh stop            # stop it; :8200 and the pension portal are left alone
./run.sh test            # the 62 backend tests
./run.sh logs            # follow backend/logs/gpf.log
```

Then open **http://localhost:8201/** — intake, SAP extracts, examination, cure-by-upload,
the DOA register, disposal and the issue pack. One process serves the API, the UI and the
case assets.

`./run.sh prototype` still serves the frozen September HTML demo on :8099. It decides
nothing and reads nothing; it is kept for reference only.

`./run.sh engine` drives the standard-library rules engine with no web layer at all:

```bash
./run.sh engine                 # all eight corpus cases, four numbers each
./run.sh engine fp-death        # one case, every check
./run.sh engine --catalogue     # every registered check, by group
./run.sh engine test            # its 181 tests
```

**Four deployments share this machine and only two are ours.** `:8201` is this copy and
`:8200` is the original in `~/Desktop/Pension-AG/gp-fund` — the same application under a
different root, so nothing this script stops can be found by pattern alone. Every process it
touches is confirmed by working directory first. `PORT=8202 ./run.sh` moves ours.

The app runs on `/home/tmc/vllm_env`, the shared interpreter that already carries FastAPI and
the CUDA stack. Nothing is ever installed into it; `./run.sh test` builds its own small venv
under `~/.cache/gpf-test-venv` on first use.

Or drive the decision layer directly:

```bash
cd GP
python3 -m gpfund                        # every corpus case, four numbers each
python3 -m gpfund fp-death               # one case, every check
python3 -m gpfund refundable --no-sap    # the same case as received without its SAP pages
python3 -m gpfund missing-credits --pack # the issue pack, as JSON
python3 -m gpfund --catalogue            # every registered check, by group

python3 -m unittest discover -s gpfund/tests -t .     # 181 tests, ~0.3s
```

No GPU, no network, no clock, no third-party package. The decision layer is standard-library
Python, which is what lets the office re-check a case years later with nothing but this
directory and an interpreter.

---

## What governs the build

> **The language model never decides anything. It reads. The rules decide, from facts.**
> — specification §0

Everything here is the half of the module that needs no model: the facts and result
contracts, the rule catalogue, the SAP data contract, the cure loop, the DOA register and the
disposal gates. The reading stage (§3 stages 1 to 5) produces a facts object; nothing below
that line calls a model, and nothing above it decides anything.

```
scan ──► [READ: vision model] ──► facts ──► [RULES: this package] ──► results
                                     ▲                                  │
     SAP extract ────────────────────┤                                  ▼
     uploaded document ──► [READ] ───┤             observations · verification tasks
     officer verification ───────────┘              SAP items · satisfied checks
                                                                        │
                                                          officer disposes ──► issue pack
```

---

## The acceptance test

§16.2 is explicit: *a build that does not produce these results from these facts is not
working.* It does.

| Case | Hard | Obs. | Verify | SAP |
|---|---|---|---|---|
| Final payment, non-gazetted (Subscriber A. Test) | 0 | 3 | 5 | 0 |
| Final payment, death (Subscriber B. Test) | 4 | 4 | 7 | 0 |
| Final payment, dismissal (Subscriber C. Test) | 0 | 4 | 6 | 0 |
| Missing credits (Dr Subscriber D. Test) | 1 | 1 | 1 | 4 |
| Residual payment (Subscriber E. Test) | 1 | 1 | 2 | 0 |
| Refundable advance (Subscriber F. Test) | 0 | 2 | 4 | 0 |
| Non-refundable advance (Subscriber G. Test) | 0 | 2 | 4 | 0 |
| Balance transfer (Subscriber H. Test) | 0 | 0 | 2 | 5 |

Pinned by result **id**, not only by count, so a compensating change cannot hide. Every case
is also run with its SAP pages removed, and uploading the sample extract from
`agofficegpfund/prototype/sap-samples/` returns each case to the results above.

---

## What is here

| Module | Specification | What it does |
|---|---|---|
| `contracts.py` | §4.1–§4.4 | `Facts`, `Result`, `Lists`, the seven-status vocabulary |
| `params.py` | §4.5, §11.1, §13.2 | advance limits by clause, confidence thresholds, delegation bands — each with its source |
| `engine.py` | §0, §4.4, §7.1 | the check registry, `evaluate`, `lists`, the run diff |
| `rules_common.py` | §5.1 | 11 checks across families (SAP, R3, R5, R10, R4, R7, R6) |
| `rules_advances.py` | §5.2, §11 | 10 checks, the advance ceiling and the §6.5 balance-timing trap |
| `rules_final.py` | §5.3, §12 | 11 checks: fresh, death, dismissal, residual |
| `rules_missing_credits.py` | §5.4, §5.5 | 7 checks: missing credits and balance transfer |
| `rules_statutory.py` | §5.3 | the statutory guard on R13 — *"to build; not in the prototype"* |
| `rules_custom.py` | §5 | 14 case-specific checks, each with an id, a ref and a code |
| `sap.py` | §6 | the extract contract, the text/JSON parser, `SapConnector`, `ManualUploadConnector` |
| `qr.py` | §9.2, §9.3 | the payload parsers — smart CNIC backs, e-Stamp, the three NADRA portals, the QR-coded sanction — and which codes need a portal |
| `cures.py` | §7.2 | 24 mappings from a confirmed upload to a change in the facts |
| `casefile.py` | §7, §13.2, §15 | fact versions, the cure loop, dispositions, the append-only log |
| `disposal.py` | §12, §13 | report reconciliation, the disposal gates, the issue pack |
| `doa.py` | §8 | the register, designation normalisation, the lookup |
| `corpus/` | §16 | the eight cases as facts fixtures, plus the provisional register |

**40 registered checks + 14 case-specific.** `python3 -m gpfund --catalogue` lists them.

---

## The four findings this port produced

The build specification and the prototype were followed closely; four things came out of
doing so.

**1. A provisional balance could fail a sound sanction.** §14 rule 8 forbids testing a limit
against a balance that already includes the advance, and §11.2 makes a pay-slip-only basis
`conf`. But the ceiling was tested *before* the basis: with only a pay slip, the refundable
case's Rs 58,000 measured against 80% of the post-advance Rs 19,194 reads as Rs 42,645 over
an Rs 15,355 limit — a hard stop against a sanction well inside the Rules, which is precisely
what §6.5 exists to prevent. The basis is now settled first; the ceiling is still shown so
the officer can see the figure, with no conclusion drawn from it.

**2. A result id depended on a list index being non-zero.** §4.4 wants an id stable enough to
follow a result across re-evaluations and to hang a disposition on. The first of several
results got the bare check id while its siblings got `CHECK:1`, `CHECK:2`. CNIC results are
now keyed by the page the card sits on, which is what an officer sees and does not move.

**3. The statutory guard on R13 was not built.** §5.3 sets it out and notes it is absent from
the prototype: Rule 1.35 applies section 4 of the Provident Funds Act 1925, and where a payee
is neither family under Rule 1.2(1)(c) nor a dependant nominee, no nomination subsists, and
the balance exceeds Rs 5,000, section 4(1)(c) requires probate. It is now
`DEATH-SECTION4`, deliberately separate from `DEATH-SUCCESSION` so it can fire *even when an
OSD post has satisfied R13* — the statute outranks the office instruction. On the corpus death
case all three heirs are family, so it reports `ok` and changes no count; it fires on a payee
outside the family.

**4. `PAYSLIP-ATTEST` does not come back after an upload, and should not.** R5 makes an
unattested pay slip an observation because a *department* supplied the copy. An extract this
office pulled from SAP raises no attestation question at all, so the check stops applying.
§16.2's "returns each case to the results above" holds for every other result; the test names
this one exception rather than adjusting a count to hide it.

---

## What is deliberately not here

§19 orders the build, and phases 1 to 4 are the ones that need no model. They are done.
Phases 5 to 10 need a GPU, a barcode library, an SAP link or an agreement the office does not
yet have, and the specification's rule for them is the standing one: never demonstrate an
untested path as working.

| Phase | Left to build | Blocked on |
|---|---|---|
| 5 | the QR and barcode **decoder** (zxing-cpp, OpenCV). The **payload parsers** of §9.2 are now built (`qr.py`); the corpus decode results are still carried as facts | zxing-cpp and OpenCV, which the decision layer will not take as dependencies |
| 6–9 | Stages 1 to 5 — page identification, per-artefact extraction, Service Book reading with the LoRA loop | a GPU and the model layer at §2 |
| 10 | `SapRfcConnector` / `SapODataConnector`, the verification gateway, the NADRA biometric route | GPF-O19, GPF-O20, GPF-O22 |

Two things the specification says to build and this package does **not** attempt, on purpose:

* **Fingerprint matching.** §10: tested on every CNIC copy and every impression in the
  corpus, and *it cannot be done from the case papers*. Same-person pairs scored 0.10–0.21
  against different-person pairs at 0.08–0.28; the ranges overlap completely. `§14 rule 5`
  forbids claiming a match either way, and a test greps the package to keep a matcher from
  appearing later.
* **Deciding a signature.** §8.4 allows an assistive similarity score; it never passes or
  fails a signature and is never shown without the images. This build computes none, so
  nothing can leak one.

---

## The thirteen open items this build engages

The module reports these rather than resolving them. Each appears in a finding on a real case.

`GPF-O13` delegation bands · `GPF-O14` the DOA register and specimens — until it is published
no signature can be a hard stop · `GPF-O15` **advance limits**, the widest of them: the
office's 80% agrees with the Rules for house and land advances, is looser than the Rules for
general temporary advances (half the balance) and stricter than Rule 1.16 (100% at 50), and
the compendium carries no notification raising the temporary ceiling · `GPF-O16` second
advance timing · `GPF-O17` the OSD post and the reconciliation of A.2(vi) with Rule 1.34 ·
`GPF-O19` SAP access by RFC or OData rather than BDC · `GPF-O20` the QR verification route ·
`GPF-O21` gazetted status against BS-16 · `GPF-O22` the NADRA biometric route · `GPF-O23`
heirs and post-death credits · `GPF-O24` Service Book receipt · `GPF-O25` partial crediting ·
`GPF-O26` R4 on forwarding endorsements.

---

## The evaluation harness

`gpfund/tests/`, 181 tests, and the §17 rows it covers:

| §17 row | Where |
|---|---|
| Rules engine against the fixture facts, every check id and status | `test_fixtures.py` |
| Re-evaluation determinism | `test_determinism.py` |
| Model swap invariance | `test_determinism.py` |
| SAP text-export parsing, 100% on the samples | `test_sap.py` |
| QR payload parsing against every decoded payload in the corpus | `test_qr.py` |
| SAP extract identity rejection, 100% | `test_sap.py` |
| DOA lookup on the corpus designation strings | `test_doa.py` |
| False-positive observations, with §16.3 as permanent regression cases | `test_regressions.py` |

`test_regressions.py` also holds §14's prohibitions. Several are assertions about the code
rather than about a case — that nothing in the decision layer can reach a clock, a random
number, a socket or a fingerprint matcher — because "do not build it" is not a property any
single case can demonstrate.

Not covered here, because they need the reading stage: QR decode **rate** on the corpus
(`test_qr.py` covers what every decoded payload *means*, not how many decode from the
images), field extraction precision on financially material fields, and page classification.
