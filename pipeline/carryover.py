"""Reuse an earlier round's reading of the papers that have not changed. 30 Sep 2026.

A case the Accountant General returns for a missing paper comes back with that paper added,
and every other page exactly as it was. Re-reading all of them spent the vision model on
pages that had been read already -- six to twelve minutes for a case whose one change was a
two-page certificate. This module is how a resubmission's run reads only what is new.

How a page is recognised as unchanged
    Each run's ``bundle.json`` records every document of the bundle with its sha256 and the
    page range it occupies in the case file (``pipeline.bundle``). A document of the new
    bundle whose bytes match a document of the base run's bundle occupies the same number of
    pages, rendered from the same bytes, so its pages are the base run's pages under new
    numbers. Matching is by content, never by name or position, so a replacement earlier in
    the bundle that shifts every later page is handled like any other renumbering.

What is carried, under the new page numbers
    page images (and the as-scanned original beside a turned page) and their manifest rows,
    page identities (stage 3, with the OCR verdict of stage 2), OCR text, and the signature
    reads of stage 6b. Stage 4 and stage 6 take the base run's results through
    :func:`remap` and read only the new pages (``pipeline.extract``). Everything that
    compares documents -- assembly, case type, the checklist, every flag, the determination
    -- is pure code and runs over the whole case every time, so a new paper is always
    checked against the old ones.

When nothing is carried
    No base run, a base run that was not a raw scan, a new case file that is not one, or no
    document in common. The run is then a full run, exactly as a first submission is.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .ingest import atomic_write_text

CARRYOVER = "carryover.json"
CARRIED_PAGES = "carried_pages.json"

_DROP = object()


# -- the plan -----------------------------------------------------------------------------
def plan(new_bundle: dict, base_bundle: dict) -> dict:
    """Which pages of the new bundle are pages of the base bundle, matched by document content.

    Returns ``page_map`` (new page -> base page), ``new_pages`` (pages nothing matched) and
    one entry per document of the new bundle saying which it is. Two identical files in one
    bundle are matched in order, one to one.
    """
    pool: dict[str, list[dict]] = {}
    for part in base_bundle.get("parts") or []:
        if part.get("skipped") or not part.get("pages"):
            continue
        pool.setdefault(part["sha256"], []).append(part)

    page_map: dict[int, int] = {}
    new_pages: list[int] = []
    parts: list[dict] = []
    for part in new_bundle.get("parts") or []:
        if part.get("skipped") or not part.get("pages"):
            continue
        lo, hi = int(part["page_from"]), int(part["page_to"])
        match = None
        candidates = pool.get(part["sha256"]) or []
        while candidates:
            c = candidates.pop(0)
            if int(c["pages"]) == int(part["pages"]):
                match = c
                break
        if match is not None:
            for k in range(hi - lo + 1):
                page_map[lo + k] = int(match["page_from"]) + k
            parts.append({"name": part["name"], "sha256": part["sha256"], "pages": [lo, hi],
                          "status": "REUSED", "base_pages": [int(match["page_from"]), int(match["page_to"])]})
        else:
            new_pages.extend(range(lo, hi + 1))
            parts.append({"name": part["name"], "sha256": part["sha256"], "pages": [lo, hi], "status": "NEW"})
    return {"page_map": page_map, "new_pages": sorted(new_pages), "parts": parts}


# -- remapping artefacts ------------------------------------------------------------------
def remap(obj: Any, forward: dict[int, int]) -> Any:
    """A base-run artefact under the new page numbers.

    ``forward`` maps base page -> new page. Every dict carrying a ``page`` (or a ``pages``
    list) is renumbered; one citing a base page that is not in the new bundle -- a replaced
    document's page -- is dropped, because a fact read from a paper the department withdrew
    must not reach the new round's findings.
    """
    out = _remap(obj, forward)
    return None if out is _DROP else out


def _remap(obj: Any, fwd: dict[int, int]) -> Any:
    if isinstance(obj, list):
        kept = [_remap(x, fwd) for x in obj]
        return [x for x in kept if x is not _DROP]
    if not isinstance(obj, dict):
        return obj
    out: dict = {}
    for key, value in obj.items():
        if key == "page" and isinstance(value, int) and not isinstance(value, bool):
            if value not in fwd:
                return _DROP
            out[key] = fwd[value]
        elif key == "pages" and isinstance(value, list) and all(isinstance(v, int) for v in value):
            if any(v not in fwd for v in value):
                return _DROP
            out[key] = [fwd[v] for v in value]
        else:
            mapped = _remap(value, fwd)
            if mapped is _DROP:
                continue
            out[key] = mapped
    return out


# -- preparing a run directory --------------------------------------------------------------
def load(run_dir: str | Path) -> dict | None:
    """The carry-over record of a run, or None for a full run."""
    path = Path(run_dir) / CARRYOVER
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return None
    return data if data.get("mode") == "INCREMENTAL" else None


def forward_map(carry: dict) -> dict[int, int]:
    """base page -> new page, from a carry-over record."""
    return {int(old): int(new) for new, old in (carry.get("page_map") or {}).items()}


def base_artefact(carry: dict, name: str) -> Any:
    """One of the base run's artefacts, as it was written, or None."""
    path = Path(carry["base_dir"]) / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:
        return None


