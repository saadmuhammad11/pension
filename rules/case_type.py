"""Case-type classification. BRAIN §4, §4.1.

"Everything downstream branches on case type. Classify first, and state your evidence."

Why this is code and not a model call
-------------------------------------
§4.1 rule 1 is decisive and mechanical: **the PSA form present in the file settles the case
type**, and narrative text does not overrule a present, signed form. That makes the decision a
lookup from an identified document to a path -- not a reading task. The reading task is
"which document is on this page", which is what the vision model does in
``extraction/identify.py``.

The split matters because the paths carry different formulas. Form B-IV covers *both* invalid
pension and compulsory retirement, and the two are not interchangeable: one rests on a
Category-A medical board, the other is a penalty. §4.1 rule 6 is explicit -- "if the file is
genuinely ambiguous, say so and route to human classification. Never guess between paths that
carry different formulas." So where the evidence does not separate two paths, this module
returns both and refuses to choose, in the same spirit as the ``Ambiguity`` mechanism.

§4.1 rule 2 is the other trap: **absence of the expected form is a checklist defect, not a
reclassification.** A file that reads like an invalid-pension case but carries a Form B-I is a
Form B-I case with a flag on it, not a silently reclassified B-IV.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .caserecord import CaseRecord

# -- the shared list (29 Sep 2026) -------------------------------------------------------------
#: One file names the case types for the whole system: this module derives its tables from it
#: and the portal (portals/src/shared/caseTypes.ts) imports the same file, so the list the
#: department picks from and the list the rules run on cannot drift apart.
CASE_TYPES_FILE = Path(__file__).resolve().parents[1] / "config" / "case_types.json"


def load_case_types(path: Path = CASE_TYPES_FILE) -> dict:
    """The shared config as written: ``{"version", "case_types": [...], "aliases": {...}}``."""
    return json.loads(path.read_text(encoding="utf-8"))


_CONFIG = load_case_types()
#: The pipeline's paths (what a bundle is classified as), in config order, with labels.
CASE_TYPES: tuple[str, ...] = tuple(t["id"] for t in _CONFIG["pipeline_types"])
CASE_TYPE_INFO: dict[str, dict] = {t["id"]: t for t in _CONFIG["pipeline_types"]}
CASE_TYPE_LABELS: dict[str, str] = {t["id"]: t["label"] for t in _CONFIG["pipeline_types"]}
#: Older spellings still found in reports and the old portal, mapped to the current id.
CASE_TYPE_ALIASES: dict[str, str] = dict(_CONFIG.get("aliases") or {})
#: The office's case types (the columns of its document sheet), what a DDO declares at intake.
#: Each is also the checklist column the case runs on, and names the pipeline path(s) it may be.
OFFICE_CASE_TYPES: tuple[str, ...] = tuple(t["id"] for t in _CONFIG["case_types"])
OFFICE_CASE_TYPE_INFO: dict[str, dict] = {t["id"]: t for t in _CONFIG["case_types"]}
OFFICE_CASE_TYPE_LABELS: dict[str, str] = {t["id"]: t["label"] for t in _CONFIG["case_types"]}


def canonical_case_type(value: str | None) -> str | None:
    """The config id for a pipeline path as typed or stored, or None where it is not one."""
    if not value:
        return None
    value = CASE_TYPE_ALIASES.get(value, value)
    return value if value in CASE_TYPE_INFO else None


def canonical_office_type(value: str | None) -> str | None:
    """The config id for an office case type (a sheet column) as typed or stored, or None."""
    return value if value and value in OFFICE_CASE_TYPE_INFO else None


def case_type_label(value: str | None) -> str:
    """A label for either kind of id: an office type, or a pipeline path."""
    if value and value in OFFICE_CASE_TYPE_LABELS:
        return OFFICE_CASE_TYPE_LABELS[value]
    key = canonical_case_type(value)
    return CASE_TYPE_LABELS[key] if key else (value or "not determined")


def pipeline_types_for(office_type: str | None) -> tuple[str, ...]:
    """The pipeline path(s) an office case type may be; empty means any (a revision)."""
    key = canonical_office_type(office_type)
    return tuple(OFFICE_CASE_TYPE_INFO[key]["pipeline_types"]) if key else ()


def office_type_for(pipeline_type: str | None, variant: str | None = None) -> str | None:
    """The office case type a detected path (and, after a pensioner's death, the detected
    claimant column) corresponds to; None where the papers do not settle the column."""
    if variant and variant in OFFICE_CASE_TYPE_INFO:
        return variant
    key = canonical_case_type(pipeline_type)
    if not key:
        return None
    matches = [t["id"] for t in _CONFIG["case_types"] if key in t["pipeline_types"]]
    return matches[0] if len(matches) == 1 else None


# -- the seven paths of §4 (plus the two family variants) --------------------------------------
SUPERANNUATION_PENSION = "SUPERANNUATION_PENSION"
RETIRING_PENSION = "RETIRING_PENSION"
ANTICIPATORY_PENSION = "ANTICIPATORY_PENSION"
FINAL_PENSION_AFTER_ANTICIPATORY = "FINAL_PENSION_AFTER_ANTICIPATORY"
INVALID_PENSION = "INVALID_PENSION"
COMPULSORY_RETIREMENT_PENSION = "COMPULSORY_RETIREMENT_PENSION"
FAMILY_PENSION_DEATH_IN_SERVICE = "FAMILY_PENSION_DEATH_IN_SERVICE"
FAMILY_PENSION_DEATH_AFTER_RETIREMENT = "FAMILY_PENSION_DEATH_AFTER_RETIREMENT"

#: The PSA form that governs each path, for the checklist and for §4.1 rule 2. From the
#: shared config; the constants above are checked against it so a typo cannot pass quietly.
PRESCRIBED_FORM: dict[str, str] = {t["id"]: t["prescribed_form"] for t in _CONFIG["pipeline_types"]}
_EXPECTED = {SUPERANNUATION_PENSION, RETIRING_PENSION, ANTICIPATORY_PENSION, FINAL_PENSION_AFTER_ANTICIPATORY,
             INVALID_PENSION, COMPULSORY_RETIREMENT_PENSION, FAMILY_PENSION_DEATH_IN_SERVICE,
             FAMILY_PENSION_DEATH_AFTER_RETIREMENT}
if set(CASE_TYPES) != _EXPECTED:                               # pragma: no cover - config guard
    raise RuntimeError(f"config/case_types.json lists {sorted(CASE_TYPES)}, the rules know {sorted(_EXPECTED)}")

#: Document type -> the path(s) that form governs. A form mapping to more than one path does
#: not settle the case on its own and must be separated by secondary evidence.
_FORM_TO_PATHS: dict[str, tuple[str, ...]] = {
    "FORM_D_I": (FAMILY_PENSION_DEATH_IN_SERVICE,),
    "FORM_D_II": (FAMILY_PENSION_DEATH_AFTER_RETIREMENT,),
    "FORM_B_I": (SUPERANNUATION_PENSION, RETIRING_PENSION),
    "FORM_B_II": (ANTICIPATORY_PENSION,),
    "FORM_B_III": (FINAL_PENSION_AFTER_ANTICIPATORY,),
    "FORM_B_IV": (INVALID_PENSION, COMPULSORY_RETIREMENT_PENSION),
}

#: Confidence bands. A signed prescribed form is the strongest evidence the corpus offers;
#: anything inferred without one sits below the 0.95 accept threshold of BRAIN §5.3 on purpose,
#: because §4.1 rule 2 wants the missing form surfaced rather than worked around.
CONF_SIGNED_FORM = 0.98
CONF_UNSIGNED_FORM = 0.90
CONF_INFERRED = 0.70


@dataclass(frozen=True)
class CaseTypeResult:
    """A classification, its evidence, and what it could not rule out."""

    case_type: str | None
    confidence: float
    evidence: str
    #: Populated when the evidence does not separate two or more paths. Non-empty means
    #: ``case_type`` is None and the case routes to human classification (§4.1 rule 6).
    alternatives: tuple[str, ...] = ()
    #: §4.1 rule 2 findings: the form present disagrees with what the file reads like, or no
    #: prescribed form was located at all. Never a reason to reclassify.
    contradictions: tuple[str, ...] = ()
    prescribed_form: str | None = None

    @property
    def needs_human(self) -> bool:
        return self.case_type is None or bool(self.alternatives)

    @property
    def route(self) -> str:
        return "ROUTE_MANUAL" if self.needs_human else "CLASSIFIED"

    def to_dict(self) -> dict:
        return {
            "case_type": self.case_type,
            "case_type_confidence": self.confidence,
            "case_type_evidence": self.evidence,
            "prescribed_form": self.prescribed_form,
            "prescribed_form_present": self.prescribed_form is not None,
            "alternatives": list(self.alternatives),
            "contradictions": list(self.contradictions),
            "route": self.route,
        }


def _signed(record: CaseRecord, doc_type: str) -> bool:
    doc = record.document(doc_type)
    return bool(doc and doc.present and doc.signatory_is_psa)


def _separate_b_iv(record: CaseRecord) -> tuple[str | None, str]:
    """Invalid pension or compulsory retirement? §4.1 rule 4.

    A Category-A medical board certificate countersigned by the Director General Health
    Services means invalid pension. Orders of compulsory retirement mean the penalty path.
    Neither present, or both, and the two are not separable from the file.
    """
    medical = record.has_document("MEDICAL_BOARD_CERTIFICATE", "INVALIDATION_CERTIFICATE")
    penalty = record.has_document("COMPULSORY_RETIREMENT_ORDER")
    if medical and not penalty:
        return INVALID_PENSION, (
            "Category-A invalidation certificate on file, countersigned by DG Health Services"
        )
    if penalty and not medical:
        return COMPULSORY_RETIREMENT_PENSION, "orders of compulsory retirement on file"
    return None, (
        "Form B-IV governs both invalid pension and compulsory retirement; the file carries "
        + ("both an invalidation certificate and compulsory-retirement orders"
           if medical and penalty else "neither an invalidation certificate nor "
           "compulsory-retirement orders")
    )


def _separate_b_i(record: CaseRecord) -> tuple[str | None, str]:
    """Superannuation or retiring pension? §4 rows 1 and 2.

    Both are Form B-I and both use ``CALC-01``, so a wrong call here does not change the
    arithmetic -- but it changes the trigger recorded on the case and the deadline the
    disposal dashboard measures against, so it is still separated rather than guessed.
    """
    years = record.stated_qualifying_service_years
    if record.has_document("VOLUNTARY_RETIREMENT_REQUEST"):
        return RETIRING_PENSION, "voluntary retirement request on file"
    if years is not None and years >= 25 and record.has_document("VOLUNTARY_RETIREMENT_ORDER"):
        return RETIRING_PENSION, f"voluntary retirement order with {years} years qualifying service"
    if record.has_document("SUPERANNUATION_ORDER"):
        return SUPERANNUATION_PENSION, "superannuation order on file"
    return None, (
        "Form B-I governs both superannuation and retiring (voluntary) pension; no "
        "superannuation order or voluntary-retirement request distinguishes them"
    )


def _infer_without_form(record: CaseRecord) -> CaseTypeResult:
    """No prescribed form located. §4.1 rules 2 and 3.

    Falls back to secondary evidence at reduced confidence, and always records the missing
    form as a contradiction so the checklist defect stays visible. A death certificate with a
    living claimant means family pension; the presence of the deceased's own PPO separates
    death-after-retirement (7b) from death-in-service (7a).
    """
    contradiction = (
        "No PSA-prescribed form (B-I/B-II/B-III/B-IV/D-I/D-II) was located in the bundle. "
        "This is a checklist defect, not a basis for reclassification (§4.1 rule 2)."
    )

    has_death = record.has_document("NADRA_DEATH_CERTIFICATE", "DEATH_CERTIFICATE")
    if has_death:
        has_ppo = record.has_document("PPO", "FPPO")
        case_type = (
            FAMILY_PENSION_DEATH_AFTER_RETIREMENT if has_ppo
            else FAMILY_PENSION_DEATH_IN_SERVICE
        )
        basis = (
            "death certificate on file with the deceased's own PPO, indicating death after "
            "retirement" if has_ppo else
            "death certificate on file with no PPO for the deceased, indicating death in service"
        )
        return CaseTypeResult(
            case_type=case_type,
            confidence=CONF_INFERRED,
            evidence=f"Inferred without a prescribed form: {basis} (§4.1 rule 3).",
            contradictions=(contradiction,),
            prescribed_form=None,
        )

    return CaseTypeResult(
        case_type=None,
        confidence=0.0,
        evidence="No prescribed form and no death certificate; the path is not determinable "
                 "from the bundle.",
        contradictions=(contradiction,),
        prescribed_form=None,
    )


def classify_case_type(record: CaseRecord) -> CaseTypeResult:
    """Derive the case type from the identified documents. §4.1, strongest evidence first.

    Returns a result whose ``case_type`` is ``None`` whenever the evidence does not separate
    the candidate paths. That is a routing outcome, not a failure: §4.1 rule 6 requires the
    case to reach a human rather than be guessed onto one of two formulas.
    """
    present_forms = [ft for ft in _FORM_TO_PATHS if record.has_document(ft)]

    if not present_forms:
        return _infer_without_form(record)

    contradictions: list[str] = []
    if len(present_forms) > 1:
        contradictions.append(
            "More than one PSA-prescribed form is present in the bundle: "
            f"{', '.join(present_forms)}. Only one path can govern the case."
        )
        return CaseTypeResult(
            case_type=None,
            confidence=0.0,
            evidence="Conflicting prescribed forms in one bundle.",
            alternatives=tuple(
                path for ft in present_forms for path in _FORM_TO_PATHS[ft]
            ),
            contradictions=tuple(contradictions),
        )

    form_type = present_forms[0]
    paths = _FORM_TO_PATHS[form_type]
    doc = record.document(form_type)
    signed = _signed(record, form_type)
    form_label = PRESCRIBED_FORM[paths[0]]

    if not signed:
        contradictions.append(
            f"Form {form_label} is present but not recorded as signed by the PSA. The form "
            f"still governs the case type (§4.1 rule 1); the signature is a checklist matter."
        )

    if len(paths) == 1:
        return CaseTypeResult(
            case_type=paths[0],
            confidence=CONF_SIGNED_FORM if signed else CONF_UNSIGNED_FORM,
            evidence=(
                f"{'Signed' if signed else 'Unsigned'} Form {form_label} at "
                f"{doc.page_ref}. The PSA form present in the file is decisive (§4.1 rule 1)."
            ),
            contradictions=tuple(contradictions),
            prescribed_form=form_label,
        )

    separator = _separate_b_iv if form_type == "FORM_B_IV" else _separate_b_i
    resolved, basis = separator(record)
    if resolved is None:
        return CaseTypeResult(
            case_type=None,
            confidence=0.0,
            evidence=(
                f"Form {form_label} at {doc.page_ref}, but {basis}. Routed to human "
                f"classification rather than guessed (§4.1 rule 6)."
            ),
            alternatives=paths,
            contradictions=tuple(contradictions),
            prescribed_form=form_label,
        )

    return CaseTypeResult(
        case_type=resolved,
        confidence=CONF_SIGNED_FORM if signed else CONF_UNSIGNED_FORM,
        evidence=(
            f"{'Signed' if signed else 'Unsigned'} Form {form_label} at {doc.page_ref}, "
            f"separated by {basis} (§4.1 rule 1 with rule "
            f"{'4' if form_type == 'FORM_B_IV' else '5'})."
        ),
        contradictions=tuple(contradictions),
        prescribed_form=form_label,
    )


# ==============================================================================================
# Whose CNIC is this? BRAIN §8.4 (identity), §5.3 (never invent).
# ==============================================================================================

def _name_key(name: str | None) -> set[str]:
    """Significant name tokens, lower-cased, honorifics dropped.

    Pakistani names on these documents vary in order and spelling -- "Mst. Nargas
    Waqar", "NARGIS WAQAR (LATE)", "Nargas Waqar" -- so matching is on the set
    of significant tokens rather than on the string.
    """
    if not name:
        return set()
    drop = {"mst", "mr", "mrs", "miss", "late", "s/o", "d/o", "w/o", "h/o", "the", "of"}
    tokens = {
        "".join(ch for ch in tok.lower() if ch.isalpha())
        for tok in str(name).replace("/", " ").split()
    }
    return {t for t in tokens if len(t) > 2 and t not in drop}


#: The marker a Punjab pension document prints beside the name of the servant who died.
#: Tested on the RAW name string, before ``_name_key`` tokenises it -- the tokeniser drops
#: "late" as an honorific, which is right for matching and useless for role resolution.
_LATE_MARKER = re.compile(r"\(\s*late\s*\)|\blate\b|\bmarhoom(?:a)?\b|\bdeceased\b", re.I)


@dataclass(frozen=True)
class Parties:
    """Who died and who is claiming, resolved from printed evidence rather than from labels.

    ``corrected`` records that the extraction had the two the wrong way round, and
    ``unresolved_reason`` that the evidence did not settle it. Both must reach the report:
    a role decided on a model's say-so, silently, is how one misread name becomes a letter
    addressed to the wrong person.
    """

    deceased: str | None
    claimant: str | None
    corrected: bool = False
    unresolved_reason: str | None = None


def resolve_parties(
    deceased_claimed: str | None,
    claimant_claimed: str | None,
    *,
    death_certificate_names: tuple[str, ...] = (),
) -> Parties:
    """Decide which extracted name is the deceased and which is the claimant.

    The schema asks the model for ``deceased_name`` and ``claimant_name``, and on the real
    file it returned them **swapped**: the deceased came back as "MR/MST. WAQAR ABDUL BASIT"
    (the surviving widower) and the claimant as "MR/MST. NARGAS WAQAR (LATE)" (the
    servant who died). Form D-I is a sanction "in respect of" the deceased while also naming
    the claimant, and that is enough to confuse the reading.

    The consequence is not a cosmetic label. These two names drive ``assign_cnic_roles``, so
    the bundle's single CNIC -- the widower's -- was filed as the deceased's. CL-06 (the
    deceased's CNIC) then read PRESENT, satisfied by the wrong person's card, and CL-07 (the
    claimant's) read MISSING though it was on the page. Two errors from one swap, and only
    one of them visible: the visible one sends the widower a letter demanding a card he
    already filed, and the invisible one means nobody ever asks for the card that is missing.
    The claimant name also goes on the letters themselves.

    Resolution order, strongest evidence first:

      1. the NADRA death certificate, which is authoritative on who died (§8.3), where its
         subject has been extracted;
      2. the "(LATE)" marker printed beside the deceased's name, when exactly one of the two
         carries it.

    Where neither settles it the labels are kept as given and ``unresolved_reason`` is set,
    because guessing between two people is worse than saying which step could not be taken.
    """
    dec_raw = (deceased_claimed or "").strip() or None
    cl_raw = (claimant_claimed or "").strip() or None
    if dec_raw is None or cl_raw is None:
        return Parties(dec_raw, cl_raw, False,
                       "only one party name was extracted, so the roles could not be "
                       "cross-checked against the record.")

    # 1. NADRA on who died.
    for subject in death_certificate_names:
        key = _name_key(subject)
        if not key:
            continue
        hits_dec, hits_cl = len(key & _name_key(dec_raw)), len(key & _name_key(cl_raw))
        if hits_cl > hits_dec:
            return Parties(cl_raw, dec_raw, True, None)
        if hits_dec > hits_cl:
            return Parties(dec_raw, cl_raw, False, None)

    # 2. The printed LATE marker, but only when it distinguishes the two.
    dec_late = bool(_LATE_MARKER.search(dec_raw))
    cl_late = bool(_LATE_MARKER.search(cl_raw))
    if cl_late and not dec_late:
        return Parties(cl_raw, dec_raw, True, None)
    if dec_late and not cl_late:
        return Parties(dec_raw, cl_raw, False, None)

    return Parties(
        dec_raw, cl_raw, False,
        f"Nothing on the papers says which of {dec_raw!r} and {cl_raw!r} is the deceased "
        f"and which is the claimant -- neither the death certificate nor a printed 'late' "
        f"marker tells them apart. The roles below are as first read, and unconfirmed.",
    )


def assign_cnic_roles(
    documents: tuple,
    deceased_name: str | None,
    claimant_name: str | None,
) -> tuple:
    """Re-label each generic ``CNIC`` document as the deceased's or the claimant's.

    The vision model is asked only for the name printed on the card, because whose card it is
    cannot be read off the card -- it depends on who the case is about. Asked to decide the
    role directly it got it wrong on the real file: page 34 is "CNIC Copy - Waqar Abdul Basit
    (claimant)" and came back ``CNIC_DECEASED``. That single misclassification caused two
    errors, only one of them visible: the claimant's CNIC requirement reported MISSING, and
    the deceased's reported PRESENT, satisfied by the wrong person's card.

    A card whose name matches neither, or both, stays ``CNIC``. It then satisfies no
    requirement and surfaces as a gap, which is the honest outcome: BRAIN §15.2's degradation
    path is flag and escalate, never guess.
    """
    from .caserecord import Document

    dec, cl = _name_key(deceased_name), _name_key(claimant_name)
    out = []
    for d in documents:
        if d.type != "CNIC":
            out.append(d)
            continue
        person = _name_key(getattr(d, "person_named", None))
        # Overlap counts rather than equality: one document prints a maiden name, another a
        # married name, and the shared tokens are what identify the person.
        hits_dec, hits_cl = len(person & dec), len(person & cl)
        if hits_dec > hits_cl and hits_dec:
            role = "CNIC_DECEASED"
        elif hits_cl > hits_dec and hits_cl:
            role = "CNIC_CLAIMANT"
        else:
            out.append(d)
            continue
        out.append(Document(
            type=role, pages=d.pages, present=d.present, signatory=d.signatory,
            signatory_is_psa=d.signatory_is_psa, attested=d.attested,
            countersigned_by=d.countersigned_by, defects=d.defects,
        ))
    return tuple(out)

# ==============================================================================================
# Which checklist column does this case belong to? Derived, not asked.
# ==============================================================================================

#: The prescribed form settles the case type, and the case type settles the checklist column --
#: except after a pensioner's death, where one form (D-II) serves seven different claimants and
#: only the claimant's relationship separates them.
#: Which office columns each pipeline path maps to, derived from the shared config.
_VARIANTS_FOR_CASE_TYPE: dict[str, tuple[str, ...]] = {
    pt: tuple(t["id"] for t in _CONFIG["case_types"] if pt in t["pipeline_types"])
    for pt in CASE_TYPES
}
_VARIANTS_FOR_CASE_TYPE = {k: v for k, v in _VARIANTS_FOR_CASE_TYPE.items() if v}


def variants_for_case_type(case_type: str | None) -> tuple[str, ...]:
    """The office checklist column(s) a case type runs on. An office type is its own column;
    a pipeline path maps to the columns that name it; empty where there is none."""
    if canonical_office_type(case_type):
        return (case_type,)
    key = canonical_case_type(case_type)
    return _VARIANTS_FOR_CASE_TYPE.get(key, ()) if key else ()


def declared_case_type_result(declared: str, detected: "CaseTypeResult | None" = None) -> CaseTypeResult:
    """The classification a DDO's declaration stands for.

    The office type names the pipeline path(s) the case may be. One path: that is the case
    type. Two (Fresh – Self is Form B-I, superannuation or retiring): the papers' own reading
    picks between them where it lands inside the declaration, else the first. None (a
    revision): whatever the papers read as. A declaration is not evidence read off the papers,
    so it does not borrow the form confidences; it is the DDO's statement, taken at face value
    for selecting the checklist and the rules, and checked against the papers by
    ``rules.flags.check_declared_case_type`` rather than overruled here.
    """
    key = canonical_office_type(declared)
    if key is None:
        raise KeyError(f"unknown case type {declared!r}; have {list(OFFICE_CASE_TYPES)}")
    allowed = pipeline_types_for(key)
    read = detected.case_type if detected else None
    if not allowed:
        path = read
    elif read in allowed:
        path = read
    else:
        path = allowed[0]
    return CaseTypeResult(
        case_type=path, confidence=1.0,
        evidence=f"Declared by the DDO at intake: {OFFICE_CASE_TYPE_LABELS[key]}"
                 + (f" ({case_type_label(path)})." if path else "."),
        prescribed_form=PRESCRIBED_FORM.get(path) if path else None,
    )

#: How a claimant's stated relationship maps onto a column, longest phrase first so
#: "widowed daughter" is not read as "widow".
_RELATION_TO_VARIANT: tuple[tuple[str, str], ...] = (
    ("DISABLED DAUGHTER", "DISABLED_CHILD_SIBLING"),
    ("DISABLED SON", "DISABLED_CHILD_SIBLING"),
    ("DISABLED SISTER", "DISABLED_CHILD_SIBLING"),
    ("DISABLED CHILD", "DISABLED_CHILD_SIBLING"),
    ("WIDOWED DAUGHTER", "WD_DAUGHTER"),
    # As the forms actually word them: "widow daughter of late ...", "divorce daughter".
    ("WIDOW DAUGHTER", "WD_DAUGHTER"),
    ("DIVORCED DAUGHTER", "DIVORCED_DAUGHTER"),
    ("DIVORCEE DAUGHTER", "DIVORCED_DAUGHTER"),
    ("DIVORCE DAUGHTER", "DIVORCED_DAUGHTER"),
    ("UNMARRIED DAUGHTER", "UNMARRIED_CHILD"),
    ("UNMARRIED SON", "UNMARRIED_CHILD"),
    ("WIDOWER OF", "WIDOW"),
    ("WIDOW OF", "WIDOW"),
    ("SISTER OF", "SISTER"),
    ("MOTHER OF", "PARENT"),
    ("FATHER OF", "PARENT"),
)


@dataclass(frozen=True)
class VariantSuggestion:
    """The checklist column the record points to, and how confidently.

    ``variant`` is set only where the evidence settles it. Where it narrows the field without
    deciding -- a Form D-II names the form but not which of seven claimants is filing --
    ``candidates`` carries what remains and the officer chooses from those rather than from
    all eleven.
    """

    variant: str | None
    candidates: tuple[str, ...]
    evidence: str

    @property
    def decided(self) -> bool:
        return self.variant is not None


#: Which daughter column a claimant falls in is decided by her marital status, and §8.3 makes
#: NADRA authoritative on exactly that. The forms print the relation as a bare "Daughter" far
#: more often than as "unmarried daughter", so without this the column could never be derived
#: and the case reached the officer with no checklist at all -- no required documents, no
#: verdict, nothing to act on.
#: What the relation clause itself says about marital status, where it says anything: real
#: forms print "um daughters" for an unmarried daughter and "wd daughter" for a widowed one.
_RELATION_SAYS_MARITAL: tuple[tuple[str, str], ...] = (
    ("UNMARRIED", "UNMARRIED_CHILD"), ("UM ", "UNMARRIED_CHILD"), ("UN ", "UNMARRIED_CHILD"),
    ("WIDOWED", "WD_DAUGHTER"), ("WD ", "WD_DAUGHTER"),
    ("DIVORC", "DIVORCED_DAUGHTER"),
)

_MARITAL_TO_DAUGHTER_COLUMN: tuple[tuple[str, str], ...] = (
    ("UNMARRIED", "UNMARRIED_CHILD"),
    ("SINGLE", "UNMARRIED_CHILD"),
    ("WIDOW", "WD_DAUGHTER"),
    ("DIVORC", "DIVORCED_DAUGHTER"),
)

#: The columns a bare "daughter" could be, in the order the office sheet lists them.
_DAUGHTER_COLUMNS = ("UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER")


def suggest_variant(
    case_type: str | None,
    form_text: str = "",
    alternatives: tuple[str, ...] = (),
    claimant_relation: str = "",
    claimant_marital: str = "",
    forwarding_subject: str = "",
) -> VariantSuggestion:
    """Derive the checklist column from the case type, narrowing by the claimant where needed.

    The form decides four of the eleven columns outright: Form B-I is a fresh self pension,
    B-IV an invalid one, D-I a death in service. Form D-II is where it stops being mechanical,
    because the same form serves a widow, an unmarried child, a parent and four other
    claimants, and what separates them is the relationship -- which the form itself usually
    prints, as in "IN RESPECT OF MST. GHULAM ZAINAB WIDOW OF AKBAR HUSSAIN".

    Returns a suggestion, never a decision. An officer confirms it, for the reason the 9
    September case showed: that bundle was filed as a death in service and is in fact a
    death after retirement, and running the wrong column asks a family for eight documents
    it does not need.
    """
    if not case_type:
        # An undecided case type is not always an undecided checklist column. Form B-I governs
        # both superannuation and retiring pension, so §4.1 rightly refuses to choose between
        # them -- and both are the same column on the office sheet. Where every remaining
        # candidate points to one column, the column is settled even though the case type is
        # not, and there is nothing to ask the officer.
        from_alts = {
            v for alt in alternatives for v in _VARIANTS_FOR_CASE_TYPE.get(alt, ())
        }
        if len(from_alts) == 1:
            only = from_alts.pop()
            return VariantSuggestion(
                only, (only,),
                f"the case type is undecided between {' and '.join(alternatives)}, but both "
                f"take the same checklist column",
            )
        if from_alts:
            return VariantSuggestion(
                None, tuple(sorted(from_alts)),
                f"the case type is undecided between {', '.join(alternatives)}, which take "
                f"different checklist columns",
            )
        return VariantSuggestion(None, (), "no case type could be derived from the bundle")
    candidates = _VARIANTS_FOR_CASE_TYPE.get(case_type, ())
    if not candidates:
        return VariantSuggestion(
            None, (),
            f"{case_type} has no column on the AG office checklist sheet",
        )
    if len(candidates) == 1:
        return VariantSuggestion(candidates[0], candidates, f"case type {case_type}")

    # The claimant's relation as stage 4 read it off the form is tried first: it is the one
    # clause that answers the question, where the form text as a whole opens on the WIDOW of
    # the pensioner even when the claimant is her divorced daughter -- which put the
    # divorced-daughter bundle on the widow's checklist.
    # The department's own subject line is read alongside the form. It is typed, it sits at
    # the head of the bundle, and it states what the department thinks it is forwarding --
    # "FAMILY PENSION PAPERS OF MISS. ASIA BIBI QURESHI (MENTALLY DISABLE DAUGHTER) AND MR.
    # MUHAMMAD HARIS QURESHI (MENTALLY DISABLED SON)". On that bundle the handwritten form
    # yielded a claimant relation of "Husband", the case went to the widow's column, and the
    # office was asked for a sole-widow certificate on a disabled children's claim.
    sources = (("the claimant's stated relation", claimant_relation),
               ("the department's forwarding letter", forwarding_subject),
               ("the prescribed form", form_text))

    def clean(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^A-Z ]+", " ", (text or "").upper()))

    for source, text in sources:
        haystack = clean(text)
        if not haystack.strip():
            continue
        for phrase, variant in _RELATION_TO_VARIANT:
            if phrase in haystack and variant in candidates:
                return VariantSuggestion(
                    variant, candidates,
                    f"case type {case_type}, and {source} states \"{phrase.lower()}\"",
                )

    # "Son, Disable" / "disable daughter" / "MENTALLY DISABLE DAUGHTER": the words need not
    # be adjacent, and the form spells it both "disable" and "disabled". Read across the
    # relation clause AND the forwarding letter, and BEFORE the bare-spouse fallback below:
    # a disabled child's claim is its own column on the office sheet, and a single word in a
    # handwritten relation box must not outrank the department's own statement of the claim.
    if "DISABLED_CHILD_SIBLING" in candidates:
        for source, text in sources[:2]:
            haystack = clean(text)
            if "DISABL" in haystack and re.search(
                    r"\b(SON|DAUGHTER|CHILD|SISTER|BROTHER)\b", haystack):
                return VariantSuggestion(
                    "DISABLED_CHILD_SIBLING", candidates,
                    f"case type {case_type}, and {source} reads "
                    f"\"{(text or '').strip()[:80]}\"",
                )

    # A bare "widow" / "w/o" in the relation clause, with no daughter wording anywhere in
    # it, is the spouse. Only the relation clause is read this loosely: in the form text
    # the word appears in every widow's, daughter's and re-grant's narrative alike.
    relation_hay = clean(claimant_relation)
    if "DAUGHTER" not in relation_hay and "SON" not in relation_hay.split() \
            and "WIDOW" in candidates \
            and re.search(r"\b(WIDOW|WIDOWER|W O|WIFE|HUSBAND)\b", relation_hay):
        return VariantSuggestion(
            "WIDOW", candidates,
            f"case type {case_type}, and the claimant's stated relation reads "
            f"\"{claimant_relation.strip()}\"",
        )
    # A bare "Daughter" or "Son". The relation is stated; only the marital status separates
    # the columns, so the NADRA record decides it where the bundle carries one and the field
    # is narrowed to the daughter columns where it does not.
    relation = re.sub(r"[^A-Z ]+", " ", (claimant_relation or "").upper())
    if re.search(r"\bDAUGHTERS?\b|\bD O\b", relation):
        for needle, variant in _RELATION_SAYS_MARITAL:
            if needle in f"{relation} " and variant in candidates:
                return VariantSuggestion(
                    variant, candidates,
                    f"case type {case_type}; the claimant's stated relation reads "
                    f"\"{claimant_relation.strip()}\"",
                )
        marital = re.sub(r"[^A-Z]+", "", (claimant_marital or "").upper())
        for needle, variant in _MARITAL_TO_DAUGHTER_COLUMN:
            if marital.startswith(needle) and variant in candidates:
                return VariantSuggestion(
                    variant, candidates,
                    f"case type {case_type}; the claimant is a daughter and the NADRA record "
                    f"states her as {claimant_marital.strip().lower()}",
                )
        narrowed = tuple(v for v in _DAUGHTER_COLUMNS if v in candidates)
        if narrowed:
            return VariantSuggestion(
                None, narrowed,
                f"case type {case_type}; the claimant is a daughter, but no marital status "
                f"was read for her and that is what separates the three daughter columns",
            )
    if re.search(r"\bSONS?\b|\bS O\b", relation) and "UNMARRIED_CHILD" in candidates:
        return VariantSuggestion(
            "UNMARRIED_CHILD", candidates,
            f"case type {case_type}; the claimant is a son, and the office sheet has one "
            f"column for a child's claim",
        )

    return VariantSuggestion(
        None, candidates,
        f"case type {case_type}; the form does not state which family member is claiming, "
        f"so the column must be chosen from the {len(candidates)} it could be",
    )

#: Honorifics that precede a name on these forms and are not part of it.
#: The honorific, and the placeholder a blank form prints in its place. The prescribed forms
#: carry "MST/MR ......" with the name written after the dots, so the dots have to be stepped
#: over or the name is never reached.
_HONORIFIC = (
    r"(?:MST\s*/\s*MR|MR\s*/\s*MST|MST|MRS|MR|MISS|MS|SYED|SYEDA|MUSAMMAT|MUHTARMA)"
    r"\.?\s*(?:[./\s]*\.{2,}\s*)?"
)

#: "IN RESPECT OF <claimant> <relationship> OF <deceased>". The prescribed form states who
#: the case is for in its own subject line, which is the most authoritative statement of the
#: claimant in the bundle -- it is the sentence the PSA signed.
_IN_RESPECT_OF = re.compile(
    r"IN\s+RESPECT\s+OF\s+(?:" + _HONORIFIC + r")?"
    r"(?P<name>[A-Z][A-Z .]{3,60}?)\s+"
    # A qualifier belongs to the relationship, not to the name: "SANA BIBI UNMARRIED
    # DAUGHTER OF ..." names Sana Bibi, not Sana Bibi Unmarried.
    r"(?:(?:UN-?MARRIED|WIDOWED|DIVORCED|DISABLED|REAL)\s+)?"
    r"(?:WIDOW|WIDOWER|SON|DAUGHTER|SISTER|BROTHER|MOTHER|FATHER|W/O|S/O|D/O)\b",
    re.I,
)


#: Words that can sit where a name sits in that sentence and are not one.
#: Ranks and posts that precede a name on these forms. Trimmed only while at least two words
#: would remain, so a short genuine name is never eaten by a word that merely looks like a post.
_DESIGNATION = {"SUB", "INSPECTOR", "CONSTABLE", "HEAD", "ASSISTANT", "SENIOR", "JUNIOR",
                "PRINCIPAL", "CLERK", "OFFICER", "SUPERINTENDENT", "DEPUTY", "ADDITIONAL",
                "DIRECTOR", "SECRETARY", "TEACHER", "LECTURER", "PROFESSOR", "DRIVER",
                "NAIB", "QASID", "CHOWKIDAR", "SEPOY", "EX"}

_NOT_A_NAME = {"THE", "LATE", "SAID", "ABOVE", "DECEASED", "PENSIONER", "APPLICANT",
               "GOVERNMENT", "SERVANT", "WIDOW", "FAMILY",
               # printed form vocabulary that follows the name on a sanction form and would
               # otherwise be read as part of it: "... WAQIAR ABDUL BASIT Notification /
               # Order No: ..." must not yield a claimant called "Ala Notification".
               "NOTIFICATION", "ORDER", "ORDERS", "SUBJECT", "DATED", "DATE", "SIR",
               "MADAM", "REF", "REFERENCE", "MEMO", "NO", "SANCTION", "GRANT", "PENSION",
               "GRATUITY", "RESPECT", "RETIRED", "EX", "DESIGNATION", "SCALE", "OFFICE"}


_IN_RESPECT_OF_BARE = re.compile(
    r"IN\s+RESPECT\s+OF\s+(?:" + _HONORIFIC + r")?(?P<name>[A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]{2,}){1,3})",
)

#: How the grade is written, in the places it is written. "BS-19" and "BPS 19" appear on a
#: sanction form; a Last Pay Certificate instead prints a sentence with the number filled
#: into a blank -- "entitled to draw the following scale of pay __14__" -- which the first
#: two patterns do not see at all, so the LPC's grade was invisible to the checklist.
#: Note the trailing ``(?!\d)`` rather than ``\b``. The LPC prints the grade into a ruled
#: blank -- "scale of pay __14__" -- and an underscore is a WORD character, so a word
#: boundary after the digits never matches and the number was invisible. What is actually
#: wanted is "no further digit", which is what this says.
_PAY_SCALE_PATTERNS = (
    re.compile(r"\bB\.?\s?S\.?\s*-?\s*(\d{1,2})(?!\d)", re.I),
    re.compile(r"\bBPS\s*-?\s*(\d{1,2})(?!\d)", re.I),
    re.compile(r"\bSCALE\s+OF\s+PAY\s*[-_:.\s]{0,8}(\d{1,2})(?!\d)", re.I),
    re.compile(r"\bPAY\s+SCALE\s*[-_:.\s]{0,8}(\d{1,2})(?!\d)", re.I),
)


def pay_scale_from_form(form_text: str) -> int | None:
    """The servant's grade, from the prescribed form's own text.

    The checklist needs this to know whether a service book or an AG service statement is the
    record to ask for, and it was reading it from the determination -- which is produced two
    stages later and not at all for a case the engine cannot compute. A clean run therefore
    reported BOTH service records missing on a BS-19 officer, because the grade had not been
    established yet. The grade is printed on the sanction form; a document check should not
    wait on a calculation to read it.
    """
    for pattern in _PAY_SCALE_PATTERNS:
        for found in pattern.findall(form_text or ""):
            grade = int(found)
            # Punjab runs BS-1 to BS-22. Anything else is a page number, a year or a
            # misread, and guessing a grade decides which service record the office
            # demands -- so an out-of-range figure is ignored, not clamped.
            if 1 <= grade <= 22:
                return grade
    return None


def claimant_from_form(form_text: str) -> str | None:
    """The claimant, as the prescribed form's own subject line names them.

    Needed because the claimant otherwise reaches the record only through stage 4, which reads
    Form D-I -- and a case filed on Form B-I or D-II has no Form D-I to read. On the widow's
    case that left ``claimant_name`` unset, and the Nikah Nama condition ("required only where
    the applicant is not shown in the FRC") could not be evaluated at all: the FRC had been
    read, the widow was in it, and the case was still returned for a marriage certificate.

    Returns ``None`` rather than a guess. A name that cannot be read off the form is better
    absent than wrong -- it decides whose CNIC satisfies which line.
    """
    text = re.sub(r"\s+", " ", form_text or "")
    m = _IN_RESPECT_OF.search(text)
    if not m:
        # A sanction form often names the claimant with no relationship clause after it --
        # "IN RESPECT OF MST/MR ... WAQIAR ABDUL BASIT" and then the notification number.
        # Take the run of name-shaped words and stop at the first thing that is not one.
        m = _IN_RESPECT_OF_BARE.search(text)
    if not m:
        return None
    name = re.sub(r"\s+", " ", m.group("name")).strip(" .")
    # Trim form vocabulary from the right, and rank or designation from the left. A sanction
    # form names the person by post as well as name -- "IN RESPECT OF SUB INSPECTOR JAMSHAID
    # ULLAH" -- and the post is not part of the name that goes on a letter.
    words = name.split()
    while words and words[-1].upper().strip(".") in _NOT_A_NAME:
        words.pop()
    while len(words) > 2 and words[0].upper().strip(".") in _DESIGNATION:
        words.pop(0)
    name = " ".join(words)
    # One word can be a whole name, so a length test alone would drop real claimants; what it
    # must not admit is a stray fragment of the surrounding sentence.
    if not words or all(w.upper().strip(".") in _NOT_A_NAME for w in words):
        return None          # "THE LATE", "THE SAID WIDOW" -- sentence, not a name
    if len(words) == 1 and len(name) < 4:
        return None
    return name.title()

#: The event that starts a pension entitlement, as the prescribed forms state it: a servant
#: who "expired on 03.07.2026" or "Retired at 27-02-2026". This is the date the office counts
#: three years from when it asks why a case was submitted late.
#: Any inflection of the entitling event, then the date. The window allows the words that
#: sit between them on real forms -- "Superannuation retirement from Govt. Service with
#: effect from 18-02-2026" puts forty characters in the way -- but permits NO DIGIT inside
#: it, so an intervening number ends the match rather than letting the pattern reach across
#: the page to an unrelated date. A sanction form carries half a dozen dates.
_ENTITLEMENT_DATE = re.compile(
    r"(?:retir\w*|superannuat\w*|expir\w*)[^0-9\n]{0,60}?"
    r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})",
    re.I,
)


def entitlement_date_from_form(form_text: str) -> date | None:
    """When the servant died or retired, from the sanction form's own words.

    Item 19 of the office checklist asks for a reason for late submission "if more 3 years",
    and three years has to run from something. It runs from the event that created the
    entitlement, which every prescribed form states: Form D-I and D-II record when the
    servant expired, Form B-I when they retired on superannuation.

    ``None`` where the form does not say. The requirement then stands, because a case whose
    age cannot be established is not a case known to be recent.
    """
    # The anchored readings first: the retirement sentence on Form B-I, the "expired on"
    # clause on Forms D-I / D-II. The loose pattern below is the fallback, and on a Form B-I
    # it has taken the application date for the retirement date.
    anchored = dates_from_form(form_text).get("date_of_retirement") or death_date_from_form(form_text)
    if anchored is not None:
        return anchored
    m = _ENTITLEMENT_DATE.search(re.sub(r"\s+", " ", form_text or ""))
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    if not (1 <= day <= 31 and 1 <= month <= 12 and 1940 <= year <= 2100):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None

#: Dates the sanction form states about the servant, each anchored to the words beside it so
#: a form quoting several dates does not yield the wrong one.
_FORM_FACTS = {
    # "Day of Birth" is how PaddleOCR read one Form B-I; the anchor tolerates it.
    "date_of_birth": re.compile(
        r"da[ty]e?\s+of\s+birth\D{0,20}?(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", re.I),
    "date_first_entry": re.compile(
        r"(?:1st|first)\s+entry\D{0,40}?(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", re.I),
    # Form B-I: "shall stand retired from Government service on superannuation 01-06-2026",
    # "retired from Government Service on.23.10.2025 A/N", "retired ... on 18-02-2026 (A.N)".
    # Anchored to the retirement sentence, because the same form prints the notification
    # date and the application date within sixty characters of the word "retiring", and the
    # loose entitlement pattern took the application date (30-12-2025) for a servant who
    # retired on 01-06-2026.
    "date_of_retirement": re.compile(
        r"(?:retired?\s+from\s+government\s+service\s+on\W{0,4}(?:superannuation\W{0,4})?"
        r"|date\s+of\s+retirement\D{0,20}?)"
        r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", re.I),
}

#: Form D-I / D-II: "expired on 28-2-21", "expired on 8-04-2015". Two-digit years occur on the
#: handwritten forms. They used to be read as 20xx; since 7 Oct 2026 (audit L1) a two-digit
#: year yields NO date -- the century is the reader's guess, not the form's statement -- and
#: the clause is reported through ``ambiguous_death_date_from_form`` so an officer confirms the
#: date against the death certificate and keys it at intake.
_DEATH_DATE = re.compile(
    r"expired\s+on\W{0,4}(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})", re.I)

#: A day-first date whose year has two digits, anywhere in a short value: "28-2-21", "6/3/26",
#: "02.10.25". Four-digit years do not match (the year group is bounded on both sides).
_TWO_DIGIT_YEAR = re.compile(r"(?<!\d)(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2})(?!\d)")


def two_digit_year(text: str | None) -> str | None:
    """The ``dd-mm-yy`` written in ``text``, or None where its year has four digits or there is
    no date. Readers call this to say WHY they returned nothing, so the century is confirmed by
    a person rather than guessed by the code."""
    m = _TWO_DIGIT_YEAR.search(str(text or ""))
    return m.group(0) if m else None


def death_date_from_form(form_text: str) -> date | None:
    """The date the servant or pensioner died, from the form's own "expired on" clause.

    None where the clause is absent, is not a calendar date, or writes the year with two
    digits (see ``ambiguous_death_date_from_form``)."""
    m = _DEATH_DATE.search(re.sub(r"\s+", " ", form_text or ""))
    if not m:
        return None
    if len(m.group(3)) < 4:
        return None
    day, month, year = (int(g) for g in m.groups())
    if not (1 <= day <= 31 and 1 <= month <= 12 and 1940 <= year <= 2100):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def ambiguous_death_date_from_form(form_text: str) -> str | None:
    """The "expired on" date as written, where its year has only two digits ("28-2-21").

    The pipeline puts this in front of the officer instead of a date: "21" is 2021 to anyone
    who knows the case and 1921 to the code, and the commencement of a family pension and the
    lateness of the submission both run from it."""
    m = _DEATH_DATE.search(re.sub(r"\s+", " ", form_text or ""))
    if not m or len(m.group(3)) >= 4:
        return None
    return "-".join(m.groups())


#: Money the prescribed forms print beside a fixed label. OCR text, not a model's field:
#: the second, independent reading SOP §6.3(9) asks for, and the one that is left when the
#: vision read files the pension under the wrong name (the Widow Daughter bundle's
#: "drawing Pension @ Rs.19,874/-" came back as pay_scale_printed).
_FORM_MONEY = {
    "pension_drawn_rs": re.compile(
        r"drawing\s+(?:family\s+)?pension\s*(?:/\s*family\s+pension\s*)?(?:@|of|at)?\s*"
        r"(?:rs\.?\s*)?([\d,]{3,}(?:\.\d+)?)\s*/?-?\s*(?:p\.?m|per\s+month)?", re.I),
    "net_pension_rs": re.compile(
        r"net\s+pension\W{0,6}(?:rs\.?\s*)?([\d,]{3,}(?:\.\d+)?)", re.I),
    "total_pension_rs": re.compile(
        r"total\s+pension\W{0,6}(?:rs\.?\s*)?([\d,]{3,}(?:\.\d+)?)", re.I),
    "average_basic_pay_rs": re.compile(
        r"(?:total\s+)?average\s+(?:basic\s+)?pay\W{0,6}(?:rs\.?\s*)?([\d,]{4,}(?:\.\d+)?)", re.I),
    # Form B-I: "(1) Basic Pay Rs.89090/=", "i. Basic Pay .....17404.", and in the narrative
    # "drawing pay Rs. 60810/-". The LAST-DRAWN pay, not the three-year average.
    "basic_pay_rs": re.compile(
        r"\bbasic\s+pay\b(?!\s+including)\W{0,10}(?:rs\.?\s*)?([\d,]{4,}(?:\.\d+)?)", re.I),
    "drawing_pay_rs": re.compile(
        r"drawing\s+pay\W{0,6}(?:rs\.?\s*)?([\d,]{4,}(?:\.\d+)?)", re.I),
}


def printed_form_figures(form_text: str) -> dict:
    """Rupee figures the sanction form prints beside its own labels, as Decimal strings.

    A label matched more than once with different figures is dropped -- a form quoting two
    "net pensions" is not one this reader may choose between -- and a figure under 100
    rupees is noise, not a pension.
    """
    text = re.sub(r"\s+", " ", form_text or "")
    out: dict = {}
    for name, pattern in _FORM_MONEY.items():
        values = set()
        for m in pattern.finditer(text):
            raw = m.group(1).replace(",", "")
            try:
                v = float(raw)
            except ValueError:
                continue
            if v >= 100:
                values.add(raw.rstrip("0").rstrip(".") if "." in raw else raw)
        if len(values) == 1:
            out[name] = values.pop()
    return out


def dates_from_form(form_text: str) -> dict:
    """Date of birth and date of first entry, from the sanction form's own text.

    Stage 4 reads these from Form D-I, and a self pension has no Form D-I -- so on a
    superannuation case they never reached the record and qualifying service could not be
    computed at all. Annex-B-1 states both: "(a) His date of birth is 28-02-1966 (b) Date of
    1st entry in Govt. Service 01-11-1987".

    Each pattern is anchored to the words printed beside the date. A sanction form carries
    half a dozen dates -- notification, retirement, entry, birth -- and an unanchored search
    would take whichever came first.
    """
    text = re.sub(r"\s+", " ", form_text or "")
    out: dict = {}
    for name, pattern in _FORM_FACTS.items():
        m = pattern.search(text)
        if not m:
            continue
        day, month, year = (int(g) for g in m.groups())
        if 1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2100:
            try:
                out[name] = date(year, month, day)
            except ValueError:
                pass
    return out

