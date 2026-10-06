"""Put a sideways-scanned form the right way up before it is read. BRAIN §5.3.

The prescribed forms are portrait documents. Scanned on a flatbed in a hurry they arrive as
landscape pages with the text running up the side, and the vision model does not turn them
round in its head: on the Disabled Son bundle it read a signed Form D-II that way and returned
"Husband" for a claimant the form calls "Son, Disable", the same name for the pensioner, the
prior pensioner and the claimant, and dates no calendar has. Page classification survived --
the heading is legible at any angle -- so the case reached stage 4 and was then determined on
nonsense.

Choosing the orientation
------------------------
OCR cannot choose it. PaddleOCR-VL reads that page equally well at 0, 90 and 270 degrees
(scores 109 / 101 / 107 on the real image), which is admirable and useless here. The reader
that is orientation-sensitive is the one that matters -- the vision model -- so the choice is
made by reading the form once under its own schema at each candidate orientation and scoring
what came back on DETERMINISTIC sanity: do the date fields parse as dates, is the claimant a
different person from the deceased, are the rupee figures whole positive numbers. The
orientation whose read makes sense is the one the page is then read from, twice, as usual.
Where no rotation reads better than the page as scanned, the page is left as it was.

Cost: one single read per candidate, on landscape form pages only. The rotated copy is kept
beside the page so an auditor can see exactly which image the figures were read from.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y")
_NAME_NOISE = re.compile(r"[^a-z ]+")
_HONORIFICS = {"mst", "mr", "mrs", "ms", "miss", "late", "s/o", "d/o", "w/o", "mohtarma"}


def _parses_as_date(text: str) -> bool:
    raw = (text or "").strip()[:10]
    for fmt in _DATE_FORMATS:
        try:
            when = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return 1940 <= when.year <= 2100
    return False


def _name_key(text: str | None) -> str:
    words = _NAME_NOISE.sub(" ", (text or "").casefold()).split()
    return " ".join(w for w in words if w not in _HONORIFICS)


def field_sanity_score(data: dict[str, Any]) -> int:
    """How much like a correctly read form this extraction is. Higher is better.

    Every term is a check an officer would make by eye, written so a wrong orientation loses
    on it: a sideways read yields dates that are not dates, one name in every name field, and
    amounts that are not amounts. No term rewards a particular answer.
    """
    score = 0
    names: dict[str, str] = {}
    for key, node in (data or {}).items():
        if isinstance(node, dict) and "value" in node:
            value = node.get("value")
            filled = value not in (None, "")
            if key.startswith("date_"):
                if filled:
                    score += 2 if _parses_as_date(str(value)) else -2
            elif key.endswith("_name"):
                if filled:
                    score += 1
                    names[key] = _name_key(str(value))
            elif filled:
                score += 1
        elif key.endswith("_rs"):
            if isinstance(node, int) and node > 0:
                score += 1
    # Distinct people in distinct name fields. The deceased, the claimant and any prior
    # family pensioner are three people; a read that calls them all the same is wrong.
    distinct = {v for v in names.values() if v}
    if len(names) >= 2:
        score += 2 * (len(distinct) - 1) - 3 * (len(names) - len(distinct))
    return score


def upright_form_image(
    image: str | Path,
    page: int,
    *,
    schema_name: str,
    progress: Callable[[str], None] | None = None,
    read=None,
) -> Path:
    """The image to read a prescribed form from: the page itself, or its upright rotation.

    Only a LANDSCAPE page is considered -- a portrait form is taken as upright -- and the
    original is scored alongside the rotations, so a genuinely landscape document that reads
    well as it stands is left alone. Returns the path to read; writes ``<page>-rot090.png`` /
    ``<page>-rot270.png`` beside the page. ``read(image, schema_name)`` must return an object
    with a ``data`` dict; it defaults to one vision read under the form's schema.
    """
    from PIL import Image

    src = Path(image)
    try:
        with Image.open(src) as im:
            if im.height >= im.width:
                return src
            candidates = {0: src}
            for angle in (90, 270):
                out = src.with_name(f"{src.stem}-rot{angle:03d}.png")
                if not out.exists():
                    im.rotate(angle, expand=True).save(out)
                candidates[angle] = out
    except (OSError, ValueError):
        # Not an image this library can open. Orientation is a courtesy to the reader, never
        # a reason to stop the stage: the page is read as it is.
        return src

    if read is None:
        from .client import extract_page

        def read(path, schema):                       # noqa: E306
            return extract_page(path, schema, _retry_on_suspect=False)

    scores: dict[int, int] = {}
    for angle, path in candidates.items():
        try:
            scores[angle] = field_sanity_score(read(path, schema_name).data)
        except Exception:                                    # noqa: BLE001
            scores[angle] = -999
    # Highest score wins; on a tie the page as scanned, then the smaller rotation.
    best = max(scores, key=lambda a: (scores[a], a == 0, -a))
    if best == 0:
        return src
    if progress:
        shown = ", ".join(f"{a}:{s}" for a, s in sorted(scores.items()))
        progress(f"p.{page:>2}  landscape scan of a form: read upright at {best} degrees "
                 f"(field-sanity scores {shown})")
    return candidates[best]
