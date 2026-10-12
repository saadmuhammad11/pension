"""Assemble the case report the portal renders. BRAIN §6, §12.1.

Emits exactly what the pipeline actually produced. Where a stage has not run, the field is
null and the portal says so -- BUILD §15 rule 12: never demonstrate an untested path as
working. Stage 4 (field extraction) is not yet wired, so ``emoluments`` and ``determination``
are null here and the flag battery has no field-level assertions to run over. The checklist
and the case type are real, computed from the 43 pages the vision model actually read.

    python3 -m pipeline.report artifacts/golden artifacts/golden/case_report.json
"""

from __future__ import annotations

import copy
import json
import re
import sys
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from rules import (
    Assertion,
    CaseRecord,
    Document,
    FamilyMember,
    Recovery,
    Source,
    TimelineEvent,
    assign_cnic_roles,
    resolve_parties,
    claimant_from_form,
    entitlement_date_from_form,
    pay_scale_from_form,
    classify_case_type,
    suggest_variant,
    recommend,
    run_battery,
    run_checklist,
    select_pack,
)
from rules.case_type import canonical_office_type, declared_case_type_result, pipeline_types_for
from rules.emoluments import Emoluments, PayComponent
from rules.notifications import notify
from rules.scope import scrub_determination, scrub_emoluments
from .ingest import atomic_write_text


def _emoluments_from(payload: dict | None) -> Emoluments | None:
    """The ``Emoluments`` stage 7 wrote, as an object the flag battery can read.

    Every field is taken from the artefact; nothing is re-derived. The payload carries each
    component with the reckonable verdict already made, so the pack is not needed here.
    """
    if not payload or not payload.get("components"):
        return None
    comps = [
        (PayComponent(c["printed_label"], c["component"], c["amount"], c.get("page")),
         bool(c.get("reckonable")))
        for c in payload["components"]
    ]
    reckonable = tuple(c for c, ok in comps if ok)
    excluded = tuple(c for c, ok in comps if not ok)
    return Emoluments(
        reckonable_total=Decimal(sum(int(c.amount) for c in reckonable)),
        excluded_total=Decimal(sum(int(c.amount) for c in excluded)),
        reckonable=reckonable,
        excluded=excluded,
        unknown=(),
        printed_total=(Decimal(payload["printed_total"])
                       if payload.get("printed_total") is not None else None),
        computation_shown="",
    )


#: A printed money figure: grouped thousands, or a decimal amount. Deliberately strict --
#: bare digit runs are what turned a sentence about a 1974 posting into an 11-million-rupee
#: recovery.
#:
#: The decimal branch excludes a field of a dotted date. "w.e.f. 19.02.2026" read as
#: Rs. 19, and the only caller asks "does this text state a figure at all?" to decide
#: whether the sanction form DENIES a recovery -- so a date read as money made the form
#: look like it had declared one, and F-3, the recovery flag §13.8 calls "the one that
#: costs money", could not fire on any form that prints a dotted date beside the
#: declaration. A date is not an amount: reject a two-decimal run that is preceded by
#: `<digits>.` or followed by `.<digit>`, which is what makes it a date field rather than
#: a figure. Grouped thousands need no such guard -- dates carry no commas.
_MONEY = re.compile(
    r"\b\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?\b"      # 126,355 / 220,941.56
    r"|(?<![\d.])\d+\.\d{2}(?!\.?\d)"            # 1234.50, but not the 19.02 of 19.02.2026
)


def _money_in(text: str) -> int | None:
    """First money-shaped figure in the text, as whole rupees, or None."""
    m = _MONEY.search(text or "")
    if not m:
        return None
    from decimal import ROUND_HALF_UP, Decimal
    return int(Decimal(m.group(0).replace(",", "")).quantize(Decimal("1"),
                                                             rounding=ROUND_HALF_UP))


#: Every field of Document, so a new one cannot be silently dropped in transit. Twice now a
#: hand-written constructor omitted person_named -- once assembling pages into documents, once
#: reading them back here -- and each time the CNIC role assignment had nothing to match on
#: while every stage reported success. One mapping, one place to get it wrong.
_DOCUMENT_FIELDS = (
    "type", "pages", "present", "signatory", "signatory_is_psa",
    "attested", "countersigned_by", "defects", "person_named",
)


def _document(d: dict) -> Document:
    kwargs = {k: d[k] for k in _DOCUMENT_FIELDS if k in d}
    for seq in ("pages", "countersigned_by", "defects"):
        if seq in kwargs:
            kwargs[seq] = tuple(kwargs[seq])
    return Document(**kwargs)


#: Pakistani forms print dates day-first. ISO is accepted where a reader already normalised.
#: The real sweep returned all of these from one bundle: "12-02-2026", "18/03/2026",
#: "2026-03-18", "4th March, 2026", "6/3/26". Anything not listed here is refused rather than
#: coerced -- a misparsed date does not produce a missing SLA flag, it produces a WRONG one,
#: and an SLA breach is an accusation about an institution's timeliness.
#:
#: Two-digit years ("6/3/26") are refused too, since 7 Oct 2026 (audit L1): strptime's "%y"
#: completes 26 to 2026 and 66 to 2066, and a date of birth of 2066 is as wrong as one of 1926.
#: Such dates are collected by ``two_digit_year_dates`` and raised as a finding for a person
#: to settle (rules.flags.check_ambiguous_dates).
_DATE_FORMATS = (
    "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y",
    "%d %B %Y", "%d %B, %Y", "%d %b %Y", "%d %b, %Y",
)

#: Ordinal suffixes on a printed day: "4th March, 2026".
_ORDINAL = re.compile(r"\b(\d{1,2})(st|nd|rd|th)\b", re.I)

#: Plausible range for anything on a live pension case.
_EARLIEST, _LATEST = date(1940, 1, 1), date(2100, 1, 1)

#: The dated fields of the prescribed forms, as fields.json names them: the ones a
#: determination runs from, so a two-digit year in any of them affects the determination.
_DETERMINATION_DATE_FIELDS = frozenset({
    "date_of_birth", "date_first_entry", "date_of_retirement", "date_of_death",
    "date_of_death_of_pensioner", "date_of_death_of_prior_pensioner", "date_of_divorce",
})


def _fields_document(fields_path: Path) -> dict:
    """fields.json as a dict, or {} where stage 4 has not run or wrote junk."""
    if not fields_path.exists():
        return {}
    try:
        return json.loads(fields_path.read_text()) or {}
    except (OSError, ValueError):
        return {}


_FORM_DATE_FIELDS = ("date_of_birth", "date_first_entry", "date_of_death", "date_of_retirement")


def form_dates_from_fields(fields: dict) -> tuple:
    """The dates the prescribed form states, as stage 4 read them: ``(field, date, page, document)``.
    Two-digit years and unreadable values yield nothing here (they are findings of their own)."""
    out = []
    for f in fields.get("fields") or []:
        if f.get("name") in _FORM_DATE_FIELDS and f.get("value") and str(f.get("document", "")).startswith("FORM_"):
            when = _as_date(str(f["value"]))
            if when is not None:
                out.append((f["name"], when, f.get("page"), f["document"]))
    return tuple(out)


def pay_lines_from_fields(fields: dict) -> tuple:
    """Every pay line stage 4 read, with the document it came from (decision H2)."""
    from pipeline.extract import pay_line_document
    from rules.caserecord import PayLine
    out = []
    for c in fields.get("pay_components") or []:
        try:
            out.append(PayLine(document=pay_line_document(c, fields), page=c.get("page"),
                               component=str(c.get("component") or "unknown"),
                               printed_label=str(c.get("printed_label") or ""), amount=int(c["amount"])))
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(out)


def disputed_reads_from_fields(fields: dict) -> tuple[tuple[str, int | None, tuple[str, ...]], ...]:
    """Every page whose two reads disagreed, from stage 4's record: the ``<document>_agreement``
    entries (prescribed form, salary statement, LPC) and each pension witness's ``agreement``.
    ``(document, page, what differed)``; the page is None on records written before the
    reader tagged them (7 Oct 2026)."""
    found: list[tuple[str, int | None, tuple[str, ...]]] = []
    for key, value in fields.items():
        if not key.endswith("_agreement") or not isinstance(value, dict) or value.get("agree", True):
            continue
        doc = value.get("document") or key[:-len("_agreement")].upper()
        page = value.get("page")
        if page is None and doc == fields.get("prescribed_form"):
            page = fields.get("prescribed_form_page")
        found.append((doc, page, tuple(value.get("disputed") or ("figures on the page",))))
    for w in fields.get("pension_witnesses") or []:
        agreement = w.get("agreement") or {}
        if isinstance(agreement, dict) and not agreement.get("agree", True):
            found.append((w.get("document") or "PPO", w.get("page"), tuple(agreement.get("disputed") or ("figures on the page",))))
    return tuple(dict.fromkeys(found))


