"""Stage 0: turn a mixed bundle of files into the one case PDF the pipeline reads.

A case uploaded as a zip holds whatever the department sent, one file per document: a scanned
PDF of the service book, a phone photograph of a CNIC, a Word copy of the LPC, a JPEG of the
death certificate. The pipeline reads one PDF. Everything between those two facts lives here.

    zip  ->  extract  ->  convert each member to PDF  ->  merge in order  ->  one case PDF

Nothing is thrown away silently. Every member of the bundle comes back in the manifest with
what became of it: the page range it occupies in the merged file, or the reason it could not
be converted. A bundle whose third attachment was an unreadable `.msg` is still processed --
the officer is told which document is missing from the pages rather than the pipeline pretending
the bundle was complete. BRAIN §15.2: flag, cite, escalate, never guess.

The tools are the ones the box already has and a DGX Spark image ships with: poppler's
``pdfunite`` and ``pdfinfo`` (ingest already depends on poppler), LibreOffice headless for
office formats, and Pillow for images. No new third-party wheel enters the project for this.

**Page geometry is normalised deliberately.** ``pipeline.ingest._render_dpi`` picks a rendering
resolution from the first page's size, so a merged file that opened with a 200x300 pt phone
photograph would have every later page rendered at the resolution that photograph implied.
Images and office documents are therefore laid onto an A4 page here, and only genuine scanned
PDFs keep their own geometry.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import signal
import subprocess
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

#: A4 in points. What an office scanner produces and what LibreOffice writes.
A4 = (595.276, 841.89)

#: Guards against a bundle that is hostile or simply wrong. A pension case is tens of files,
#: not thousands, and the counter's scanner produces tens of megabytes, not gigabytes.
MAX_MEMBERS = 300
MAX_UNCOMPRESSED = 512 * 1024 * 1024
#: One nested zip is a department that zipped a folder of zips; two is a mistake.
MAX_DEPTH = 2
#: Frames taken from one multi-page TIFF or animated GIF. A scanner's multi-page TIFF of a
#: service book is tens of pages; an animated GIF of thousands is not a document.
MAX_FRAMES = 200
#: Pixels in one frame, read from the file's header before anything is decoded. A 600 dpi A4
#: scan is 35 Mpx; a frame past this is not a page from a counter scanner. Without it a 1 MB
#: group-4 TIFF of 200 frames at 9000x9000 asked for ~25 GB (audit 6 Oct 2026, item 5).
MAX_FRAME_PIXELS = 50_000_000
#: Pixels across all the frames taken from one image file: 200 frames of 2 Mpx, or eleven
#: 600 dpi A4 pages.
MAX_IMAGE_PIXELS = 400_000_000

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
#: HTML is not among them: LibreOffice renders a web page by fetching every address in it, so
#: one <img src=...> made the server request internal addresses and embed local files in the
#: case PDF (audit 6 Oct 2026, item 6). An .html member is now "not a document".
OFFICE_EXT = {".doc", ".docx", ".odt", ".rtf", ".txt", ".csv", ".xls", ".xlsx", ".ods",
              ".ppt", ".pptx", ".odp"}
#: The import filter each extension is opened with. Forced: left to itself LibreOffice decides
#: the type from the content, and HTML saved as notice.doc or notice.rtf was opened as a web
#: page and fetched its addresses all the same.
_OFFICE_FILTERS = {
    ".doc": "MS Word 97", ".docx": "MS Word 2007 XML", ".odt": "writer8",
    ".rtf": "Rich Text Format", ".txt": "Text (encoded):UTF8", ".csv": "Text - txt - csv (StarCalc)",
    ".xls": "MS Excel 97", ".xlsx": "Calc MS Excel 2007 XML", ".ods": "calc8",
    ".ppt": "MS PowerPoint 97", ".pptx": "Impress MS PowerPoint 2007 XML", ".odp": "impress8",
}
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_OLE_EXT = {".doc", ".xls", ".ppt"}
_PACKAGE_EXT = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}
#: Field codes that make Word or LibreOffice load another file or address when the document
#: is opened. Checked in ASCII and in UTF-16 (how .doc stores its text).
_LOAD_FIELDS = re.compile(rb"INCLUDEPICTURE|INCLUDETEXT|\bLINK\s+\w+\.\w+|\bDDE(?:AUTO)?\b"
                          rb"|\\objautlink|\\objlink|\\objupdate")
#: An OOXML relationship to something outside the package. Hyperlinks are allowed: they are
#: shown, never fetched on opening.
_RELATIONSHIP = re.compile(rb"<Relationship\b[^>]*>", re.I)
#: An OpenDocument element that loads what its xlink:href names, pointing outside the package.
_ODF_LOADS = re.compile(rb"<(?:draw:image|draw:object|draw:object-ole|draw:fill-image|draw:plugin"
                        rb"|draw:applet|text:section-source|style:background-image|form:\w+)\b"
                        rb"[^>]*xlink:href=\"(?!#|\./|Pictures/|Object |ObjectReplacements/)[^\"]+\"")
#: Junk that archivers add and that is never a pension document.
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}

_SOFFICE_TIMEOUT = 180
_DIGITS = re.compile(r"(\d+)")


class BundleError(RuntimeError):
    """The bundle could not be turned into a case file. The message is shown to the officer."""


@dataclass
class Part:
    """One member of the bundle, and what became of it."""

    index: int
    name: str                    #: path inside the zip, as the department named it
    kind: str                    #: pdf | image | office | archive | unknown
    bytes: int
    sha256: str
    converter: str = ""          #: how it became PDF: "" (already PDF), pillow, libreoffice
    pages: int = 0
    page_from: int = 0           #: 1-based, in the merged case file; 0 where it contributed none
    page_to: int = 0
    skipped: str = ""            #: why it is not in the merged file; empty where it is
    note: str = ""               #: what was kept back from a document that is in it, if anything


@dataclass
class Bundle:
    """The merged case file and the account of what went into it."""

    pdf: bytes
    parts: list[Part] = field(default_factory=list)
    source_name: str = ""
    source_sha256: str = ""

    @property
    def pages(self) -> int:
        return sum(p.pages for p in self.parts if not p.skipped)

    @property
    def skipped(self) -> list[Part]:
        return [p for p in self.parts if p.skipped]

    def manifest(self) -> dict:
        return {
            "source": self.source_name,
            "source_sha256": self.source_sha256,
            "pages": self.pages,
            "documents": len([p for p in self.parts if not p.skipped]),
            "skipped": len(self.skipped),
            "parts": [asdict(p) for p in self.parts],
        }


def looks_like_zip(data: bytes) -> bool:
    """A zip's local file header, or the empty-archive form some tools write."""
    return data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def looks_like_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-" or data[:4] == b"%PDF"


