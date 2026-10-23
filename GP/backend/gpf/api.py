"""FastAPI application: the HTTP surface over the case service.

The frontend (a buildless SPA under ``web/``) is served from ``/``. Corpus page
images and evidence crops are served read-only so the examination view can show
the real scans. Every mutating endpoint takes an ``officer`` so the delegation
bands are enforced (there is no real auth in the MVP; wire SSO/LDAP in front in
production).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .engine import OFFICERS
from .clients import ManualUploadConnector, StubModelClient, VllmModelClient
from .reading import Artefact, ALL_TYPES, ReadingPipeline, ingest_pages, to_json_schema
from .reading.jobs import JobRegistry
from .reading.artefacts import CLASSIFY_HINTS
from . import apikey
from .reading.barcodes import NullBarcodeDecoder
from .reference import rules_in_force
from . import doa as doa_mod
from .service import CaseService, ServiceError
from .store import DEFAULT_DB, CaseRepository, DocumentStore, SqliteCaseRepository

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent          # the "GP Fund" project root
DATA_DIR = Path(os.environ.get("GPF_DATA_DIR", BACKEND_DIR / "data"))
WEB_DIR = BACKEND_DIR / "web"
# The DOA register's saved copy: specimens recorded and signatories added survive a restart
# (audit 6 Oct 2026, G5). Loaded now, before the service answers anything.
doa_mod.DOA_PATH = DATA_DIR / "doa.json"
doa_mod.load_register()
PROTO = REPO_ROOT / "prototype"

# ── singletons (swap the repository/connector for Postgres/RFC in production) ──
# Cases live in the shared portal database (29 Sep 2026): GPF_DB names it -- a PostgreSQL URL
# (9 Oct 2026; GP/backend/run.sh takes it from deploy/postgres.env) or a SQLite file, default the
# pension tree's artifacts/portal.sqlite3. GPF_DB set empty keeps the module on its own JSON
# snapshots under GPF_DATA_DIR/cases, which is also where the pre-move snapshots are imported from.
DB_PATH = os.environ.get("GPF_DB")
if DB_PATH is None:
    if not Path(DEFAULT_DB).exists():
        raise RuntimeError("GPF_DB is not set: give the PostgreSQL URL (GP/backend/run.sh reads deploy/postgres.env), "
                           "a SQLite file, or GPF_DB= (empty) for the JSON store")
    DB_PATH = str(DEFAULT_DB)                         # a box still on the file
if DB_PATH:
    repo = SqliteCaseRepository(DB_PATH, import_dir=DATA_DIR / "cases")
    docstore = DocumentStore(DATA_DIR / "uploads", db=repo)
else:
    repo = CaseRepository(snapshot_dir=DATA_DIR / "cases")
    docstore = DocumentStore(DATA_DIR / "uploads")
connector = ManualUploadConnector()
service = CaseService(repo, docstore, connector)
# The signing-authority master store (C1, 9 Oct 2026) is read through the same connection.
from . import signatories as signatories_mod  # noqa: E402
signatories_mod.set_connection(getattr(repo, "conn", None))

# Reading pipeline (stages 1-5). Point GPF_VLLM_URL at the DGX Spark's vLLM server
# to enable real scan reading; otherwise the stub is used and /from-scans returns 503.
# GPF_VLLM_URLS = comma-separated endpoints to auto-discover roles across (vision/OCR/
# embedding on one Spark, reasoning on another). GPF_VLLM_URL = a single endpoint.
_VLLM_URLS = os.environ.get("GPF_VLLM_URLS")
_VLLM_URL = os.environ.get("GPF_VLLM_URL")
_VLLM_TIMEOUT = float(os.environ.get("GPF_VLLM_TIMEOUT", "180"))


def _model_api_key() -> str:
    """The key the model servers ask for (vLLM VLLM_API_KEY; audit 6 Oct 2026, item 7).

    The pipeline's own value, PENSION_MODEL_API_KEY, unless GPF_VLLM_API_KEY overrides it;
    "EMPTY" when neither is set, which a vLLM started without a key accepts.
    """
    key = os.environ.get("GPF_VLLM_API_KEY") or os.environ.get("PENSION_MODEL_API_KEY") or ""
    return key.strip() or "EMPTY"


_VLLM_API_KEY = _model_api_key()
if _VLLM_URLS:
    urls = [u.strip() for u in _VLLM_URLS.split(",") if u.strip()]
    try:
        model_client = VllmModelClient.from_discovery(urls, api_key=_VLLM_API_KEY,
                                                      timeout=_VLLM_TIMEOUT)
    except Exception:
        model_client = StubModelClient()
elif _VLLM_URL:
    try:
        model_client = VllmModelClient.from_server(_VLLM_URL, api_key=_VLLM_API_KEY,
                                                   timeout=_VLLM_TIMEOUT)
    except Exception as exc:
        # The key goes on the fallback too. It did not, so a discovery that failed for ANY
        # reason produced a client with api_key="EMPTY", and every later call came back 401 --
        # the examination reported "Unauthorized" when the truth was that discovery had asked
        # the wrong path and got a 404 (20 Oct 2026). A fallback that quietly drops the
        # credential turns one fault into a different and misleading one.
        print(f"[gpf] model discovery failed ({exc}); using {_VLLM_URL} without it",
              file=sys.stderr)
        model_client = VllmModelClient(_VLLM_URL, api_key=_VLLM_API_KEY, timeout=_VLLM_TIMEOUT)
else:
    model_client = StubModelClient()
# explicit env overrides win over auto-discovery
if isinstance(model_client, VllmModelClient):
    if os.environ.get("GPF_VLLM_VISION_MODEL"):
        model_client.vision_model = os.environ["GPF_VLLM_VISION_MODEL"]
    if os.environ.get("GPF_VLLM_REASONING_MODEL"):
        model_client.reasoning_model = os.environ["GPF_VLLM_REASONING_MODEL"]
reading_pipeline = ReadingPipeline(model_client, NullBarcodeDecoder())
# Scan reads run on a worker thread so the UI can show progress rather than a stalled request.
reading_jobs = JobRegistry()

# The API description pages list every route; the shared deployment switch turns them off in
# production (PENSION_ENV=production, docs/DEPLOYMENT.md F3). GPF_API_DOCS=1 forces them on.
_PRODUCTION = os.environ.get("PENSION_ENV", "").strip().lower() in ("production", "prod")
#: FastAPI's /docs, /redoc and /openapi.json. Off in production; GPF_API_DOCS decides either way
#: outside it, so a trial box can close them without the rest of production's posture
#: (13 Oct 2026) -- it used to be forced on whenever production was off.
_DOCS_FLAG = os.environ.get("GPF_API_DOCS", "").strip().lower()
_DOCS = (_DOCS_FLAG in ("1", "true", "yes") if _DOCS_FLAG else not _PRODUCTION)
app = FastAPI(title="GP Fund AI Pre-Audit Module", version="0.1.0",
              description="Deterministic pre-audit for GP Fund claims (AG Punjab).",
              docs_url="/docs" if _DOCS else None, redoc_url="/redoc" if _DOCS else None,
              openapi_url="/openapi.json" if _DOCS else None)


@app.middleware("http")
async def _require_the_portal_s_key(request: Request, call_next):
    """Every /api request carries the shared key; the portal and the bridge set it.

    The module decides what an officer may do but not who they are -- the portal has already
    settled that and will not pass a request it has refused. This is what stops anything else
    on the box asking the module directly, which until 13 Oct 2026 nothing did (C-04). The web
    UI's own files are not gated: they are served through the same portal and carry no claim.
    """
    path = request.url.path
    if path.startswith("/api") and path not in apikey.OPEN_PATHS:
        if not apikey.presented_is_right(request.headers.get(apikey.HEADER)):
            return JSONResponse(status_code=401, content={
                "detail": "the GP Fund module is reached through the pension portal; "
                          "this request did not come from it"})
    return await call_next(request)


@app.exception_handler(ServiceError)
async def _service_error(_: Request, exc: ServiceError):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


# ── who is acting ─────────────────────────────────────────────────────────────
#: The officer the pension portal has signed in (5 Oct 2026, docs/DEPLOYMENT.md F10). The portal
#: server confirms the AG's sign-in for every /gpf/ request and names the officer in this header,
#: dropping any copy the browser sent; the module listens on loopback only, so nothing else can
#: set it. Where it is present it decides who acts, whatever ``officer`` the page put in the body
#: -- the page's own choice is what an edited frame address could change.
ACTING_OFFICER_HEADER = "x-gpf-officer"
#: The signed-in officer's own name, set by the pension portal's server beside the band (business
#: decision G6, 7 Oct 2026). The module records every action under this name, with the band's
#: powers; without it the band's placeholder name is recorded, as before.
ACTING_USER_HEADER = "x-gpf-user"


def _acting(request: Request, claimed: str) -> str:
    """Who acts: the band the portal fixed (else the one the page claimed), and the officer's own
    name where the portal sent it -- encoded ``band|name``, which ``service._officer`` reads."""
    fixed = (request.headers.get(ACTING_OFFICER_HEADER) or "").strip()
    band = fixed or claimed
    name = _acting_name(request)
    return f"{band}|{name}" if fixed and name else band


def _acting_name(request: Request) -> str:
    """The officer's name from the portal, percent-encoded on the way (review N30, 9 Oct 2026: a
    non-ASCII name arrived as ???); a plain name from an older portal reads unchanged."""
    from urllib.parse import unquote
    raw = (request.headers.get(ACTING_USER_HEADER) or "").strip()
    return unquote(raw).strip() if "%" in raw else raw


# ── request models ────────────────────────────────────────────────────────────
class CreateCase(BaseModel):
    templateKey: str
    withoutSap: bool = False
    officer: str = "ao"


class VerifyBody(BaseModel):
    vid: str
    ok: bool = True
    note: str = ""
    officer: str = "ao"


class DispositionBody(BaseModel):
    resultId: str
    action: str
    ground: str = ""
    authority: str = ""
    officer: str = "ao"


class DisposeBody(BaseModel):
    disposal: str
    note: str = ""
    officer: str = "ao"


class SapTextBody(BaseModel):
    filename: str = "extract.txt"
    text: str
    officer: str = "ao"


class SignatoryBody(BaseModel):
    authorityId: str
    post: str
    name: str = ""
    mayFor: bool = False
    powers: str = ""
    officer: str = "ao"


class OfficerBody(BaseModel):
    officer: str = "ao"


# ── meta ──────────────────────────────────────────────────────────────────────
@app.exception_handler(doa_mod.RegisterDamaged)
async def _register_damaged(request: Request, exc: doa_mod.RegisterDamaged):
    # The saved signatory register could not be read at start-up (review C4): every change to it
    # is refused with the reason, rather than written over the damaged file.
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.get("/api/health")
def health():
    problem = doa_mod.register_problem()
    return {"ok": True, "connector": connector.health().__dict__,
            "model": {"mode": getattr(model_client, "name", "?")},
            "register": {"ok": problem is None, **({"problem": problem} if problem else {})},
            "cases": len(service.repo.list_ids())}


@app.get("/api/model")
def model_status():
    """Detailed model-client status (probes the vLLM endpoints)."""
    return model_client.health()


@app.get("/api/reading/artefacts")
def reading_artefacts():
    return {"types": ALL_TYPES, "hints": {a.value: h for a, h in CLASSIFY_HINTS.items()}}


@app.get("/api/reading/schema/{artefact}")
def reading_schema(artefact: str):
    try:
        art = Artefact(artefact)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown artefact '{artefact}'.")
    return to_json_schema(art)


@app.get("/api/acting")
def acting(request: Request):
    """Who the pension portal says is acting, for the page to show (and to stop it offering a
    choice that the actions would ignore). None where the module is used on its own."""
    return {"officer": (request.headers.get(ACTING_OFFICER_HEADER) or "").strip() or None,
            "name": _acting_name(request) or None}


@app.get("/api/officers")
def officers():
    return OFFICERS


@app.get("/api/rules")
def rules():
    return rules_in_force()


@app.get("/api/intake/checklists")
def intake_checklists(gazetted: str = "unknown"):
    """The papers the department is asked to attach, per kind of claim, so the portal's filing
    screen can show them the way a pension case shows its type's documents (23 Oct 2026).

    Read off the checks themselves (gpf.intake), never a second copy of the list. ``gazetted``
    is what the department has said about the subscriber: on a missing-credits claim it decides
    which manual deduction certificate is wanted, and "unknown" asks for both."""
    from .intake import checklists
    return {"gazetted": gazetted, "kinds": checklists(gazetted)}


@app.get("/api/doa")
def doa():
    return service.doa_register()


@app.get("/api/signatories/{spec_id}/image", include_in_schema=False)
def signatory_specimen_image(spec_id: str):
    """A specimen from the shared master store, beside the signature as read. The frame this page
    runs in is the AG's side only (the portal signs it in); never cached (C1)."""
    path = signatories_mod.specimen_path(spec_id)
    if path is None:
        raise HTTPException(404, "no such specimen")
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(str(path), media_type=media, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/api/citations/search")
def citations_search(q: str, k: int = 5):
    """Cite the circular clauses / rules / clarifications most relevant to a query."""
    from .citations import search as cite_search
    return cite_search(q, max(1, min(k, 20)), model_client)


# ── intake ────────────────────────────────────────────────────────────────────
@app.get("/api/case-templates")
def case_templates():
    return service.list_templates()


@app.get("/api/cases")
def list_cases():
    return service.list_cases()


@app.post("/api/cases")
def create_case(request: Request, body: CreateCase):
    cid = service.create_case(body.templateKey, without_sap=body.withoutSap, officer_id=_acting(request, body.officer))
    return {"id": cid, "case": service.view(cid)}


#: What a stored scan may be, by its first bytes, and the type it is served as. Anything else was
#: kept under its own name and served inline on the portal's address through /gpf/ -- an .html
#: or .js "specimen" became a page or a script there (audit 6 Oct 2026).
_SCAN_TYPES = ((b"%PDF", "application/pdf"), (b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG", "image/png"),
               (b"GIF8", "image/gif"), (b"II*\x00", "image/tiff"), (b"MM\x00*", "image/tiff"),
               (b"BM", "image/bmp"))


def _scan_type(head: bytes) -> str | None:
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    return next((t for magic, t in _SCAN_TYPES if head.startswith(magic)), None)


def _serve_stored(path: Path) -> FileResponse:
    """A stored scan as the image or PDF its bytes say it is; anything else only as a download."""
    with path.open("rb") as fh:
        media = _scan_type(fh.read(16))
    headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}
    if media is None:
        return FileResponse(path, media_type="application/octet-stream", filename=path.name, headers=headers)
    return FileResponse(path, media_type=media, headers=headers)


async def _store_scans(files: list[UploadFile]) -> list[str]:
    """Save the upload and return the page refs, in the order they were sent. Pages and specimen
    signatures are scans: a PDF or an image, by content, or the request is refused."""
    import uuid as _uuid
    scan_id = "scan-" + _uuid.uuid4().hex[:8]
    refs = []
    for f in files:
        content = await f.read()
        if _scan_type(content[:16]) is None:
            raise HTTPException(status_code=422, detail=f"{f.filename or 'a file'} is not a PDF or an image")
        meta = docstore.save(scan_id, f.filename or "page", content)
        refs.append(str((DATA_DIR / "uploads" / meta["storedAs"])))
    return refs


def _read_scans(refs: list[str], kind: str, gazetted: str, officer: str,
                on_progress=None, reuse_scope: str = "", page_keys: Optional[list[str]] = None,
                specimens: Optional[list[dict]] = None, into_case: str = "") -> dict:
    """Stages 1-5 -> facts -> an open case. Shared by the sync and the job path, so the
    two cannot drift into producing different cases from the same scans.

    ``reuse_scope`` and ``page_keys`` (from the portal, 30 Sep 2026): a page read in an earlier
    submission of the same case is taken from the page cache (reading.page_cache). Without
    them every page is read, as it always was."""
    cache = None
    if reuse_scope and page_keys:
        from .reading.page_cache import PageCache
        cache = PageCache(DATA_DIR / "page_cache", reuse_scope)
    result = reading_pipeline.run(ingest_pages(refs), kind=kind, gazetted=gazetted,
                                  on_progress=on_progress, cache=cache, page_keys=page_keys)
    # into_case: the module case the portal already holds for this claim. A resubmission is a
    # second ROUND of one examination, not a second examination (H-19) -- see
    # service.create_case_from_facts for what carries across and what does not.
    cid = service.create_case_from_facts(result.facts, meta={"label": f"{kind.title()} (from scans)"},
                                         officer_id=officer,   # callers resolve _acting() first
                                         into=into_case or None)
    # The case's own pages, in reading order, so its evidence can be shown (30 Sep 2026: every
    # scanned claim's evidence images were blank -- the screen looked for them among the demo cases').
    save_page_refs(cid, refs)
    if specimens:
        save_specimens(cid, specimens)
    return {"id": cid, "needsHuman": result.needs_human, "illegiblePages": result.illegible_pages,
            "reusedPages": result.reused_pages, "pagesTotal": len(refs),
            "case": service.view(cid)}


@app.post("/api/cases/from-scans")
async def create_case_from_scans(request: Request, kind: str = Form(...), gazetted: str = Form("unknown"),
                                 officer: str = Form("ao"), files: list[UploadFile] = File(...)):
    """Open a case by reading uploaded scans through the pipeline (stages 1-5 -> facts).

    Synchronous: it holds the request open for the whole read, which on a real file is a
    minute or more. Kept for scripts and for `eval_reading.py`; the UI uses the job pair
    below so it can show progress instead of a dead screen.

    Requires a vision model (set GPF_VLLM_URLS); with the stub it returns 503.
    """
    refs = await _store_scans(files)
    try:
        return _read_scans(refs, kind, gazetted, _acting(request, officer))
    except NotImplementedError as e:
        raise HTTPException(status_code=503,
                            detail="Reading pipeline needs the vision model. Set GPF_VLLM_URL to the "
                                   "DGX Spark's vLLM server. (" + str(e) + ")")


@app.post("/api/cases/from-scans/start", status_code=202)
async def start_case_from_scans(request: Request, kind: str = Form(...), gazetted: str = Form("unknown"),
                                officer: str = Form("ao"), files: list[UploadFile] = File(...),
                                reuse_scope: str = Form(""), page_keys: str = Form(""),
                                specimens: list[UploadFile] = File(default=[]), specimen_labels: str = Form(""),
                                into_case: str = Form("")):
    """Same read, started on a worker thread. Returns a job to poll.

    The upload itself is consumed here, before returning, so the request body is fully
    read while the connection is still open -- a background thread cannot go back for it.
    """
    refs = await _store_scans(files)
    # The department's specimen signature(s), filed with the claim (30 Sep 2026): kept with the
    # case and shown beside every signature the officer must check against the DOA register.
    spec_refs = await _store_scans(specimens) if specimens else []
    try:
        spec_labels = [str(x) for x in json.loads(specimen_labels)] if specimen_labels else []
    except ValueError:
        spec_labels = []
    spec = [{"path": r, "label": (spec_labels[i] if i < len(spec_labels) else "Specimen signature")}
            for i, r in enumerate(spec_refs)]
    keys = None
    if reuse_scope and page_keys:
        try:
            keys = [str(k) for k in json.loads(page_keys)]
        except ValueError:
            raise HTTPException(status_code=422, detail="page_keys must be a JSON list")
        if len(keys) != len(refs):
            raise HTTPException(status_code=422, detail="page_keys must name every page, in order")
    job = reading_jobs.start(
        lambda report: _read_scans(refs, kind, gazetted, _acting(request, officer), on_progress=report,
                                   reuse_scope=reuse_scope, page_keys=keys, specimens=spec,
                                   into_case=into_case),
        total=len(refs))
    return job.view()


@app.get("/api/reading/jobs/{job_id}")
def reading_job(job_id: str):
    """Poll a reading job. 404 once it has aged out of the registry."""
    job = reading_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such reading job (it may have expired).")
    return job.view()


PAGE_REFS = DATA_DIR / "page_refs"


def save_page_refs(case_id: str, refs: list[str]) -> None:
    PAGE_REFS.mkdir(parents=True, exist_ok=True)
    (PAGE_REFS / f"{case_id}.json").write_text(json.dumps([str(r) for r in refs]))


SPECIMENS = DATA_DIR / "case_specimens"


def save_specimens(case_id: str, specimens: list[dict]) -> None:
    SPECIMENS.mkdir(parents=True, exist_ok=True)
    (SPECIMENS / f"{case_id}.json").write_text(json.dumps(specimens))


def case_specimens(case_id: str) -> list[dict]:
    path = SPECIMENS / f"{case_id}.json"
    if not path.exists() or "/" in case_id or ".." in case_id:
        return []
    try:
        return json.loads(path.read_text())
    except ValueError:
        return []


def page_refs(case_id: str) -> list[str]:
    path = PAGE_REFS / f"{case_id}.json"
    if not path.exists() or "/" in case_id or ".." in case_id:
        return []
    try:
        return json.loads(path.read_text())
    except ValueError:
        return []


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, request: Request):
    # The band of the officer asking, where the portal sent it: what may be done to each
    # observation and to the case is judged against the reader, not against whoever acted last
    # (audit 13 Oct 2026). Absent, the answer is unchanged from before.
    view = service.view(case_id, (request.headers.get(ACTING_OFFICER_HEADER) or "").strip() or None)
    # Pages of a claim read from scans are served by the case itself (below); the demo cases'
    # pages stay under /assets/pages.
    view["pageImages"] = bool(page_refs(case_id))
    # The department's specimen beside each signature to be checked against the DOA register.
    # The comparison is the officer's: nothing here judges the ink.
    spec = case_specimens(case_id)
    if spec:
        view["specimens"] = [{"n": i + 1, "label": x.get("label")} for i, x in enumerate(spec)]
        for name in ("hard", "adv", "conf", "ok"):
            for item in view["lists"].get(name, []):
                if not str(item.get("id", "")).startswith("DOA:"):
                    continue
                item["evidence"] = list(item.get("evidence") or []) + [
                    {"url": f"api/cases/{case_id}/specimens/{i + 1}", "specimen": True,
                     "label": f"Specimen signature on file — {x.get('label')}"} for i, x in enumerate(spec)]
                if item.get("finding"):
                    item["finding"] = item["finding"].replace(
                        "No specimen signature is on the register yet.",
                        "The department's specimen signature, filed with the case, is shown beside it: compare them.")
    return view


