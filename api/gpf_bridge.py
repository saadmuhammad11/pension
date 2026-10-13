"""The GP Fund module, as the case system sees it.

The GP Fund pre-audit module (GP/backend, ``gpf.api``) is its own FastAPI application with its
own reading pipeline, rules engine and case store, on :8201. The case system does not re-implement
any of it: a GP Fund case filed by a department is examined by asking that module to read the
department's scans (``/api/cases/from-scans/start``), the reading job is polled like a pension
run, and the module's own case is what the Accountant General works in afterwards (its web
app, embedded in the portal). What comes back here is only what the case system needs to move
the case: which hard stops want a document from the department, whether anything is open, and
the disposal the officer recorded.

Standard library only (urllib), so the reconciler thread carries no extra dependency. The
module's address is ``PENSION_GPF_URL`` (default http://127.0.0.1:8201).
"""
from __future__ import annotations

import json
import re
import os
import secrets
import threading
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path

GPF_URL = os.environ.get("PENSION_GPF_URL", "http://127.0.0.1:8201").rstrip("/")
TIMEOUT = float(os.environ.get("PENSION_GPF_TIMEOUT", "60"))

#: The kinds of claim the module's reader accepts (its intake select, web/js/app.js).
KINDS = {
    "refundable": "Refundable advance",
    "nonrefundable": "Non-refundable advance",
    "final": "Final payment",
    "death": "Final payment — death",
    "dismissal": "Final payment — dismissal",
    "missing_credits": "Missing credits",
    "balance_transfer": "Balance transfer",
}
GAZETTED = ("unknown", "gazetted", "non-gazetted")

#: The module's officer band an account acts as. The Accounts Officer (level 2) may pass a case
#: for payment; the administrator acts as the DAG (Funds), who may also clear a second return.
#: The administrator has no band: it takes no action in GP Fund (G6).
#: The module's officer band for each portal role (Q3 of 9 Oct 2026: Senior Auditor -> da,
#: Assistant AO and AO -> ao, Deputy AG -> dag; the AG's desk acts as the DAG, so it may clear a
#: hard stop like the Deputy AG).
OFFICER_FOR_ROLE = {"AG_SENIOR_AUDITOR": "da", "AG_ASSISTANT_AO": "ao", "AG_AO": "ao", "AG_REVIEWER": "dag",
                    "AG_DAG": "dag", "DEPT_OFFICER": "da"}


class GpfError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


def header_name(name: str) -> str:
    """An officer's name as the X-GPF-User header carries it: percent-encoded, so a name in
    Urdu or with a diacritic arrives whole instead of as ??? (review N30, 9 Oct 2026); the GP
    Fund module decodes it (gpf/api.py _acting_name). Plain ASCII letters pass unchanged."""
    from urllib.parse import quote
    return quote(" ".join(str(name or "").split()), safe="")


#: The key the module expects on every /api request, so that nothing but the portal and this
#: bridge can reach it (audit of 13 Oct 2026, C-04). Its own copy of this, which must agree on
#: the environment variable and the file and on nothing else, is ``GP/backend/gpf/apikey.py``.
GPF_KEY_HEADER = "X-GPF-Key"
_KEY_FILE = Path(__file__).resolve().parents[1] / "artifacts" / ".gpf_api_key"
#: Resolved once. The portal puts this header on every proxied request, and a case's scans are
#: dozens of them, so reading the file each time would be disk I/O inside the portal's event
#: loop on every page image. ``None`` is cached too: a box that cannot make the key will not
#: start making it on the next request, and the module refuses either way.
_key: str | None = None
_key_read = False
_key_lock = threading.Lock()


def _read_key() -> str | None:
    given = os.environ.get("GPF_API_KEY", "").strip()
    if given:
        return given
    try:
        if _KEY_FILE.exists():
            return _KEY_FILE.read_text(encoding="utf-8").strip() or None
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(32)
        fd = os.open(_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, key.encode("utf-8"))
        finally:
            os.close(fd)
        return key
    except FileExistsError:                           # the module created it a moment ago
        try:
            return _KEY_FILE.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    except OSError:
        return None