def two_digit_year_dates(run: Path, facts: dict) -> tuple[tuple[str | None, int | None, str, str], ...]:
    """Every date on the case written with a two-digit year: ``(document, page, as written, field)``.

    Looked for where ``_as_date`` is applied -- the dated fields of the prescribed form, each
    document's own date, the CNIC cards' expiry -- so what the parser refused is reported, not
    silently absent. The orientation scorer still accepts such a value as "looks like a date";
    that is a sanity score, never a figure.
    """
    from rules.case_type import two_digit_year
    found: list[tuple[str | None, int | None, str, str]] = []
    fields_path = run / "fields.json"
    if fields_path.exists():
        try:
            for f in json.loads(fields_path.read_text()).get("fields", []):
                if f.get("name") in _DETERMINATION_DATE_FIELDS and two_digit_year(f.get("value")):
                    found.append((f.get("document") or "FORM", f.get("page"), str(f["value"]).strip(), f["name"]))
        except (OSError, ValueError):
            pass
    for d in facts.get("document_dates", []):
        if two_digit_year(d.get("value")):
            found.append((d.get("document"), d.get("page"), str(d["value"]).strip(), "document_date"))
    for card in facts.get("cnic_cards", []):
        raw = (card.get("date_of_expiry") or "").strip()
        if two_digit_year(raw):
            found.append(("CNIC", card.get("page"), raw, "date_of_expiry"))
    return tuple(dict.fromkeys(found))


def _as_date(text: str) -> date | None:
    raw = _ORDINAL.sub(r"\1", (text or "").strip())
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        return parsed if _EARLIEST <= parsed < _LATEST else None
    return None


def _aliases(names: list[dict], canonicals: list[str | None], documents: tuple) -> tuple:
    """Distinct spellings of the servant's name across documents. BRAIN §8.4, flag F-6.

    Reported at LOW and only when the variants are close enough to be the same person -- the
    point is to show an auditor that the variants were noticed and reconciled, not to accuse
    anyone. Two genuinely different people would not be aliases, so the similarity gate is the
    same one the family check uses.

    ``resolved_by`` cites what actually reconciles them. A name-change order in the bundle is
    the strongest evidence; without one the variants are still reported, but as corroborated
    by the documents that carry them rather than by an order that is not there.
    """
    from difflib import SequenceMatcher

    from rules import Alias

    def key(v: str) -> str:
        return " ".join(sorted("".join(c for c in t.lower() if c.isalpha())
                               for t in (v or "").split()))

    # Variants are grouped per person. §13.5 F-6 covers both the deceased (Nargas /
    # Nargis / the maiden name Nargis Kamal) and the claimant ("Waqar Abdulbasit" on the
    # salary statement), so gating on the deceased's name alone silently dropped half of them.
    bases = [(key(c), c) for c in canonicals if c]
    grouped: dict[str, dict[str, dict]] = {}
    for entry in names:
        k = key(entry["value"])
        if not k:
            continue
        scored = sorted(
            ((SequenceMatcher(None, b, k).ratio(), b) for b, _ in bases), reverse=True
        )
        if not scored or scored[0][0] < 0.55:
            continue          # a different person, not a variant
        grouped.setdefault(scored[0][1], {}).setdefault(k, entry)

    variants = {k: e for group in grouped.values() if len(group) > 1
                for k, e in group.items()}
    if not variants:
        return ()

    order = next((d for d in documents if d.type in ("NAME_CHANGE_ORDER",)), None)
    basis = (
        f"name-change order at {order.page_ref}" if order else
        "corroborated across the documents that carry each spelling"
    )
    return tuple(
        Alias(value=e["value"], kind="spelling_variant", resolved_by=basis,
              source=(Source(int(e["page"]), e.get("document") or "")
                      if e.get("page") else None))
        for e in variants.values()
    )


#: What to ASK the corpus for each flag class. Not the class name and not the flag's own
#: title: querying with "CONTRA-IDENTITY Personnel-number mismatch 90000857 vs 90000853"
#: retrieved §8.2's table of class names, because the passage most similar to a class name is
#: the list of class names. It also dragged in case-specific digits as noise. Each entry below
#: is the question whose answer is the rule that makes the finding a defect.
_FLAG_QUERY = {
    "DECLARED-TYPE-MISMATCH":
        "Which prescribed form settles the case type -- Form B-I, B-IV, D-I or D-II -- and does a "
        "department's own description of the case overrule the form present in the file?",
    "CONTRA-IDENTITY":
        "When documents record different personnel numbers for the same servant, which "
        "document is authoritative — the payroll record or the sanction form?",
    "CONTRA-FAMILY":
        "A document attested by the department contradicts NADRA on a family relation or "
        "marital status. Which record wins, and must the attested one still be corrected?",
    "CONTRA-MONEY":
        "Which document governs when pay components differ between the LPC, the computerised "
        "pay slip and the sanction form?",
    "CONTRA-DATE":
        "How are inconsistent dates of entry, retirement or death across documents resolved?",
    "EXTRACT-DISAGREE":
        "When two readings of the same page of a pension case give different figures or dates, "
        "may either reading be used, or must an officer read the original page?",
    "RELATION-INELIGIBLE":
        "Which relations of a deceased pensioner or Government servant are eligible for family "
        "pension, in what order, and what must each prove -- age, marital status, income, disability?",
    "SERVICE-SHORT":
        "What is the minimum qualifying service for a monthly family pension on a death in service, "
        "and what does the family receive when the service falls short of it?",
    "DATE-AMBIGUOUS":
        "When a date on a prescribed form or supporting paper is written with a two-digit year, "
        "how is the date of death, birth or entry established before it is used in the pension?",
    "CONTRA-SERVICE":
        "What if the qualifying service stated on the form disagrees with the service record?",
    "RULE-UNDECLARED":
        "Undeclared recovery: which record governs recoveries and demands, and what money "
        "check compares a recovery in the pay record against the sanction form's declaration?",
    "RULE-CAP":
        "What is the maximum qualifying service reckoned for pension, and what happens when "
        "the form states more?",
    "SPECIMEN-CHECK":
        "Who must sign the prescribed pension form as Pension Sanctioning Authority, and with "
        "what name, date and stamp?",
    "AUTH-DEFECT":
        "Who must sign and attest the prescribed pension form and Annexure-A?",
    "SLA-BREACH":
        "What is the statutory time limit for sanctioning family pension, and does exceeding "
        "it defeat the case?",
    "ALIAS-RESOLVED":
        "How are variant spellings of a servant's name across documents reconciled?",
    "SCOPE-CONFUSION":
        "Does a succession certificate determine entitlement to monthly family pension?",
    "EXTRACT-LOWCONF":
        "What must happen when a determination-critical field cannot be read confidently?",
    "DOC-STALE":
        "How recent must the NADRA Family Registration Certificate be when a pension case "
        "is submitted?",
    "DOC-EXPIRED": "Must the claimant's CNIC be valid when a pension case is submitted?",
    "RELATIONSHIP-UNPROVED":
        "When must a family pension claimant file a marriage registration (Nikah Nama), and "
        "when does the NADRA Family Registration Certificate prove the relationship instead?",
    "CONTRA-SERVICE-DATES":
        "What is the age of superannuation, and what authorises service beyond it?",
    "ATTEST-MISSING": "Which documents in a pension case must be attested, and by whom?",
    "CNIC-UNCORROBORATED":
        "Whose CNIC copies must a pension case carry, and how is a card shown to belong to "
        "the servant or claimant in the case rather than to someone else?",
    "EXTRACT-ROLE-SWAP":
        "How is it established which person named in a pension case is the deceased "
        "government servant and which is the surviving claimant?",
}

#: Likewise per rule id, so a determination step cites the rule rather than a schema example.
_RULE_QUERY = {
    "EMOL-BASE": "Which pay components are reckonable for pension and which are excluded?",
    "QS-01": "How is qualifying service counted for pension?",
    "QS-08": "What is the maximum qualifying service reckoned for pension?",
    "CALC-01": "How is gross pension calculated from reckonable emoluments and qualifying service?",
    "FAM-IS-03": "How is family pension calculated on the death of a servant in service?",
    "FAM-IS-04": "Is gratuity on death in service the literal 25% of gross pension or a capitalised value?",
    "FAM-IS-05": "When does family pension commence after a death in service?",
    "ADD-02": "Is medical allowance computed on gross pension or on family pension?",
    "COMM-01": "What percentage of gross pension may be commuted in Punjab?",
    "FAM-DUR-01": "For how long is family pension payable to the widow or widower "
                  "under rule 4.10(1) as amended in December 2024?",
    "FAM-AR-06": "For how long is family pension payable to the widow or widower "
                 "under rule 4.10(1) as amended in December 2024?",
    # The death-after-retirement path landed after this map was written, so its three steps
    # fell through to their own descriptions -- which on a D-II case are "Family pension for
    # widow daughter of late Muhammad Bashir" and the like. A person's name is a poor query
    # for a rule and does not belong in a shared retrieval cache (BRAIN §15.4).
    "FAM-AR-01": "On the death of a pensioner, is family pension computed from the pension "
                 "in payment as stated on the PPO, or from a fresh emoluments calculation?",
    "FAM-AR-02": "What percentage of the deceased pensioner's pension is payable as family "
                 "pension in Punjab, and is it taken on the gross or the net pension?",
    "FAM-AR-05": "When does family pension commence on the death of a pensioner?",
    "FAM-AR-03": "When a family pensioner dies, on what terms is the family pension "
                 "re-granted to a surviving daughter or other eligible family member?",
    # The self-pension steps. Exercised by little -- BUILD §12.2 calls that path unproven
    # until a real Form B-I case passes -- which is why they were missed here too.
    "QS-05": "Does extraordinary leave without pay count towards qualifying service for "
             "pension, and when may it be allowed to count?",
    "VOL-RED-01": "What reduction applies to the pension of a government servant who "
                  "retires voluntarily before the age of superannuation?",
    "COMM-03": "How is the commuted value of a pension calculated from the commuted "
               "percentage, the gross pension and the age factor?",
    "CALC-02": "How is the net monthly pension arrived at after part of the gross pension "
               "has been commuted?",
}


