"""Pipeline stage 3: identify document types and boundaries across the bundle. BRAIN §5, §4.1.

A real case file is "a scanned bundle in no reliable order, at CamScanner quality: skewed,
variable lighting, mixed English and Urdu, handwritten annotations, rubber stamps over text,
photographs of photographs. **Page order does not imply document boundaries** -- one document
may span pages 19-20 while pages 24-36 are twelve separate certificates."

Two halves, deliberately separated:

*   :func:`identify_page` is a **reading** task -- "what is printed at the top of this page" --
    and runs on the vision model against a closed enum of document types.
*   :func:`assemble_documents` is a **rule** -- how identified pages group into documents --
    and is plain Python with no model in it.

The case type is then derived from the assembled documents by ``rules.case_type``, which is
also pure code, because §4.1 rule 1 makes it a lookup rather than a judgement: the PSA form
present in the file is decisive.

Why the enum is closed
----------------------
An open ``document_type`` string invites a plausible near-miss -- "Form D1", "Death Cert" --
that no downstream lookup matches. The checklist would then report a document missing that is
sitting in the file, and the case would go back to a department that did nothing wrong. A page
that fits nothing is ``OTHER`` and reaches a human; the model never coins a type.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from rules.caserecord import Document

from .client import DEFAULT_ENDPOINT, DEFAULT_MODEL, Extraction, extract_page
from .schemas import DOCUMENT_TYPE_GLOSS

#: Below this, a page identification is not acted on: it is surfaced for human confirmation.
#: BRAIN §5.3 puts the silent-accept floor at 0.80, and a misidentified document is not a
#: field-level error -- it removes a whole requirement from the checklist or invents one.
IDENTIFY_ACCEPT_THRESHOLD = 0.80

#: Replaces the pay-extraction default rather than appending to it. See client.py's
#: instruction_override: prepending five lines about reckonable pay to an identification task
#: made this call confidently wrong.
IDENTIFY_INSTRUCTION = (
    "Your only task is to identify which document this scanned page belongs to.\n"
    "Ignore any monetary figures on the page. Do not extract pay components.\n"
    "Work from the printed heading, the form number, and any official stamp. Quote what you "
    "read as your evidence; do not describe the page.\n"
    "A prescribed form (B-I, B-II, B-III, B-IV, D-I, D-II) is identified by its printed form "
    "number, not by what the page is about.\n"
    "If the page carries no heading and continues the previous document, set "
    "is_first_page_of_document false — but STILL classify it by its content. Pages of one "
    "document are scattered through the bundle, so the page before it is usually unrelated. "
    "A headless continuation of a service order is still POSTING_ORDER, not a letter.\n"
    "Many pages are wholly or partly in URDU. A page you cannot read word for word is still "
    "identifiable from its heading, its stamps and its layout, and answering OTHER because "
    "the body is in Urdu drops a document the case needs. The widow's affidavit in the "
    "September case was headed 'بیان حلفی' over an oath commissioner's stamp and was "
    "answered OTHER, so the case was returned for an affidavit that was in the bundle.\n"
    "If the page fits none of the listed types, answer OTHER. Never invent a type.\n"
    "A CNIC card is CNIC. Put the name printed on it in person_named. Do NOT decide whether "
    "it belongs to the deceased or to the claimant -- you cannot know that from the card.\n"
    "One sheet often carries two or three separate documents -- a death certificate beside "
    "the FRC, several certificates on one sworn page. Put the main one in document_type and "
    "list every other one, by its own printed heading or layout, in other_documents_on_page. "
    "Leave it empty for a page with one document; never list a document the page only "
    "mentions, refers to or asks for.\n"
    "A PHOTOGRAPH of the pensioner or claimant affixed to a page -- pasted, stapled, taped or "
    "printed into a box on a form -- is PHOTOGRAPHS, and belongs in other_documents_on_page "
    "even though it carries no heading of its own. Departments commonly attach it to the "
    "descriptive roll rather than filing it on a sheet of its own, and a photograph on such a "
    "page was reported nowhere at all until 22 Oct 2026.\n"
    "\n"
    "Answer document_type with the TOKEN on the left of these pairs:\n"
    + "\n".join(f"  {k} = {v}" for k, v in DOCUMENT_TYPE_GLOSS.items())
)


@dataclass(frozen=True)
class PageIdentity:
    """One page's identification."""

    page: int
    document_type: str
    confidence: float
    evidence: str
    is_first_page: bool
    signed_by_psa: bool | None = None
    attested: bool | None = None
    printed_form_number: str | None = None
    person_named: str | None = None
    #: Set when a FORM_* claim was rejected because no matching form number was printed.
    downgraded_from: str | None = None
    #: Set when that rejection was followed by a successful re-read of what the page IS.
    reclassified: bool = False
    #: Set when the model's label was replaced by a prescribed form that OCR found printed on the
    #: page, number and title both (``_reclaim_form``). The label it replaced.
    promoted_from: str | None = None
    #: Further separate documents printed on the same sheet (two certificates on one page).
    also_on_page: tuple[str, ...] = ()

    @property
    def needs_human(self) -> bool:
        return self.confidence < IDENTIFY_ACCEPT_THRESHOLD or self.document_type == "OTHER"

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "document_type": self.document_type,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "is_first_page_of_document": self.is_first_page,
            "signed_by_psa": self.signed_by_psa,
            "printed_form_number": self.printed_form_number,
            "person_named": self.person_named,
            "downgraded_from": self.downgraded_from,
            "attested": self.attested,
            "other_documents_on_page": list(self.also_on_page),
            "needs_human": self.needs_human,
        }


