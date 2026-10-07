"""Pipeline orchestration, stages 1-4 then the deterministic layer. BUILD §5, §5.1.

Stages are resumable and idempotent. Each writes its artefact to the run directory and, on a
re-run, loads what is already there rather than recomputing it -- BUILD §5.1: "A failure at
stage 6 re-runs stage 6, not stages 1-5. Page-level checkpoints within stages 1-2."

Stage 3 checkpoints per **page**, not per stage, because it is the expensive one: 43 pages at
roughly twelve seconds each is nine minutes of GPU, and losing all of it to one timeout on
page 40 is the failure mode §5.1 exists to prevent.

    stage 1  ingest        PDF -> page images + quality + source hash
    stage 3  identify      page image -> document type            [vision model]
    stage 3b assemble      pages -> documents                     [pure code]
    stage 3c classify      documents -> case type                 [pure code, BRAIN §4.1]
    stage 4  extract       document -> fields                     [vision model]
    ---- deterministic layer ----
    checklist, flags, determination, verdict, notifications       [no model at all]

Stage 2 (first-pass OCR on PaddleOCR) is not wired here: the digitised source gives one clean
image per page, so the escalation path stage 2 exists to feed has nothing to decide yet. It
belongs with a raw multi-page scan.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .ingest import (SourcePage, atomic_write_text, load_manifest, read_checkpoint,
                     source_pages)

#: How many pages to read at once. Matched to the vision server's --max-num-seqs: asking for
#: more than it will batch just queues requests inside vLLM and adds latency to each.
IDENTIFY_CONCURRENCY = 4

IDENTITIES = "identities.json"
DOCUMENTS = "documents.json"
CASE_TYPE = "case_type.json"
REPORT = "case_report.json"


def _write(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def stage_identify(
    run_dir: str | Path,
    *,
    progress: Callable[[str], None] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Stage 3: identify every page's document type. Checkpoints after each page.

    Interrupting and re-running picks up where it stopped. The checkpoint is the artefact
    itself -- a page already present in ``identities.json`` is not re-read.
    """
    from extraction.identify import identify_page

    run = Path(run_dir)
    out = run / IDENTITIES
    done: dict[int, dict] = {}
    # A checkpoint too damaged to read is worth re-earning; refusing to start is not.
    resumed = read_checkpoint(out)
    if resumed:
        done = {d["page"]: d for d in resumed}

    pages: list[SourcePage] = source_pages(load_manifest(run), run)
    if limit is not None:
        pages = pages[:limit]

    pending = [sp for sp in pages if sp.page not in done]

    # Read several pages at once. The vision server is started with --max-num-seqs 4, so it
    # will batch four requests and was being fed one: a 44-page bundle spent six minutes in
    # this stage with three quarters of the server's capacity idle. Nothing about WHAT is
    # read changes -- each page is still one independent call under the same schema -- only
    # how many are in flight.
    #
    # The checkpoint still happens on this thread, after each result arrives, so an
    # interrupted run resumes exactly as before and identities.json is never written from
    # two threads at once.
    from pipeline import timing
    with ThreadPoolExecutor(max_workers=IDENTIFY_CONCURRENCY) as pool:
        futures = {
            pool.submit(timing.carry(identify_page, stage="identify", page=sp.page), sp.image_path, page=sp.page): sp
            for sp in pending
        }
        for future in as_completed(futures):
            sp = futures[future]
            ident = future.result()
            record = ident.to_dict()
            record["header_title"] = sp.header_title   # ground truth, for the eval
            record["quality"] = sp.quality
            done[sp.page] = record
            _write(out, [done[k] for k in sorted(done)])
            if progress:
                progress(
                    f"p.{sp.page:>2}  {ident.document_type:<28} "
                    f"{ident.confidence:.2f}  {sp.header_title[:44]}"
                )

    return [done[k] for k in sorted(done)]