def inspect(data: bytes, filename: str = "") -> list[dict]:
    """What a bundle holds, read from the zip's index alone -- no extraction, no conversion.

    Saying what arrived must not cost a minute of LibreOffice first. This reads the central directory and nothing else, so it costs nothing on a 200 MB bundle.
    """
    if looks_like_pdf(data):
        name = Path(filename).name or "case.pdf"
        return [{"name": name, "kind": "pdf", "bytes": len(data), "readable": True}]
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        members = [i for i in archive.infolist() if not i.is_dir() and not _is_junk(i.filename)]
    except zipfile.BadZipFile as exc:
        raise BundleError(f"not a readable zip archive: {exc}") from None
    return [
        {
            "name": i.filename,
            "kind": _kind(Path(i.filename)),
            "bytes": i.file_size,
            "readable": _kind(Path(i.filename)) != "unknown",
        }
        for i in sorted(members, key=lambda i: _natural_key(i.filename))
    ]


def _natural_key(name: str) -> tuple:
    """Sort ``page2.jpg`` before ``page10.jpg``, and a folder's files together.

    The order of the pages is the order the officer sees them in, so it has to be the order a
    person would put them in -- which is not ASCII order once a scanner starts numbering.
    """
    parts = Path(name).parts
    return tuple(
        tuple((int(t), "") if t.isdigit() else (0, t.casefold()) for t in _DIGITS.split(p) if t)
        for p in parts
    )


