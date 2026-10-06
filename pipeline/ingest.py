"""Stage 1: ingest and page triage. BRAIN §5, BUILD §5 stage 1.

"Split PDF to page images, deskew, denoise, orient, score quality per page, hash the source."

The source here is `E-Pension_data_v01_DIGITIZED.pdf`, a digitised verification copy of the
golden case: 43 source pages, each reproduced as **the original scan image** followed by **a
typed transcription** of that page. So one PDF carries both the input the pipeline must read
and a human-made ground truth to measure it against:

    pdf page 2k+1  ->  source page k, the scan   (one embedded image)
    pdf page 2k+2  ->  source page k, typed transcription

The image-page header also names the document ("SOURCE PAGE 2 of 43 - NADRA Punjab Succession
Certificate"), which is a hand-labelled document type for every page in the bundle. That makes
the classification eval of BUILD §12.3 possible without labelling anything by hand.

**The transcription is never fed to the model.** It is ground truth, and a pipeline that reads
the answer sheet measures nothing. Stage 3 and stage 4 see only the scan image; the
transcription is used afterwards, to score them.

No third-party PDF library: poppler's `pdftoppm`/`pdfimages`/`pdftotext` are already on the
box and are what a DGX Spark image ships with, so ingest adds no dependency to a pipeline that
has to run air-gapped inside the AG office.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"


def atomic_write_text(path: Path, text: str) -> None:
    """Write through a temporary file in the same directory, then rename over the target.

    A checkpoint exists to protect the minutes of vision inference behind it, and a direct
    write leaves a truncated file if the process dies mid-write -- an API restart, an OOM
    kill. That turns a resumable run into one that cannot be re-uploaded at all, because the
    run id is the content hash and every retry meets the same corrupt file. os.replace is
    atomic on POSIX where source and destination share a filesystem, so a reader sees either
    the whole old file or the whole new one.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def read_checkpoint(path: Path) -> Any | None:
    """Load a resumable artefact, treating a truncated one as absent rather than fatal.

    Returns None where there is nothing usable to resume from, so the caller recomputes. A
    corrupt checkpoint written before atomic_write_text existed costs the time it saved; an
    unhandled JSONDecodeError costs the whole run and blocks every re-upload of that file.
    The file is left in place: the stage that owns it overwrites it on the next checkpoint.
    """
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (ValueError, UnicodeDecodeError):
        return None

_HEADER_RE = re.compile(r"SOURCE PAGE\s+(\d+)\s+of\s+(\d+)\s*[—-]\s*(.+)")


class IngestError(RuntimeError):
    """The source PDF is not the shape ingest expects. Never guessed around."""


@dataclass(frozen=True)
class SourcePage:
    """One page of the original case file."""

    page: int
    image_path: str
    #: The document title printed on the image page's header. Hand-made ground truth.
    header_title: str
    #: The typed transcription of this page. Ground truth; never sent to a model.
    transcription: str
    quality: float
    width: int
    height: int
    #: Degrees anticlockwise applied to bring the text upright, and why. 0 for a page that
    #: arrived the right way up -- which is most of them. The page as rendered is kept beside
    #: the upright one (``-as-scanned.png``); nothing the department sent is thrown away.
    rotation: int = 0
    rotation_basis: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


#: Seconds any one poppler call may take. A crafted PDF can keep pdftoppm busy indefinitely, and
#: with no limit the run sat "running" for ever (audit 6 Oct 2026). A real page takes a second or two.
TOOL_TIMEOUT = int(os.environ.get("PENSION_PDF_TOOL_TIMEOUT", "300") or 300)