def _found_as(checklist: dict, run: Path, variant: str | None) -> dict:
    """Say which paper satisfied each line, in the title the page itself prints (30 Sep 2026).

    "Found — document titled 'Non Source of Income Certificate' (page 12)": a department's own
    wording for a checklist paper is recorded against the line it satisfied, so an officer can
    see at a glance why a differently worded certificate was accepted. Read from the OCR text
    the run already holds; nothing is read again.
    """
    from extraction.identify import title_found
    from rules.checklist import requirements_for
    try:
        ocr = json.loads((run / "ocr_text.json").read_text()) if (run / "ocr_text.json").exists() else {}
        reqs = {r.id: r for r in requirements_for(variant)} if variant else {}
    except (ValueError, KeyError):
        return checklist
    for item in checklist.get("items") or []:
        req = reqs.get(item.get("id"))
        pages = item.get("located") or []
        if req is None or not pages or item.get("status") not in ("PRESENT", "FOUND_NOT_REQUIRED", "DEFECTIVE"):
            continue
        for page in pages:
            text = ocr.get(str(page)) or ""
            title = next((t for t in (title_found(d, text) for d in req.satisfied_by) if t), None)
            if title:
                item["found_as"] = f"Found — document titled '{title}' (page {page})"
                break
    return checklist


def _cite_all(report: dict) -> dict:
    """Attach a retrieved citation to every determination step, ambiguity and flag.

    BUILD §2 wants RAG over the rules corpus "so every flag and figure carries a citation".
    The rule pack already names the authority (FMT-04); this adds the passage an officer can
    actually read, retrieved from the corpus rather than restated from memory.

    Degrades visibly, never silently: if the embedding or reranker service is unreachable the
    report is still built and the citation field says the retrieval failed. A missing citation
    an officer can see beats a confident one that came from nowhere.

    Every query is collected first and retrieved in ONE batched call. Sequentially this was
    the entire cost of building a report -- 12.40s against 0.00s for everything else on the
    golden case, 17 round trips of embed-then-rerank -- and it made the report irreproducible,
    because the reranker's score is not bit-stable across runs and it lands in the case
    record. ``rag.store.cite_many`` caches each citation against the corpus fingerprint, so a
    rebuild returns the byte-identical passage (SOP §8.5.1) and costs nothing.
    """
    try:
        from rag.store import RagError, cite_many, unavailable
    except ImportError:
        return report

    # Which entry wants which query, decided once, so the batch can be de-duplicated and so
    # two steps asking the same question cannot end up citing different passages.
    #
    # `rules_only` is the subset the shared cache may keep: a curated question, or an
    # ambiguity's own question, both of which are about a rule and identical on every case.
    # The fallbacks are NOT in it. Where no curated question covers a rule id or a flag
    # class, the query becomes a step's description or a flag's title -- "Family pension for
    # widow daughter of late Muhammad Bashir", "CNIC copy at p.45 is not referred to
    # anywhere in the case" -- and case facts must not be written to a file outside the case
    # record (BRAIN §15.4). They are still de-duplicated and fetched concurrently here; they
    # are just not persisted, and they would never have been reused anyway.
    wants: list[tuple[dict, str]] = []
    rules_only: list[str] = []
    det = report.get("determination")
    if det:
        for step in det["steps"]:
            curated = _RULE_QUERY.get(step["rule_id"])
            wants.append((step, curated or step["description"]))
            if curated:
                rules_only.append(curated)
        for amb in det["ambiguities"]:
            # The ambiguity's own `question` is already a natural question about the rule --
            # exactly the right query. The BLOCKING id would only add noise.
            wants.append((amb, amb["question"]))
            rules_only.append(amb["question"])
    for flag in report.get("flags", []):
        curated = _FLAG_QUERY.get(flag["class"])
        wants.append((flag, curated or flag["title"]))
        if curated:
            rules_only.append(curated)

    if not wants:
        return report

    # ``cite_many`` degrades one query at a time, but it opens the index and its fingerprint
    # BEFORE any query, and that raised when artifacts/rag/index.json was absent: build_report
    # failed, and the whole run with it, after all the model work was done (12 Oct 2026). The
    # same answer the per-query path gives, attached to every entry, so the report is built and
    # says on each line why it carries no passage.
    try:
        citations = cite_many([query for _, query in wants], top_n=1, cacheable=rules_only)
    except (RagError, OSError) as exc:
        citations = {query: unavailable(exc) for _, query in wants}
    for entry, query in wants:
        # A copy each. Two steps can share a query, and a report is a mutable structure that
        # later passes through _redact and the API -- one shared list would let an edit to
        # one step's citation appear under another's.
        entry["corpus_citation"] = copy.deepcopy(citations[query])
    return report


#: The timestamp a determination carries when the caller supplies none. The same fixed value
#: ``stage_determine`` uses on the family path, so a report rebuilt from the same artefacts is
#: byte-identical. ``api.runs.execute`` passes the run's own start time in production.
_DEFAULT_COMPUTED_AT = datetime(2026, 6, 3, 10, 0, 0)