def _is_junk(name: str) -> bool:
    lower = Path(name).name.casefold()
    return (name.startswith("__MACOSX/") or lower in JUNK_NAMES or lower.startswith("._")
            or name.endswith("/"))


def _kind(path: Path) -> str:
    ext = path.suffix.casefold()
    if ext == ".pdf":
        return "pdf"
    if ext in IMAGE_EXT:
        return "image"
    if ext in OFFICE_EXT:
        return "office"
    if ext == ".zip":
        return "archive"
    return "unknown"


class _OverBudget(BundleError):
    """The bundle as a whole, nested zips included, is past MAX_MEMBERS or MAX_UNCOMPRESSED."""


@dataclass
class _Budget:
    """What the whole bundle has cost so far, counted across every level of nested zip.

    Checked per archive alone, a zip of ten zips each just under the limits would be ten times
    the limit. The counts are shared, so the guard is on the bundle, not on each box in it.
    """

    members: int = 0
    expanded: int = 0

    def admit(self, members: int, expanded: int) -> None:
        self.members += members
        self.expanded += expanded
        if self.members > MAX_MEMBERS:
            raise _OverBudget(f"the zip holds {self.members} files; the limit is {MAX_MEMBERS}")
        if self.expanded > MAX_UNCOMPRESSED:
            raise _OverBudget(f"the zip expands to {self.expanded // 1048576} MB; the limit is "
                              f"{MAX_UNCOMPRESSED // 1048576} MB")


def _copy_capped(src, dst, budget: _Budget, declared: int) -> None:
    """Copy one member, holding it to the bytes its header declared and the bundle's budget."""
    written = 0
    while True:
        chunk = src.read(1024 * 1024)
        if not chunk:
            return
        written += len(chunk)
        if written > declared:
            # The header is what the budget was charged; anything past it is uncharged.
            budget.admit(0, written - declared)
            declared = written
        dst.write(chunk)


def _safe_extract(data: bytes, into: Path, *, depth: int = 1, budget: _Budget | None = None,
                  problems: dict[str, str] | None = None) -> list[tuple[str, Path]]:
    """Extract a zip to ``into``, refusing anything that would write outside it.

    ``zipfile.extractall`` is not used: it will happily be handed a member named
    ``../../etc/cron.d/x`` by anyone who can attach a file to a helpdesk ticket. Members are
    written one at a time, under a name derived from the archive's but rooted here.

    A member that cannot be read out goes into ``problems`` with the reason, and stays in the
    list so the manifest names it; only the bundle-wide budget stops the extraction.
    """
    budget = budget if budget is not None else _Budget()
    problems = problems if problems is not None else {}
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        members = [i for i in archive.infolist() if not i.is_dir() and not _is_junk(i.filename)]
    except Exception as exc:                                     # noqa: BLE001
        raise BundleError(f"not a readable zip archive: {exc}") from None

    if not members:
        raise BundleError("the zip holds no files")
    budget.admit(len(members), sum(i.file_size for i in members))

    out: list[tuple[str, Path]] = []
    for info in sorted(members, key=lambda i: _natural_key(i.filename)):
        rel = Path(*(p for p in Path(info.filename).parts
                     if p not in ("..", "/", "\\") and not p.startswith("/")))
        if not rel.name:
            continue
        target = (into / rel).resolve()
        if not str(target).startswith(str(into.resolve())):
            continue                                   # member tried to escape; drop it
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with archive.open(info) as src, target.open("wb") as dst:
                _copy_capped(src, dst, budget, info.file_size)
        except _OverBudget:
            raise
        except Exception as exc:                                 # noqa: BLE001
            # Encrypted members raise RuntimeError("File is encrypted"); a damaged one
            # BadZipFile, zlib.error or EOFError; an unsupported method NotImplementedError.
            # One unreadable attachment must not lose the other nine.
            target.write_bytes(b"")
            problems[info.filename] = (f"could not be read out of the zip "
                                       f"({type(exc).__name__}: {str(exc)[:160]})")
            out.append((info.filename, target))
            continue
        if target.suffix.casefold() == ".zip":
            if depth >= MAX_DEPTH:
                problems[info.filename] = ("a zip inside a zip inside the bundle is not opened; "
                                           "attach its documents directly")
                out.append((info.filename, target))
                continue
            nested = target.parent / f"{target.stem}.unzipped"
            nested.mkdir(parents=True, exist_ok=True)
            sub: dict[str, str] = {}
            try:
                inner = _safe_extract(target.read_bytes(), nested, depth=depth + 1,
                                      budget=budget, problems=sub)
            except _OverBudget:
                raise
            except BundleError as exc:
                problems[info.filename] = f"the zip inside the bundle could not be opened: {exc}"
                out.append((info.filename, target))
                continue
            problems.update({f"{info.filename}!{n}": why for n, why in sub.items()})
            out.extend((f"{info.filename}!{n}", p) for n, p in inner)
            continue
        out.append((info.filename, target))
    return out