def prepare(run_dir: str | Path, base_dir: str | Path, base_run_id: str, pdf_path: str | Path) -> dict:
    """Seed ``run_dir`` with the base run's results for every unchanged page. Idempotent.

    Called after the bundle is unpacked (``bundle.json`` exists) and before ingest. Writes
    ``carryover.json`` either way: an INCREMENTAL record with the page map, or a FULL one
    saying why nothing could be carried.
    """
    run, base = Path(run_dir), Path(base_dir)
    existing = run / CARRYOVER
    if existing.exists():
        try:
            return json.loads(existing.read_text())
        except ValueError:
            pass

    def full(reason: str) -> dict:
        record = {"mode": "FULL", "base_run_id": base_run_id, "reason": reason,
                  "prepared_at": datetime.now().isoformat(timespec="seconds")}
        atomic_write_text(existing, json.dumps(record, indent=2))
        return record

    # A run already under way without a carry-over record began as a full run (before
    # rounds existed, or with no base): seeding it now would overwrite what it has read.
    if (run / "manifest.json").exists() or (run / "identities.json").exists():
        return full("this run was already under way as a full run")

    new_bundle = _json(run / "bundle.json")
    base_bundle = _json(base / "bundle.json")
    base_manifest = _json(base / "manifest.json")
    if not new_bundle or not base_bundle:
        return full("no bundle record to match documents by")
    if not base_manifest or base_manifest.get("source_kind") != "raw_scan":
        return full("the earlier round was not read as a departmental scan")
    if not (base / "identities.json").exists() or not (base / "case_report.json").exists():
        return full("the earlier round's run did not finish")
    if _is_verification_copy(Path(pdf_path)):
        return full("the case file is a verification copy, whose pages are not the bundle's pages")

    p = plan(new_bundle, base_bundle)
    if not p["page_map"]:
        return full("no document of this round is unchanged from the earlier round")

    fwd = {old: new for new, old in p["page_map"].items()}
    pages_dir = run / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    # Page images and their manifest rows. Named for the page they now are and the page they
    # were, so a reader of the directory can see where each came from.
    carried_rows: dict[str, dict] = {}
    by_old = {int(r["page"]): r for r in base_manifest.get("pages") or []}
    for new, old in sorted(p["page_map"].items()):
        row = by_old.get(old)
        if row is None:
            continue
        src = base / row["image_path"]
        if not src.exists():
            continue
        name = f"p{new:03d}-c{old:03d}.png"
        shutil.copy2(src, pages_dir / name)
        scanned = src.with_name(f"{src.stem}-as-scanned.png")
        if scanned.exists():
            shutil.copy2(scanned, pages_dir / f"p{new:03d}-c{old:03d}-as-scanned.png")
        carried_rows[str(new)] = {**row, "page": new, "image_path": f"pages/{name}"}
    # A page whose image could not be copied is read afresh rather than half-carried.
    for new in [n for n in p["page_map"] if str(n) not in carried_rows]:
        del p["page_map"][new]
        p["new_pages"].append(new)
    p["new_pages"].sort()
    fwd = {old: new for new, old in p["page_map"].items()}
    atomic_write_text(run / CARRIED_PAGES, json.dumps(carried_rows, indent=2))

    # Stage 3 identities (stage 2's verdict included): identify skips a page already present.
    ids = _json(base / "identities.json") or []
    carried_ids = remap([r for r in ids if r.get("page") in fwd], fwd) or []
    atomic_write_text(run / "identities.json",
                      json.dumps(sorted(carried_ids, key=lambda r: r["page"]), indent=2, ensure_ascii=False))

    # OCR text, keyed by page.
    ocr = _json(base / "ocr_text.json") or {}
    carried_ocr = {str(fwd[int(k)]): v for k, v in ocr.items() if k.isdigit() and int(k) in fwd}
    if carried_ocr:
        atomic_write_text(run / "ocr_text.json", json.dumps(carried_ocr, ensure_ascii=False))

    # Stage 6b signature reads, and the signature cut-outs they point at.
    sigs = _json(base / "psa_signatures.json")
    carried_forms = 0
    if sigs:
        forms = []
        for form in remap(sigs.get("forms") or [], fwd) or []:
            img = form.get("signature_image")
            if img:
                src = base / img
                if src.exists():
                    dest = Path(img).parent / f"carried-{Path(img).name}"
                    (run / dest).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, run / dest)
                    form["signature_image"] = str(dest)
                else:
                    form["signature_image"] = None
            forms.append(form)
        carried_forms = len(forms)
        if forms:
            atomic_write_text(run / "psa_signatures.json",
                              json.dumps({"forms": forms}, indent=2, ensure_ascii=False, default=str))

    record = {
        "mode": "INCREMENTAL", "base_run_id": base_run_id, "base_dir": str(base),
        "page_map": {str(k): v for k, v in sorted(p["page_map"].items())},
        "new_pages": p["new_pages"], "parts": p["parts"],
        "seeded": {"pages": len(carried_rows), "identities": len(carried_ids),
                   "ocr_pages": len(carried_ocr), "signature_forms": carried_forms},
        "prepared_at": datetime.now().isoformat(timespec="seconds"),
    }
    atomic_write_text(existing, json.dumps(record, indent=2))
    return record


