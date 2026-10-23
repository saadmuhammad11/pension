"""The cross-document check battery and the flag taxonomy. BRAIN §8.

"This is where the system earns its value. Checklist completeness is mechanical; catching a
contradiction across 46 pages is what a human takes hours to do and misses."

The battery is deterministic and runs over the ``CaseRecord``. Every check here corresponds to
a real defect observed in a real file, and two of them are the ones BRAIN §13.8 singles out:
missing **F-3** (a recovery the sanction form denies) is "the one that costs money"; missing
**F-2** (an attested family record contradicting NADRA) is "the one a human eye skips".

Precedence, not averaging
-------------------------
When two documents disagree the battery does not average them and does not prefer the clearer
scan. §8.3 fixes an order of authority grounded in who owns the fact: NADRA owns identity and
family; payroll owns pay and personnel numbers; the LPC owns recoveries; the Pension Rules own
entitlement. A department typing a personnel number onto a sanction form is *restating*; the
payroll system is the fact.

Two consequences the checks encode explicitly:

*   **An attested document can be wrong.** Attestation certifies that a copy matches an
    original or that a declarant signed -- not that the content is true.
*   **Where the authoritative source contradicts the legally operative document, both
    matter.** Annex-A listing a married son as an unmarried daughter does not change the
    entitlement (the spouse precedes children, ``ENT-07``), and the flag is still HIGH,
    because Annex-A is the attested declaration the sanction rests on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .caserecord import CaseRecord, Source
from .engine import SELF_PENSION_KINDS
from .checklist import SELF_PENSION_VARIANTS
from .loader import RulePack
from .money import fmt

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

_SEVERITY_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}

#: Document types in the words the office uses, for the text an officer reads. The schema
#: names (``CNIC_CLAIMANT``, ``NADRA_FRC``) stay in the evidence, where a machine reads them;
#: a finding that says "p.4 (CNIC_CLAIMANT)" is asking a clerk to learn our constants.
_DOC_WORDS = {
    "CNIC": "CNIC", "CNIC_CLAIMANT": "claimant's CNIC", "CNIC_DECEASED": "deceased's CNIC",
    "NADRA_FRC": "family certificate", "NADRA_DEATH_CERTIFICATE": "death certificate",
    "SALARY_STATEMENT": "salary statement", "ANNEX_A": "Annex-A",
    "FORM_B_I": "Form B-I", "FORM_D_I": "Form D-I", "FORM_D_II": "Form D-II",
    "SUCCESSION_CERTIFICATE": "succession certificate", "LPC": "last pay certificate",
    "PPO": "PPO", "SERVICE_BOOK": "service book", "BANK_OPTION_FORM": "bank option form",
    "QUALIFYING_SERVICE_PROFORMA": "proforma for qualifying service",
    "DESCRIPTIVE_ROLL": "descriptive roll", "PENSION_SLIP": "pension slip",
}


def _doc_words(doc_type: str) -> str:
    return _DOC_WORDS.get(doc_type, (doc_type or "").replace("_", " ").lower())


def _first_sentence(text: str, limit: int = 110) -> str:
    """The first sentence of a diagnostic line, for a reader who is not debugging it.

    The reader's own message says things like "24 pay rows were read with labels but only 0
    carry an amount. Rejected: [...]" -- true, useful in a log, and not what an officer needs
    in the middle of a finding. The whole line stays in the artefacts.
    """
    head = (text or "").strip().split(". ")[0].strip().rstrip(".")
    if ": " in head and len(head.split(": ", 1)[0]) < 24:      # drop a "p010-10.png: " prefix
        head = head.split(": ", 1)[1]
    return (head[:limit].rstrip() + "…") if len(head) > limit else head

CONTRA_IDENTITY = "CONTRA-IDENTITY"
CONTRA_FAMILY = "CONTRA-FAMILY"
CONTRA_MONEY = "CONTRA-MONEY"
CONTRA_DATE = "CONTRA-DATE"
CONTRA_SERVICE = "CONTRA-SERVICE"
#: Service at death under the minimum the rules set for a monthly pension (decision H3, 7 Oct 2026).
SERVICE_SHORT = "SERVICE-SHORT"
RULE_CAP = "RULE-CAP"
RULE_UNDECLARED = "RULE-UNDECLARED"
AUTH_DEFECT = "AUTH-DEFECT"
SLA_BREACH = "SLA-BREACH"
ALIAS_RESOLVED = "ALIAS-RESOLVED"
SCOPE_CONFUSION = "SCOPE-CONFUSION"
EXTRACT_LOWCONF = "EXTRACT-LOWCONF"
#: Two reads of one page disagreed; nothing from it was used (decision H1, 7 Oct 2026).
EXTRACT_DISAGREE = "EXTRACT-DISAGREE"
EXTRACT_ROLE_SWAP = "EXTRACT-ROLE-SWAP"
CNIC_UNCORROBORATED = "CNIC-UNCORROBORATED"
DOC_STALE = "DOC-STALE"
DOC_EXPIRED = "DOC-EXPIRED"
#: A date whose year is written with two digits; the century is for a person to confirm (L1).
DATE_AMBIGUOUS = "DATE-AMBIGUOUS"
SELF_PENSION_REFUSED = "CONTRA-SERVICE-DATES"
ATTEST_MISSING = "ATTEST-MISSING"
#: Stage 6 did not run, so no check that needs two documents to disagree ran either (C-03).
CROSS_CHECKS_NOT_RUN = "CROSS-CHECKS-NOT-RUN"
#: A sanction signature an officer is asked to compare with the department's specimen by eye.
SPECIMEN_CHECK = "SPECIMEN-CHECK"
#: The relationship that entitles the claimant is proved by no document in the bundle.
RELATIONSHIP_UNPROVED = "RELATIONSHIP-UNPROVED"
#: The claimant's stated relation is not on the DRAFT list of eligible relations, or fails one of
#: its conditions on the papers (H6). Advisory: a check for the reviewer, never a hard stop, until
#: the rules owner confirms the list (decision of 7 Oct 2026).
RELATION_INELIGIBLE = "RELATION-INELIGIBLE"

#: The sanction forms the party names are read from, and the certificate that settles who
#: died -- the pages a finding about the roles or the stated service opens.
PRESCRIBED_FORMS = ("FORM_D_I", "FORM_D_II", "FORM_B_I", "FORM_B_II", "FORM_B_III", "FORM_B_IV")
DEATH_CERTIFICATES = ("NADRA_DEATH_CERTIFICATE", "DEATH_CERTIFICATE")
#: The department declared one case type and the papers read as another (29 Sep 2026).
DECLARED_TYPE_MISMATCH = "DECLARED-TYPE-MISMATCH"

#: The columns office checklist item 22 asked a Nikah Nama on (now check_nikah_nama).
NIKAH_NAMA_VARIANTS = frozenset({"DEATH_IN_SERVICE", "WIDOW", "WD_DAUGHTER",
                                 "DIVORCED_DAUGHTER", "SISTER"})


#: §8.3, as data. Earlier document types win. A type absent from a list carries no authority
#: over that fact and is treated as a restatement.
PRECEDENCE: dict[str, tuple[str, ...]] = {
    "identity": ("NADRA_CNIC", "NADRA_FRC", "NADRA_DEATH_CERTIFICATE", "CNIC_DECEASED",
                 "CNIC_CLAIMANT"),
    "personnel_no": ("SAP_PAYROLL", "LPC", "SALARY_STATEMENT", "SERVICE_STATEMENT",
                     "BANK_OPTION_FORM", "NDC"),
    "pay": ("SAP_PAYROLL", "LPC", "SALARY_STATEMENT"),
    "service_history": ("SERVICE_BOOK", "SERVICE_STATEMENT", "QUALIFYING_SERVICE_PROFORMA"),
    "recovery": ("LPC",),
    "pension_in_payment": ("PPO", "FPPO"),
}

#: Which precedence list governs which extracted field.
#: Facts a case has ONE of, so two values is a contradiction. Compared case-wide.
#:
#: CNIC is deliberately absent. A case has many CNICs -- the deceased's, the claimant's,
#: each child's on the FRC, two witnesses on the bank form, the oath commissioner's on the
#: affidavit -- and comparing them case-wide called every ordinary bundle a mismatch. It is
#: checked per PERSON instead, in check_cnic_consistency, which is the question actually
#: worth asking: is one person's number the same wherever this case quotes it.
_FIELD_AUTHORITY: dict[str, str] = {
    "personnel_no": "personnel_no",
    "date_of_birth": "identity",
    "name": "identity",
    "date_of_death": "identity",
}


@dataclass(frozen=True)
class Flag:
    """One finding. Mirrors the §6 ``flags`` schema entry."""

    id: str
    severity: str
    flag_class: str
    title: str
    finding: str
    required_action: str
    owner: str
    asserted: tuple[Source, ...] = ()
    contradicted_by: tuple[Source, ...] = ()
    affects_determination: bool = False
    #: The specimen a sanction signature is to be compared with, and the signature cut from
    #: the form, for the side-by-side the officer compares (check_psa_specimen). None elsewhere.
    specimen: dict | None = None
    #: The finding in one plain sentence of at most 15 words (rules.flag_curation), for the screen.
    summary: str = ""

    @property
    def blocks_ppo(self) -> bool:
        """HIGH blocks PPO issuance; nothing else does. §8.1.

        Derived rather than stored: a HIGH flag that did not block, or a LOW one that did,
        would be a silent inconsistency between the severity shown to an officer and the
        behaviour of the workflow.
        """
        return self.severity == HIGH

    def to_dict(self) -> dict:
        out = {
            "id": self.id,
            "severity": self.severity,
            "class": self.flag_class,
            "title": self.title,
            "finding": self.finding,
            "evidence": {
                "asserted": [{"page": s.page, "doc": s.document} for s in self.asserted],
                "contradicted_by": [
                    {"page": s.page, "doc": s.document} for s in self.contradicted_by
                ],
            },
            "affects_determination": self.affects_determination,
            "blocks_ppo": self.blocks_ppo,
            "required_action": self.required_action,
            "owner": self.owner,
            **({"specimen": self.specimen} if self.specimen else {}),
            **({"summary": self.summary} if self.summary else {}),
        }
        # The exact finding, independent of its position in the list (decision H8, 7 Oct 2026):
        # a waiver is tied to this, not to "F-2".
        out["rule_id"] = self.flag_class
        out["fingerprint"] = finding_fingerprint(out)
        return out


_PAGE_REF = re.compile(r"\bpp?\.\s*#?\d*(?:\s*[-–]\s*\d+)?", re.I)


def _finding_text_key(text: str | None) -> str:
    """A finding's words without page numbers or spacing differences: the same finding on a
    renumbered page is the same finding; a changed amount, date or name is not."""
    return " ".join(_PAGE_REF.sub(" ", str(text or "")).casefold().split())


def finding_fingerprint(flag: dict) -> str:
    """What a waiver is tied to: the rule (the finding's class), the documents it cites, and the
    title and finding text, which carry the field and the value. Pages and the running number
    are left out, so a re-check that renumbers pages keeps the waiver and one that changes a
    figure, a date or a name lapses it (business decision H8, 7 Oct 2026)."""
    import hashlib
    ev = flag.get("evidence") or {}
    docs = lambda side: sorted({str(e.get("doc") or e.get("document") or "") for e in ev.get(side) or []})
    material = "\x1f".join([
        str(flag.get("class") or flag.get("rule_id") or ""),
        _finding_text_key(flag.get("title")),
        _finding_text_key(flag.get("finding")),
        "|".join(docs("asserted")),
        "|".join(docs("contradicted_by")),
    ])
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _pages(sources: tuple[Source, ...]) -> str:
    return ", ".join(f"p.{s.page}" for s in sorted(sources, key=lambda s: s.page))


def _doc_sources(record: CaseRecord, *doc_types: str) -> tuple[Source, ...]:
    """The located pages of the named documents, as sources a finding can cite.

    For a finding about a document rather than a single statement on it -- the roles were
    read from the form, the relationship is not on the family certificate -- the page to
    open is the document itself. A finding that cites no page leaves the officer to hunt
    for the paper in a fifty-page bundle, so a document present but not located cites
    nothing rather than guessing.
    """
    out: list[Source] = []
    for d in record.documents:
        if d.type in doc_types and d.present:
            out.extend(Source(page, d.type) for page in d.pages)
    return _dedupe(tuple(out))


def _dedupe(sources: tuple[Source | None, ...]) -> tuple[Source, ...]:
    seen: list[Source] = []
    for s in sources:
        if s is not None and s not in seen:
            seen.append(s)
    return tuple(seen)


#: Display labels. str.title() mangles the acronyms these strings are full of -- "PSA_SANCTION"
#: becomes "Psa Sanction" -- and these strings go verbatim into shortcoming letters sent to a
#: department, so they are written out rather than derived.
_FIELD_LABELS = {
    "personnel_no": "Personnel-number",
    "cnic": "CNIC",
    "date_of_birth": "Date-of-birth",
    "name": "Name",
    "date_of_death": "Date-of-death",
}

_EVENT_LABELS = {
    "ANNEX_A_SIGNED": "Annex-A signed",
    "PSA_SANCTION": "PSA sanction",
    "FORWARDED_TO_AG": "forwarded to the AG",
    "RECEIVED_AT_AG": "received at the AG",
    # Named for what the page actually evidences: the department certifying, in its letter of
    # transfer, that the sanction had been signed. Form D-I's signature block is undated, so
    # "PSA sanction" would claim a date the record does not carry.
    "SANCTION_FORWARDED_TO_AG": "transfer of the signed sanction to the AG",
    "FORM_D_I_NOTIFIED": "Form D-I notification date",
    "FRC_ISSUED": "NADRA FRC issued",
    "CNIC_CLAIMANT_EXPIRES": "claimant's CNIC expires",
    "CNIC_DECEASED_EXPIRES": "deceased's CNIC expires",
}


def _field_label(field_name: str) -> str:
    return _FIELD_LABELS.get(field_name, field_name.replace("_", " ").capitalize())


def _event_label(event: str) -> str:
    return _EVENT_LABELS.get(event, event.replace("_", " ").lower())


def _sentence(text: str) -> str:
    """Capitalise the first character only.

    str.capitalize() lowercases everything after it, which turns "PSA sanction" into
    "Psa sanction" and "Annex-A signed" into "Annex-a signed" -- in text that goes to a
    department over the AG's name.
    """
    return text[:1].upper() + text[1:] if text else text


def _authority_rank(doc_type: str, kind: str) -> int:
    order = PRECEDENCE.get(kind, ())
    return order.index(doc_type) if doc_type in order else len(order)


# -- the checks --------------------------------------------------------------------------------
# Each returns flags without ids; run_battery assigns F-n after sorting by severity.


def check_identity_consistency(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """Same person, different identifiers across documents. ``CONTRA-IDENTITY``.

    Resolves by §8.3 precedence rather than by counting sources. Counting would usually
    give the same answer on the golden case (five documents against two) but would be wrong
    in principle and wrong in a file where a department restated an error onto several
    forms: a restatement repeated five times is still a restatement.
    """
    flags: list[Flag] = []
    for field_name, kind in _FIELD_AUTHORITY.items():
        values = record.distinct_values(field_name)
        if field_name == "personnel_no":
            # A Punjab personnel number is eight digits. Anything else is a misread -- or a
            # different number read into the field -- not a second identity: 56e5 raised a
            # HIGH mismatch on "839923865", which p.14 does not print at all.
            values = {v: s for v, s in values.items() if len(v) == 8 and v.isdigit()}
        if len(values) < 2:
            continue

        ranked = sorted(
            values.items(),
            key=lambda kv: min(_authority_rank(s.document, kind) for s in kv[1]),
        )
        authoritative_value, authoritative_sources = ranked[0]
        challenged = ranked[1:]
        challenged_values = " / ".join(v for v, _ in challenged)
        challenged_sources = tuple(s for _, srcs in challenged for s in srcs)

        best_doc = min(
            authoritative_sources, key=lambda s: _authority_rank(s.document, kind)
        ).document
        label = _field_label(field_name)

        flags.append(
            Flag(
                id="",
                severity=HIGH,
                flag_class=CONTRA_IDENTITY,
                title=f"{label} mismatch: {challenged_values} vs {authoritative_value}",
                finding=(
                    f"The {label.lower()} is {challenged_values} at "
                    f"{_pages(challenged_sources)} but {authoritative_value} at "
                    f"{_pages(authoritative_sources)}. The {_doc_words(best_doc)} decides it, "
                    f"so {authoritative_value} is the right one."
                ),
                asserted=challenged_sources,
                contradicted_by=authoritative_sources,
                affects_determination=False,
                required_action=(
                    f"Verify against the SAP HR master; correct the {label.lower()} on the "
                    "prescribed form and cover before PPO."
                ),
                owner="DEPARTMENT",
            )
        )
    return flags


def frc_spouse_pair(frc_family: tuple) -> tuple | None:
    """The married couple a child-headed FRC names, or ``None``. ``FRC-03``, ``FRC-04``.

    On an FRC written from a child's seat the ``Father`` row and the ``Mother`` row are that
    child's parents, so they are married to each other -- and NADRA is the authority for
    that, above Annex-A and above the sanction form (§8.3). Where the deceased is the
    ``Father``, the ``Mother`` is his widow, stated by the one office that owns the fact.

    Returned only where exactly one distinct father and one distinct mother appear
    (``FRC-04``). An FRC may carry more than one family unit -- the head's parents and a
    spouse's parents both print as Father/Mother -- and two of the four real bundles do
    exactly that, so pairing them there would be a guess with a widow's pension on it.
    """
    fathers, mothers = {}, {}
    for m in frc_family or ():
        rel = _norm_token(m.relation, _RELATION)
        if rel == "FATHER":
            fathers.setdefault(" ".join(sorted(_norm_name(m.name))), m)
        elif rel == "MOTHER":
            mothers.setdefault(" ".join(sorted(_norm_name(m.name))), m)
    if len(fathers) == 1 and len(mothers) == 1:
        return next(iter(fathers.values())), next(iter(mothers.values()))
    return None


def check_more_than_one_widow(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """Two mothers against one father on the FRC. ``FRC-05``, rule 4.10(1).

    The 2 December 2024 amendment substituted rule 4.10(1): "in case a Government servant
    had more than one wife, the pension shall be divided equally among the widows". So a
    second wife is not a curiosity, it halves a pension -- and nothing in this engine looked
    for one.

    Raised at MEDIUM, deliberately. The evidence is an extracted table, and on a real bundle
    the reader returned three "Mother" rows for one woman plus a man's name among them. A
    HIGH flag on that would block a sound case, which is the failure this battery has already
    made once. MEDIUM puts it in front of the officer with the page to check, and the
    determination question follows only if the original confirms it.
    """
    if not record.frc_family:
        return []
    # A table read that repeats one row three times has looped, and its rows are not
    # evidence of anything: 27d5's FRC came back with "Zohra Bibi, Mother" four times and a
    # man among the mothers, and was reported as three widows.
    from collections import Counter
    rows = Counter((" ".join(sorted(_norm_name(m.name))), _norm_token(m.relation, _RELATION))
                   for m in record.frc_family)
    if rows and max(rows.values()) >= 3:
        return []
    fathers, mothers = {}, {}
    for m in record.frc_family:
        rel = _norm_token(m.relation, _RELATION)
        if rel == "FATHER":
            fathers.setdefault(" ".join(sorted(_norm_name(m.name))), m)
        elif rel == "MOTHER" and not (_norm_name(m.name) & _MALE_NAME_WORDS):
            mothers.setdefault(" ".join(sorted(_norm_name(m.name))), m)
    if len(fathers) != 1 or len(mothers) < 2:
        return []
    named = ", ".join(sorted(m.name for m in mothers.values()))
    return [Flag(
        id="",
        severity=MEDIUM,
        flag_class=CONTRA_FAMILY,
        title="The FRC records more than one mother against one father",
        finding=(
            f"The family certificate shows one father but {len(mothers)} mothers ({named}). "
            f"If there was more than one widow, the pension is split equally between them."
        ),
        required_action=(
            "Check the mother rows against the original certificate -- it may be a "
            "misreading, or one certificate covering two families. If there really is more "
            "than one widow, send the case to the Determining Officer: the pension is divided "
            "equally between them (rule 4.10(1), amended 2 December 2024)."
        ),
        owner="AG_OFFICE",
        asserted=tuple(m.source for m in mothers.values()),
        contradicted_by=tuple(f.source for f in fathers.values()),
        affects_determination=True,
    )]


#: Name words only a man carries, as these forms transliterate them ("Feroz Ud Din",
#: "Muhammad ..."). A "Mother" row with one of them is a misread row, not a second widow.
_MALE_NAME_WORDS = frozenset({"muhammad", "mohammad", "muhammed", "din", "ullah", "ahmad",
                              "ahmed", "khan", "hussain", "hassan", "iqbal", "akbar"})


def _frc_is_headed_by_a_child(pairs: list[tuple[str, str]]) -> bool:
    """Is this FRC written from a child's seat rather than the deceased's?

    ``pairs`` is (Annex-A relation, FRC relation) for every person both documents name, both
    already normalised. The answer is yes only when at least one pair is explained by the
    child frame AND no pair contradicts it -- so one genuinely wrong row keeps the whole
    family in the direct comparison, where it is flagged. A frame is accepted on the evidence
    of the whole family or not at all.
    """
    explained = unexplained = 0
    for annex_rel, frc_rel in pairs:
        if annex_rel == frc_rel:
            continue                       # agrees in either frame; says nothing about seat
        allowed = _FRC_HEADED_BY_A_CHILD.get(annex_rel)
        if allowed and frc_rel in allowed:
            explained += 1
        else:
            unexplained += 1
    # One unexplained pair must not veto the frame: a single mis-paired name -- a son matched
    # to the only "Malik ..." row on the certificate -- did exactly that on the
    # divorced-daughter bundle and put four HIGH flags back on a family that agrees. The
    # unexplained pair is still flagged on its own below; what the vote decides is only
    # whether the WORDING difference is read as a contradiction for the rest of the family.
    if unexplained == 0:
        return explained > 0
    return explained >= 2 and explained > unexplained


def check_family_consistency(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """Annex-A against the NADRA FRC. ``CONTRA-FAMILY``.

    The FRC is authoritative on family composition (§8.3), but Annex-A is the attested legal
    declaration the sanction rests on, so a contradiction is flagged and returned for
    re-attestation **even where the entitlement outcome is unaffected** -- which on the
    golden case it is, because the spouse precedes children under ``ENT-07``.

    Before anything is called a contradiction the two documents are put in the same frame:
    an FRC requested by a son states the deceased as "Father" and a daughter as "Sister", and
    reading that as a contradiction produced a HIGH flag against every member of every real
    family -- see ``_FRC_HEADED_BY_A_CHILD``.
    """
    if not record.annex_a_family or not record.frc_family:
        return []

    matched: list[tuple] = []
    for stated in record.annex_a_family:
        actual = _match_person(stated.name, record.frc_family)
        if actual is None:
            continue
        # The pairing must hold from both ends. "Ahmad Raza" scores 0.86 against the FRC's
        # "Hammad Raza" -- but Annex-A lists Hammad Raza too, and he is the FRC row's exact
        # match. Pairing one way only put a HIGH "contradiction" on a son the FRC simply does
        # not list (56e5), and paired "Muhammad Tahir Munir" with the father row (d368).
        if _match_person(actual.name, record.annex_a_family) is not stated:
            continue
        stated_rel = _norm_token(stated.relation, _RELATION)
        actual_rel = _norm_token(actual.relation, _RELATION)
        # The FRC labels its requester "Applicant"/"Self". That is a role on the certificate,
        # not a relation to the deceased, so there is nothing to compare -- unless the frame
        # check below needs it, which is why the pair is kept and skipped later.
        matched.append((stated, actual, stated_rel, actual_rel))

    shifted = _frc_is_headed_by_a_child(
        [(a, b) for _s, _x, a, b in matched if "SELF" not in (a, b)]
    )

    # ``FRC-06``: is the death reflected on the FRC at all? NADRA updates the marital column
    # only when somebody reports a death, so a deceased pensioner routinely still reads
    # "Married" -- and then his widow reading "Married" beside him is the SAME unreported
    # marriage, not a claim that she is not a widow. Two independent signs of that: Annex-A
    # marking someone dead whom the FRC still calls married, and the paired Father row
    # (``FRC-03``) reading married on a case where somebody has died.
    pair = frc_spouse_pair(record.frc_family)
    death_not_on_frc = any(
        _marital(s.marital_status) == "DECEASED" and _marital(x.marital_status) != "DECEASED"
        for s, x, _a, _b in matched
    ) or (pair is not None and _marital(pair[0].marital_status) == "MARRIED")

    self_pension = record.case_type in SELF_PENSION_KINDS \
        or (record.case_variant or "") in SELF_PENSION_VARIANTS
    flags: list[Flag] = []
    for stated, actual, stated_rel, actual_rel in matched:
        if "SELF" in (stated_rel, actual_rel):
            continue

        differences = []
        # NADRA's newer certificates print "Child" for a son or a daughter alike. That is
        # the same answer less specifically, not a different one.
        child_for_child = "CHILD" in (stated_rel, actual_rel) \
            and {stated_rel, actual_rel} <= {"CHILD", "SON", "DAUGHTER"}
        if stated_rel != actual_rel and not child_for_child:
            allowed = _FRC_HEADED_BY_A_CHILD.get(stated_rel, frozenset())
            if not (shifted and actual_rel in allowed):
                differences.append(f"relation {stated.relation!r} vs {actual.relation!r}")

        stated_marital, actual_marital = _marital(stated.marital_status), _marital(
            actual.marital_status)
        # Death is evidenced by the death certificate, not by the FRC's marital column, and a
        # column that answers a different question is not a contradiction.
        marital_comparable = "DECEASED" not in (stated_marital, actual_marital)
        # A column nobody filled in is a missing value, not a disagreement. Annex-A prints
        # "Unknown" where the form left it blank, and comparing that against the FRC accused
        # a department of contradicting a fact it never stated.
        if stated_marital in _NOT_STATED or actual_marital in _NOT_STATED:
            marital_comparable = False
        # ``FRC-06``. The spouse of a dead pensioner is a widow whatever the FRC's marital
        # column says, and the death certificate -- not this column -- is the authority on
        # the death (§8.3). NADRA changes the column only when a family reports the death,
        # which is precisely why the death certificate is a separate required document, so
        # "Married" there is weak evidence of nothing and must not block a PPO. Not
        # conditioned on the Father row: that row CORROBORATES the staleness where it is
        # present, but its absence is not evidence the other way.
        if stated_rel == "SPOUSE" and stated_marital == "WIDOWED" \
                and actual_marital == "MARRIED":
            marital_comparable = False
        if marital_comparable and stated_marital != actual_marital:
            differences.append(
                f"marital status {stated.marital_status!r} vs {actual.marital_status!r}"
            )
        if not differences:
            continue

        flags.append(
            Flag(
                id="",
                # On the servant's own pension the family decides nothing today -- it is the
                # record a future family pension will be checked against -- so a difference is
                # put in front of the officer without blocking the case.
                severity=MEDIUM if self_pension else HIGH,
                flag_class=CONTRA_FAMILY,
                title=f"Annex-A contradicts NADRA FRC for {stated.name}",
                finding=(
                    f"Annex-A and the family certificate disagree about {stated.name}: "
                    f"{'; '.join(differences)}. NADRA decides family details, so the "
                    f"certificate is the one to follow."
                    + (" This is not the difference of wording already allowed for."
                       if shifted else "")
                ),
                asserted=(stated.source,),
                contradicted_by=(actual.source,),
                affects_determination=False,
                required_action=(
                    "Return Annex-A for correction and re-attestation so it matches NADRA. "
                    "Who gets the pension does not change -- the widow comes before the "
                    "children -- but Annex-A is the sworn declaration the sanction rests on "
                    "(§8.3, ENT-07)."
                ),
                owner="DEPARTMENT",
            )
        )

    if shifted:
        # Recorded, not hidden. An officer comparing the two pages by eye will see the words
        # differ, and must be able to see that the engine noticed and why it did not object.
        source = next((x.source for _s, x, _a, _b in matched), None)
        flags.append(Flag(
            id="",
            severity=LOW,
            flag_class=CONTRA_FAMILY,
            title="NADRA FRC is written from another family member's seat",
            finding=(
                "The FRC states each relation relative to the family member who requested it "
                "-- typically a child of the deceased -- while Annex-A states them relative "
                "to the deceased, so the same people read 'Father'/'Mother'/'Brother'/"
                "'Sister' on one page and 'Husband'/'Widow'/'Son'/'Daughter' on the other. "
                "Every pair on this case is consistent under that reading, so no "
                "contradiction is raised on the wording alone."
                + (" The FRC also predates the death, or was not updated for it: it still "
                   "records the deceased as married." if death_not_on_frc else "")
                + (f" Its Father and Mother rows -- {pair[0].name} and {pair[1].name} -- are "
                   f"the requester's parents and so are married to each other (FRC-03), which "
                   f"is NADRA's own corroboration of the spousal relationship the sanction "
                   f"rests on." if pair else "")
                + " A marital column left blank on either page is treated as unstated, not "
                "as a disagreement."
            ),
            required_action=(
                "None. Verify the composition against the FRC as usual; the differing words "
                "are a difference of reference point, not of fact."
            ),
            owner="AG_OFFICE",
            asserted=tuple(s.source for s, _x, _a, _b in matched[:1]),
            contradicted_by=(source,) if source else (),
            affects_determination=False,
        ))
    return flags


#: How close two renderings of the same name must be to be treated as the same person.
#: Chosen from the real file: "USMAN WAQAR" against "Usman Waqqar" scores 0.92, while the
#: nearest different person ("MAHNOOR WAQAR") scores 0.68. 0.85 separates them with room.
NAME_MATCH_THRESHOLD = 0.85

#: Marital status, normalised before comparison. Two documents describing the same fact in
#: different words is not a contradiction, and raising it as one is worse than missing it: on
#: the real file "Un-Married" against "Unmarried" produced a HIGH flag that would have blocked
#: a PPO and sent a department a correction letter for a hyphen.
_MARITAL = {
    "UNMARRIED": "UNMARRIED", "UNMARRIED ": "UNMARRIED", "SINGLE": "UNMARRIED",
    "MARRIED": "MARRIED",
    "WIDOW": "WIDOWED", "WIDOWER": "WIDOWED", "WIDOWED": "WIDOWED",
    "DIVORCED": "DIVORCED", "DIVORCEE": "DIVORCED",
    # The columns are written by hand and abbreviated. "M" against "Married" is the same
    # answer twice, and reading it as a disagreement accused a department of contradicting
    # NADRA about a family it had described correctly.
    "M": "MARRIED", "MRD": "MARRIED",
    "U": "UNMARRIED", "UM": "UNMARRIED", "UNM": "UNMARRIED",
    "W": "WIDOWED", "WID": "WIDOWED",
    "D": "DIVORCED", "DIV": "DIVORCED",
}

#: What Annex-A writes in the marital column for the deceased: "Died on 03.07.2026", "Late",
#: "Expired". Recognised by prefix, because the date travels with the word.
_DECEASED_MARKERS = ("DIED", "LATE", "EXPIRED", "DECEASED", "DEATH")

#: What a form says when the column was left blank. Never compared against anything.
_NOT_STATED = frozenset({"", "UNKNOWN", "NOTSTATED", "NA", "NIL", "NONE", "BLANK"})


def _marital(value: str) -> str:
    # A note in brackets qualifies the status, it does not change it: "Unmarried (Disabled)"
    # against the FRC's "Unmarried" raised a HIGH contradiction on e2c2.
    value = re.sub(r"\([^)]*\)", " ", value or "")
    key = "".join(ch for ch in value.upper() if ch.isalpha())
    if any(key.startswith(m) for m in _DECEASED_MARKERS):
        return "DECEASED"
    return _MARITAL.get(key, key)


#: A NADRA Family Registration Certificate states every relation RELATIVE TO THE PERSON WHO
#: REQUESTED IT -- its "Self" row -- and that person is usually a child of the deceased, not
#: the deceased. Annex-A states relations to the deceased. So the same family reads:
#:
#:      Annex-A            FRC (headed by a son)
#:      Husband (deceased) Father
#:      Widow              Mother
#:      Daughter           Sister
#:      Son                Brother / Self
#:
#: Nothing there is a contradiction; it is one family described from two seats. Comparing the
#: words directly raised a HIGH flag on EVERY member of EVERY real family-pension bundle --
#: four on one case -- and a HIGH flag blocks a PPO, so the office could forward nothing.
#: This table is the translation, and it is applied only when the whole family agrees on one
#: seat (see below): a single pair that does not fit is still a contradiction.
_FRC_HEADED_BY_A_CHILD: dict[str, frozenset[str]] = {
    "SPOUSE": frozenset({"MOTHER", "FATHER"}),
    "SELF": frozenset({"MOTHER", "FATHER"}),
    "SON": frozenset({"BROTHER", "SELF"}),
    "DAUGHTER": frozenset({"SISTER", "SELF"}),
    "FATHER": frozenset({"GRANDFATHER"}),
    "MOTHER": frozenset({"GRANDMOTHER"}),
}

#: Relation, likewise. SELF covers the FRC's own label for the person who requested the
#: certificate -- "Applicant" is that person's role on the document, not their relation to the
#: deceased, so comparing it against Annex-A's "Husband" compares two different questions.
_RELATION = {
    "HUSBAND": "SPOUSE", "WIFE": "SPOUSE", "SPOUSE": "SPOUSE", "WIDOW": "SPOUSE",
    "WIDOWER": "SPOUSE",
    "SON": "SON", "DAUGHTER": "DAUGHTER", "CHILD": "CHILD",
    # As the forms abbreviate them: DST, DGT, DTR for a daughter; S/O and D/O where the
    # column was filled in with the parentage instead of the relation.
    "DST": "DAUGHTER", "DGT": "DAUGHTER", "DTR": "DAUGHTER", "DO": "DAUGHTER",
    "SO": "SON",
    "FATHER": "FATHER", "MOTHER": "MOTHER",
    "BROTHER": "BROTHER", "SISTER": "SISTER",
    "GRANDFATHER": "GRANDFATHER", "GRANDMOTHER": "GRANDMOTHER",
    "APPLICANT": "SELF", "SELF": "SELF", "HOLDER": "SELF",
}


def _norm_token(value: str, table: dict[str, str]) -> str:
    key = "".join(ch for ch in (value or "").upper() if ch.isalpha())
    # The FRC's column label read in place of the relation: "Mother Name", "Father Name"
    # (d368, 25 Sep 2026 re-read). The label names the relation the row states.
    if key not in table and key.endswith("NAME") and key[:-4] in table:
        key = key[:-4]
    return table.get(key, key)


def _match_person(name: str, candidates: tuple[FamilyMember, ...]) -> FamilyMember | None:
    """Find the same person in another document, allowing for transliteration variants.

    Urdu names reach these forms through more than one transliteration, and the golden case
    proves it matters: Annex-A prints the surname WAQAR and the NADRA FRC prints WAQQAR.
    An exact match drops the pair, and dropping the pair drops F-2 -- the flag BRAIN §13.8
    calls "the one a human eye skips over".

    Returns None unless the best candidate clears the threshold AND is clearly better than
    the runner-up, so an ambiguous match escalates instead of silently pairing two siblings.
    """
    from difflib import SequenceMatcher

    target = " ".join(sorted(_norm_name(name)))
    scored = sorted(
        ((SequenceMatcher(None, target, " ".join(sorted(_norm_name(c.name)))).ratio(), c)
         for c in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not scored or scored[0][0] < NAME_MATCH_THRESHOLD:
        return None
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 0.05:
        return None          # two candidates equally close: do not guess between them
    return scored[0][1]


def _same_name(a: str, b: str) -> bool:
    """Two renderings of one person's name: close as a whole, or one's words inside the other's."""
    from difflib import SequenceMatcher
    ta, tb = _norm_name(a), _norm_name(b)
    if not ta or not tb:
        return False
    if SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio() \
            >= NAME_MATCH_THRESHOLD:
        return True
    small, large = sorted((ta, tb), key=len)
    return len(small) >= 2 and small <= large


def _norm_name(name: str) -> set[str]:
    drop = {"mst", "mr", "mrs", "miss", "late", "the"}
    tokens = {
        "".join(ch for ch in tok.lower() if ch.isalpha())
        for tok in (name or "").replace("/", " ").split()
    }
    return {t for t in tokens if len(t) > 2 and t not in drop}


def check_undeclared_recoveries(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """A recovery in the record that the sanction form denies. ``RULE-UNDECLARED``.

    BRAIN §16 item 8: "A recovery on the LPC that the sanction denies is a HIGH flag, every
    time." This is the flag §13.8 calls "the one that costs money" -- undetected, the
    Rs. 126,355 surfaces later as a demand against a widower already living on 75% of a
    pension.
    """
    flags: list[Flag] = []
    for rec in record.recoveries:
        if rec.declared_on_sanction:
            continue
        flags.append(
            Flag(
                id="",
                severity=HIGH,
                flag_class=RULE_UNDECLARED,
                title=f"Unrecorded recovery of {fmt(rec.amount)}",
                finding=(
                    f"The {_doc_words(rec.source.document)} shows {fmt(rec.amount)} still "
                    f"to be recovered ({rec.reason}), but the sanction form says nothing is "
                    f"due. The last pay certificate is the document that settles this (§8.3)."
                ),
                asserted=(rec.source,),
                contradicted_by=(),
                affects_determination=True,
                required_action=(
                    f"Note the recovery in the sanction, or adjust {fmt(rec.amount)} "
                    "against the gratuity or the first payment."
                ),
                owner="DEPARTMENT",
            )
        )
    return flags


#: Roles whose CNIC belongs to somebody incidental to the case -- a witness to a signature,
#: the officer who attested a copy, the agent who bought the stamp paper. Their numbers are
#: on the page legitimately and must not be compared with the pensioner's.
_INCIDENTAL_ROLES = ("witness", "attesting", "attestor", "oath", "agent", "vendor",
                     "commissioner", "officer", "manager", "verifier")


#: Words that arrive in the `person` field but are roles, not names. A CNIC card came back
#: with person "deceased" -- inferred from the pension context, printed nowhere on the card.
#: Grouping on that would file a widow's own card under the deceased and raise a HIGH flag
#: comparing her number with his.
_ROLE_WORDS = {"deceased", "applicant", "claimant", "widow", "widower", "pensioner",
               "son", "daughter", "father", "mother", "sister", "brother", "spouse",
               "witness", "agent", "vendor", "self", "govt servant", "government servant"}


def _is_a_name(person: str | None) -> bool:
    """Is this a name we can group people by, or a role word standing in for one?"""
    cleaned = (person or "").strip().strip(".").lower()
    return bool(cleaned) and cleaned not in _ROLE_WORDS


def _is_incidental(role: str | None) -> bool:
    lowered = (role or "").lower()
    return any(word in lowered for word in _INCIDENTAL_ROLES)


def check_cnic_consistency(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """One person, one CNIC, wherever the case quotes it. ``CONTRA-IDENTITY``. SOP §6.1.

    The CNIC is the primary identity key (BRAIN §7.2), so two different numbers for the same
    person is the identity contradiction that matters most -- it is the difference between
    paying a pension to the family and paying it to a stranger.

    Grouped by PERSON, never by case. A page of a sanction form quotes the deceased's number
    and the claimant's; a bank form adds two witnesses; the FRC lists a household. Comparing
    every number on a case against every other would call an ordinary bundle a contradiction
    on every run, and a check that fires on every case is one an officer learns to dismiss.
    Numbers belonging to witnesses, attesting officers and stamp vendors are set aside for
    the same reason.
    """
    cnics = [
        a for a in record.assertions
        if a.field == "cnic" and _is_a_name(a.person) and not _is_incidental(a.role)
    ]
    by_person: dict[str, list] = {}
    for a in cnics:
        key = " ".join(sorted(_norm_name(a.person)))
        if key:
            by_person.setdefault(key, []).append(a)

    flags: list[Flag] = []
    for entries in by_person.values():
        # Two sources agreeing is evidence; one source is an assertion. The same principle
        # the emoluments reconciliation runs on, applied here because a single reading of a
        # CNIC is not reliable enough to accuse a family with. A real sweep of one clean case
        # produced the right number on three documents, a misread on a fourth and a
        # placeholder 3520200000000 on a fifth -- and comparing raw readings would have
        # raised a HIGH identity flag against a widow whose papers are in order.
        #
        # So each candidate number must be CORROBORATED: stated by at least two documents.
        # A contradiction then means two numbers each of which the case asserts twice, which
        # is a disagreement between documents rather than a slip of the reader.
        seen: dict[str, set[int]] = {}
        for a in entries:
            seen.setdefault(a.value, set()).add(a.source.page)
        distinct = {v for v, pages in seen.items() if len(pages) >= 2}
        if len(distinct) < 2:
            continue
        entries = [a for a in entries if a.value in distinct]
        who = entries[0].person
        stated = "; ".join(
            f"{value} at {', '.join(f'p.{a.source.page}' for a in entries if a.value == value)}"
            for value in sorted(distinct)
        )
        flags.append(
            Flag(
                id="",
                severity=HIGH,
                flag_class=CONTRA_IDENTITY,
                title=f"Two different CNICs recorded for {who}",
                finding=(
                    f"The file carries {len(distinct)} different CNIC numbers for {who}: "
                    f"{stated}. One of them is not this person."
                ),
                asserted=tuple(a.source for a in entries),
                contradicted_by=(),
                affects_determination=False,
                required_action=(
                    "Establish which number is correct against NADRA and have the department "
                    "correct the documents that carry the other."
                ),
                owner="DEPARTMENT",
            )
        )
    return flags


def check_cnic_cards_belong_to_the_case(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """Is the attached CNIC copy this case's person? ``CNIC-UNCORROBORATED``. SOP §6.1.

    A card is corroborated when the number printed on it is quoted somewhere else in the
    bundle -- on the sanction form, the bank option form, the descriptive roll. A card whose
    number appears on no other page is not tied to this case by anything except having been
    filed with it, which is exactly the state of affairs when the wrong person's copy is
    attached.

    The number is the test, not the name. A wrong card can carry a similar name -- these
    bundles already produce WAQAR against WAQQAR on the same person -- and a name
    comparison would pass it. Nothing else on a CNIC ties it to a pension case.
    """
    cards = [d for d in record.documents if d.type.startswith("CNIC")]
    if not cards:
        return []
    quoted: dict[str, list] = {}
    for a in record.assertions:
        if a.field != "cnic":
            continue
        quoted.setdefault(a.value, []).append(a)

    # Whose case this is: the claimant, and the servant -- Annex-A's "Self" row, or the member
    # it marks as dead. A card belonging to one of them and quoted nowhere else may be a
    # substitution, and that blocks a PPO. A card whose holder is plainly somebody else -- a
    # witness to the affidavit, a relative whose copy was filed with the rest -- is quoted once
    # because a witness IS quoted once. d368 raised three HIGH flags on exactly those.
    parties = [record.claimant_name] if record.claimant_name else []
    parties += [m.name for m in record.annex_a_family
                if _norm_token(m.relation, _RELATION) == "SELF"
                or _marital(m.marital_status) == "DECEASED"]

    def belongs_to_a_party(card) -> bool:
        if card.type in ("CNIC_DECEASED", "CNIC_CLAIMANT"):
            return True                   # the checklist asked for this card by that role
        holder = card.person_named or ""
        # No holder, or one this engine cannot compare (the Urdu name line, a number read
        # into the name slot): treated as a party's card, because the substitution this check
        # exists to catch is exactly the one that names nobody recognisable.
        if not parties or not _norm_name(holder) or any(ch.isdigit() for ch in holder):
            return True
        return any(_same_name(holder, p) for p in parties)

    flags: list[Flag] = []
    for card in cards:
        pages = set(card.pages)
        on_card = [v for v, entries in quoted.items()
                   if any(a.source.page in pages for a in entries)]
        if not on_card:
            continue                      # the card's own number was not read: F-4 territory
        party_card = belongs_to_a_party(card)
        for number in on_card:
            elsewhere = [a for a in quoted[number] if a.source.page not in pages]
            if elsewhere:
                continue
            # One digit away from a number the case quotes elsewhere is a misread card, not a
            # stranger's: 27d5's upside-down card read …0858 where the bank form quotes …0868.
            near = sorted({v for v, entries in quoted.items() if v != number and len(v) == len(number)
                           and sum(x != y for x, y in zip(v, number)) == 1
                           and any(a.source.page not in pages for a in entries)})
            if near:
                flags.append(Flag(
                    id="",
                    severity=MEDIUM,
                    flag_class=CNIC_UNCORROBORATED,
                    title=f"CNIC copy at p.{card.pages[0]} was probably misread",
                    finding=(f"The CNIC at p.{card.pages[0]} was read as {number}, one digit away "
                             f"from {', '.join(near)} quoted elsewhere in the case. Most likely "
                             f"the same card read wrongly."),
                    asserted=(Source(card.pages[0], card.type),),
                    contradicted_by=tuple(a.source for v in near for a in quoted[v]),
                    affects_determination=False,
                    required_action="Compare the card with the number quoted on the forms.",
                    owner="AG_OFFICE",
                ))
                continue
            if not party_card:
                flags.append(Flag(
                    id="",
                    severity=MEDIUM,
                    flag_class=CNIC_UNCORROBORATED,
                    title=f"CNIC copy at p.{card.pages[0]} belongs to neither party",
                    finding=(
                        f"The CNIC at p.{card.pages[0]} ({number}, {card.person_named}) is "
                        f"neither the claimant's nor the government servant's and appears "
                        f"nowhere else. Most likely a witness's or relative's copy filed with "
                        f"the rest."
                    ),
                    asserted=(Source(card.pages[0], card.type),),
                    contradicted_by=(),
                    affects_determination=False,
                    required_action=(
                        "Confirm whose copy this is. No action is needed where it is a witness "
                        "to the affidavit or a relative whose copy was filed with the rest."
                    ),
                    owner="AG_OFFICE",
                ))
                continue
            flags.append(
                Flag(
                    id="",
                    severity=HIGH,
                    flag_class=CNIC_UNCORROBORATED,
                    title=f"CNIC copy at p.{card.pages[0]} is not referred to anywhere in the case",
                    finding=(
                        f"The CNIC at p.{card.pages[0]} ({number}"
                        + (f", {card.person_named}" if card.person_named else "")
                        + ") appears nowhere else in the file, so nothing ties this card to "
                        "this case."
                    ),
                    asserted=(Source(card.pages[0], card.type),),
                    contradicted_by=(),
                    affects_determination=False,
                    required_action=(
                        "Confirm the card is the right person's, and have the department "
                        "supply the correct copy if it is not."
                    ),
                    owner="DEPARTMENT",
                )
            )
    return flags


def check_statutory_caps(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """A stated value exceeding a statutory cap. ``RULE-CAP``.

    MEDIUM, not HIGH: the engine applies the cap itself, so the case is still correctly
    calculable. It is recorded because the department's own figure differs from the one the
    determination uses, and an officer comparing the two needs to see why.
    """
    flags: list[Flag] = []

    stated_years = record.stated_qualifying_service_years
    cap = int(pack.ref("qualifying_service", "max_years_reckoned"))
    if stated_years is not None and stated_years > cap:
        flags.append(
            Flag(
                id="",
                severity=MEDIUM,
                flag_class=RULE_CAP,
                title=f"Qualifying service stated as {stated_years} years, above the {cap}-year cap",
                finding=(
                    f"The form states {stated_years} years of service. Pension counts "
                    f"{cap} years at most, which is 70% of pay, so the extra years add "
                    f"nothing (QS-08)."
                ),
                asserted=(_dedupe((record.stated_qualifying_service_source,))
                          or _doc_sources(record, *PRESCRIBED_FORMS)),
                affects_determination=True,
                required_action=f"None. The {cap}-year limit is applied for you (QS-08).",
                owner="AG",
            )
        )

    opted = record.commutation_pct_opted
    if opted is not None:
        max_pct = pack.amount("commutation", "max_percent_of_gross")
        if opted > max_pct:
            flags.append(
                Flag(
                    id="",
                    severity=MEDIUM,
                    flag_class=RULE_CAP,
                    title=f"Commutation opted at {opted}%, above the Punjab maximum of {max_pct}%",
                    finding=(
                        f"Annex-A asks to commute {opted}% of the pension. Punjab allows "
                        f"{max_pct}% at most -- the federal 25% does not apply here (COMM-01)."
                    ),
                    asserted=_doc_sources(record, "ANNEX_A"),
                    affects_determination=True,
                    required_action=f"Restrict commutation to {max_pct}% and confirm the option with the claimant.",
                    owner="AG",
                )
            )
    return flags


def check_sla(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """Statutory timelines. ``SLA-BREACH``.

    These never defeat a case (§8.1, BUILD §8.2). They feed the disposal dashboard the
    Additional Chief Secretary reviews monthly, and BUILD §12.4 requires the dashboard to be
    equally willing to show the AG's own queue time -- a breach is a finding about an
    institution, not about the family waiting on it.
    """
    flags: list[Flag] = []
    for event in record.timeline:
        if event.sla_days is None or event.sla_from is None:
            continue
        start = record.event(event.sla_from)
        if start is None:
            continue
        actual = (event.date - start.date).days
        if actual <= event.sla_days:
            continue

        received = record.event("RECEIVED_AT_AG")
        tail = ""
        if received is not None:
            tail = (
                f" The file reached the Office of the Accountant General on "
                f"{received.date.isoformat()}, {(received.date - start.date).days} days "
                f"after {_event_label(event.sla_from)}."
            )

        flags.append(
            Flag(
                id="",
                severity=MEDIUM,
                flag_class=SLA_BREACH,
                title=(
                    f"{_sentence(_event_label(event.event))} took {actual} days against a "
                    f"{event.sla_days}-day requirement"
                ),
                finding=(
                    f"{_sentence(_event_label(event.sla_from))} on "
                    f"{start.date.isoformat()}; {_event_label(event.event)} on "
                    f"{event.date.isoformat()} - {actual} days against the "
                    f"{event.sla_days}-day statutory requirement.{tail}"
                    + (f" {event.sla_note}" if event.sla_note else "")
                ),
                asserted=tuple(s for s in (event.source,) if s is not None),
                affects_determination=False,
                required_action=(
                    "No case defect. Record against the disposal-monitoring dashboard."
                ),
                owner="DEPARTMENT",
            )
        )
    return flags


def check_aliases(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """Name variants reconciled by documentary evidence. ``ALIAS-RESOLVED``.

    Recorded at LOW rather than dropped: an auditor reading the file will meet the same
    variants and needs to see that they were noticed and reconciled, not overlooked.
    """
    resolved = [a for a in record.aliases if a.resolved_by]
    if not resolved:
        return []
    variants = ", ".join(f"{a.value!r} ({a.kind.replace('_', ' ')})" for a in resolved)
    bases = "; ".join(dict.fromkeys(a.resolved_by for a in resolved if a.resolved_by))
    return [
        Flag(
            id="",
            severity=LOW,
            flag_class=ALIAS_RESOLVED,
            title=(f"A name is spelt two ways, and they match" if len(resolved) == 1
                   else f"{len(resolved)} names are spelt more than one way, and they match"),
            finding=f"Variants found: {variants}. Reconciled by: {bases}.",
            asserted=_dedupe(tuple(a.source for a in resolved)),
            affects_determination=False,
            required_action="None - recorded as resolved aliases.",
            owner="AG",
        )
    ]


def check_unreadable_documents(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """A determination-critical document that no reader could get through. ``EXTRACT-LOWCONF``.

    HIGH, because the consequence is not a missing field -- it is a check that silently did not
    run. On the real case LPC p.29 defeated three read attempts, and since the failure only
    reached a log line the report showed no F-3 and nothing to say that the page carrying a
    Rs. 126,355 recovery had never been read. An officer looking at that report would have had
    no way to know.

    BRAIN §5.3: below the threshold, route to human verification with the scan region beside
    the field. An unreadable page is that rule at document scale.
    """
    if not record.unreadable:
        return []
    pages = ", ".join(f"p.{page} ({_doc_words(doc)})" for page, doc, _ in record.unreadable)
    unread = {page for page, _, _ in record.unreadable}
    # Say what was salvaged. An independent OCR pass reads every LPC whatever the vision
    # model managed, and on the real case it recovered the Rs. 126,355 from this very page --
    # so a blanket "nothing was read from these pages" would contradict F-3, which cites it.
    salvaged = tuple(r for r in record.recoveries if r.source.page in unread)
    rescued = (
        " An independent OCR pass did recover "
        + ", ".join(f"{fmt(r.amount)} from p.{r.source.page}" for r in salvaged)
        + ", reported separately; the rest of each page remains unread."
    ) if salvaged else ""
    return [
        Flag(
            id="",
            severity=HIGH,
            flag_class=EXTRACT_LOWCONF,
            title=(f"A document could not be read: {pages}" if len(record.unreadable) == 1
                   else f"{len(record.unreadable)} documents could not be read: {pages}"),
            finding=(
                f"{pages} could not be read, so the checks that use these pages did not "
                f"run. Nothing found on them does not mean nothing is wrong with them."
                + rescued
            ),
            asserted=tuple(Source(page, doc) for page, doc, _ in record.unreadable),
            affects_determination=True,
            required_action=(
                "Read these pages yourself and confirm what they say before the case goes "
                "further. The reader's own account of why it failed is in the case artefacts: "
                + _first_sentence(record.unreadable[0][2])
            ),
            owner="AG",
        )
    ]


def check_cross_checks_ran(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """Stage 6 produced no cross-document facts at all. ``CROSS-CHECKS-NOT-RUN``, HIGH.

    Every check that needs two documents to disagree -- the personnel number stated twice, the
    undeclared recovery, the Annex-A against the FRC, the CNIC cards against the form -- reads
    its facts from stage 6. When that stage fails the battery runs over an empty fact set, each
    of those checks finds nothing to compare, and the report comes out with no findings at all.
    That is indistinguishable, on the screen, from a case where everything agrees.

    So the absence is itself the finding. HIGH and blocking, for the same reason an unreadable
    page is: silence from a check that never ran is not a clean result (audit 13 Oct 2026).
    """
    if record.cross_checks_ran:
        return []
    return [
        Flag(
            id="",
            severity=HIGH,
            flag_class=CROSS_CHECKS_NOT_RUN,
            title="The cross-document checks did not run on this case",
            finding=("The stage that collects the same fact from every document that states it "
                     "did not complete, so nothing on this case was compared against anything "
                     "else. No finding here means those checks did not run -- it does not mean "
                     "the documents agree."),
            asserted=(),
            affects_determination=True,
            required_action=("Verify the case again before it goes further. If it fails a second "
                             "time, the reason is in the run's own record (determination_gap) and "
                             "the case needs a person to compare the documents by hand."),
            owner="AG",
        )
    ]


def check_form_d_i_dates(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """Form D-I's dates against each other, and the service they imply. Business decision H3.

    Impossible dates -- death before birth, entry after the death, entry before the birth (or
    before age 15), a death-in-service after the notional superannuation -- are a hard stop:
    ``CONTRA-DATE``, HIGH, for the department to correct, and the engine refuses to compute on
    them (rules.engine.ImpossibleDates). Where the dates can all be true but the service from
    first entry to the death is under the pack's minimum for a monthly pension (10 years),
    ``SERVICE-SHORT``, MEDIUM, for the reviewer: this release computes no entitlement, so the
    finding says what the dates imply and leaves the rule to the officer.
    """
    from rules.engine import death_in_service_date_defects
    from rules.service import span

    dates = {field: (when, page, doc) for field, when, page, doc in record.form_dates if doc == "FORM_D_I"}
    if not dates:
        return []
    dob = dates.get("date_of_birth", (None,))[0]
    entry = dates.get("date_first_entry", (None,))[0]
    death = dates.get("date_of_death", (None,))[0]
    sources = tuple(sorted({Source(page, doc) for _, page, doc in dates.values() if page is not None}, key=lambda s: s.page))
    defects = death_in_service_date_defects(dob, entry, death, pack)
    if defects:
        return [Flag(
            id="", severity=HIGH, flag_class=CONTRA_DATE,
            title="The dates on Form D-I cannot all be true",
            finding="Form D-I states dates that contradict each other: " + "; ".join(defects)
                    + ". Nothing was computed on them (hard stop, decision H3).",
            required_action=("Department to correct Form D-I against the service book and the death certificate "
                             "and re-issue it. Officer to confirm the corrected dates against the originals."),
            owner="DEPARTMENT", asserted=sources, affects_determination=True,
        )]
    if entry and death:
        try:
            minimum = int(pack.ref("qualifying_service", "min_years_for_monthly_pension"))
        except Exception:                                    # noqa: BLE001
            minimum = 10
        # Whole calendar dates, not a day count: entry on 1 July 2011 and death on 30 June 2021
        # is ten years with the day of death counted, and the exclusive count said nine. No
        # figure in the finding either; the length is a computation this release does not show
        # (audit of 12 Oct 2026).
        from datetime import timedelta

        from rules.engine import add_years
        if death + timedelta(days=1) < add_years(entry, minimum):
            return [Flag(
                id="", severity=MEDIUM, flag_class=SERVICE_SHORT,
                title=f"Service at death may be under {minimum} years",
                finding=(f"From first entry on {entry.isoformat()} to the death on {death.isoformat()} is less "
                         f"than the {minimum} years the rules set for a monthly pension (QS-02), on the dates as "
                         f"read. No entitlement is computed in this release; the rule is for the reviewer to apply."),
                required_action=("Check the service against the service book (and any earlier service that counts), "
                                 "and decide the entitlement under QS-02 and the gratuity rules."),
                owner="AG", asserted=sources, affects_determination=True,
            )]
    return []


def check_disputed_reads(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """Two reads of a page disagreed on a figure or a date. ``EXTRACT-DISAGREE``, HIGH.

    NOT IN THE BATTERY since 23 Oct 2026, by the office's decision: it is not shown.

    What that does NOT change is what the system computes. The blanking is the reader's, not
    this finding's (extraction.client.extract_page_confirmed): where two reads differ, the
    page's pay lines are emptied, every *_rs field and each disputed date set to None, and
    nothing from the page reaches the determination. That still happens on every run. The
    disagreement is still recorded in fields.json and still reaches CaseRecord.disputed_reads,
    so the report carries it and a later decision can be built on it.

    What it changes is that nobody is told. The flag was the commonest HIGH finding on the
    seven S&GAD cases re-verified that morning -- five of the seven -- and most of it was
    spelling: 'Adhoc Rel AI 15% 22(PS17)' against 'Adhoc Rel Al 15% 22(PS17)', one stroke on
    the page read two ways, with the amounts identical to the rupee. The fold in
    extraction.client._fold_pay_label took that kind out; the office took the rest out.

    The cost, recorded because it is real: a page whose figures were discarded for a genuine
    disagreement now passes without saying so, and the checks that needed those figures did
    not run. Put the function back in BATTERY to have the finding again.

    Every determination-critical page is read twice. Until 7 Oct 2026 a disagreement was
    recorded in fields.json and the second read's figures were used anyway; nothing read that
    record. Business decision H1 was to stop and raise; the stopping stands, the raising does
    not.
    """
    if not record.disputed_reads:
        return []
    items = record.disputed_reads

    def _where(doc: str, page: int | None) -> str:
        return f"p.{page} ({_doc_words(doc)})" if page is not None else _doc_words(doc)

    listed = "; ".join(f"{_where(doc, page)} on {', '.join(fields[:5])}{' …' if len(fields) > 5 else ''}"
                       for doc, page, fields in items)
    return [
        Flag(
            id="",
            severity=HIGH,
            flag_class=EXTRACT_DISAGREE,
            title=(f"Two reads of a page disagree: {_where(*items[0][:2])}" if len(items) == 1
                   else f"Two reads disagree on {len(items)} pages"),
            finding=(
                f"The page was read twice and the reads differ: {listed}. No figure and no "
                f"disputed date from {'this page' if len(items) == 1 else 'these pages'} was "
                f"used, so the checks that need them did not run."
            ),
            asserted=tuple(Source(page, doc) for doc, page, _ in items if page is not None),
            affects_determination=True,
            required_action=(
                "Read the original page and transcribe the disputed figures and dates yourself; "
                "key at intake what the case needs, then verify the case again."
            ),
            owner="AG",
        )
    ]


def check_ambiguous_dates(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """A date written with a two-digit year was refused, not completed. ``DATE-AMBIGUOUS``.

    Until 7 Oct 2026 the readers completed "28-2-21" to 2021 and strptime completed "6/3/66"
    to 2066 (audit L1). Either is a guess about a figure the determination runs from -- the
    date of death starts the family pension and the lateness clock, the date of birth decides
    the retirement age -- so the readers now return nothing for such a date and this finding
    asks the officer to read the page and settle the century. MEDIUM: the case cannot be
    auto-approved with a date unsettled, and nothing is wrong with the papers themselves.
    Where the engine needs the date, the officer keys it at intake.
    """
    if not record.ambiguous_dates:
        return []
    items = record.ambiguous_dates
    affects = any(field != "document_date" for _, _, _, field in items)

    def _where(doc: str | None, page: int | None) -> str:
        where = f"p.{page}" if page is not None else "a page"
        return f"{where} ({_doc_words(doc)})" if doc else where

    listed = "; ".join(
        f"'{written}' for {field.replace('_', ' ')} on {_where(doc, page)}" if field != "document_date"
        else f"'{written}' dating {_where(doc, page)}"
        for doc, page, written, field in items)
    return [
        Flag(
            id="",
            severity=MEDIUM,
            flag_class=DATE_AMBIGUOUS,
            title=(f"A date is written with a two-digit year: {items[0][2]}" if len(items) == 1
                   else f"{len(items)} dates are written with two-digit years"),
            finding=(
                f"The year has two digits and could belong to either century, so the date was "
                f"not used: {listed}. Nothing was computed or measured from "
                f"{'it' if len(items) == 1 else 'them'}."
            ),
            asserted=tuple(Source(page, doc or "FORM") for doc, page, _, _ in items if page is not None),
            affects_determination=affects,
            required_action=(
                "Read each date on the page and confirm the century against the supporting "
                "paper (death certificate, CNIC, service book). Where the determination needs "
                "the date, key it at intake and re-run the verification."
            ),
            owner="AG",
        )
    ]


def check_party_roles(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """Whether the deceased/claimant roles were confirmed. ``EXTRACT-ROLE-SWAP``.

    The extraction labelled the widower as the deceased and the deceased as the claimant.
    Code corrected it from the printed "(LATE)" marker (``rules.case_type.resolve_parties``),
    and this flag exists so the correction is visible rather than silent: those two names
    decide whose CNIC satisfies which checklist item and whose name goes on the letters, and
    an auditor should be able to see that the question was asked.

    LOW where the record settled it, MEDIUM where it did not -- an unconfirmed role is a
    thing to check, not a defect in the case.
    """
    # A self pension has no deceased: the pensioner is the applicant, and there is no pair of
    # roles to resolve or confuse. Reporting "roles not independently confirmed" on such a
    # case is a finding about nothing, and a finding about nothing teaches an officer to skim.
    if record.case_variant in SELF_PENSION_VARIANTS:
        return []
    if record.party_roles_note:
        return [
            Flag(
                id="",
                severity=MEDIUM,
                flag_class=EXTRACT_ROLE_SWAP,
                title="Deceased and claimant roles not independently confirmed",
                finding=record.party_roles_note,
                asserted=_doc_sources(record, *DEATH_CERTIFICATES, *PRESCRIBED_FORMS),
                affects_determination=False,
                required_action=(
                    "Confirm from the death certificate which party is the deceased before "
                    "the CNIC and family requirements are relied on."
                ),
                owner="AG",
            )
        ]
    if not record.party_roles_corrected:
        return []
    return [
        Flag(
            id="",
            severity=LOW,
            flag_class=EXTRACT_ROLE_SWAP,
            title="Deceased and claimant were extracted the wrong way round, and corrected",
            finding=(
                "The extraction returned the surviving claimant as the deceased and the "
                "deceased as the claimant. The roles were reassigned from the 'late' marker "
                "printed beside the deceased's name, and the CNIC requirements and letters "
                "below use the corrected assignment. Recorded because these two names decide "
                "which checklist items are satisfied and who the letters address."
            ),
            asserted=_doc_sources(record, *DEATH_CERTIFICATES, *PRESCRIBED_FORMS),
            affects_determination=False,
            required_action=(
                "No action if the corrected reading matches the file. Verify against the "
                "death certificate if in doubt."
            ),
            owner="AG",
        )
    ]


def check_scope_confusion(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """A document applied to something it does not govern. ``SCOPE-CONFUSION``.

    BRAIN §9.8 and §16 item 9: succession shares never touch monthly family pension. A
    succession certificate governs estate items -- financial assistance, group insurance,
    four months' salary, GPF -- and the pension vests in the widow/widower under the Pension
    Rules regardless of the shares it recites. Conflating the two is called out as "a
    recurring, serious error".
    """
    if record.succession_certificate is None:
        return []
    if not record.case_type.startswith("FAMILY_PENSION"):
        return []
    return [
        Flag(
            id="",
            severity=LOW,
            flag_class=SCOPE_CONFUSION,
            title="Succession certificate present in a family-pension case",
            finding=(
                "A succession certificate divides the estate -- group insurance, four "
                "months' salary, GPF. The monthly family pension is not divided that way: it "
                "goes to the entitled family member under the Pension Rules (§9.8)."
            ),
            asserted=(record.succession_certificate,),
            affects_determination=False,
            required_action=(
                "Ensure estate items are not conflated with the monthly family pension."
            ),
            owner="AG",
        )
    ]


#: Run order. Within a severity band, flags keep this order, which is what makes the assigned
#: ids stable for the same input -- a determination that renumbered its flags between runs
#: would break every reference in a shortcoming letter already sent.
#: Pay components whose amount one document may not restate differently from the LPC.
_PAY_LINE_DOCS_AUTHORITY = ("LPC",)


def check_pay_lines_against_lpc(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """The LPC is the source of truth for pay components; another document's differing amount
    for the same component is a finding. ``CONTRA-MONEY``, HIGH. Business decision H2, 7 Oct 2026.

    Until then the lines of the form, the LPC and the salary statement were pooled, so a
    component printed at two amounts was summed into the base. Nothing is summed across
    documents now (pipeline.extract.single_source_pay_lines); this check says where the
    documents disagree, line by line, with the LPC's figure first. Where no LPC pay line was
    read and another document carries pay lines, that absence is itself a finding (MEDIUM):
    there is no source of truth to check the lines against.
    """
    lines = record.pay_lines
    if not lines:
        return []
    lpc = {}
    for ln in lines:
        if ln.document in _PAY_LINE_DOCS_AUTHORITY and ln.component != "unknown":
            lpc.setdefault(ln.component, ln)
    others = [ln for ln in lines if ln.document not in _PAY_LINE_DOCS_AUTHORITY]
    if not lpc:
        if not others:
            return []
        docs = sorted({ln.document for ln in others})
        return [Flag(
            id="", severity=MEDIUM, flag_class=CONTRA_MONEY,
            title="No LPC pay lines read; the pay components cannot be checked against the LPC",
            finding=(f"Pay lines were read from {', '.join(_doc_words(d) for d in docs)} but no pay line "
                     f"could be read from an LPC, which is the source of truth for pay components. "
                     f"The lines were not checked against it and nothing was summed across documents."),
            required_action="Confirm the pay components against the original LPC; if the bundle has none, "
                            "ask the department for it.",
            owner="AG",
            asserted=tuple(sorted({Source(ln.page, ln.document) for ln in others if ln.page is not None},
                                  key=lambda s: s.page)),
            affects_determination=True,
        )]
    differences = []
    for ln in others:
        truth = lpc.get(ln.component)
        if truth is not None and int(truth.amount) != int(ln.amount):
            differences.append((ln, truth))
    if not differences:
        return []
    listed = "; ".join(
        f"{ln.component.replace('_', ' ')}: LPC prints {fmt(truth.amount)}"
        f"{f' (p.{truth.page})' if truth.page is not None else ''}, "
        f"{_doc_words(ln.document)} prints {fmt(ln.amount)}{f' (p.{ln.page})' if ln.page is not None else ''}"
        for ln, truth in differences)
    return [Flag(
        id="", severity=HIGH, flag_class=CONTRA_MONEY,
        title=(f"A pay component differs from the LPC: {differences[0][0].component.replace('_', ' ')}"
               if len(differences) == 1 else f"{len(differences)} pay components differ from the LPC"),
        finding=(f"The LPC is the source of truth for pay components, and another document prints a "
                 f"different amount for the same component: {listed}. The amounts were not summed; the "
                 f"LPC's figure stands and the difference is for the department to explain."),
        required_action=("Department to correct the document that disagrees with the LPC, or produce the "
                         "pay order that changed the component. Officer to confirm against the original LPC."),
        owner="DEPARTMENT",
        asserted=tuple(sorted({Source(t.page, t.document) for _, t in differences if t.page is not None}, key=lambda s: s.page)),
        contradicted_by=tuple(sorted({Source(ln.page, ln.document) for ln, _ in differences if ln.page is not None}, key=lambda s: s.page)),
        affects_determination=True,
    )]


def check_emoluments_reconciliation(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """The reckonable pay lines against the total the sanction form prints. ``CONTRA-MONEY``.

    BRAIN §8.4 calls this "the single highest-value arithmetic check in the system", and
    until now its failure produced no flag: the engine refused to determine, the refusal went
    to the run log, and the officer saw "Not computed" with nothing to send back to the
    department. The engine now computes on the pay records (§8.3) and this check raises the
    discrepancy HIGH, so the case is returned with the defect named.

    Where the difference equals exactly one pay line, the finding says which -- on the
    OSD-post case it is the Rs. 750 qualification pay the AG salary statement prints and
    Form D-I's total omits, and Note 2 makes qualification pay reckonable (EMOL-04). That is
    the sentence the department needs; "Rs. 750 short" is not.
    """
    emol = record.emoluments
    if emol is None or emol.printed_total is None or emol.reconciled:
        return []
    diff = emol.discrepancy
    lines = [*emol.reckonable, *emol.excluded]

    def doc_at(page: int | None) -> str:
        for d in record.documents:
            if page is not None and page in d.pages:
                return d.type
        return "PAY_RECORD"

    asserted = tuple(sorted({Source(c.page, doc_at(c.page)) for c in emol.reckonable
                             if c.page is not None}, key=lambda s: s.page))
    form = record.document("FORM_D_I") or record.document("FORM_B_I")
    contradicted = (Source(form.pages[0], form.type),) if form and form.pages else ()

    # Printed figures only (scope decision of 7 Oct 2026): the lines as printed and the form's own
    # Total Pay. The engine's sum and the difference are never quoted; where the difference equals
    # one printed line, that line is named.
    printed = ", ".join(f"'{c.printed_label}' {fmt(c.amount)}" for c in emol.reckonable)
    finding = (
        f"The pay lines the pay record prints ({printed}) do not add up to the Total Pay the "
        f"prescribed form prints ({fmt(emol.printed_total)})."
    )
    culprit = next((c for c in lines if c.amount == abs(diff)), None)
    if culprit is not None and diff > 0:
        finding += (
            f" The form's total omits the '{culprit.printed_label}' line"
            f"{f' (p.{culprit.page})' if culprit.page else ''} of {fmt(culprit.amount)}, which the pay "
            f"record prints; {culprit.component.replace('_', ' ')} is reckonable under Note 2 of the form."
        )
    elif culprit is not None:
        finding += (
            f" The form's total appears to include the '{culprit.printed_label}' line"
            f"{f' (p.{culprit.page})' if culprit.page else ''} of {fmt(culprit.amount)}, which the pay "
            f"records do not carry."
        )
    else:
        finding += (
            " No single pay line accounts for it: either a line was misread or the "
            "department's own arithmetic is wrong, and those need different letters."
        )
    return [Flag(
        id="",
        severity=HIGH,
        flag_class=CONTRA_MONEY,
        title="Pay lines do not add up to the form's printed total",
        finding=finding,
        required_action=(
            "Department to re-issue the sanction form with every reckonable component and "
            "the total as per the AG pay record, or state why the line is not reckonable "
            "for this servant. Officer to confirm the pay lines against the original."
        ),
        owner="DEPARTMENT",
        asserted=asserted,
        contradicted_by=contradicted,
        affects_determination=True,
    )]


def check_prescribed_form_is_complete(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """A sanction form that states no figure for the pension it sanctions. ``AUTH-DEFECT``.

    Form D-II prints "drawing pension / family pension @ ______ per month", and on the
    unmarried-daughter bundle the department left that blank, along with "Net pension" and
    "Total pension". The family pension is a share of that figure, so the case cannot be
    computed -- and the engine said so only in the determination panel, as a gap. A gap is
    not a letter. The department left a required field of its own form empty, which is a
    defect in the paperwork, and the officer needs it in the findings list where the
    shortcoming letter is written from.
    """
    if not record.prescribed_form_blanks:
        return []
    doc = (record.document("FORM_D_II") or record.document("FORM_D_I")
           or record.document("FORM_B_I"))
    where = (Source(doc.pages[0], doc.type),) if doc and doc.pages else ()
    listed = ", ".join(record.prescribed_form_blanks)
    return [Flag(
        id="",
        severity=HIGH,
        flag_class=AUTH_DEFECT,
        title="The prescribed form states no pension figure",
        finding=(
            f"The form does not say what pension the deceased was drawing ({listed} left "
            f"blank). Without that figure the family pension cannot be worked out."
        ),
        required_action=(
            "Send the form back to be completed and re-signed with the pension stated, or "
            "have the Auditor copy it from the PPO and note that on the file. A pension slip "
            "in the bundle is not used instead: it may be on a different basis, and the form "
            "is what the sanction rests on (§8.3)."
        ),
        owner="DEPARTMENT",
        asserted=where,
        affects_determination=True,
    )]


def check_nikah_nama(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """No Nikah Nama, and the FRC does not show the applicant. ``RELATIONSHIP-UNPROVED``, MEDIUM.

    Office checklist item 22 asked for the marriage registration "in case applicant not Shown
    in FRC". It is a finding rather than a checklist line (office decision, 24 Sep 2026): a
    missing line made the case incomplete and went into every return letter, while the officer
    is better placed to judge whether the relationship is proved some other way. MEDIUM, so it
    does not block the case the way a HIGH finding does.

    Raised on the checklist's own condition (``rules.checklist._applicant_shown_in_frc``): an
    FRC that was not read, or a claimant not named, does not excuse it -- absence of evidence
    is not proof. A Nikah Nama found anywhere in the bundle, or a column that never asked for
    one, raises nothing.
    """
    from .checklist import _applicant_shown_in_frc

    if record.case_variant not in NIKAH_NAMA_VARIANTS or record.has_document("NIKAH_NAMA"):
        return []
    if _applicant_shown_in_frc(record):
        return []
    why = ("the NADRA FRC was not read" if not record.frc_family
           else "the applicant is not named on the case" if not record.claimant_name
           else "the applicant is not shown in the NADRA FRC")
    return [Flag(
        id="",
        severity=MEDIUM,
        flag_class=RELATIONSHIP_UNPROVED,
        title="No Nikah Nama, and the family certificate does not prove the relationship",
        finding=(f"The bundle holds no marriage registration (Nikah Nama), and {why}, so no "
                 f"document proves the relationship the claim rests on."),
        # The certificate the applicant is not on is the page to check; where the FRC was not
        # read, its located pages still open, so the officer can read what the reader could not.
        asserted=(_dedupe(tuple(m.source for m in record.frc_family))
                  or _doc_sources(record, "NADRA_FRC")),
        required_action=("Check the relationship from the papers on file. Where it is not "
                         "proved, ask the department for the computerised marriage "
                         "registration (Nikah Nama), attested by the DDO."),
        owner="DEPARTMENT",
        affects_determination=False,
    )]


#: Case types and columns the eligible-relations check applies to: a family pension, where the
#: claimant is someone other than the servant.
_FAMILY_CASE_TYPES = ("FAMILY_PENSION_DEATH_IN_SERVICE", "FAMILY_PENSION_DEATH_AFTER_RETIREMENT")


def _claimant_row(rows, name: str | None):
    """The claimant's own row among family members (FRC or Annex-A), by name, or None."""
    from difflib import SequenceMatcher
    if not name:
        return None

    def key(v: str) -> str:
        return " ".join(sorted("".join(c for c in t.lower() if c.isalpha()) for t in (v or "").split()))
    target = key(name)
    for m in rows:
        if SequenceMatcher(None, target, key(m.name)).ratio() >= 0.85:
            return m
    return None


def _claimant_frc_row(record: CaseRecord):
    """The claimant's own row on the NADRA FRC, by name, or None."""
    return _claimant_row(record.frc_family, record.claimant_name)


def check_claimant_relation(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """The claimant's relation against the DRAFT list of eligible relations, and its proof.
    Business decision H6, 7 Oct 2026 (draft list: rules.relations; decision sheet Appendix B).

    Advisory only, by the owner's decision of 7 Oct 2026: every finding here is MEDIUM, worded as
    a check for the reviewer, and never blocks a case -- the list is pending the rules owner's
    confirmation, and a draft must not stop a pension.

    * not stated -> RELATIONSHIP-UNPROVED: "Verify relation eligibility: relation not stated";
    * not on the list (a grandchild, an in-law, a nephew) -> RELATION-INELIGIBLE: "Verify relation
      eligibility: <relation> is not on the draft list";
    * on the list but a condition fails on the papers -- an "unmarried daughter" the FRC records
      as married, a spouse recorded remarried, a son past the draft age limit -> RELATION-INELIGIBLE,
      "Verify relation eligibility: ...";
    * on the list with proof missing -> RELATIONSHIP-UNPROVED: "Proof of <age / marital status /
      income> not found", naming the documents that would supply it.
    This release computes no share; the finding is what the officer decides on.
    """
    from rules.relations import SON_AGE_LIMIT_YEARS, parse_relation
    family = (record.case_type in _FAMILY_CASE_TYPES
              or (record.case_variant or "") in {"WIDOW", "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER",
                                                 "DISABLED_CHILD_SIBLING", "PARENT", "SISTER", "DEATH_IN_SERVICE"})
    if not family:
        return []
    form = record.document("FORM_D_II") or record.document("FORM_D_I")
    sources = (Source(form.pages[0], form.type),) if form and form.pages else ()
    # The relation as the prescribed form words it; Form D-I states none (the department's
    # sanction names the servant), so the claimant's own row on the NADRA FRC, else Annex-A,
    # speaks for the form there.
    row = _claimant_frc_row(record)
    stated = (record.claimant_relation or "").strip()
    stated_by = "the prescribed form"
    if not stated and row is not None and (row.relation or "").strip():
        stated, stated_by = row.relation.strip(), "the NADRA FRC"
        sources = sources + (row.source,)
    if not stated:
        annex = _claimant_row(record.annex_a_family, record.claimant_name)
        if annex is not None and (annex.relation or "").strip():
            stated, stated_by = annex.relation.strip(), "Annex-A"
            sources = sources + (annex.source,)
    if not stated and (record.frc_applicant_relation or "").strip():
        stated, stated_by = record.frc_applicant_relation.strip(), "the NADRA FRC (as its applicant)"
    parsed = parse_relation(stated)
    if not stated:
        return [Flag(id="", severity=MEDIUM, flag_class=RELATIONSHIP_UNPROVED,
                     title="Verify relation eligibility: the claimant's relation to the deceased is not stated",
                     finding="Neither the prescribed form, the NADRA FRC nor Annex-A states (or the reader could not read) "
                             "the claimant's relation to the deceased, and every family-pension entitlement turns on it.",
                     required_action="Read the relation off the papers; where the form leaves it blank, the department "
                                     "re-issues the form with the relation stated.",
                     owner="DEPARTMENT", asserted=sources, affects_determination=False)]
    entry = parsed.entry
    if entry is None:
        return [Flag(id="", severity=MEDIUM, flag_class=RELATION_INELIGIBLE,
                     title=f"Verify relation eligibility: {stated} is not on the draft list",
                     finding=(f"{parsed.reason}. The draft list of eligible relations (pending the rules owner's "
                              f"confirmation) has the widow or widower, sons to the prescribed age, unmarried, widowed "
                              f"and divorced daughters, disabled children, dependent parents and sisters. A check for "
                              f"the reviewer, not a bar."),
                     required_action="Verify the relation against the NADRA FRC and the rules; decide the claim on them.",
                     owner="AG", asserted=sources, affects_determination=False)]
    out: list[Flag] = []
    status = (row.marital_status or "").strip().casefold() if row else ""
    if entry.key == "unmarried_daughter" and status and status.startswith("marr"):
        out.append(Flag(id="", severity=MEDIUM, flag_class=RELATION_INELIGIBLE,
                        title="Verify relation eligibility: claimed as an unmarried daughter, the NADRA FRC records her as married",
                        finding=(f"{stated_by.capitalize()} states the claimant as '{stated}'; the FRC row for "
                                 f"{row.name} records marital status '{row.marital_status}'. An unmarried daughter's "
                                 f"entitlement ends on marriage (ENT-03)."),
                        required_action="Verify the marital status against the FRC and the CNIC before deciding.",
                        owner="AG", asserted=sources + ((row.source,) if row else ()), affects_determination=False))
    if entry.key == "spouse" and status and status.startswith("remarr"):
        out.append(Flag(id="", severity=MEDIUM, flag_class=RELATION_INELIGIBLE,
                        title="Verify relation eligibility: the NADRA FRC records the spouse as remarried",
                        finding=f"The FRC row for {row.name} records '{row.marital_status}'; the spouse's family pension ends on remarriage (ENT-01).",
                        required_action="Verify against the FRC and the non-remarriage certificate before deciding.",
                        owner="AG", asserted=sources + ((row.source,) if row else ()), affects_determination=False))
    if entry.key in ("son", "child") and row is not None and row.birth_year:
        when = record.entitlement_date or record.processed_on
        if when is not None and when.year - int(row.birth_year) >= SON_AGE_LIMIT_YEARS:
            out.append(Flag(id="", severity=MEDIUM, flag_class=RELATION_INELIGIBLE,
                            title=f"Verify relation eligibility: son past the draft age limit of {SON_AGE_LIMIT_YEARS}",
                            finding=(f"The FRC gives {row.name}'s year of birth as {row.birth_year}; at the entitlement date "
                                     f"({when.isoformat()}) that is {when.year - int(row.birth_year)} years. A son draws only to "
                                     f"the prescribed age (ENT-02), which the office has not yet confirmed (BLOCKING-08; "
                                     f"draft {SON_AGE_LIMIT_YEARS})."),
                            required_action="Verify the date of birth against the CNIC / B-form and apply the prescribed age limit.",
                            owner="AG", asserted=sources + (row.source,), affects_determination=False))
    missing = []
    for proof in entry.proofs:
        if proof.kind == "relationship" and row is not None:
            continue                                   # the FRC names the claimant
        if not record.has_document(*proof.documents):
            missing.append(proof)
    if missing:
        listed = "; ".join(f"{p.kind.replace('_', ' ')} — {p.note}" for p in missing)
        docs = sorted({d for p in missing for d in p.documents})
        out.append(Flag(id="", severity=MEDIUM, flag_class=RELATIONSHIP_UNPROVED,
                        title="Proof of " + " / ".join(p.kind.replace("_", " ") for p in missing) + f" not found (claim as {entry.label.lower()})",
                        finding=(f"The claimant is stated by {stated_by} as '{stated}' ({entry.label.lower()}, {entry.rule}). "
                                 f"The papers do not prove: {listed}. Entitlement runs: {entry.limit}"),
                        required_action="Verify each condition against the papers; where a paper is wanted, ask the department for: "
                                        + ", ".join(_doc_words(d) for d in docs) + ".",
                        owner="DEPARTMENT", asserted=sources, affects_determination=False))
    return out


def check_frc_currency(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """A NADRA FRC older than six months at submission. ``DOC-STALE``, HIGH.

    Office practice (rules.checklist.FRC_MAX_AGE_MONTHS): the certificate must have been
    issued within six months of the case reaching the office. The same test marks AG-06
    DEFECTIVE on the checklist, so the shortcoming letter asks for a fresh certificate; the
    flag is what blocks the PPO and what the officer verifies against the page (SOP §4.4(4)).
    One flag per certificate page, so the letter can name the page.
    """
    from .checklist import FRC_MAX_AGE_MONTHS, stale_frcs

    # AG-06 requires the certificate on every column, the self-pension ones since the user's
    # decision of 12 Oct 2026 (S14), so a stale one is a defect wherever it is filed: the same
    # test marks the checklist line DEFECTIVE, and the flag must not say less than the line.
    flags: list[Flag] = []
    for x in stale_frcs(record):
        flags.append(
            Flag(
                id="",
                severity=HIGH,
                flag_class=DOC_STALE,
                title=(
                    f"The family certificate at p.{x['page']} is out of date: issued "
                    f"{x['issued'].isoformat()}"
                ),
                finding=(
                    f"The family certificate at p.{x['page']} was issued "
                    f"{x['issued'].isoformat()} and was good until "
                    f"{x['valid_until'].isoformat()}. It had expired by the time the case "
                    f"was sent ({x['reference'].isoformat()})."
                ),
                asserted=(Source(x["page"], "NADRA_FRC"),),
                affects_determination=False,
                required_action=(
                    f"Get a fresh NADRA FRC (family certificate), issued within "
                    f"{FRC_MAX_AGE_MONTHS} months of submission and attested by the DDO."
                ),
                owner="DEPARTMENT",
            )
        )
    return flags


def check_cnic_expiry(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """The claimant's CNIC must be in force. ``DOC-EXPIRED``. SOP §5.2 AG-02 ("valid CNIC").

    HIGH where the card had already expired when the case was submitted: the department
    forwarded a claim on an identity document that was not valid, and the same test marks
    AG-02 DEFECTIVE so the letter asks for a valid card. MEDIUM where the card was valid on
    arrival but has expired since (measured to the run's own recorded date, not the clock):
    nothing was wrong with the submission, but no PPO should issue to a card that has lapsed,
    so the officer is told before the case is forwarded. A lifetime card raises nothing.
    """
    from .checklist import claimant_cnic_status

    flags: list[Flag] = []
    for x in claimant_cnic_status(record):
        src = (Source(x["page"], "CNIC_CLAIMANT"),)
        if (x["expired_at_submission"] or x["expired_since"]) and not x["confirmed"]:
            flags.append(Flag(
                id="", severity=MEDIUM, flag_class=DOC_EXPIRED,
                title=f"Check the expiry date on the claimant's CNIC at p.{x['page']}",
                finding=(f"The scan of the claimant's CNIC at p.{x['page']} was read as expiring "
                         f"on {x['expires'].isoformat()}, but its issue date could not be read "
                         f"beside it, so this may be the issue date read into the wrong place. "
                         f"Many cards print 'Lifetime' instead."),
                asserted=src, affects_determination=False,
                required_action=("Look at the card: if it prints 'Lifetime' or a date after "
                                 "submission, nothing is needed. If it really has expired, ask "
                                 "for the renewed CNIC."),
                owner="AG_OFFICE",
            ))
        elif x["expired_at_submission"]:
            flags.append(Flag(
                id="", severity=HIGH, flag_class=DOC_EXPIRED,
                title=(f"Claimant's CNIC at p.{x['page']} had expired before submission: "
                       f"expiry {x['expires'].isoformat()}"),
                finding=(f"The claimant's CNIC at p.{x['page']} expired on "
                         f"{x['expires'].isoformat()}, before {x['reference_label'].lower()} on "
                         f"{x['reference'].isoformat()}. The case came in on an identity card "
                         f"that was already out of date (SOP §5.2 AG-02)."),
                asserted=src, affects_determination=False,
                required_action=("Obtain an attested copy of the claimant's renewed CNIC and "
                                 "resubmit."),
                owner="DEPARTMENT",
            ))
        elif x["expired_since"]:
            flags.append(Flag(
                id="", severity=MEDIUM, flag_class=DOC_EXPIRED,
                title=(f"Claimant's CNIC at p.{x['page']} has expired since submission: "
                       f"expiry {x['expires'].isoformat()}"),
                finding=(f"The claimant's CNIC copy at p.{x['page']} was valid when the case "
                         f"came in but prints a date of expiry of {x['expires'].isoformat()}, "
                         f"before this case was processed on "
                         f"{x['processed_on'].isoformat()}. Not a defect in the submission; "
                         f"the PPO should not issue against a lapsed card."),
                asserted=src, affects_determination=False,
                required_action=("Ask the claimant for the renewed CNIC before the PPO / FPPO "
                                 "issues; the Pension Facilitation Centre can take it at the "
                                 "counter."),
                owner="AG_OFFICE",
            ))
    return flags


def check_attestation(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """Photocopies the SOP requires attested, on which the reader saw no attestation.
    ``ATTEST-MISSING``, MEDIUM. SOP §5.1(1).

    MEDIUM rather than HIGH, and a finding rather than a checklist defect, deliberately: an
    attestation is a stamp and a signature, which a reader can miss on a dark copy, and a
    HIGH flag here would return real cases over a stamp the officer can see on the page. The
    officer verifies it against the page cited (SOP §4.4(4)) and, where it is truly absent,
    returns the case. Only an explicit "not attested" reading is reported; "not judged" is not.
    """
    from .checklist import unattested_copies

    docs = unattested_copies(record)
    if not docs:
        return []
    pages = ", ".join(f"p.{d.pages[0]} ({_doc_words(d.type)})" for d in docs if d.pages)
    return [Flag(
        id="", severity=MEDIUM, flag_class=ATTEST_MISSING,
        title=(f"{len(docs)} photocopy has no attestation stamp" if len(docs) == 1
               else f"{len(docs)} photocopies have no attestation stamp"),
        finding=(f"No attesting officer's stamp was seen on {pages}. A photocopy has to be "
                 f"stamped and signed to be accepted."),
        asserted=tuple(Source(d.pages[0], d.type) for d in docs if d.pages),
        affects_determination=False,
        required_action=("Look at each page first -- a stamp on a dark copy is easy to miss. "
                         "Where it really is absent, send the document back to the department "
                         "to be attested by the DDO (SOP §5.1(1))."),
        owner="DEPARTMENT",
    )]


def check_psa_specimen(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """The sanction's signatory against the specimen the department sent the AG for that post.

    BRAIN §2: "the signature authority on a form is itself a checklist item -- a sanction signed
    by the wrong officer is a defect"; SOP §5.2 AG-04, the prescribed form "signed by the PSA".
    The register is rules/specimens; the first entry is S&GAD's Additional Secretary (Admn),
    letter No.SO.A.III(S&GAD)7-7/2025 of 9 September 2025.

    What code can check, it checks: the name stamped under the signature, the stamp's words,
    that there is a signature and a stamp at all, and that the specimen was in force on the date
    signed. Any of those wrong is ``AUTH-DEFECT`` MEDIUM. The signature itself is compared by
    the officer, from the cut-out signature beside the specimen (``SPECIMEN-CHECK`` LOW): the
    vision model was tested for this and cannot do it (pipeline/signatory.py). Nothing here is
    HIGH -- a reading of a stamp is not proof, and the officer looks before a case is returned.
    """
    from . import specimens

    register = {s.id: s for s in specimens.load()}
    flags: list[Flag] = []
    for sig in record.psa_signatures:
        where = (Source(sig.page, sig.document),) if sig.page else ()
        form = _doc_words(sig.document)
        signed = f"p.{sig.page} ({form})" if sig.page else form

        if sig.unreadable:
            # No reader got through the block, so every field below is blank by default rather
            # than by observation. Falling through from here produced "there is no signature in
            # the sanctioning authority's block" and returned the case to a department whose
            # form is signed; where that department had no specimen on file the failure instead
            # vanished entirely (audit 13 Oct 2026). Either way the officer was told something
            # the readers never established. The page goes to the officer instead.
            flags.append(Flag(
                id="", severity=MEDIUM, flag_class=SPECIMEN_CHECK,
                title=f"The sanctioning authority's block on {form} could not be read",
                finding=(f"No reader got through the signature block on {signed}, so whether it "
                         f"carries a signature, a stamp and a competent signatory is not "
                         f"established either way. This is a failure of the reading, not a "
                         f"finding about the department's form."),
                asserted=where, owner="AG_OFFICE",
                required_action=("Look at the page yourself and confirm the sanction is signed "
                                 "and stamped by the competent authority before the case goes "
                                 "further."),
            ))
            continue

        if sig.specimen is None:
            depts = specimens.for_department(" / ".join(t for t in (sig.department, sig.stamp_text, sig.stamp_ocr) if t))
            if not depts:
                continue                        # no specimen from this department: nothing to check
            spec = depts[-1]
            if sig.specimen_status == "post not on file":
                flags.append(Flag(
                    id="", severity=LOW, flag_class=SPECIMEN_CHECK,
                    title=f"{form} is signed by a {spec.department} officer with no specimen on file",
                    finding=(f"The sanction on {signed} is signed as "
                             f"{sig.designation or sig.stamp_text or 'an officer whose post was not read'}. "
                             f"{spec.department} has sent the AG a specimen only for its {spec.post} "
                             f"(PSA for {spec.scope}; {spec.cite})."),
                    asserted=where, owner="AG_OFFICE",
                    required_action=(f"Confirm that this officer is competent to sanction this case, "
                                     f"and ask {spec.department} for their specimen signature."),
                ))
            elif sig.specimen_status.startswith("not in force"):
                flags.append(Flag(
                    id="", severity=LOW, flag_class=SPECIMEN_CHECK,
                    title=f"No specimen on file for the date {form} was signed",
                    finding=(f"The sanction on {signed} is dated {sig.date_signed_raw}, before the "
                             f"{spec.department} specimen for {spec.post} came into force "
                             f"({spec.effective_from:%d %b %Y}, {spec.cite}). The officer who held the "
                             f"post then may be someone else."),
                    asserted=where, owner="AG_OFFICE",
                    required_action=(f"Compare the signature with the specimen {spec.department} sent "
                                     f"for {spec.post} before {spec.effective_from:%d %b %Y}, or ask "
                                     f"the department for it."),
                ))
            continue

        spec = register.get(sig.specimen)
        if spec is None:
            continue
        side_by_side = {
            "id": spec.id, "officer": spec.officer, "post": spec.post,
            "department": spec.department, "scope": spec.scope, "cite": spec.cite,
            "images": [p.name for p in spec.images], "page": sig.page,
            "signature_image": sig.signature_image,
        }
        wrong: list[str] = []
        if not sig.signature_present:
            wrong.append("there is no signature in the sanctioning authority's block")
        if not sig.stamp_present:
            wrong.append("there is no officer's stamp with the signature")
        # A "name" that is the post ("Additional Secretary (Admn.)") is the stamp read twice,
        # not a name; only a person's name can disagree with the specimen officer's.
        named = sig.signer_name if sig.signer_name and not specimens.names_post(spec, sig.signer_name) else None
        if named and _norm_name(named) and _norm_name(spec.officer) and \
                not (_norm_name(named) & _norm_name(spec.officer)):
            wrong.append(f"the name under the signature reads \"{named}\", and the "
                         f"specimen is {spec.officer}'s")
        stamp = sig.stamp_ocr or sig.stamp_text
        if stamp and not specimens.names_post(spec, stamp):
            wrong.append(f"the stamp reads \"{stamp}\", not {spec.stamp_text}")
        on = (f"signed {sig.date_signed:%d %b %Y}" if sig.date_signed
              else "the signature is not dated, so the specimen in force today is used")
        if wrong:
            flags.append(Flag(
                id="", severity=MEDIUM, flag_class=AUTH_DEFECT,
                title=f"{form} does not match the {spec.department} specimen for {spec.post}",
                finding=(f"The sanction on {signed} is from {spec.department} ({on}), where the "
                         f"specimen on file is {spec.officer}, {spec.post} ({spec.cite}). But "
                         + "; ".join(wrong) + "."),
                asserted=where, owner="DEPARTMENT", specimen=side_by_side,
                required_action=("Compare the form with the specimen shown here. Where it is not the "
                                 f"specimen officer's, return the case to {spec.department} for a "
                                 "sanction signed by the competent PSA (SOP §5.2, AG-04)."),
            ))
        else:
            flags.append(Flag(
                id="", severity=LOW, flag_class=SPECIMEN_CHECK,
                title=f"Compare the sanction signature with the {spec.department} specimen",
                finding=(f"The sanction on {signed} is signed as {spec.post}, {spec.department} "
                         f"({on}). The stamp names that post"
                         + (f" and the name under the signature is {named}" if named else "")
                         + f", as in the specimen on file: {spec.officer}, {spec.cite}. The "
                         f"signature itself is for you to compare; it is shown beside the specimen."),
                asserted=where, owner="AG_OFFICE", specimen=side_by_side,
                required_action=("Compare the signature with the three specimens. Where it is not the "
                                 "same hand, record that and return the case for a sanction signed "
                                 "by the competent PSA."),
            ))
    return flags


def check_self_pension_refusal(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """The self-pension engine refused on a contradiction in the papers. HIGH.

    The engine will not compute a pension from a date of birth and a date of retirement that
    put a servant ten years past superannuation, or from service too short to earn one. That
    refusal is a finding about the department's own form, and an officer who sees it only in
    the determination panel has no shortcoming to send back. It is raised here with the
    engine's own sentence, so the letter says exactly what the engine said.
    """
    if not record.self_pension_defect:
        return []
    return [Flag(
        id="", severity=HIGH, flag_class=SELF_PENSION_REFUSED,
        title="The pension could not be computed: the sanction form's own dates contradict",
        finding=record.self_pension_defect,
        asserted=tuple(Source(d.pages[0], d.type) for d in record.documents
                       if d.type.startswith("FORM_B_") and d.pages),
        affects_determination=True,
        required_action=("Settle the contradiction with the department: obtain the corrected "
                         "sanction form, or the order extending service where one exists, and "
                         "resubmit."),
        owner="DEPARTMENT",
    )]


def check_self_pension_service_short(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """The self-pension engine found the service short of a monthly pension (QS-02). MEDIUM.

    The same weight as SERVICE-SHORT on a Form D-I, and with the same restraint: the rule is
    for the reviewer to apply, and the length the engine counted is not shown (decision of
    7 Oct 2026). Until 12 Oct 2026 this refusal was a HIGH contradiction blamed on the
    department, with the computed years in it (audit of 12 Oct 2026).
    """
    if not record.self_pension_service_short:
        return []
    return [Flag(
        id="", severity=MEDIUM, flag_class=SERVICE_SHORT,
        title="Service may be short of the minimum for a monthly pension",
        finding=("The rules engine found the service, from the first entry to the retirement the sanction "
                 "form states, short of the minimum the rules set for a monthly pension (QS-02). No "
                 "entitlement is computed in this release; the rule is for the reviewer to apply."),
        asserted=tuple(Source(d.pages[0], d.type) for d in record.documents
                       if d.type.startswith("FORM_B_") and d.pages),
        affects_determination=True,
        required_action=("Check the dates of entry and retirement against the service book, and any "
                         "earlier service that counts, and decide the entitlement under QS-02 and the "
                         "gratuity rules."),
        owner="AG",
    )]


def check_declared_case_type(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """The declared case type against what the papers read as.

    The DDO declares one of the office's case types (a column of its document sheet); each
    names the pipeline path(s) it may be. The declaration selects the checklist and the rules
    and is never overruled by this check, which only says when the bundle disagrees:

    * a prescribed form of another path in the file (confidence at or above the unsigned-form
      band) is HIGH -- the DDO either declared the wrong type or sent the wrong papers, and
      the case cannot go to PPO on that checklist;
    * a path inferred without a form (a death certificate with a PPO, say) is MEDIUM;
    * after a pensioner's death, a claimant column the papers name differently (declared
      widow, the form says daughter) is MEDIUM: the right column decides the documents;
    * where the papers settle nothing, nothing is said -- the checklist reports the form.
    """
    from .case_type import CONF_UNSIGNED_FORM, case_type_label

    declared = record.declared_case_type
    if not declared:
        return []
    allowed = tuple(record.declared_pipeline_types)
    detected = record.detected_case_type
    alternatives = tuple(record.detected_case_type_alternatives)
    forms = tuple(Source(d.pages[0], d.type) for d in record.documents
                  if d.type.startswith("FORM_") and d.pages)
    flag = None
    if allowed and detected is not None and detected not in allowed:
        severity = HIGH if record.detected_case_type_confidence >= CONF_UNSIGNED_FORM else MEDIUM
        flag = (severity, f"The DDO declared this case as {case_type_label(declared)}; the papers read as "
                          f"{case_type_label(detected)}. {record.detected_case_type_evidence}")
    elif allowed and detected is None and alternatives and not (set(alternatives) & set(allowed)):
        flag = (MEDIUM, f"The DDO declared this case as {case_type_label(declared)}; the papers read as "
                        f"{' or '.join(case_type_label(a) for a in alternatives)}. {record.detected_case_type_evidence}")
    elif (record.detected_case_variant and record.detected_case_variant != declared
          and detected in allowed and len(allowed) == 1 and detected == "FAMILY_PENSION_DEATH_AFTER_RETIREMENT"):
        flag = (MEDIUM, f"The DDO declared this case as {case_type_label(declared)}; the papers name the claimant as "
                        f"{case_type_label(record.detected_case_variant)}. The claimant decides which documents apply.")
    if flag is None:
        return []
    severity, finding = flag
    return [Flag(
        id="", severity=severity, flag_class=DECLARED_TYPE_MISMATCH,
        title="Declared case type may not match documents",
        finding=finding.strip(),
        asserted=forms,
        required_action=("Confirm the case type with the DDO. Correct it on the case and examine "
                         "the claim again, or return the case for the right papers; the checklist and "
                         "rules above were run for the declared type."),
        owner="AG_OFFICE",
        affects_determination=severity == HIGH,
    )]


#: The service dates the proforma for qualifying service states, by the names stage 6 files
#: them under (pipeline.extract.proforma_assertions).
_PROFORMA = "QUALIFYING_SERVICE_PROFORMA"
_PROFORMA_SERVICE_DATES = {"date_first_entry": "date of appointment", "date_of_retirement": "date of retirement"}


def check_proforma_service_dates(record: CaseRecord, pack: RulePack) -> list[Flag]:
    """The proforma's service dates against every other paper stating them. ``CONTRA-SERVICE``.

    Scope change C2 (12 Oct 2026, S3). The proforma's date of birth and personnel number are
    compared by check_identity_consistency like any other document's; the dates that bound the
    service are compared here, and only where the proforma is one side of the disagreement, so
    a bundle without one is checked exactly as before. MEDIUM, not HIGH: a payroll statement's
    "entry into service" can rightly precede the appointment the proforma records where there
    was earlier service, so the officer settles it rather than the PPO being blocked outright.
    """
    flags: list[Flag] = []
    for field_name, label in _PROFORMA_SERVICE_DATES.items():
        values = record.distinct_values(field_name)
        stated = {v: srcs for v, srcs in values.items() if any(s.document == _PROFORMA for s in srcs)}
        others = {v: srcs for v, srcs in values.items() if v not in stated}
        if not stated or not others:
            continue
        on_proforma = " / ".join(stated)
        elsewhere = " / ".join(others)
        proforma_sources = tuple(s for srcs in stated.values() for s in srcs if s.document == _PROFORMA)
        other_sources = tuple(s for srcs in others.values() for s in srcs)
        flags.append(Flag(
            id="",
            severity=MEDIUM,
            flag_class=CONTRA_SERVICE,
            title=f"The proforma's {label} ({on_proforma}) differs from {elsewhere}",
            finding=(
                f"The proforma for qualifying service gives the {label} as {on_proforma} at "
                f"{_pages(proforma_sources)}, but {elsewhere} at {_pages(other_sources)}."
            ),
            asserted=proforma_sources,
            contradicted_by=other_sources,
            required_action=(
                f"Check the {label} against the service book and correct the proforma or the "
                f"other paper before the case goes forward."
            ),
            owner="DEPARTMENT",
        ))
    return flags


BATTERY: tuple[Callable[[CaseRecord, RulePack], list[Flag]], ...] = (
    check_prescribed_form_is_complete,
    check_more_than_one_widow,
    check_pay_lines_against_lpc,
    check_emoluments_reconciliation,
    check_identity_consistency,
    check_proforma_service_dates,
    check_family_consistency,
    check_undeclared_recoveries,
    check_cnic_consistency,
    check_cnic_cards_belong_to_the_case,
    check_statutory_caps,
    check_sla,
    check_aliases,
    check_scope_confusion,
    check_unreadable_documents,
    check_cross_checks_ran,
    check_form_d_i_dates,
    # check_disputed_reads is NOT in the battery (office's decision, 23 Oct 2026). See its
    # docstring: the page's figures are still discarded, only the finding is not raised.
    check_ambiguous_dates,
    check_party_roles,
    check_frc_currency,
    check_claimant_relation,
    check_nikah_nama,
    check_cnic_expiry,
    check_attestation,
    check_psa_specimen,
    check_self_pension_refusal,
    check_self_pension_service_short,
    check_declared_case_type,
)


def run_battery(record: CaseRecord, pack: RulePack) -> tuple[Flag, ...]:
    """Run every check and assign stable ``F-n`` ids, most severe first."""
    raised: list[Flag] = []
    for check in BATTERY:
        raised.extend(check(record, pack))

    ordered = sorted(raised, key=lambda f: _SEVERITY_ORDER[f.severity])
    return tuple(
        Flag(
            id=f"F-{n}",
            severity=f.severity,
            flag_class=f.flag_class,
            title=f.title,
            finding=f.finding,
            required_action=f.required_action,
            owner=f.owner,
            asserted=f.asserted,
            contradicted_by=f.contradicted_by,
            affects_determination=f.affects_determination,
            specimen=f.specimen,
        )
        for n, f in enumerate(ordered, start=1)
    )