def _self_pension(run, bps, annual_pay: dict, retirement: "date | None",
                  case_type: str | None, fields_path,
                  computed_at: "datetime | None" = None,
                  commutation_percent: "str | None" = None,
                  basic_pay_read: int | None = None,
                  printed_average: "Decimal | None" = None,
                  printed_base_note: str | None = None) -> dict:
    """Work out a pension payable to the servant, from officer-supplied annual pay.

    Kept out of stage 7 deliberately. Stage 7 reads a bundle and computes a family pension
    from what it finds; this needs three figures that are not in the bundle at all, and the
    honest place for a value a human typed is a path that says so on the determination.
    """
    from decimal import Decimal

    from rules import select_pack
    from rules.emoluments import AnnualPay, reckon_average
    from rules.engine import SelfPensionCase, determine_self_pension

    if retirement is None:
        raise ValueError(
            "the date of retirement could not be read, so neither the rule pack nor the "
            "three years to average can be established"
        )
    pack = select_pack(effective_date=retirement)
    from_printed = False
    if annual_pay:
        years = [AnnualPay(int(y), Decimal(str(v).replace(",", "").strip()))
                 for y, v in sorted(annual_pay.items())]
        # The retirement date is passed so the engine can check the officer typed the right
        # three years, not merely three. Intake cannot know them -- the bundle has not been
        # read when the figures are entered -- so this is the first point at which the
        # window required by rule 4.4(4) is knowable, and therefore the point that must
        # check it.
        emol = reckon_average(years, pack, retirement=retirement)
    elif printed_average is not None:
        # No figures keyed yet, but Form B-I itself prints "Average Basic pay Rs. 57330".
        # Computed on that, PROVISIONALLY (BLOCKING-23 in the engine), so the officer sees
        # a figure and the case sits in the exceptional lane rather than showing nothing;
        # the three keyed figures replace it and the determination becomes final.
        from rules.emoluments import Emoluments, PayComponent
        from rules.money import exact, money
        base = money(printed_average)
        label = printed_base_note or "Average Basic pay (printed on Form B-I)"
        comp = PayComponent(printed_label=label, component="basic_pay", amount=base)
        emol = Emoluments(reckonable_total=base, excluded_total=Decimal(0),
                          reckonable=(comp,), excluded=(), unknown=(), printed_total=base,
                          computation_shown=(f"{exact(base)} = {label} (PROVISIONAL)"))
        from_printed = True
    else:
        raise ValueError("no annual pay figures were supplied and the form prints no average")

    read = {}
    if fields_path.exists():
        for f in json.loads(fields_path.read_text()).get("fields", []):
            if f.get("value"):
                read[f["name"]] = f["value"]
    # Stage 4 where it ran; otherwise the sanction form's own text, which states both.
    from rules import dates_from_form
    rows = json.loads((run / "identities.json").read_text())
    from_form = dates_from_form(
        " ".join(r.get("form_text", "") for r in rows if r.get("form_text"))
    )
    dob = _as_date(read.get("date_of_birth", "")) or from_form.get("date_of_birth")
    entry = _as_date(read.get("date_first_entry", "")) or from_form.get("date_first_entry")
    # The AG's own Monthly Salary Statement prints both dates in fields, generated by the
    # payroll system rather than written by a department (extraction.payroll). Where the form
    # reading disagrees with it, the statement is taken and the difference is carried as a
    # caveat: on abdd a pen stroke turned the form's 1966 into 1956, which refused the case
    # as "retired four years late" when the statement says she retired at exactly 60.
    date_caveats: list[str] = []
    payroll = {}
    assertions_path = run / "assertions.json"
    if assertions_path.exists():
        for a in json.loads(assertions_path.read_text()).get("assertions", []):
            if a.get("document") == "SALARY_STATEMENT" and a.get("field") in (
                    "date_of_birth", "date_first_entry"):
                payroll.setdefault(a["field"], (_as_date(a["value"]), a.get("page")))
    for field, label in (("date_of_birth", "date of birth"),
                         ("date_first_entry", "date of first entry")):
        stated, page = payroll.get(field, (None, None))
        current = dob if field == "date_of_birth" else entry
        if stated is None or stated == current:
            continue
        if current is not None:
            date_caveats.append(
                f"The sanction form was read as giving the {label} {current.isoformat()}; the "
                f"AG salary statement at p.{page} prints {stated.isoformat()}, which is used. "
                f"Check the form against the statement.")
        if field == "date_of_birth":
            dob = stated
        else:
            entry = stated
    if dob is None or entry is None:
        raise ValueError(
            "date of birth and date of first entry are needed for qualifying service and "
            "could not be read from the sanction form"
        )
    # Where the bundle's own pay certificate disagrees with what the officer keyed, both are
    # carried. Neither source is overruled: the certificate can predate a revision, and the
    # officer may be reading a service book the certificate does not reflect. Silently
    # preferring either one would decide a pension on a guess about which paper is fresher.
    pay_caveats: list[str] = []
    if basic_pay_read and annual_pay and years:
        latest = max(years, key=lambda y: y.year)
        if int(latest.amount) != int(basic_pay_read):
            pay_caveats.append(
                f"The pay certificate in this bundle prints a basic pay of "
                f"{int(basic_pay_read):,}, and the figure supplied for {latest.year} is "
                f"{int(latest.amount):,}. The pension is built on the supplied figures. "
                f"An officer should settle which is right before the PPO issues."
            )

    case = SelfPensionCase(
        case_ref=run.name,
        date_of_birth=dob,
        date_of_first_entry=entry,
        date_of_retirement=retirement,
        emoluments=emol,
        # The grade as the sanction form prints it, or None where no page states one. It was
        # a hardcoded 0 -- a pay band that does not exist -- written straight into `inputs`,
        # which is the block an auditor recomputes the determination from. A fabricated input
        # sitting beside real ones is indistinguishable from a read one.
        bps=bps,
        pension_kind=case_type or "SUPERANNUATION_PENSION",
        stated_qualifying_service=read.get("qualifying_service_printed"),
        base_is_three_year_average=True,
        base_from_printed_average=from_printed,
        commutation_percent=(Decimal(str(commutation_percent).replace(",", "").strip())
                             if str(commutation_percent or "").strip() else None),
        extra_caveats=tuple(pay_caveats + date_caveats),
    )
    # Injected, never read from the clock here. The engine's own docstring is explicit --
    # "no system clock ... the same inputs and the same pack reproduce the same output byte
    # for byte, forever" -- and `stage_determine` on the family path is pinned to that by
    # test_computed_at_is_injected_not_read_from_the_clock. This path called datetime.now(),
    # so rebuilding one case's report twice produced two different determinations.
    det = determine_self_pension(case, pack, computed_at or _DEFAULT_COMPUTED_AT)
    return {"determination": det.to_dict(), "emoluments": None}


def _psa_signatures(run: Path) -> tuple:
    """``psa_signatures.json`` as the rules read it; empty for a run from before the stage."""
    from rules import PsaSignature
    path = run / "psa_signatures.json"
    if not path.exists():
        return ()
    out = []
    for f in json.loads(path.read_text()).get("forms", []):
        iso = f.get("date_signed_iso")
        out.append(PsaSignature(
            document=f["document"], page=f.get("page"),
            signature_present=bool(f.get("signature_present")),
            stamp_present=bool(f.get("stamp_present")),
            signer_name=f.get("signer_name"), designation=f.get("designation"),
            department=f.get("department"), stamp_text=f.get("stamp_text"),
            stamp_ocr=f.get("stamp_ocr"),
            date_signed=date.fromisoformat(iso) if iso else None,
            date_signed_raw=f.get("date_signed"),
            signature_image=f.get("signature_image"),
            specimen=f.get("specimen"), specimen_status=f.get("specimen_status") or "",
        ))
    return tuple(out)