def api_key() -> str | None:
    """The shared key: ``GPF_API_KEY`` where the two run apart, else the file they share."""
    global _key, _key_read
    if _key_read:
        return _key
    with _key_lock:
        if not _key_read:
            _key, _key_read = _read_key(), True
    return _key


def forget_key() -> None:
    """Drop the resolved key, so the next call reads it again. For the tests."""
    global _key, _key_read
    with _key_lock:
        _key, _key_read = None, False


def _request(method: str, path: str, *, body: bytes | None = None, content_type: str | None = None,
             timeout: float = TIMEOUT, acting_name: str | None = None) -> dict:
    req = urllib.request.Request(GPF_URL + path, data=body, method=method)
    key = api_key()
    if key:
        req.add_header(GPF_KEY_HEADER, key)
    if content_type:
        req.add_header("Content-Type", content_type)
    if acting_name:
        # The signed-in officer's own name (G6): the module records the action under it, with the
        # band's powers. Header-safe: one line, ASCII where the name is not.
        req.add_header("X-GPF-User", header_name(acting_name))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail") or str(exc)
        except Exception:                                   # noqa: BLE001
            detail = str(exc)
        raise GpfError(exc.code, f"the GP Fund module answered {exc.code}: {detail}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise GpfError(502, f"the GP Fund module on {GPF_URL} is not reachable ({exc}); start it with ./GP/run.sh") from None


def health() -> dict | None:
    try:
        return _request("GET", "/api/health", timeout=3)
    except GpfError:
        return None


# -- pages ---------------------------------------------------------------------------------------

_IMAGE = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def page_images(files: list[Path], out_dir: Path, dpi: int = 200, *, with_keys: bool = False):
    """The department's documents as page images, in filing order: the module's reader takes
    pages, not PDFs. PDFs are rendered with poppler's pdftoppm (already on this machine for the
    pension pipeline); images pass through; anything else is skipped.

    ``with_keys``: also return each page's key -- the sha256 of the document it came from and
    its place in it -- by which the module recognises a page it read in an earlier submission
    of the same case (GP/backend/gpf/reading/page_cache.py)."""
    import hashlib
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[Path] = []
    keys: list[str] = []
    for i, f in enumerate(files, start=1):
        suffix = f.suffix.lower()
        doc_sha = hashlib.sha256(f.read_bytes()).hexdigest() if with_keys else ""
        if suffix in _IMAGE:
            pages.append(f)
            keys.append(f"{doc_sha}:1")
        elif suffix == ".pdf":
            prefix = out_dir / f"d{i:02d}"
            subprocess.run(["pdftoppm", "-r", str(dpi), "-jpeg", str(f), str(prefix)], check=True,
                           capture_output=True, timeout=600)
            rendered = sorted(out_dir.glob(f"d{i:02d}-*.jpg"))
            pages.extend(rendered)
            keys.extend(f"{doc_sha}:{k}" for k in range(1, len(rendered) + 1))
    return (pages, keys) if with_keys else pages


def part_filename(name: str) -> str:
    """A file name safe inside a multipart header: its base name, with the quote, backslash and
    line-break characters that would end the header or the part replaced (audit 6 Oct 2026, L7).
    The department's own name for the paper is kept in the case record; this is transport."""
    base = Path(str(name or "")).name
    cleaned = re.sub(r'["\\\r\n\x00-\x1f\x7f]', "_", base).strip() or "upload"
    return cleaned[:200]


def _multipart(fields: dict[str, str], files: list[Path], extra: dict[str, list[Path]] | None = None) -> tuple[bytes, str]:
    boundary = "----pension" + uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for field, group in (("files", files), *((extra or {}).items())):
        for f in group:
            ctype = "image/jpeg" if f.suffix.lower() in (".jpg", ".jpeg") else "application/octet-stream"
            out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{part_filename(f.name)}\"\r\n"
                    f"Content-Type: {ctype}\r\n\r\n").encode()
            out += f.read_bytes() + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