def stage_verify_forms(run_dir: str | Path, *, progress=None,
                       skip_pages: set[int] | frozenset[int] = frozenset()) -> list[dict]:
    """Stage 2 (targeted): second-read every claimed prescribed form with PaddleOCR.

    Only pages stage 3 called a prescribed form are re-read -- three or four out of forty-odd.
    Those are the pages that select a pension formula, and stage 3's own account of them
    cannot be trusted to check itself (see extraction/ocr.py).

    ``skip_pages`` are pages carried from an earlier round (``pipeline.carryover``): their
    rows already carry this stage's verdict and are left exactly as that round left them.
    """
    from extraction.identify import PageIdentity, verify_with_ocr

    run = Path(run_dir)
    rows = json.loads((run / IDENTITIES).read_text())
    by_page = {r["page"]: r for r in rows}
    manifest_pages = {p["page"]: p["image_path"] for p in load_manifest(run)["pages"]}

    def claimed(r: dict) -> str:
        # Re-verify from the model's ORIGINAL claim, not from the last verdict on it. This
        # stage rewrites identities.json in place, so a denial was permanent: once a row read
        # OTHER with downgraded_from set, every later run saw OTHER, skipped it, and a fix to
        # the OCR patterns never reached the case. The divorced-daughter bundle's "Proforma
        # D-II" was denied on 15 September, the pattern was widened the same afternoon, and
        # the case kept reporting "no prescribed form" on every re-run since. Only a row the
        # denial left as OTHER is reopened; one the re-read placed elsewhere stands.
        if r["document_type"] == "OTHER" and r.get("downgraded_from"):
            return r["downgraded_from"]
        return r["document_type"]

    identities = [
        PageIdentity(
            page=r["page"], document_type=claimed(r), confidence=r["confidence"],
            evidence=r["evidence"], is_first_page=r["is_first_page_of_document"],
            signed_by_psa=r.get("signed_by_psa"), attested=r.get("attested"),
            printed_form_number=r.get("printed_form_number"),
        )
        for r in rows
        if r["page"] not in skip_pages
    ]
    verified = verify_with_ocr(identities, lambda pg: run / manifest_pages[pg])
    form_text = getattr(verify_with_ocr, "form_text", {})

    for v in verified:
        row = by_page[v.page]
        if v.page in form_text:
            # What the prescribed form itself says, kept for the checklist-column derivation.
            row["form_text"] = form_text[v.page]
        if v.downgraded_from:
            row["document_type"] = v.document_type
            row["downgraded_from"] = v.downgraded_from
            row["needs_human"] = True
            if progress:
                progress(
                    f"p.{v.page:>2}  OCR denies {v.downgraded_from} -> OTHER "
                    f"(no such form number printed)"
                )
        elif row.get("downgraded_from"):
            # An earlier denial, now withdrawn: the second reader corroborates the claim.
            row["document_type"] = v.document_type
            row.pop("downgraded_from", None)
            row.pop("needs_human", None)
            if progress:
                progress(f"p.{v.page:>2}  OCR now corroborates {v.document_type}; "
                         f"earlier denial withdrawn")
    out = [by_page[k] for k in sorted(by_page)]
    _write(run / IDENTITIES, out)
    return out


def stage_assemble(run_dir: str | Path) -> list[dict]:
    """Stage 3b: group identified pages into documents. Pure code."""
    from extraction.identify import PageIdentity, assemble_documents

    run = Path(run_dir)
    raw = json.loads((run / IDENTITIES).read_text())
    identities = [
        PageIdentity(
            page=d["page"],
            document_type=d["document_type"],
            confidence=d["confidence"],
            evidence=d["evidence"],
            is_first_page=d["is_first_page_of_document"],
            signed_by_psa=d.get("signed_by_psa"),
            attested=d.get("attested"),
            # Without this the name read off a CNIC card is dropped on the way from the page
            # identity to the document, and assign_cnic_roles has nothing to match on -- the
            # card stays a generic CNIC and BOTH the deceased's and the claimant's checklist
            # requirements report MISSING.
            person_named=d.get("person_named"),
        )
        for d in raw
    ]
    docs = assemble_documents(identities)
    docs = docs + documents_also_on_the_page(raw, docs)
    docs = docs + documents_named_by_their_own_heading(run, raw, docs)
    payload = [asdict(d) for d in docs]
    _write(run / DOCUMENTS, payload)
    return payload


