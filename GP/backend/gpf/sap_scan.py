"""Reading a SAP pay slip or re-calculation report the section has scanned (23 Oct 2026).

The SAP extracts step took the text SAP exports and nothing else, so a section that had a
printout or a PDF of the pay slip could not give it to the case at all: the claim sat on an
open SAP item (R1) with the paper in the officer's hand.

The module already reads both artefacts -- a pay slip and the re-calculation report are two of
the types its pipeline classifies, and PC-2026-000070's twenty-four year ledger came off page
6 of the claim that way. What was missing was a door into that reader for a page arriving on
its own, after the claim has been read, to be merged into a case that already exists.

So this is the claim reader pointed at one or two pages, with everything it finds that is NOT
a SAP extract thrown away. A pay slip the section pulled is a pay slip; if the page turns out
to be a covering letter it changes nothing, and the officer is told that rather than left to
wonder why the figures did not move.

Reading is a vision call per page -- tens of seconds -- so the route starts a job and the
screen polls it, exactly as the examination does (gpf.reading.jobs).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Optional

from .reading.artefacts import Artefact
from .reading.pipeline import _merge_payslip, _merge_recalc, ingest_pages

#: Page images pass through; a PDF is rendered. Anything else the section might scan to is
#: refused by name rather than read as noise.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
#: What this reader keeps. Everything else the page might be classified as is discarded: the
#: claim's own reading is the claim's, and a page handed in here speaks only for SAP.
SAP_ARTEFACTS = {Artefact.SAP_PAYSLIP.value: ("payslip", _merge_payslip),
                 Artefact.SAP_GPF_RECALC_REPORT.value: ("recalc", _merge_recalc)}
#: The resolution the claim's pages are rendered at (api/gpf_bridge.page_images), so a page
#: scanned here is read at the quality the reader was tuned on.
DPI = 200


class ScanError(ValueError):
    """The upload could not be turned into pages. Carries what to do about it."""


def render_pages(files: list[tuple[str, bytes]], out_dir: Path, *, dpi: int = DPI) -> list[str]:
    """The uploaded files as page images, in the order they were given.

    pdftoppm is poppler's and is already on the machine: it renders the claim's own PDFs on
    the portal side (api/gpf_bridge.page_images), and this matches its flags so that a page
    read here is the same picture the claim reader would have been given.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[str] = []
    for i, (name, body) in enumerate(files, start=1):
        suffix = Path(name or "").suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            dest = out_dir / f"d{i:02d}{suffix}"
            dest.write_bytes(body)
            pages.append(str(dest))
        elif suffix == ".pdf":
            src = out_dir / f"d{i:02d}.pdf"
            src.write_bytes(body)
            prefix = out_dir / f"d{i:02d}"
            try:
                subprocess.run(["pdftoppm", "-r", str(dpi), "-jpeg", str(src), str(prefix)],
                               check=True, capture_output=True, timeout=600)
            except FileNotFoundError:
                raise ScanError("This machine cannot render a PDF (poppler's pdftoppm is not "
                                "installed). Upload the pay slip as an image, or as the text "
                                "SAP exports.") from None
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
                raise ScanError(f"{name} could not be read as a PDF"
                                + (": " + detail[-1] if detail else ".")) from None
            rendered = sorted(out_dir.glob(f"d{i:02d}-*.jpg"))
            if not rendered:
                raise ScanError(f"{name} has no pages in it.")
            pages.extend(str(p) for p in rendered)
        else:
            raise ScanError(f"{name} is not a page. Upload the pay slip or the re-calculation "
                            "report as a PDF or a scanned image, or give the extract as the "
                            "text SAP exports.")
    if not pages:
        raise ScanError("No page was uploaded.")
    return pages


def read_sap_pages(pipeline, refs: list[str], *, kind: str = "", gazetted: str = "unknown",
                   on_progress: Optional[Callable[[dict], None]] = None) -> dict:
    """Read the pages and return only what SAP speaks for.

    ``{"payslip": <facts or None>, "recalc": <facts or None>, "pages": [{page, artefact}]}``.
    The merge functions are the pipeline's own, so a page read here lands on the case in
    exactly the shape a page of the claim would -- there is no second reading of a pay slip
    in this codebase to drift from the first.
    """
    result = pipeline.run(ingest_pages(refs), kind=kind or None, gazetted=gazetted,
                          on_progress=on_progress)
    found: dict = {"payslip": None, "recalc": None,
                   "pages": [{"page": pr.page, "artefact": pr.artefact} for pr in result.pages]}
    # A stand-in facts object for the mergers to write into: they expect the shape
    # assemble_facts builds, and only the "sap" part of it is kept.
    scratch: dict = {"sap": None, "docs": {}, "signatures": []}
    for pr in result.pages:
        entry = SAP_ARTEFACTS.get(pr.artefact)
        if not entry:
            continue
        part, merge = entry
        merge(scratch, pr)
        found[part] = (scratch.get("sap") or {}).get(part)
    return found


def read_upload(pipeline, files: list[tuple[str, bytes]], *, kind: str = "",
                gazetted: str = "unknown", on_progress=None, work_dir: Optional[Path] = None) -> dict:
    """Render the upload and read it. The rendered pages are kept only while they are read."""
    own = work_dir is None
    base = Path(work_dir or Path(tempfile.gettempdir()) / ("gpf-sap-scan-" + uuid.uuid4().hex[:12]))
    try:
        refs = render_pages(files, base)
        return read_sap_pages(pipeline, refs, kind=kind, gazetted=gazetted, on_progress=on_progress)
    finally:
        if own:
            shutil.rmtree(base, ignore_errors=True)
