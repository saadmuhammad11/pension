"""The reading pipeline: stages 1-5, then assemble the case facts (spec §3, §4.3).

    ingest ─► (OCR) ─► classify ─► extract ─► barcodes ─► ASSEMBLE ─► facts
      1          2          3          4          5

Stages 1-5 turn scans into structured extractions; the assembler merges them
into the exact facts object the rules engine consumes. The language model is
used only in stages 3-4 (classify + extract) and only through
schema-constrained calls; stage 5 is deterministic (no model). Any extracted
field below its confidence threshold is flagged for a person — the model never
auto-accepts an account number, CNIC, date or amount (spec §0 rule 3, §4.5).

In Phase 1 the case facts ship as fixtures; this pipeline is the path that will
produce them from real scans once the DGX Spark serves the models. It runs
end-to-end today with a `ScriptedModelClient`, which is how the reading->facts->
rules seam is tested.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..clients.model_client import ExtractedField, ModelClient
from . import sanction_claim
from .artefacts import Artefact
from .barcodes import BarcodeDecoder, DecodedCode, NullBarcodeDecoder


#: Pages read at once. Each page is two model calls and a local barcode decode, and no page
#: needs anything another page produced, so this is the same shape of work the pension
#: pipeline fans out in stage 3.
#:
#: 4 by default, not more: these servers also carry the pension pipeline, which runs up to
#: PENSION_MAX_CONCURRENT_RUNS cases at PENSION_IDENTIFY_CONCURRENCY each. The budget is
#: shared and this is the smaller claim on it. GPF_READ_CONCURRENCY=1 restores the serial
#: read exactly, which is the first thing to try if a result ever looks order-dependent.
def read_concurrency() -> int:
    try:
        return max(1, int(os.environ.get("GPF_READ_CONCURRENCY") or 4))
    except ValueError:
        return 4


# ── stage 1: ingest ───────────────────────────────────────────────────────────
@dataclass
class Page:
    number: int
    image_ref: str
    dpi: Optional[int] = None
    rotation: int = 0
    quality: Optional[float] = None
    illegible: bool = False


def ingest_pages(image_refs: list[str], *, dpi: int = 300) -> list[Page]:
    """Stage 1 — image handling, no AI. (Deskew/quality scoring plug in here.)"""
    return [Page(number=i + 1, image_ref=ref, dpi=dpi) for i, ref in enumerate(image_refs)]


# ── per-page result ───────────────────────────────────────────────────────────
@dataclass
class PageResult:
    page: int
    artefact: str
    classify_confidence: float
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    codes: list[DecodedCode] = field(default_factory=list)
    needs_human: list[str] = field(default_factory=list)


@dataclass
class ReadingResult:
    pages: list[PageResult]
    facts: dict
    needs_human: list[dict]     # [{page, artefact, field, confidence, threshold}]
    illegible_pages: list[int]
    #: Pages taken from the case's page cache rather than read (a resubmission).
    reused_pages: list[int] = field(default_factory=list)


# ── progress reporting ────────────────────────────────────────────────────────
# A progress event. `done` counts pages finished, so done/total is a real fraction and
# not a guess; `stage` names which of the five stages is running; `message` is the line
# an operator reads. The callback protocol is deliberately a plain dict: it crosses a
# thread boundary into the API's job registry, and dataclasses there buy nothing.
Progress = dict
ProgressFn = Callable[[Progress], None]


def _label(artefact: str) -> str:
    """The artefact type as a person would say it, for the progress line."""
    return str(artefact).replace("_", " ").lower()


# ── the pipeline ──────────────────────────────────────────────────────────────
class ReadingPipeline:
    def __init__(self, model: ModelClient, barcodes: Optional[BarcodeDecoder] = None):
        self.model = model
        self.barcodes = barcodes or NullBarcodeDecoder()

    def run(self, pages: list[Page], *, kind: Optional[str] = None,
            gazetted: str = "unknown",
            on_progress: Optional[ProgressFn] = None,
            cache=None, page_keys: Optional[list[str]] = None) -> ReadingResult:
        """Read `pages` into a facts object.

        `on_progress`, if given, is called at each stage boundary with a plain dict
        (see `Progress`). It exists because stages 3 and 4 are one vision-model call
        per page each: on a real case that is a minute or more of silence, and an
        officer watching a dead screen cannot tell a slow model from a hung one. The
        callback is advisory — it never changes what is read, and an exception raised
        inside it is the caller's problem, not the pipeline's.
        """
        page_results: list[PageResult] = []
        needs_human: list[dict] = []
        illegible: list[int] = []
        reused: list[int] = []
        total = len(pages)
        # A resubmission (page_cache): the portal names each page by its document and place in
        # it; a page read in an earlier round of this case is taken from the cache.
        keys = page_keys if (cache is not None and page_keys and len(page_keys) == total) else None

        def emit(**ev):
            if on_progress:
                on_progress({"total": total, **ev})

        # `done` counts pages FINISHED, not the loop index. With pages read together they
        # finish out of order, and a bar fed an index walks backwards (jobs.Job.done takes
        # whatever it is given). Counting completions keeps it monotonic whatever order the
        # model answers in.
        # ...and `in_flight` says how many pages are with the model right now. Completed pages
        # alone make a bar that sits at nothing while four pages work and then jumps by four,
        # which an officer reads as stuck. The two together let the screen show what is
        # finished and what is under way, which is the honest shape of a parallel read.
        _finished = 0
        _in_flight = 0
        _counts = threading.Lock()

        def emit_running(**ev):
            with _counts:
                d, f = _finished, _in_flight
            emit(done=d, in_flight=f, **ev)

        def started():
            nonlocal _in_flight
            with _counts:
                _in_flight += 1

        def ended():
            nonlocal _in_flight
            with _counts:
                _in_flight = max(0, _in_flight - 1)

        def emit_done(**ev):
            nonlocal _finished
            with _counts:
                _finished += 1
                d, f = _finished, _in_flight
            emit(done=d, in_flight=f, **ev)

        emit(stage="ingest", done=0, page=None,
             message=f"{total} page{'s' if total != 1 else ''} received")

        def read_one(i: int, pg: Page) -> dict:
            """Everything this stage does with one page, and nothing another page needs.

            Two model calls -- classify, then extract for whatever classify said the page is --
            and a local barcode decode. The only shared thing it touches is the page cache,
            which keys one file per page, so two pages never write the same file.
            """
            out: dict = {"page": pg.number, "result": None, "needs_human": [],
                         "illegible": False, "reused": False}
            if pg.illegible:
                out["illegible"] = True
                emit_done(stage="illegible", page=pg.number,
                          message=f"Page {pg.number} is illegible — skipped")
                return out
            hit = cache.get(keys[i]) if keys else None
            if hit is not None:
                from .page_cache import codes_from, fields_from
                artefact = str(hit["artefact"])
                fields = fields_from(hit, pg.number)
                gated = []
                for name, ef in fields.items():
                    if ef.needs_human:
                        gated.append(name)
                        out["needs_human"].append({"page": pg.number, "artefact": artefact, "field": name,
                                                   "confidence": ef.confidence, "threshold": ef.threshold})
                out["result"] = PageResult(page=pg.number, artefact=artefact,
                                           classify_confidence=float(hit.get("classify_confidence") or 0.0),
                                           fields=fields, codes=codes_from(hit, pg.number),
                                           needs_human=gated)
                out["reused"] = True
                emit_done(stage="page-done", page=pg.number, artefact=artefact, reused=True,
                          message=f"Page {pg.number} of {total} — {_label(artefact)}, unchanged since the last submission")
                return out
            # From here the page is in the model's hands, and the screen counts it as
            # under way. In a finally, so a page that raises does not leave the bar
            # claiming it is still being read.
            started()
            try:
                # stage 3: classify
                emit_running(stage="classify", page=pg.number,
                             message=f"Page {pg.number} of {total} — identifying the document")
                from . import timing
                with timing.stage("classify", page=pg.number):
                    cls = self.model.classify_document(pg.image_ref)
                artefact = str(cls.value)
                # A page claimed as the sanction is asked to show that it is one. Two classes
                # describe a page with a QR code and only one is the sanction, so the back of
                # a smart CNIC was read as SANCTION_ORDER_QR at 0.95 and the case recorded its
                # sanction there (PC-2026-000070 page 8, 24 Oct 2026). See reading.sanction_claim
                # for what settles it and why a page that did not read keeps its classification.
                if sanction_claim.is_a_sanction_claim(artefact):
                    try:
                        settled, why = sanction_claim.settle(artefact, self.model.ocr_text(pg.image_ref))
                    except Exception:                      # noqa: BLE001 -- the reading stands
                        settled, why = artefact, ""
                    if settled != artefact:
                        out["needs_human"].append({"page": pg.number, "artefact": artefact,
                                                   "field": "document type", "confidence": cls.confidence,
                                                   "threshold": cls.confidence, "why": why})
                        artefact = settled
                # And the same question the other way round (26 Oct 2026, PC-2026-000063): a
                # page the classifier would not name, whose text says in terms that a GP Fund
                # advance is sanctioned, is the sanction. UNKNOWN reaches no merger, so such a
                # page left no mark at all and the claim reported no sanction on file.
                elif artefact == Artefact.UNKNOWN.value:
                    try:
                        promote = sanction_claim.reads_as_a_sanction(self.model.ocr_text(pg.image_ref))
                    except Exception:                      # noqa: BLE001 -- the reading stands
                        promote = False
                    if promote:
                        out["needs_human"].append({
                            "page": pg.number, "artefact": artefact, "field": "document type",
                            "confidence": cls.confidence, "threshold": cls.confidence,
                            "why": ("The classifier did not name this page, and it reads as a sanction "
                                    "of a GP Fund advance. Taken as the sanction order; confirm the page.")})
                        artefact = Artefact.SANCTION_ORDER.value
                # stage 4: extract fields for this artefact type
                try:
                    art_enum = Artefact(artefact)
                except ValueError:
                    art_enum = Artefact.UNKNOWN
                emit_running(stage="extract", page=pg.number, artefact=artefact,
                             message=f"Page {pg.number} of {total} — reading {_label(artefact)}")
                with timing.stage("extract", page=pg.number):
                    fields = ({} if art_enum is Artefact.UNKNOWN
                              else self.model.extract_fields(pg.image_ref, artefact))
                # confidence gating (§4.5): below-threshold fields go to a person
                gated = []
                for name, ef in fields.items():
                    if ef.needs_human:
                        gated.append(name)
                        out["needs_human"].append({"page": pg.number, "artefact": artefact, "field": name,
                                                   "confidence": ef.confidence, "threshold": ef.threshold})
                # stage 5: barcodes (deterministic)
                with timing.stage("barcodes", page=pg.number):
                    codes = self.barcodes.decode_page(pg.image_ref, pg.number)
                out["result"] = PageResult(page=pg.number, artefact=artefact,
                                           classify_confidence=cls.confidence, fields=fields,
                                           codes=codes, needs_human=gated)
                if keys:
                    cache.put(keys[i], artefact=artefact, confidence=cls.confidence, fields=fields, codes=codes)
            finally:
                ended()
            emit_done(stage="page-done", page=pg.number, artefact=artefact,
                      message=f"Page {pg.number} of {total} — {_label(artefact)} read")
            return out

        # Pages are read together. Measured on this box 20 Oct 2026, a three-page claim spent
        # 54.99s of model time in 55.0s of wall clock -- 1.00x, every page waiting for the one
        # before it, while the vision server reported a single request running against a
        # scheduler that will take 128. The per-page cost is also wildly uneven (4.8s, 11.3s,
        # 35.4s on those three), so serial order means the whole case waits on the worst page
        # AND on every page before it; read together, it waits only on the worst.
        workers = read_concurrency()
        if workers <= 1 or total < 2:
            outcomes = [read_one(i, pg) for i, pg in enumerate(pages)]
        else:
            with ThreadPoolExecutor(max_workers=min(workers, total)) as pool:
                # Submitted in order and read back by index: the case file is a page order,
                # and completion order here is the order the model happened to finish in.
                from . import timing as _timing
                futures = [pool.submit(_timing.carry(read_one, page=pg.number), i, pg)
                           for i, pg in enumerate(pages)]
                outcomes = [f.result() for f in futures]

        # Assembled on this thread, in page order, exactly as the serial loop left them.
        for out in outcomes:
            if out["illegible"]:
                illegible.append(out["page"])
                continue
            if out["reused"]:
                reused.append(out["page"])
            if out["result"] is not None:
                page_results.append(out["result"])
            needs_human.extend(out["needs_human"])

        # stage 5b: deterministic, and fast — but it is the step that turns per-page
        # extractions into a case, so it is worth naming rather than leaving a stalled bar.
        emit(stage="assemble", done=total, page=None, message="Assembling the case facts")
        facts = assemble_facts(page_results, kind=kind, gazetted=gazetted)
        emit(stage="done", done=total, page=None, message="Read")
        return ReadingResult(pages=page_results, facts=facts, needs_human=needs_human,
                             illegible_pages=illegible, reused_pages=reused)


# ── facts assembler (stage-4 extractions -> the §4.3 facts object) ────────────
def _v(fields: dict[str, ExtractedField], name: str):
    ef = fields.get(name)
    return ef.value if ef else None


def assemble_facts(page_results: list[PageResult], *, kind: Optional[str] = None,
                   gazetted: str = "unknown") -> dict:
    """Merge per-page extractions into the case facts object the rules engine reads.

    Each artefact type has a merger. Fields are translated from the schema's
    snake_case to the facts object's camelCase. Codes (stage 5) become qr[]
    entries; cross-document comparison of a code's payload is left to the rules.
    """
    F: dict = {"kind": kind, "gazetted": gazetted, "docs": {}, "qr": [], "signatures": [],
               "thumbs": [], "custom": [], "verifications": {}, "sap": None, "persNos": []}

    # What every page was taken to be, kept on the case (26 Oct 2026). Only the pages that
    # MERGED left a trace before this, so a page the classifier read as the wrong thing -- or
    # as something with no merger at all -- vanished without one, and the claim simply said
    # the document was not there. PC-2026-000063 carried its sanction order on page 4 and the
    # checklist reported no sanction; nothing on the case could say what page 4 had been
    # called instead, so the miss could not be diagnosed without reading the claim again.
    # The rules do not read this. It is the reading's account of itself.
    F["pages"] = [{"page": pr.page, "artefact": pr.artefact,
                   "confidence": round(float(pr.classify_confidence or 0.0), 3),
                   "merged": pr.artefact in _MERGERS,
                   "fields": sorted(pr.fields)} for pr in page_results]

    for pr in page_results:
        merger = _MERGERS.get(pr.artefact)
        if merger:
            merger(F, pr)
        for code in pr.codes:
            F["qr"].append({
                "id": f"code-p{pr.page}-{len(F['qr'])}", "page": pr.page,
                "doc": pr.artefact, "symbology": code.symbology,
                "decoded": code.decoded, "payload": code.payload, "compare": [],
                **({"why": code.why} if code.why else {}),
                **({"notSupplied": None} if code.decoded else {}),
            })

    _finalise_identity(F)
    return F


def _cnic(F, whose, typ, pr):
    F["docs"].setdefault("cnics", [])
    F["docs"]["cnics"].append({
        "page": pr.page, "whose": whose, "type": typ,
        "number": _v(pr.fields, "number"), "name": _v(pr.fields, "name"),
        "attested": bool(_v(pr.fields, "attested")),
    })


def _merge_sanction(F, pr):
    f = pr.fields
    F["docs"]["sanction"] = {
        "present": True, "page": pr.page, "orderNo": _v(f, "order_no"), "date": _v(f, "date"),
        "dept": _v(f, "dept"), "printedAuthority": _v(f, "printed_authority"),
        "amount": _v(f, "amount"), "rule": _v(f, "rule"), "reason": _v(f, "reason"),
        "limitClause": _v(f, "limit_clause"), "basicPay": _v(f, "basic_pay_stated"),
        "balanceStated": _v(f, "balance_stated"),
        "qrId": None,
    }
    F["signatures"].append({
        "id": "sanction", "page": pr.page, "doc": "sanction order", "role": "sanctioning",
        "roleLabel": "Sanctioning signature", "authority": _v(f, "printed_authority") or _v(f, "dept") or "",
        "signedBy": _v(f, "actual_signatory") or _v(f, "printed_authority") or "",
        "forMarker": bool(_v(f, "for_marker")),
    })


def _merge_form(label):
    def merge(F, pr):
        f = pr.fields
        cf = {"present": True, "label": label, "page": pr.page,
              "personalNo": _v(f, "personal_no"), "name": _v(f, "name"), "cnic": _v(f, "cnic"),
              "sigKind": _v(f, "sig_kind") or "none", "ddoSigned": bool(_v(f, "ddo_signed")),
              "ddoStamp": _v(f, "ddo_stamp")}
        if "06" in label:
            cf["oldGpfNo"] = _v(f, "old_gpf_no")
        F["docs"]["changeForm"] = cf
        role_id = "form05-ddo" if "05" in label else "form06-ddo"
        F["signatures"].append({
            "id": role_id, "page": pr.page, "doc": label, "role": "ddo", "roleLabel": "DDO signature",
            "authority": _v(f, "ddo_stamp") or "", "signedBy": _v(f, "ddo_stamp") or "", "forMarker": False,
        })
    return merge


def _merge_gpf10(F, pr):
    f = pr.fields
    missing = []
    if not _v(f, "account_no"):
        missing.append("GP Fund account no.")
    if _v(f, "signed") is False:
        missing.append("signature of subscriber or claimant")
    if _v(f, "ddo_signed") is False:
        missing.append("signature of DDO")
    F["docs"]["gpf10"] = {"present": True, "page": pr.page, "accountNo": _v(f, "account_no"),
                          "missing": missing}
    F["signatures"].append({"id": "gpf10-ddo", "page": pr.page, "doc": "GPF-10", "role": "ddo",
                            "roleLabel": "DDO signature", "authority": "", "signedBy": "", "forMarker": False})


def _merge_payslip(F, pr):
    f = pr.fields
    F["sap"] = F["sap"] or {"source": "case"}
    F["sap"]["source"] = "case"
    F["sap"]["payslip"] = {
        "page": pr.page, "persNo": _v(f, "pers_no"), "name": _v(f, "name"),
        "designation": _v(f, "designation"), "cnic": _v(f, "cnic"), "month": _v(f, "month"),
        "bps": _v(f, "bps"), "ddoCode": _v(f, "ddo_code"), "gpfNo": _v(f, "gpf_no"),
        "oldGpfNo": _v(f, "old_gpf_no"), "gpfBalance": _v(f, "gpf_balance"),
        "gpfSubscription": _v(f, "gpf_subscription"), "loanInstalment": _v(f, "gpf_loan_instalment"),
        "loanBalance": _v(f, "gpf_loan_balance"), "basicPay": _v(f, "basic_pay"),
        "osdPost": _v(f, "osd_post"), "attested": bool(_v(f, "attested")),
    }


def _merge_recalc(F, pr):
    f = pr.fields
    F["sap"] = F["sap"] or {"source": "case"}
    F["sap"]["source"] = "case"
    F["sap"]["recalc"] = {
        "page": pr.page, "persNo": _v(f, "pers_no"), "reportDate": _v(f, "report_date"),
        "rows": _v(f, "rows") or [],
    }


def _merge_challan(F, pr):
    f = pr.fields
    ch = F["docs"].setdefault("challans", {"copies": []})
    ch.setdefault("copies", [])
    ch["copies"].append({"page": pr.page, "sr": _v(f, "sr"), "amount": _v(f, "amount"),
                         "bankStamp": bool(_v(f, "bank_stamp_present")),
                         "period": _v(f, "period"), "cheque": _v(f, "cheque")})
    if _v(f, "treasury_verified"):
        ch["toVerified"] = True
        ch["toPage"] = pr.page


def _merge_notification(label):
    def merge(F, pr):
        f = pr.fields
        F["docs"]["notification"] = {"present": True, "page": pr.page, "label": label,
                                     "no": _v(f, "no"), "date": _v(f, "date")}
    return merge


def _merge_service_book(F, pr):
    f = pr.fields
    sb = F["docs"].setdefault("serviceBook", {"present": True, "pages": [], "entries": {}})
    sb["present"] = True
    sb.setdefault("pages", []).append(pr.page)
    sb["entries"] = {"dor": bool(_v(f, "dor")), "order": bool(_v(f, "order")), "leave": bool(_v(f, "leave"))}


def _merge_fp_proforma(F, pr):
    """The proforma stands where the Service Book would (A2-vii, 26 Oct 2026).

    Named _merge_fp_proforma, not _merge_proforma: the balance transfer has a proforma of its
    own and had the plain name first. Two functions of one name is how this merger was wired
    and then silently replaced by the other (26 Oct 2026).

    The department sends it INSTEAD of the original book, so it fills the same slot. Its
    entries are read off the form itself and not assumed: the date of retirement and the type
    of retirement are printed lines on it, and the SERVICE RECORD SUMMARY is the leave account
    in summary. Where a line is blank the entry stays false and FP-SB asks for it, which is
    the same answer it would give on a book missing that entry.
    """
    f = pr.fields
    F["docs"]["serviceBook"] = {
        "present": True, "proforma": True, "page": pr.page, "pages": [pr.page],
        "label": "Proforma for GP Fund final payment",
        "entries": {"dor": bool(_v(f, "date_of_retirement")),
                    "order": bool(_v(f, "type_of_retirement")),
                    "leave": bool(_v(f, "leave_summary_filled"))},
        "ddoSigned": bool(_v(f, "ddo_signed")),
    }


def _merge_covering(F, pr):
    F["docs"]["covering"] = {"present": True, "page": pr.page, "nature": "Forwarding instrument"}


def _merge_proforma(F, pr):
    f = pr.fields
    F["docs"]["proforma"] = {"page": pr.page, "name": _v(f, "name"), "father": _v(f, "father"),
                             "designation": _v(f, "designation"), "oldAc": _v(f, "old_ac"),
                             "newAc": _v(f, "new_ac"), "lastDeduction": _v(f, "last_deduction"),
                             "periods": _v(f, "periods"), "daoConfirmed": _v(f, "dao_confirmed")}


_MERGERS = {
    Artefact.SANCTION_ORDER.value: _merge_sanction,
    Artefact.SANCTION_ORDER_QR.value: _merge_sanction,
    Artefact.FORM_PAY_05.value: _merge_form("FORM PAY 05"),
    Artefact.FORM_PAY_06.value: _merge_form("FORM PAY 06"),
    Artefact.GPF_FORM_10.value: _merge_gpf10,
    Artefact.SAP_PAYSLIP.value: _merge_payslip,
    Artefact.SAP_GPF_RECALC_REPORT.value: _merge_recalc,
    Artefact.CNIC_SMART_FRONT.value: lambda F, pr: _cnic(F, "subscriber", "smart", pr),
    Artefact.CNIC_OLD_FRONT.value: lambda F, pr: _cnic(F, "subscriber", "old", pr),
    Artefact.CHALLAN_32A.value: _merge_challan,
    Artefact.RETIREMENT_NOTIF.value: _merge_notification("Retirement notification"),
    Artefact.PUNISHMENT_ORDER.value: _merge_notification("Punishment order, dismissal from service"),
    Artefact.OBITUARY_NOTIF.value: _merge_notification("Obituary notification"),
    Artefact.SERVICE_BOOK_PAGE.value: _merge_service_book,
    Artefact.FP_PROFORMA.value: _merge_fp_proforma,
    Artefact.COVERING_LETTER.value: _merge_covering,
    Artefact.BALANCE_TRANSFER_PROF.value: _merge_proforma,
}


def _finalise_identity(F):
    """Derive the case personnel number from the strongest available source."""
    import re as _re
    sap = F.get("sap") or {}
    docs = F.get("docs") or {}
    cf = docs.get("changeForm") or {}
    g10 = docs.get("gpf10") or {}
    pf = docs.get("proforma") or {}

    def _digits(v):
        d = _re.sub(r"\D", "", str(v or ""))
        return d if len(d) >= 6 else None   # a personnel number, not a stray digit

    F["personnelNo"] = (
        (sap.get("payslip") or {}).get("persNo")
        or (sap.get("recalc") or {}).get("persNo")
        or cf.get("personalNo") or _digits(g10.get("accountNo"))
        or _digits(pf.get("newAc")) or _digits(pf.get("oldAc"))
    )
    # record where the personnel number appears (used by the SAP step UI)
    seen = []
    for label, val in [("SAP pay slip", (sap.get("payslip") or {}).get("persNo")),
                       ("GPF Final Re-calculation Report", (sap.get("recalc") or {}).get("persNo")),
                       ("change form", cf.get("personalNo"))]:
        if val:
            seen.append({"doc": label, "value": val})
    F["persNos"] = seen
