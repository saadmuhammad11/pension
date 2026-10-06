"""Run registry and pipeline execution. BUILD §5.1.

Separated from the HTTP layer so the pipeline can be driven from a test, a CLI or a Celery
worker without a web server in the way -- BUILD §4 puts Celery in production and this keeps
that swap to one function.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"
UPLOADS = ARTIFACTS / "uploads"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class Run:
    run_id: str
    pdf_path: Path
    run_dir: Path
    state: str = "queued"
    started_at: str = ""
    finished_at: str = ""
    error: str | None = None
    #: The AG office checklist column the officer chose at intake. Not derivable from the
    #: bundle -- whether a claimant is a widow, an unmarried daughter or a parent is a fact
    #: about who is claiming -- so SOP §6.4's drop-down is where it comes from.
    variant: str | None = None
    #: A resubmission's earlier round (30 Sep 2026): the run whose reading of unchanged papers
    #: this one reuses (pipeline.carryover). None for a first submission: a full run.
    base_run_id: str | None = None
    #: The case type the department declared at intake (config/case_types.json), 29 Sep 2026.
    #: Selects the checklist and rules directly; the papers are still classified and compared.
    case_type: str | None = None
    #: Basic pay including personal pay as at 1 July, for each of the three years before
    #: retirement, as {year: amount}. Required by rule 4.4(4) for any case after 2 December
    #: 2024, and not derivable from a bundle that carries one pay slip.
    annual_pay: dict[str, str] = field(default_factory=dict)
    #: The fraction of gross pension the pensioner elected to commute, as a percentage
    #: string. Empty means no election is on the file, which is not the same as zero.
    commutation_percent: str = ""
    #: The date of retirement as the officer typed it at intake, ISO. Used only where the
    #: sanction form's own text yields none; the form governs where it speaks.
    retirement_date: str = ""
    #: For a family pension on the death of a pensioner: the pension in payment as the
    #: Auditor reads it off the PPO, and the date of death, keyed only where no page of the
    #: bundle yields them. Recorded on the determination as officer entries.
    pension_in_payment: str = ""
    date_of_death: str = ""
    #: Where a case arrived as a bundle of mixed documents -- a zip the officer
    #: uploaded -- this is that zip, and ``pdf_path`` is the
    #: single case file made from it (``pipeline.bundle``). Empty for a plain PDF upload.
    bundle_path: Path | None = None
    #: Where the case came from: the officer's own upload and the desk that made it. Kept so a page can always be traced back to the file it arrived in.
    source: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, stage: str, message: str, **extra: Any) -> None:
        now = datetime.now()
        ev = {
            "seq": len(self.events),
            "at": now.strftime("%H:%M:%S"),
            # The full moment, for a screen that opens mid-run (30 Sep 2026): "at" alone is a
            # time of day the browser cannot place, so a reopened analysis took every event as
            # happening "now" and its progress started again from zero.
            "ts": now.isoformat(timespec="milliseconds"),
            "stage": stage,
            "message": message,
            **extra,
        }
        with self.lock:
            self.events.append(ev)
        print(f"  [{self.run_id}] {stage:<10} {message}", flush=True)


RUNS: dict[str, Run] = {}
#: Where a run's intake choices are kept, beside its artefacts.
INTAKE = "intake.json"
_REGISTRY_LOCK = threading.Lock()


def completed_run_ids() -> list[str]:
    """Run ids that finished and left a report behind, newest first.

    The registry lives in memory, so a restart used to hide every case the office had
    already processed. The artefacts were never lost -- the run directory holds the whole
    account of a run, and the run id is the content hash of the file that produced it -- so
    the index is rebuilt from disk rather than kept alive in a process.
    """
    if not ARTIFACTS.is_dir():
        return []
    found: list[tuple[float, str]] = []
    for d in ARTIFACTS.glob("run-*"):
        report = d / "case_report.json"
        if d.is_dir() and report.exists():
            found.append((report.stat().st_mtime, d.name[len("run-"):]))
    return [run_id for _, run_id in sorted(found, reverse=True)]


def adopt_from_disk(run_id: str) -> Run | None:
    """Rebuild the registry entry for a finished run, or return None.

    Only runs that produced a ``case_report.json`` are adopted. A directory left behind by a
    run still executing when the process died did not finish, and presenting it as a case
    would invent a history the artefacts do not support -- re-uploading the file resumes it
    properly instead (§5.1).

    The adopted run carries one synthetic ``end`` event so the event stream closes at once
    rather than following a run that will never speak again. It is marked ``replayed`` so a
    reader can tell it from the events the pipeline actually emitted.
    """
    if not run_id or "/" in run_id or "\\" in run_id or run_id.startswith("."):
        return None
    run_dir = ARTIFACTS / f"run-{run_id}"
    report = run_dir / "case_report.json"
    if not run_dir.is_dir() or not report.exists():
        return None

    with _REGISTRY_LOCK:
        existing = RUNS.get(run_id)
        if existing is not None:
            return existing
        manifest = run_dir / "manifest.json"
        started = datetime.fromtimestamp(
            (manifest if manifest.exists() else report).stat().st_mtime
        ).isoformat(timespec="seconds")
        finished = datetime.fromtimestamp(report.stat().st_mtime).isoformat(timespec="seconds")
        uploads = sorted(UPLOADS.glob(f"{run_id}-*")) if UPLOADS.is_dir() else []
        # A bundled case leaves two uploads: the zip as it arrived and the case PDF built
        # from it. The run reads the PDF, so the PDF is what the adopted run points at.
        pdfs = [u for u in uploads if u.suffix.casefold() == ".pdf"]
        bundles = [u for u in uploads if u.suffix.casefold() == ".zip"]
        intake: dict = {}
        try:
            intake = json.loads((run_dir / INTAKE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            intake = {}
        run = Run(
            run_id=run_id,
            pdf_path=(pdfs or uploads or [UPLOADS / f"{run_id}.pdf"])[0],
            bundle_path=bundles[0] if bundles else None,
            source=intake.get("source") or {},
            run_dir=run_dir,
            state="done",
            started_at=started,
            finished_at=finished,
            variant=intake.get("variant") or None,
            case_type=intake.get("declared_case_type") or None,
            annual_pay={str(k): str(v) for k, v in (intake.get("annual_pay") or {}).items()},
            commutation_percent=str(intake.get("commutation_percent") or ""),
            retirement_date=str(intake.get("retirement_date") or ""),
            pension_in_payment=str(intake.get("pension_in_payment") or ""),
            date_of_death=str(intake.get("date_of_death") or ""),
            events=[{"seq": 0, "at": finished[11:], "stage": "end",
                     "message": "done", "state": "done", "replayed": True}],
        )
        RUNS[run_id] = run
        return run


#: Report summaries, keyed by path and invalidated by mtime. The intake history asks for
#: every finished case each time it is opened, and a case report is 40 kB of JSON the officer
#: never sees a byte of -- re-parsing all of them on every poll is work done for nothing.
_SUMMARY_CACHE: dict[str, tuple[float, dict]] = {}


def _report_summary(run_dir: Path) -> dict:
    """The handful of fields a case needs to appear in a list. Empty where no report exists.

    Deliberately thin. A history line says which case this was, what the engine concluded and
    how strong the paperwork was -- enough to recognise a case, not enough to act on one. An
    officer who wants the findings opens the case, where they come with their evidence.
    """
    path = run_dir / "case_report.json"
    if not path.exists():
        return {}
    stamp = path.stat().st_mtime
    cached = _SUMMARY_CACHE.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        # A half-written report is not a case to list. Saying so beats showing a blank row.
        return {"unreadable": True}
    rec = report.get("recommendation") or {}
    checklist = report.get("checklist") or {}
    source = report.get("source") or {}
    flags = report.get("flags") or []
    summary = {
        "claimant_name": report.get("claimant_name"),
        "diary_no": report.get("diary_no"),
        "case_type": (report.get("case_type") or {}).get("case_type"),
        "case_type_source": (report.get("case_type") or {}).get("source") or "detected",
        "declared_case_type": (report.get("case_type") or {}).get("declared"),
        "detected_case_type": ((report.get("case_type_detected") or report.get("case_type") or {}).get("case_type")),
        "detected_case_type_confidence": ((report.get("case_type_detected") or report.get("case_type") or {})
                                          .get("case_type_confidence")),
        "case_variant": report.get("case_variant"),
        "verdict": rec.get("verdict"),
        "blocking_flags": list(rec.get("blocking_flags") or []),
        "flags": len(flags),
        "high_flags": sum(1 for f in flags if f.get("severity") == "HIGH"),
        "checklist_result": checklist.get("result"),
        "checklist_satisfied": checklist.get("satisfied"),
        "checklist_required": checklist.get("required"),
        "source_file": source.get("file"),
        "source_pages": source.get("source_pages"),
    }
    _SUMMARY_CACHE[str(path)] = (stamp, summary)
    return summary


def summarise(run: Run) -> dict:
    """One case, as it appears in a list of cases.

    Carries the decision in force alongside the engine's verdict, because the two are
    different facts and a history that showed only one of them would be misleading in both
    directions: a case the engine wanted returned may have been forwarded by an officer who
    recorded why, and a case nobody has decided yet is not a decided case.
    """
    from api.decisions import current_decision

    decision = current_decision(run.run_dir)
    return {
        "run_id": run.run_id,
        "state": run.state,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "variant": run.variant,
        "error": run.error,
        "events": len(run.events),
        "file": run.pdf_path.name,
        "source": run.source or None,
        **_report_summary(run.run_dir),
        "decision": None if decision is None else {
            "action": decision.get("action"),
            "officer": decision.get("officer"),
            "role": decision.get("role") or "",
            "at": decision.get("at"),
            "overrides_recommendation": bool(decision.get("overrides_recommendation")),
        },
    }


def gpu_utilisation() -> dict:
    """Live GPU numbers.

    On the GB10 the memory columns report ``[N/A]`` because CPU and GPU share one coherent
    pool, so memory is read from /proc/meminfo instead. Where a figure is genuinely
    unavailable it is returned as null rather than filled with a plausible one -- an invented
    percentage on a demo screen is what makes a real one untrustworthy.
    """
    out: dict[str, Any] = {
        "gpu_util_pct": None, "gpu_name": None,
        "mem_used_gb": None, "mem_total_gb": None,
        "at": datetime.now().strftime("%H:%M:%S"),
    }
    try:
        raw = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if raw:
            util, name = (p.strip() for p in raw.split(",")[:2])
            out["gpu_name"] = name
            if not util.startswith("[N/A"):
                out["gpu_util_pct"] = int(util.rstrip(" %"))
    except Exception:
        pass
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                info[k] = int(v.strip().split()[0])
        total = info["MemTotal"] / 1048576
        out["mem_total_gb"] = round(total, 1)
        out["mem_used_gb"] = round(total - info["MemAvailable"] / 1048576, 1)
    except Exception:
        pass
    return out


#: Where a stage's refusal is kept so the report can quote it. BRAIN §15.2 requires a gap to
#: be stated "precisely" and escalated to a person; the stages do say precisely why they
#: refused, but the sentence used to end its life in this process's stdout. The officer saw a
#: determination panel reading "Not computed." and no reason at all.
DETERMINATION_GAP = "determination_gap.json"


def _record_gap(run: Run, stage: str, reason: str) -> None:
    """Keep what a stage said when it declined, alongside the artefacts it did not write.

    Accumulated rather than overwritten: stage 4 finding no readable form is the cause, and
    stage 7 having no inputs is the consequence, and an officer reading only the second would
    go looking for the wrong thing.
    """
    from pipeline.ingest import atomic_write_text

    path = run.run_dir / DETERMINATION_GAP
    gaps: dict[str, str] = {}
    if path.exists():
        try:
            gaps = json.loads(path.read_text())
        except ValueError:
            gaps = {}
    gaps[stage] = reason
    run.run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(gaps, indent=2, ensure_ascii=False))


#: What a bundled run's manifest is called, beside its artefacts.
BUNDLE_MANIFEST = "bundle.json"


def unpack(run: Run) -> dict:
    """Turn the bundle into the one case file the pipeline reads. ``pipeline.bundle``.

    Every attachment's fate is recorded twice: as an event the officer watches go by, and in
    ``bundle.json`` beside the artefacts, where the page range each document occupies in the
    merged file is kept. That is what lets the Review screen say which file page 31 came out
    of, and what lets an officer see that the department's ``.msg`` attachment never became a
    page at all -- the failure this replaces is a bundle quietly arriving one document short.
    """
    from pipeline.bundle import describe, normalise

    assert run.bundle_path is not None
    run.emit("bundle", f"unpacking {run.bundle_path.name}")
    bundle = normalise(run.bundle_path.read_bytes(), run.bundle_path.name,
                       run.run_dir / "bundle")
    run.pdf_path.write_bytes(bundle.pdf)
    manifest = bundle.manifest()
    manifest["source"] = run.source or {"kind": "upload", "file": run.bundle_path.name}
    manifest["bundle_file"] = run.bundle_path.name
    (run.run_dir / BUNDLE_MANIFEST).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    for part in bundle.skipped:
        run.emit("bundle", f"{part.name} is not in the case file — {part.skipped}",
                 level="warn")
    run.emit("bundle", describe(bundle.parts), pages=bundle.pages)
    return manifest


def execute(run: Run) -> None:
    """Run every stage, emitting an event as each completes."""
    from pipeline.extract import stage_assertions, stage_determine, stage_extract
    from pipeline.ingest import atomic_write_text, ingest
    from pipeline.report import build_report
    from pipeline.run import stage_assemble, stage_classify, stage_identify, stage_verify_forms

    run.state = "running"
    run.started_at = datetime.now().isoformat(timespec="seconds")
    persist_intake(run)
    # A re-run that gets further than the last one must not carry the old refusal with it.
    (run.run_dir / DETERMINATION_GAP).unlink(missing_ok=True)
    try:
        # Stage 0. A case that arrived as a zip of loose scans -- becomes one case file first. Skipped on a resume: the case
        # file is already on disk and rebuilding it would change nothing but the clock.
        if run.bundle_path is not None and not run.pdf_path.exists():
            unpack(run)

        # A resubmission: carry the earlier round's reading of every unchanged paper, so only
        # the new pages reach the models (pipeline.carryover). No base run, or nothing in
        # common with it, and the run is a full run -- exactly what a first submission is.
        carry = None
        carried_rows = None
        if run.base_run_id:
            from pipeline import carryover
            prepared = carryover.prepare(run.run_dir, ARTIFACTS / f"run-{run.base_run_id}",
                                         run.base_run_id, run.pdf_path)
            carry = carryover.load(run.run_dir)
            if carry:
                carried_rows = carryover.carried_manifest_rows(run.run_dir)
                run.emit("carryover",
                         f"resubmission: {len(carry['page_map'])} page(s) reused from run "
                         f"{run.base_run_id}; {len(carry['new_pages'])} new page(s) to read "
                         f"({', '.join(map(str, carry['new_pages'])) or 'none'})")
            else:
                run.emit("carryover", f"full run — {prepared.get('reason')}")

        run.emit("ingest", f"reading {run.pdf_path.name}")
        manifest = ingest(run.pdf_path, run.run_dir, carried=carried_rows)
        run.emit("ingest",
                 f"{manifest['source_pages']} source pages · "
                 f"sha256 {manifest['source_sha256'][:16]}…",
                 pages=manifest["source_pages"])

        run.emit("identify",
                 f"classifying {manifest['source_pages']} pages on the vision model "
                 f"(this is the slow stage)")
        stage_identify(run.run_dir, progress=lambda line: run.emit("identify", line.strip()))

        run.emit("verify", "second-reading every claimed prescribed form with OCR")
        stage_verify_forms(run.run_dir, progress=lambda line: run.emit("verify", line.strip()),
                           skip_pages=frozenset(int(k) for k in (carry or {}).get("page_map", {})))

        docs = stage_assemble(run.run_dir)
        run.emit("assemble", f"{len(docs)} documents assembled from the page identities")

        ct = stage_classify(run.run_dir)
        run.emit("classify",
                 f"case type {ct['case_type'] or 'ROUTE_MANUAL'} "
                 f"({ct['case_type_confidence']}) — {ct['case_type_evidence'][:80]}")

        # Stages 4, 6 and 7 serve the DETERMINATION. A case the engine cannot compute is a
        # routing outcome, not a crash (BRAIN §15.2: flag, cite, escalate -- never guess), and
        # the work already done still has to reach the officer. A self-pension bundle raised
        # ExtractionGap here -- correctly, it carries Form B-I and not Form D-I -- and the
        # whole run was marked failed, so nine correctly identified documents were thrown away
        # and the officer saw an error where a document list should have been.
        run.emit("extract", "reading determination-critical documents (each read twice)")
        try:
            stage_extract(run.run_dir, progress=lambda line: run.emit("extract", line.strip()),
                          carry=carry)
        except Exception as exc:                          # noqa: BLE001
            run.emit("extract", f"no determination inputs — {exc}", level="warn")
            _record_gap(run, "extract", str(exc))

        # Stage 6 was missing from this flow. Without it there is no assertions.json, so the
        # flag battery runs over a record with no cross-document facts in it and raises 2 of
        # the 8 findings with NOTHING blocking -- no personnel-number mismatch, no Annex-A /
        # FRC contradiction, no Rs. 126,355 recovery, no unreadable page, no SLA breach. The
        # report still looked complete, which is the dangerous part. Every flag that needs two
        # documents to disagree needs this stage.
        # Stage 6 needs no prescribed form -- it reads whatever identifier documents are in
        # the bundle -- so it runs even where stage 4 found nothing to read.
        run.emit("assertions", "collecting the same fact from each document that states it")
        try:
            stage_assertions(run.run_dir,
                             progress=lambda line: run.emit("assertions", line.strip()),
                             carry=carry)
        except Exception as exc:                          # noqa: BLE001
            run.emit("assertions", f"cross-document checks incomplete — {exc}", level="warn")

        # Stage 6b: who signed each prescribed form, and the specimen on file for that post
        # (pipeline.signatory, rules.specimens). One model call per form page; the signature
        # itself is left for the officer to compare, beside the specimen.
        run.emit("signatures", "reading the sanctioning authority's signature and stamp")
        try:
            from pipeline.signatory import stage_psa_signatures
            sigs = stage_psa_signatures(run.run_dir,
                                        progress=lambda line: run.emit("signatures", line.strip()))
            for f in sigs.get("forms", []):
                run.emit("signatures", f"{f['document']} p.{f.get('page')}: "
                         f"{f.get('designation') or 'signatory not read'} — specimen "
                         f"{f.get('specimen') or f.get('specimen_status')}")
        except Exception as exc:                          # noqa: BLE001
            run.emit("signatures", f"signature check incomplete — {exc}", level="warn")

        try:
            det = stage_determine(run.run_dir)
            d = det["determination"]
            e = det.get("emoluments")
            # A Form D-II determination carries no emoluments block -- the base is the
            # pension in payment, not a pay table -- and indexing None here raised AFTER the
            # determination had been written, so every D-II case was logged "routed to
            # human" beside a determination that existed.
            if e:
                run.emit("determine",
                         f"reckonable {e['reckonable_total']:,} / excluded "
                         f"{e['excluded_total']:,} · reconciled={e['reconciled']}")
            run.emit("determine",
                     f"rule pack {d['rule_pack_id']} · {len(d['steps'])} steps · "
                     f"{len(d['ambiguities'])} unresolved reading(s) · "
                     f"{'PROVISIONAL' if d['provisional'] else 'final'}")
        except Exception as exc:                          # noqa: BLE001
            # A determination gap is a routing outcome, not a crash. BRAIN §15.2: the
            # degradation path is always flag, cite, escalate -- never guess.
            run.emit("determine", f"routed to human — {exc}", level="warn")
            _record_gap(run, "determine", str(exc))

        # The run's own start time, so a report rebuilt from these artefacts carries the
        # same determination timestamp it did the first time (BUILD §6.2 requirement 1).
        report = build_report(run.run_dir, variant=run.variant,
                              annual_pay=run.annual_pay,
                              computed_at=datetime.fromisoformat(run.started_at),
                              commutation_percent=run.commutation_percent,
                              retirement_date=run.retirement_date or None,
                              case_type=run.case_type)
        atomic_write_text(
            run.run_dir / "case_report.json",
            json.dumps(report, indent=2, ensure_ascii=False),
        )
        verdict = report["recommendation"]["verdict"] if report["recommendation"] else "n/a"
        run.emit("report", f"verdict {verdict}")
        run.state = "done"
    except Exception as exc:                              # noqa: BLE001
        run.state = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.emit("error", run.error, level="error")
        traceback.print_exc()
    finally:
        run.finished_at = datetime.now().isoformat(timespec="seconds")
        run.emit("end", run.state, state=run.state)


def recompute(run: Run) -> dict:
    """Re-run the deterministic layer -- stage 7 and the report -- on a finished run.

    No model is called (one OCR read of the form page for the grade on a D-I case). This is
    how a case catches up with a rule an authorised desk has since confirmed: the pages, the
    identities and the extracted fields stand, and only what the engine concludes from them
    is rebuilt. The previous determination and gap are removed first so a refusal on the new
    rules cannot leave a stale figure beside it.
    """
    from pipeline.extract import DETERMINATION, stage_determine
    from pipeline.ingest import atomic_write_text
    from pipeline.report import build_report

    if not (run.run_dir / "manifest.json").exists():
        raise FileNotFoundError(f"run {run.run_id} has no artefacts to recompute from")
    (run.run_dir / DETERMINATION_GAP).unlink(missing_ok=True)
    (run.run_dir / DETERMINATION).unlink(missing_ok=True)
    persist_intake(run)
    computed_at = (datetime.fromisoformat(run.started_at) if run.started_at
                   else datetime.now())
    try:
        det = stage_determine(run.run_dir, computed_at=computed_at)
        d = det["determination"]
        run.emit("determine",
                 f"recomputed · rule pack {d['rule_pack_id']} · {len(d['steps'])} steps · "
                 f"{len(d['ambiguities'])} unresolved reading(s) · "
                 f"{'PROVISIONAL' if d['provisional'] else 'final'}")
    except Exception as exc:                              # noqa: BLE001
        run.emit("determine", f"routed to human — {exc}", level="warn")
        _record_gap(run, "determine", str(exc))
    report = build_report(run.run_dir, variant=run.variant, annual_pay=run.annual_pay,
                          computed_at=computed_at,
                          commutation_percent=run.commutation_percent,
                          retirement_date=run.retirement_date or None,
                          case_type=run.case_type)
    atomic_write_text(run.run_dir / "case_report.json",
                      json.dumps(report, indent=2, ensure_ascii=False))
    verdict = report["recommendation"]["verdict"] if report["recommendation"] else "n/a"
    run.emit("report", f"recomputed · verdict {verdict}")
    return report



def persist_intake(run: Run) -> None:
    """Write the officer's intake choices beside the artefacts.

    So a restart does not lose them and a recompute after one does not rebuild the report
    with none (found 17 Sep 2026: two intake-selected cases lost their column that way).
    Called by ``execute`` once the run directory exists; ``adopt_from_disk`` reads it back.
    """
    run.run_dir.mkdir(parents=True, exist_ok=True)
    (run.run_dir / INTAKE).write_text(json.dumps({
        "variant": run.variant, "declared_case_type": run.case_type, "annual_pay": run.annual_pay,
        "commutation_percent": run.commutation_percent, "retirement_date": run.retirement_date,
        "pension_in_payment": run.pension_in_payment, "date_of_death": run.date_of_death,
        "source": run.source,
    }, indent=2), encoding="utf-8")


def start_run(body: bytes, filename: str, variant: str | None = None,
              annual_pay: dict | None = None, commutation_percent: str = "",
              retirement_date: str = "", pension_in_payment: str = "",
              date_of_death: str = "", source: dict | None = None,
              namespace: str | None = None, case_type: str | None = None,
              base_run_id: str | None = None) -> dict:
    """Persist the upload and start (or resume) its run.

    ``body`` is either the scanned case file as one PDF, or a zip of the documents that make
    it up -- a folder of loose scans. A zip is stored as
    it arrived and merged into a case file by the run itself (``unpack``), so what the office
    received and what the pipeline read are both on disk and can be compared.

    The run id is the content hash of what was submitted, so the same file always maps to the
    same run directory and re-uploading resumes from the artefacts already on disk rather than
    repeating nine minutes of vision inference (§5.1). Hashing the zip rather than the merged
    file keeps that true for bundles: the merge is deterministic, but the bundle is the thing
    the office actually sent.

    ``namespace`` (the multi-department portal passes the case id) is mixed into the run id, so
    two departments uploading the same papers get two runs, while the same case re-checking an
    unchanged set of papers still resumes its own. ``sha256`` in the answer is always the plain
    digest of the bytes.

    ``base_run_id`` (a resubmission, 30 Sep 2026) names the earlier round's run; pages of
    documents unchanged since it are carried rather than read again (``pipeline.carryover``).
    """
    from pipeline.bundle import looks_like_zip

    digest = hashlib.sha256(body).hexdigest()
    run_id = (hashlib.sha256(f"{namespace}:".encode() + body).hexdigest()[:12]
              if namespace else digest[:12])
    UPLOADS.mkdir(parents=True, exist_ok=True)
    bundled = looks_like_zip(body)
    name = Path(filename).name.replace("/", "_") or ("bundle.zip" if bundled else "case.pdf")
    # Named by what it is rather than by what it was called: a zip an officer named
    # `case.pdf` would otherwise be adopted as the case file after a restart.
    if bundled and not name.casefold().endswith(".zip"):
        name = f"{name}.zip"
    upload = UPLOADS / f"{run_id}-{name}"
    if not upload.exists():
        upload.write_bytes(body)
    bundle_path = upload if bundled else None
    pdf_path = (UPLOADS / f"{run_id}-case.pdf") if bundled else upload

    run_dir = ARTIFACTS / f"run-{run_id}"
    resumed = run_dir.exists()
    with _REGISTRY_LOCK:
        existing = RUNS.get(run_id)
        if existing and existing.state in ("queued", "running"):
            return {"run_id": run_id, "state": existing.state, "resumed": True,
                    "sha256": digest}
        run = Run(run_id=run_id, pdf_path=pdf_path, run_dir=run_dir, variant=variant,
                  case_type=case_type or None, base_run_id=base_run_id or None,
                  bundle_path=bundle_path, source=source or {},
                  annual_pay=annual_pay or {},
                  commutation_percent=commutation_percent or "",
                  retirement_date=retirement_date or "",
                  pension_in_payment=pension_in_payment or "",
                  date_of_death=date_of_death or "")
        RUNS[run_id] = run
    threading.Thread(target=execute, args=(run,), daemon=True).start()
    return {"run_id": run_id, "state": "queued", "file": upload.name,
            "sha256": digest, "resumed": resumed, "variant": variant,
            "bundle": bundled}
