"""The case record the checklist and the check battery run over. BRAIN §6.

A narrowed, typed view of the §6 extraction schema -- the parts the deterministic layer
consumes. Extraction produces the full JSON; this is what the rules side reads.

One modelling decision matters more than the rest. A fact is not stored as a single value
with a list of pages; it is stored as **one ``Assertion`` per document that states it**:

    Assertion("personnel_no", "90000857", Source(page=2,  document="FILE_COVER"))
    Assertion("personnel_no", "90000853", Source(page=6,  document="LPC"))

A schema that stored ``personnel_no = "90000853", sources=[2, 6, 9, ...]`` has already
resolved the contradiction, silently and without recording that it happened -- and F-1, the
golden case's personnel-number mismatch, becomes unfindable. Keeping each document's own
statement is what lets §8.3's precedence hierarchy decide which one wins, and lets the flag
name both the asserting and the contradicting pages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .emoluments import Emoluments
from .money import money


@dataclass(frozen=True)
class Source:
    """Where a statement was read. ``document`` is a type from the §6 ``documents`` list."""

    page: int
    document: str

    def __str__(self) -> str:
        return f"p.{self.page} ({self.document})"


@dataclass(frozen=True)
class Assertion:
    """One document's statement of one fact. Never pre-reconciled -- see the module docstring.

    ``person`` and ``role`` are set where the fact belongs to somebody in particular. A CNIC
    is meaningless without them: one page of a sanction form quotes the deceased's number and
    the claimant's, and a bank form adds two witnesses. Comparing the numbers alone would
    call a perfectly ordinary page a contradiction.
    """

    field: str
    value: str
    source: Source
    person: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class FamilyMember:
    """A family member as recorded by one document.

    Held separately per source (Annex-A vs NADRA FRC) precisely so the two can disagree.
    On the golden case Annex-A calls Usman Waqar an unmarried daughter; the FRC records a
    married son.
    """

    name: str
    relation: str
    marital_status: str
    source: Source
    birth_year: int | None = None


@dataclass(frozen=True)
class PayLine:
    """One pay line as one document prints it: which document, which page, the component the
    label was classified as, the label as printed and the amount as printed. The LPC's lines are
    the source of truth for pay components (business decision H2, 7 Oct 2026); another
    document's differing amount for the same component is a finding, never a sum."""

    document: str
    page: int | None
    component: str
    printed_label: str
    amount: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))


@dataclass(frozen=True)
class Recovery:
    """A recoverable amount found in the record.

    ``declared_on_sanction`` is the whole point: a recovery on the LPC that the sanction
    form denies is ``RULE-UNDECLARED``, HIGH, every time (BRAIN §16 item 8).
    """

    amount: Decimal
    reason: str
    source: Source
    declared_on_sanction: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))


@dataclass(frozen=True)
class TimelineEvent:
    """A dated event, with the statutory deadline that applies to it where one does."""

    event: str
    date: date
    source: Source | None = None
    #: Days allowed between the preceding trigger and this event, per BRAIN §4.
    sla_days: int | None = None
    sla_from: str | None = None
    #: What the reader must know about how this interval was measured, where the exact
    #: statutory event is not itself dated in the record. Appended verbatim to the finding
    #: so a flag never implies a precision the documents do not carry.
    sla_note: str | None = None


@dataclass(frozen=True)
class Alias:
    """A name variant. ``resolved_by`` names the document that reconciles it, if any."""

    value: str
    kind: str
    resolved_by: str | None = None
    #: Where this spelling was read, so the finding can open the page that carries it.
    source: Source | None = None


