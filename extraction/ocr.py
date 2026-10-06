"""Stage 2: first-pass OCR. BUILD §5 stage 2, on PaddleOCR-VL.

Why this stage exists in this pipeline, having initially been skipped
--------------------------------------------------------------------
Stage 3 asks the vision model which document a page is. On the real case file it answered
FORM_D_I for an "Application for Grant of Family Pension" and FORM_D_II for an "Entitlement
Declaration" -- neither of which prints a form number at all. Adding a ``printed_form_number``
field so the claim could be checked did not help: the model simply asserted that "FORM D-II"
was printed, because a model that will misclassify a page will also supply the evidence for
its own misclassification. **A model cannot be its own witness.**

PaddleOCR is a different model reading the same pixels, so its text is independent testimony.
Stage 3's classification is then checked against that text by ``rules``-side code with no model
in it: if OCR cannot find "FORM D-II" anywhere on the page, the page is not Form D-II,
whatever stage 3 says.

This matters more than a mislabelled page normally would. BRAIN §4.1 rule 1 makes the PSA form
decisive for the case type, so a fabricated form does not produce a wrong field -- it selects a
different pension formula, or, as it did here, puts two conflicting forms in one bundle and
routes a perfectly determinable case to manual classification.
"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

#: PENSION_OCR_URL points a deployment at its own GPU box (docs/DEPLOYMENT.md F4).
OCR_ENDPOINT = os.environ.get("PENSION_OCR_URL") or "http://192.168.1.1:8012/v1/chat/completions"
OCR_MODEL = "paddleocr-vl-1.6"

OCR_INSTRUCTION = (
    "Transcribe all printed text on this page, in reading order. "
    "Output the text only, with no commentary and no description of the layout."
)


class OcrError(RuntimeError):
    """The OCR service returned nothing usable. Never swallowed."""


def normalise(text: str) -> str:
    """Upper-case, punctuation-stripped, single-spaced -- for form-number matching.

    A function as well as a property so that a caller holding CACHED page text can apply
    exactly the same normalisation without a second read of the page. Two copies of this
    expression would be two answers to "is this Form B-I".
    """
    return re.sub(r"[^A-Z0-9 ]+", " ", (text or "").upper())


@dataclass(frozen=True)
class PageText:
    page: int
    text: str
    model: str
    #: Why the reader stopped. "length" means it hit the token budget and the rest of the
    #: page was never transcribed -- so this text says nothing about what is further down it.
    #: The difference between "not on the page" and "not reached" decides whether the office
    #: may accuse a department of filing an unattested copy.
    finish_reason: str = "stop"

    @property
    def complete(self) -> bool:
        """Did the reader get to the end of the page?"""
        return self.finish_reason != "length"

    @property
    def normalised(self) -> str:
        return normalise(self.text)


def ocr_page(
    image: str | Path,
    page: int,
    *,
    endpoint: str = OCR_ENDPOINT,
    model: str = OCR_MODEL,
    max_tokens: int = 2048,
    timeout_s: int = 300,
) -> PageText:
    """Read a page with PaddleOCR. Free-form text, deliberately -- no schema, no judgement.

    This stage is asked for characters, not conclusions. Every interpretive decision belongs
    to code that can be audited.
    """
    b64 = base64.b64encode(Path(image).read_bytes()).decode()
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": OCR_INSTRUCTION},
            ],
        }],
    }
    req = urllib.request.Request(
        endpoint, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    try:
        raw = urllib.request.urlopen(req, timeout=timeout_s).read()
    except urllib.error.HTTPError as exc:
        raise OcrError(
            f"page {page}: OCR returned HTTP {exc.code}: "
            f"{exc.read()[:300].decode(errors='replace')}"
        ) from exc
    except OSError as exc:
        raise OcrError(
            f"page {page}: cannot reach the OCR service at {endpoint} ({exc}). "
            "Check: systemctl status paddleocr-vl"
        ) from exc

    body = json.loads(raw)
    choice = body["choices"][0]
    text = _strip_layout_tokens(choice["message"]["content"] or "")
    if not text.strip():
        raise OcrError(f"page {page}: OCR returned empty text")
    return PageText(page=page, text=text, model=model,
                    finish_reason=choice.get("finish_reason") or "stop")


#: PaddleOCR-VL emits bounding-box tokens like ``<|LOC_160|>`` on some inputs and not on
#: others -- the digitised verification copy comes back as clean prose, while a rendered
#: departmental scan comes back with a quad of them after every line.
_LAYOUT_TOKEN = re.compile(r"<\|[A-Z]+_\d+\|>|<\|[a-z_]+\|>")


def _strip_layout_tokens(text: str) -> str:
    """Remove layout metadata from the transcription.

    These tokens are coordinates, not characters on the page, and they are full of digits.
    ``recoveries_in`` looks for a money figure near a recovery word; a line reading
    "...is recoverable" followed by ``<|LOC_877|>`` puts an invented 877 within reach of
    that pattern. This stage was asked for the text, so it returns the text.
    """
    return re.sub(r"[ \t]+\n", "\n", _LAYOUT_TOKEN.sub("", text or ""))


#: Printed form numbers, as they appear after normalisation. Ordered longest-first so that
#: "FORM D II" is not matched by the "FORM D I" pattern.
#: Roman OR arabic. The FD's own blank-forms compendium prints "Form B-1" and "Form D-1"
#: with the digit one, while departmental copies print "FORM B-I" and "FORM D-I" in Roman.
#: Matching only Roman meant OCR could not find the number on a genuine form, so
#: ``verify_with_ocr`` withdrew the classification and sent a valid case to manual review --
#: the exact false negative this check exists to prevent, inverted.
#: What the departments call these forms. The FD compendium prints "Form B-1"; a department
#: heads the very same sanction on the same proforma "Annex-B-1", and the forwarding letters
#: list "Annex-D-I (Form)". Matching only the word FORM denied a genuine Form B-I on a real
#: case and threw the sanction form out of the bundle -- the one document that decides the
#: case type.
#: PROFORMA and its common local spelling PERFORMA are added because the Government
#: Printing Press sanction in the divorced-daughter bundle is headed "Proforma D-II",
#: not "Form D-II". OCR therefore corroborated no form number, _verify_form_claim
#: withdrew a CORRECT FORM_D_II classification, and the prescribed form dropped out of
#: the bundle entirely -- leaving the case with no form, no case type and no
#: determination, reported to the officer as "the bundle has no prescribed form".
_FORM_WORD = r"(?:FORM|PROFORMA|PERFORMA|ANNEX|ANNEXURE|ANNEXE)"

_FORM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("FORM_B_III", re.compile(rf"\b{_FORM_WORD}\s*B\s*(?:III|3)\b")),
    ("FORM_B_IV", re.compile(rf"\b{_FORM_WORD}\s*B\s*(?:IV|4)\b")),
    ("FORM_B_II", re.compile(rf"\b{_FORM_WORD}\s*B\s*(?:II|2)\b")),
    ("FORM_B_I", re.compile(rf"\b{_FORM_WORD}\s*B\s*(?:I|1)\b")),
    ("FORM_D_II", re.compile(rf"\b{_FORM_WORD}\s*D\s*(?:II|2)\b")),
    ("FORM_D_I", re.compile(rf"\b{_FORM_WORD}\s*D\s*(?:I|1)\b")),
)


#: What an identity card carries and a pay document does not. The reverse of a CNIC prints a
#: card serial, a 13-digit number and the standard lost-card sentence, and nothing else.
_CNIC_MARKERS = (
    re.compile(r"\b\d{5}-\d{7}-\d\b"),                      # the number, as printed
    re.compile(r"گمشدہ|لیٹر\s*بکس|قومی\s*شناختی|شناختی\s*کارڈ"),  # lost-card / national ID
    re.compile(r"\bRegistrar\s+General\b", re.I),
    re.compile(r"\bNational\s+Identity\s+Card\b", re.I),
)

#: What a pay document says and an identity card never does.
_PAY_VOCABULARY = re.compile(
    r"last\s+pay\s+certificate|substantive\s+pay|officiating\s+pay|scale\s+of\s+pay"
    r"|\bG\.?P\.?F\b|deduction|gross\s+pay|basic\s+pay|pay\s+slip|salary",
    re.I,
)


def looks_like_identity_card(page_text: PageText) -> bool:
    """Is this page an identity card rather than a pay document, per OCR?

    Exists because the vision model claimed LPC, at confidence 1.00, for the REVERSE of a
    CNIC in the divorced-daughter bundle -- and supplied its own evidence for the claim:
    "headed with 'D23M2Q' and contains 'نامہ نمبر: 00001-0000110-4', which is consistent with
    the format of a Last Pay Certificate". D23M2Q is the card serial. A model that will
    misclassify a page will also justify the misclassification, so the second reader decides.

    Deliberately requires the ABSENCE of pay vocabulary as well as the presence of card
    markers. A real Last Pay Certificate quotes the servant's CNIC too, and denying those
    would drop the pay document this pipeline most needs.
    """
    text = page_text.text or ""
    if _PAY_VOCABULARY.search(text):
        return False
    return sum(1 for pattern in _CNIC_MARKERS if pattern.search(text)) >= 2


def forms_printed_on(page_text: PageText) -> tuple[str, ...]:
    """Which prescribed-form numbers are actually printed on the page, per OCR.

    Longest-first matching, and the match is removed before shorter patterns are tried, so a
    page printing "FORM D-II" does not also report "FORM D-I". Getting that ordering wrong
    would hand back exactly the false positive this module exists to eliminate.
    """
    text = page_text.normalised
    found: list[str] = []
    for name, pattern in _FORM_PATTERNS:
        if pattern.search(text):
            found.append(name)
            text = pattern.sub(" ", text)
    return tuple(found)


#: A recoverable amount as printed on a Last Pay Certificate. Requires BOTH a money figure and
#: a word that makes it a recovery -- "recoverable", "recovery", "demand", "ROP" -- because a
#: bare figure on an LPC is far more likely to be pay than a demand.
#: A rupee figure as these offices print it: Western grouping (126,355) or the lakh grouping
#: the Punjab pay offices use (1,76,336). The lakh form is tried first; tried second, the
#: Western pattern reads "1,76,336" as 76,336.
_AMOUNT = r"\d{1,3}(?:,\d{2})+,\d{3}(?:\.\d{1,2})?|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{4,9}"
_RECOVERY = re.compile(
    rf"(?:recover\w*|demand|\bROP\b)[^0-9\n]{{0,60}}?({_AMOUNT})"
    rf"|({_AMOUNT})[^0-9\n]{{0,40}}?(?:is\s+)?recover\w*"
    # "ROP OF PAY & ALLOWANCES WEF 18.02.2026 TO 28.02.2026 @ RS.1,76,336/- MAY PLEASE BE
    # RECOVERED IN PENSION" (abdd): the period's dates sit between the word and the figure,
    # so the figure is the one written as rupees, and OCR garbles "recovered" ("REDADE").
    rf"|\bROP\b[^\n]{{0,120}}?\bRS\.?\s*({_AMOUNT})",
    re.I,
)


def recoveries_in(page_text: PageText) -> list[dict]:
    """Recoverable amounts printed on the page, per OCR. BRAIN §8.4 (Money), flag F-3.

    Read by OCR rather than by the vision model, for the same reason the pay scale is: this is
    a printed figure beside a printed word, which is character recognition and not judgement.
    On the real case the vision model could not read LPC p.29 at all -- three attempts returned
    21 pay-row labels with zero amounts -- and the recovery it carries is the flag BRAIN §13.8
    calls "the one that costs money".

    Ground truth for that page reads: "...to 28.02.2026 (10 days) amounting to Rs. 126,355 is
    recoverable."
    """
    out: list[dict] = []
    seen: set[int] = set()
    for m in _RECOVERY.finditer(page_text.text or ""):
        raw = m.group(1) or m.group(2) or m.group(3)
        if not raw:
            continue
        from decimal import ROUND_HALF_UP, Decimal
        amount = int(Decimal(raw.replace(",", "")).quantize(Decimal("1"),
                                                            rounding=ROUND_HALF_UP))
        # A recovery of a few rupees, or one larger than any plausible pay run, is a misread.
        if not 100 <= amount <= 10_000_000 or amount in seen:
            continue
        seen.add(amount)
        start = max(0, m.start() - 70)
        out.append({
            "amount": amount,
            "reason": re.sub(r"\s+", " ", (page_text.text or "")[start:m.end() + 40]).strip(),
            "page": page_text.page,
        })
    return out

#: The scenario each prescribed form states in its own title, from the FD blank-forms
#: compendium. A departmental copy often prints the descriptive title and NO form number at
#: all: the family-pension case of 9 September carried a genuine Form D-II headed only
#: "FAMILY PENSION FORM (To be forwarded ... in the event of death of the pensioner)".
#:
#: Every phrase here must DISCRIMINATE. "FAMILY PENSION FORM" heads both D-I and D-II, so it
#: proves nothing; what separates them is the event -- in-service death against death of the
#: pensioner. A phrase that also appears on a neighbouring form would confirm a false claim,
#: which is the one thing this check exists to stop.
_FORM_TITLES: dict[str, tuple[str, ...]] = {
    "FORM_B_I": ("RETIREMENT ON SUPERANNUATION",),
    "FORM_B_II": ("FOR ANTICIPATORY PENSION",),
    "FORM_B_III": ("FINAL PENSION PAYMENT",),
    "FORM_B_IV": ("INVALIDATION RETIREMENT", "COMPULSORY INVALIDATION"),
    "FORM_D_I": ("IN SERVICE DEATH", "DEATH OF A GOVERNMENT SERVANT WHILE IN SERVICE"),
    "FORM_D_II": ("DEATH OF THE PENSIONER", "DEATH OF PENSIONER"),
}


def form_titles_on(page_text: PageText) -> tuple[str, ...]:
    """Which prescribed forms the page identifies by its printed TITLE, per OCR.

    Corroboration of last resort, for a form that does not print its number. It is weaker
    evidence than the number and is used only where the number is absent -- never to overrule
    a number that is present and says something else.
    """
    text = re.sub(r"\s+", " ", page_text.normalised)
    return tuple(
        name for name, phrases in _FORM_TITLES.items()
        if any(phrase in text for phrase in phrases)
    )


# -- Attestation, repetition loops and banded reading -------------------------------------
# Ported from the Pension-AG deployment (25 Sep 2026), where they were written and tested.

#: Words that name an office rather than a person. An attestation is an officer certifying a
#: copy, and what makes it an attestation rather than a signature is that the signer states
#: the office they hold. These are the designations the AG office's bundles actually carry.
_DESIGNATIONS = (
    "HEADMISTRESS", "HEADMASTER", "HEAD MISTRESS", "HEAD MASTER", "PRINCIPAL",
    "DDO", "DRAWING AND DISBURSING OFFICER", "DISTRICT OFFICER", "DEPUTY DIRECTOR",
    "ASSISTANT DIRECTOR", "DIRECTOR", "SECRETARY", "DEPUTY SECRETARY", "SECTION OFFICER",
    "SUPERINTENDENT", "TEHSILDAR", "NAIB TEHSILDAR", "MAGISTRATE", "OATH COMMISSIONER",
    "NOTARY", "GAZETTED OFFICER", "ACCOUNTS OFFICER", "AUDIT OFFICER", "TREASURY OFFICER",
    "SENIOR HEADMISTRESS", "SENIOR HEADMASTER", "CHAIRMAN", "SECRETARY UNION COUNCIL",
    # Police and revenue officers attest cards too (ecb2: "Dy. Superintendent of Police").
    "SUPERINTENDENT OF POLICE", "DSP", "ASSISTANT COMMISSIONER", "DEPUTY COMMISSIONER",
    "INSPECTOR", "CHIEF", "OFFICER INCHARGE",
)

#: The word itself, where the attesting officer writes it. Urdu تصدیق شدہ is included
#: because a Union Council or oath commissioner's stamp is frequently Urdu-only.
_ATTEST_WORDS = ("ATTESTED", "ATTESTATION", "CERTIFIED TRUE COPY", "TRUE COPY",
                 "تصدیق شدہ", "تصدیق")


def _designations_in(text: str) -> list[str]:
    """Designations present in ``text``, tolerating what OCR does to them.

    An exact match is not available here. A real scan returned the stamp as "HEADSTRESS
    GOVT GIRLS HIGH SCHOOL" -- the reader dropped two characters out of the middle of the
    word, which is ordinary for a rubber stamp on a photocopy of a photocopy. Requiring the
    word to be spelt correctly would throw away a perfectly legible attestation.

    So each designation is compared as a whole against equal-length windows of the page,
    and a close match counts. The threshold is tight enough that ACCOUNTS OFFICER and AUDIT
    OFFICER stay distinct, which matters because the name goes into the letter the office
    sends back.
    """
    words = text.split()
    found: list[str] = []
    for role in _DESIGNATIONS:
        parts = role.split()
        n = len(parts)
        if role in text:
            found.append(role)
            continue
        for i in range(len(words) - n + 1):
            window = " ".join(words[i:i + n])
            if SequenceMatcher(None, role, window).ratio() >= 0.86:
                found.append(role)
                break
    return found


def attestation_marks_on(page_text: PageText) -> tuple[str, ...]:
    """Evidence of a THIRD-PARTY attestation on this page, per OCR. SOP §5.

    The second reader for ``PageIdentity.attested``. The vision model's own answer cannot
    corroborate itself -- the same attested CNIC read True in one run and False in the next,
    because the field asked whether there was "a stamp or signature" and a CNIC card prints
    the holder's own signature.

    What this looks for is the thing that distinguishes an attestation from a signature: a
    stated OFFICE. An officer attesting a copy writes their designation under the signature,
    because the certification is worth nothing without it. A holder signing their own card
    does not.

    Returns the marks found, so a caller can show an officer what the evidence was rather
    than asserting a verdict. Empty means OCR saw no attestation, which is evidence of
    absence only as far as OCR goes -- a handwritten designation may not survive the scan.
    """
    if looks_degenerate(page_text):
        return ()
    text = re.sub(r"\s+", " ", page_text.normalised.upper())
    found: list[str] = []
    for word in _ATTEST_WORDS:
        if word.upper() in text and word.upper() not in found:
            found.append(word.upper())
    for role in _designations_in(text):
        if role not in found:
            found.append(role)
    return tuple(found)

def looks_degenerate(page_text: PageText) -> bool:
    """Has the OCR model fallen into a repetition loop? Then its text is not evidence.

    Observed on a real CNIC page: the reader spent its whole 2048-token budget emitting
    "HEADMISTRESS GOVERNMENT OF INDIA" over and over. Nothing on the page says India. The
    words were manufactured by the loop, not read -- and one of them is a designation, so a
    check looking for an attesting officer found one that was never printed.

    That is the danger of degenerate output: it is not noise, it is confident noise, and it
    lands in exactly the vocabulary a keyword check is watching for. A page that reads like
    this must be treated as UNREAD, never as evidence of what is or is not on it.
    """
    words = page_text.normalised.upper().split()
    if len(words) < 40:
        return False
    # A page of real text repeats function words, not content words. Below about a sixth of
    # the tokens being distinct, the reader is looping rather than reading.
    if len(set(words)) / len(words) < 0.16:
        return True
    # A four-word phrase covering half the page is a loop even where the vocabulary is wider.
    grams: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - 3):
        g = tuple(words[i:i + 4])
        grams[g] = grams.get(g, 0) + 1
    return bool(grams) and max(grams.values()) * 4 > len(words) * 0.5


#: Fraction of each band that overlaps the next. A stamp straddling the cut would otherwise
#: be halved into two unreadable pieces; a tenth of the page is comfortably more than the
#: height of a designation stamp.
_BAND_OVERLAP = 0.10


def ocr_card_page(image: str | Path, page: int, **kw: Any) -> PageText:
    """A CNIC page, read as columns where the two faces sit side by side.

    Whole, the ecb2 card came back with its number as "34104.2267392-1" and the attesting
    stamp missing; its left half alone printed "Identity Number 00001-0000113-1". A page no
    wider than it is tall is read whole, as before.
    """
    from PIL import Image

    src = Path(image)
    with Image.open(src) as im:
        width, height = im.size
        if width <= height:
            return ocr_page(src, page, **kw)
        pieces, truncated = [], False
        for box in ((0, 0, width // 2, height), (width // 2, 0, width, height)):
            with tempfile.NamedTemporaryFile(suffix=src.suffix or ".png", delete=False) as fh:
                tmp = Path(fh.name)
            try:
                im.crop(box).save(tmp)
                part = ocr_page(tmp, page, **kw)
            except OcrError:
                truncated = True
                continue
            finally:
                tmp.unlink(missing_ok=True)
            truncated = truncated or not part.complete
            if not looks_degenerate(part):
                pieces.append(part.text)
    if not pieces:
        raise OcrError(f"page {page}: neither half of the card produced usable text")
    return PageText(page=page, text="\n".join(pieces), model=OCR_MODEL,
                    finish_reason="length" if truncated else "stop")


def ocr_page_banded(
    image: str | Path,
    page: int,
    *,
    bands: int = 2,
    max_tokens: int = 2048,
    **kw: Any,
) -> PageText:
    """Read a page in horizontal bands, so the FOOT of it is always reached.

    ``ocr_page`` sends the whole page and takes what comes back. On a dense scan -- a CNIC
    with Urdu on both halves, a service-book spread -- the reader exhausts its budget partway
    down and stops, and the response says so with ``finish_reason="length"``. Everything below
    that point is simply never transcribed.

    That is fatal for one question in particular. An attestation is written at the FOOT of
    the copy it certifies: the officer signs under the document and states their office. It
    is the last thing on the page and therefore the first thing lost. Two real CNIC pages
    both stopped midway down the card, and both in fact carried a Headmistress's stamp below
    the cut -- so the page read as unattested when it was nothing of the kind.

    Splitting the page gives each band its own budget, and the band carrying the foot starts
    at the foot. The bands overlap so a stamp across a cut survives in one piece.

    The result reads as one page. ``finish_reason`` is "length" if ANY band ran out, because
    the guarantee the caller needs is that the whole page was transcribed, not most of it.
    """
    from PIL import Image

    src = Path(image)
    with Image.open(src) as im:
        width, height = im.size
        step = height / bands
        margin = int(height * _BAND_OVERLAP)
        pieces: list[str] = []
        truncated = False
        for i in range(bands):
            top = max(0, int(i * step) - margin)
            bottom = min(height, int((i + 1) * step) + margin)
            crop = im.crop((0, top, width, bottom))
            with tempfile.NamedTemporaryFile(suffix=src.suffix or ".png", delete=False) as fh:
                tmp = Path(fh.name)
            try:
                crop.save(tmp)
                part = ocr_page(tmp, page, max_tokens=max_tokens, **kw)
            except OcrError:
                # One unreadable band must not lose the others. The page is marked
                # incomplete, which is the honest description of what happened.
                truncated = True
                continue
            finally:
                tmp.unlink(missing_ok=True)
            truncated = truncated or not part.complete
            if not looks_degenerate(part):
                pieces.append(part.text)

    if not pieces:
        raise OcrError(f"page {page}: no band produced usable text")
    return PageText(
        page=page,
        text="\n".join(pieces),
        model=OCR_MODEL,
        finish_reason="length" if truncated else "stop",
    )


@dataclass(frozen=True)
class Attestation:
    """What an independent reader found of a third-party certification on one page."""

    marks: tuple[str, ...]
    #: Did the reader get through the FOOT of the page -- the band an attestation is written
    #: in? Where it did not, ``marks`` being empty is not evidence that the page carries
    #: none, and the office must not accuse a department on it.
    #:
    #: Deliberately not "was the whole page transcribed". A CNIC's upper half is a dense
    #: bilingual card that routinely exhausts the reader, and on these scans a whole-page
    #: test was False every time -- which would have left the check able to CONFIRM an
    #: attestation and never able to deny one. What the question actually needs is whether
    #: we read the place an attestation is signed.
    read_the_foot: bool


def attestation_on(image: str | Path, page: int, **kw: Any) -> Attestation:
    """Look for a third-party attestation on this page, in the place one is written.

    Two things separate this from running the keyword check over the whole page.

    The page is read in BANDS, so the foot is always reached. An attestation is the last
    thing written on a document and therefore the first thing a reader that runs out of
    budget loses.

    And only the FOOT band's designations count. This is the distinction a whole-page scan
    cannot draw: a Last Pay Certificate is headed "OFFICE OF THE SENIOR HEADMISTRESS, GOVT.
    GIRLS ELEMENTARY SCHOOL", and that is a letterhead naming the office that ISSUED the
    document -- not an officer certifying a copy of somebody else's. Counting it would mark
    every departmental letter as attested and make the check worthless. An officer attesting
    a copy signs beneath it.

    The word ATTESTED is taken wherever it appears, because nobody prints it in a letterhead.
    """
    bands: list[PageText] = []
    src = Path(image)
    from PIL import Image

    with Image.open(src) as im:
        width, height = im.size
        # A page wider than it is tall is, in these bundles, a CNIC copy with both faces side
        # by side (ecb2: 2060 x 764). Its attestation is stamped across the card, not under a
        # letter, and read whole the stamp was lost; read as two columns, both halves printed
        # "Dy. Superintendent of Police". Such a page has no letterhead to confuse with an
        # attesting officer, so a designation counts wherever it is.
        landscape = width > height
        step = (width if landscape else height) / 2
        margin = int((width if landscape else height) * _BAND_OVERLAP)
        foot_read = False
        for i in range(2):
            top = max(0, int(i * step) - margin)
            bottom = min(width if landscape else height, int((i + 1) * step) + margin)
            box = (top, 0, bottom, height) if landscape else (0, top, width, bottom)
            with tempfile.NamedTemporaryFile(suffix=src.suffix or ".png", delete=False) as fh:
                tmp = Path(fh.name)
            try:
                im.crop(box).save(tmp)
                part = ocr_page(tmp, page, **kw)
            except OcrError:
                bands.append(PageText(page=page, text="", model=OCR_MODEL))
                continue
            finally:
                tmp.unlink(missing_ok=True)
            if looks_degenerate(part):
                # Confident noise. Treat the band as unread rather than as evidence.
                part = PageText(page=page, text="", model=OCR_MODEL, finish_reason="length")
            if i == len(range(2)) - 1:
                foot_read = part.complete and (not landscape or bands[0].complete)
            bands.append(part)

    marks: list[str] = []
    for band in bands:                       # the word, anywhere on the page
        text = re.sub(r"\s+", " ", band.normalised.upper())
        for word in _ATTEST_WORDS:
            if word.upper() in text and word.upper() not in marks:
                marks.append(word.upper())
    signed = bands if landscape else bands[-1:]
    foot = " ".join(re.sub(r"\s+", " ", b.normalised.upper()) for b in signed)
    for role in _designations_in(foot):      # the office, only where one is signed
        if role not in marks:
            marks.append(role)
    return Attestation(tuple(marks), foot_read)