@app.get("/api/cases/{case_id}/specimens/{n}")
def case_specimen(case_id: str, n: int):
    """A specimen signature filed with this claim, as an image."""
    spec = case_specimens(case_id)
    if n < 1 or n > len(spec):
        raise HTTPException(status_code=404, detail="No such specimen on this case.")
    path = Path(spec[n - 1]["path"]).resolve()
    if not str(path).startswith(str(DATA_DIR.resolve()) + "/") or not path.is_file():
        raise HTTPException(status_code=404, detail="The specimen is no longer on the server.")
    return _serve_stored(path)


@app.get("/api/cases/{case_id}/pages/{page}")
def case_page(case_id: str, page: int):
    """One page of a claim read from scans, 1-based in the order it was read."""
    refs = page_refs(case_id)
    if not refs or page < 1 or page > len(refs):
        raise HTTPException(status_code=404, detail=f"No page {page} on this case.")
    path = Path(refs[page - 1]).resolve()
    allowed = [DATA_DIR.resolve(), (REPO_ROOT.parent / "artifacts" / "cases").resolve()]
    if not any(str(path).startswith(str(a) + "/") for a in allowed) or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Page {page} is no longer on the server.")
    return _serve_stored(path)


# ── SAP extracts ──────────────────────────────────────────────────────────────
@app.post("/api/cases/{case_id}/sap")
def upload_sap(request: Request, case_id: str, body: SapTextBody):
    diff = service.upload_sap(case_id, body.filename, body.text, officer_id=_acting(request, body.officer))
    return {"diff": diff, "case": service.view(case_id)}