def documents_also_on_the_page(rows: list[dict], docs: tuple) -> tuple:
    """The further documents the identifier saw on a page besides the one it filed it as.

    One sheet often carries two or three certificates, and a page has one document_type, so
    the second and third were never registered and read MISSING on the checklist. The
    identifier now lists them (``other_documents_on_page``); each becomes a one-page document
    of its own on that page. A run identified before the field existed has none, and is
    unchanged. OTHER never becomes a document, as in ``assemble_documents``.
    """
    from rules.caserecord import Document

    covered = {(p, d.type) for d in docs for p in d.pages}
    added: list[Document] = []
    for row in rows:
        page = row.get("page")
        if page is None:
            continue
        for doc_type in row.get("other_documents_on_page") or ():
            if not doc_type or doc_type == "OTHER" or (page, doc_type) in covered:
                continue
            covered.add((page, doc_type))
            added.append(Document(type=doc_type, pages=(page,), present=True,
                                  attested=row.get("attested")))
    return tuple(added)


def documents_named_by_their_own_heading(run: Path, rows: list[dict],
                                         docs: tuple) -> tuple:
    """Documents a generically-labelled page proves it is, by the title printed on it.

    The identifier calls a page ``AFFIDAVIT`` when it is sworn before an oath commissioner and
    ``OTHER`` when it recognises nothing -- and a department's sole-widow certificate, list of
    family members and no-income certificate are all routinely sworn. On the real bundles that
    cost three checklist lines: page 5 of the disabled-son case is headed "LIST OF FAMILY
    MEMBERS OF Abdul Waheed Qureshi", was filed as an affidavit, and AG-05 reported the list of
    family members MISSING while it sat in the bundle.

    So the page's own heading is read -- by OCR, an independent reading, never from the
    model's account of itself -- and where it names a checklist document, that document is
    ADDED. The page keeps its original label and the affidavit it also is: nothing is
    overridden, nothing is lost, and a sworn certificate satisfies both lines it belongs to.
    Only ``OTHER`` and ``AFFIDAVIT`` pages are read this way; a page the identifier placed
    specifically is left exactly where it put it.
    """
    from extraction.identify import GENERIC_LABELS, STATEMENTS_ON_LABELLED_PAGES, statements_on_page, titles_on_page
    from pipeline.extract import page_ocr_text
    from rules.caserecord import Document

    covered = {(p, d.type) for d in docs for p in d.pages}
    added: list[Document] = []
    for row in rows:
        label = row.get("document_type")
        page = row.get("page")
        if page is None:
            continue
        if label in GENERIC_LABELS:
            found = titles_on_page(page_ocr_text(run, page))
        elif label in STATEMENTS_ON_LABELLED_PAGES:
            # A specifically labelled page keeps its label; a statement it prints (the
            # commutation option on an Annexure-A) is added as the document it also is. The
            # identifier's own account of the page counts as a second reading, so a poor scan
            # whose OCR misses the line is still credited when the model quoted it.
            text = page_ocr_text(run, page) + " " + str(row.get("evidence") or "")
            found = statements_on_page(label, text)
        else:
            continue
        for doc_type in found:
            if (page, doc_type) in covered:
                continue
            covered.add((page, doc_type))
            # NOT recorded as a defect. `defects` is what makes a checklist line DEFECTIVE,
            # and a document that is present and legible is not defective for having been
            # found by its heading. Where it came from is visible on the page it cites.
            added.append(Document(
                type=doc_type, pages=(page,), present=True,
                attested=row.get("attested"),
            ))
    return tuple(added)


