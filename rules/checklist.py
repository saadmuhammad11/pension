"""The checklist engine. BRAIN §7, codified from the FD checklist of annexures.

Four statuses, and the distinction between two of them decides which letter a department
gets: ``MISSING`` asks for a document, ``DEFECTIVE`` asks for a correction (§7.3). Collapsing
them into "not ok" would send the wrong letter and cost another round trip on a file that has
already been in a queue for 75 days.

Two behaviours are easy to get wrong and are enforced here:

*   **A complete checklist does not mean a clean case.** The golden case is 16/16 complete and
    still returns for correction on three data defects. Completeness and correctness are
    reported as separate dimensions and neither implies the other (§7.3, BRAIN §16 item 6).

*   **A missing NDC is never a blocker.** Rule 5.4 Note 1 is explicit, and treating an absent
    No Demand Certificate as a missing document would return cases that are properly
    complete. It resolves to ``NOT_APPLICABLE`` with the rule cited, not to ``MISSING``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Callable

from .caserecord import CaseRecord

PRESENT = "PRESENT"
MISSING = "MISSING"
DEFECTIVE = "DEFECTIVE"
NOT_APPLICABLE = "NOT_APPLICABLE"
#: Office rule of 30 Sep 2026: lines the office never requires (AG-19, AG-23, AG-24 in every
#: case type; AG-16 for an unmarried daughter / son), joined on 12 Oct 2026 by AG-09 (the AG
#: service statement) and AG-12 (the autonomous-body payslip) in every case type (user, S16).
#: Absent -> NOT_REQUIRED; present -> FOUND_NOT_REQUIRED, cited. Neither is ever a deficiency,
#: and neither counts as missing.
NOT_REQUIRED = "NOT_REQUIRED"
FOUND_NOT_REQUIRED = "FOUND_NOT_REQUIRED"

#: The lines not required in any case type, and those not required in particular columns.
NOT_REQUIRED_ANYWHERE = frozenset({"AG-09", "AG-10", "AG-12", "AG-19", "AG-23", "AG-24"})
NOT_REQUIRED_FOR: dict[str, frozenset[str]] = {
    # Unmarried daughter / son: there is no widow, so there is no sole-widow certificate to ask for.
    "AG-16": frozenset({"UNMARRIED_CHILD"}),
}

#: Why a line is not required, in the words the checklist shows.
NOT_REQUIRED_WHY: dict[str, str] = {
    "AG-16": "not required for an unmarried daughter / son (office rule)",
}


def not_required(item_id: str, variant: str | None) -> bool:
    """Whether the office requires this line at all for this column (30 Sep 2026)."""
    return item_id in NOT_REQUIRED_ANYWHERE or (variant is not None and variant in NOT_REQUIRED_FOR.get(item_id, ()))

COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class Requirement:
    """One checklist line: what is required, and what would satisfy or defeat it."""

    id: str
    requirement: str
    #: Any one of these document types present satisfies the requirement.
    satisfied_by: tuple[str, ...]
    #: Universal-requirement id from §7.1, where this line derives from one.
    derives_from: str | None = None
    #: Returns a reason when the requirement does not apply to this case, else None.
    not_applicable_when: Callable[[CaseRecord], str | None] | None = None
    #: Returns a defect description when the document is present but deficient, else None.
    defective_when: Callable[[CaseRecord], str | None] | None = None
    #: When absent, resolve to NOT_APPLICABLE with this reason rather than MISSING.
    absence_excused_by: str | None = None
    #: Case variants this line applies to. Empty means "every variant of its checklist".
    #: The AG office sheet is a matrix, not a list: 25 documents against 11 variants, and a
    #: line ticked for a widow is not ticked for a parent. Encoding that as data keeps one
    #: engine rather than eleven checklists.
    applies_to: frozenset[str] = frozenset()
    #: Where the satisfying document differs by variant. The prescribed form is the case in
    #: point: the sheet prints one line, "(B-I, B-IV, D-I, D-II, ...)", but only one of those
    #: is correct for any given case, and accepting any of them would pass a bundle carrying
    #: the wrong sanction form.
    satisfied_by_for: dict[str, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class ChecklistItem:
    id: str
    requirement: str
    status: str
    located: tuple[int, ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict:
        d = {"id": self.id, "requirement": self.requirement, "status": self.status}
        if self.located:
            d["located"] = list(self.located)
        if self.reason:
            d["reason"] = self.reason
        return d


@dataclass(frozen=True)
class Checklist:
    checklist_id: str
    items: tuple[ChecklistItem, ...]

    @property
    def required(self) -> int:
        return len(self.items)

    @property
    def present(self) -> int:
        return sum(1 for i in self.items if i.status == PRESENT)

    @property
    def missing(self) -> int:
        return sum(1 for i in self.items if i.status == MISSING)

    @property
    def defective(self) -> int:
        return sum(1 for i in self.items if i.status == DEFECTIVE)

    @property
    def not_applicable(self) -> int:
        return sum(1 for i in self.items if i.status == NOT_APPLICABLE)

    @property
    def not_required(self) -> int:
        return sum(1 for i in self.items if i.status in (NOT_REQUIRED, FOUND_NOT_REQUIRED))

    @property
    def satisfied(self) -> int:
        """Present plus properly not-applicable or not required. What "16/16" counts."""
        return self.present + self.not_applicable + self.not_required

    @property
    def result(self) -> str:
        """``COMPLETE`` only when nothing is missing. BRAIN §6.1 invariant 4.

        A DEFECTIVE item does not make the checklist incomplete -- the paper is there. It
        surfaces as a flag instead, which is what sends the correction letter.
        """
        return COMPLETE if self.missing == 0 else INCOMPLETE

    @property
    def result_line(self) -> str:
        if self.result == COMPLETE:
            return (
                f"CHECKLIST COMPLETE - {self.satisfied}/{self.required}, no missing document. "
                "Any defects found are data inconsistencies, not absent papers."
            )
        names = ", ".join(i.id for i in self.items if i.status == MISSING)
        return f"CHECKLIST INCOMPLETE - {self.missing} missing ({names})."

    def item(self, item_id: str) -> ChecklistItem:
        for i in self.items:
            if i.id == item_id:
                return i
        raise KeyError(f"no checklist item {item_id!r}")

    def to_dict(self) -> dict:
        return {
            "checklist_id": self.checklist_id,
            "items": [i.to_dict() for i in self.items],
            "result": self.result,
            "required": self.required,
            "present": self.present,
            "missing": self.missing,
            "defective": self.defective,
            "not_applicable": self.not_applicable,
            "not_required": self.not_required,
            "satisfied": self.satisfied,
        }


# -- applicability and defect predicates -------------------------------------------------------

def _no_deputation(record: CaseRecord) -> str | None:
    """``U-07``: deputation challans do not apply where the record shows no deputation.

    §7.3 forbids marking NOT_APPLICABLE without a reason grounded in the case facts, so the
    reason names what was inspected rather than merely asserting non-applicability.
    """
    if record.stated("deputation_period"):
        return None
    return "no deputation period appears in the service record"


def _form_not_signed_by_psa(record: CaseRecord) -> str | None:
    """Whether the prescribed form lacks a PSA signature.

    Deliberately does NOT fire on the vision model's own boolean. That flag flipped between
    two runs of the identical page on 2026-09-04 -- True on one, False on the next -- and
    False marks the requirement DEFECTIVE, which under §7.3 sends the department a correction
    letter for a form that §13.4 records as properly signed by the Additional Secretary
    (Admn), countersigned by DEO(SE) and DPI.

    A defect asserted from one unreliable boolean is a false accusation, and the asymmetry in
    BRAIN §15.2 is explicit: a gap costs an officer minutes, a wrong assertion costs a family
    a round trip. Until the signature can be corroborated -- a second reader, or the officer
    confirming it in the reviewer UI -- this returns None and the requirement stands as
    PRESENT with the signature unverified rather than denied.
    """
    doc = record.document("FORM_D_I") or record.document("FORM_D_II")
    if doc and doc.signatory_is_psa is False and doc.signatory:
        # Only where the model actually named a signatory who is not the PSA -- that is a
        # positive finding, not the absence of one.
        return f"prescribed form signed by {doc.signatory}, who is not the PSA (U-01)"
    return None


def _annex_a_unattested(record: CaseRecord) -> str | None:
    doc = record.document("ANNEX_A")
    if doc and doc.attested is False:
        return "Annex-A is not attested (U-02)"
    return None


#: Gazetted service begins at BPS-16 (confirmed by the AG office, 9 September 2026). The
#: boundary decides which service record exists at all, so it is named here rather than
#: written into a comparison. Note it is NOT the same boundary as the medical-allowance
#: bands, which also split at 16 but for an unrelated reason -- two rules sharing a number
#: is a coincidence, and collapsing them would couple them.
GAZETTED_FROM_BPS = 16


def _service_record_pair(record: CaseRecord) -> tuple[bool | None, str]:
    """Is this a gazetted servant, and on what evidence? ``None`` where it cannot be said.

    Preference order is deliberate. The grade decides it where the grade is known. Where it
    is not, the bundle itself often settles the question -- an AG service statement is issued
    only to gazetted officers and a service book is kept only for non-gazetted ones, so the
    presence of exactly one of them identifies the kind of servant without any grade at all.
    """
    bps = record.pay_scale_bps
    if bps is not None:
        gazetted = bps >= GAZETTED_FROM_BPS
        return gazetted, f"BS-{bps}"
    has_statement = record.document("SERVICE_STATEMENT") is not None
    has_book = record.document("SERVICE_BOOK") is not None
    if has_statement and not has_book:
        return True, "an AG service statement is in the bundle, which is issued only for gazetted officers"
    if has_book and not has_statement:
        return False, "a service book is in the bundle, which is kept only for non-gazetted servants"
    return None, ""


def _service_book_not_kept(record: CaseRecord) -> str | None:
    """AG-10 does not apply to a gazetted officer: no service book exists to produce."""
    gazetted, basis = _service_record_pair(record)
    if gazetted is True:
        return (
            f"the servant is gazetted ({basis}); the manual service book is the non-gazetted "
            f"record, and the AG service statement stands in its place"
        )
    return None


def _claimant_relation_key(record: CaseRecord) -> str | None:
    """The claimant's relation as the prescribed form words it, read against the fixed list
    (rules.relations); None where the form does not say."""
    from rules.relations import parse_relation
    stated = record.claimant_relation or record.frc_applicant_relation
    return parse_relation(stated).key if stated else None


def _medical_board_certificate_not_called_for(record: CaseRecord) -> str | None:
    """AG-14, the medical board's certificate, is a conditional line: it proves an invalidation
    or a claimant's disability. On a death in service it is called for only where the claimant is
    a disabled child; on an invalid pension not where the retirement was a compulsory one (a
    penalty, with no board). Until 12 Oct 2026 the line was demanded of every death in service,
    so every complete Form D-I bundle read INCOMPLETE (audit of 12 Oct 2026). A relation the form
    does not state keeps the line, so it asks rather than excuses."""
    if record.case_variant == "DEATH_IN_SERVICE":
        key = _claimant_relation_key(record)
        if key is not None and key != "disabled_child":
            return ("the claimant is not a disabled child; no medical board certificate is called for on "
                    "this death in service")
    if record.case_variant == "FRESH_INVALID" and record.has_document("COMPULSORY_RETIREMENT_ORDER") \
            and not record.has_document("MEDICAL_BOARD_CERTIFICATE"):
        return "a compulsory retirement is ordered as a penalty, not certified by a medical board"
    return None


def _income_certificate_not_called_for(record: CaseRecord) -> str | None:
    """AG-17, the no-regular-income certificate, is for a dependent claimant other than the
    spouse: on a death in service a widow or widower is not asked for one (audit of 12 Oct 2026)."""
    if record.case_variant == "DEATH_IN_SERVICE" and _claimant_relation_key(record) == "spouse":
        return "the claimant is the spouse; the no-regular-income certificate is for a dependent child, parent or sister"
    return None


def _divorce_certificate_not_called_for(record: CaseRecord) -> str | None:
    """AG-21, the divorce certificate, proves a divorced daughter's or sister's status: on a death
    in service it is called for only where the claimant is divorced (audit of 12 Oct 2026)."""
    if record.case_variant == "DEATH_IN_SERVICE":
        key = _claimant_relation_key(record)
        if key is not None and key != "divorced_daughter":
            return "the claimant is not a divorced daughter; no divorce certificate is called for"
    return None


def _lpc_not_required_of_a_gazetted_self_pensioner(record: CaseRecord) -> str | None:
    """AG-08 on a self pension: the LPC is required of a non-gazetted servant and not of a
    gazetted one (user, 12 Oct 2026, decision S15; gazetted from BS-16 as GAZETTED_FROM_BPS).

    Self-pension columns only: a death in service is family pension and outside the decision.
    A grade that cannot be told keeps the requirement, so the line asks rather than excuses."""
    if record.case_variant not in SELF_PENSION_VARIANTS:
        return None
    gazetted, basis = _service_record_pair(record)
    if gazetted is True:
        return (f"the servant is gazetted ({basis}); a gazetted officer's last pay is certified by "
                f"Audit/Payrolls, so the Last Pay Certificate is not required of them")
    return None


def _pension_slip_stands_in(record: CaseRecord) -> str | None:
    """Items 23 and 24: "not required in case of on-line pension slip".

    The PPO book and the bank half are the paper record of a pension in payment. Where the
    pension runs on a slip instead -- on-line or printed -- that record exists in the system
    and the office does not ask for the books (AG office, 9 September 2026: if the slip is
    present in either form, accept it).

    Nothing in a bundle announces "this case is on-line", so the condition is decided by the
    slip actually being there rather than by a status nobody records. If it is absent, the
    lines stand: a case with neither the books nor a slip has no payment record at all.
    """
    doc = record.document("PENSION_SLIP")
    if doc is None:
        return None
    return (
        f"a pension slip is in the bundle{doc.page_ref and f' at {doc.page_ref}' or ''}; the "
        f"sheet does not require the PPO book or the bank file where the pension runs on a slip"
    )


#: Item 19 asks for a reason for late submission "if more 3 years".
LATE_SUBMISSION_YEARS = 3


def _case_submitted_in_time(record: CaseRecord) -> str | None:
    """Item 19 applies only to a case submitted more than three years after the event.

    Both dates come off the papers: the sanction form states when the servant died or
    retired, and the forwarding letter is dated when the department sent the case in. Where
    the gap is under three years the department has nothing to explain and the line does not
    apply.

    Where either date is unknown the requirement STANDS. A case whose age cannot be
    established is not a case known to be recent, and excusing it on that basis would hide
    exactly the delay the item exists to surface.
    """
    began, sent = record.entitlement_date, record.submitted_date
    if began is None or sent is None or sent < began:
        return None
    years = (sent - began).days / 365.2425
    if years >= LATE_SUBMISSION_YEARS:
        return None
    return (
        f"the case was submitted {_span(began, sent)} after the servant "
        f"{'died' if record.case_variant not in SELF_PENSION_VARIANTS else 'retired'} "
        f"({began.isoformat()} to {sent.isoformat()}), within the "
        f"{LATE_SUBMISSION_YEARS} years beyond which item 19 asks for an explanation"
    )


def _span(a: date, b: date) -> str:
    """A human interval: "4 years 10 months", not "1756 days"."""
    months = (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)
    years, rem = divmod(max(months, 0), 12)
    if years and rem:
        return f"{years} year{'s' if years > 1 else ''} {rem} month{'s' if rem > 1 else ''}"
    if years:
        return f"{years} year{'s' if years > 1 else ''}"
    if rem:
        return f"{rem} month{'s' if rem > 1 else ''}"
    return f"{(b - a).days} day{'s' if (b - a).days != 1 else ''}"


def _applicant_shown_in_frc(record: CaseRecord) -> str | None:
    """Item 22 applies only "in case applicant not Shown in FRC".

    The Nikah Nama exists to prove the relationship that entitles the claimant. Where the
    NADRA Family Registration Certificate already records them as a family member, the
    relationship is proved and the office does not ask for it -- the condition is printed in
    the item's own text, and without it the line reads MISSING on a case that is complete.

    Two deliberate refusals to excuse:

    *   **No FRC extracted, no excuse.** An empty family list means the FRC was not read, not
        that the applicant is absent from it. Absence of evidence must not satisfy a document
        requirement, so the line stays required and an officer sees it.
    *   **No claimant name, no excuse.** Same reason.

    Matching is by similarity rather than equality, at the threshold the family checks already
    use: this bundle's FRC prints WAQQAR where the forms print WAQAR, and an exact match
    would excuse nobody. Membership is the question -- whether the applicant appears at all --
    so it does not use ``_match_person``, which refuses when two candidates tie. This FRC lists
    the same person three times, and three identical entries are one person, not an ambiguity.
    """
    from difflib import SequenceMatcher

    from .flags import NAME_MATCH_THRESHOLD, _norm_name

    if not record.frc_family or not record.claimant_name:
        return None
    target = " ".join(sorted(_norm_name(record.claimant_name)))
    if not target:
        return None
    for member in record.frc_family:
        candidate = " ".join(sorted(_norm_name(member.name)))
        if candidate and SequenceMatcher(None, target, candidate).ratio() >= NAME_MATCH_THRESHOLD:
            where = f" at p.{member.source.page}" if member.source else ""
            return (
                f"the applicant is shown in the NADRA FRC as {member.name} "
                f"({member.relation}){where}; item 22 asks for a marriage registration only "
                f"where the applicant is NOT shown in the FRC"
            )
    return None


# -- the checklists ----------------------------------------------------------------------------

FAMILY_IN_SERVICE_DEATH = (
    Requirement("CL-01", "Form D-I on the FD-prescribed proforma, signed by the PSA",
                ("FORM_D_I",), derives_from="U-01", defective_when=_form_not_signed_by_psa),
    Requirement("CL-02", "Annex-A (Descriptive Roll with undertaking), duly attested",
                ("ANNEX_A",), derives_from="U-02", defective_when=_annex_a_unattested),
    Requirement("CL-03", "Attested death certificate (NADRA / AMA / TMA / Union Administration)",
                ("NADRA_DEATH_CERTIFICATE", "DEATH_CERTIFICATE")),
    Requirement("CL-04", "Attested copy of the last computer salary slip issued by AG/DAO",
                ("SALARY_STATEMENT",), derives_from="U-04"),
    Requirement("CL-05", "Last Pay Certificate (LPC)", ("LPC",)),
    Requirement("CL-06", "Attested copy of the valid CNIC of the deceased",
                ("CNIC_DECEASED",), derives_from="U-05"),
    Requirement("CL-07", "Attested CNIC of the eligible family member / claimant",
                ("CNIC_CLAIMANT",), derives_from="U-05"),
    Requirement("CL-08", "Deputation: verified pension-contribution credit challans",
                ("DEPUTATION_CHALLANS",), derives_from="U-07",
                not_applicable_when=_no_deputation),
    # POSTING_ORDER counts. §13.4 records the service-record requirement as satisfied by
    # "AG service statement + posting orders 1993-2014 + DAO Sheikhupura LPC", and the real
    # bundle contains no service statement at all -- the service history is carried by the
    # posting orders. Accepting only SERVICE_STATEMENT/SERVICE_BOOK reported a complete case
    # as missing a document, which would have sent a department a letter asking for papers
    # it had already filed.
    # The proforma for qualifying service is a service record for gazetted and non-gazetted
    # servants alike (C2, 12 Oct 2026, S3).
    Requirement("CL-09", "Service record: service book, AG service statement, the posting-order history, "
                "or the proforma for qualifying service",
                ("SERVICE_STATEMENT", "SERVICE_BOOK", "POSTING_ORDER", "QUALIFYING_SERVICE_PROFORMA"),
                derives_from="U-03/U-06"),
    Requirement("CL-10", "Forwarding letter from the administrative department",
                ("FORWARDING_LETTER",)),
    Requirement("CL-11", "Obituary / death office order", ("DEATH_OFFICE_ORDER", "OBITUARY")),
    Requirement("CL-12", "Attested photographs of the claimant", ("PHOTOGRAPHS",)),
    Requirement("CL-13", "Specimen signatures and thumb impressions, attested",
                ("SPECIMEN_SIGNATURES",)),
    Requirement("CL-14", "Bank option form verified by the branch, with indemnity bond",
                ("BANK_OPTION_FORM",)),
    Requirement("CL-15", "No-marriage / non-remarriage evidence (Union Council certificate, affidavit, FRC)",
                ("NON_REMARRIAGE_CERTIFICATE", "NADRA_FRC")),
    Requirement("CL-16", "NDC / No Enquiry / No Audit Para / No Punishment certificates",
                ("NDC",),
                absence_excused_by=(
                    "Rule 5.4 Note 1: the absence of a No Demand Certificate is not a "
                    "reason to withhold or delay a pension case"
                )),
)

CHECKLISTS: dict[str, tuple[str, tuple[Requirement, ...]]] = {
    "FAMILY_PENSION_DEATH_IN_SERVICE": ("FD_FAMILY_IN_SERVICE_DEATH", FAMILY_IN_SERVICE_DEATH),
}



# -- the AG office checklist of 2026 -----------------------------------------------------------
# Source: "Document Checklist.pdf", the operational sheet in use at the AG office. It is a
# matrix of 25 documents against 11 case variants, which group into the two case families the
# office actually works in.
#
# The FD checklist above (FD_FAMILY_IN_SERVICE_DEATH, 16 lines) is kept and still governs the
# golden case, because BRAIN §13.4 records that case as 16/16 and it is the one benchmark whose
# every value has been verified by hand. Two lists, both real, selected explicitly -- the same
# pattern the rule packs already use.

SELF_PENSION = "SELF_PENSION"
FAMILY_PENSION = "FAMILY_PENSION"

#: Which variants belong to which family. The officer's sheet runs Death-in-Service through
#: Sister as one continuous block: they are all family pension, differing only in who claims.
CASE_FAMILY_VARIANTS: dict[str, tuple[str, ...]] = {
    SELF_PENSION: ("FRESH_SELF", "FRESH_INVALID", "REVISED"),
    FAMILY_PENSION: (
        "DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER",
        "DISABLED_CHILD_SIBLING", "PARENT", "SISTER",
    ),
}

#: Column headings as the officer's sheet prints them, for the intake drop-down.
VARIANT_LABELS: dict[str, str] = {
    "FRESH_SELF": "Fresh - Self",
    "FRESH_INVALID": "Fresh - Invalid",
    "REVISED": "Revised",
    "DEATH_IN_SERVICE": "Death during service",
    "WIDOW": "Widow / Widower",
    "UNMARRIED_CHILD": "Unmarried daughter / son",
    "WD_DAUGHTER": "Widowed / divorced daughter",
    "DIVORCED_DAUGHTER": "Divorced daughter",
    "DISABLED_CHILD_SIBLING": "Disabled son / daughter / sister",
    "PARENT": "Parent",
    "SISTER": "Unmarried / widowed / divorced sister",
}

#: Columns where the claimant IS the pensioner, so the entitling event is a retirement
#: rather than a death. rules.flags imports this rather than keeping a second copy.
SELF_PENSION_VARIANTS = frozenset(CASE_FAMILY_VARIANTS[SELF_PENSION])

ALL_VARIANTS: tuple[str, ...] = tuple(
    v for vs in CASE_FAMILY_VARIANTS.values() for v in vs
)



#: Which prescribed form the PSA signs, per case variant. Read from the FD's blank-forms
#: compendium, where each form states its own scenario in its subject line:
#:
#:   Form B-I    "to be used in case of retirement on superannuation or RETIRING PENSION"
#:   Form B-II   "FOR ANTICIPATORY PENSION ... issued 90 days before"
#:   Form B-III  "FOR FINAL PENSION PAYMENT WHERE ANTICIPATORY PENSION ALREADY PAID"
#:   Form B-IV   "TO BE USED IN CASE OF COMPULSORY / INVALIDATION RETIREMENT"
#:   Form D-I    "in the event of IN-SERVICE DEATH of a government servant"
#:   Form D-II   "in the event of DEATH OF THE PENSIONER"
#:
#: D-I against D-II turns on WHEN the death occurred, not on who claims. That is why the
#: officer's sheet has one "death during service" column (D-I) and seven claimant columns --
#: widow, unmarried child, parent and the rest -- which are all the death-of-a-pensioner
#: case (D-II), differing only in which family member is eligible. Form D-II asks for the
#: "PPO / FPPO No" of the deceased, which only exists once someone has retired; Form D-I asks
#: instead for the pay the servant "expired on while in service".
FORM_FOR_VARIANT: dict[str, tuple[str, ...]] = {
    "FRESH_SELF": ("FORM_B_I",),
    "FRESH_INVALID": ("FORM_B_IV",),
    # No form in the compendium describes a revision, so the sheet's PSA-form line cannot be
    # narrowed for this variant: a revised case is a revision OF an earlier sanction, and the
    # governing form is whichever the original case used. Any prescribed form satisfies it,
    # and that looseness is recorded here rather than hidden.
    "REVISED": ("FORM_B_I", "FORM_B_II", "FORM_B_III", "FORM_B_IV", "FORM_D_I", "FORM_D_II"),
    "DEATH_IN_SERVICE": ("FORM_D_I",),
    "WIDOW": ("FORM_D_II",),
    "UNMARRIED_CHILD": ("FORM_D_II",),
    "WD_DAUGHTER": ("FORM_D_II",),
    "DIVORCED_DAUGHTER": ("FORM_D_II",),
    "DISABLED_CHILD_SIBLING": ("FORM_D_II",),
    "PARENT": ("FORM_D_II",),
    "SISTER": ("FORM_D_II",),
}

#: Scenarios the compendium prescribes a form for that the office sheet has no column for.
#: Recorded so the gap is visible rather than discovered by a case that cannot be processed.
FORMS_WITHOUT_A_CHECKLIST_COLUMN = {
    "FORM_B_II": "anticipatory pension",
    "FORM_B_III": "final pension where anticipatory was already paid",
}

#: How old a NADRA Family Registration Certificate may be when the case is submitted. AG
#: Punjab office practice, stated by the office on 17 September 2026: an FRC is a snapshot
#: of a family that changes -- deaths, marriages, births -- and one issued more than six
#: months before the case reached the office no longer proves the family it describes. No
#: notification on file states the figure; it is office practice and is cited as such.
#: CONFIRM: the period, and whether it is measured to the department's forwarding date or to
#: receipt at the AG.
FRC_MAX_AGE_MONTHS = 6


def add_months(on: date, months: int) -> date:
    """The same day of the month ``months`` later, clamped to the end of a shorter month."""
    y, m = divmod(on.month - 1 + months, 12)
    year, month = on.year + y, m + 1
    last = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(on.day, last))


def frc_reference_date(record: CaseRecord) -> tuple[date, str] | None:
    """The date an FRC's age is measured to: receipt at the AG, else the forwarding date."""
    received = record.event("RECEIVED_AT_AG")
    if received is not None:
        return received.date, "receipt at the Accountant General"
    if record.submitted_date is not None:
        return record.submitted_date, "the date the department forwarded the case"
    return None


