"""Turn a sideways page the right way up, at ingest, before anything reads it.

A counter scans a portrait form on a flatbed in a hurry and it arrives as a landscape page
with the text running up the side. The vision model does not turn it round in its head: on the
Disabled Son bundle it read a signed Form D-II that way and returned the same name for the
pensioner, the prior pensioner and the claimant, and dates no calendar has
(``extraction/orient.py`` exists because of that case). That module fixes the form at stage 4,
one page, by re-reading it. This one fixes **every** page at stage 1, so the classifier, the
OCR pass, the extractor and the officer's own preview all see the same upright image.

**Portrait is not the goal; upright text is.** Some documents are genuinely landscape -- a
wide pay table, some FRC layouts -- and rotating those would put readable text on its side.
Page shape cannot tell the two apart: a portrait page photographed sideways and a wide table
have the same aspect ratio. So the decision is made on where the *text* runs, not on the shape
of the paper.

How the angle is chosen
-----------------------
Two questions, answered by two different means, because they have different costs:

1.  **Which way do the text lines run?** Deterministic and free: binarise, smear the ink
    sideways with a wide morphological kernel, and see whether the blobs that result are wide
    (lines of text running across the page) or tall (lines running up it). ~40 ms a page, and
    it decides whether the page is touched at all. Most pages stop here.
2.  **Clockwise or anticlockwise?** The vision model is asked, once per candidate: is the text
    on this page the right way up, or upside down. Two calls of about two seconds, on sideways
    pages only, and the page is turned **only where exactly one of the two candidates comes
    back upright**. Where both look upside down to it, or both look upright, nothing is turned.

The second question was first answered by geometry -- line starts are tidier than line ends on
left-aligned text, and that ought to invert when the page is upside down. It is a real signal
and it is not good enough: on a bank form of ruled boxes it chose confidently and wrongly, with
the same margin (1.34) as a correct call on a family list. A cue that is wrong at full
confidence cannot be the decider, so the ratio is now recorded as an observation and the model
makes the call. OCR cannot do it either: PaddleOCR turns text lines round internally, so it
read the same sideways form at 2304 characters one way and 2211 the other.

180° on a page that is already portrait is deliberately not attempted. Catching it would mean
asking the model about every page rather than the rare sideways one, and a page turned by
mistake is worse than one left alone.

Nothing is overwritten: the page as rendered is kept beside the upright copy and the angle is
recorded in the manifest, so an auditor can see what the department sent as well as what the
engine read. "The AI silently rotated the evidence" is not a sentence anyone wants in an audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

#: Blobs wider than this ratio are lines of text lying across the page; taller than its
#: reciprocal, lines running up it. Deliberately blunt: a line of print is many times longer
#: than it is tall whichever way the page is turned.
_LINE_RATIO = 2.5

#: How much of the ink has to agree before the page is called sideways. A page whose text
#: runs both ways -- a table with rotated column headings, a stamp across a form -- is left
#: alone rather than rotated on a slim majority.
_MAJORITY = 0.65

#: Fewer line-shaped blobs than this and there is not enough text to judge: a photograph of a
#: CNIC, a page carrying one stamp. Left as scanned.
_MIN_LINES = 8

#: How much tidier the line starts must be, one way round than the other, for the layout to
#: settle the direction by itself. Set from the two sideways pages in the sample bundles: the
#: Annex-A clears it at 1.34 and the Form D-II, whose boxes and rules give it much less prose
#: to go on, at 1.14. Below this the reader is asked instead.
_TIDY_MARGIN = 1.10

#: How much more text the reader must find one way round than the other before its vote counts.
#: It is a model, it is not deterministic, and on the Form D-II it returned 2304 characters
#: against 2211 one minute and the reverse the next -- a margin that narrow is noise, and the
#: page is left alone rather than turned on it.
_READ_MARGIN = 1.20


@dataclass
class Orientation:
    """What was decided about one page, and why. Recorded in the manifest."""

    rotation: int = 0            #: degrees anticlockwise to apply; 0, 90 or 270
    basis: str = "upright"       #: how it was decided, in words, for the audit trail
    horizontal_lines: int = 0
    vertical_lines: int = 0

    @property
    def rotated(self) -> bool:
        return self.rotation != 0


def text_axis(image_path: str | Path) -> tuple[str, int, int]:
    """Which way the text lines run: ``horizontal``, ``vertical`` or ``unclear``.

    Returns the axis and the two line counts, so a caller can record what it saw rather than
    just what was concluded.
    """
    import cv2

    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return "unclear", 0, 0

    # Downscale first: this is a shape question, and a 2200 px page answers it as well at 1000.
    height, width = img.shape[:2]
    if max(height, width) > 1000:
        scale = 1000 / max(height, width)
        img = cv2.resize(img, (max(1, int(width * scale)), max(1, int(height * scale))),
                         interpolation=cv2.INTER_AREA)

    # Ink as white on black, so the morphology below grows text rather than paper.
    ink = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 25, 15)

    def lines_along(kernel_shape: tuple[int, int]) -> int:
        """Smear the ink along one axis and count the line-shaped blobs that result."""
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_shape)
        smeared = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel)
        count = 0
        contours, _ = cv2.findContours(smeared, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            _x, _y, w, h = cv2.boundingRect(c)
            if w * h < 200:                       # speckle, a comma, scanner dirt
                continue
            if kernel_shape[0] > kernel_shape[1]:
                if w >= h * _LINE_RATIO:
                    count += 1
            elif h >= w * _LINE_RATIO:
                count += 1
        return count

    horizontal = lines_along((25, 1))
    vertical = lines_along((1, 25))
    total = horizontal + vertical
    if total < _MIN_LINES:
        return "unclear", horizontal, vertical
    if horizontal / total >= _MAJORITY:
        return "horizontal", horizontal, vertical
    if vertical / total >= _MAJORITY:
        return "vertical", horizontal, vertical
    return "unclear", horizontal, vertical


def tidy_line_starts(image_path: str | Path) -> float:
    """How much tidier the line STARTS are than the line ENDS. Above 1 means left-aligned.

    A page of left-aligned text has line starts on a common margin and ragged ends, so the
    spread of left edges is smaller than the spread of right edges. Turn the page upside down
    and the two swap, which makes this the one cheap signal that tells 90° from 270° -- the
    blob geometry of the two is identical, and OCR reads both almost equally well (the trap
    ``extraction/orient.py`` documents: 2304 characters against 2211 on the same form).

    Returns the ratio, or 0.0 where there is too little text to say. Measured on both
    candidates and compared: a single page's ratio means nothing on its own, since a
    right-aligned Urdu page inverts it. The comparison is what carries the answer.
    """
    import cv2
    import numpy as np

    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    height, width = img.shape[:2]
    if max(height, width) > 1400:
        scale = 1400 / max(height, width)
        img = cv2.resize(img, (max(1, int(width * scale)), max(1, int(height * scale))),
                         interpolation=cv2.INTER_AREA)
    ink = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 25, 15)
    smeared = cv2.morphologyEx(ink, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (35, 1)))
    contours, _ = cv2.findContours(smeared, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    lefts, rights = [], []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < h * _LINE_RATIO or w * h < 400 or h < 6:
            continue
        lefts.append(x)
        rights.append(x + w)
    if len(lefts) < 5:
        return 0.0
    # Half a percent of the page width: below that, edges are aligned as far as anyone can
    # see, and dividing by the remaining noise would turn a tidy page into an infinity.
    floor = max(1.0, img.shape[1] * 0.005)
    spread_of_starts = max(float(np.std(lefts)), floor)
    spread_of_ends = max(float(np.std(rights)), floor)
    return spread_of_ends / spread_of_starts


def decide(
    image_path: str | Path,
    judge: Callable[[Path], bool | None] | None = None,
) -> Orientation:
    """The rotation this page needs, in degrees anticlockwise: 0, 90 or 270.

    ``judge`` answers one question about one image -- is the text upright (True), upside down
    (False), or is it unsure (None). It is called at most twice, and only for a page whose
    text runs up the side. Without it, or where it cannot separate the two candidates, the
    page is left exactly as it was scanned and the manifest says why: an officer can read a
    sideways page by tilting their head and knows to, where a page turned the wrong way looks
    authoritative and is upside down.
    """
    from PIL import Image

    path = Path(image_path)
    axis, horizontal, vertical = text_axis(path)
    if axis == "horizontal":
        return Orientation(0, "text already runs across the page", horizontal, vertical)
    if axis == "unclear":
        return Orientation(0, "not enough text to tell which way the page is turned",
                           horizontal, vertical)
    if judge is None:
        return Orientation(0, "text runs up the page, but nothing was available to say which "
                              "way round it goes", horizontal, vertical)

    import tempfile
    with Image.open(path) as img, tempfile.TemporaryDirectory(prefix="upright-") as tmp:
        verdicts: dict[int, bool | None] = {}
        tidy: dict[int, float] = {}
        for angle in (90, 270):
            turned = Path(tmp) / f"{path.stem}-{angle}.png"
            img.rotate(angle, expand=True).save(turned)
            tidy[angle] = tidy_line_starts(turned)
            try:
                verdicts[angle] = judge(turned)
            except Exception:                      # noqa: BLE001 - a judge that fails is one
                verdicts[angle] = None             # that cannot vote, not a crash

    upright_ones = [a for a, v in verdicts.items() if v is True]
    # Recorded either way: the ratio that used to decide this, kept so a reader can see what
    # the layout thought and how often it agreed.
    layout = f"line starts {tidy[90]:.2f} at 90°, {tidy[270]:.2f} at 270°"
    if len(upright_ones) != 1:
        state = ("both ways round look upside down" if not upright_ones
                 else "both ways round look right")
        return Orientation(0, f"text runs up the page, but {state} to the reader, so it was "
                              f"left as scanned ({layout})", horizontal, vertical)
    chosen = upright_ones[0]
    return Orientation(chosen, f"text ran up the page; turned {chosen}° anticlockwise, the one "
                               f"way round the page reads upright ({layout})",
                       horizontal, vertical)


def apply(image_path: str | Path, rotation: int, keep_original_as: str | Path) -> None:
    """Write the upright page over ``image_path``, keeping what was rendered beside it.

    The original is moved, not copied, and then the rotated image takes its name -- so every
    path already recorded in the manifest still points at the page the engine reads, and the
    scan as it arrived is one file away for anybody who asks.
    """
    from PIL import Image

    path, original = Path(image_path), Path(keep_original_as)
    if rotation == 0:
        return
    path.replace(original)
    with Image.open(original) as img:
        img.rotate(rotation, expand=True).save(path)


def vision_judge(
    endpoint: str | None = None,
    model: str | None = None,
) -> Callable[[Path], bool | None]:
    """The vision model, asked the one question it answers well and cheaply here.

    Not asked what the document is, or what it says -- stage 3 does that, and a reader that
    could be wrong about the page should not also choose which way up it goes. It is asked
    whether the printed text reads the right way up, in one word, at about two seconds a call.
    An answer it does not give in that form counts as "unsure", which leaves the page alone.
    """
    import base64
    import json
    import urllib.request

    from extraction.client import DEFAULT_ENDPOINT, DEFAULT_MODEL

    url = endpoint or DEFAULT_ENDPOINT
    name = model or DEFAULT_MODEL

    def judge(path: Path) -> bool | None:
        image = base64.b64encode(Path(path).read_bytes()).decode()
        body = {
            "model": name, "max_tokens": 8, "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{image}"}},
                {"type": "text", "text":
                    "Look at the printed text on this page. Answer with one word only: "
                    "UPRIGHT if the text reads normally, or UPSIDEDOWN if the page is "
                    "rotated 180 degrees."},
            ]}],
        }
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            answer = json.load(response)["choices"][0]["message"]["content"].strip().upper()
        if "UPSIDE" in answer:
            return False
        if "UPRIGHT" in answer:
            return True
        return None

    return judge