def _run(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise IngestError(f"{cmd[0]} did not finish within {TOOL_TIMEOUT} s") from None
    if proc.returncode != 0:
        raise IngestError(f"{cmd[0]} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def _page_text(pdf: Path, page: int) -> str:
    return _run(["pdftotext", "-f", str(page), "-l", str(page), str(pdf), "-"])


def _quality(image_path: Path) -> tuple[float, int, int]:
    """A 0-1 legibility proxy. BUILD §5 stage 1 wants a quality score per page.

    Contrast (pixel standard deviation) times edge energy, both normalised. Crude and
    deliberately so: this is triage, deciding which pages to escalate from the cheap OCR pass
    to the vision model, not a measurement anyone acts on directly. A blank or washed-out
    page scores near zero; a dense typed page scores high.
    """
    from PIL import Image, ImageFilter, ImageStat

    with Image.open(image_path) as im:
        w, h = im.size
        grey = im.convert("L")
        # Pillow's stddev is sqrt(var), and on a perfectly uniform page (blank scan) float
        # rounding can leave var a hair below zero, which raised "math domain error" and
        # failed the whole run. Clamp before the root.
        contrast = math.sqrt(max(0.0, ImageStat.Stat(grey).var[0])) / 128.0
        edges = ImageStat.Stat(grey.filter(ImageFilter.FIND_EDGES)).mean[0] / 64.0
    return round(min(1.0, contrast * 0.5 + min(1.0, edges) * 0.5), 3), w, h


#: Target long edge, in pixels, for a rendered page. Chosen so a dense typed form stays
#: legible to both readers without pushing the vision model past its image budget: the
#: verification copy's own scans are 910x1287 to 1684x2548, and reads are reliable across
#: that range.
_TARGET_LONG_PX = 2200


def _page_size_pts(pdf: Path) -> tuple[float, float]:
    """Page size in points, from pdfinfo. Falls back to A4 if it cannot be read."""
    out = _run(["pdfinfo", str(pdf)])
    m = re.search(r"Page size:\s*([\d.]+)\s*x\s*([\d.]+)", out)
    return (float(m.group(1)), float(m.group(2))) if m else (595.0, 842.0)


def _page_sizes_pts(pdf: Path, total: int) -> dict[int, tuple[float, float]]:
    """Every page's size in points, from one pdfinfo call."""
    out = _run(["pdfinfo", "-f", "1", "-l", str(total), str(pdf)])
    return {int(m.group(1)): (float(m.group(2)), float(m.group(3)))
            for m in re.finditer(r"Page\s+(\d+)\s+size:\s*([\d.]+)\s*x\s*([\d.]+)", out)}


def _oversized_pages(pdf: Path, total: int, dpi: int) -> list[tuple[int, int]]:
    """(page, megapixels) of every page that would render past the image limit at ``dpi``.

    The resolution is chosen from page 1, so a 428-byte PDF with an A4 first page and a
    9500 x 9500 pt second page rendered page 2 at 24,800 px square: 2.4 GB in pdftoppm, and the
    run failed only afterwards (audit 6 Oct 2026). Measured first now, from the PDF's own sizes."""
    from pipeline.bundle import MAX_FRAME_PIXELS
    out = []
    for n, (w, h) in _page_sizes_pts(pdf, total).items():
        pixels = (w * dpi / 72) * (h * dpi / 72)
        if pixels > MAX_FRAME_PIXELS:
            out.append((n, round(pixels / 1e6)))
    return out


def _render_dpi(pdf: Path) -> int:
    """Resolution that puts the long edge near ``_TARGET_LONG_PX``.

    A fixed DPI does not work across both shapes of input. This case file's pages measure
    1684 x 2548 pt because the scan is embedded at 72 ppi, so 150 dpi would render a
    3500 x 5300 image; an ordinary A4 page at 72 dpi would render 595 px wide, far too
    small to read a form. Scaling to a target pixel size handles both.
    """
    long_pts = max(_page_size_pts(pdf))
    return max(72, min(300, round(_TARGET_LONG_PX * 72 / long_pts)))


def _has_verification_headers(pdf: Path, total_pdf_pages: int) -> bool:
    """Is this the digitised verification copy, or a raw scan?

    Decided by looking, not by a flag the caller has to remember to pass. Only the first few
    sheets are inspected: the header is on every image page of the verification copy, so if
    it is absent from the first six there is no reason to read another eighty.
    """
    for pdf_page in range(1, min(total_pdf_pages, 6) + 1):
        if _HEADER_RE.search(_page_text(pdf, pdf_page)):
            return True
    return False


def _ingest_raw_scan(pdf: Path, out: Path, pages_dir: Path,
                     carried: dict[int, dict] | None = None) -> list[SourcePage]:
    """One rendered image per PDF page. For an ordinary departmental scan.

    Rendered with ``pdftoppm`` rather than extracted with ``pdfimages``, because a scanned
    page is not always one embedded image. In this case file page 2 carries a 2060x712
    fragment alongside the full page, and taking the largest embedded image would have fed
    a strip of the page to the classifier as though it were the whole document.

    ``header_title`` and ``transcription`` are empty: a raw scan carries no hand-made ground
    truth. Classification accuracy and value grounding therefore cannot be scored on this
    input -- the pipeline runs, but the verification harness has less to check it against.
    """
    from extraction import upright

    dpi = _render_dpi(pdf)
    total = int(_run(["pdfinfo", str(pdf)]).split("Pages:")[1].split()[0])
    too_big = _oversized_pages(pdf, total, dpi)
    if too_big:
        listed = ", ".join(f"p.{n} ({mp} Mpx)" for n, mp in too_big[:5])
        raise IngestError(f"{len(too_big)} page(s) of {pdf.name} are far larger than a document page and would "
                          f"not render safely at {dpi} dpi: {listed}. Scan them again at a normal size.")
    # Asked only about a page whose text runs up the side, twice, at about two seconds a
    # call. Built once; if the vision service is not up, those pages are left exactly as they
    # were scanned and the manifest says so.
    judge = upright.vision_judge()
    pages: list[SourcePage] = []
    fields = set(SourcePage.__dataclass_fields__)
    for n in range(1, total + 1):
        row = (carried or {}).get(n)
        if row is not None and (out / row["image_path"]).exists():
            pages.append(SourcePage(**{k: v for k, v in row.items() if k in fields}))
            continue
        produced = sorted(pages_dir.glob(f"p{n:03d}-*.png")) or sorted(
            pages_dir.glob(f"p{n:03d}.png")
        )
        if not produced:
            _run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(n), "-l", str(n),
                  str(pdf), str(pages_dir / f"p{n:03d}")])
            produced = sorted(pages_dir.glob(f"p{n:03d}*.png"))
        if not produced:
            raise IngestError(f"page {n} of {pdf.name} could not be rendered")
        image = max(produced, key=lambda q: q.stat().st_size)
        # A form scanned sideways is turned upright HERE, before the quality score, the
        # classifier, the OCR pass, the extractor or the officer's own preview sees it --
        # so all of them read the same image. extraction/upright.py explains how the angle
        # is chosen; the page as rendered is kept beside it.
        turn = upright.decide(image, judge)
        if turn.rotated:
            upright.apply(image, turn.rotation, image.with_name(f"{image.stem}-as-scanned.png"))
        quality, w, h = _quality(image)
        pages.append(SourcePage(
            page=n,
            image_path=str(image.relative_to(out)),
            header_title="",
            transcription="",
            quality=quality,
            width=w,
            height=h,
            rotation=turn.rotation,
            rotation_basis=turn.basis,
        ))
    return pages