def stale_frcs(record: CaseRecord) -> list[dict]:
    """Every FRC page issued more than ``FRC_MAX_AGE_MONTHS`` before the reference date.

    Reads the ``FRC_ISSUED`` timeline events the report builds from the certificate's own
    printed date. An FRC issued AFTER the reference date is not stale -- a family that
    obtained a fresh certificate while the case was in transit has done what is asked.
    Where no reference date is on the record nothing is returned: an age that cannot be
    measured is not reported as either fine or stale.
    """
    ref = frc_reference_date(record)
    if ref is None:
        return []
    ref_date, ref_label = ref
    out: list[dict] = []
    seen: set[int] = set()
    for ev in record.timeline:
        if ev.event != "FRC_ISSUED" or ev.source is None or ev.source.page in seen:
            continue
        seen.add(ev.source.page)
        limit = add_months(ev.date, FRC_MAX_AGE_MONTHS)
        if limit < ref_date:
            out.append({
                "page": ev.source.page, "issued": ev.date, "reference": ref_date,
                "reference_label": ref_label, "valid_until": limit,
                "days_over": (ref_date - limit).days,
            })
    return sorted(out, key=lambda x: x["page"])


#: What a card prints where it does not expire.
CNIC_LIFETIME = "LIFETIME"


def claimant_cnic_status(record: CaseRecord) -> list[dict]:
    """Each of the claimant's CNIC cards with whether it was in force when the case came in.

    Reads the ``CNIC_CLAIMANT_EXPIRES`` timeline events the report builds from the card's own
    printed 'Date of Expiry' (a lifetime card puts nothing on the timeline and is never
    expired). Measured to the same reference date as the FRC: receipt at the AG where the
    record has it, else the forwarding date; and, where the record carries the date it was
    processed, whether the card has expired since. Empty where nothing can be measured.
    """
    ref = frc_reference_date(record)
    out: list[dict] = []
    seen: set[int] = set()
    for ev in record.timeline:
        if ev.event not in ("CNIC_CLAIMANT_EXPIRES", "CNIC_CLAIMANT_EXPIRES_UNCONFIRMED") \
                or ev.source is None or ev.source.page in seen:
            continue
        seen.add(ev.source.page)
        entry = {"page": ev.source.page, "expires": ev.date,
                 # False where OCR read an expiry but no issue date: see pipeline.report.
                 "confirmed": ev.event == "CNIC_CLAIMANT_EXPIRES",
                 "expired_at_submission": False, "expired_since": False,
                 "reference": None, "reference_label": None, "processed_on": record.processed_on}
        if ref is not None:
            ref_date, ref_label = ref
            entry["reference"], entry["reference_label"] = ref_date, ref_label
            entry["expired_at_submission"] = ev.date < ref_date
            if not entry["expired_at_submission"] and record.processed_on is not None:
                entry["expired_since"] = ev.date < record.processed_on
        elif record.processed_on is not None:
            entry["expired_since"] = ev.date < record.processed_on
        out.append(entry)
    return sorted(out, key=lambda x: x["page"])


