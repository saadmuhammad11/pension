#!/usr/bin/env python3
"""Benchmark the pension and GP Fund pipelines on a fixed set of cases (perf/pipeline, 7 Oct 2026).

    python3 tools/bench.py --label baseline [--cases small,medium,large,gpf] [--check-only]

Runs each case through the same code an officer's verification runs -- api.runs.execute for a
pension case, the GP Fund module's reading job for a GP Fund case -- against the live model
servers, in an ISOLATED artefact folder and database (artifacts/bench/<label>/), so the trial's
data is never touched. Records, per case: wall time, every stage and model call (from
run_timings), GPU utilisation (nvidia-smi, sampled each second), peak system RAM and this
process's peak RSS, and a normalised copy of EVERY finding the case produced, for
tools/bench_compare.py to hold a later run to.

Refuses to start while a trial run is active (the trial database's case_runs) or a model server
is not healthy. Never starts or restarts a service.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api import dbcore  # noqa: E402  -- no other project module yet: isolation is set below, before api.db loads

#: The trial's database: PostgreSQL when PENSION_DATABASE_URL is set (deploy/postgres.env), else the file.
TRIAL_DB = os.environ.get("PENSION_DATABASE_URL") or str(ROOT / "artifacts" / "portal.sqlite3")
MODELS = {"vision": "http://127.0.0.1:8011", "ocr": "http://127.0.0.1:8012", "embed": "http://127.0.0.1:8093"}

#: The fixed set. Pension cases are root PDFs (run id = sha256 prefix, as the API does it); the GP
#: Fund case is the rendered pages of a trial case the portal already turned into images.
CASES = {
    "small":  {"kind": "pension", "pdf": "Family Pension.pdf", "note": "D-II widow, 12 pages"},
    "medium": {"kind": "pension", "pdf": "Family Pen Case OSD Post.pdf", "note": "D-I, 29 pages, CONTRA-MONEY case"},
    "large":  {"kind": "pension", "pdf": "E-Pension_data_v01_DIGITIZED.pdf", "note": "golden D-I, 43 pages"},
    "gpf":    {"kind": "gpf", "pages": "artifacts/cases/0217225bf63242f7a5dd3f93ace42718/s1-gpf-pages/pages.json",
               "gpf_kind": "death", "note": "GP Fund death claim, 14 scanned pages (PC-2026-000079)"},
}


def _trial_runs_active() -> int:
    if not dbcore.is_postgres(TRIAL_DB) and not Path(TRIAL_DB).exists():
        return 0
    con = dbcore.connect(TRIAL_DB)
    try:
        if "case_runs" not in dbcore.table_names(con):
            return 0
        return con.execute("SELECT COUNT(*) FROM case_runs WHERE state IN ('queued','running')").fetchone()[0]
    finally:
        con.close()


def _isolated_target(bench_dir: Path, label: str) -> str:
    """Where this benchmark's rows go, apart from the trial's: a schema of its own in the same
    PostgreSQL database (bench_<label>, emptied first), or a SQLite file under the bench folder."""
    if not dbcore.is_postgres(TRIAL_DB):
        return str(bench_dir / "bench.sqlite3")
    import re
    import urllib.parse
    schema = "bench_" + re.sub(r"[^a-z0-9_]", "_", label.lower())[:40]
    con = dbcore.connect(TRIAL_DB)
    try:
        con.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        con.execute(f'CREATE SCHEMA "{schema}"')
    finally:
        con.close()
    # libpq's options parameter: every connection made with this URL works in that schema.
    sep = "&" if "?" in TRIAL_DB else "?"
    return TRIAL_DB + sep + "options=" + urllib.parse.quote(f"-csearch_path={schema}")


def _healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=5) as r:
            return r.status == 200
    except Exception:                                      # noqa: BLE001
        return False


class Sampler:
    """GPU utilisation (nvidia-smi) and RAM, once a second, on a thread."""

    def __init__(self) -> None:
        self.gpu: list[float] = []
        self.ram_used: list[int] = []
        self.rss: list[int] = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        import psutil
        proc = psutil.Process()
        while not self._stop.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
                self.gpu.append(float(out.splitlines()[0]))
            except Exception:                              # noqa: BLE001
                pass
            self.ram_used.append(psutil.virtual_memory().used)
            self.rss.append(proc.memory_info().rss)
            self._stop.wait(1.0)

    def __enter__(self) -> "Sampler":
        self._t.start(); return self

    def __exit__(self, *a) -> None:
        self._stop.set(); self._t.join(timeout=5)

    def summary(self) -> dict:
        gb = 1024 ** 3
        return {"gpu_util_mean_pct": round(sum(self.gpu) / len(self.gpu), 1) if self.gpu else None,
                "gpu_util_max_pct": max(self.gpu) if self.gpu else None,
                "gpu_samples": len(self.gpu),
                "ram_used_peak_gb": round(max(self.ram_used) / gb, 2) if self.ram_used else None,
                "ram_used_start_gb": round(self.ram_used[0] / gb, 2) if self.ram_used else None,
                "process_rss_peak_mb": round(max(self.rss) / 1024 ** 2, 1) if self.rss else None,
                "note": "GPU memory is unified on this box (nvidia-smi reports N/A); peak system RAM stands in for VRAM"}


def _findings_pension(report: dict) -> dict:
    """Everything the case produced that an officer sees, in a stable order."""
    return {
        "verdict": (report.get("recommendation") or {}).get("verdict"),
        "blocking_flags": (report.get("recommendation") or {}).get("blocking_flags"),
        "case_type": (report.get("case_type") or {}).get("case_type"),
        "case_variant": report.get("case_variant"),
        "flags": [{"class": f.get("class"), "severity": f.get("severity"), "title": f.get("title"), "finding": f.get("finding"),
                   "fingerprint": f.get("fingerprint"), "evidence": f.get("evidence"), "owner": f.get("owner")}
                  for f in report.get("flags") or []],
        "flags_set_aside": report.get("flags_set_aside"),
        "checklist": {"result": (report.get("checklist") or {}).get("result"),
                      "items": [(i.get("id"), i.get("status"), i.get("pages")) for i in (report.get("checklist") or {}).get("items") or []]},
        "documents": [(d.get("type"), d.get("pages"), d.get("present")) for d in report.get("documents") or []],
        "pages": [(p.get("page"), p.get("document_type"), round(float(p.get("confidence") or 0), 2), bool(p.get("needs_human")))
                  for p in report.get("pages") or []],
        "pages_unaccounted": report.get("pages_unaccounted"),
        "determination_gap": report.get("determination_gap"),
        "self_pension_error": report.get("self_pension_error"),
        "determination_rules": [s.get("rule_id") for s in ((report.get("determination") or {}).get("steps") or [])],
        "unverified_rules_engaged": (report.get("determination") or {}).get("unverified_rules_engaged"),
        "notifications": [(n.get("kind"), n.get("to")) for n in report.get("notifications") or []],
    }


def _findings_gpf(view: dict) -> dict:
    lists = view.get("lists") or {}
    return {"position": view.get("position"),
            "items": {k: [(r.get("id"), r.get("code"), r.get("status"), r.get("title"), r.get("finding"))
                          for r in lists.get(k) or []] for k in sorted(lists)},
            "facts_keys": sorted((view.get("facts") or {}).keys()) if isinstance(view.get("facts"), dict) else None}


def _timings(db_path: Path | str, run_id: str) -> dict:
    con = dbcore.connect(str(db_path))
    try:
        rows = [dict(r) for r in con.execute("SELECT * FROM run_timings WHERE run_id = ? ORDER BY id", (run_id,))]
    finally:
        con.close()
    stages, models = {}, {}
    for r in rows:
        if r["kind"] == "stage":
            stages[r["stage"]] = {"duration_s": r["duration_s"], "pages": r["pages"], "status": r["status"]}
        elif r["kind"] == "model":
            m = models.setdefault(r["stage"], {"calls": 0, "total_s": 0.0, "max_s": 0.0, "errors": 0, "queue_s": 0.0,
                                                "prompt_tokens": 0, "completion_tokens": 0, "by_schema": {}})
            m["calls"] += 1; m["total_s"] = round(m["total_s"] + r["duration_s"], 1); m["max_s"] = max(m["max_s"], r["duration_s"])
            m["errors"] += r["status"] != "ok"; m["queue_s"] = round(m["queue_s"] + (r["queue_s"] or 0.0), 1)
            d = json.loads(r["detail_json"] or "{}")
            m["prompt_tokens"] += d.get("prompt_tokens") or 0; m["completion_tokens"] += d.get("completion_tokens") or 0
            s = m["by_schema"].setdefault(r["name"] or "?", {"calls": 0, "total_s": 0.0})
            s["calls"] += 1; s["total_s"] = round(s["total_s"] + r["duration_s"], 1)
    return {"stages": stages, "models": models, "rows": len(rows), "raw": rows}


def run_pension(case: dict, bench_dir: Path, db_path: Path | str) -> dict:
    import hashlib
    from api import runs
    from pipeline import timing
    pdf = ROOT / case["pdf"]
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()[:12]
    run_dir = bench_dir / "artifacts" / f"run-{digest}"
    if run_dir.exists():
        shutil.rmtree(run_dir)                              # a cold run every time: no checkpoint reuse
    run = runs.Run(run_id=digest, pdf_path=pdf, run_dir=run_dir)
    runs.RUNS[digest] = run
    started = time.time()
    with Sampler() as s:
        runs.execute(run)
    wall = time.time() - started
    report = json.loads((run_dir / "case_report.json").read_text()) if (run_dir / "case_report.json").exists() else {}
    return {"run_id": digest, "state": run.state, "error": run.error, "wall_s": round(wall, 1), "resources": s.summary(),
            "findings": _findings_pension(report), "timings": _timings(db_path, digest),
            "events": [{"stage": e.get("stage"), "message": e.get("message"), "at": e.get("at")} for e in run.events]}


def run_gpf(case: dict, bench_dir: Path, db_path: Path | str) -> dict:
    sys.path.insert(0, str(ROOT / "GP" / "backend"))
    from gpf import api as gpf_api
    pages = json.loads((ROOT / case["pages"]).read_text())
    refs = [p if Path(p).exists() else str(ROOT / p) for p in pages]
    started = time.time()
    with Sampler() as s:
        job = gpf_api.reading_jobs.start(lambda report: gpf_api._read_scans(refs, case["gpf_kind"], "unknown", "ao", on_progress=report),
                                         total=len(refs))
        while job.state not in ("done", "failed", "error"):
            time.sleep(1)
    wall = time.time() - started
    view = (job.result or {}).get("case") if job.state == "done" else {}
    return {"run_id": job.id, "state": job.state, "error": getattr(job, "error", None), "wall_s": round(wall, 1),
            "resources": s.summary(), "findings": _findings_gpf(view or {}), "timings": _timings(db_path, job.id),
            "pages": len(refs)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--cases", default="small,medium,large,gpf")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--allow-active-runs", action="store_true", help="(tests only)")
    args = ap.parse_args(argv[1:])

    active = _trial_runs_active()
    if active and not args.allow_active_runs:
        print(f"refusing: {active} trial run(s) active", file=sys.stderr); return 3
    down = [k for k, u in MODELS.items() if not _healthy(u)]
    if down:
        print(f"refusing: model server(s) not healthy: {down}", file=sys.stderr); return 3
    if args.check_only:
        print("preflight ok: no active trial run; models healthy"); return 0

    bench_dir = ROOT / "artifacts" / "bench" / args.label
    bench_dir.mkdir(parents=True, exist_ok=True)
    db_path = _isolated_target(bench_dir, args.label)
    # Isolation and model addresses, set before api.db (and the GP Fund module) are imported.
    if dbcore.is_postgres(db_path):
        os.environ["PENSION_DATABASE_URL"] = db_path
    else:
        os.environ.pop("PENSION_DATABASE_URL", None)
        os.environ["PENSION_DB"] = db_path
    os.environ.pop("PENSION_TEST_DATABASE_URL", None)
    os.environ["GPF_DB"] = db_path
    os.environ["GPF_DATA_DIR"] = str(bench_dir / "gpf-data")
    os.environ.setdefault("PENSION_VISION_URL", MODELS["vision"] + "/v1/chat/completions")
    os.environ.setdefault("PENSION_OCR_URL", MODELS["ocr"] + "/v1/chat/completions")
    os.environ.setdefault("PENSION_EMBED_URL", MODELS["embed"] + "/v1/embeddings")
    os.environ.setdefault("GPF_VLLM_URLS", ",".join(MODELS.values()) + ",http://192.168.101.10:8001")
    from api import db, runs
    db.migrate()
    runs.ARTIFACTS = bench_dir / "artifacts"; runs.UPLOADS = runs.ARTIFACTS / "uploads"
    runs.ARTIFACTS.mkdir(parents=True, exist_ok=True); runs.UPLOADS.mkdir(parents=True, exist_ok=True)

    summary = {"label": args.label, "started": datetime.now().isoformat(timespec="seconds"), "host": os.uname().nodename,
               "git": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip(),
               "cases": {}}
    for name in args.cases.split(","):
        case = CASES[name]
        print(f"== {name}: {case['note']}", flush=True)
        t0 = time.time()
        try:
            result = run_pension(case, bench_dir, db_path) if case["kind"] == "pension" else run_gpf(case, bench_dir, db_path)
        except Exception as exc:                            # noqa: BLE001
            result = {"state": "bench-error", "error": f"{type(exc).__name__}: {exc}", "wall_s": round(time.time() - t0, 1)}
        result["note"] = case["note"]
        (bench_dir / f"{name}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str))
        summary["cases"][name] = {k: result.get(k) for k in ("run_id", "state", "error", "wall_s", "resources")}
        summary["cases"][name]["stages"] = (result.get("timings") or {}).get("stages")
        summary["cases"][name]["models"] = {k: {kk: vv for kk, vv in v.items() if kk != "by_schema"} for k, v in ((result.get("timings") or {}).get("models") or {}).items()}
        print(f"   {result.get('state')} in {result.get('wall_s')} s", flush=True)
    summary["finished"] = datetime.now().isoformat(timespec="seconds")
    (bench_dir / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
    print(f"written {bench_dir}/summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