def identify_page(
    image: str | Path,
    page: int,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
    timeout_s: int = 300,
    extra_instruction: str | None = None,
) -> PageIdentity:
    """Identify one page. Raises rather than returning something doubtful.

    Cheap relative to field extraction -- the schema is six fields, so this runs over every
    page in the bundle before the expensive per-document extraction narrows to the pages that
    matter.
    """
    ext: Extraction = extract_page(
        image,
        schema_name="PAGE_IDENTITY",
        endpoint=endpoint,
        model=model,
        max_tokens=800,   # six fields; 512 truncated on dense pages (source page 24)
        timeout_s=timeout_s,
        instruction_override=(
            IDENTIFY_INSTRUCTION + "\n\n" + extra_instruction if extra_instruction
            else IDENTIFY_INSTRUCTION
        ),
    )
    d = ext.data
    return PageIdentity(
        page=page,
        document_type=d["document_type"],
        confidence=float(d["document_type_confidence"]),
        evidence=d.get("evidence") or "",
        is_first_page=bool(d.get("is_first_page_of_document")),
        signed_by_psa=d.get("signed_by_psa"),
        attested=d.get("attested"),
        printed_form_number=d.get("printed_form_number"),
        person_named=(d.get("person_named") or None),
        also_on_page=tuple(dict.fromkeys(
            t for t in (d.get("other_documents_on_page") or ())
            if t and t not in ("OTHER", d["document_type"]))),
    )


#: A FORM_* token is only accepted when the page actually prints that form number.
_FORM_NUMBER = {
    "FORM_B_I": ("B-I", "B1"), "FORM_B_II": ("B-II", "B2"),
    "FORM_B_III": ("B-III", "B3"), "FORM_B_IV": ("B-IV", "B4"),
    "FORM_D_I": ("D-I", "D1"), "FORM_D_II": ("D-II", "D2"),
}


#: How the page is cut up for the second look below: overlapping bands, so a heading sitting on
#: a boundary is whole in one of them.
_BANDS = ((0.0, 0.32), (0.26, 0.64), (0.58, 1.0))