#: A department files its specimen signature sheet with the claim (30 Sep 2026). It is not a page
#: of the claim -- the reader must not read it as one -- but the specimen the officer compares the
#: sanctioning signature against, so it is recognised by its name and sent apart.
SPECIMEN_NAME = re.compile(r"specimen|\bs\.?\s*signature|signature\s*\(", re.I)


def is_specimen(filename: str) -> bool:
    return bool(SPECIMEN_NAME.search(filename or ""))


def specimen_label(filename: str) -> str:
    """What the specimen is of, from the name the department gave the file (tidied)."""
    stem = re.sub(r"^\d{2}-", "", Path(filename).stem)
    words = " ".join(re.sub(r"[_]+", " ", stem).replace("( ", "(").replace(" )", ")").split())
    return words or "Specimen signature"


# -- the examination -----------------------------------------------------------------------------

def start_examination(files: list[Path], *, kind: str, gazetted: str, officer: str, work_dir: Path,
                      reuse_scope: str = "", specimens: list[Path] | None = None) -> dict:
    """Ask the module to read the pages and open its case. Returns the job view ({jobId, ...}).

    ``reuse_scope`` (the portal's case id, 30 Sep 2026): the module keeps each page's reading
    under this case, and on a resubmission reads only pages it has not seen in the case before.
    """
    if kind not in KINDS:
        raise GpfError(422, f"unknown kind of GP Fund claim {kind!r}; one of {', '.join(KINDS)}")
    pages, keys = page_images(files, work_dir, with_keys=True)
    if not pages:
        raise GpfError(422, "none of the documents could be turned into pages (attach PDFs or scanned images)")
    # The page list in reading order, so the portal can show the page the module is on.
    (work_dir / "pages.json").write_text(json.dumps([str(p) for p in pages]))
    fields = {"kind": kind, "gazetted": gazetted if gazetted in GAZETTED else "unknown", "officer": officer}
    if reuse_scope:
        fields.update({"reuse_scope": reuse_scope, "page_keys": json.dumps(keys)})
    # The department's specimen signature(s), as images, with what each is of.
    spec_images: list[Path] = []
    labels: list[str] = []
    for i, f in enumerate(specimens or [], start=1):
        imgs = page_images([f], work_dir / f"specimen-{i:02d}")
        spec_images += imgs
        labels += [specimen_label(f.name)] * len(imgs)
    if spec_images:
        fields["specimen_labels"] = json.dumps(labels)
    body, ctype = _multipart(fields, pages, {"specimens": spec_images})
    return _request("POST", "/api/cases/from-scans/start", body=body, content_type=ctype, timeout=600)


def job(job_id: str) -> dict:
    """The reading job: state queued|running|done|error, done/total pages, result on success."""
    return _request("GET", f"/api/reading/jobs/{job_id}", timeout=10)


def case(gpf_case_id: str) -> dict:
    """The module's own view of its case: lists of hard stops, observations, verification
    tasks, SAP items; the live position; the officer's disposal."""
    return _request("GET", f"/api/cases/{gpf_case_id}", timeout=10)


def act(gpf_case_id: str, action: str, payload: dict, *, acting_name: str | None = None) -> dict:
    """One officer action on the module's case, as its own screen sends it (30 Sep 2026: the
    portal now draws the GP Fund examination itself). ``action`` is verify | dispositions |
    dispose | sap; the payload carries the officer. The module decides and enforces who may."""
    if action not in ("verify", "dispositions", "dispose", "sap"):
        raise GpfError(400, f"unknown GP Fund action {action!r}")
    return _request("POST", f"/api/cases/{gpf_case_id}/{action}", body=json.dumps(payload).encode(),
                    content_type="application/json", timeout=60, acting_name=acting_name)