@dataclass(frozen=True)
class Document:
    """One identified document in the bundle.

    ``present`` and ``defects`` are separate on purpose: BRAIN §7.3 requires MISSING and
    DEFECTIVE to be distinguished sharply, because they generate different letters -- one
    asks for a document, the other for a correction.
    """

    type: str
    pages: tuple[int, ...] = ()
    present: bool = True
    signatory: str | None = None
    signatory_is_psa: bool | None = None
    attested: bool | None = None
    countersigned_by: tuple[str, ...] = ()
    defects: tuple[str, ...] = ()
    #: For a document belonging to one person (a CNIC card, a photograph page), the name
    #: printed on it. The role -- deceased or claimant -- is assigned from this by
    #: rules.case_type.assign_cnic_roles, never read off the document itself.
    person_named: str | None = None

    @property
    def page_ref(self) -> str:
        if not self.pages:
            return "not located"
        if len(self.pages) == 1:
            return f"p.{self.pages[0]}"
        return f"pp.{self.pages[0]}-{self.pages[-1]}"


@dataclass(frozen=True)
class PsaSignature:
    """The sanctioning authority's signature block on one prescribed form (pipeline.signatory).

    ``specimen`` is the register entry it answers to (rules.specimens), or None with the reason
    in ``specimen_status``: "department not on file", "post not on file", "not in force on ...".
    """

    document: str
    page: int | None
    signature_present: bool = False
    stamp_present: bool = False
    signer_name: str | None = None
    designation: str | None = None
    department: str | None = None
    stamp_text: str | None = None
    #: The stamp as OCR read it off the cut-out signature; preferred to ``stamp_text`` where
    #: present, because the vision model misreads a small stamp on a full page.
    stamp_ocr: str | None = None
    date_signed: date | None = None
    date_signed_raw: str | None = None
    signature_image: str | None = None
    specimen: str | None = None
    specimen_status: str = ""