def build_report(run_dir: str | Path, *, with_citations: bool = True,
                 variant: str | None = None,
                 annual_pay: dict | None = None,
                 computed_at: datetime | None = None,
                 commutation_percent: str | None = None,
                 retirement_date: str | None = None,
                 case_type: str | None = None) -> dict:
    """``case_type`` is the type the department declared at intake (29 Sep 2026). Where given
    it selects the checklist column and the rules directly; the papers are still classified,
    and a disagreement becomes a finding rather than a reclassification."""
    run = Path(run_dir)
    manifest = json.loads((run / "manifest.json").read_text())
    identities = json.loads((run / "identities.json").read_text())
    docs_raw = json.loads((run / "documents.json").read_text())

    documents = tuple(_document(d) for d in docs_raw)
    # Attestation, from two readers. The page reading's "no attestation" stands only where
    # the second reader (pipeline.extract.check_attestation_by_ocr) also found none AND read
    # the foot of the page, where an attesting officer signs. A stamp found by either reader
    # makes the copy attested; a foot never reached leaves the question unjudged.
    assertions_file = run / "assertions.json"
    checked = {}
    if assertions_file.exists():
        for c in json.loads(assertions_file.read_text()).get("attestation_checked", []):
            prev = checked.get(c["page"])
            if prev is None or (c.get("marks") and not prev.get("marks")):
                checked[c["page"]] = c
    if checked:
        def _attested(d: Document) -> Document:
            if d.attested is not False:
                return d
            seen = [checked[p] for p in d.pages if p in checked]
            if not seen:
                return d
            if any(c.get("marks") for c in seen):
                return replace(d, attested=True)
            if not all(c.get("read_the_foot") for c in seen):
                return replace(d, attested=None)
            return d
        documents = tuple(_attested(d) for d in documents)
    # Whose CNIC is whose is decided here, from the names on the cards against the names on
    # the form -- not by the vision model, which cannot know it from the card alone.
    names = {}
    fields_file = run / "fields.json"
    if fields_file.exists():
        for f in json.loads(fields_file.read_text()).get("fields", []):
            if f["name"] in ("deceased_name", "claimant_name") and f.get("value"):
                names[f["name"]] = f["value"]
    # ...and which of those two names is the deceased is decided here, from the death
    # certificate and the printed "(LATE)" marker, because the extraction returned them
    # swapped on the real file. See rules.case_type.resolve_parties.
    death_names = tuple(
        d.person_named for d in documents
        if d.type in ("NADRA_DEATH_CERTIFICATE", "DEATH_OFFICE_ORDER") and d.person_named
    )
    # The claimant otherwise reaches the record only through stage 4, which reads Form D-I --
    # so a case filed on B-I or D-II arrives with no claimant at all, and every check keyed on
    # who is claiming quietly stops working. The prescribed form names them in its own subject
    # line, and that line is the one the PSA signed.
    form_text = " ".join(r.get("form_text", "") for r in identities if r.get("form_text"))
    parties = resolve_parties(
        names.get("deceased_name"),
        names.get("claimant_name") or claimant_from_form(form_text),
        death_certificate_names=death_names,
    )
    documents = assign_cnic_roles(documents, parties.deceased, parties.claimant)

    detected_type = classify_case_type(CaseRecord(case_ref=run.name, case_type="", documents=documents))
    declared_type = canonical_office_type(case_type)
    # The declaration (an office case type: a column of the document sheet) governs where there
    # is one: the checklist column, the engine's pension kind and every check keyed on the
    # path follow it. What the papers read as is kept beside it and compared by
    # rules.flags.check_declared_case_type.
    case_type = declared_case_type_result(declared_type, detected_type) if declared_type else detected_type
    if declared_type and not variant:
        variant = declared_type                       # the office type is the checklist column

    # Per-document assertions, where stage 6 has collected them. Without these the battery
    # runs over nothing and reports a clean case: a contradiction needs two documents.
    facts: dict = {}
    facts_path = run / "assertions.json"
    if facts_path.exists():
        facts = json.loads(facts_path.read_text())

    # A personnel number is 6-10 digits. The sweep also picked up 0000100001083 from a bank
    # form -- that is the claimant's CNIC 00001-0000108-3 with its separators stripped, and
    # admitting it would have invented a third "personnel number" and put a fabricated value
    # into F-1's title on a letter to a department.
    assertions = tuple(
        Assertion(a["field"], a["value"], Source(a["page"], a["document"]),
                  person=a.get("person"), role=a.get("role"))
        for a in facts.get("assertions", [])
        if a["field"] != "personnel_no" or 6 <= len(a["value"]) <= 10
    )
    annex_family = tuple(
        FamilyMember(m["name"], m["relation"], m["marital_status"],
                     Source(m["page"], m["document"]))
        for m in facts.get("annex_a_family", [])
    )
    frc_family = tuple(
        FamilyMember(m["name"], m["relation"], m["marital_status"],
                     Source(m["page"], m["document"]))
        for m in facts.get("frc_family", [])
    )
    # A recovery is only a defect where the sanction form denies it (BRAIN §16 item 8).
    # The sanction form denies a recovery whenever it states NO FIGURE. Keyword matching on
    # "no demand" was too narrow: the model answered a bare "No" on one sweep, which the
    # pattern missed, so the form read as having DECLARED a recovery and F-3 could not fire
    # even once the recovery itself was found. Absence of a money figure is the robust test --
    # "No", "Nil", and the printed "amounting to Rs. ....." placeholder all mean the same
    # thing, while a form that really declares one prints the amount.
    declared_text = (facts.get("form_recovery_declared") or {}).get("text", "")
    denies = _money_in(declared_text) is None
    # Recoveries come from the LPC only. §8.3 puts the LPC above every other document on
    # recoveries and demands, and restricting the source also discards two artefacts of
    # digit-stripping: prose on one page ("...joinent at 12/1/74 9/3" -> 11,217,493) and a
    # decimal amount on another (220,941.56 -> 22,094,156, wrong by a factor of 100).
    # Take the amount stage 6 computed; do NOT re-parse the prose here. Re-deriving the same
    # figure in a second place is how the two readings diverge: this line used to run
    # _money_in over the evidence sentence, and "w.e.f. 19.02.2026 ... amounting to
    # Rs. 126,355 is recoverable" yields 19.02 -- so F-3 fired, correctly, over Rs. 19,
    # against a real demand of Rs. 126,355. One reader, one figure, carried forward.
    recoveries = tuple(
        Recovery(amount=Decimal(str(rec.get("amount_exact", rec["amount"]))),
                 reason=rec["reason"],
                 source=Source(rec["page"], rec["document"]),
                 declared_on_sanction=not denies)
        for rec in facts.get("recoveries", [])
        if rec["document"] == "LPC"
    )

    fields_path = run / "fields.json"

    # -- F-5: the statutory timeline ------------------------------------------------------
    # BRAIN §4 gives family-pension sanction 15 days from Annex-A. The two dates that bound
    # that window are the Annex-A signing date and the date the PSA signed Form D-I, both of
    # which each document now reports about itself.
    dated = {}
    for d in facts.get("document_dates", []):
        parsed = _as_date(d["value"])
        if parsed and d["document"] not in dated:
            dated[d["document"]] = (parsed, d["page"])

    timeline: list[TimelineEvent] = []
    if "ANNEX_A" in dated:
        when, page = dated["ANNEX_A"]
        timeline.append(TimelineEvent("ANNEX_A_SIGNED", when, Source(page, "ANNEX_A")))

    # The 15-day sanction SLA (FD reformed procedure step D-B 2) has no printed end date in
    # this bundle. Form D-I's signature block is undated: the form prints a notification /
    # order date of 12-10-2021, four years before the Annexure-A that starts the clock, and
    # nothing beside the PSA's signature. An earlier attempt gave the schema a
    # psa_signature_date field to close that gap; the model answered 2021-07-26, a date that
    # appears on no page in the bundle.
    #
    # What the record does date is the forwarding letter (p.40, 20-05-2026), in which the
    # department states the case is "duly signed by the Additional Secretary (Admn) / Pension
    # Sanctioning Authority". So a signed sanction demonstrably existed by that date, and not
    # before Annexure-A. The interval measured here is therefore Annexure-A to the
    # department's own transfer of the signed case -- the interval the disposal dashboard is
    # for (§13.5 quotes both "~33 days to sanction" and "~75 days to reach AG") -- and the
    # note says outright that the sanction date itself is absent, because a flag must not
    # imply a precision the documents do not carry.
    if "FORWARDING_LETTER" in dated:
        when, page = dated["FORWARDING_LETTER"]
        annex_date = dated.get("ANNEX_A", (None, None))[0]
        gap = (when - annex_date).days if annex_date else None
        sane = gap is not None and 0 <= gap <= 365 * 3
        timeline.append(TimelineEvent(
            "SANCTION_FORWARDED_TO_AG", when, Source(page, "FORWARDING_LETTER"),
            sla_days=15 if sane else None,
            sla_from="ANNEX_A_SIGNED" if sane else None,
            sla_note=(
                "Form D-I bears no date beside the sanctioning authority's signature, so the "
                "sanction date itself cannot be verified from the record; the interval above "
                "runs to the department's own certification, in its letter of transfer, that "
                "the case had been signed. The undated signature is a separate shortcoming."
            ) if sane else None,
        ))

    # Form D-I still goes on the timeline, at the date it prints, but carries no SLA: a
    # notification date is not a sanction date, and attaching the 15-day requirement to it
    # would have accused the department of a five-year delay.
    if "FORM_D_I" in dated:
        when, page = dated["FORM_D_I"]
        timeline.append(TimelineEvent("FORM_D_I_NOTIFIED", when, Source(page, "FORM_D_I")))

    # Every NADRA FRC page, at the issue date it prints. A bundle can carry more than one
    # certificate (the deceased's and the claimant's), and each has its own six months
    # (rules.checklist.FRC_MAX_AGE_MONTHS), so each page goes on separately rather than the
    # first-per-document `dated` entry above. No SLA: the age is measured by the checklist
    # and the flag battery against the submission date, which is fixed further down.
    frc_pages_dated: set[int] = set()
    for d in facts.get("document_dates", []):
        if d.get("document") != "NADRA_FRC" or d["page"] in frc_pages_dated:
            continue
        when = _as_date(d["value"])
        if when is None:
            continue
        frc_pages_dated.add(d["page"])
        timeline.append(TimelineEvent("FRC_ISSUED", when, Source(d["page"], "NADRA_FRC")))

    # Each CNIC card's printed 'Date of Expiry', filed under whose card it is -- which is
    # decided above by assign_cnic_roles from the name on the card, never by the card's own
    # say-so. A lifetime card expires never and puts nothing here. The claimant's card must be
    # in force (SOP §5.2 AG-02); the deceased's is recorded for the trail and judged by nobody.
    role_of_page = {pg: d.type for d in documents if d.type.startswith("CNIC") for pg in d.pages}
    # On a self pension the claimant IS the pensioner, and the bundle's one CNIC copy is that
    # person's whatever name-matching made of it (the name comes from a form that may spell
    # it differently). A single unassigned card in a self-pension case is therefore the
    # claimant's for this purpose. In a family case an unassigned card could be either party's
    # and is left alone.
    from rules.case_type import _VARIANTS_FOR_CASE_TYPE
    from rules.checklist import SELF_PENSION_VARIANTS
    self_pension_case = bool(case_type.case_type) and set(
        _VARIANTS_FOR_CASE_TYPE.get(case_type.case_type, ())) <= SELF_PENSION_VARIANTS and bool(
        _VARIANTS_FOR_CASE_TYPE.get(case_type.case_type, ()))
    cnic_docs = [d for d in documents if d.type.startswith("CNIC")]
    if self_pension_case and len(cnic_docs) == 1 and cnic_docs[0].type == "CNIC":
        for pg in cnic_docs[0].pages:
            role_of_page[pg] = "CNIC_CLAIMANT"
    cnic_pages_dated: set[int] = set()
    for card in facts.get("cnic_cards", []):
        role = role_of_page.get(card.get("page"))
        if role not in ("CNIC_CLAIMANT", "CNIC_DECEASED") or card["page"] in cnic_pages_dated:
            continue
        raw = (card.get("date_of_expiry") or "").strip()
        if not raw or raw.upper() == "LIFETIME":
            continue
        when = _as_date(raw)
        # No CNIC expires before the scheme began; such a value is a misread label, not a card.
        if when is None or when < date(2002, 1, 1):
            continue
        cnic_pages_dated.add(card["page"])
        # OCR loses the card's labels: on ecb2 it dropped "Date of Issue" and printed the issue
        # date straight after "Date of Expiry", with the real expiry ("Lifetime") a line below.
        # An OCR expiry with no issue date beside it cannot be told from that misread, so it
        # is put in front of the officer to verify rather than treated as a defect.
        # The vision read makes the same swap on a rotated card (27d5, upside down: issue
        # 12.02.2026 returned as the expiry), so the rule holds whichever reader it was.
        unconfirmed = not (card.get("date_of_issue") or "").strip()
        timeline.append(TimelineEvent(
            ("CNIC_CLAIMANT_EXPIRES" if role == "CNIC_CLAIMANT" else "CNIC_DECEASED_EXPIRES")
            + ("_UNCONFIRMED" if unconfirmed else ""),
            when, Source(card["page"], role)))

    # -- F-6: name variants ---------------------------------------------------------------
    aliases = _aliases(
        facts.get("names", []),
        [names.get("deceased_name"), names.get("claimant_name")],
        documents,
    )

    stated_years = None
    stated_years_source = None
    if fields_path.exists():
        for f in json.loads(fields_path.read_text()).get("fields", []):
            if f["name"] == "qualifying_service_printed" and f.get("value"):
                m = re.search(r"(\d{1,2})", str(f["value"]))
                if m:
                    stated_years = int(m.group(1))
                    if f.get("page"):
                        stated_years_source = Source(int(f["page"]), f.get("document") or "")

    succession = next(
        (Source(d.pages[0], d.type) for d in documents if d.type == "SUCCESSION_CERTIFICATE"),
        None,
    )

    # The forwarding department, as its own letterhead prints it. Taken from the forwarding
    # letter rather than from a constant: it names the office an SLA finding is about and
    # heads the shortcoming letter, so on another bundle a literal would address the wrong
    # department. None where no page states one -- the templates fall back.
    forwarding_department = next(
        (o["value"] for o in facts.get("issuing_offices", [])
         if o["document"] == "FORWARDING_LETTER" and o.get("value")),
        None,
    )

    # The grade, for the gazetted/non-gazetted split on the service record. Taken from the
    # determination inputs where stage 7 has run, because that value is read from OCR rather
    # than from the vision model, which returned "BS. 12" for a BS-19 officer at confidence
    # 1.00. Where there is no determination the grade is simply unknown, and the checklist
    # falls back to which service document the bundle actually carries.
    # Read off a pay document by OCR in stage 6, which is where it is most reliable: the
    # vision model returned "BS. 12" for a BS-19 officer at confidence 1.00.
    pay_scale_bps = next(
        (int(a["value"]) for a in facts.get("assertions", [])
         if a.get("field") == "pay_scale_bps" and str(a.get("value", "")).isdigit()),
        None,
    )
    # What the pay certificate says the servant was drawing. Shown whether or not a pension
    # is computed: an officer keying three years in wants the one the papers already state.
    basic_pay_read = next(
        (int(a["value"]) for a in facts.get("assertions", [])
         if a.get("field") == "basic_pay" and str(a.get("value", "")).isdigit()),
        None,
    )
    det_file = run / "determination.json"
    if pay_scale_bps is None and det_file.exists():
        try:
            pay_scale_bps = json.loads(det_file.read_text())["determination"]["inputs"]["bps"]
        except (KeyError, ValueError):
            pay_scale_bps = None
    if pay_scale_bps is None:
        # Fall back to the grade printed on the sanction form. The determination is produced
        # two stages later and not at all for a case the engine cannot compute, so a document
        # check that waits for it reports BOTH service records missing on a BS-19 officer --
        # which is what a clean run of the golden case did.
        pay_scale_bps = pay_scale_from_form(form_text)

    # Where the officer selected no column, derive one. The prescribed form settles four of
    # the eleven outright, and for a Form D-II the claimant's stated relationship usually
    # settles the rest -- so the common case needs no selection at all.
    claimant_relation = next(
        (str(f["value"]) for f in (json.loads(fields_path.read_text()).get("fields", [])
                                   if fields_path.exists() else [])
         if f.get("name") == "claimant_relation" and f.get("value")),
        "",
    )
    # The claimant's marital status, as NADRA records it (§8.3), falling back to Annex-A.
    # It is what separates an unmarried daughter's column from a widowed or divorced one.
    def _marital_of(name: str | None) -> str:
        if not name:
            return ""
        from difflib import SequenceMatcher

        def key(v: str) -> str:
            return " ".join(sorted("".join(c for c in t.lower() if c.isalpha())
                                   for t in (v or "").split()))
        target = key(name)
        for rows in (facts.get("frc_family", []), facts.get("annex_a_family", [])):
            for m in rows:
                if SequenceMatcher(None, target, key(m.get("name", ""))).ratio() >= 0.85:
                    return str(m.get("marital_status") or "")
        return ""

    # What the department said it was sending. Its own subject line names the claimant class
    # where the case is not an ordinary widow's, and it is typed rather than handwritten.
    forwarding_subject = " ".join(
        str(r.get("evidence") or "") for r in identities
        if r.get("document_type") == "FORWARDING_LETTER"
    )[:1200]
    detected = suggest_variant(
        case_type.case_type, form_text, alternatives=tuple(case_type.alternatives),
        claimant_relation=claimant_relation,
        claimant_marital=_marital_of(names.get("claimant_name") or parties.claimant),
        forwarding_subject=forwarding_subject,
    )
    variant_source = ("declared" if declared_type and variant == declared_type else "selected") if variant else None
    if not variant and detected.decided:
        variant, variant_source = detected.variant, "detected"

    # -- item 19: how old is this case? ---------------------------------------------------
    # From the event that created the entitlement, to the day the department sent the case
    # in. The sanction form states the first; the forwarding letter is dated with the second.
    # Form D-I states the death in service as date_of_death; Form D-II states the pensioner's
    # death as date_of_death_of_pensioner. Reading only the first sent a D-II case to the form
    # text, which yielded the pensioner's RETIREMENT in 1986 -- a date no rule pack covers --
    # and the report crashed on it.
    #
    # The determination's own date comes FIRST where there is one. Stage 7 resolves the date
    # of death through the field read, the form's "expired on" clause and the officer's own
    # entry, in that order, and records what it settled on. Re-deriving it here from the
    # field alone put two different death dates in one report: the disabled-son case computed
    # its pension on 2021-02-28, read off the form, while item 19 measured lateness from
    # 2024-02-28, the field read -- the same value the model had also put in the retirement
    # box -- and so called a five-year-old case recent and asked for no explanation.
    entitlement_date = None
    det_inputs: dict = {}
    det_file_for_date = run / "determination.json"
    if det_file_for_date.exists():
        try:
            det_inputs = json.loads(det_file_for_date.read_text())["determination"]["inputs"]
        except (KeyError, ValueError):
            det_inputs = {}
    for key in ("date_of_death_of_pensioner", "date_of_death"):
        if det_inputs.get(key):
            entitlement_date = _as_date(str(det_inputs[key]))
            if entitlement_date is not None:
                break
    if entitlement_date is None:
        for f in (json.loads(fields_path.read_text()).get("fields", [])
                  if fields_path.exists() else []):
            if f["name"] in ("date_of_death", "date_of_death_of_pensioner") and f.get("value"):
                entitlement_date = _as_date(f["value"])
                if entitlement_date is not None:
                    break
    if entitlement_date is None:
        entitlement_date = entitlement_date_from_form(form_text)

    # A bundle can carry several forwarding letters, and their dates are not all the
    # transmittal: this case read 1997-07-20 and 18/03/2021 alongside the real 20 May 2026,
    # the first two being dates the letters MENTION. The transmittal is the latest of them,
    # and a date before the entitlement arose is not a transmittal at all.
    def _dates_from(*documents: str) -> list:
        return [
            d for d in (
                _as_date(x["value"]) for x in facts.get("document_dates", [])
                if not documents or x["document"] in documents
            ) if d is not None and (entitlement_date is None or d >= entitlement_date)
        ]

    # The forwarding letter first. Failing that, the newest document in the bundle: this
    # widow's forwarding letter was dated only "2026", which parses to nothing, and a case
    # cannot have been submitted before the most recent paper in it. A floor is worth more
    # than no date at all, and it errs towards calling a case RECENT rather than late --
    # which is the safe direction, because the requirement stands either way if we are wrong.
    forwarded = _dates_from("FORWARDING_LETTER") or _dates_from()
    submitted_date = max(forwarded) if forwarded else None

    # -- who signed each prescribed form, and the specimen on file (pipeline.signatory) ------
    psa_signatures = _psa_signatures(run)

    record = CaseRecord(
        case_ref=run.name,
        psa_signatures=psa_signatures,
        case_type=case_type.case_type or "",
        documents=documents,
        assertions=assertions,
        annex_a_family=annex_family,
        frc_family=frc_family,
        recoveries=recoveries,
        pay_lines=pay_lines_from_fields(_fields_document(fields_path)),
        form_dates=form_dates_from_fields(_fields_document(fields_path)),
        timeline=tuple(timeline),
        aliases=aliases,
        stated_qualifying_service_years=stated_years,
        stated_qualifying_service_source=stated_years_source,
        succession_certificate=succession,
        unreadable=tuple(
            (u["page"], u["document"], u["reason"]) for u in facts.get("unreadable", [])
        ),
        ambiguous_dates=two_digit_year_dates(run, facts),
        disputed_reads=disputed_reads_from_fields(_fields_document(fields_path)),
        # These four were literals of the golden case -- diary 41759, the School Education
        # Department, and "Waqar Abdul Basit" -- sitting in the middle of the production
        # path. On any other bundle the shortcoming letters would have gone out carrying
        # this case's claimant and this case's department. Derived or left None; the
        # notification templates already fall back to the case reference and to "the
        # forwarding department", which is honest where the record does not say.
        #
        # diary_no stays None deliberately: the AG's diary number is a handwritten marginal
        # stamp, transcribed as "41759 [?]" with the uncertainty marker, and a receipt
        # number quoted wrongly in a letter to a department is worse than one omitted.
        entitlement_date=entitlement_date,
        submitted_date=submitted_date,
        case_variant=variant,
        declared_case_type=declared_type,
        declared_pipeline_types=pipeline_types_for(declared_type),
        detected_case_variant=detected.variant if detected.decided else None,
        detected_case_type=detected_type.case_type,
        detected_case_type_confidence=detected_type.confidence,
        detected_case_type_evidence=detected_type.evidence,
        detected_case_type_alternatives=tuple(detected_type.alternatives),
        pay_scale_bps=pay_scale_bps,
        diary_no=None,
        forwarding_department=forwarding_department,
        forwarding_department_ur=None,
        claimant_name=parties.claimant,
        claimant_relation=claimant_relation or None,
        frc_applicant_relation=((facts.get("frc_applicant") or {}).get("relation_with_hof") or None),
        party_roles_note=parties.unresolved_reason,
        party_roles_corrected=parties.corrected,
        processed_on=(computed_at or _DEFAULT_COMPUTED_AT).date(),
    )

    stage4: dict = {}
    det_path = run / "determination.json"
    if det_path.exists():
        stage4 = json.loads(det_path.read_text())

    # A self pension under the December 2024 amendment: the base is the three-year average
    # the officer supplied at intake. Stage 7 computes only the family-pension path, so this
    # is where a superannuation, retiring, invalid or compulsory-retirement case is worked
    # out -- and only where the figures are there. Without them the engine refuses, which is
    # the point: a single pay slip is not the average the rule requires.
    self_pension_error = None
    self_pension_defect = None
    # The date of retirement the officer typed at intake is the fallback where the sanction
    # form's own text yields none; the form governs where it speaks.
    retirement_for_self = entitlement_date
    if retirement_for_self is None and retirement_date:
        try:
            retirement_for_self = date.fromisoformat(str(retirement_date))
        except ValueError:
            retirement_for_self = None
    # "Average Basic pay" as the Form B-I prints it, from its OCR text. Read here only for a
    # self-pension form; a family form's figures are stage 7's business.
    from rules.case_type import printed_form_figures
    printed_average = None
    printed_base_note = None
    if case_type.prescribed_form and str(case_type.prescribed_form).startswith("B"):
        figs = printed_form_figures(form_text)
        if figs.get("average_basic_pay_rs"):
            printed_average = Decimal(figs["average_basic_pay_rs"])
            printed_base_note = "Average Basic pay as printed on the sanction form"
        elif figs.get("basic_pay_rs") or figs.get("drawing_pay_rs"):
            # No average printed: the form states only the LAST-DRAWN basic pay. Under rule
            # 4.4(4) as substituted the base is a three-year average, which on any rising
            # scale is LOWER than the last-drawn figure -- so this is an upper bound, shown
            # provisionally so the officer sees a figure and the case sits in the HOLD lane
            # until the three 1 July figures are keyed and replace it.
            printed_average = Decimal(figs.get("basic_pay_rs") or figs["drawing_pay_rs"])
            printed_base_note = ("last-drawn Basic Pay as printed on the sanction form -- an "
                                 "UPPER BOUND, not the three-year average rule 4.4(4) requires")
    # Which pension the engine computes. Form B-IV governs both an invalid and a compulsory
    # retirement pension and §4.1 rightly leaves the type undecided between them; neither
    # falls at the superannuation age, so defaulting an undecided B-IV to SUPERANNUATION
    # made the engine refuse a 52-year-old's invalid pension as "short of 60".
    pension_kind = case_type.case_type
    if pension_kind is None:
        alts = set(case_type.alternatives or ())
        if alts and alts <= {"INVALID_PENSION", "COMPULSORY_RETIREMENT_PENSION"}:
            pension_kind = "INVALID_PENSION"
    if not stage4 and (annual_pay or printed_average is not None):
        try:
            stage4 = _self_pension(run, pay_scale_bps, annual_pay, retirement_for_self,
                                   pension_kind, fields_path,
                                   computed_at=computed_at,
                                   commutation_percent=commutation_percent,
                                   basic_pay_read=basic_pay_read,
                                   printed_average=printed_average,
                                   printed_base_note=printed_base_note)
        except Exception as exc:                         # noqa: BLE001
            # Without the engine's figures (scope decision of 7 Oct 2026): a refusal quotes what it
            # summed, and the text reaches the screen and the department's letter as a finding.
            from rules.scope import strip_money
            self_pension_error = strip_money(str(exc))
            # A refusal that says the papers contradict each other is a defect in the
            # department's paperwork, and belongs in the shortcoming letter -- not only in
            # the determination panel. The engine names the contradiction; this carries it
            # to the officer as a finding with the same weight as any other HIGH.
            self_pension_defect = self_pension_error

    # What the pipeline said when it declined to determine, quoted rather than re-derived.
    # BRAIN §15.2: "Say so, precisely, and route to a human... prefer the visible gap every
    # time." Stages 4 and 7 already say precisely why they stopped -- no Form D-I in the
    # bundle, no inputs to compute from -- and the sentence reached the run log and stopped
    # there. The officer's screen said "Not computed." and nothing else, which is a gap that
    # is neither visible nor precise. Read from disk, never inferred here: working out why
    # the engine refused, from the outside, is the reporting layer reasoning about a
    # determination, and §15.1 puts that out of bounds.
    determination_gap = None
    gap_path = run / "determination_gap.json"
    if not stage4 and gap_path.exists():
        try:
            determination_gap = json.loads(gap_path.read_text()) or None
        except ValueError:
            determination_gap = None

    # Whether the officer's three pay figures would actually produce a determination for this
    # case. True only on a self-pension column: _self_pension builds a SelfPensionCase, so on
    # a family-pension bundle the figures reach nothing and asking for them sends an officer
    # to fetch a service book for no result. A case with no column settled yet counts only if
    # every column it could be is a self-pension one.
    from rules.checklist import SELF_PENSION_VARIANTS
    columns = {variant} if variant else set(detected.candidates)
    awaiting_pay_figures = bool(
        not annual_pay
        and columns and columns <= set(SELF_PENSION_VARIANTS)
    )

    # BLOCKING-21: the pack in force when the entitlement arose. Falls back to the
    # submission date only where the event date could not be read.
    #
    # `date.today()` was the third fallback here, and it is the one thing loader.py forbids in
    # as many words -- "effective_date is an argument, never date.today(): the engine must
    # produce the same answer for a 2021 case whenever it is run". It made WHICH LAW APPLIES a
    # fact about the day the report was built: the same bundle rebuilt either side of
    # 2 December 2024 gets a different pension-base rule, silently. The battery below still
    # needs a pack, so one is selected -- but the basis is recorded, and where it is not the
    # case's own date that is reported as the gap it is rather than passed off as a reading.
    pack_basis = (
        f"entitlement date {entitlement_date.isoformat()}" if entitlement_date
        else f"date the case was forwarded, {submitted_date.isoformat()}" if submitted_date
        else None
    )
    from rules import PackError, load_all
    # The last resort is the newest pack's own effective date, NOT `date.today()`. The
    # battery has to run over the record even where no date could be read, so a pack must
    # be chosen -- but choosing it by the clock made two auditors reading the same bundle on
    # two different days get different reference values out of the same papers, which is the
    # property SOP §8.5.1 and BUILD §6.2 exist to forbid. `load_all` is sorted by
    # effective_from, so the last entry is deterministic and, for any date from the newest
    # pack onwards, is the pack `date.today()` would have picked anyway. `pack_basis` stays
    # None so the report still reports the gap rather than passing this off as a reading.
    pack_on = entitlement_date or submitted_date or load_all()[-1].effective_from
    try:
        pack = select_pack(effective_date=pack_on)
        no_pack_in_force = None
    except PackError as exc:
        # A date before the earliest pack -- a pensioner who died in 2011, the Widow Daughter
        # case -- has no pack in force, and the battery still needs one to run over the record.
        # The nearest pack in time is used for the CONSISTENCY CHECKS ONLY, and the report says
        # so; a determination never rests on it (the D-II engine carries its own rules, and
        # the D-I engine selects its own pack and refuses where none is in force).
        packs = load_all()
        pack = min(packs, key=lambda p: abs((p.effective_from - pack_on).days))
        no_pack_in_force = (
            f"{exc} The consistency checks below were run against {pack.id}, the pack nearest "
            f"in time, for that purpose only."
        )
    rule_pack_gap = no_pack_in_force if no_pack_in_force else None if pack_basis else (
        "No entitlement date and no forwarding date could be read from the bundle, so the "
        "rule pack in force for this case could not be established (BLOCKING-21). The "
        f"consistency checks below were run against {pack.id}, selected on the date this "
        "report was built and for that purpose only. No determination may rest on it: which "
        "law applies is a fact about the case, not about when it was processed."
    )
    # A case type with no checklist defined is a coverage gap, and it must be reported as
    # one rather than crash the report. Seven of the eight paths have no checklist yet.
    checklist = None
    checklist_gap = None
    if variant:
        # The officer selected a column of the AG office sheet at intake. That settles which
        # documents this case needs, so the checklist runs whether or not the bundle's own
        # papers were enough to derive a case type -- and a self-pension bundle, where Form
        # B-I governs two different paths and neither can be told from the other, is exactly
        # the case that has a selected variant and no derived case type.
        checklist = run_checklist(record, variant=variant)
    else:
        checklist_gap = (
            "No document checklist could be applied: " + detected.evidence
            + (f". Choose one of: {', '.join(detected.candidates)}."
               if detected.candidates else "")
        )

    # The battery runs over whatever the record holds, always. It used to be gated on a
    # derived case type, which meant a self-pension bundle -- where Form B-I governs two
    # paths and §4.1 rightly declines to choose -- had its checks silently skipped: that
    # case carries two different personnel numbers and reported zero flags. Only one of the
    # nine checks needs the case type (a succession certificate matters in a family-pension
    # case and not otherwise), and it guards itself.
    # The emoluments the determination rests on, so the battery can raise the form/pay-record
    # discrepancy the engine computed through (rules.flags.check_emoluments_reconciliation).
    # Rebuilt from the determination artefact rather than re-summed here: this layer reports
    # what stage 7 established, it does not reckon.
    emoluments = _emoluments_from(stage4.get("emoluments")) if stage4 else None
    if emoluments is not None:
        record = replace(record, emoluments=emoluments)
    # What the sanctioning authority left blank on its own form. Read from the extraction, in
    # the form's own words, so the finding quotes the field the department has to fill in.
    blanks: list[str] = []
    if fields_path.exists():
        totals = dict(json.loads(fields_path.read_text()).get("printed_totals") or {})
        # The form's OCR text is the second reading the determination already falls back on
        # (pipeline.extract, SOP §6.3(9)). 27d5 prints "drawing Pension @ Rs.19,874/- pm" and
        # was computed from it -- while this check, reading the vision fields alone, told the
        # department it had left the figure blank.
        from rules.case_type import printed_form_figures
        for key, value in printed_form_figures(form_text).items():
            if totals.get(key) in (None, ""):
                totals[key] = value
        if (json.loads(fields_path.read_text()).get("prescribed_form") == "FORM_D_II"
                and totals.get("pension_drawn_rs") in (None, "")
                and totals.get("net_pension_rs") in (None, "")
                and totals.get("total_pension_rs") in (None, "")):
            blanks.append("the pension in payment (\"drawing pension / family pension @\"), "
                          "\"Net pension\" and \"Total pension\"")
    if blanks:
        record = replace(record, prescribed_form_blanks=tuple(blanks))
    if self_pension_defect:
        record = replace(record, self_pension_defect=self_pension_defect)
    flags = run_battery(record, pack)
    # Only the findings a reviewer must act on, one short line each, most serious first (office
    # rule, 30 Sep 2026). The rest are kept in the report, set aside with their reason.
    from rules.flag_curation import curate
    flags, flags_set_aside = curate(flags, checklist, variant)
    # The determination is passed, not dropped. It used to be `None` here, which made both
    # HOLD branches in rules/verdict.py unreachable from the pipeline: a case whose figures
    # rest on an unresolved reading -- BLOCKING-06's gratuity is Rs 33,605 on one reading and
    # Rs 4,989,130 on the other -- came back FORWARD, on a rationale that positively asserted
    # "no unresolved rule item engaged" while the determination beside it in the same report
    # said `provisional: true`. api/decisions.py then read that FORWARD as clean, so the case
    # could be forwarded with no justification and no override recorded against it.
    rec = recommend(checklist, flags, stage4.get("determination")) if checklist else None
    notes = notify(record, checklist, flags, rec) if checklist and rec else ()

    report = {
        "case_ref": run.name,
        "diary_no": record.diary_no,
        "forwarding_department": record.forwarding_department,
        "claimant_name": record.claimant_name,
        "source": {
            "file": manifest["source_file"],
            "sha256": manifest["source_sha256"],
            "source_pages": manifest["source_pages"],
        },
        # The type the rules ran on, with where it came from; the AI's own reading is kept
        # whole beside it so the two can always be compared.
        "case_type": {**case_type.to_dict(),
                      "source": "declared" if declared_type else "detected",
                      "declared": declared_type,
                      "detected": detected_type.case_type},
        "case_type_detected": detected_type.to_dict(),
        "documents": [{"type": d.type, "pages": list(d.pages), "present": d.present} for d in documents],
        "pages": identities,
        # Stage 4 output, where it has run. Still null rather than fixture-filled when it
        # has not: §15 rule 12, never demonstrate an untested path as working.
        # ... and never with a computed figure in it (business decision of 7 Oct 2026: this
        # release does no pension calculations; rules.scope). The engine's checks remain.
        "emoluments": scrub_emoluments(stage4.get("emoluments")),
        "determination": scrub_determination(stage4.get("determination")),
        "checklist": _found_as({**checklist.to_dict(), "result_line": checklist.result_line}, run, variant) if checklist else None,
        # Pages the bundle contains that produced no document. A MISSING line can only be
        # trusted when this is empty: the widow's affidavit was on page 12, classified OTHER
        # and dropped, and the case was returned for a document it contained. An officer
        # testing with a case they know is complete must be told which pages we could not
        # read, rather than shown a shortcoming we invented.
        "pages_unaccounted": sorted(
            {p["page"] for p in manifest["pages"]}
            - {pg for d in documents for pg in d.pages}
        ),
        # What stage 6 actually read, per document, with the page it read it on -- what the
        # Extracted Data tab shows. Built as Pension-AG's report builds it; without it the
        # tab was empty on every case.
        "extracted": {
            "assertions": facts.get("assertions", []),
            "annex_a_family": facts.get("annex_a_family", []),
            "frc_family": facts.get("frc_family", []),
            "frc_applicant": facts.get("frc_applicant"),
            "document_dates": facts.get("document_dates", []),
            "names": facts.get("names", []),
            "issuing_offices": facts.get("issuing_offices", []),
            "recoveries": facts.get("recoveries", []),
            "unreadable": facts.get("unreadable", []),
        },
        "self_pension_error": self_pension_error,
        # Why there is no determination, in the words of the stage that refused, and whether
        # the one route that is open to this case has been taken.
        "determination_gap": determination_gap,
        # Why the rule pack below is not evidence of anything, where it is not. None when the
        # pack was chosen by a date actually read off the case.
        "rule_pack_gap": rule_pack_gap,
        # The basic pay the bundle's own pay certificate prints, for the officer keying the
        # three-year average in. Never substituted for what they type -- see _self_pension.
        "basic_pay_read": basic_pay_read,
        "awaiting_pay_figures": awaiting_pay_figures,
        "case_variant": variant,
        "case_variant_source": variant_source,
        "case_variant_evidence": detected.evidence,
        "case_variant_candidates": list(detected.candidates),
        "checklist_gap": checklist_gap,
        "flags": [f.to_dict() for f in flags],
        "flags_set_aside": flags_set_aside,
        "recommendation": rec.to_dict() if rec else None,
        "notifications": [n.to_dict() for n in notes],
        "provenance": {
            "vl_model": "qwen3-vl-30b-a3b-fp8",
            "ocr_model": "paddleocr-vl-1.6",
            "rule_pack_version": pack.id,
            "rule_pack_selected_on": pack_basis or "no case date could be read (see rule_pack_gap)",
            "prompt_version": "AGPB-EXTRACT-PROMPT-1.0",
            "pages_read": len(identities),
            "documents_identified": len(documents),
            "rag_corpus": "pension rules + FD procedure + forms (208 chunks)",
        },
    }
    return _cite_all(report) if with_citations else report


if __name__ == "__main__":
    run_dir = sys.argv[1] if len(sys.argv) > 1 else "artifacts/golden"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(run_dir) / "case_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(run_dir)
    atomic_write_text(out, json.dumps(report, indent=2, ensure_ascii=False))
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    print(f"  case type : {report['case_type']['case_type']} ({report['case_type']['case_type_confidence']})")
    cl = report["checklist"]
    print(f"  checklist : {cl['result']} {cl['satisfied']}/{cl['required']} (missing {cl['missing']})" if cl else "  checklist : n/a")
    print(f"  flags     : {len(report['flags'])}")
    print(f"  verdict   : {report['recommendation']['verdict'] if report['recommendation'] else 'n/a'}")