@app.post("/api/cases/{case_id}/sap-file")
async def upload_sap_file(request: Request, case_id: str, officer: str = Form("ao"), file: UploadFile = File(...)):
    text = (await file.read()).decode("utf-8", errors="replace")
    diff = service.upload_sap(case_id, file.filename, text, officer_id=_acting(request, officer))
    return {"diff": diff, "case": service.view(case_id)}


class PayslipBalancesBody(BaseModel):
    gpfBalance: Optional[float] = None
    loanBalance: Optional[float] = None
    basis: str = ""
    officer: str = "ao"


@app.post("/api/cases/{case_id}/payslip-balances")
def payslip_balances(request: Request, case_id: str, body: PayslipBalancesBody):
    """Fill the pay slip balances the first reading missed (service.refresh_payslip_balances)."""
    res = service.refresh_payslip_balances(case_id, body.gpfBalance, body.loanBalance, basis=body.basis,
                                           officer_id=_acting(request, body.officer))
    return {**res, "case": service.view(case_id)}


@app.get("/api/cases/{case_id}/sap-template")
def sap_template(case_id: str):
    from .sap import parse_sap_text  # noqa: F401 (import kept local)
    view = service.view(case_id)
    pn = view["sap"].get("personnelNo") or view["meta"].get("personnelNo") or ""
    tmpl = ("SAP EXTRACT: PAY SLIP\nPersonnel No: " + pn +
            "\nName: \nDesignation: \nCNIC: \nMonth: \nBPS: \nDDO Code: \nGPF No: \nOld GPF No: "
            "\nGPF Balance: \nGPF Subscription: \nGPF Loan Instalment: \nGPF Loan Balance: \nBasic Pay: \nOSD Post: "
            "\n\nSAP EXTRACT: GPF FINAL RE-CALCULATION REPORT\nPersonnel No: " + pn +
            "\nReport Date: \nStart Date|End Date|Opening Balance|Monthly Subscription|Adjustments|"
            "Temp Advance|Rec of Temp Advance|Permanent Advance|Interest Applied|Closing Balance\n")
    return {"template": tmpl}


