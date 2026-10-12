"""Pilot API: runs the pipeline for real and streams stage events. BUILD §4, §5.1.

    GET  /api/runs                 every case run here, newest first, with its decision
    POST /api/runs                 upload a PDF, start a run           -> {"run_id": ...}
    GET  /api/runs/{id}/events     server-sent events, one per stage
    GET  /api/runs/{id}/report     the finished case report
    GET  /api/runs/{id}/status
    POST /api/runs/{id}/checklist-actions  name a document, waive or clear a checklist item
    POST /api/runs/{id}/recompute  rebuild stage 7 + report from the artefacts (no model)
    GET  /api/runs/{id}/bundle     what a zipped case was built from, attachment by attachment
    GET  /api/specimens            the specimen-signature register (rules/specimens)
    GET  /api/rules/open           open rule items, provisional values, confirmations
    POST /api/rules/confirm        an authorised desk confirms a rule value, citing authority
    /api/v2/...                    the multi-department case system (api.v2): login, cases,
                                   workflow, admin. Its own users and database (api.db).
    GET  /api/gpu                  live GPU utilisation
    GET  /api/health

Run it with the interpreter that already has FastAPI and the CUDA stack:

    /home/tmc/vllm_env/bin/python3 -m api.server 8110

What this replaces
------------------
The portal's Analysis screen previously replayed a finished run on a 420 ms timer. It looked
like a live pipeline and was not one: no request left the browser and nothing touched the GPU.
This server makes the button do the work it claims to. An upload starts a real run, every stage
reports as it happens, and ``/api/gpu`` lets the console show utilisation while the vision model
reads the pages.

A 43-page file takes about ten minutes. That is the honest number, and BUILD §3.1 is explicit
about why: the Spark's decode is memory-bandwidth-limited, so "do not promise sub-minute
turnaround on a 46-page case in the pilot. Measure it, then promise."

Jobs run on a thread rather than Celery. BUILD §4 specifies Celery + Redis and that remains the
production target; the pipeline's own stage checkpoints already provide the resumability §5.1
asks for, so the queue can be swapped in without touching the stages. Re-posting the same PDF
resumes from its artefacts instead of recomputing nine minutes of inference.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Form, HTTPException, Header, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from .runs import (RUNS, Run, adopt_from_disk, completed_run_ids,
                   gpu_utilisation, start_run, summarise)

ROOT = Path(__file__).resolve().parent.parent

from api import settings as _settings

# The API's own description pages list every route; production turns them off (docs/DEPLOYMENT.md F3).
_DOCS = _settings.api_docs()
app = FastAPI(title="AG Punjab AI Pension Portal — pilot API", version="0.1.0",
              docs_url="/docs" if _DOCS else None, redoc_url="/redoc" if _DOCS else None,
              openapi_url="/openapi.json" if _DOCS else None)

# The portal is served by Vite on another port during development. In the AG office both sit
# behind one origin, so this is a development affordance and not the deployed posture.
# Deployed, the portal and the API share one origin through the portal server, so no
# cross-origin access is needed; PENSION_CORS_ORIGINS="http://host:5300" opens it for a dev server.
_CORS = [o for o in os.environ.get("PENSION_CORS_ORIGINS", "").split(",") if o.strip()]
if _CORS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )


@app.get("/api/health")
def health() -> JSONResponse:
    """The database, the disk, the model servers and GP Fund (api.health). 503 when the API cannot
    do its job; a model or GP Fund being down is reported as ``degraded`` but does not fail it."""
    from api.health import report
    body, status = report()
    return JSONResponse(body, status_code=status)


@app.get("/api/gpu")
def gpu() -> dict:
    """Live GPU and unified-memory numbers, straight from nvidia-smi and /proc/meminfo."""
    return gpu_utilisation()


@app.get("/api/cases")
def case_register() -> list[dict]:
    """Every case the office has seen, newest first. SOP §4.2 monitoring.

    Read from disk rather than the registry so the list survives a restart -- see
    ``api.cases``. This is what the register screen shows.

    It overlaps ``/api/runs`` and does not replace it: ``/api/runs`` reports a run, this
    reports a CASE, with its status derived from the decision log beside the report. Both
    read the same run directories, so neither can drift from the other.
    """
    from api.cases import register
    from api.runs import ARTIFACTS
    live = {
        r.run_id: {"state": r.state, "started_at": r.started_at, "error": r.error,
                   "file": r.pdf_path.name}
        for r in RUNS.values()
    }
    live.update(_stopped_before_reporting(ARTIFACTS, live))
    return register(ARTIFACTS, live)


def _stopped_before_reporting(artifacts: Path, live: dict) -> dict:
    """Runs whose artefacts exist but which never produced a report, and are not running now.

    ``api.cases.summarise`` returns None for a run directory with no ``case_report.json`` and
    no live entry, so such a case DISAPPEARS from the register. That is the wrong failure: on
    22 Sep 2026 three cases were killed mid-stage by a restart, and because the process had
    forgotten them and no report had been written, the register showed seventeen cases where
    the office had taken up twenty. A case that was taken up and stopped is precisely what
    "proper monitoring for proper disposal" (SOP §4.2) has to show; silence reads as a case
    nobody ever started.

    Reported as FAILED, which is the register's existing word for "stopped before it produced
    a report" -- no new status is invented, because the screen that renders these is a
    verbatim copy and knows only the six it already has. The artefacts are untouched and the
    run resumes from its own checkpoints when it is taken up again.
    """
    stopped: dict[str, dict] = {}
    for run_dir in artifacts.glob("run-*"):
        run_id = run_dir.name.removeprefix("run-")
        if not run_dir.is_dir() or run_id in live:
            continue
        if (run_dir / "case_report.json").exists():
            continue                      # finished: the report speaks for it
        manifest = run_dir / "manifest.json"
        if not manifest.exists():
            continue                      # nothing was ever ingested; not a case yet
        started, source = "", ""
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            started = m.get("started_at") or m.get("at") or ""
            source = m.get("file") or m.get("source_file") or ""
        except (OSError, ValueError):
            pass
        stopped[run_id] = {
            "state": "failed", "started_at": started, "file": source,
            "error": "The run stopped before it produced a report. Its artefacts are intact; "
                     "taking the case up again resumes from the last completed stage.",
        }
    return stopped


@app.get("/api/roles")
def roles() -> list[dict]:
    """The parties named by SOP §4 and what each may do.

    The two parties here are the ones the SOP names; ``/api/desks`` lists the nine desks
    inside them that this build actually checks against. ``api.desks`` maps one onto the
    other, so a decision claimed by a party is recorded against a desk.
    """
    from api.roles import LABELS, PERMISSIONS, ROLES
    return [{"id": r, "label": LABELS[r], "permissions": list(PERMISSIONS[r])}
            for r in ROLES]


@app.get("/api/runs")
def list_runs() -> list[dict]:
    """Every case this office has run, newest first, with the decision taken on each.

    This is what the intake screen's history panel reads. It carries the engine's verdict and
    the officer's decision side by side: the second is not a copy of the first, and a list
    that showed only the recommendation would claim cases were disposed of that are still
    sitting undecided.
    """
    # Finished runs are brought back from disk first, so a restart does not hide the cases
    # the office has already processed. adopt_from_disk leaves anything already in RUNS
    # alone, so a live run is never replaced by its own artefacts mid-flight.
    for known in completed_run_ids():
        adopt_from_disk(known)
    return [
        summarise(r)
        for r in sorted(RUNS.values(), key=lambda r: r.started_at, reverse=True)
    ]


def _desk_for(action: str, stated: str | None, request: Request | None = None) -> str:
    """The desk id for the request, or a 403 carrying the SOP paragraph. api.desks.

    Over HTTP every request here is signed in (``_v1_requires_a_token`` puts the account on
    ``request.state.user``), and the desk must be one that account holds. Without a request --
    a direct call from a test of the permission table -- the stated desk is checked alone.
    """
    from api.desks import DeskNotAuthorised, desk_for_account, require_desk
    user = _signed_in(request)
    try:
        if user is not None:
            return desk_for_account(action, user.role, stated)
        return require_desk(action, stated)
    except DeskNotAuthorised as exc:
        raise HTTPException(403, str(exc)) from None


def _signed_in(request: Request | None):
    """The case-system account behind this request, where the token middleware found one."""
    return getattr(getattr(request, "state", None), "user", None) if request is not None else None


def _refuse_recompute_behind_a_decision(run_id: str, verb: str = "rebuilt") -> None:
    """A run that belongs to a case is rebuilt, or otherwise changed, only while that case is
    still open on it.

    The old route had no idea of the case: an administrator could rebuild the report behind an
    approved or rejected case, or behind a run the case had already moved on from, and the
    register would show figures nobody had decided on (audit 6 Oct 2026, C3). The same held for
    the old dispositions, checklist actions and removal until 12 Oct 2026: the Deputy AG could
    change the overlay a decision rested on, through a door the case system keeps shut. A run
    with no case (the old register's own uploads) is unaffected.
    """
    from api import db as _db
    from api import workflow
    conn = _db.connect()
    try:
        link = conn.execute(
            "SELECT c.case_no, c.status, c.current_run_id FROM case_runs cr JOIN cases c ON c.id = cr.case_id "
            "WHERE cr.run_id = ? ORDER BY cr.started_at DESC, cr.id DESC LIMIT 1", (run_id,)).fetchone()
    finally:
        conn.close()
    if link is None:
        return
    if link["status"] in (workflow.APPROVED, workflow.REJECTED):
        raise HTTPException(409, f"case {link['case_no']} is {link['status'].lower()}; the report it was decided on "
                                 f"is part of that decision and is not {verb}")
    if link["current_run_id"] and link["current_run_id"] != run_id:
        raise HTTPException(409, f"case {link['case_no']} has moved on to a newer examination; "
                                 f"this run's report is history and is not {verb}")


def _officer(request: Request | None, typed: str) -> str:
    """Who is recorded as acting: the signed-in account's name, never one typed into the request."""
    user = _signed_in(request)
    return user.display_name if user is not None else typed


def _audit_v1(request: Request, action: str, run_id: str, after: dict | None = None, reason: str = "") -> None:
    """An audit-log row for a state change on the old routes, under the signed-in account (F6)."""
    user = _signed_in(request)
    if user is None:
        return
    from api import db as _db
    from api import workflow
    from api.v2 import _client_address
    conn = _db.connect()
    try:
        workflow.audit(conn, actor=user, action=action, entity_type="run", entity_id=run_id,
                       before=None, after=after, reason=reason, ip=_client_address(request))
    finally:
        conn.close()


@app.get("/api/desks")
def desks() -> dict:
    """The desks the SOP names and the actions each may perform (SOP §4, BUILD §11.1)."""
    from api.desks import permissions_table
    return permissions_table()


@app.get("/api/variants")
def variants() -> dict:
    """The case variants an officer picks from at intake, grouped by case family."""
    from rules.checklist import CASE_FAMILY_VARIANTS, VARIANT_LABELS, requirements_for
    return {
        "families": [
            {
                "id": family,
                "label": family.replace("_", " ").title(),
                "variants": [
                    {"id": v, "label": VARIANT_LABELS[v], "documents": len(requirements_for(v))}
                    for v in vs
                ],
            }
            for family, vs in CASE_FAMILY_VARIANTS.items()
        ]
    }


def _intake_choices(variant: str | None, annual_pay: str | None,
                    commutation_percent: str | None, retirement_date: str | None,
                    pension_in_payment: str | None, date_of_death: str | None,
                    x_desk: str | None, request: Request | None = None) -> dict:
    """Check the officer's intake entries and the desk making them; return them for ``start_run``.

    The same figures decide the same pension whatever the file, so they are checked in one
    place before any run starts.
    """
    from rules.checklist import ALL_VARIANTS
    _desk_for("intake", x_desk, request)
    if variant or (annual_pay or "").strip() or (commutation_percent or "").strip() \
            or (retirement_date or "").strip() or (pension_in_payment or "").strip() \
            or (date_of_death or "").strip():
        _desk_for("intake_choices", x_desk, request)
    for label, value in (("retirement_date", retirement_date), ("date_of_death", date_of_death)):
        if (value or "").strip():
            try:
                date.fromisoformat(value.strip())
            except ValueError:
                raise HTTPException(422, f"{label} must be YYYY-MM-DD") from None
    if (pension_in_payment or "").strip():
        digits = pension_in_payment.replace(",", "").strip()
        if not digits.replace(".", "", 1).isdigit():
            raise HTTPException(422, "pension_in_payment must be a rupee amount")
    if variant and variant not in ALL_VARIANTS:
        raise HTTPException(422, f"unknown case variant {variant!r}; have {list(ALL_VARIANTS)}")
    # {"2023": "58000", "2024": "60500", "2025": "62550"} -- three figures, three years.
    pay: dict = {}
    if annual_pay:
        try:
            pay = {str(k): str(v) for k, v in json.loads(annual_pay).items()}
        except (ValueError, AttributeError):
            raise HTTPException(422, "annual_pay must be a JSON object of year -> amount") from None
    return {
        "variant": variant,
        "annual_pay": pay,
        "commutation_percent": (commutation_percent or "").strip(),
        "retirement_date": (retirement_date or "").strip(),
        "pension_in_payment": (pension_in_payment or "").replace(",", "").strip(),
        "date_of_death": (date_of_death or "").strip(),
    }


def _legacy_writes_or_403() -> None:
    """The old register records nothing in production unless asked to (N23): every filing and
    every decision goes through a case, with its department and its second officer."""
    from api import settings as _settings
    if not _settings.legacy_register_writes():
        raise HTTPException(403, "the old register is read-only here; file and decide the case in the portal")


@app.post("/api/runs", status_code=202)
async def create_run(
    request: Request,
    file: UploadFile,
    variant: str | None = Form(default=None),
    annual_pay: str | None = Form(default=None),
    commutation_percent: str | None = Form(default=None),
    retirement_date: str | None = Form(default=None),
    pension_in_payment: str | None = Form(default=None),
    date_of_death: str | None = Form(default=None),
    case_type: str | None = Form(default=None),
    x_desk: str | None = Header(default=None),
) -> dict:
    """Accept a scanned case file and start the pipeline on it.

    ``case_type`` is the declared case type (config/case_types.json), which any desk may state:
    it selects the checklist and the rules directly, and the papers are checked against it.

    ``variant`` is the AG office checklist column, chosen by the officer. It cannot be read
    off the bundle, so it is supplied rather than inferred; without it the run still produces
    a document list, but no checklist.

    The department, the Pension Facilitation Centre and the Auditor may submit a file
    (SOP §4.1, §4.3, §4.4); only the Auditor, Pension Wing, selects the variant or supplies
    pay and commutation figures (SOP §4.4(1)-(2)). The desk is the ``X-Desk`` header.
    """
    _legacy_writes_or_403()
    choices = _intake_choices(variant, annual_pay, commutation_percent, retirement_date,
                              pension_in_payment, date_of_death, x_desk, request)
    from rules.case_type import OFFICE_CASE_TYPES, canonical_office_type
    declared = canonical_office_type((case_type or "").strip() or None)
    if (case_type or "").strip() and not declared:
        raise HTTPException(422, f"unknown case type {case_type!r}; have {list(OFFICE_CASE_TYPES)}")
    body = await file.read()
    # A case arrives either as one scanned PDF or as the documents that make it up -- a
    # folder of loose scans the officer zipped.
    # The zip is merged into one case file by the run itself.
    from pipeline.bundle import looks_like_pdf, looks_like_zip
    if not (looks_like_pdf(body) or looks_like_zip(body)):
        raise HTTPException(415, "not a PDF or a zip of documents")
    if len(body) > 256 * 1024 * 1024:
        raise HTTPException(413, "file exceeds 256 MB")
    if looks_like_pdf(body):
        from api.v2 import pdf_page_count
        pages = pdf_page_count(body)
        if pages is not None and pages > _settings.max_case_pages():
            raise HTTPException(413, f"the file has {pages} pages; the most one file may have is {_settings.max_case_pages()}")
    desk = _desk_for("intake", x_desk, request)
    started = start_run(body, file.filename or "case.pdf",
                        source={"kind": "upload", "file": file.filename or "case.pdf",
                                "desk": desk, "officer": _officer(request, "")},
                        case_type=declared, **choices)
    _audit_v1(request, "V1_RUN_UPLOAD", str(started.get("run_id", "")) if isinstance(started, dict) else "",
              after={"file": file.filename, "desk": desk})
    return started


@app.get("/api/runs/{run_id}/status")
def run_status(run_id: str) -> dict:
    run = _get(run_id)
    return {"run_id": run.run_id, "state": run.state, "error": run.error,
            "events": len(run.events), "started_at": run.started_at,
            "finished_at": run.finished_at}


@app.get("/api/runs/{run_id}/report")
def run_report(run_id: str) -> Any:
    run = _get(run_id)
    path = run.run_dir / "case_report.json"
    if not path.exists():
        return JSONResponse({"error": "report not ready", "state": run.state}, status_code=409)
    from api.checklist_actions import apply
    from rules.scope import scrub_report
    return scrub_report(apply(json.loads(path.read_text()), run.run_dir))


@app.post("/api/runs/{run_id}/remove")
def run_remove(request: Request, run_id: str, body: dict = Body(default={}),
               x_desk: str | None = Header(default=None)) -> dict:
    """The register's "×": take a case off the register. Nothing is deleted.

    The run directory -- papers, report, decisions -- stays on disk, and ``removed.json`` beside
    it says who removed it and when. A case still being read cannot be removed; one read again
    later comes back (``api.cases.is_removed``).
    """
    # The case system's doors stay shut here too (audit of 12 Oct 2026): no legacy write in
    # production, and none behind a decision or on a run the case has moved on from.
    _legacy_writes_or_403()
    _refuse_recompute_behind_a_decision(run_id, verb="changed")
    import re
    from api.cases import REMOVED
    from api.desks import DESKS
    from api.runs import ARTIFACTS
    from datetime import datetime
    from pipeline.ingest import atomic_write_text
    desk = _desk_for("intake", x_desk or str(body.get("role") or ""), request)
    if not re.fullmatch(r"[0-9a-f]{6,64}", run_id):
        raise HTTPException(404, f"no case {run_id}")
    run_dir = ARTIFACTS / f"run-{run_id}"
    if not run_dir.is_dir():
        raise HTTPException(404, f"no case {run_id}")
    live = RUNS.get(run_id)
    if live and live.state in ("queued", "running"):
        raise HTTPException(409, "this case is still being read; it can be removed once it stops")
    entry = {"run_id": run_id, "removed_by": _officer(request, str(body.get("officer") or "")),
             "desk": DESKS.get(desk, desk), "reason": str(body.get("reason") or ""),
             "removed_at": datetime.now().isoformat(timespec="seconds")}
    atomic_write_text(run_dir / REMOVED, json.dumps(entry, indent=2, ensure_ascii=False))
    _audit_v1(request, "V1_RUN_REMOVE", run_id, after={"desk": desk}, reason=entry["reason"])
    return entry


@app.get("/api/runs/{run_id}/decision")
def read_decision(run_id: str) -> dict:
    """The decision in force on this case, and the full audit trail behind it."""
    from api.decisions import current_decision, decisions_for
    run = _get(run_id)
    return {
        "run_id": run_id,
        "current": current_decision(run.run_dir),
        "history": decisions_for(run.run_dir),
    }


@app.post("/api/runs/{run_id}/decision", status_code=201)
def make_decision(request: Request, run_id: str, body: dict = Body(...),
                  x_desk: str | None = Header(default=None)) -> dict:
    """Record an officer's decision. Append-only; nothing is ever overwritten.

    A second decision on the same case is allowed and is recorded as a further entry rather
    than replacing the first -- a case that was returned and later forwarded has a history,
    and erasing it would erase the reason the case moved.

    Only the Auditor, Pension Wing, and the DAG (Pension) record decisions (SOP §4.4(6),
    §4.6). The desk is ``role`` in the body, or the ``X-Desk`` header where the body has none;
    the entry records the desk's label as the portal prints it.
    """
    _legacy_writes_or_403()
    from api.decisions import DecisionError, record_decision
    from api.desks import DESKS
    stated = str(body.get("role") or "") or x_desk
    role_label = DESKS[_desk_for("decide", stated, request)]
    run = _get(run_id)
    report_path = run.run_dir / "case_report.json"
    if not report_path.exists():
        raise HTTPException(409, "no case report yet; the run has not produced one to decide on")
    from api.checklist_actions import apply
    report = apply(json.loads(report_path.read_text()), run.run_dir)
    try:
        entry = record_decision(
            run.run_dir,
            run_id=run_id,
            action=str(body.get("action", "")),
            officer=_officer(request, str(body.get("officer", ""))),
            role=role_label,
            justification=str(body.get("justification", "")),
            report=report,
        )
    except DecisionError as exc:
        raise HTTPException(422, str(exc)) from None
    _audit_v1(request, "V1_DECISION", run_id, after={"action": entry.get("action"), "desk": role_label},
              reason=str(body.get("justification", "")))
    run.emit("decision", f"{entry['action']} by {entry['officer']}"
                         + (" (override)" if entry["overrides_recommendation"] else ""))
    return entry


@app.get("/api/runs/{run_id}/bundle")
def run_bundle(run_id: str) -> Any:
    """What the case file was built from: one line per attachment, with its page range.

    404 where the case was uploaded as a single PDF -- there was no bundle, and saying so is
    better than inventing a one-line manifest that implies there was.
    """
    run = _get(run_id)
    path = run.run_dir / "bundle.json"
    if not path.exists():
        raise HTTPException(404, "this case was submitted as a single PDF, not as a bundle")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/runs/{run_id}/pages/{page}", include_in_schema=False)
def page_image(run_id: str, page: int):
    """The rendered image of one page, so a finding can be checked against the paper.

    A finding names the page it was read from -- "the card at p.2", "Annex-A contradicts the
    FRC" -- and until now the officer had to go and find that page in the original PDF. The
    whole point of citing a page is that somebody can look at it.
    """
    run = _get(run_id)
    manifest_path = run.run_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(404, "this run has no rendered pages")
    for p in json.loads(manifest_path.read_text()).get("pages", []):
        if int(p.get("page", 0)) == page:
            img = run.run_dir / p["image_path"]
            if img.is_file():
                return FileResponse(img, media_type="image/png")
            break
    raise HTTPException(404, f"no rendered image for page {page} of this run")


@app.get("/api/specimens")
def specimen_register() -> dict:
    """The specimen-signature register (rules/specimens): whose signature each post is."""
    from rules import specimens
    return {"specimens": [{
        "id": s.id, "department": s.department, "post": s.post, "officer": s.officer,
        "scope": s.scope, "effective_from": s.effective_from.isoformat(),
        "effective_to": s.effective_to.isoformat() if s.effective_to else None,
        "cite": s.cite, "images": [p.name for p in s.images], "authority": s.authority,
    } for s in specimens.load()]}


@app.get("/api/specimens/{specimen_id}/images/{name}", include_in_schema=False)
def specimen_image(request: Request, specimen_id: str, name: str) -> FileResponse:
    # Specimens are for the AG's side and the administrator only (C1, Q6); the token middleware
    # has put the account on the request. The portal uses /api/v2/signatories/... now.
    from api.signatories import viewer_roles
    user = getattr(request.state, "user", None)
    if user is None or user.role not in viewer_roles():
        raise HTTPException(403, "specimen signatures are for the Accountant General's desk")
    from rules import specimens
    spec = next((s for s in specimens.load() if s.id == specimen_id), None)
    path = next((p for p in (spec.images if spec else ()) if p.name == name), None)
    if path is None or not path.exists():
        raise HTTPException(404, "no such specimen image")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/runs/{run_id}/signatures/{name}", include_in_schema=False)
def signature_image(run_id: str, name: str) -> FileResponse:
    """The sanctioning signature cut from a form page (pipeline.signatory)."""
    import re
    from api.runs import ARTIFACTS
    if not re.fullmatch(r"[A-Z_]+-p\d+\.jpg", name):
        raise HTTPException(404, "no such signature")
    path = ARTIFACTS / f"run-{run_id}" / "signatures" / name
    if not re.fullmatch(r"[0-9a-f]{6,64}", run_id) or not path.exists():
        raise HTTPException(404, "no such signature")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/runs/{run_id}/dispositions")
def read_dispositions(run_id: str) -> dict:
    """How each finding has been disposed of, and whether the pension may yet be computed."""
    from api.dispositions import calculation_gate, current, history
    run = _get(run_id)
    report_path = run.run_dir / "case_report.json"
    from api.checklist_actions import apply
    report = apply(json.loads(report_path.read_text()), run.run_dir) if report_path.exists() else {}
    return {
        "run_id": run_id,
        "current": current(run.run_dir),
        "history": history(run.run_dir),
        "gate": calculation_gate(report, run.run_dir),
    }


@app.post("/api/runs/{run_id}/dispositions", status_code=201)
def make_disposition(request: Request, run_id: str, body: dict = Body(...)) -> dict:
    """Record an officer's disposition of ONE finding. Append-only.

    The pension is gated on every finding being cleared, so this is the endpoint that moves
    a case toward a determination. It refuses a waiver without a written ground for the same
    reason the case-level override does: waiving a HIGH finding is the one act here that
    lets money move past a check designed to stop it.
    """
    # The case system's doors stay shut here too (audit of 12 Oct 2026): no legacy write in
    # production, and none behind a decision or on a run the case has moved on from.
    _legacy_writes_or_403()
    _refuse_recompute_behind_a_decision(run_id, verb="changed")
    from api.dispositions import DispositionError, calculation_gate, current, record
    run = _get(run_id)
    report_path = run.run_dir / "case_report.json"
    if not report_path.exists():
        raise HTTPException(409, "no case report yet; there are no findings to dispose of")
    from api.checklist_actions import apply
    report = apply(json.loads(report_path.read_text()), run.run_dir)

    flag_id = str(body.get("flag_id", "")).strip()
    flag = next((f for f in report.get("flags", []) if f.get("id") == flag_id), None)
    if flag is None:
        raise HTTPException(
            404, f"this case has no finding {flag_id!r}; it raised "
                 f"{[f['id'] for f in report.get('flags', [])]}")
    try:
        entry = record(
            run.run_dir, run_id=run_id, flag_id=flag_id,
            action=str(body.get("action", "")), officer=_officer(request, str(body.get("officer", ""))),
            role=_party(request, str(body.get("role", ""))), ground=str(body.get("ground", "")), flag=flag,
        )
    except DispositionError as exc:
        raise HTTPException(422, str(exc)) from None
    _audit_v1(request, "V1_DISPOSITION", run_id, after={"flag_id": flag_id, "action": entry.get("action")},
              reason=str(body.get("ground", "")))

    gate = calculation_gate(report, run.run_dir)
    run.emit("disposition", f"{flag_id} {entry['action']} by {entry['officer']}")
    return {**entry, "gate": gate, "current": current(run.run_dir)}


@app.get("/api/runs/{run_id}/checklist-actions")
def read_checklist_actions(run_id: str) -> dict:
    """The officer's actions on this case's checklist, oldest first, and those in force."""
    from api import checklist_actions
    run = _get(run_id)
    return {"run_id": run_id, "history": checklist_actions.history(run.run_dir),
            "current": checklist_actions.current(run.run_dir)}


@app.post("/api/runs/{run_id}/checklist-actions", status_code=201)
def make_checklist_action(request: Request, run_id: str, body: dict = Body(...)) -> dict:
    """Name a document on its pages, name a page the checklist does not ask for, waive an item,
    or clear one of those. Append-only (api.checklist_actions)."""
    # The case system's doors stay shut here too (audit of 12 Oct 2026): no legacy write in
    # production, and none behind a decision or on a run the case has moved on from.
    _legacy_writes_or_403()
    _refuse_recompute_behind_a_decision(run_id, verb="changed")
    from api import checklist_actions
    from api.dispositions import calculation_gate
    run = _get(run_id)
    report_path = run.run_dir / "case_report.json"
    if not report_path.exists():
        raise HTTPException(409, "no case report yet; there is no checklist to act on")
    report = json.loads(report_path.read_text())
    try:
        entry = checklist_actions.record(
            run.run_dir, run_id=run_id, report=report, action=str(body.get("action", "")),
            officer=_officer(request, str(body.get("officer", ""))), role=_party(request, str(body.get("role", ""))),
            item_id=(str(body["item_id"]) if body.get("item_id") else None),
            pages=body.get("pages") or [], document_name=str(body.get("document_name", "")),
            ground=str(body.get("ground", "")),
            name_id=(str(body["name_id"]) if body.get("name_id") else None))
    except checklist_actions.ChecklistActionError as exc:
        raise HTTPException(422, str(exc)) from None
    _audit_v1(request, "V1_CHECKLIST_ACTION", run_id,
              after={"action": entry.get("action"), "item_id": entry.get("item_id")}, reason=str(body.get("ground", "")))
    applied = checklist_actions.apply(report, run.run_dir)
    run.emit("checklist", f"{entry['action']} {entry.get('item_id') or entry.get('document_name')} "
                          f"by {entry['officer']}")
    from rules.scope import scrub_report
    return {**entry, "report": scrub_report(applied), "gate": calculation_gate(applied, run.run_dir)}


@app.post("/api/runs/{run_id}/recompute")
def recompute_run(request: Request, run_id: str, x_desk: str | None = Header(default=None)) -> Any:
    """Rebuild the determination and the report from the artefacts already on disk.

    For a case to catch up with a rule value confirmed since it ran. Nothing is re-read from
    the pages; a run still in progress is refused rather than raced. The Pension Wing desks,
    the DAG, the reference-data administrator and the system administrator may ask for it;
    the desks that only submit, sign or read may not (SOP §4).
    """
    from api.runs import recompute
    desk = _desk_for("recompute", x_desk, request)
    run = _get(run_id)
    if run.state in ("queued", "running"):
        raise HTTPException(409, "the run is still in progress; recompute it once it has finished")
    _refuse_recompute_behind_a_decision(run_id)
    try:
        result = recompute(run)
    except FileNotFoundError as exc:
        raise HTTPException(409, str(exc)) from None
    _audit_v1(request, "V1_RECOMPUTE", run_id, after={"desk": desk})
    return result


@app.get("/api/reports/disposal")
def disposal_report() -> dict:
    """SOP §8.4: the statement the DAG (Pension) places before the AG -- cases disposed of,
    returned and held; overrides with their grounds; cases that could not be determined and
    why, by class. Read-only, from the artefacts; open to every desk (the Audit Office reads
    it for the Annual Certification Audit, §4.7)."""
    from api.reports import disposal_statement
    for known in completed_run_ids():
        adopt_from_disk(known)
    return disposal_statement(r.run_dir for r in RUNS.values())


@app.get("/api/rules/open")
def rules_open() -> dict:
    """Every open rule item, each value with its provisional figure and any confirmation."""
    from rules.confirmations import open_items
    return {"items": open_items()}


@app.post("/api/rules/confirm", status_code=201)
def rules_confirm(request: Request, body: dict = Body(...),
                  x_desk: str | None = Header(default=None)) -> dict:
    """Record that an authorised desk has confirmed a rule value, citing its authority.

    Append-only, like a decision. The desk is the one stated at sign-in and is restricted on
    that claim -- the same footing every decision in this build stands on until Keycloak.
    """
    from rules.confirmations import ConfirmationError, NotAuthorised, record_confirmation
    stated = str(body.get("role") or x_desk or "")
    if _signed_in(request) is not None:
        stated = _desk_for("confirm_rule", stated, request)        # a desk this account holds
    try:
        entry = record_confirmation(
            item=str(body.get("item", "")),
            key=str(body.get("key", "")),
            value=str(body.get("value", "")),
            officer=_officer(request, str(body.get("officer", ""))),
            role=stated,
            authority=str(body.get("authority", "")),
            note=str(body.get("note", "")),
        )
    except NotAuthorised as exc:
        raise HTTPException(403, str(exc)) from None
    except ConfirmationError as exc:
        raise HTTPException(422, str(exc)) from None
    _audit_v1(request, "V1_RULE_CONFIRM", f"{body.get('item', '')}/{body.get('key', '')}",
              after={"value": str(body.get("value", "")), "desk": stated}, reason=str(body.get("authority", "")))
    return entry


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> EventSourceResponse:
    """Stage events as they happen. Replays the backlog first, then follows live.

    Replaying matters: a browser that reconnects, or an officer who opens the case after the
    run started, must see the whole trail rather than joining halfway. The events are the
    audit-visible account of what the pipeline did.
    """
    run = _get(run_id)

    async def stream():
        sent = 0
        while True:
            if await request.is_disconnected():
                return
            with run.lock:
                backlog = run.events[sent:]
            for ev in backlog:
                sent += 1
                yield {"data": json.dumps(ev, ensure_ascii=False)}
                if ev["stage"] == "end":
                    return
            await asyncio.sleep(0.4)

    return EventSourceResponse(stream())


def _party(request: Request | None, typed: str) -> str:
    """The SOP §4 party a signed-in account acts for on a finding or a checklist item: the
    Accounts Office, as the case system records it (api.v2). Without a sign-in, what was typed."""
    return "ACCOUNTS_OFFICE" if _signed_in(request) is not None else typed


def _get(run_id: str) -> Run:
    run = RUNS.get(run_id)
    if run is None:
        # A finished run outlives the process that produced it: the report, the events it
        # ended on and the decision log are all in its run directory. Only 404 once the
        # disk agrees there is nothing there.
        run = adopt_from_disk(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    return run


# -- the multi-department case system ------------------------------------------------------------
from api.v2 import router as _v2_router  # noqa: E402

app.include_router(_v2_router)
from api.signatories import router as _signatories_router  # noqa: E402  -- signing authorities (C1, 9 Oct 2026)
app.include_router(_signatories_router)

#: The old portal's routes carry no sign-in of their own. Now that every case belongs to a
#: department, they are reachable only with a case-system token; the handful of reference
#: routes the run script and the portals need stay open.
_OPEN_V1 = ("/api/health", "/api/gpu", "/api/variants", "/api/v2/")

MAX_REQUEST_BYTES = _settings.MAX_REQUEST_BYTES


@app.middleware("http")
async def _uploads_need_a_session_first(request: Request, call_next):
    """An upload to the case system is refused before its body is read unless it carries a live
    session. FastAPI parses -- and spools to disk -- a multipart body before the route's own
    sign-in check runs, so anyone could make the server take 520 MB per request on the way to a
    401 (audit 6 Oct 2026). The old /api/* routes check the token first in their own middleware."""
    if (request.method in ("POST", "PUT", "PATCH") and request.url.path.startswith("/api/v2/")
            and request.headers.get("content-type", "").lower().startswith("multipart/")):
        from starlette.concurrency import run_in_threadpool
        from api import auth, db
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""

        def check() -> int | None:
            if not token:
                return 401
            conn = db.connect()
            try:
                auth.user_for_token(token, conn)
            except auth.AuthError as exc:
                return exc.status
            finally:
                conn.close()
            return None
        refused = await run_in_threadpool(check)
        if refused:
            return JSONResponse({"detail": "sign in before uploading documents"}, status_code=refused)
    return await call_next(request)


@app.middleware("http")
async def _oversized_requests_are_refused_early(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_REQUEST_BYTES:
        return JSONResponse({"detail": f"the request exceeds {MAX_REQUEST_BYTES // 1048576} MB"}, status_code=413)
    return await call_next(request)


@app.middleware("http")
async def _api_responses_are_never_cached(request: Request, call_next):
    """Case data must not survive in a browser cache after sign-out: Back must not show it."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.middleware("http")
async def _v1_requires_a_token(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not any(path == p or path.startswith(p) for p in _OPEN_V1):
        from api import db as _db
        from api.auth import AuthError, _bearer, user_for_token
        token = _bearer(request.headers.get("authorization"))
        # ``?token=`` exists for <img> and EventSource, which cannot send a header: reads only. A
        # token on the address of a write lands in proxy and browser history and in any log of
        # the address, and a link alone could then record a decision (audit 6 Oct 2026, L12).
        if not token and request.method in ("GET", "HEAD"):
            token = request.query_params.get("token")
        if not token:
            detail = ("sign in at your portal; this address needs a case-system token" if request.method in ("GET", "HEAD")
                      else "a change needs the token in the Authorization header, not on the address")
            return JSONResponse({"detail": detail}, status_code=401)
        conn = _db.connect()
        try:
            user = user_for_token(token, conn)
        except AuthError as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status)
        finally:
            conn.close()
        from api.auth import PASSWORD_CHANGE_DUE, password_change_due
        if password_change_due(user, path):
            return JSONResponse({"detail": PASSWORD_CHANGE_DUE}, status_code=403)
        # The routes take the desk and the officer's name from this account (api.desks, F2).
        request.state.user = user
        # The old routes know nothing of departments: a run there is any run. So they are for
        # the administrator, and read-only for the Pension Wing; a department officer's token
        # opens only the case system, which scopes every run to its case.
        # Writes on the old register are the Deputy AG's (G6: the administrator takes no case
        # action); the administrator and the reviewers read.
        # The wing's tiers (C3) read nothing here either. The old register knows no wing and no
        # tier: a Senior Auditor of one wing could list every run and open any wing's report
        # and page scans, and an AO could read a case not yet sent up to the AO (audit of 12 Oct
        # 2026). Their reads go through the case system, which scopes every run to its case.
        from api import workflow as _wf
        allowed = user.role == "AG_DAG" or (user.role in ("AG_REVIEWER", "ADMIN") and request.method in ("GET", "HEAD"))
        if not allowed:
            detail = ("the old register is not for the wing's tiers; open the case in the case system"
                      if user.role in _wf.TIER_ROLES
                      else "this address is read-only for your role; case actions are taken in the case system")
            return JSONResponse({"detail": detail}, status_code=403)
    return await call_next(request)


@app.on_event("startup")
def _v2_startup() -> None:
    """The case database is migrated and seeded, and the run reconciler started, with the API.

    Nothing here touches the old portal's routes or artefacts.
    """
    import traceback
    from api import auth, case_runs, db, legacy
    if _settings.production():
        # Outside the try below on purpose: a server that would sign forgeable sessions must not
        # come up at all (uvicorn exits when a start-up handler raises).
        auth.require_production_secret()
    try:
        db.migrate()
        db.seed()
        if _settings.production():
            _production_startup_checks()
        # The old portal's runs are no longer brought in (the office started the register fresh
        # on 25 Sep 2026); PENSION_IMPORT_LEGACY=1 before start brings them back under LEGACY.
        if os.environ.get("PENSION_IMPORT_LEGACY", "").lower() in ("1", "true", "yes"):
            legacy.import_legacy_runs()
        # The signing-authority master store (scope change C1, 9 Oct 2026): the two legacy registers
        # imported where missing, and the pension export the pipeline reads written and activated.
        from api import signatories as _signatories
        added = _signatories.start_up()
        if added["pension"] or added["gpf"]:
            print(f"[v2] signing authorities imported: {added}", flush=True)
        # Cases filed before the case type existed (29 Sep 2026) take the AI's reading, marked DETECTED.
        filled = case_runs.backfill_case_types()
        if filled:
            print(f"[v2] case type backfilled from the last verification on {filled} case(s)", flush=True)
        # Submission rounds (30 Sep 2026): records for cases filed before they existed. Inserts only.
        from api import rounds
        conn = db.connect()
        try:
            added = rounds.backfill(conn)
        finally:
            conn.close()
        if added:
            print(f"[v2] submission-round records backfilled: {added} row(s)", flush=True)
    except Exception:                                 # noqa: BLE001
        # Loud, with the traceback: a silent failure here once left the service up with no seed.
        print("[v2] STARTUP FAILED -- the case system may be incomplete:\n" + traceback.format_exc(), flush=True)
        if _settings.production():
            # Production does not serve on a half-migrated or unseeded database: uvicorn exits when
            # a start-up handler raises, and systemd's restart and the journal take it from there
            # (audit 6 Oct 2026). The trial keeps running, as before, so a slip there is not an outage.
            raise
    # The reconciler runs regardless: a case mid-verification must still be moved on.
    case_runs.start_reconciler()


def _production_startup_checks() -> None:
    """What production refuses to go live with, said once at start-up (docs/DEPLOYMENT.md §3.0)."""
    from api import auth, db
    conn = db.connect()
    try:
        shared = auth.shared_logins(conn)
        flagged = auth.flag_weak_passwords(conn)
    finally:
        conn.close()
    if shared:
        # F12 (decision C1, 7 Oct 2026): named logins for every reviewer. A shared login records
        # nobody's decision, so production does not start with one active.
        print(f"[v2] production refuses to start: shared login(s) still active: {', '.join(shared)}. "
              f"Disable them and create named accounts (`python3 -m api.db add-reviewer ...`).", flush=True)
        raise SystemExit(1)
    if flagged:
        print(f"[v2] production: {len(flagged)} account(s) on a shared or obvious password must change it at "
              f"next sign-in: {', '.join(flagged[:10])}{' …' if len(flagged) > 10 else ''}", flush=True)
    if db.CREDENTIALS_CSV.exists():
        print(f"[v2] production: the plaintext sign-in sheet {db.CREDENTIALS_CSV} is still on disk; hand the "
              f"passwords out, then run `python3 -m api.db forget-credentials`", flush=True)


if __name__ == "__main__":
    import sys

    import uvicorn

    if _settings.production():
        from api import auth
        try:
            auth.require_production_secret()
        except auth.InsecureSecret as exc:
            print(f"[v2] production: refusing to start: {exc}", file=sys.stderr, flush=True)
            sys.exit(1)

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8110
    # No access log: document and event URLs carry the session token on the query string, and an
    # access log would keep every one of them.
    # Loopback only: every client comes through the portal server on :5184. PENSION_API_BIND=0.0.0.0
    # exposes the API directly (not recommended: it lets callers bypass the proxy's headers).
    uvicorn.run(app, host=os.environ.get("PENSION_API_BIND", "127.0.0.1"), port=port, log_level="info", access_log=False)