@dataclass(frozen=True)
class CaseRecord:
    """Everything the deterministic layer needs about one case."""

    case_ref: str
    case_type: str
    assertions: tuple[Assertion, ...] = ()
    documents: tuple[Document, ...] = ()
    annex_a_family: tuple[FamilyMember, ...] = ()
    frc_family: tuple[FamilyMember, ...] = ()
    recoveries: tuple[Recovery, ...] = ()
    #: Every pay line stage 4 read, by document -- see rules.flags.check_pay_lines_against_lpc.
    pay_lines: tuple[PayLine, ...] = ()
    #: The dates the prescribed form states, ``(field, date, page, document)``: date_of_birth,
    #: date_first_entry, date_of_death on Form D-I. Checked against each other by
    #: rules.flags.check_form_d_i_dates (decision H3): an impossible set is a hard stop.
    form_dates: tuple[tuple[str, date, int | None, str], ...] = ()
    timeline: tuple[TimelineEvent, ...] = ()
    aliases: tuple[Alias, ...] = ()
    emoluments: Emoluments | None = None
    #: The qualifying service the department states on the form, in whole years.
    stated_qualifying_service_years: int | None = None
    #: The form page that figure was read from, so the RULE-CAP finding can open it.
    stated_qualifying_service_source: Source | None = None
    #: Commutation percentage opted on Annex-A, where applicable.
    commutation_pct_opted: Decimal | None = None
    #: Set when a succession certificate appears in the bundle (BRAIN §9.8 scope warning).
    succession_certificate: Source | None = None

    # -- addressing, for notifications (BRAIN §12.2) -----------------------------------------
    #: When the entitlement arose -- the servant died or retired. Item 19 counts three years
    #: from here; ``submitted_date`` is where it counts to.
    entitlement_date: date | None = None
    submitted_date: date | None = None
    #: The AG office checklist column this case belongs to, where it is known. Some checks
    #: only make sense for one family of cases: a deceased/claimant pair exists in a family
    #: pension and not in a self pension, where the pensioner is the applicant.
    case_variant: str | None = None
    #: Basic Pay Scale, where it has been established. Gazetted status turns on it, and that
    #: decides which service record the office requires -- see rules.checklist.
    pay_scale_bps: int | None = None
    diary_no: str | None = None
    #: Why the deceased/claimant roles could not be confirmed from the record, if they could
    #: not, and whether the extraction's own labelling had to be corrected. Both surface as a
    #: finding: a role taken on a model's say-so must not pass silently into a letter.
    party_roles_note: str | None = None
    party_roles_corrected: bool = False
    forwarding_department: str | None = None
    #: The department's name in Urdu. Carried as data rather than transliterated: an
    #: automatic transliteration of an arbitrary department name will eventually be wrong,
    #: and this text is read by a bereaved family.
    forwarding_department_ur: str | None = None
    claimant_name: str | None = None
    claimant_contact: str | None = None
    #: Determination-critical documents no reader could get through. Surfaced as a finding,
    #: never left as an absence -- see rules.flags.check_unreadable_documents.
    unreadable: tuple[tuple[int, str, str], ...] = ()
    #: Pages whose two reads disagreed, ``(document, page, what differed)``. Nothing from such a
    #: page was used (extraction.client.extract_page_confirmed blanks it); the finding puts the
    #: page in front of the officer -- see rules.flags.check_disputed_reads (decision H1).
    disputed_reads: tuple[tuple[str, int | None, tuple[str, ...]], ...] = ()
    #: Dates on the case written with a two-digit year, ``(document, page, as written, field)``.
    #: The readers refuse them rather than complete the century (audit L1, 7 Oct 2026); a
    #: finding asks a person to -- see rules.flags.check_ambiguous_dates.
    ambiguous_dates: tuple[tuple[str | None, int | None, str, str], ...] = ()
    #: Fields of the prescribed form the sanctioning authority left empty, named as the form
    #: names them. A blank that stops a determination is a defect in the department's
    #: paperwork and belongs in the shortcoming letter, not only in the determination panel.
    prescribed_form_blanks: tuple[str, ...] = ()
    #: The date this record was built, taken from the run's own recorded start and never from
    #: the clock (SOP §8.5). A document valid at submission and expired by the time the
    #: officer reads the case is a different finding from one expired on arrival.
    processed_on: date | None = None
    #: Why the self-pension engine refused, where it did and the refusal names a contradiction
    #: in the papers rather than a value nobody supplied. Surfaced as a HIGH finding so it
    #: reaches the shortcoming letter, not only the determination panel.
    self_pension_defect: str | None = None
    #: The case type the department declared at intake (29 Sep 2026), where it did, and what
    #: the papers themselves read as. ``case_type`` above is the one the rules ran on -- the
    #: declaration where there is one -- so the two are kept here for the check that
    #: compares them; a disagreement is a finding, never a silent reclassification.
    declared_case_type: str | None = None            # the office type (a sheet column) the DDO declared
    declared_pipeline_types: tuple[str, ...] = ()    # the path(s) that declaration may be; empty = any
    detected_case_variant: str | None = None         # the claimant column the papers read (Form D-II)
    detected_case_type: str | None = None
    detected_case_type_confidence: float = 0.0
    detected_case_type_evidence: str = ""
    detected_case_type_alternatives: tuple[str, ...] = ()
    #: Who signed each prescribed form as sanctioning authority, and the specimen on file for
    #: that post (BRAIN §2: "the signature authority on a form is itself a checklist item").
    psa_signatures: tuple[PsaSignature, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    # -- lookups the checks are written against ---------------------------------------------
    def stated(self, field_name: str) -> tuple[Assertion, ...]:
        """Every document's statement of one field, in extraction order."""
        return tuple(a for a in self.assertions if a.field == field_name)

    def distinct_values(self, field_name: str) -> dict[str, tuple[Source, ...]]:
        """Distinct values of a field, mapped to the sources asserting each.

        More than one key means the documents disagree. Insertion-ordered, so the first key
        is the first value encountered -- stable output for the same input.
        """
        out: dict[str, list[Source]] = {}
        for a in self.stated(field_name):
            out.setdefault(a.value, []).append(a.source)
        return {v: tuple(s) for v, s in out.items()}

    def document(self, doc_type: str) -> Document | None:
        for d in self.documents:
            if d.type == doc_type:
                return d
        return None

    def has_document(self, *doc_types: str) -> bool:
        present = {d.type for d in self.documents if d.present}
        return any(t in present for t in doc_types)

    def event(self, name: str) -> TimelineEvent | None:
        for e in self.timeline:
            if e.event == name:
                return e
        return None