# ── cure by upload / verification ─────────────────────────────────────────────
@app.post("/api/cases/{case_id}/cure")
async def cure(request: Request, case_id: str, resultId: str = Form(...), officer: str = Form("ao"),
               values: str = Form("{}"), file: Optional[UploadFile] = File(None)):
    try:
        parsed = json.loads(values or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="values must be JSON")
    content = await file.read() if file is not None else None
    filename = file.filename if file is not None else None
    diff = service.cure(case_id, resultId, parsed, filename=filename, content=content, officer_id=_acting(request, officer))
    return {"diff": diff, "case": service.view(case_id)}


@app.post("/api/cases/{case_id}/verify")
def verify(request: Request, case_id: str, body: VerifyBody):
    diff = service.verify(case_id, body.vid, body.ok, body.note, officer_id=_acting(request, body.officer))
    return {"diff": diff, "case": service.view(case_id)}


# ── dispositions and disposal ─────────────────────────────────────────────────
@app.post("/api/cases/{case_id}/dispositions")
def set_disposition(request: Request, case_id: str, body: DispositionBody):
    res = service.set_disposition(case_id, body.resultId, body.action, ground=body.ground,
                                  authority=body.authority, officer_id=_acting(request, body.officer))
    return {"result": res, "case": service.view(case_id)}