def stage_classify(run_dir: str | Path) -> dict:
    """Stage 3c: derive the case type from the assembled documents. BRAIN §4.1."""
    from rules import CaseRecord, Document, classify_case_type

    run = Path(run_dir)
    docs = tuple(
        Document(
            type=d["type"],
            pages=tuple(d["pages"]),
            present=d["present"],
            signatory_is_psa=d.get("signatory_is_psa"),
            attested=d.get("attested"),
        )
        for d in json.loads((run / DOCUMENTS).read_text())
    )
    result = classify_case_type(CaseRecord(case_ref=run.name, case_type="", documents=docs))
    _write(run / CASE_TYPE, result.to_dict())
    return result.to_dict()


def classification_eval(run_dir: str | Path) -> dict:
    """Score stage 3 against the header titles. BUILD §12.3 extraction eval.

    The digitised copy titles every page by hand, so accuracy is measurable without labelling
    anything. Reported per document type rather than blended, for the same reason BUILD §2.1
    insists handwriting accuracy is reported separately from printed: a single number hides
    exactly the class you are failing.
    """
    run = Path(run_dir)
    rows = json.loads((run / IDENTITIES).read_text())

    #: Header title keyword -> expected document type. The header is prose written for a
    #: human, so matching is by keyword rather than exact string.
    keywords: list[tuple[str, str]] = [
        ("form d-i", "FORM_D_I"), ("form d-ii", "FORM_D_II"),
        ("succession certificate", "SUCCESSION_CERTIFICATE"),
        ("death registration", "NADRA_DEATH_CERTIFICATE"),
        ("death certificate", "NADRA_DEATH_CERTIFICATE"),
        ("family registration", "NADRA_FRC"), ("frc", "NADRA_FRC"),
        ("last pay certificate", "LPC"), ("lpc", "LPC"),
        ("salary statement", "SALARY_STATEMENT"),
        ("service statement", "SERVICE_STATEMENT"),
        ("name-change", "NAME_CHANGE_ORDER"), ("name change", "NAME_CHANGE_ORDER"),
        ("posting order", "POSTING_ORDER"),
        ("recruitment order", "POSTING_ORDER"), ("joining", "POSTING_ORDER"),
        ("promotion", "POSTING_ORDER"),
        # The model now answers the generic CNIC; whose card it is is decided afterwards by
        # rules.case_type.assign_cnic_roles, so the reading task is scored on CNIC alone.
        ("cnic", "CNIC"),
        ("no demand", "NDC"), ("no-demand", "NDC"),
        ("bank", "BANK_OPTION_FORM"),
        ("descriptive roll", "ANNEX_A"), ("annex", "ANNEX_A"),
        ("photograph", "PHOTOGRAPHS"),
        ("affidavit", "NON_REMARRIAGE_CERTIFICATE"),
        ("non-marriage", "NON_REMARRIAGE_CERTIFICATE"),
        ("forwarding", "FORWARDING_LETTER"),
    ]

    per_type: dict[str, dict[str, int]] = {}
    scored = unmatched = 0
    for r in rows:
        title = (r.get("header_title") or "").lower()
        expected = next((t for kw, t in keywords if kw in title), None)
        if expected is None:
            unmatched += 1
            continue
        scored += 1
        bucket = per_type.setdefault(expected, {"n": 0, "correct": 0})
        bucket["n"] += 1
        if r["document_type"] == expected:
            bucket["correct"] += 1

    correct = sum(b["correct"] for b in per_type.values())
    return {
        "pages": len(rows),
        "scored": scored,
        "unlabelled_by_keyword": unmatched,
        "correct": correct,
        "accuracy": round(correct / scored, 3) if scored else None,
        "per_type": {
            k: {**v, "accuracy": round(v["correct"] / v["n"], 3)}
            for k, v in sorted(per_type.items())
        },
        "low_confidence_pages": [
            r["page"] for r in rows if r["confidence"] < 0.80 or r["document_type"] == "OTHER"
        ],
    }