def _claimant_cnic_expired(record: CaseRecord) -> str | None:
    """AG-02 is DEFECTIVE where the claimant's card had expired before the case was submitted."""
    expired = [x for x in claimant_cnic_status(record)
               if x["expired_at_submission"] and x["confirmed"]]
    if not expired:
        return None
    parts = [
        f"claimant's CNIC at p.{x['page']} expired {x['expires'].isoformat()}; "
        f"{x['reference_label']} was {x['reference'].isoformat()}"
        for x in expired
    ]
    return f"expired before the case was submitted ({'; '.join(parts)}). A valid CNIC is required."


#: Documents the SOP requires as attested photocopies (§5.1(1); §5.2 AG-02, AG-06; §5.6 AG-20,
#: AG-21, AG-22; §5.3 AG-12), by the type the identifier assigns.
ATTESTED_COPY_TYPES: frozenset[str] = frozenset({
    "CNIC", "CNIC_CLAIMANT", "CNIC_DECEASED", "NADRA_FRC", "NADRA_DEATH_CERTIFICATE",
    "DIVORCE_CERTIFICATE", "NIKAH_NAMA", "SALARY_STATEMENT",
})


def unattested_copies(record: CaseRecord) -> list:
    """Required photocopy documents the reader saw NO attestation on (``attested`` is False).

    ``None`` means the page was not judged and is not reported; only an explicit False is.
    """
    return [d for d in record.documents
            if d.type in ATTESTED_COPY_TYPES and d.present and d.attested is False]