def carried_manifest_rows(run_dir: str | Path) -> dict[int, dict]:
    """The manifest rows ingest takes as they are, keyed by (new) page number."""
    data = _json(Path(run_dir) / CARRIED_PAGES) or {}
    return {int(k): v for k, v in data.items()}


def summarise(run_dir: str | Path, *, started_at: str | None = None, finished_at: str | None = None) -> dict:
    """What a finished run read and what it reused, stage by stage, from its own artefacts."""
    run = Path(run_dir)
    carry = load(run)
    manifest = _json(run / "manifest.json") or {}
    total = len(manifest.get("pages") or [])
    duration = None
    if started_at and finished_at:
        try:
            duration = (datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)).total_seconds()
        except ValueError:
            duration = None
    if carry is None:
        return {"mode": "FULL", "pages_total": total, "pages_read": total, "pages_reused": 0,
                "duration_s": duration,
                "reason": (_json(run / CARRYOVER) or {}).get("reason")}
    reused = len(carry.get("page_map") or {})
    fields = _json(run / "fields.json") or {}
    facts = _json(run / "assertions.json") or {}
    ocr = _json(run / "ocr_text.json") or {}
    sigs = _json(run / "psa_signatures.json") or {}
    return {
        "mode": "INCREMENTAL", "base_run_id": carry.get("base_run_id"),
        "pages_total": total, "pages_read": total - reused, "pages_reused": reused,
        "new_pages": carry.get("new_pages") or [], "duration_s": duration,
        "steps": {
            "ingest": {"run": total - reused, "reused": reused},
            "identify": {"run": total - carry["seeded"]["identities"], "reused": carry["seeded"]["identities"]},
            "ocr": {"run": max(0, len(ocr) - carry["seeded"]["ocr_pages"]), "reused": carry["seeded"]["ocr_pages"]},
            "extract": fields.get("carryover") or {},
            "assertions": facts.get("carryover") or {},
            "signatures": {"run": max(0, len(sigs.get("forms") or []) - carry["seeded"]["signature_forms"]),
                           "reused": carry["seeded"]["signature_forms"]},
            "checks": {"run": "all", "note": "checklist, flags, cross-checks and determination run over the whole case"},
        },
        "parts": carry.get("parts") or [],
    }


def _json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:
        return None


def _is_verification_copy(pdf: Path) -> bool:
    from .ingest import _has_verification_headers, _run
    try:
        total = int(_run(["pdfinfo", str(pdf)]).split("Pages:")[1].split()[0])
        return _has_verification_headers(pdf, total)
    except Exception:                                  # noqa: BLE001 -- unknown shape: do not carry
        return True