def ingest(
    pdf_path: str | Path,
    out_dir: str | Path,
    *,
    force: bool = False,
    carried: dict[int, dict] | None = None,
) -> dict:
    """Split the digitised case file into source pages. Idempotent and resumable.

    ``carried`` (a resubmission, ``pipeline.carryover``) gives the manifest rows of pages an
    earlier round already rendered and turned upright; those are taken as they are. Only a
    departmental scan carries pages -- a verification copy never does.

    Re-running skips work already on disk (BUILD §5.1: "a failure at stage 6 re-runs stage 6,
    not stages 1-5"), unless ``force``. The manifest records the source hash, so a different
    PDF under the same name is detected rather than silently mixed with existing artefacts.
    """
    pdf = Path(pdf_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pages_dir = out / "pages"
    pages_dir.mkdir(exist_ok=True)
    manifest_path = out / MANIFEST_NAME

    source_hash = sha256_of(pdf)

    existing = None if force else read_checkpoint(manifest_path)
    if existing is not None:
        if existing.get("source_sha256") == source_hash:
            return existing
        raise IngestError(
            f"{manifest_path} was built from a different source "
            f"({existing.get('source_sha256', '?')[:12]} vs {source_hash[:12]}). "
            "Pass force=True to rebuild, or use a fresh output directory."
        )

    total_pdf_pages = int(
        _run(["pdfinfo", str(pdf)]).split("Pages:")[1].split()[0]
    )

    # Which shape of input is this? The verification copy interleaves scans with typed
    # transcriptions under 'SOURCE PAGE n of m' headers; a departmental case file is just
    # pages. Both are supported, and the difference is detected rather than declared.
    if not _has_verification_headers(pdf, total_pdf_pages):
        pages = _ingest_raw_scan(pdf, out, pages_dir, carried=carried)
        pages.sort(key=lambda p: p.page)
        manifest = {
            "source_file": pdf.name,
            "source_sha256": source_hash,
            "source_pages": len(pages),
            "pdf_pages": total_pdf_pages,
            "source_kind": "raw_scan",
            "pages": [p.to_dict() for p in pages],
        }
        atomic_write_text(manifest_path, json.dumps(manifest, indent=2))
        return manifest

    pages: list[SourcePage] = []
    for pdf_page in range(1, total_pdf_pages + 1):
        text = _page_text(pdf, pdf_page)
        m = _HEADER_RE.search(text)
        if not m:
            continue  # front matter, or a transcription sheet
        source_no, _total, title = int(m.group(1)), int(m.group(2)), m.group(3).strip()

        # The transcription for this page is the next PDF sheet.
        transcription = ""
        if pdf_page + 1 <= total_pdf_pages:
            nxt = _page_text(pdf, pdf_page + 1)
            if f"TRANSCRIPTION — SOURCE PAGE {source_no} " in nxt or \
               f"TRANSCRIPTION - SOURCE PAGE {source_no} " in nxt:
                transcription = nxt.strip()

        stem = pages_dir / f"p{source_no:03d}"
        produced = sorted(pages_dir.glob(f"p{source_no:03d}-*.png"))
        if not produced:
            _run(["pdfimages", "-f", str(pdf_page), "-l", str(pdf_page), "-png",
                  str(pdf), str(stem)])
            produced = sorted(pages_dir.glob(f"p{source_no:03d}-*.png"))
        if not produced:
            raise IngestError(
                f"source page {source_no} (pdf p.{pdf_page}) carries no embedded image"
            )
        # Largest image is the scan; anything smaller is a logo or rule.
        image = max(produced, key=lambda p: p.stat().st_size)
        quality, w, h = _quality(image)

        pages.append(
            SourcePage(
                page=source_no,
                image_path=str(image.relative_to(out)),
                header_title=title,
                transcription=transcription,
                quality=quality,
                width=w,
                height=h,
            )
        )

    if not pages:
        raise IngestError(
            f"no 'SOURCE PAGE n of m' headers found in {pdf.name}; this ingest is written "
            "for the digitised verification copy, not for a raw scan"
        )

    pages.sort(key=lambda p: p.page)
    manifest = {
        "source_file": pdf.name,
        "source_sha256": source_hash,
        "source_pages": len(pages),
        "pdf_pages": total_pdf_pages,
        "source_kind": "verification_copy",
        "pages": [p.to_dict() for p in pages],
    }
    atomic_write_text(manifest_path, json.dumps(manifest, indent=2))
    return manifest


def load_manifest(out_dir: str | Path) -> dict:
    path = Path(out_dir) / MANIFEST_NAME
    if not path.exists():
        raise IngestError(f"no manifest at {path}; run ingest() first")
    manifest = read_checkpoint(path)
    if manifest is None:
        raise IngestError(
            f"{path} is unreadable -- it was left truncated by an interrupted run. "
            "Re-ingest the source PDF to rebuild it."
        )
    return manifest


def source_pages(manifest: dict, out_dir: str | Path) -> list[SourcePage]:
    out = Path(out_dir)
    return [
        SourcePage(**{**p, "image_path": str(out / p["image_path"])})
        for p in manifest["pages"]
    ]
