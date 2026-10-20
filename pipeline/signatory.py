"""Who signed the sanction, and the specimen the department sent for that post.

Stage 6b. For each prescribed form in the bundle (Forms B-I..B-IV, D-I, D-II), the sanctioning
authority's signature block is read -- signer, designation, department, stamp, date, and where
on the page the signature is -- and the signature is cut out of the page. The specimen register
(rules/specimens) then says whether that department sent the AG a specimen for that post, in
force on that date. rules.flags.check_psa_specimen turns the result into findings: the printed
facts (post, name, stamp, date) are checked by code, and the signature itself is put beside the
specimen for the Auditor to compare by eye.

Why the signature is not judged by the model
--------------------------------------------
It was tried, five ways, on 23 September 2026 against the S&GAD specimen: 6 genuine signatures
(the three specimens, and three degraded as a photocopy would degrade them) and 12 signatures
of other officers cut from the sanction forms of real cases. Asked "same hand?" on the whole
page it called three other officers' signatures CONSISTENT; on a cut-out signature, still three
(14/18). Asked about the specimen's distinctive features one by one it answered YES to every
feature on every signature (6/18), and it answers YES to a leading question about a stroke the
signature plainly does not have. Asked to pick which of two candidates matches, it rejected two
of three genuine signatures. A check that passes a wrong signatory, or accuses a right one, is
worse than none; comparing a signature stays with a person, who now has the specimen in front
of them instead of in a file.

Writes ``psa_signatures.json`` and ``signatures/*.jpg`` in the run directory. Resumable: a form
already recorded is not read again, so ``refresh_psa_signatures`` brings an old run up to date
with one model call per form page.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable

from extraction.client import ExtractionError, extract_page
from pipeline.ingest import atomic_write_text
from rules import specimens

PSA_SIGNATURES = "psa_signatures.json"

#: The prescribed forms a Pension Sanctioning Authority signs (BRAIN §2, SOP §5.2 AG-04).
PRESCRIBED_FORMS = ("FORM_B_I", "FORM_B_II", "FORM_B_III", "FORM_B_IV", "FORM_D_I", "FORM_D_II")

BLOCK_INSTRUCTION = (
    "This is a page of a pension sanction form from a Punjab government department. Find the "
    "SANCTIONING AUTHORITY's signature block -- the officer who sanctions the pension, usually "
    "at the foot of the form over 'Pension Sanctioning Authority' or the officer's designation, "
    "with a rubber stamp. Ignore the pensioner's or claimant's own signature and any "
    "countersignature. Fill the schema from that block only; a value not printed there is null."
)

def read_block(image: Path, cache: dict | None = None) -> dict:
    """The signature block printed on this page.

    A pure function of the IMAGE: same schema, same instruction, same limits, no document in
    the question. So when several prescribed forms cite one page the answer is the same every
    time, and ``cache`` keeps it.

    That is not hypothetical. check_form runs once per form and the caller's de-duplication
    keys on (type, pages), so Form B-I, B-II, B-III and B-IV all sitting on page 13 -- which
    is what a departmental bundle looks like when the four sanction forms are printed on one
    sheet -- read that page four times and threw three answers away (20 Oct 2026).
    """
    key = str(image)
    if cache is not None and key in cache:
        return cache[key]
    ext = extract_page(image, "PSA_SIGNATURE_BLOCK", max_tokens=1024, timeout_s=180,
                       instruction_override=BLOCK_INSTRUCTION)
    if cache is not None:
        cache[key] = ext.data
    return ext.data


def _val(block: dict, name: str) -> str | None:
    node = block.get(name) or {}
    value = node.get("value")
    return str(value).strip() if value not in (None, "") else None


def _date(text: str | None) -> date | None:
    """"2025-10-02", "02/10/2025", "2-10-2025" -> a date; day before month, as Pakistan writes.

    "02.10.25" -> None: a two-digit year is not completed to 20xx (audit L1, 7 Oct 2026). The
    specimen lookup then compares the signature with the specimens in force today and the
    block carries ``date_signed_note`` so the officer sees why."""
    if not text:
        return None
    t = text.strip()
    try:
        return date.fromisoformat(t)
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$", t)
    if not m:
        return None
    d, mo, y = (int(g) for g in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def cut_signature(image: Path, box: list | None, out: Path) -> str | None:
    """Save the signature-and-stamp region of the page; None where the box is unusable."""
    if not box or len(box) != 4:
        return None
    x1, y1, x2, y2 = (max(0, min(1000, int(v))) for v in box)
    if x2 - x1 < 30 or y2 - y1 < 15:
        return None
    from PIL import Image
    im = Image.open(image).convert("RGB")
    w, h = im.size
    # A margin, because the model's box is tight and a clipped stroke end is what an eye compares.
    mx, my = (x2 - x1) * 0.12, (y2 - y1) * 0.2
    crop = im.crop((int(max(0, x1 - mx) * w / 1000), int(max(0, y1 - my) * h / 1000),
                    int(min(1000, x2 + mx) * w / 1000), int(min(1000, y2 + my) * h / 1000)))
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out, "JPEG", quality=90)
    return out.name


def check_form(run: Path, page_images: dict[int, Path], doc: dict, *,
               department_hint: str | None = None, register: tuple | None = None,
               block_cache: dict | None = None) -> dict:
    """One prescribed form: its signature block, the cut-out signature, and the specimen it answers to."""
    pages = [p for p in doc.get("pages", []) if p in page_images]
    blocks = []
    for page in pages:
        try:
            blocks.append((page, read_block(page_images[page], block_cache)))
        except ExtractionError as exc:
            blocks.append((page, {"_error": str(exc)}))
    # The page carrying the sanctioning authority's signature: the last one that shows it
    # (a D-I spans two pages and is signed on the second).
    signed = [(p, b) for p, b in blocks if b.get("signature_present") or b.get("stamp_present")]
    page, block = (signed or blocks or [(None, {})])[-1]

    entry: dict[str, Any] = {
        "document": doc["type"], "pages": pages, "page": page,
        "signature_present": bool(block.get("signature_present")),
        "stamp_present": bool(block.get("stamp_present")),
        "signer_name": _val(block, "signer_name"),
        "designation": _val(block, "designation"),
        "department": _val(block, "department"),
        "stamp_text": _val(block, "stamp_text"),
        "date_signed": _val(block, "date_signed"),
        "signature_image": None,
    }
    if "_error" in block:
        entry["unreadable"] = block["_error"]
    if page is not None and block.get("signature_present"):
        entry["signature_image"] = cut_signature(
            page_images[page], block.get("signature_box"),
            run / "signatures" / f"{doc['type']}-p{page}.jpg")

    # The stamp read again, by OCR, off the cut-out, where it is large: on the whole page the
    # vision model read an S&GAD stamp as "S R G A D" once and "S R G A N" the next time. OCR
    # is asked for characters only; what they mean is decided by the register's matcher.
    if entry["signature_image"]:
        try:
            from extraction.ocr import ocr_page
            entry["stamp_ocr"] = " / ".join(
                line.strip() for line in ocr_page(run / "signatures" / entry["signature_image"],
                                                  page or 0, max_tokens=256, timeout_s=60).text.splitlines()
                if line.strip())[:400] or None
        except Exception as exc:                      # noqa: BLE001 -- OCR is a second opinion
            entry["stamp_ocr"] = None
            entry["stamp_ocr_error"] = str(exc)[:200]

    # The department: what the block itself says, else the stamp, else the forwarding letter.
    signed_on = _date(entry["date_signed"])
    entry["date_signed_iso"] = signed_on.isoformat() if signed_on else None
    from rules.case_type import two_digit_year
    written = two_digit_year(entry["date_signed"]) if signed_on is None else None
    entry["date_signed_note"] = (
        f"The signature is dated '{written}', a year written with two digits; the date was not "
        f"used and the specimens in force today were compared. Confirm the date on the page."
    ) if written else None
    ocr = entry.get("stamp_ocr")
    post = " / ".join(t for t in (entry["designation"], entry["stamp_text"], ocr) if t)
    dept = " / ".join(t for t in (entry["department"], entry["stamp_text"], ocr) if t)
    spec, why = specimens.lookup(dept, post, signed_on, register)
    if why == "department not on file" and department_hint:
        spec, why = specimens.lookup(department_hint, post, signed_on, register)
        if spec is not None or why != "department not on file":
            entry["department_from"] = "forwarding letter"
    entry["specimen"] = spec.id if spec else None
    entry["specimen_status"] = why
    return entry


def _department_hint(run: Path) -> str | None:
    """The forwarding department, as the report's issuing offices name it, for a block that doesn't."""
    facts = run / "assertions.json"
    if not facts.exists():
        return None
    offices = json.loads(facts.read_text()).get("issuing_offices") or []
    names = [o.get("value") if isinstance(o, dict) else str(o) for o in offices]
    return " / ".join(n for n in names if n) or None


def stage_psa_signatures(run_dir: str | Path, *, progress: Callable[[str], None] | None = None,
                         register: tuple | None = None) -> dict:
    """Read and compare every prescribed form's sanctioning signature. Resumable per form."""
    run = Path(run_dir)
    out_path = run / PSA_SIGNATURES
    result = json.loads(out_path.read_text()) if out_path.exists() else {"forms": []}
    done = {(f["document"], tuple(f["pages"])) for f in result["forms"]}
    manifest = json.loads((run / "manifest.json").read_text())
    images = {p["page"]: run / p["image_path"] for p in manifest["pages"]}
    documents = json.loads((run / "documents.json").read_text())
    hint = _department_hint(run)
    #: One read per PAGE, not per form. The loop below de-duplicates on (type, pages), which
    #: does not help when four different forms sit on one sheet.
    block_cache: dict = {}
    for doc in documents:
        if doc["type"] not in PRESCRIBED_FORMS or not doc.get("pages"):
            continue
        key = (doc["type"], tuple(p for p in doc["pages"] if p in images))
        if key in done:
            continue
        if progress:
            progress(f"signature  {doc['type']} p.{','.join(map(str, key[1]))}")
        result["forms"].append(check_form(run, images, doc, department_hint=hint,
                                          register=register, block_cache=block_cache))
        atomic_write_text(out_path, json.dumps(result, indent=2, ensure_ascii=False, default=str))
    result["register"] = [s.id for s in (register if register is not None else specimens.load())]
    atomic_write_text(out_path, json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return result


refresh_psa_signatures = stage_psa_signatures