def _frc_stale(record: CaseRecord) -> str | None:
    """AG-06 is DEFECTIVE, not merely present, where the FRC has outlived its six months."""
    stale = stale_frcs(record)
    if not stale:
        return None
    parts = [
        f"FRC at p.{x['page']} issued {x['issued'].isoformat()}, valid to "
        f"{x['valid_until'].isoformat()}; {x['reference_label']} was "
        f"{x['reference'].isoformat()}, {x['days_over']} day(s) later"
        for x in stale
    ]
    return (f"issued more than {FRC_MAX_AGE_MONTHS} months before the case was submitted "
            f"({'; '.join(parts)}). A fresh NADRA FRC is required.")


AG_OFFICE_2026: tuple[Requirement, ...] = (
    Requirement(
        "AG-01",
        "Forwarding letter from the DDO of the concerned department",
        ("FORWARDING_LETTER",),
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID", "REVISED", "DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-02",
        "Attested copies of CNIC/s, attested by the DDO",
        ("CNIC_CLAIMANT", "CNIC_DECEASED", "CNIC",),
        defective_when=_claimant_cnic_expired,
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID", "REVISED", "DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-03",
        "Passport-size photographs",
        ("PHOTOGRAPHS",),
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID", "DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-04",
        "Pension Sanctioning Authority form for this case, signed by the PSA",
        ("FORM_B_I", "FORM_B_II", "FORM_B_III", "FORM_B_IV", "FORM_D_I", "FORM_D_II",),
        satisfied_by_for=FORM_FOR_VARIANT,
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID", "REVISED", "DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-05",
        "List of family members, verified by the PSA",
        ("ANNEX_A",),
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID", "DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-06",
        "NADRA Family Registration Certificate/s, attested by the DDO",
        ("NADRA_FRC",),
        defective_when=_frc_stale,
        # The printed sheet ticks the family-pension columns only. The user's decision of
        # 12 Oct 2026 (S14) adds the three self-pension columns: the certificate is required
        # there too, found or not found. tests.test_checklist_fidelity carries the same
        # addition as a decision made after the sheet was printed.
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID", "REVISED", "DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-07",
        "Option for commutation",
        ("COMMUTATION_OPTION",),
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID"}),
    ),
    Requirement(
        "AG-08",
        "Last Pay Certificate (DDO for non-gazetted, Audit/Payrolls for gazetted)",
        ("LPC",),
        not_applicable_when=_lpc_not_required_of_a_gazetted_self_pensioner,
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID", "REVISED", "DEATH_IN_SERVICE"}),
    ),
    Requirement(
        "AG-09",
        "Service statement, gazetted by Audit (Payrolls)",
        ("SERVICE_STATEMENT",),
        # Off the sheet entirely from 21 Oct 2026 by the office's decision. It was not required
        # in any case type from 12 Oct (S16) but still printed a "Not required" line on every
        # column, and the office asked for the line itself to go: a checklist that lists what
        # it does not want read as noise to the officers working it.
        #
        # The line is kept here rather than deleted so the reason stays on the record, and
        # because the statement still tells a gazetted officer from a non-gazetted servant for
        # _service_record_pair, which excuses AG-08 for a gazetted officer (decision S15).
        # Empty applies_to is what removes it: requirements_for skips a line whose column set
        # does not contain the variant.
        applies_to=frozenset(),
    ),
    Requirement(
        "AG-10",
        "Original service book with photocopies attested by the DDO, or the proforma for "
        "qualifying service (non-gazetted)",
        # A "Character and Service Roll" is the same record under the name the police and
        # several other departments use for it: photograph, particulars, posting history,
        # declaration. Accepting only the words "service book" returned a case for a document
        # that was in the bundle under its other name.
        #
        # The proforma for qualifying service satisfies the line too (scope change C2, decided
        # by the user 12 Oct 2026, S3): either paper, from now on, with no cut-off date while the
        # proforma is still "proposed". A cut-off, if the office notifies one, goes here.
        #
        # NOT REQUIRED in any case type from 20 Oct 2026, by the office's decision -- the same
        # treatment AG-09 was given on 12 Oct. The line is kept rather than deleted so a service
        # book that IS filed is still cited (FOUND_NOT_REQUIRED) instead of going unmentioned,
        # and so the reason this stopped being asked for stays on the record. Absent, it is
        # NOT_REQUIRED and never counts as missing.
        #
        # Off the sheet entirely from 21 Oct 2026, with AG-09 and for the same reason: it stopped
        # being required on 20 Oct and went on printing "Not required" on every column. What the
        # office now asks for instead is AG-26, the proforma, which is required everywhere.
        ("SERVICE_BOOK", "CHARACTER_SERVICE_ROLL", "QUALIFYING_SERVICE_PROFORMA"),
        not_applicable_when=_service_book_not_kept,
        applies_to=frozenset(),
    ),
    Requirement(
        "AG-11",
        "Bank option form verified by the bank, with indemnity bond where available",
        ("BANK_OPTION_FORM",),
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID", "DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-12",
        "Last computerised payslip (autonomous bodies), attested by the DDO",
        ("SALARY_STATEMENT",),
        # Not required in any case type since 12 Oct 2026 (NOT_REQUIRED_ANYWHERE, S16).
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID", "DEATH_IN_SERVICE"}),
    ),
    Requirement(
        "AG-13",
        "Order of retirement / obituary / death / revision, original or DDO-attested",
        ("DEATH_OFFICE_ORDER", "SUPERANNUATION_ORDER", "COMPULSORY_RETIREMENT_ORDER", "VOLUNTARY_RETIREMENT_REQUEST",),
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID", "REVISED", "DEATH_IN_SERVICE"}),
    ),
    Requirement(
        "AG-14",
        "Original medical / disability certificate from a medical board",
        ("MEDICAL_BOARD_CERTIFICATE",),
        not_applicable_when=_medical_board_certificate_not_called_for,
        applies_to=frozenset({"FRESH_INVALID", "DEATH_IN_SERVICE", "DISABLED_CHILD_SIBLING"}),
    ),
    Requirement(
        "AG-15",
        "Non-remarriage / no-marriage certificate, Union Council, countersigned by the DDO",
        ("NON_REMARRIAGE_CERTIFICATE",),
        applies_to=frozenset({"DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "SISTER"}),
    ),
    Requirement(
        "AG-16",
        "Sole / lawful widow certificate, verified by the DDO",
        ("SOLE_WIDOW_CERTIFICATE",),
        applies_to=frozenset({"DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-17",
        "No-regular-source-of-income certificate, signed by the PSA",
        ("NO_REGULAR_INCOME_CERTIFICATE",),
        not_applicable_when=_income_certificate_not_called_for,
        applies_to=frozenset({"DEATH_IN_SERVICE", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-18",
        "Entitlement of arrears certificate, signed by the PSA",
        ("ARREARS_ENTITLEMENT_CERTIFICATE",),
        applies_to=frozenset({"UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-19",
        "Reason for late submission, by the DDO, where the case is more than three years old",
        ("LATE_SUBMISSION_REASON",),
        not_applicable_when=_case_submitted_in_time,
        applies_to=frozenset({"FRESH_SELF", "FRESH_INVALID", "DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-20",
        "Computerised death certificate/s, attested by the DDO",
        ("NADRA_DEATH_CERTIFICATE", "DEATH_CERTIFICATE",),
        applies_to=frozenset({"DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-21",
        "Computerised divorce certificate/s, attested by the DDO",
        ("DIVORCE_CERTIFICATE",),
        not_applicable_when=_divorce_certificate_not_called_for,
        applies_to=frozenset({"DEATH_IN_SERVICE", "SISTER"}),
    ),
    # AG-22, the Nikah Nama "where the applicant is not shown in the FRC", is not a checklist
    # line here (office decision, 24 Sep 2026): no real bundle carried one where it was asked
    # for, and a MISSING line put it in every return letter. It is a MEDIUM finding instead --
    # rules.flags.check_nikah_nama -- raised on the same condition, for the officer to decide.
    Requirement(
        "AG-23",
        "Original PPO book with LPC (FIR where lost); not required with an on-line pension slip",
        ("PPO",),
        not_applicable_when=_pension_slip_stands_in,
        applies_to=frozenset({"DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-24",
        "Original bank file / half (bank letter where misplaced); not required with an on-line pension slip",
        ("BANK_FILE",),
        not_applicable_when=_pension_slip_stands_in,
        applies_to=frozenset({"DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    Requirement(
        "AG-25",
        "Affidavit in original",
        ("AFFIDAVIT",),
        applies_to=frozenset({"FRESH_INVALID", "DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"}),
    ),
    # The proforma for qualifying service, required of every case type from 21 Oct 2026 by the
    # office's decision. It is the paper that REPLACED the service book: AG-10 stopped being
    # required anywhere on 20 Oct, and departments now file this one-pager instead of sending
    # the book. So this is not an addition to the service-record lines but the successor to
    # them, and unlike AG-09 and AG-10 it is asked for in all eleven variants.
    #
    # AG-26 rather than AG-22, which is retired: a number the office has seen on a sheet should
    # not come back meaning something else.
    #
    # The service record is still read as the office states it and compared with nothing -- no
    # qualifying service is computed here (rules/scope.py). This line asks whether the paper is
    # in the bundle, which is the whole of what the checklist decides.
    Requirement(
        "AG-26",
        # The office's own words for it, and the spelling printed on the form itself
        # ("PROPOSED PERFORMA FOR QUALIFYING SEVICE FOR PENSION"). Renamed 21 Oct 2026 from
        # "Proforma for qualifying service, certified by the department and verified by the
        # Accountant General / District Accounts Office": a checklist line is read at a glance
        # down a column, and the certification it describes is the same on every other line.
        "Performa for Qualifying Service",
        ("QUALIFYING_SERVICE_PROFORMA",),
        applies_to=frozenset(ALL_VARIANTS),
    ),
)


def requirements_for(variant: str) -> tuple[Requirement, ...]:
    """The AG office lines that apply to one case variant, specialised to it."""
    if variant not in ALL_VARIANTS:
        raise KeyError(f"unknown case variant {variant!r}; have {ALL_VARIANTS}")
    out: list[Requirement] = []
    for r in AG_OFFICE_2026:
        if variant not in r.applies_to:
            continue
        if r.satisfied_by_for and variant in r.satisfied_by_for:
            r = replace(r, satisfied_by=r.satisfied_by_for[variant])
        out.append(r)
    return tuple(out)


def run_checklist(record: CaseRecord, *, variant: str | None = None) -> Checklist:
    """Evaluate the checklist. ``PRESENT`` / ``MISSING`` / ``DEFECTIVE`` / ``NOT_APPLICABLE``.

    ``variant`` selects a column of the AG office sheet -- "FRESH_SELF", "WIDOW", and so on.
    Which variant a case is cannot be read off the bundle: whether the claimant is a widow, an
    unmarried daughter or a parent is a fact about who is claiming, and guessing it would pick
    the wrong column and demand the wrong documents. SOP §6.4 already requires entries to be
    made "via drop-down menus" rather than typed, so the variant is an officer's selection at
    intake, and this function takes it as an input rather than inferring it.

    With no variant, the FD checklist for the case type is used, which is what the golden case
    runs on (BRAIN §13.4, 16/16).

    Order of evaluation matters: not-applicable is decided before presence, because a
    requirement that does not apply is not missing; and a defect is only reachable once the
    document has been found, because a document that is absent is missing, not defective.
    """
    if variant is not None:
        checklist_id = f"AG_OFFICE_2026:{variant}"
        requirements = requirements_for(variant)
    else:
        try:
            checklist_id, requirements = CHECKLISTS[record.case_type]
        except KeyError:
            raise NotImplementedError(
                f"no checklist defined for case type {record.case_type!r}, and no case "
                f"variant was selected. Defined case types: {sorted(CHECKLISTS)}; "
                f"selectable variants: {list(ALL_VARIANTS)}"
            ) from None

    items: list[ChecklistItem] = []
    for req in requirements:
        # Order (office rule, 30 Sep 2026): the case type is known; a line the office does not
        # require is settled first -- cited if the paper is there anyway, never "not found".
        if not_required(req.id, variant):
            located = ()
            for doc_type in req.satisfied_by:
                doc = record.document(doc_type)
                if doc is not None and doc.present:
                    located = doc.pages
                    break
            why = ("not required in any case type (office rule)" if req.id in NOT_REQUIRED_ANYWHERE
                   else NOT_REQUIRED_WHY.get(req.id, "not required for this case type (office rule)"))
            items.append(ChecklistItem(req.id, req.requirement,
                                       FOUND_NOT_REQUIRED if located else NOT_REQUIRED,
                                       located=located, reason=why))
            continue
        if req.not_applicable_when is not None:
            reason = req.not_applicable_when(record)
            if reason:
                items.append(ChecklistItem(req.id, req.requirement, NOT_APPLICABLE, reason=reason))
                continue

        located: tuple[int, ...] = ()
        found = None
        for doc_type in req.satisfied_by:
            doc = record.document(doc_type)
            if doc is not None and doc.present:
                found = doc
                located = doc.pages
                break

        if found is None:
            if req.absence_excused_by:
                items.append(
                    ChecklistItem(req.id, req.requirement, NOT_APPLICABLE,
                                  reason=req.absence_excused_by)
                )
            else:
                items.append(
                    ChecklistItem(req.id, req.requirement, MISSING,
                                  reason=f"none of {', '.join(req.satisfied_by)} located in the bundle")
                )
            continue

        defect = req.defective_when(record) if req.defective_when else None
        if not defect and found.defects:
            defect = "; ".join(found.defects)

        items.append(
            ChecklistItem(
                req.id, req.requirement,
                DEFECTIVE if defect else PRESENT,
                located=located,
                reason=defect,
            )
        )

    return Checklist(checklist_id=checklist_id, items=tuple(items))