@app.post("/api/cases/{case_id}/dispose")
def dispose(request: Request, case_id: str, body: DisposeBody):
    res = service.dispose(case_id, body.disposal, note=body.note, officer_id=_acting(request, body.officer))
    return {"result": res, "case": service.view(case_id)}


@app.get("/api/cases/{case_id}/issue-pack")
def issue_pack(case_id: str):
    return service.issue_pack(case_id)


# ── DOA admin ─────────────────────────────────────────────────────────────────
@app.post("/api/doa/specimens")
async def doa_specimen(request: Request, sigId: str = Form(...), officer: str = Form("ao"), file: UploadFile = File(...)):
    content = await file.read()
    return service.doa_add_specimen(None, sigId, file.filename, content, officer_id=_acting(request, officer))


@app.post("/api/doa/signatories")
def doa_signatory(request: Request, body: SignatoryBody):
    return service.doa_add_signatory(body.authorityId, body.post, name=body.name,
                                     may_for=body.mayFor, powers=body.powers, officer_id=_acting(request, body.officer))


@app.post("/api/doa/finalize")
def doa_finalize(request: Request, body: OfficerBody):
    return service.doa_finalize(officer_id=_acting(request, body.officer))


# ── corpus assets (read-only page images + evidence crops) ────────────────────
if (PROTO / "pages").exists():
    app.mount("/assets/pages", StaticFiles(directory=PROTO / "pages"), name="pages")
if (PROTO / "evidence").exists():
    app.mount("/assets/evidence", StaticFiles(directory=PROTO / "evidence"), name="evidence")
if (PROTO / "sap-samples").exists():
    app.mount("/assets/sap-samples", StaticFiles(directory=PROTO / "sap-samples"), name="sap-samples")


# ── frontend (must be mounted LAST so /api and /assets win) ────────────────────
@app.get("/")
def index():
    idx = WEB_DIR / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse({"detail": "Frontend not built yet. API is live at /api/health."})


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