def _forms_in_bands(image: str | Path, page: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Form numbers and titles found by reading the page in bands rather than whole.

    PaddleOCR does not always read a whole page. On the S&GAD bundles of 22 Oct 2026 it
    returned 859 characters of a page carrying well over two thousand -- the order number, the
    opening paragraph and the pay table -- and stopped, never reaching the title at the top
    (partly under a sticky note) or the sanction clauses at the foot. The same page read in
    bands gives up "FORM B-I" from the top band and the sanction wording from the bottom.

    That is not a degenerate read, so ``looks_degenerate`` does not catch it, and a claim the
    model had right was denied for want of corroboration that was on the page all along:
    PC-2026-000037 p.3 became OTHER and PC-2026-000034 p.3 became POSTING_ORDER, taking AG-04
    with them. Read only when the whole-page read found NOTHING -- no number and no title -- so
    this costs three OCR calls on the pages that would otherwise be refused, and nothing
    elsewhere. Still OCR corroborating, never the model's own account of itself.

    The bands are ENLARGED before reading. A band is a third of a page, and at the rendered
    188dpi the reader simply does not resolve a heading that small: the top band of
    PC-2026-000037 p.3 came back 651 characters with no form number on two tries running, and
    759 characters WITH "FORM B-I" on two tries at twice the size. The whole-page read is left
    alone -- this only applies to the crops.
    """
    import tempfile
    from PIL import Image
    from .ocr import form_titles_on, forms_printed_on, looks_degenerate, ocr_page
    forms: list[str] = []
    titles: list[str] = []
    try:
        with Image.open(image) as im:
            width, height = im.size
            for top, bottom in _BANDS:
                crop = im.crop((0, int(height * top), width, int(height * bottom)))
                crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
                    crop.save(fh.name)
                    band = fh.name
                try:
                    text = ocr_page(band, page)
                except Exception:                     # noqa: BLE001 -- a band that fails says nothing
                    continue
                if looks_degenerate(text):
                    continue
                forms.extend(forms_printed_on(text))
                titles.extend(form_titles_on(text))
    except Exception:                                 # noqa: BLE001 -- no second look, not a denial
        return (), ()
    return tuple(dict.fromkeys(forms)), tuple(dict.fromkeys(titles))


def _verify_form_claim(
    ident: PageIdentity,
    ocr_forms: tuple[str, ...] | None = None,
    ocr_titles: tuple[str, ...] | None = None,
) -> PageIdentity:
    """Reject a prescribed-form classification that OCR cannot corroborate. BRAIN §4.1 rule 1.

    ``ocr_forms`` is the set of form numbers an INDEPENDENT reader (PaddleOCR, stage 2) found
    printed on the page. Pass ``None`` to skip verification.

    An earlier version of this check asked the vision model itself to quote the printed form
    number, and it failed for the reason such checks always fail: on the real case file the
    model classified an "Entitlement Declaration" as FORM_D_II *and* asserted that "FORM D-II"
    was printed on it. A model that will misclassify a page will also supply the evidence for
    its own misclassification, so its self-report corroborates nothing. Only a second reader
    counts.

    The consequence is larger than one mislabelled page: the PSA form decides the case type,
    so two fabricated forms in one bundle routed a determinable case to manual classification.

    ``ocr_titles`` is the fallback, and it exists because the check was also wrong in the
    other direction. Many departmental forms print no form number -- the family-pension case
    of 9 September carried a genuine Form D-II headed only "FAMILY PENSION FORM (To be
    forwarded ... in the event of death of the pensioner)". OCR found no number, so a CORRECT
    classification was withdrawn and the sanction form dropped out of the bundle, taking three
    checklist lines with it. A form that states its scenario in words has identified itself as
    surely as one that prints a number.

    The ordering is what keeps this safe. A number OCR did find always wins; titles are read
    only when the page prints no form number at all. So a page headed as one form and numbered
    as another is still denied, which is the case this check was built for.
    """
    expected = _FORM_NUMBER.get(ident.document_type)
    if expected is None or ocr_forms is None:
        return ident
    if ident.document_type in ocr_forms:
        return ident
    # A number OCR found for a DIFFERENT form is positive evidence against this claim, and
    # no title may talk it round. Only silence -- no number printed at all -- opens the door
    # to the weaker corroboration below.
    if not ocr_forms and ident.document_type in (ocr_titles or ()):
        return ident
    return PageIdentity(
        page=ident.page,
        document_type="OTHER",
        confidence=ident.confidence,
        evidence=ident.evidence,
        is_first_page=ident.is_first_page,
        signed_by_psa=ident.signed_by_psa,
        attested=ident.attested,
        printed_form_number=ident.printed_form_number,
        downgraded_from=ident.document_type,
        also_on_page=ident.also_on_page,
    )


def _reclassify_after_denial(
    ident: PageIdentity,
    image: str | Path,
    ocr_text: str,
) -> PageIdentity:
    """Ask what the page IS, having established what it is not.

    The re-read is told the denied type and why, and is given the second reader's own
    transcription -- so it is not simply the same question asked twice, which would invite
    the same answer. If it still cannot place the page, the denial stands and the page stays
    OTHER for a human: an unidentified page must never become a document that satisfies a
    requirement.
    """
    denied = ident.downgraded_from or ""
    try:
        again = identify_page(
            image,
            page=ident.page,
            extra_instruction=(
                f"A second reader has checked this page and it is NOT {denied}: no such form "
                f"number is printed on it. Do not answer {denied}. Identify what the page "
                f"actually is from its heading. This is its transcribed text:\n{ocr_text}"
            ),
        )
    except Exception:                                   # noqa: BLE001
        return ident
    if again.document_type in ("OTHER", denied):
        return ident
    # A re-read that names ANOTHER prescribed form must clear the same bar the first claim
    # failed. Accepting it on the model's word alone lets the re-read walk past the very
    # guard it sits behind: on a real case an "APPLICATION FOR PENSION AND/OR GRATUITY" was
    # denied as Form B-I, came back as Form B-III, was accepted -- and the bundle then held
    # two prescribed forms, so §4.1 refused to type the case at all.
    if again.document_type in _FORM_NUMBER:
        from .ocr import form_titles_on, forms_printed_on, looks_degenerate, ocr_page
        corroborating = PageIdentity(
            page=ident.page, document_type=again.document_type, confidence=again.confidence,
            evidence=again.evidence, is_first_page=again.is_first_page,
        )
        # The corroborating read is the OCR reader's, so it must be imported and it must be
        # allowed to fail. Until 12 Oct 2026 ``ocr_page`` was not imported here at all, so every
        # denied form that came back as another form raised NameError and failed the whole run
        # after the vision stage; and an OCR failure is no corroboration either way, so the
        # page keeps what the denial left rather than taking the re-read on the model's word.
        try:
            text = ocr_page(image, ident.page)
        except Exception:                               # noqa: BLE001
            return ident
        # Same rule as verify_with_ocr: loop-garbage is not a second reading, so it may not
        # deny the re-read either -- otherwise the recovery path inherits the fault that made
        # the recovery necessary.
        checked = _verify_form_claim(
            corroborating,
            None if looks_degenerate(text) else forms_printed_on(text),
            None if looks_degenerate(text) else form_titles_on(text),
        )
        if checked.document_type == "OTHER":
            return ident
    return PageIdentity(
        page=ident.page,
        document_type=again.document_type,
        confidence=again.confidence,
        evidence=again.evidence,
        is_first_page=again.is_first_page,
        signed_by_psa=again.signed_by_psa,
        attested=again.attested,
        printed_form_number=again.printed_form_number,
        downgraded_from=denied,
        reclassified=True,
        also_on_page=again.also_on_page,
    )


#: Types read for their pay figures. A page filed as one of these reaches stage 4.
_PAY_DOCUMENT_TYPES = ("LPC", "SALARY_STATEMENT", "PENSION_SLIP")


def _deny_pay_claim_on_a_card(ident: PageIdentity, image: str | Path) -> PageIdentity:
    """Withdraw a pay-document claim where the second reader says the page is an ID card.

    Mirrors ``_verify_form_claim``: the vision model's own evidence for its own claim
    corroborates nothing, so OCR decides. Denied pages become OTHER carrying
    ``downgraded_from``, exactly as a denied form does, and are picked up by the same
    reclassification path rather than being silently dropped.
    """
    from .ocr import looks_like_identity_card, ocr_page

    try:
        text = ocr_page(image, ident.page)
    except Exception:                                    # noqa: BLE001
        return ident                                     # no second reader, no denial
    if not looks_like_identity_card(text):
        return ident
    return PageIdentity(
        page=ident.page,
        document_type="OTHER",
        confidence=ident.confidence,
        evidence=(f"{ident.evidence} -- WITHDRAWN: the second reader finds an identity card "
                  f"on this page and no pay vocabulary at all."),
        is_first_page=ident.is_first_page,
        signed_by_psa=ident.signed_by_psa,
        attested=ident.attested,
        printed_form_number=ident.printed_form_number,
        downgraded_from=ident.document_type,
        also_on_page=ident.also_on_page,
    )


#: Labels a prescribed form has been filed under by mistake, and may be reclaimed from. On the
#: self-pension case of 12 Oct 2026 the department's Form B-I, headed "Annex-B-1", was filed as
#: ANNEX_A at confidence 1.00; nothing re-read it, so the bundle had no prescribed form and the
#: case fell to manual routing. The set is deliberately short: a forwarding letter or a file cover
#: names the forms it encloses, and a pension application quotes their clauses, so a page under
#: those labels is never reclaimed however plainly it mentions a form.
PROMOTABLE_LABELS = frozenset({"ANNEX_A", "OTHER", "AFFIDAVIT", "SUPERANNUATION_ORDER"})


def _reclaim_form(ident: PageIdentity, image: str | Path) -> tuple[PageIdentity, str]:
    """A prescribed form the model filed under another label, reclaimed on OCR's evidence.

    The bar is higher than for confirming a claim. To confirm, one printed form number or one
    title is enough; to overrule the model, the page must print exactly ONE form number AND
    that form's own scenario title (``form_titles_on``): "Annex-B-1" with "RETIREMENT ON
    SUPERANNUATION" is Form B-I, while a descriptive roll that says "Annex-B-1 enclosed" is not,
    and a page quoting two forms (B-III cites B-II) is left for a person. An OCR failure keeps
    the label: no second reading is not evidence against the first. Returns the identity and
    the page's text, which is the form's text when reclaimed.
    """
    from .ocr import (PageText, form_rubric_on, form_titles_on, forms_printed_on,
                      looks_degenerate, ocr_page)
    try:
        text = ocr_page(image, ident.page)
    except Exception:                                   # noqa: BLE001
        return ident, ""
    titles = form_titles_on(text)
    numbers = tuple(dict.fromkeys(forms_printed_on(text)))

    def promoted(name: str) -> tuple[PageIdentity, str]:
        return replace(ident, document_type=name, is_first_page=True,
                       promoted_from=ident.document_type), text.text or ""

    if not numbers and not looks_degenerate(text):
        # OCR read the page but did not transcribe its form number, and the model DID. On the
        # 78-page bundle of 20 Oct 2026 page 17 was the department's Form B-I: the model filed
        # it ANNEX_A at confidence 1.00 while reporting printed_form_number "Annex-B-1", and
        # OCR read the scenario title as Form B-I's but never caught the label in the corner.
        # One printed number was required, so nothing was reclaimed and the PSA sanction form
        # read MISSING against the department.
        #
        # This is NOT the model corroborating itself -- the trap this function's bar exists to
        # avoid. It is the model CONTRADICTING itself: the number it read says Form B-I and the
        # label it chose says ANNEX_A, and the independent reader's title agrees with the
        # number, not the label. Two readings against one, and the weaker of them is the
        # model's own conclusion rather than its transcription.
        #
        # The bar is otherwise untouched: a number OCR did find still decides on its own terms,
        # the title must still agree, and a page whose reader looped supplies nothing.
        claimed = forms_printed_on(PageText(page=ident.page,
                                            text=ident.printed_form_number or "",
                                            model=text.model))
        if len(claimed) == 1 and claimed[0] in titles:
            return promoted(claimed[0])

        # The form's own printed RUBRIC, where no number is printed at all.
        #
        # These forms do not always print a number anywhere a reader catches, and the model
        # does not always transcribe one. Swept over 503 real pages on 20 Oct 2026, eleven
        # genuine Form B-I pages across nine bundles were filed as SUPERANNUATION_ORDER or
        # ANNEX_A for exactly that reason -- which is honest of the model, because Form B-I IS
        # the retirement notification; it is the PRESCRIBED one, and the checklist asks for
        # the prescribed one.
        #
        # So the second phrase comes off the page instead: "(To be issued by the Appointing
        # authority 90 days before superannuation...)", the instruction printed on the blank
        # form. It says the page is a prescribed form without saying which, and on those 503
        # pages it appeared on 17, every one a genuine form and nothing else -- not on the
        # forwarding letter or the departmental checklist that print a form NUMBER while
        # merely listing it as an enclosure.
        #
        # Which form it is still has to be said by something. OCR's title says it where there
        # is exactly one; where the title is damaged past recognition -- one real page prints
        # "ORDERS OF SUPERANUATION RETIREMENT", the words the other way round -- the model's
        # own transcribed number says it, and the rubric is what makes that safe to take.
        # Two titles means two forms on one sheet and is left for a person.
        #
        # A model number that names a DIFFERENT form blocks this. The two readers disagree
        # about which form the page is, and this function overrules a label only where they
        # agree -- a disagreement is the case the module leaves for a person. Nothing real is
        # lost to it: every page the sweep recovered either had an agreeing number or had
        # none at all.
        contradicted = bool(claimed) and not set(claimed) & set(titles) if titles else False
        if form_rubric_on(text) and not contradicted:
            distinct = tuple(dict.fromkeys(titles))
            if len(distinct) == 1:
                return promoted(distinct[0])
            if not distinct and len(claimed) == 1:
                return promoted(claimed[0])
    if len(numbers) != 1 or numbers[0] not in titles:
        return ident, text.text or ""
    return promoted(numbers[0])


def _verify_proforma_claim(ident: PageIdentity, image: str | Path) -> PageIdentity:
    """Keep a proforma claim where the form's heading was read, or its sections.

    A denied page is asked again, told what it is not, exactly as a denied form is; an OCR
    failure keeps the claim, as ``_deny_pay_claim_on_a_card`` does, because no second reading
    is not evidence against the first."""
    from .ocr import ocr_page
    try:
        text = ocr_page(image, ident.page)
    except Exception:                                   # noqa: BLE001
        return ident
    flat = re.sub(r"\s+", " ", text.text or "").lower()
    # The heading is enough, whoever read it (office's decision, 23 Oct 2026). Three ways in:
    # the printed title in the OCR, the sections that only this form prints, or the title in
    # the identifier's own transcription of the page.
    #
    # The third is new and is a deliberate exception to this function's bar. "Performa for
    # Qualifying Service for Pension" is not a conclusion about a page, it is a line of text
    # copied off it, and no other paper in a pension bundle prints it. Weighed against what
    # the denial costs: PC-2026-000042 p.8 carries that heading, OCR read 555 characters of
    # the body and then looped on "OI - OZ - 2O26" without reaching the title or section 2, so
    # neither of the other two ways could fire -- and a denial here does not merely doubt the
    # claim, it files the page as OTHER and drops the document out of the bundle, which is how
    # AG-26 came to be reported missing against a department that had filed it.
    claimed = re.sub(r"\s+", " ", f"{ident.evidence or ''} {ident.printed_form_number or ''}").lower()
    if re.search(PROFORMA_TITLE, flat) or re.search(PROFORMA_SECTIONS, flat) \
            or re.search(PROFORMA_TITLE, claimed):
        return ident
    denied = PageIdentity(
        page=ident.page, document_type="OTHER", confidence=ident.confidence,
        evidence=ident.evidence, is_first_page=ident.is_first_page,
        signed_by_psa=ident.signed_by_psa, attested=ident.attested,
        printed_form_number=ident.printed_form_number,
        downgraded_from=ident.document_type, also_on_page=ident.also_on_page,
    )
    return _reclassify_after_denial(denied, image, (text.text or "")[:1200])


#: Pages second-read at once in stage "verify". Was a plain sequential loop until 19 Oct 2026,
#: which measured 1.00x parallelism -- 89.4s of model work in 89.5s of wall clock -- while the
#: OCR server reported one request running and nothing queued. Each page here is independent,
#: so this is the same shape of work stage 3 already fans out.
VERIFY_CONCURRENCY = max(1, int(os.environ.get("PENSION_VERIFY_CONCURRENCY") or 4))


def verify_with_ocr(
    identities: Sequence[PageIdentity],
    image_for: Callable[[int], str | Path],
) -> tuple[PageIdentity, ...]:
    """Second-read every page claimed to be a prescribed form, and drop the ones OCR denies.

    Only form claims are re-read -- typically three or four pages out of forty-odd -- because
    those are the ones that select a pension formula. Everything else is a field-level risk
    the checklist and the flag battery already cover.
    """
    from pipeline import timing

    from .ocr import form_titles_on, forms_printed_on, looks_degenerate, ocr_page

    def one(ident: PageIdentity) -> tuple[PageIdentity, int | None, str | None]:
        """Second-read one page. Returns the identity, and the form text to keep for it.

        Independent of every other page: it reads one image and returns one identity. That is
        what makes the pool below safe -- no shared state is touched here, and the caller
        reassembles both the order and the form_text dictionary on its own thread.
        """
        # A pay-document claim gets the same second reader a form claim gets. The model
        # answered LPC, at confidence 1.00, for the REVERSE of a CNIC -- and justified it
        # with the card's own serial and number. An LPC is read for its pay figures, so a
        # CNIC filed as one puts an identity card into the determination path.
        if ident.document_type in _PAY_DOCUMENT_TYPES:
            return _deny_pay_claim_on_a_card(ident, image_for(ident.page)), None, None
        # The proforma decides a checklist line on its own (AG-10, decision S3), so the vision
        # model's word is not enough for it either: OCR must find its printed title. It prints
        # no form number, so it is not one of the prescribed forms below and never takes part
        # in deciding the case type.
        if ident.document_type == "QUALIFYING_SERVICE_PROFORMA":
            return _verify_proforma_claim(ident, image_for(ident.page)), None, None
        if ident.document_type not in _FORM_NUMBER:
            if ident.document_type in PROMOTABLE_LABELS:
                promoted, page_text = _reclaim_form(ident, image_for(ident.page))
                if promoted.promoted_from:
                    return promoted, promoted.page, page_text[:8000]
                return promoted, None, None
            return ident, None, None
        text = ocr_page(image_for(ident.page), ident.page)
        # A reader that fell into a repetition loop has not read the page, and its silence
        # about a form number is not evidence that none is printed. On a real 78-page bundle
        # three pages the vision model called FORM_B_I at 0.95 came back 97% repeated -- "In
        # terms of full pay", 319 times, cut off mid-word -- and because that text printed no
        # form number the claim was denied and the PSA sanction form was reported MISSING
        # against the department (20 Oct 2026). looks_degenerate() was written for exactly
        # this and was applied only to the card and attestation paths.
        #
        # None, not (): the parameter already means "no second reading, do not verify", which
        # is the truth here. An empty tuple means "a reader looked and found no number", and
        # that is what withdrew a correct classification.
        unreadable = looks_degenerate(text)
        ocr_forms = None if unreadable else forms_printed_on(text)
        ocr_titles = None if unreadable else form_titles_on(text)
        # The whole page read, and said nothing either way. Before refusing a claim on that
        # silence, look again in bands: PaddleOCR stops partway down some pages, and the form
        # number it did not reach is still printed on them (see _forms_in_bands).
        if not unreadable and not ocr_forms and not ocr_titles:
            ocr_forms, ocr_titles = _forms_in_bands(image_for(ident.page), ident.page)
        verified = _verify_form_claim(ident, ocr_forms, ocr_titles)
        # A denial says what the page is NOT. Filing it as OTHER then drops it from the
        # bundle, so a correct rejection still costs the office a document: on the real
        # cases an "Application for Grant of Family Pension", an "Entitlement Declaration"
        # and a "Superannuation Notification" all vanished this way, and three checklist
        # lines reported missing papers that were in the file. Ask again, told plainly what
        # the page is not, and keep whatever comes back.
        if verified.document_type == "OTHER" and verified.downgraded_from:
            verified = _reclassify_after_denial(
                verified, image_for(ident.page), text.text[:1200],
            )
        # Keep what the second reader saw. The prescribed form states which family member is
        # claiming -- "IN RESPECT OF MST. GHULAM ZAINAB WIDOW OF ..." -- and that is what
        # separates the seven Form D-II checklist columns from one another.
        # 8,000 rather than 2,000: a Form B-I runs to ~3,600 characters of OCR and its
        # retirement date, average pay and qualifying service all sat past the old cut.
        if unreadable:
            # Stage 6 quotes the form's own wording from this; 319 repeats of one line is not
            # wording. Better it have nothing than confident noise.
            return verified, None, None
        return verified, verified.page, text.text[:8000]

    idents = list(identities)
    if VERIFY_CONCURRENCY <= 1 or len(idents) < 2:
        results = [one(i) for i in idents]
    else:
        with ThreadPoolExecutor(max_workers=VERIFY_CONCURRENCY) as pool:
            # Submitted in order and read back by index, so the bundle's page order survives
            # the pool: a tuple returned in completion order would reorder the documents.
            results = [f.result() for f in [
                pool.submit(timing.carry(one, stage="verify", page=i.page), i) for i in idents
            ]]

    out = [r[0] for r in results]
    form_text: dict[int, str] = {page: text for _, page, text in results if page is not None}
    verify_with_ocr.form_text = form_text          # noqa: B010 - read by stage_verify_forms
    return tuple(out)


#: Printed headings that name a checklist document beyond doubt, as the office's own sheet
#: names them. Deliberately narrow: each pattern is a TITLE a department prints at the head
#: of a page, not a phrase that could occur in the body of another document. "Death
#: certificate" is absent for that reason -- Form D-II's own text says "death certificate is
#: attached" -- and so is anything a covering letter routinely mentions.
NO_INCOME_TITLE = (
    r"non?[\s-]*(?:regular\s+)?source\s+of\s+income"
    r"|no[\s-]*(?:regular\s+)?income\s+certificate"
    r"|certificate\s+of\s+no\s+(?:regular\s+)?(?:source\s+of\s+)?income"
    r"|no[\s-]*(?:regular|independent)\s+(?:source\s+of\s+)?income"
    r"|ذریعہ\s*آمدن|ذریعہ\s*معاش|آمدنی\s*کا\s*کوئی"
)
#: The same certificate proved by its content: a sworn or signed statement that the claimant
#: has no regular or independent source of income, wherever it is printed.
NO_INCOME_STATEMENT = (
    r"(?:has|have|having|possess(?:es)?)\s+no\s+(?:other\s+)?(?:regular\s+|independent\s+|permanent\s+)*"
    r"(?:source\s+of\s+)?(?:income|livelihood|earning)"
    r"|(?:not|no)\s+(?:having\s+)?any\s+(?:regular\s+|independent\s+)*source\s+of\s+(?:income|livelihood)"
    r"|کوئی\s*ذریعہ\s*آمدن\s*نہیں|ذریعہ\s*آمدن\s*نہ"
)

#: The proforma for qualifying service (scope change C2, 12 Oct 2026), by its printed title. The
#: word before "for qualifying" is required: Form B-I's clause 3 reads "Total length of
#: qualifying service for pension", and a title test on that phrase alone would confirm a B-I
#: page as the proforma. The office's own sample prints "PERFORMA" and "SEVICE", and OCR read
#: that heading back as "PERFORMANCE ... SERVICE" (12 Oct 2026), so the form's name and the word
#: "service" are both matched loosely.
#: "service" is allowed to arrive in two pieces. PaddleOCR read the S&GAD proforma's title as
#: "PROPOSED PERFORMA FOR QUALIFYING SERV ICE FOR PENSION" -- one word, split by a space -- and
#: `se\w{0,6}\s+for` could not span it, so three bundles of 22 Oct 2026 had a proforma the model
#: had already recognised denied under them (PC-2026-000033 p.4, -38 p.4, -39 p.10). The words
#: either side, "qualifying" before and "for pension" after, are what keep this from matching a
#: form that merely MENTIONS qualifying service -- Form B-I's clause 3 does, and still does not
#: match.
PROFORMA_TITLE = r"(?:pro|per|pre)\s*form\w{0,5}\s+for\s+qualifying\s+se\w{0,3}\s*\w{0,4}\s+for\s+pension"

#: The proforma identified by its STRUCTURE rather than its heading, because the heading is
#: often not on the page at all. The copy filed with the case of 21 Oct 2026 (run b3b0e3f35d7c,
#: p.1) begins "[For Use in the Administrative/Attached Department/Office]" -- the title line is
#: above the top of the scan -- and the vision model, told to look for the heading, answered
#: OTHER at confidence 1.00. The page then counted as no document at all, so the checklist line
#: it exists to satisfy would have read MISSING against a department that had filed it.
#:
#: Its numbered sections are what make it this form and nothing else. "PARTICULARS OF EMPLOYEE"
#: is the anchor -- section 1 of this proforma and of nothing else in a pension bundle -- and ONE
#: more of its sections within reach confirms it.
#:
#: All three were required at first, in order. That was too brittle for a reader that is not
#: deterministic: re-running the same page the same day, OCR skipped section 2 entirely and went
#: "1. PARTICULARS OF EMPLOYEE ... 29-04-41Y ... 3. PAY FIXATION", so the match failed and the
#: page stayed OTHER on a second run after the first had been rescued. Which sections survive a
#: read varies; that one of them does is reliable.
#:
#: The gap is bounded so headings scattered across a composite sheet cannot combine. Checked
#: against the real bundle: it matches both OCR readings of the proforma and none of the service
#: statement, Form B-I, the LPC, the pension application or the departmental checklist.
PROFORMA_SECTIONS = (
    r"particulars\s+of\s+employ\w{0,3}"
    r".{0,1500}?(?:service\s+record\s+summ\w{0,4}|pay\s+fixation|pension\s+contribut\w{0,3})"
)

#: The department's own pension sanction, by words only it prints: the operative clause that
#: grants the pension, or a signature block naming the signer as the sanctioning authority.
#:
#: "The sanction accorded, as above" was in this pattern and is not, because a PPO refers to it
#: in those words, and a PPO the identifier happened to call OTHER would then have been taken
#: for the sanction itself. The clause that GRANTS a pension, and a designation followed by
#: "Pension Sanctioning", are the two things only the sanction carries. Checked 22 Oct 2026
#: against the five S&GAD sanctions and against a PPO, an Annex-A, two forwarding letters, a
#: superannuation order, an NDC and a pension application: five matches, no false ones.
SANCTION_ORDER_TITLE = (
    r"sanction\s+for\s+(?:the\s+)?grant\s+of\s+pension"
    r"|(?:secretary|officer|authority)[^.]{0,60}pension\s+sanction"
)

DOCUMENT_TITLES: tuple[tuple[str, str], ...] = (
    (PROFORMA_TITLE, "QUALIFYING_SERVICE_PROFORMA"),
    (SANCTION_ORDER_TITLE, "PENSION_SANCTION_ORDER"),
    (PROFORMA_SECTIONS, "QUALIFYING_SERVICE_PROFORMA"),
    (r"list\s+of\s+family\s+members|descriptive\s+roll", "ANNEX_A"),
    (r"sole\s+(?:family|widow)\s+certificate|sole\s+and\s+lawful\s+widow"
     r"|lawful\s+widow\s+certificate", "SOLE_WIDOW_CERTIFICATE"),
    (r"entitlement\s+of\s+arrears", "ARREARS_ENTITLEMENT_CERTIFICATE"),
    # Matched by meaning (office rule, 30 Sep 2026): departments title this certificate a dozen
    # ways -- "Non Source of Income", "No Source of Income", "No Income Certificate",
    # "Certificate of No Regular Income" -- and in Urdu; all are the same paper.
    (NO_INCOME_TITLE, "NO_REGULAR_INCOME_CERTIFICATE"),
    (r"non[\s-]*re[\s-]*marriage\s+certificate|no[\s-]*marriage\s+certificate",
     "NON_REMARRIAGE_CERTIFICATE"),
    (r"reason\s+for\s+late\s+submission", "LATE_SUBMISSION_REASON"),
    (r"no\s+demand\s+certificate", "NDC"),
)

#: Labels that say only "this page is a page". A page carrying one of these is the only kind
#: this reconciliation reads, and even then its label is kept -- see ``titles_on_page``.
GENERIC_LABELS = frozenset({"OTHER", "AFFIDAVIT"})

#: Statements a SPECIFICALLY labelled page may also prove, by the words printed on it. The
#: office's Annexure-A (descriptive roll and undertaking) carries the pensioner's option for
#: commutation as its own printed section -- "I hereby opt full pension without commutation /
#: commutation @ ..." -- and the identifier rightly files the page as ANNEX_A; the checklist's
#: "Option for commutation" line then read MISSING while the option sat on page 6 (Agriculture,
#: 29 Sep 2026). The option is the pensioner's own declaration, not a mention of one, so an
#: Annexure-A page printing it satisfies both lines it belongs to.
#: What may be taken from the model's `other_documents_on_page` and made a document of.
#:
#: Deliberately one entry. Everything else this module adds to a bundle is corroborated by a
#: second reader -- a title OCR found, a statement OCR matched -- because the model's own
#: account of a page cannot check itself. A photograph is the case where no second reader is
#: possible: OCR reads characters, and a photograph has none. So the model's word is all there
#: is, and the alternative was what the S&GAD bundles of 22 Oct 2026 did -- report AG-03
#: MISSING against departments that had attached the photograph to the descriptive roll
#: (PC-2026-000033 p.8, PC-2026-000034 p.5).
#:
#: It stays one entry for that reason. Any type that OCR CAN corroborate belongs above, where
#: it is corroborated.
ALSO_ON_PAGE_TRUSTED = frozenset({"PHOTOGRAPHS"})

STATEMENTS_ON_LABELLED_PAGES: dict[str, tuple[tuple[str, str], ...]] = {
    # A sworn sheet filed as one certificate often states, in its body, that the claimant has no
    # source of income: that statement is the no-income certificate (office rule, 30 Sep 2026).
    **{label: ((NO_INCOME_TITLE + "|" + NO_INCOME_STATEMENT, "NO_REGULAR_INCOME_CERTIFICATE"),)
       for label in ("SOLE_WIDOW_CERTIFICATE", "ARREARS_ENTITLEMENT_CERTIFICATE", "NON_REMARRIAGE_CERTIFICATE",
                     "LATE_SUBMISSION_REASON")},
    "ANNEX_A": (
        (r"opt\w*\s+(?:for\s+)?(?:full\s+)?pension\s+(?:with|without)\s+commutation"
         r"|option\s+for\s+commutation|commutation\s+@|hereby\s+opt\w*\s.{0,60}commutation",
         "COMMUTATION_OPTION"),
    ),
}


def statements_on_page(label: str, text: str) -> tuple[str, ...]:
    """Checklist documents a page labelled ``label`` also proves by a statement printed on it."""
    flat = re.sub(r"\s+", " ", (text or "")).lower()
    return tuple(sorted({doc for pattern, doc in STATEMENTS_ON_LABELLED_PAGES.get(label, ()) if re.search(pattern, flat)}))


def titles_on_page(text: str) -> tuple[str, ...]:
    """Checklist documents whose printed TITLE appears in a page's OCR text.

    Every one that does. Departments put two and three certificates on one sheet -- page 12
    of case 71b639daac14 is one sworn page headed sole-widow certificate, no-regular-income
    certificate and entitlement-of-arrears certificate -- and this used to answer nothing for
    such a page, so all three read MISSING and the officer was asked to approve papers that
    were in the bundle. Only ``OTHER`` and ``AFFIDAVIT`` pages are read this way (see
    ``pipeline.run.documents_named_by_their_own_heading``), which is what keeps a form that
    merely mentions a certificate from counting as one.
    """
    flat = re.sub(r"\s+", " ", (text or "")).lower()
    found = {doc for pattern, doc in DOCUMENT_TITLES if re.search(pattern, flat)}
    if re.search(NO_INCOME_STATEMENT, flat):
        found.add("NO_REGULAR_INCOME_CERTIFICATE")
    return tuple(sorted(found))


def title_found(doc_type: str, text: str) -> str | None:
    """The heading a page actually prints for a checklist document, for "found as ..." (30 Sep 2026)."""
    patterns = [p for p, d in DOCUMENT_TITLES if d == doc_type]
    if doc_type == "NO_REGULAR_INCOME_CERTIFICATE":
        patterns.append(NO_INCOME_STATEMENT)
    for line in (text or "").splitlines():
        flat = re.sub(r"\s+", " ", line).strip()
        if flat and any(re.search(p, flat.lower()) for p in patterns):
            return flat[:90]
    return None


def assemble_documents(identities: Iterable[PageIdentity]) -> tuple[Document, ...]:
    """Group identified pages into documents. Deterministic; no model.

    A new document starts when the type changes, **or** when a page declares itself a first
    page. That second condition is what handles pp.24-36 of the golden case: twelve separate
    NDC certificates, all the same type, back to back. Grouping on type alone would merge
    them into one thirteen-page document and lose the count; grouping on the declared heading
    keeps them apart.

    ``OTHER`` pages are dropped rather than assembled -- an unidentified page must not become
    a document that satisfies a checklist requirement. They remain in the ``PageIdentity``
    list for a human to look at.
    """
    docs: list[Document] = []
    run_type: str | None = None
    run_pages: list[int] = []
    run_signed: bool | None = None
    run_attested: bool | None = None
    run_person: str | None = None

    def flush() -> None:
        nonlocal run_type, run_pages, run_signed, run_attested, run_person
        if run_type is not None and run_pages:
            docs.append(
                Document(
                    type=run_type,
                    pages=tuple(run_pages),
                    present=True,
                    signatory_is_psa=run_signed,
                    attested=run_attested,
                    person_named=run_person,
                )
            )
        run_type, run_pages, run_signed, run_attested, run_person = None, [], None, None, None

    for ident in identities:
        if ident.document_type == "OTHER":
            flush()
            continue
        starts_new = ident.document_type != run_type or (ident.is_first_page and run_pages)
        if starts_new:
            flush()
            run_type = ident.document_type
        run_pages.append(ident.page)
        # A signature or attestation anywhere in a document applies to the document.
        if ident.signed_by_psa is not None:
            run_signed = bool(run_signed) or ident.signed_by_psa
        if ident.attested is not None:
            run_attested = bool(run_attested) or ident.attested
        if run_person is None and ident.person_named:
            run_person = ident.person_named

    flush()
    return tuple(docs)


def low_confidence_pages(
    identities: Iterable[PageIdentity],
    threshold: float = IDENTIFY_ACCEPT_THRESHOLD,
) -> tuple[PageIdentity, ...]:
    """Pages a human must confirm before the checklist is trusted.

    Surfaced separately from the assembled documents because the consequence is different in
    kind: a low-confidence *field* is one wrong value, a low-confidence *document* silently
    adds or removes an entire checklist requirement.
    """
    return tuple(
        i for i in identities if i.confidence < threshold or i.document_type == "OTHER"
    )