def cure(gpf_case_id: str, result_id: str, officer: str, values: dict, file: tuple[str, bytes] | None,
         *, acting_name: str | None = None) -> dict:
    """Cure an item by a document or by values (a QR's payload), as the module's screen does."""
    boundary = "----pension" + uuid.uuid4().hex
    out = bytearray()
    for k, v in {"resultId": result_id, "officer": officer, "values": json.dumps(values or {})}.items():
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    if file is not None:
        name, content = file
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{part_filename(name)}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return _request("POST", f"/api/cases/{gpf_case_id}/cure", body=bytes(out),
                    content_type=f"multipart/form-data; boundary={boundary}", timeout=120, acting_name=acting_name)


def issue_pack(gpf_case_id: str) -> dict:
    return _request("GET", f"/api/cases/{gpf_case_id}/issue-pack", timeout=20)


def sap_template(gpf_case_id: str) -> dict:
    return _request("GET", f"/api/cases/{gpf_case_id}/sap-template", timeout=10)


def issues(view: dict) -> dict:
    """The module's view in the shape the case system moves cases by (api.case_runs.outcome).

    * ``missing_checklist``: hard stops the department can cure by supplying a document (the
      module's ``cure.kind == "doc"``): these send the case back with the list.
    * ``flags_total``: everything else still open -- hard stops of other kinds, verification
      tasks, SAP items, observations not yet disposed of -- which the Accountant General works
      through in the module's own screens.
    * ``clean``: nothing open at all, or the officer passed the case for payment.
    """
    lists = view.get("lists") or {}
    pos = view.get("position") or {}
    missing, other_hard = [], []
    for r in lists.get("hard") or []:
        if (r.get("disposition") or {}).get("action") in ("waive", "correct"):
            continue
        entry = {"id": r.get("code") or r.get("id"), "requirement": r.get("doc") or r.get("title") or r.get("id"),
                 "status": "MISSING", "result_id": r.get("id")}
        if (r.get("cure") or {}).get("kind") == "doc":
            missing.append(entry)
        else:
            other_hard.append(entry)
    open_obs = pos.get("open", 0)
    conf, sap = len(lists.get("conf") or []), len(lists.get("sap") or [])
    flags_total = len(other_hard) + conf + sap + open_obs
    disp = (view.get("caseDisp") or "").lower()
    passed = disp.startswith("passed")
    returned = disp == "returned"
    clean = passed or (not missing and not flags_total)
    return {
        "verdict": "FORWARD" if clean else ("RETURN_FOR_CORRECTION" if (missing or returned) else "HOLD"),
        "blocking_flags": [h["result_id"] for h in other_hard],
        "high_flags": [{"id": h["result_id"], "title": h["requirement"], "class": h["id"]} for h in other_hard],
        "flags_total": flags_total, "missing_checklist": missing,
        "checklist_result": "COMPLETE" if not missing else "INCOMPLETE", "checklist_present": True,
        "unidentified_pages": 0, "has_issues": not clean,
        "gpf": {"case_id": view.get("id"), "version": view.get("version"), "position": pos,
                "disposal": view.get("caseDisp"), "note": view.get("caseNote"),
                # Who disposed of the case in the module (its audit names the signed-in officer, G6).
                "disposed_by": next((a.get("by") for a in reversed(view.get("audit") or [])
                                     if "dispos" in str(a.get("what") or "").lower() or "return" in str(a.get("what") or "").lower()), None),
                "hard": pos.get("hard", 0), "conf": conf, "sap": sap, "adv": pos.get("adv", 0)},
        "gpf_passed": passed, "gpf_returned": returned,
    }


def scratch_dir(case_id: str, submission_no: int) -> Path:
    """Where a case's rendered pages go: beside its documents, under artifacts/cases."""
    from api import db
    return db.ROOT / "artifacts" / "cases" / case_id / f"s{submission_no}-gpf-pages"