def _run(cmd: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _pdf_pages(pdf: Path) -> int:
    proc = _run(["pdfinfo", str(pdf)])
    if proc.returncode != 0:
        raise BundleError(f"pdfinfo could not read {pdf.name}: {proc.stderr.strip()[:200]}")
    for line in proc.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise BundleError(f"{pdf.name} reports no page count")


def _upright(frame):
    """One frame, turned the way its EXIF orientation tag says, as an RGB copy of its own.

    A phone held sideways writes the picture in sensor order and records the rotation in an
    EXIF tag; the gallery honours it, so the clerk who attached it saw an upright CNIC.
    Ignoring the tag is how that same card arrives here on its side, and no amount of
    cleverness later recovers what the camera already told us. Applied first, so the detection
    at ingest only has to deal with pages nothing declared. A frame whose tag cannot be read
    is taken as it is.
    """
    from PIL import ImageOps
    try:
        frame = ImageOps.exif_transpose(frame) or frame
    except Exception:                                            # noqa: BLE001
        pass
    return frame.convert("RGB")


def image_problem(src) -> str | None:
    """Why this image file must not be decoded, judged from its headers alone; None if it may.

    ``src`` is a path or a binary file object. ``Image.open`` reads headers and decodes
    nothing, and moving to a TIFF frame reads that frame's directory, not its pixels; so a
    file is measured frame by frame (up to ``MAX_FRAMES``) before a byte of image data is
    unpacked. A GIF's logical screen bounds every frame and is read before any frame is
    counted. Anything Pillow cannot open is not this function's to judge (None): the
    conversion reports it.
    """
    from PIL import Image
    try:
        with Image.open(src) as im:
            w, h = im.size
            if w * h > MAX_FRAME_PIXELS:
                return (f"is {w} x {h} pixels; a page may have at most "
                        f"{MAX_FRAME_PIXELS // 1_000_000} million")
            total = 0
            n = 0
            while n < MAX_FRAMES:
                w, h = im.size
                if w * h > MAX_FRAME_PIXELS:
                    return (f"page {n + 1} is {w} x {h} pixels; a page may have at most "
                            f"{MAX_FRAME_PIXELS // 1_000_000} million")
                total += w * h
                if total > MAX_IMAGE_PIXELS:
                    return (f"holds more than {MAX_IMAGE_PIXELS // 1_000_000} million pixels by page "
                            f"{n + 1}; split it into smaller files")
                n += 1
                try:
                    im.seek(n)
                except EOFError:
                    break
    except Image.DecompressionBombError as exc:
        return f"is too large to open safely ({exc})"
    except Exception:                                            # noqa: BLE001
        return None
    return None


def _image_to_pdf(src: Path, dst: Path) -> str:
    """One image, one A4 page, the image fitted inside it at full resolution.

    Fitted rather than stretched: a CNIC photographed in landscape stays the shape it was
    photographed in, because a stretched identity card is one the officer cannot check against
    the form. Multi-frame TIFFs keep all their frames -- a scanner set to multi-page TIFF is
    a normal thing to find at the counter -- up to ``MAX_FRAMES``; the note returned says
    where one was cut short, and is empty otherwise.

    The frames are read from the file as opened. ``exif_transpose`` returns a single-frame
    copy, so iterating what it returned read the first page of a multi-page TIFF and nothing
    else.
    """
    import tempfile

    from PIL import Image, ImageSequence

    problem = image_problem(src)
    if problem:
        raise BundleError(f"{src.name} {problem}")
    with Image.open(src) as opened, tempfile.TemporaryDirectory(dir=dst.parent) as tmp:
        try:
            total = int(getattr(opened, "n_frames", 1) or 1)
        except Exception:                                        # noqa: BLE001
            total = 1
        # Each page is written as soon as it is made and merged at the end, so one page is in
        # memory at a time rather than every page of the file (audit 6 Oct 2026, item 5).
        written: list[Path] = []
        canvas = (0, 0)
        dpi = 72.0
        for n, raw in enumerate(ImageSequence.Iterator(opened)):
            if n >= MAX_FRAMES:
                break
            frame = _upright(raw)
            if n == 0:
                w, h = frame.size
                box_w, box_h = (A4 if h >= w else (A4[1], A4[0]))
                # The page must measure A4 in points, and the image must keep the pixels it
                # arrived with: those two together fix the resolution. dpi = the pixels per
                # inch at which this image already fills the page. Clamped, so a 20 MP
                # photograph of a CNIC does not become a 600 dpi page and a 90x60 thumbnail
                # does not become a 4 dpi one. Every later frame goes on a page this size.
                dpi = max(72.0, min(600.0, 72.0 * max(w / box_w, h / box_h)))
                canvas = (round(box_w * dpi / 72), round(box_h * dpi / 72))
            ratio = min(canvas[0] / frame.width, canvas[1] / frame.height)
            if ratio < 1:                      # only ever shrinks, never upscales a scan
                frame = frame.resize((max(1, round(frame.width * ratio)),
                                      max(1, round(frame.height * ratio))), Image.LANCZOS)
            page = Image.new("RGB", canvas, "white")
            page.paste(frame, ((canvas[0] - frame.width) // 2, (canvas[1] - frame.height) // 2))
            frame.close()
            one = Path(tmp) / f"{n:04d}.pdf"
            page.save(one, "PDF", resolution=dpi)
            page.close()
            written.append(one)
        if not written:
            raise BundleError(f"{src.name} holds no image")
        _merge(written, dst)
    if total > len(written):
        return f"only the first {len(written)} of {total} frames were taken (limit {MAX_FRAMES})"
    return ""


def office_problem(data: bytes, ext: str) -> str | None:
    """Why this Office file must not be handed to LibreOffice; None if it may.

    Its contents must be the kind its extension says -- a .doc that is really HTML is refused
    rather than converted -- and it may not load anything from outside itself on opening: a
    linked picture or object, an external template, an INCLUDEPICTURE/INCLUDETEXT/LINK/DDE
    field. LibreOffice follows those to any address the server can reach, and to local files
    (audit 6 Oct 2026, item 6). There is no sandbox to run it in on this host (unprivileged
    namespaces are disabled), so the document is refused before it is opened.
    """
    ext = ext.casefold()
    loads = "links to files or web addresses outside itself; save it as PDF and attach that"
    mismatch = f"is not really a {ext} file; save it as PDF and attach that"
    if ext in _OLE_EXT:
        if not data.startswith(_OLE_MAGIC):
            return mismatch
        if _LOAD_FIELDS.search(data) or _LOAD_FIELDS.search(data.replace(b"\x00", b"")):
            return loads
    elif ext in _PACKAGE_EXT:
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            return mismatch
        with zf:
            budget = 0
            for info in zf.infolist():
                if not info.filename.endswith((".xml", ".rels")):
                    continue
                budget += info.file_size
                if budget > MAX_UNCOMPRESSED:
                    return "is too large to check"
                xml = zf.read(info)
                for rel in _RELATIONSHIP.findall(xml):
                    if re.search(rb'TargetMode\s*=\s*"External"', rel, re.I) \
                            and not re.search(rb'Type\s*=\s*"[^"]*/hyperlink"', rel, re.I):
                        return loads
                if _ODF_LOADS.search(xml) or _LOAD_FIELDS.search(xml):
                    return loads
    elif ext == ".rtf":
        if not data.lstrip().startswith(b"{\\rtf"):
            return mismatch
        if _LOAD_FIELDS.search(data):
            return loads
    elif ext in (".txt", ".csv"):
        if b"\x00" in data[:65536]:
            return mismatch
    return None


def _office_to_pdf(src: Path, out_dir: Path, profile: Path) -> Path:
    """LibreOffice headless, in a throwaway profile so it never touches the user's own.

    A shared profile is how a second conversion running at the same time silently produces
    nothing: soffice sees a lock, attaches to the running instance and exits 0 having written
    no file. One profile per run, checked for the file afterwards.

    soffice is a launcher that starts ``soffice.bin``; killing the launcher on a timeout left
    the real process holding the profile, and every later document in the bundle attached to
    it and produced nothing. So it runs in a session of its own, the whole group is killed on
    a timeout, and the profile it may have left locked is thrown away for the next call.
    """
    ext = src.suffix.casefold()
    problem = office_problem(src.read_bytes(), ext)
    if problem:
        raise BundleError(f"{src.name} {problem}")
    if not shutil.which("soffice"):
        raise BundleError("LibreOffice (soffice) is not installed on this machine")
    proc = subprocess.Popen(
        ["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{profile}",
         f"--infilter={_OFFICE_FILTERS[ext]}",
         "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        _, stderr = proc.communicate(timeout=_SOFFICE_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.communicate()
        shutil.rmtree(profile, ignore_errors=True)
        raise BundleError(f"LibreOffice did not finish converting {src.name} within "
                          f"{_SOFFICE_TIMEOUT} s") from None
    produced = out_dir / f"{src.stem}.pdf"
    if not produced.exists():
        raise BundleError(f"LibreOffice produced no PDF ({(stderr or '').strip()[:160] or 'no error text'})")
    return produced


def _merge(pdfs: list[Path], dst: Path) -> None:
    """``pdfunite`` in order. One file is copied rather than "merged" with itself."""
    if len(pdfs) == 1:
        shutil.copyfile(pdfs[0], dst)
        return
    proc = _run(["pdfunite", *[str(p) for p in pdfs], str(dst)], timeout=300)
    if not dst.exists() or dst.stat().st_size == 0:
        raise BundleError(f"the documents could not be merged: {proc.stderr.strip()[:200]}")


def normalise(data: bytes, filename: str, workdir: Path, *,
              max_pages: int | None = None) -> Bundle:
    """Turn ``data`` -- a zip of mixed documents, or a lone PDF -- into one case PDF.

    ``workdir`` holds the extracted members and the per-part PDFs. It is kept, not cleaned:
    when an officer asks why page 31 says what it says, the file it came out of is still there
    under the name the department gave it.

    ``max_pages`` is for a caller that reads only the start of the case :
    once the merged file holds that many pages, the members after it are listed but not
    converted. None, the default, converts everything, as a run must.
    """
    workdir = Path(workdir)
    parts_dir = workdir / "parts"
    pdf_dir = workdir / "pdf"
    for d in (parts_dir, pdf_dir):
        d.mkdir(parents=True, exist_ok=True)

    problems: dict[str, str] = {}
    if looks_like_pdf(data):
        member = parts_dir / Path(filename).name
        member.write_bytes(data)
        members = [(Path(filename).name, member)]
    elif looks_like_zip(data):
        members = _safe_extract(data, parts_dir, problems=problems)
    else:
        raise BundleError("the file is neither a PDF nor a zip archive")

    parts: list[Part] = []
    merged_inputs: list[Path] = []
    profile = workdir / "lo-profile"
    page = 1

    for i, (name, path) in enumerate(members, start=1):
        raw = path.read_bytes() if path.exists() else b""
        part = Part(index=i, name=name, kind=_kind(Path(name)), bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest() if raw else "")
        parts.append(part)
        if name in problems:
            part.skipped = problems[name]
            continue
        if not raw:
            part.skipped = "the file is empty or could not be read out of the zip (encrypted?)"
            continue
        if max_pages is not None and page > max_pages:
            part.skipped = f"not converted: the first {max_pages} pages were all that was asked for"
            continue
        try:
            if part.kind == "pdf" or looks_like_pdf(raw):
                part.kind = "pdf"
                converted = pdf_dir / f"{i:03d}-{path.stem}.pdf"
                shutil.copyfile(path, converted)
            elif part.kind == "image":
                converted = pdf_dir / f"{i:03d}-{path.stem}.pdf"
                part.note = _image_to_pdf(path, converted)
                part.converter = "pillow"
            elif part.kind == "office":
                produced = _office_to_pdf(path, pdf_dir, profile)
                converted = pdf_dir / f"{i:03d}-{path.stem}.pdf"
                if produced != converted:
                    produced.replace(converted)
                part.converter = "libreoffice"
            else:
                part.skipped = (f"{Path(name).suffix or 'this kind of file'} is not a document "
                                f"the portal can read; attach it as PDF, an image or Word")
                continue
            part.pages = _pdf_pages(converted)
            if part.pages == 0:
                part.skipped = "the document holds no pages"
                continue
        except Exception as exc:                                 # noqa: BLE001
            # Whatever one attachment does -- a decompression bomb, a TIFF compression Pillow
            # has no codec for, a truncated deflate stream -- it is that attachment's failure,
            # recorded against it, and the rest of the bundle still becomes the case file.
            text = str(exc) if isinstance(exc, BundleError) else f"{type(exc).__name__}: {exc}"
            part.skipped = text[:300] or type(exc).__name__
            continue
        part.page_from, part.page_to = page, page + part.pages - 1
        page += part.pages
        merged_inputs.append(converted)

    if not merged_inputs:
        reasons = "; ".join(f"{p.name}: {p.skipped}" for p in parts[:5])
        raise BundleError(f"nothing in this bundle could be read as a document. {reasons}")

    case_pdf = workdir / "case.pdf"
    _merge(merged_inputs, case_pdf)
    return Bundle(pdf=case_pdf.read_bytes(), parts=parts,
                  source_name=Path(filename).name,
                  source_sha256=hashlib.sha256(data).hexdigest())


def describe(parts: Iterable[Part]) -> str:
    """One line for the event log: what the bundle turned out to hold."""
    parts = list(parts)
    kept = [p for p in parts if not p.skipped]
    kinds: dict[str, int] = {}
    for p in kept:
        kinds[p.kind] = kinds.get(p.kind, 0) + 1
    shape = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "nothing"
    tail = f" · {len(parts) - len(kept)} could not be read" if len(kept) != len(parts) else ""
    return f"{len(kept)} of {len(parts)} attachments merged ({shape}){tail}"
