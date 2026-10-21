"""Stage 4: field extraction over the identified documents. BUILD §5 stage 4, BRAIN §5.3.

Runs only over the documents the determination actually needs -- the prescribed form, the LPC
and the salary statement -- rather than all 43 pages. Stage 3 has already said which page is
which, so stage 4 asks each document the questions its own schema was written for, which is
what stops the model mislabelling an amount it had no business reading.

Determination-critical pages are read with :func:`extract_page_confirmed`, which reads twice
and requires the two reads to agree. BRAIN §5.3 requires corroboration for the fields that
change the money, and ``client.py`` documents a reproducible first-read failure that no
per-field confidence exposes. Two reads cost about a minute a page; the pension it authorises
lasts a lifetime.

The reckonable/non-reckonable split is **not** taken from the model. The model reports the
printed label and the amount; ``extraction.classify`` maps the label to a component by rule,
and the rule pack says which components are reckonable. BRAIN §9.3 calls that split "the most
consequential extraction judgement you make", and on this case the excluded allowances are 84%
of the pensionable amount.
"""

from __future__ import annotations

import os
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable

from pipeline.ingest import atomic_write_text, read_checkpoint
from extraction.classify import classify_pay_label
from extraction.client import ExtractionError, extract_page_confirmed
from rules import PayComponent, reckon, select_pack
from rules.engine import DeathInServiceCase, determine_family_pension_death_in_service
from rules.money import fmt
from rules.case_type import ambiguous_death_date_from_form, death_date_from_form, printed_form_figures
from rules.dii import (InputMissing, DEATH_AFTER_RETIREMENT, REGRANT_AFTER_WIDOW_DEATH, UNKNOWN,
                       CaseClass, CaseTypeNotDetermined, DIIRules,
                       DeathAfterRetirementCase, Provenance, classify_case,
                       determine_family_pension_death_after_retirement)

#: Documents read at once in stage 6. Each is a confirming double read, so twice this many
#: requests are in flight; matched to the vision server's --max-num-seqs.
#:
#: Tunable without a redeploy (PENSION_ASSERTION_CONCURRENCY); see IDENTIFY_CONCURRENCY in
#: pipeline/run.py for why. Stage 6 is the dominant cost of a run -- 451.8s of a 631.6s run
#: measured 19 Oct 2026, at 1.76x parallelism -- so this is the one with the most to give.
ASSERTION_CONCURRENCY = max(1, int(os.environ.get("PENSION_ASSERTION_CONCURRENCY") or 2))

#: Pages whose printed heading stage 3b reads at once (see prefetch_page_ocr). Was one at a
#: time until 19 Oct 2026.
ASSEMBLE_OCR_CONCURRENCY = max(1, int(os.environ.get("PENSION_ASSEMBLE_OCR_CONCURRENCY") or 8))

#: Stage 6's own OCR sweeps -- recoveries off every LPC, and the attestation second reader.
#: Both were plain `for` loops issuing one ~8s call at a time while the vision reader beside
#: them sustained 4-6 concurrent. Measured over four real runs on 21 Oct 2026: 22-31 OCR
#: calls, 156-211s busy, span 152-189s -- a mean concurrency of 1.0, against a wall clock of
#: 221-268s. The reads are independent and go to the PaddleOCR server (its own chip), so they
#: contend with nothing the vision model is doing.
#:
#: Same discipline as prefetch_page_ocr: the reads happen in the pool, every mutation of
#: `result` happens on the calling thread, and results are folded in SUBMISSION order, so the
#: recoveries already-seen set still grows in page order and progress lines still arrive in it.
#:
#: Four, not more. Ten real pages read sequentially took 31.7s; pooled at 4, 17.9s (1.80x);
#: pooled at 8, 17.6s (1.80x). PaddleOCR has one chip and decodes tokens like any other reader,
#: so it saturates around four and the rest is queueing. These also multiply with
#: PENSION_MAX_CONCURRENT_RUNS, and eight runs at eight would put 64 requests on that one chip
#: for no gain over 32.
OCR_SWEEP_CONCURRENCY = max(1, int(os.environ.get("PENSION_OCR_SWEEP_CONCURRENCY") or 4))

FIELDS = "fields.json"
DETERMINATION = "determination.json"


class ExtractionGap(RuntimeError):
    """A determination-critical field could not be read. Never defaulted around."""


@dataclass(frozen=True)
class ExtractedField:
    """One value, with where it came from and how sure the reader was."""

    name: str
    value: str | None
    confidence: float
    page: int
    document: str
    unreadable_reason: str | None = None

    @property
    def usable(self) -> bool:
        """BRAIN §5.3: below 0.80 is never silently accepted."""
        return self.value is not None and self.confidence >= 0.80


def _val(node: Any, name: str, page: int, doc: str) -> ExtractedField:
    if not isinstance(node, dict):
        return ExtractedField(name, None, 0.0, page, doc, "field absent from the extraction")
    return ExtractedField(
        name=name,
        value=None if node.get("value") in (None, "") else str(node["value"]),
        confidence=float(node.get("confidence") or 0.0),
        page=page,
        document=doc,
        unreadable_reason=node.get("unreadable_reason"),
    )


#: The one document a pay base may be read from, in order of authority (decision H2, 7 Oct
#: 2026): the LPC first; then the prescribed form the sanctioning authority signed; the AG's own
#: salary statement last. Lines are never merged across documents.
PAY_SOURCE_AUTHORITY = ("LPC", "FORM_D_I", "FORM_B_I", "SALARY_STATEMENT")


def pay_line_document(line: dict, extracted: dict) -> str:
    """Which document a stage-4 pay line came from. Tagged since 7 Oct 2026; older records are
    read by page: the prescribed form's page is the form, the rest the salary statement where
    one was read."""
    if line.get("document"):
        return str(line["document"])
    page = line.get("page")
    if page is not None and page == extracted.get("prescribed_form_page"):
        return str(extracted.get("prescribed_form") or "FORM_D_I")
    # Older still: no form page recorded, but every form field carries its page and document.
    for f in extracted.get("fields") or []:
        if page is not None and f.get("page") == page and f.get("document") in ("FORM_D_I", "FORM_B_I"):
            return str(f["document"])
    totals = extracted.get("printed_totals") or {}
    return "SALARY_STATEMENT" if "salary_statement_gross" in totals else "PAY_RECORD"


def single_source_pay_lines(extracted: dict) -> tuple[list[PayComponent], str | None]:
    """The pay lines of the most authoritative document that printed any, and which it was.

    Within that one document a line restated (the same component at the same amount) is one
    fact; across documents nothing is pooled. ``([], None)`` where no pay line was read."""
    by_doc: dict[str, list[PayComponent]] = {}
    for c in extracted.get("pay_components") or []:
        by_doc.setdefault(pay_line_document(c, extracted), []).append(PayComponent(
            printed_label=c["printed_label"], component=c["component"],
            amount=int(c["amount"]), page=c.get("page")))
    order = [*PAY_SOURCE_AUTHORITY, *sorted(d for d in by_doc if d not in PAY_SOURCE_AUTHORITY)]
    for doc in order:
        if by_doc.get(doc):
            seen: dict[tuple[str, int], PayComponent] = {}
            for c in by_doc[doc]:
                seen.setdefault((c.component, int(c.amount)), c)
            return list(seen.values()), doc
    return [], None


def _pay_components(data: dict, page: int, printed_total: int | None = None) -> list[PayComponent]:
    """Turn the model's printed labels into classified components. Never trusts its judgement.

    Drops any component whose amount equals the form's own printed total. On the real Form D-I
    the page reads "... Total Pay Rs. 192030/(2) Orderly Allowance (if any) Rs. ____" -- the
    total, then an empty field -- and the model paired 192,030 with the next label, returning
    "Orderly Allowance 192,030". Orderly allowance is RECKONABLE, so summing it would have
    put the pensionable pay at 384,060 instead of 192,030 and doubled the pension for life.

    The reconciliation against the printed total would have caught it (that is what §8.4 calls
    the highest-value check in the system), but a component that *is* the total is a
    recognisable error with a cheap deterministic test, and catching it here keeps the
    reconciliation as an independent check rather than the only one.
    """
    out: list[PayComponent] = []
    for row in data.get("pay_components") or []:
        label = (row.get("printed_label") or "").strip()
        amount = row.get("amount_rs")
        if not label or amount in (None, ""):
            continue
        verdict = classify_pay_label(label)
        # An UNRECOGNISED label is carried, not dropped. `classify_pay_label` marks it
        # ``is_line_item=False`` because it must never be SUMMED -- and `rules.emoluments`
        # is the layer that decides that: it puts an unknown component in `Emoluments.unknown`,
        # never in either total, and `needs_human` then refuses the determination (EMOL-08).
        # Dropping it here made that refusal unreachable from the pipeline, so an
        # unrecognised line that was in fact RECKONABLE understated a pension for life with
        # nothing raised anywhere -- and where no printed total had been extracted, the
        # reconciliation could not catch it either.
        #
        # The figure is what makes this safe. The model returns arbitrary page furniture in
        # `pay_components` -- "City: LAHORE", a vendor number, a CNIC repeated to the schema
        # cap -- and every one of those rows carries ``amount_rs: null`` and is already gone
        # at the guard above. What survives here is a row with a rupee figure on it and a
        # label no rule recognises, which is exactly the case an officer has to settle.
        if not verdict["is_line_item"] and verdict["component"] != "unknown":
            continue          # printed totals, deductions, recoveries: never summed
        # The drop above is for a label that BORROWED the total. Basic pay is exempt: on a
        # form whose only reckonable line is the basic pay -- the OSD-post case prints
        # "Basic Pay 89,530 / Total 89,530" -- the basic pay equals the total by arithmetic,
        # not by misreading, and dropping it left the prescribed form contributing no pay
        # line at all to the determination it governs.
        if (printed_total is not None and int(amount) == int(printed_total)
                and verdict["component"] != "basic_pay"):
            continue
        out.append(
            PayComponent(
                printed_label=label,
                component=str(verdict["component"]),
                amount=int(amount),
                page=page,
            )
        )
    return out


def stage_extract(
    run_dir: str | Path,
    *,
    progress: Callable[[str], None] | None = None,
    carry: dict | None = None,
) -> dict:
    """Read the determination-critical documents. Resumable: skips what is already on disk.

    ``carry`` (a resubmission, ``pipeline.carryover``): a read whose page is carried from the
    earlier round, in the same role there -- the prescribed form, a pension document, the
    salary statement, the LPC -- is taken from that round rather than read again. Only reads
    of new pages reach the model. Without it the stage runs exactly as it always has.
    """
    run = Path(run_dir)
    out_path = run / FIELDS
    done = read_checkpoint(out_path)
    if done is not None:
        return done

    manifest = json.loads((run / "manifest.json").read_text())
    image_for = {p["page"]: run / p["image_path"] for p in manifest["pages"]}
    documents = json.loads((run / "documents.json").read_text())
    reuse = _ExtractReuse(carry, documents) if carry else None

    def first(doc_type: str) -> dict | None:
        for d in documents:
            if d["type"] == doc_type and d["pages"]:
                return d
        return None

    result: dict[str, Any] = {"fields": [], "pay_components": [], "printed_totals": {}}

    # -- the prescribed form: whichever of the two this bundle carries --------------------
    # Stage 4 accepted FORM_D_I and nothing else, so a bundle carrying the death-of-a-
    # pensioner form was rejected as having "no prescribed form" -- of a bundle whose
    # prescribed form was sitting in documents.json. Both forms are read here; which
    # determination they feed is settled later, in stage_determine.
    form = first("FORM_D_I")
    form_type = "FORM_D_I"
    if form is None:
        form = first("FORM_D_II")
        form_type = "FORM_D_II"
    if form is None:
        b_forms = [d["type"] for d in documents
                   if d["type"].startswith("FORM_B_") and d["pages"]]
        if b_forms:
            raise ExtractionGap(
                f"the bundle's prescribed form is {b_forms[0].replace('_', ' ').replace('FORM ', 'Form ')}, "
                f"a SELF-pension sanction. Under rule 4.4(4) as amended on 2 December 2024 a "
                f"self pension is computed on the average basic pay (including personal pay) "
                f"in force on 1 July of the last three years, which no single page of the "
                f"bundle states -- the Auditor, Pension Wing supplies the three figures at "
                f"intake (SOP paragraph 5.8) and the engine computes from them. Stage 4 reads "
                f"no determination inputs from a Form B."
            )
        raise ExtractionGap(
            "no prescribed form among the identified documents: stage 4 looks for Form D-I "
            "(death in service) and Form D-II / Proforma D-II (death of a pensioner), and "
            "the bundle carries neither. Stage 4 has nothing authoritative to read the "
            "determination inputs from."
        )
    page = form["pages"][0]
    label = "Form D-I" if form_type == "FORM_D_I" else "Form D-II"
    form_reused = reuse is not None and reuse.take_form(result, form_type, page)
    if form_reused:
        if progress:
            progress(f"stage 4  {label} p.{page} reused from the earlier round")
        data = {}
    else:
        if progress:
            progress(f"stage 4  reading {label} p.{page} (double read)")
        # A form scanned sideways is turned upright first -- see extraction/orient.py. The
        # Disabled Son bundle's Form D-II was read as a landscape image and every field came
        # back wrong, at confidence 0.8-0.9.
        from extraction.orient import upright_form_image
        form_image = upright_form_image(image_for[page], page, schema_name=form_type,
                                        progress=progress)
        ext, agreement = extract_page_confirmed(form_image, schema_name=form_type)
        agreement.update({"document": form_type, "page": page})
        data = ext.data
        if reuse is not None:
            reuse.read("form", form_type, page)
    result["prescribed_form"] = form_type
    result["prescribed_form_page"] = page
    if not form_reused:
        result[f"{form_type.lower()}_agreement"] = agreement

    if form_reused:
        pass
    elif form_type == "FORM_D_I":
        for name in ("date_of_birth", "date_first_entry", "date_of_death", "eol_availed",
                     "qualifying_service_printed", "recovery_declared", "pay_scale_printed",
                     "deceased_name", "claimant_name"):
            result["fields"].append(_val(data.get(name), name, page, "FORM_D_I").__dict__)
        result["printed_totals"]["form_total_pay"] = data.get("total_pay_printed_rs")
        form_total = data.get("total_pay_printed_rs")
        result["pay_components"] += [c.__dict__ | {"amount": int(c.amount), "document": "FORM_D_I"}
                                     for c in _pay_components(data, page, form_total)]
    else:
        # D-II carries no pay table at all. It states the pension the deceased was already
        # drawing, and that single figure is the base -- so the fields read here are the
        # ones the D-II rules consume, not D-I's.
        for name in ("deceased_pensioner_name", "designation_at_retirement",
                     "pay_scale_printed", "ppo_no", "pensioner_id", "deceased_cnic",
                     "date_of_birth", "date_of_retirement", "date_of_death_of_pensioner",
                     "prior_family_pensioner_name", "prior_family_pensioner_ppo",
                     "date_of_death_of_prior_pensioner",
                     "claimant_name", "claimant_relation", "claimant_cnic",
                     "date_of_divorce", "recovery_declared", "authority_cited"):
            result["fields"].append(_val(data.get(name), name, page, "FORM_D_II").__dict__)
        for key in ("pension_drawn_rs", "net_pension_rs", "total_pension_rs",
                    "orderly_allowance_rs"):
            result["printed_totals"][key] = data.get(key)

    # -- the PPO: the authority on the pension in payment ---------------------------------
    # BRAIN §8.3 puts the PPO/FPPO above every restatement for "existing pension in payment",
    # and FAM-AR-01 computes a D-II family pension "from the pension in payment as stated on
    # the PPO/FPPO AND Form D-II". Reading only the form was a departure from both: the
    # unmarried-daughter bundle carries seven PPO pages and a Form D-II whose money fields the
    # department left blank, and the case reached the officer with no figure at all.
    if form_type == "FORM_D_II":
        # TWO pension documents, not one. §8.4: "Two sources agreeing is evidence. One source
        # is an assertion." A single read of a PPO page returned Rs 710,214 as the monthly
        # pension of a constable -- beside a gross of Rs 47,584 on the same page -- and a
        # family pension of Rs 532,661 a month was computed from it. Both reads of the
        # confirming pair agreed, because the model was reading the wrong number on the page
        # consistently; agreement between two reads of ONE page cannot catch that. Only a
        # second document can.
        seen_pages: set[int] = set()
        witnesses: list[dict] = []
        for doc in documents:
            if doc["type"] not in ("PPO", "FPPO", "PENSION_SLIP") or not doc["pages"]:
                continue
            pg = doc["pages"][0]
            if pg in seen_pages:
                continue
            seen_pages.add(pg)
            if reuse is not None:
                taken = reuse.take_witness(result, doc["type"], pg)
                if taken is not None:
                    if taken:
                        witnesses.append(taken)
                        if len(witnesses) >= 3:
                            break
                    continue
                reuse.read("witness", doc["type"], pg)
            if progress:
                progress(f"stage 4  reading {doc['type']} p.{pg} for the pension in payment "
                         f"(§8.3 authority; double read)")
            try:
                e, agree = extract_page_confirmed(image_for[pg], schema_name="PPO")
            except ExtractionError as exc:
                result.setdefault("unread_pay_documents", []).append(
                    {"document": doc["type"], "page": pg, "reason": str(exc)}
                )
                continue
            witnesses.append({
                "document": doc["type"], "page": pg,
                "monthly_pension_rs": e.data.get("monthly_pension_rs"),
                "gross_pension_rs": e.data.get("gross_pension_rs"),
                "is_family_pension": e.data.get("is_family_pension"),
                "agreement": agree,
            })
            if len(witnesses) >= 3:
                break
        if witnesses:
            result["pension_witnesses"] = witnesses

    # -- pay documents: the components themselves ----------------------------------------
    for doc_type in ("SALARY_STATEMENT", "LPC"):
        doc = first(doc_type)
        if doc is None:
            continue
        pg = doc["pages"][0]
        if reuse is not None:
            if reuse.take_pay_document(result, doc_type, pg):
                if progress:
                    progress(f"stage 4  {doc_type} p.{pg} reused from the earlier round")
                continue
            reuse.read("pay", doc_type, pg)
        if progress:
            progress(f"stage 4  reading {doc_type} p.{pg} (double read)")
        try:
            e, agree = extract_page_confirmed(image_for[pg], schema_name="AG_PAY_CERTIFICATE")
        except ExtractionError as exc:
            # A SUPPLEMENTARY pay document that cannot be read is a gap in the record, not a
            # reason to throw away the prescribed form that was read successfully. This read
            # was unguarded, and because `fields.json` is written after the loop, one
            # illegible page discarded the whole stage: on the golden case p041 (Form D-I,
            # the authoritative source) and p042 (the salary statement) both read, and then
            # p007 -- a handwritten 2003 transfer LPC from another district, quality 0.364,
            # which the bundle's own transcription calls "the least legible page of the
            # file" -- raised, and the case reported "no prescribed form for the extraction
            # to read". It has a prescribed form. It read it.
            #
            # That page has never contributed a figure to this determination: the verified
            # 4 September extraction read it, got nothing usable from it, and computed the
            # golden determination from p041 and p042 alone. So the gap is recorded and the
            # stage continues. Form D-I above is NOT treated this way and still raises --
            # without it there are no dates, no grade and no base.
            result.setdefault("unread_pay_documents", []).append(
                {"document": doc_type, "page": pg, "reason": str(exc)}
            )
            if progress:
                progress(f"stage 4  {doc_type} p.{pg} could not be read — recorded as a gap; "
                         f"an officer must transcribe it")
            continue
        agree.update({"document": doc_type, "page": pg})
        result[f"{doc_type.lower()}_agreement"] = agree
        comps = _pay_components(e.data, pg, e.data.get('gross_printed_rs'))
        if comps:
            result["pay_components"] += [c.__dict__ | {"amount": int(c.amount), "document": doc_type} for c in comps]
            result["printed_totals"][f"{doc_type.lower()}_gross"] = e.data.get("gross_printed_rs")

    if reuse is not None:
        result["carryover"] = reuse.summary()
    atomic_write_text(out_path, json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return result


class _ExtractReuse:
    """Stage 4's reads of the earlier round, for the pages this round carries (pipeline.carryover).

    A read is reused only where the page is carried AND it played the same part in the earlier
    round: the same page was that round's prescribed form, its salary statement, its LPC, or
    one of its pension documents. A page that is carried but was not read in that role (a new
    salary statement now comes first, say) is read afresh, so the result is what a full run
    over these papers would read.
    """

    _FORM_TOTALS = {
        "FORM_D_I": ("form_total_pay",),
        "FORM_D_II": ("pension_drawn_rs", "net_pension_rs", "total_pension_rs", "orderly_allowance_rs"),
    }

    def __init__(self, carry: dict, documents: list) -> None:
        from pipeline import carryover
        self.back = {int(new): int(old) for new, old in (carry.get("page_map") or {}).items()}
        fwd = carryover.forward_map(carry)
        base = carryover.base_artefact(carry, FIELDS) or {}
        self.base_form_type = base.get("prescribed_form")
        self.base_form_page = base.get("prescribed_form_page")
        self.base = carryover.remap(base, fwd) or {}
        self.fwd = fwd
        base_docs = carryover.base_artefact(carry, "documents.json") or []
        self.base_first = {}
        for d in base_docs:
            if d.get("pages") and d["type"] not in self.base_first:
                self.base_first[d["type"]] = d["pages"][0]
        self.reads: list[dict] = []

    def _was(self, new_page: int) -> int | None:
        return self.back.get(new_page)

    def read(self, role: str, doc_type: str, page: int) -> None:
        self.reads.append({"role": role, "document": doc_type, "page": page, "how": "read"})

    def _reused(self, role: str, doc_type: str, page: int) -> None:
        self.reads.append({"role": role, "document": doc_type, "page": page, "how": "reused",
                           "base_page": self._was(page)})

    def take_form(self, result: dict, form_type: str, page: int) -> bool:
        old = self._was(page)
        if old is None or self.base_form_type != form_type or self.base_form_page != old:
            return False
        result["fields"] += [f for f in self.base.get("fields") or [] if f.get("document") == form_type]
        result["pay_components"] += [c for c in self.base.get("pay_components") or [] if c.get("page") == page]
        totals = self.base.get("printed_totals") or {}
        for key in self._FORM_TOTALS.get(form_type, ()):
            if key in totals:
                result["printed_totals"][key] = totals[key]
        agree = f"{form_type.lower()}_agreement"
        if agree in self.base:
            result[agree] = self.base[agree]
        self._reused("form", form_type, page)
        return True

    def take_witness(self, result: dict, doc_type: str, page: int) -> dict | bool | None:
        """The earlier round's witness read of this page; False where it could not be read
        then (recorded again as unread); None where there is nothing to reuse."""
        if self._was(page) is None:
            return None
        for w in self.base.get("pension_witnesses") or []:
            if w.get("page") == page and w.get("document") == doc_type:
                self._reused("witness", doc_type, page)
                return dict(w)
        for u in self.base.get("unread_pay_documents") or []:
            if u.get("page") == page and u.get("document") == doc_type:
                result.setdefault("unread_pay_documents", []).append(dict(u))
                self._reused("witness", doc_type, page)
                return False
        return None

    def take_pay_document(self, result: dict, doc_type: str, page: int) -> bool:
        old = self._was(page)
        if old is None or self.base_first.get(doc_type) != old:
            return False
        for u in self.base.get("unread_pay_documents") or []:
            if u.get("page") == page and u.get("document") == doc_type:
                result.setdefault("unread_pay_documents", []).append(dict(u))
                self._reused("pay", doc_type, page)
                return True
        agree = f"{doc_type.lower()}_agreement"
        if agree not in self.base:
            return False                      # the earlier round did not read it: read it now
        result[agree] = self.base[agree]
        result["pay_components"] += [c for c in self.base.get("pay_components") or []
                                     if c.get("page") == page and c.get("page") != result.get("prescribed_form_page")]
        gross = f"{doc_type.lower()}_gross"
        if gross in (self.base.get("printed_totals") or {}):
            result["printed_totals"][gross] = self.base["printed_totals"][gross]
        self._reused("pay", doc_type, page)
        return True

    def summary(self) -> dict:
        return {"run": sum(1 for r in self.reads if r["how"] == "read"),
                "reused": sum(1 for r in self.reads if r["how"] == "reused"),
                "reads": self.reads}


def _pick(fields: list[dict], name: str) -> ExtractedField:
    for f in fields:
        if f["name"] == name:
            return ExtractedField(**{k: f[k] for k in
                                     ("name", "value", "confidence", "page", "document",
                                      "unreadable_reason")})
    return ExtractedField(name, None, 0.0, 0, "", "not extracted")


_SCALE = re.compile(r"\bB(?:P)?S[\s.\-]{0,2}(\d{1,2})\b", re.I)

#: Pakistani forms print dates DD-MM-YYYY. ISO is accepted too, because a model that has
#: already normalised should not be punished for it. Nothing else is guessed at: an ambiguous
#: 03-04-2021 is only ever read day-first, which is what the source uses throughout.
_DATE_FORMATS = ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y")


#: A money figure inside a free-text sentence, e.g. "Rs. 126,355 is recoverable" or
#: "Recoverable: 220,941.56". Grouping commas and an optional two-place fraction only.
_MONEY_IN_TEXT = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?")


def money_in_text(text: str) -> Decimal | None:
    """The money figure in a sentence, as a Decimal. ``None`` if there is none.

    Written because stripping non-digits was doing the parsing instead:
    ``"".join(ch for ch in "Recoverable: 220,941.56" if ch.isdigit())`` yields ``22094156``
    and turned a Rs. 220,941.56 recovery into Rs. 22,094,156 -- a hundredfold overstatement
    of a figure that is *subtracted from a gratuity*. The comma and the decimal point are not
    noise; one groups and the other divides.

    Two rules decide *which* number in the sentence is the money, because the first one
    usually is not. The real LPC sentence reads "w.e.f. 19.02.2026 to 28.02.2026 (10 days)
    amounting to Rs. 126,355 is recoverable", where taking the first match gives 19.02:

      1. a candidate that sits inside a date is discarded, and
      2. a comma-grouped candidate wins over a bare one, because rupees in these documents
         are printed with grouping commas while the bare integers beside them are day counts.
    """
    src = text or ""
    candidates: list[str] = []
    for m in _MONEY_IN_TEXT.finditer(src):
        before, after = src[max(0, m.start() - 1):m.start()], src[m.end():m.end() + 2]
        if re.match(r"[./-]\d", after) or re.search(r"\d[./-]$", src[:m.start()][-2:]) \
           or before in "./-":
            continue                                  # part of 19.02.2026, not an amount
        candidates.append(m.group(0))
    if not candidates:
        return None
    grouped = next((c for c in candidates if "," in c), None)
    return Decimal((grouped or candidates[0]).replace(",", ""))


def _parse_date(field: ExtractedField, name: str) -> date:
    if not field.usable:
        raise ExtractionGap(
            f"{name} is not usable (value={field.value!r}, confidence={field.confidence}, "
            f"reason={field.unreadable_reason!r}). Route to human verification."
        )
    raw = (field.value or "").strip()[:10]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ExtractionGap(
        f"{name} {raw!r} is not a date in any accepted format {_DATE_FORMATS}"
    )


def pay_scale_from_ocr(run: Path, page: int) -> int:
    """Read the pay scale from OCR of the form page. BRAIN §5.3 corroboration.

    The vision model read "BS-19" as 12, twice, at confidence 1.00 -- almost certainly from
    the adjacent date "12-10-2021" -- and dressing the answer up as "BS. 12" made it no more
    true. A printed scale token is character recognition, not judgement, so it is read by the
    OCR model instead: a second reader, and the one whose job this actually is.

    BPS selects the medical-allowance band (25% below BS-16, 20% at BS-16 and above), so a
    wrong grade is a wrong monthly payment for life.

    Reads through ``page_ocr_text``, so the page is OCR'd once per run and a recompute uses
    what is already on disk. Called ``ocr_page`` directly before, which put a 10.8s model
    call on the one path an officer takes repeatedly -- a recompute re-read the same page
    every time and measurably nothing else in the rebuild cost anything. It also made the
    rebuild depend on a service being up to reproduce a figure already recorded, against
    SOP §8.5.
    """
    from extraction.ocr import normalise

    text = normalise(page_ocr_text(run, page) or "")
    found = {int(m) for m in re.findall(r"\bB(?:P)?S[\s.\-]{0,2}(\d{1,2})\b", text)}
    found = {s for s in found if 1 <= s <= 22}
    if len(found) == 1:
        return found.pop()
    raise ExtractionGap(
        f"OCR found {sorted(found) or 'no'} pay-scale token(s) on page {page}; "
        "the grade cannot be established from this page alone. Route to human verification."
    )


def _opt_date(fields: list[dict], name: str) -> "date | None":
    """A date from the extracted fields, or None. Never raises and never guesses.

    Used only for CLASSIFICATION, where a missing date means "this evidence does not settle
    it" and the classifier says so. The determination path uses `_parse_date`, which raises,
    because there a missing date is a gap.
    """
    for f in fields:
        if f.get("name") == name and f.get("value"):
            return _as_iso_date(str(f["value"]))
    return None


def _as_iso_date(text: str) -> "date | None":
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _opt_field(fields: list[dict], name: str) -> tuple[str | None, int | None, str | None]:
    """A value with the page and document it was read from, for the provenance trail."""
    for f in fields:
        if f.get("name") == name and f.get("value"):
            return str(f["value"]), f.get("page"), f.get("document")
    return None, None, None


def _form_that_wrote(fields: list[dict]) -> str | None:
    """Which prescribed form produced this fields.json, for a file written before stage 4
    began recording it.

    This reads the SHAPE OF THE FILE, not the facts of the case: the two branches of
    ``stage_extract`` emit disjoint field sets, so the presence of ``date_first_entry`` says
    a D-I schema wrote this payload as surely as a header would. Without it every
    determination already on disk -- including the verified golden artefact -- would fail
    classification the moment this code shipped, which is a migration bug dressed up as a
    refusal.
    """
    names = {f.get("name") for f in fields}
    if names & {"date_first_entry", "eol_availed", "qualifying_service_printed"}:
        return "FORM_D_I"
    if names & {"date_of_death_of_pensioner", "prior_family_pensioner_name"}:
        return "FORM_D_II"
    return None


#: A monthly pension outside this range is a misread, not a pension. The floor is below the
#: minimum family pension of any Punjab notification on file; the ceiling is well above a
#: BS-22 pensioner's entitlement, so a genuine figure is never rejected by it.
#: A monthly pension below the floor is a misread, above the ceiling likewise. The floor was
#: 500 and rejected a real one: a constable who retired in 1989 draws Rs 357 a month on his
#: PPO and every pension slip in the bundle says so. Old PPOs are in hundreds of rupees.
PENSION_FLOOR, PENSION_CEILING = Decimal(100), Decimal(2_000_000)


def corroborated_pension(
    witnesses: list[dict],
    stated_on_form: list[Decimal] | None = None,
) -> "tuple[Decimal | None, str | None, str | None]":
    """The pension in payment, only where two documents agree on it. ``§8.4``.

    Returns ``(amount, note, rejection)``. ``amount`` is ``None`` unless a figure is stated by
    two independent witnesses -- two pension documents, or one pension document and the
    prescribed form. ``rejection`` says, in one sentence, what was read and why it was not
    used, so the refusal an officer sees names the pages rather than the absence.

    Two guards, both deterministic:

    * a monthly pension may not exceed the gross pension printed beside it on the same page;
    * a figure outside ``PENSION_FLOOR``..``PENSION_CEILING`` is a misread.

    Written after a single PPO read returned Rs 710,214 as the monthly pension of a
    constable, beside a gross of Rs 47,584 on the same page, and the engine computed a family
    pension of Rs 532,661 a month from it. Both reads of the confirming pair agreed: the model
    was reading the wrong number consistently, which is exactly what a second document
    catches and a second read of the same page cannot.
    """
    seen: list[tuple[Decimal, dict]] = []
    rejected: list[str] = []
    for w in witnesses:
        monthly = w.get("monthly_pension_rs")
        gross = w.get("gross_pension_rs")
        if monthly in (None, ""):
            continue
        amount = Decimal(str(monthly))
        where = f"{w.get('document', 'PPO')} p.{w.get('page')}"
        if gross not in (None, "") and amount > Decimal(str(gross)):
            rejected.append(f"{where} reads a monthly pension of {fmt(amount)} against a "
                            f"gross of {fmt(Decimal(str(gross)))} on the same page")
            continue
        if not PENSION_FLOOR <= amount <= PENSION_CEILING:
            rejected.append(f"{where} reads {fmt(amount)}, which is not a monthly pension")
            continue
        seen.append((amount, w))

    for amount, w in seen:
        others = [f"{o.get('document')} p.{o.get('page')}"
                  for a, o in seen if o is not w and a == amount]
        if others:
            return amount, (
                f"Pension in payment {fmt(amount)}, stated by "
                f"{w.get('document')} p.{w.get('page')} and corroborated by "
                f"{', '.join(others)} (§8.3 authority, §8.4 corroboration)."
            ), None
        if any(amount == f for f in (stated_on_form or [])):
            return amount, (
                f"Pension in payment {fmt(amount)}, stated by {w.get('document')} "
                f"p.{w.get('page')} and corroborated by the prescribed form."
            ), None

    if seen:
        listed = ", ".join(f"{o.get('document')} p.{o.get('page')} {fmt(a)}" for a, o in seen)
        rejected.append(f"the pension documents do not agree with each other ({listed})")
    return None, None, ("; ".join(rejected) + "." if rejected else None)


def _vetted_prior(fields: list[dict]) -> "tuple[str | None, date | None, str | None]":
    """The prior-family-pensioner fields, kept only where they pass ``vet_prior_pensioner``."""
    from rules.dii import vet_prior_pensioner

    name, _p, _d = _opt_field(fields, "prior_family_pensioner_name")
    claimant, _p, _d = _opt_field(fields, "claimant_name")
    deceased, _p, _d = _opt_field(fields, "deceased_pensioner_name")
    return vet_prior_pensioner(
        claimant_name=claimant, deceased_name=deceased, prior_name=name,
        prior_death=_opt_date(fields, "date_of_death_of_prior_pensioner"),
        other_dates=(
            _opt_date(fields, "date_of_death_of_pensioner"),
            _opt_date(fields, "date_of_retirement"),
            _opt_date(fields, "date_of_divorce"),
            _opt_date(fields, "date_of_birth"),
        ),
    )


#: What a pension slip or PPO prints beside its monthly figures, as OCR transcribes it.
_SLIP_NET = re.compile(
    r"(?i)(?:net\s+pension(?:\s*\(rs\.?\))?(?:\s+payable)?(?:\s+monthly)?|monthly\s+pension\s*-\s*family)"
    r"\W{0,6}(?:rs\.?\s*)?([\d,]+(?:[.\-]\d{1,2})?)")
_SLIP_GROSS = re.compile(
    r"(?i)gross\s+pension(?:\s*\(rs\.?\))?\W{0,6}(?:rs\.?\s*)?([\d,]+(?:[.\-]\d{1,2})?)")


def _slip_amount(raw: str) -> Decimal | None:
    raw = raw.replace(",", "").replace("-", ".")
    try:
        return Decimal(raw)
    except Exception:                                # noqa: BLE001
        return None


def slip_figures_from_text(text: str) -> dict:
    """Net and gross pension a slip or PPO page prints, where every occurrence agrees."""
    out: dict = {}
    for key, pattern in (("monthly_pension_rs", _SLIP_NET), ("gross_pension_rs", _SLIP_GROSS)):
        values = {_slip_amount(m.group(1)) for m in pattern.finditer(text)} - {None}
        values = {v for v in values if v >= 1}
        if len(values) == 1:
            out[key] = values.pop()
    return out


def page_ocr_text(run: Path, page: int) -> str | None:
    """OCR text of one page, cached in ``ocr_text.json`` so a recompute never re-reads it."""
    cache_path = run / "ocr_text.json"
    cache: dict = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except ValueError:
            cache = {}
    key = str(page)
    if key in cache:
        return cache[key]
    manifest = json.loads((run / "manifest.json").read_text())
    image = next((run / p["image_path"] for p in manifest["pages"] if p["page"] == page), None)
    if image is None:
        return ""
    try:
        from extraction.ocr import ocr_page
        text = ocr_page(image, page).text
    except Exception:                                # noqa: BLE001
        # NOT cached. An OCR service that was down for a minute would otherwise have "this
        # page has no text on it" written into the run as a fact, and every later read --
        # the pay scale, the slip figures, the D-II pension in payment -- would get that
        # answer forever, with nothing to say the page was never actually read. Same
        # discipline as the citation cache in rag.store: a degraded answer is returned once
        # and retried, never persisted.
        #
        # None, not "". A caller that cannot tell "the reader failed" from "the page is blank"
        # draws a conclusion from the failure: stage 3b read no printed heading, so the filed
        # document was never registered and the checklist reported it MISSING against the
        # department, with no error recorded anywhere (audit 13 Oct 2026). Callers that only
        # want text read whatever there is with `or ""`; the one that concludes something
        # checks for None.
        return None
    cache[key] = text
    atomic_write_text(cache_path, json.dumps(cache, ensure_ascii=False))
    return text


def prefetch_page_ocr(run: Path, pages: list[int], *, concurrency: int | None = None) -> int:
    """Read these pages' OCR text at once and put it in the cache ``page_ocr_text`` reads.

    Stage 3b asked for one page at a time and waited for each: 9 calls, 91.5s, every one
    starting as the last ended, while the OCR server reported a single request running
    (19 Oct 2026). The reads are independent, so they are done together here and the caller's
    loop then hits a warm cache with its ordering and its shared state untouched.

    The cache is NOT written from the pool. ``page_ocr_text`` read-modify-writes one JSON
    file, so concurrent writers would each save their own entry over everyone else's; the
    reads happen in the pool and the single write happens here, on the calling thread.

    Returns how many pages were actually read. A page already cached is not read again, and a
    page whose read FAILS is not cached -- same discipline as page_ocr_text, where a reader
    that was briefly down must not leave "this page is blank" in the run as a fact.
    """
    from extraction.ocr import ocr_page
    from pipeline import timing

    cache_path = run / "ocr_text.json"
    cache: dict = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except ValueError:
            cache = {}
    wanted = [p for p in dict.fromkeys(pages) if str(p) not in cache]
    if not wanted:
        return 0

    manifest = json.loads((run / "manifest.json").read_text())
    image_of = {p["page"]: run / p["image_path"] for p in manifest["pages"]}
    todo = [p for p in wanted if p in image_of]
    if not todo:
        return 0

    workers = concurrency or ASSEMBLE_OCR_CONCURRENCY
    def read(page: int) -> tuple[int, str | None]:
        try:
            return page, ocr_page(image_of[page], page).text
        except Exception:                            # noqa: BLE001 -- not cached, see above
            return page, None

    if workers <= 1 or len(todo) < 2:
        results = [read(p) for p in todo]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = [f.result() for f in [
                pool.submit(timing.carry(read, stage="assemble", page=p), p) for p in todo]]

    read_ok = 0
    for page, text in results:
        if text is not None:
            cache[str(page)] = text
            read_ok += 1
    if read_ok:
        atomic_write_text(cache_path, json.dumps(cache, ensure_ascii=False))
    return read_ok


def ocr_witnesses(run: Path, already: set[int], limit: int = 8) -> list[dict]:
    """Pension figures from the slip and PPO pages stage 4 did not read, by OCR.

    Stage 4 reads the first three PPO/slip pages with the vision model and stops. On the
    unmarried-daughter bundle those three were PPO pages whose reads were rubbish, while five
    pension slips further in all print "Net Pension (Rs.): 357.00". A printed label and a
    printed figure are OCR's job; each page becomes a witness marked ``source: ocr`` and is
    corroborated on the same terms as any other -- two documents must agree.
    """
    try:
        documents = json.loads((run / "documents.json").read_text())
    except (OSError, ValueError):
        return []
    out: list[dict] = []
    for doc in documents:
        if doc.get("type") not in ("PENSION_SLIP", "PPO", "FPPO") or not doc.get("pages"):
            continue
        pg = doc["pages"][0]
        if pg in already:
            continue
        figures = slip_figures_from_text(page_ocr_text(run, pg) or "")
        if "monthly_pension_rs" not in figures:
            continue
        out.append({"document": doc["type"], "page": pg, "source": "ocr",
                    "monthly_pension_rs": str(figures["monthly_pension_rs"]),
                    "gross_pension_rs": (str(figures["gross_pension_rs"])
                                         if "gross_pension_rs" in figures else None),
                    "is_family_pension": None,
                    "agreement": {"agree": True, "reads_attempted": 1, "finding": None}})
        if len(out) >= limit:
            break
    return out


def officer_inputs(run: Path) -> dict:
    """What the Auditor keyed at intake (``intake.json``): pension in payment, date of death."""
    try:
        return json.loads((run / "intake.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _form_text_for(run: Path, page: int | None) -> str:
    """The OCR text of the prescribed form page, as stage 3 stored it in identities.json."""
    if page is None:
        return ""
    try:
        rows = json.loads((run / "identities.json").read_text())
    except (OSError, ValueError):
        return ""
    for r in rows:
        if r.get("page") == page and r.get("form_text"):
            return str(r["form_text"])
    return ""


def refresh_form_text(run_dir: str | Path, *, progress: Callable[[str], None] | None = None) -> int:
    """Re-read every prescribed-form page by OCR and store the full text in identities.json.

    For runs identified before the text was kept whole: stage 3 stored the first 2,000
    characters, and a Form B-I's retirement date, average pay and qualifying service all
    sat past the cut. OCR only, a few seconds a page, no vision call. Returns pages re-read.
    """
    from extraction.ocr import ocr_page
    run = Path(run_dir)
    path = run / "identities.json"
    rows = json.loads(path.read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    image_for = {p["page"]: run / p["image_path"] for p in manifest["pages"]}
    forms = ("FORM_B_I", "FORM_B_II", "FORM_B_III", "FORM_B_IV", "FORM_D_I", "FORM_D_II")
    done = 0
    for r in rows:
        if r.get("document_type") not in forms or r.get("page") not in image_for:
            continue
        if progress:
            progress(f"form text  {r['document_type']} p.{r['page']}")
        try:
            r["form_text"] = ocr_page(image_for[r["page"]], r["page"]).text[:8000]
            done += 1
        except Exception:                            # noqa: BLE001
            continue
    if done:
        atomic_write_text(path, json.dumps(rows, indent=2, ensure_ascii=False, default=str))
    return done


def _determine_death_after_retirement(
    run: Path, extracted: dict, case_class: CaseClass, computed_at: datetime | None,
) -> dict:
    """Stage 7 for a Form D-II bundle. Refuses distinctly; never borrows D-I's arithmetic.

    Every refusal below is its own exception type carrying its own sentence, because an
    unimplemented case type, an unconfirmed rule, a failed extraction and a missing document
    surfacing alike as "Not computed" is what sent a day's work chasing an OCR bug for a
    case type that had never been built.
    """
    fields = extracted["fields"]
    totals = extracted.get("printed_totals") or {}
    trail: list[Provenance] = []

    def take(name: str) -> str | None:
        value, page, doc = _opt_field(fields, name)
        if value is not None:
            trail.append(Provenance(name, value, page, doc))
        return value

    relation = take("claimant_relation")
    take("claimant_name")
    take("deceased_pensioner_name")
    take("prior_family_pensioner_name")
    prior_name, prior_death, prior_note = _vetted_prior(fields)

    def figure(key: str) -> Decimal | None:
        value = totals.get(key)
        if value in (None, ""):
            return None
        trail.append(Provenance(key, str(value), extracted.get("prescribed_form_page"),
                                "FORM_D_II"))
        return Decimal(str(value))

    drawn = figure("pension_drawn_rs")
    # The other figures the form prints. Which one the share applies to is BLOCKING-07, and
    # the engine emits both readings where they differ rather than choosing here.
    net = figure("net_pension_rs")
    total = figure("total_pension_rs")

    # The form's OCR text is the second, independent reading of the prescribed form
    # (SOP §6.3(9)). Where the vision read filed no pension figure at all, the figure the
    # form prints beside "drawing pension @" is taken from the OCR text instead of refusing:
    # on the Widow Daughter bundle the vision read returned "Rs.19,874/-" as the PAY SCALE and
    # nothing as the pension, and the case went undetermined over a label. Only where the
    # vision read has nothing; where it read a figure, that figure stands and the OCR text
    # does not overrule it. A pension in payment below Rs. 1,000 a month is not one -- the
    # Disabled Son form's OCR reads "of 357 pPO" -- and is not taken.
    form_text = _form_text_for(run, extracted.get("prescribed_form_page"))
    ocr_figures = printed_form_figures(form_text) if form_text else {}
    ocr_caveats: list[str] = []
    for key, target in (("pension_drawn_rs", "drawn"), ("net_pension_rs", "net"),
                        ("total_pension_rs", "total")):
        if locals()[target] is None and ocr_figures.get(key):
            value = Decimal(ocr_figures[key])
            if key == "pension_drawn_rs" and value < PENSION_FLOOR:
                continue
            if target == "drawn":
                drawn = value
            elif target == "net":
                net = value
            else:
                total = value
            trail.append(Provenance(key, str(value), extracted.get("prescribed_form_page"),
                                    "FORM_D_II (OCR text)"))
            ocr_caveats.append(
                f"{key.replace('_rs', '').replace('_', ' ')} of {fmt(value)} was read from the "
                f"prescribed form's OCR text, the vision read having filed no such figure. "
                f"Confirm it against the form."
            )

    # §8.3: the PPO/FPPO is the authority on the pension in payment, above the sanction form's
    # restatement of it -- but §8.4 governs how a figure earns the right to be used at all,
    # and one document's word is an assertion, not evidence. ``corroborated_pension``
    # returns a figure only where two documents state it, and the refusal otherwise is the
    # point: a family pension of Rs 532,661 a month was computed for a constable's daughter
    # from a single uncorroborated read.
    witnesses = list(extracted.get("pension_witnesses") or [])
    witnesses += ocr_witnesses(run, {w.get("page") for w in witnesses})
    ppo_pension, ppo_note, ppo_rejected = corroborated_pension(
        witnesses,
        stated_on_form=[x for x in (drawn, net, total) if x is not None],
    )
    if ppo_pension is not None:
        first = next((w for w in witnesses
                      if str(w.get("monthly_pension_rs")) not in ("", "None")
                      and Decimal(str(w.get("monthly_pension_rs"))) == ppo_pension), {})
        trail.append(Provenance("pension_in_payment", str(ppo_pension),
                                first.get("page"), first.get("document", "PPO")))
    ppo_caveats: list[str] = [n for n in (ppo_note,) if n]
    if drawn is None and net is None:
        if ppo_pension is not None:
            drawn = ppo_pension
        elif ppo_rejected:
            raise InputMissing(
                "the prescribed form states no pension figure, and the pension documents in "
                "the bundle do not corroborate one: " + ppo_rejected + " BRAIN §8.4 requires "
                "two sources to agree before a figure decides a pension, so none is used. An "
                "officer must read the PPO and record the pension in payment on the case file."
            )
    elif ppo_pension is not None and drawn is not None and ppo_pension != drawn:
        # Both speak and they disagree. §8.3 settles WHICH governs; the difference is still
        # a finding, because a sanction form restating the wrong pension is a defect.
        ppo_caveats.append(
            f"The form states {fmt(drawn)} and the pension documents corroborate "
            f"{fmt(ppo_pension)}. §8.3 makes the PPO the authority on the pension in "
            f"payment, so it governs; the difference is raised as a finding."
        )
        drawn = ppo_pension

    # The date of death, likewise: the vision read returns the handwritten date as it saw it
    # ("28-2-24", a two-digit year that parses to nothing) and the form's own "expired on"
    # clause is read from the OCR text where the field gives no usable date.
    death = _opt_date(fields, "date_of_death_of_pensioner")
    if death is None and form_text:
        death = death_date_from_form(form_text)
        if death is not None:
            trail.append(Provenance("date_of_death_of_pensioner", death.isoformat(),
                                    extracted.get("prescribed_form_page"), "FORM_D_II (OCR text)"))
            ocr_caveats.append(
                f"The date of death, {death.isoformat()}, was read from the prescribed form's "
                f"OCR text ('expired on'); the field read gave no usable date. Confirm it "
                f"against the death certificate."
            )
        else:
            # A two-digit year is not read as 20xx (audit L1, 7 Oct 2026): the century is the
            # form's to state and the officer's to confirm. The intake entry below is the way in.
            written = ambiguous_death_date_from_form(form_text)
            if written:
                ocr_caveats.append(
                    f"The prescribed form gives the date of death as '{written}', a year written "
                    f"with two digits. It was not used: confirm the date against the death "
                    f"certificate and key it at intake so the determination can run from it."
                )
    # A pension in payment BELOW the net pension printed on the same form is a misread, not
    # a reading: the net pension is what is left after commutation, so it cannot exceed the
    # pension being drawn. On the Disabled Son form the OCR reads "drawing pension/family
    # pension of 357 pPO / FPPO No 31657835" -- 357 is a fragment of the PPO number -- against
    # a printed net pension of 1,041.5. Dropping it leaves the net pension as the one reading
    # the form supports, rather than emitting two that contradict each other.
    if drawn is not None and net is not None and drawn < net:
        ocr_caveats.append(
            f"A 'drawing pension' figure of {fmt(drawn)} was read from the form against a "
            f"printed net pension of {fmt(net)}. A pension in payment cannot be less than the "
            f"net pension left after commutation, so the smaller figure is treated as a "
            f"misreading and is not used. Confirm the pension in payment against the PPO."
        )
        drawn = None

    # Last resort, both for the figure and the date: what the Auditor keyed at intake
    # (SOP §7.3(3) sends a case the engine declines to the Determining Officer; this lets the
    # officer's own reading of the PPO reach the engine instead of a typed calculation).
    keyed = officer_inputs(run)
    if drawn is None and net is None and str(keyed.get("pension_in_payment") or "").strip():
        try:
            drawn = Decimal(str(keyed["pension_in_payment"]).replace(",", "").strip())
            trail.append(Provenance("pension_in_payment", str(drawn), None, "officer entry (intake)"))
            ocr_caveats.append(
                f"The pension in payment, {fmt(drawn)}, was keyed by the Auditor at intake from "
                f"the PPO; no page of the bundle yielded a corroborated figure. An officer "
                f"confirms it against the PPO before any FPPO issues."
            )
        except Exception:                            # noqa: BLE001
            pass
    if death is None and str(keyed.get("date_of_death") or "").strip():
        try:
            death = date.fromisoformat(str(keyed["date_of_death"]).strip())
            trail.append(Provenance("date_of_death_of_pensioner", death.isoformat(), None,
                                    "officer entry (intake)"))
            ocr_caveats.append(
                f"The date of death, {death.isoformat()}, was keyed by the Auditor at intake; "
                f"the form and the death certificate yielded none. Confirm it against the "
                f"death certificate."
            )
        except ValueError:
            pass
    if ppo_rejected and drawn is not None and any("pension drawn" in c for c in ocr_caveats):
        ocr_caveats.append(
            "The pension documents in the bundle do not corroborate the form's figure: "
            + ppo_rejected
        )

    case = DeathAfterRetirementCase(
        case_ref=run.name,
        sanctioned_pension=drawn,
        net_pension=net,
        total_pension=total,
        claimant_relation=relation or "",
        date_of_death_of_pensioner=death,
        date_of_retirement=_opt_date(fields, "date_of_retirement"),
        prior_pensioner_name=prior_name,
        prior_pensioner_death=prior_death,
        date_of_divorce=_opt_date(fields, "date_of_divorce"),
        provenance=tuple(trail),
        extra_caveats=tuple(c for c in (prior_note, *ppo_caveats, *ocr_caveats) if c),
    )
    det = determine_family_pension_death_after_retirement(
        case, DIIRules.load(), case_class,
        computed_at or datetime(2026, 6, 3, 10, 0, 0),
    )
    payload = {"determination": det.to_dict(), "emoluments": None,
               "case_class": case_class.case}
    atomic_write_text(run / DETERMINATION,
                      json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return payload


def pages_with_no_document(run: Path) -> tuple[list[int], int]:
    """Pages the bundle contains that were assigned to no document, and the page count.

    SOP §4.4 rule 5 and §6.3 rule 10: the Auditor must "confirm that every page of the
    bundle has been accounted for, a document reported as missing being reliable only where
    no page is unaccounted for". A report that says a document is absent while a third of
    the bundle produced nothing is not reporting a shortcoming, it is reporting its own
    reading failure -- and the department gets asked for a paper it already sent.

    Returns ``([], 0)`` where the manifest or the document list cannot be read: this
    qualifies a message, and failing to build one would lose the message it qualifies.
    """
    try:
        manifest = json.loads((run / "manifest.json").read_text())
        documents = json.loads((run / "documents.json").read_text())
    except (OSError, ValueError):
        return [], 0
    all_pages = {p["page"] for p in manifest.get("pages", [])}
    assigned = {pg for d in documents for pg in (d.get("pages") or [])}
    return sorted(all_pages - assigned), len(all_pages)


def stage_determine(run_dir: str | Path, *, computed_at: datetime | None = None) -> dict:
    """Run the deterministic engine over the extracted inputs.

    Raises rather than substituting a plausible value for anything it could not read: BRAIN
    §15.1 forbids inventing a determination-critical value, and a gap that stops a
    determination costs an officer minutes while a fabricated one pays the wrong amount for
    life.
    """
    run = Path(run_dir)
    # Stage 4 raises rather than writing a partial fields.json, so an absent file means the
    # extraction never found an authoritative document to read -- nothing was lost. Letting
    # that surface as ENOENT sends the reader to the filesystem for a bundle defect stage 4
    # has already named, so it is restated here as the gap it is.
    fields_path = run / FIELDS
    if not fields_path.exists():
        # This asserted "the bundle has no prescribed form for the extraction to read", which
        # is only one of the reasons fields.json can be absent -- and on the golden case it was
        # the wrong one. Form D-I was present on page 41 and had been read successfully; a
        # different page failed and took the stage down with it. An officer was sent to look
        # for a form the bundle contained. This stage cannot know why stage 4 stopped, so it
        # states what it can verify and points at the stage that does know.
        forms: list[dict] = []
        try:
            forms = [d for d in json.loads((run / "documents.json").read_text())
                     if d.get("type") in ("FORM_D_I", "FORM_D_II") and d.get("pages")]
        except (OSError, ValueError):
            pass
        if forms:
            named = "Form D-I" if forms[0]["type"] == "FORM_D_I" else "Form D-II"
            where = (
                f"The bundle DOES carry a prescribed form ({named}, page "
                f"{forms[0]['pages'][0]}), so the form is not what is missing: stage 4 stopped "
                f"for some other reason and recorded it against the extract stage. Read that "
                f"before looking for a document."
            )
        else:
            b_forms: list[str] = []
            try:
                b_forms = [d["type"] for d in json.loads((run / "documents.json").read_text())
                           if str(d.get("type", "")).startswith("FORM_B_") and d.get("pages")]
            except (OSError, ValueError):
                pass
            if b_forms:
                where = (
                    f"The bundle carries {b_forms[0].replace('_', ' ').replace('FORM ', 'Form ')}, "
                    f"a self-pension sanction. A self pension is computed from the three annual "
                    f"basic-pay figures (1 July of each of the last three years, rule 4.4(4) as "
                    f"amended) that the Auditor supplies at intake; the bundle's single pay "
                    f"slip is not that average. Supply them and the case computes."
                )
            else:
                where = (
                    "No prescribed form was identified in the bundle -- neither Form D-I (death "
                    "in service) nor Form D-II / Proforma D-II (death of a pensioner) -- and "
                    "stage 4 reads the determination inputs from one of those."
                )
                # And whether that sentence can be relied on. On a 35-page self-pension
                # bundle 22 pages were assigned to no document, and this message told the
                # officer the form was not there -- a claim about the department's paperwork
                # built on our own unread pages. SOP §4.4 rule 5 makes the qualification
                # mandatory, not optional.
                unread, total = pages_with_no_document(run)
                if unread:
                    listed = ", ".join(str(p) for p in unread[:12])
                    if len(unread) > 12:
                        listed += f" and {len(unread) - 12} more"
                    noun = "page" if len(unread) == 1 else "pages"
                    where += (
                        f" That is NOT a finding that the form is absent: {len(unread)} of "
                        f"{total} pages in this bundle produced no document at all ({noun} "
                        f"{listed}), and a prescribed form may be among them. SOP §4.4 rule 5 "
                        f"-- a document reported as missing is reliable only where no page is "
                        f"unaccounted for. Those pages need reading, or manual transcription, "
                        f"before the bundle is called incomplete."
                    )
        raise ExtractionGap(
            "stage 4 produced no determination inputs, so there is nothing to compute from. "
            + where + " Route to human verification."
        )
    extracted = json.loads(fields_path.read_text())
    fields = extracted["fields"]

    # WHICH determination this is. It used to be assumed: a DeathInServiceCase was built for
    # every bundle regardless, so a death-of-a-pensioner case would have had a fresh pension
    # accrued from pay and service under the wrong rule, and the figure would have looked
    # entirely reasonable. The class is decided from the prescribed form and corroborated by
    # the dates, and UNKNOWN refuses rather than falling through to either calculator.
    # The prior-pensioner fields are vetted before they can make this a re-grant: on every
    # real D-II bundle the model put the claimant's own name and a copied date in them.
    _prior_name, prior_death, _prior_note = _vetted_prior(fields)
    case_class = classify_case(
        prescribed_form=extracted.get("prescribed_form") or _form_that_wrote(fields),
        date_of_retirement=_opt_date(fields, "date_of_retirement"),
        date_of_death=_opt_date(fields, "date_of_death_of_pensioner"),
        prior_pensioner_death=prior_death,
    )
    if case_class.case == UNKNOWN:
        raise CaseTypeNotDetermined(
            f"the family-pension path could not be determined for this bundle, and the two "
            f"paths are computed under different rules. {case_class.evidence}"
        )
    if case_class.case in (DEATH_AFTER_RETIREMENT, REGRANT_AFTER_WIDOW_DEATH):
        return _determine_death_after_retirement(run, extracted, case_class, computed_at)

    dob = _parse_date(_pick(fields, "date_of_birth"), "date_of_birth")
    entry = _parse_date(_pick(fields, "date_first_entry"), "date_first_entry")
    death = _parse_date(_pick(fields, "date_of_death"), "date_of_death")

    # The grade comes from OCR, not from the vision model -- see pay_scale_from_ocr.
    form_page = _pick(fields, "date_of_birth").page
    bps = pay_scale_from_ocr(run, form_page)

    # One document's lines, never a merge (business decision H2, 7 Oct 2026): the LPC where it
    # was read, else the prescribed form, else the salary statement. Until then the lines of
    # every pay document were pooled and de-duplicated on (component, amount), so a component
    # two documents printed at different amounts was SUMMED. A difference between documents is
    # now a finding (rules.flags.check_pay_lines_against_lpc), and the base is one document's.
    unique, source_document = single_source_pay_lines(extracted)

    # BLOCKING-21: the rules in force when the entitlement AROSE, not when the case was
    # processed. A death in 2021 is not governed by an amendment made in 2024 unless the
    # office rules otherwise. Was a hardcoded 2026-02-18, which silently applied whichever
    # pack happened to be current.
    pack = select_pack(effective_date=death)
    # Reconcile against the same document's own printed total only: the form's "Total Pay" says
    # what the form's lines add up to, nothing about the LPC's.
    printed_total = (extracted["printed_totals"].get("form_total_pay")
                     if source_document in ("FORM_D_I", "FORM_B_I") else None)
    emol = reckon(unique, pack, printed_total=printed_total)
    # Only an UNSUMMABLE line stops the determination here: an unknown or disputed component
    # is a base nobody can state. A base that sums but disagrees with the form's printed
    # total is a different thing -- a defect in the department's paperwork, or a misread
    # line -- and BRAIN §8.4 says to return the discrepancy for a flag, not to compute
    # nothing. The engine computes on the pay records (the §8.3 authority on pay), marks the
    # determination provisional and states the difference; the flag battery raises it HIGH.
    # Refusing here left the OSD-post case with no figure at all over a Rs. 750
    # qualification-pay line the form had omitted.
    if emol.unknown:
        raise ExtractionGap(f"emoluments cannot be summed: {emol.finding()}")

    qs = _pick(fields, "qualifying_service_printed")
    case = DeathInServiceCase(
        case_ref=run.name,
        date_of_birth=dob,
        date_of_first_entry=entry,
        date_of_death=death,
        emoluments=emol,
        bps=bps,
        stated_qualifying_service=qs.value if qs.usable else None,
    )
    det = determine_family_pension_death_in_service(
        case, pack, computed_at or datetime(2026, 6, 3, 10, 0, 0)
    )
    payload = {
        "determination": det.to_dict(),
        "emoluments": {
            "source_document": source_document,
            "reckonable_total": int(emol.reckonable_total),
            "excluded_total": int(emol.excluded_total),
            "printed_total": int(emol.printed_total) if emol.printed_total is not None else None,
            "reconciled": emol.reconciled,
            "components": [
                {
                    "printed_label": c.printed_label,
                    "component": c.component,
                    "amount": int(c.amount),
                    "reckonable": c.component in set(pack.ref("reckonable_components")),
                    "page": c.page,
                }
                for c in (*emol.reckonable, *emol.excluded)
            ],
        },
    }
    atomic_write_text(run / DETERMINATION, json.dumps(payload, indent=2, default=str))
    return payload


# ==============================================================================================
# Per-document assertions, so the cross-document check battery has something to compare.
# BRAIN §8.4, BUILD §5 stage 6.
#
# Stage 4 originally read only the pay documents, which was enough for a determination and
# useless for defect detection: the battery found zero flags on a case that carries seven,
# because a contradiction needs at least two documents each stating the same fact. F-1 is the
# clearest case -- the personnel number is printed on seven documents and two of them disagree,
# and no single page can reveal that.
# ==============================================================================================

ASSERTIONS = "assertions.json"

#: Documents swept for identifiers. §13.5 F-1 names the cover and Form D-I against the LPC,
#: salary statement, service statement, bank form and ACS NDC, so the sweep covers both sides
#: of that disagreement rather than only the documents the determination happens to need.
#: Words a card uses for its own holder, and for the relations printed beside them.
_CARD_HOLDER_ROLES = ("holder", "self", "cardholder", "card holder", "owner", "bearer")
_CARD_RELATION_ROLES = ("spouse", "husband", "wife", "father", "mother", "son", "daughter",
                        "guardian", "next of kin")


def one_holder_per_card(entries: list[dict]) -> list[dict]:
    """A CNIC card carries one identity number, and it is the holder's.

    A card prints the holder's name and, beside it, a father's or husband's name. Asked for
    every CNIC on the page with the name printed next to it, the model returned the single
    number twice -- once for the holder and once for her husband, who has a card of his own
    with a different number on it. Recording that would put a wife's number against a
    husband, and the identity check groups by person: his real number, read from any other
    page, would then contradict hers.

    Where the same number is claimed for more than one person, the holder is kept. Where no
    role says which of them is the holder we cannot tell, so the number is kept with no
    person against it -- enough to corroborate the card, not enough to accuse anyone. A
    guess here files a widow's card under the deceased.
    """
    by_number: dict[str, list[dict]] = {}
    for e in entries:
        by_number.setdefault(e["value"], []).append(e)

    kept: list[dict] = []
    for number, group in by_number.items():
        names = {(e["person"] or "").casefold() for e in group if e["person"]}
        if len(names) <= 1:
            kept.append(group[0])
            continue
        holders = [e for e in group
                   if any(w in (e["role"] or "").casefold() for w in _CARD_HOLDER_ROLES)]
        relations = [e for e in group
                     if any(w in (e["role"] or "").casefold() for w in _CARD_RELATION_ROLES)]
        if len(holders) == 1:
            kept.append(holders[0])
        elif len(relations) == len(group) - 1 and len(group) - len(relations) == 1:
            kept.append(next(e for e in group if e not in relations))
        else:
            anonymous = dict(group[0]); anonymous["person"] = None; anonymous["role"] = None
            kept.append(anonymous)
    return kept


#: Documents that print what the office actually PAID, as against a figure a department
#: typed onto a sanction form.
_PAY_DOCS = ("LPC", "SALARY_STATEMENT", "PENSION_SLIP")

#: How a pay table labels the basic pay itself, as against the allowances beside it. Matched
#: exactly, because "Pay" is the basic and "Adhoc Relief Allow" is not, and an allowance
#: swept into the pension base would raise every figure below it.
_BASIC_PAY_LABELS = ("PAY", "BASIC PAY", "BASIC")


def basic_pay_in(components: list) -> int | None:
    """The basic pay from a read pay table, or None where no line says plainly which it is.

    Returns None rather than the largest figure or the first. On this office's Last Pay
    Certificate the adhoc relief for 2023 is larger than the basic pay, and the first column
    of a transposed table is a heading -- so both of those guesses produce a wrong pension
    that looks entirely reasonable.

    Accepts the ``PayComponent`` objects ``_pay_components`` returns as well as plain dicts.
    It was written for dicts and called with objects, so ``c.get`` raised on the first pay
    document of every bundle -- outside the per-document try/except -- and stage 6 died
    there: no assertions.json, no cross-document flags, and the report said "cross-document
    checks incomplete" on every case that carried a salary statement or an LPC.
    """
    for c in components:
        if isinstance(c, dict):
            label, component, amount = c.get("printed_label"), c.get("component"), c.get("amount")
        else:
            label, component, amount = c.printed_label, c.component, c.amount
        label = str(label or "").strip().upper()
        if amount and (component == "basic_pay" or label in _BASIC_PAY_LABELS):
            return int(amount)
    return None


def looks_fabricated(cnic: str) -> bool:
    """Is this 13-digit string a padded guess rather than a read number?

    The last digit of a CNIC is a gender digit and the seven before it a serial. Six or
    more trailing zeros is not an issued pattern; it is what a model produces when it is
    told a CNIC has exactly 13 digits and can only read the first few. Observed on real
    scans as 35203-0000000-0 and 35202-0000000-0, against a true 00001-0000111-8.

    A fabricated number is worse than a missing one. It appears on more than one page, so
    it clears the corroboration guard, and then contradicts the number that is real.
    """
    return len(cnic) - len(cnic.rstrip("0")) >= 6 or len(set(cnic)) == 1


_IDENTIFIER_DOCS = (
    "FORM_D_I", "FORM_D_II", "LPC", "SALARY_STATEMENT", "BANK_OPTION_FORM", "NDC",
    "SERVICE_STATEMENT", "FPPO", "FILE_COVER",
    # The cards themselves. Without them ``check_cnic_cards_belong_to_the_case`` reads a
    # card's number from nowhere and returns early, so substituting one person's CNIC copy
    # for another's passed as "CNIC present". Annex-A and the sanction forms stay out: the
    # family sweep below already reads Annex-A, and listing it here read the page twice.
    "CNIC", "CNIC_DECEASED", "CNIC_CLAIMANT",
    # The forwarding letter carries no identifier worth cross-checking, but it is the only
    # page that dates the department's transfer of a signed sanction to the AG -- and Form
    # D-I's own signature block is undated, so without this page the 15-day sanction SLA has
    # no printed end date at all and F-5 cannot be raised from evidence.
    "FORWARDING_LETTER",
    # The proforma for qualifying service (C2, 12 Oct 2026): its particulars and dates are
    # compared with every other paper that states them (decision S3).
    "QUALIFYING_SERVICE_PROFORMA",
)

#: Schema to read each document under. GENERIC_PAGE still carries the identifier envelope.
_SCHEMA_FOR = {
    # A card, read as a card (extraction.schemas.CNIC_CARD). Under GENERIC_PAGE it was asked
    # for up to 24 fields plus raw strings on a page that prints everything twice, in two
    # scripts, and ecb2 and b39c came back with no number from the card at all.
    "CNIC": "CNIC_CARD",
    "CNIC_CLAIMANT": "CNIC_CARD",
    "CNIC_DECEASED": "CNIC_CARD",
    "FORM_D_I": "FORM_D_I",
    # The death-of-a-pensioner form carries the same identifier envelope and the same
    # recovery clause as D-I, and was swept under neither: a D-II bundle had no F-3 check
    # and no identifiers from its own sanction form.
    "FORM_D_II": "FORM_D_II",
    "LPC": "AG_PAY_CERTIFICATE",
    "SALARY_STATEMENT": "AG_PAY_CERTIFICATE",
    "ANNEX_A": "DESCRIPTIVE_ROLL",
    "NADRA_FRC": "NADRA_FRC",
    "QUALIFYING_SERVICE_PROFORMA": "QUALIFYING_SERVICE_PROFORMA",
}


#: The proforma's fields that become per-document assertions, under the names the checks
#: compare them by (rules.flags), with the label each is printed beside: date of birth and
#: personnel number join the identity check, the service dates the proforma check.
_PROFORMA_DATES = (
    ("date_of_birth", "date_of_birth", r"date\s+of\s+birth"),
    ("date_of_appointment", "date_first_entry", r"date\s+of\s+appointm\w*"),
    ("date_of_retirement_or_death", "date_of_retirement", r"date\s+of\s+retirement\s*/?\s*death"),
)
_OCR_DATE = r"[^\n\d]{0,12}(\d{1,2}[-./]\d{1,2}[-./]\d{4})"


def proforma_assertions(data: dict, page: int, ocr_text: str | None) -> list[dict]:
    """What the proforma for qualifying service states, as assertions (scope change C2).

    A fact is kept only where two readers agree: the vision model's confirming double read and
    PaddleOCR's transcription of the same labelled line. Neither is a witness on its own. On the
    office's own sample the vision model read the date of birth as 1968, twice, where the page
    and OCR say 1966, and OCR read the superannuation date as "130-06-2026", taking a handwritten
    bracket for a digit. Either misread, kept, would have told a department its papers
    contradict each other -- a HIGH finding over a date that is right. A fact the two readers do
    not agree on is left out, so it raises nothing; the officer still reads the page.
    """
    def value(key: str) -> str:
        node = data.get(key)
        return str(node.get("value") or "").strip() if isinstance(node, dict) else ""

    text = re.sub(r"[ \t]+", " ", ocr_text or "")
    doc = "QUALIFYING_SERVICE_PROFORMA"
    out: list[dict] = []
    for key, field, label in _PROFORMA_DATES:
        seen = _as_iso_date(value(key))
        printed = re.search(label + _OCR_DATE, text, re.I)
        if seen is not None and printed and _as_iso_date(printed.group(1)) == seen:
            out.append({"field": field, "value": seen.isoformat(), "page": page, "document": doc})
    flat_digits = re.sub(r"\D", "", text)
    digits = "".join(c for c in value("personnel_no") if c.isdigit())
    if 6 <= len(digits) <= 10 and re.search(r"personnel\s+n(?:o|umber)[^\n]{0,30}?" + digits, text, re.I):
        out.append({"field": "personnel_no", "value": digits, "page": page, "document": doc})
    cnic = "".join(c for c in value("cnic") if c.isdigit())
    if len(cnic) == 13 and not looks_fabricated(cnic) and cnic in flat_digits:
        out.append({"field": "cnic", "value": cnic, "person": value("employee_name") or None,
                    "role": "employee", "page": page, "document": doc})
    return out



#: What a CNIC card prints beside its dates, as PaddleOCR transcribes it. The card prints
#: "Date of Expiry" and either a DD.MM.YYYY date or the word "Lifetime".
_CNIC_EXPIRY = re.compile(
    r"(?i)date\s*of\s*expiry\W{0,6}(lifetime|\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{2}-\d{2})")
_CNIC_ISSUE = re.compile(
    r"(?i)date\s*of\s*issue\W{0,6}(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{2}-\d{2})")
_CNIC_NUMBER = re.compile(r"\b(\d{5})[- ](\d{7})[- ](\d)\b")


def _iso(raw: str) -> str | None:
    raw = raw.strip()
    if raw.upper() == "LIFETIME":
        return "LIFETIME"
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def cnic_dates_from_text(text: str) -> dict:
    """The expiry and issue dates a CNIC page prints, read from its OCR text. Deterministic.

    A copy often carries both faces of a card, or two cards, so a label may occur several
    times. Every occurrence is collected and the value is used only where every occurrence
    agrees: a page carrying two cards with different expiries yields nothing here (the two
    cannot be told apart from text alone) and is left for the officer. The card number is
    returned on the same terms.

    Why OCR and not the vision model: on the CNIC page of the golden case the vision read
    ran past 8,192 output tokens twice (17 Sep 2026) and produced nothing, while PaddleOCR
    transcribed "Date of Expiry / Lifetime" in four seconds. A printed label and a printed
    date are OCR's job; judgement is not needed to read them.
    """
    expiries = {_iso(m.group(1)) for m in _CNIC_EXPIRY.finditer(text)} - {None}
    issues = {_iso(m.group(1)) for m in _CNIC_ISSUE.finditer(text)} - {None}
    numbers = {"".join(m.groups()) for m in _CNIC_NUMBER.finditer(text)}
    numbers = {n for n in numbers if not looks_fabricated(n)}
    issue = next(iter(issues)) if len(issues) == 1 else None
    expiry = next(iter(expiries)) if len(expiries) == 1 else None
    # "Lifetime" printed anywhere on a one-card page is that card's expiry. OCR reads the card's
    # two columns out of order: on ecb2 it printed "Date of Expiry / 24.06.2025 / Lifetime",
    # where 24.06.2025 is the issue date whose label it dropped.
    if re.search(r"(?i)\blife\s*time\b", text) and len(numbers) <= 1:
        expiry = "LIFETIME"
    # A card's expiry cannot precede the CNIC scheme (2002) or its own issue date. Where OCR
    # pairs the "Date of Expiry" label with a neighbouring date -- the Widow Daughter bundle
    # read a 1966 date of birth as the expiry -- the reading is a misread, not an expired
    # card, and an officer must not be told a card expired sixty years ago.
    if expiry and expiry != "LIFETIME":
        if expiry < "2002-01-01" or (issue and expiry <= issue):
            expiry = None
    return {
        "date_of_expiry": expiry,
        "date_of_issue": issue,
        "number": next(iter(numbers)) if len(numbers) == 1 else None,
        "expiry_readings": sorted(expiries),
    }


def cnic_card_by_ocr(image: Path, page: int, doc_type: str, person: str | None) -> list[dict]:
    """One ``cnic_cards`` entry for a CNIC page, from OCR, or none where nothing printed was read.

    Never raises: an OCR failure or a page with no readable expiry is an absence, which the
    rules treat as "not measured". The entry says it came from OCR so an auditor can tell it
    from a vision read.
    """
    try:
        from extraction.ocr import ocr_card_page
        text = ocr_card_page(image, page).text
    except Exception:                                # noqa: BLE001
        return []
    read = cnic_dates_from_text(text)
    if read["date_of_expiry"] is None and read["date_of_issue"] is None:
        return []
    return [{
        "page": page, "document": doc_type, "number": read["number"],
        "person": (person or "").strip() or None,
        "date_of_issue": read["date_of_issue"], "date_of_expiry": read["date_of_expiry"],
        "source": "ocr",
        **({"expiry_readings": read["expiry_readings"]} if len(read["expiry_readings"]) > 1 else {}),
    }]


def cnic_cards_on(holders: list, page: int, doc_type: str) -> list[dict]:
    """The card(s) on a CNIC page with their printed issue and expiry dates.

    A card is valid to its 'Date of Expiry' or for the holder's lifetime. The claimant's card
    must be in force when the case is submitted (SOP §5.2 AG-02, "valid CNIC"), and only the
    card itself prints the date -- so it is recorded here, per page, beside the number and
    the name, and the rules side measures it. Dates are kept as the model normalised them
    (YYYY-MM-DD) or the word LIFETIME; anything else is kept verbatim and will fail to parse
    into a date, which the rules treat as "not read" rather than as valid or expired.
    """
    out: list[dict] = []
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        digits = "".join(ch for ch in str(holder.get("number", "")) if ch.isdigit())
        if len(digits) != 13 or looks_fabricated(digits):
            continue
        expiry = (holder.get("date_of_expiry") or "").strip() or None
        issue = (holder.get("date_of_issue") or "").strip() or None
        if expiry is None and issue is None:
            continue
        out.append({
            "page": page, "document": doc_type, "number": digits,
            "person": (holder.get("person") or "").strip() or None,
            "date_of_issue": issue,
            "date_of_expiry": expiry,
        })
    return out


def check_attestation_by_ocr(result: dict, documents: list, image_for: dict,
                             *, progress: Callable[[str], None] | None = None,
                             only_pages: set[int] | None = None) -> int:
    """A second reader for every required copy the page reading called unattested.

    The vision model's ``attested`` answer flips from run to run on the same page (a CNIC
    that prints its holder's own signature reads True one run and False the next), so on its
    own it cannot accuse a department. ``extraction.ocr.attestation_on`` reads the page in
    bands and looks for the attesting officer's stated office where it is signed. The report
    treats a copy as unattested only where both readers agree (``pipeline.report``).
    Returns the number of pages read; a page already checked is not read again.
    """
    from extraction.ocr import attestation_on
    from rules.checklist import ATTESTED_COPY_TYPES

    from pipeline import timing

    done = {c["page"] for c in result.get("attestation_checked", [])}
    wanted: list[int] = []
    for doc in documents:
        if doc.get("type") not in ATTESTED_COPY_TYPES or doc.get("attested") is not False:
            continue
        for page in doc.get("pages") or []:
            if page in done or page not in image_for:
                continue
            if only_pages is not None and page not in only_pages:
                continue
            if page not in wanted:
                wanted.append(page)

    def _read_attestation(page: int):
        try:
            return attestation_on(image_for[page], page)
        except Exception:                            # noqa: BLE001
            return None                              # not read: the first answer stands

    if OCR_SWEEP_CONCURRENCY <= 1 or len(wanted) < 2:
        bands = [(p, _read_attestation(p)) for p in wanted]
    else:
        with ThreadPoolExecutor(max_workers=min(OCR_SWEEP_CONCURRENCY, len(wanted))) as ap:
            bands = list(zip(wanted, [f.result() for f in [
                ap.submit(timing.carry(_read_attestation, stage="ocr", page=p), p)
                for p in wanted]]))

    read = 0
    for page, found in bands:
        if found is None:
            continue
        read += 1
        if progress:
            progress(f"stage 6  p.{page} attestation "
                     + (", ".join(found.marks) if found.marks else "none found"))
        result.setdefault("attestation_checked", []).append({
            "page": page, "marks": list(found.marks),
            "read_the_foot": found.read_the_foot, "by": "ocr",
        })
    return read


def refresh_attestation(run_dir: str | Path) -> int:
    """Run the attestation second reader on a finished run, appending to assertions.json."""
    run = Path(run_dir)
    out_path = run / ASSERTIONS
    if not out_path.exists():
        return 0
    result = json.loads(out_path.read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    image_for = {p["page"]: run / p["image_path"] for p in manifest["pages"]}
    documents = json.loads((run / "documents.json").read_text())
    n = check_attestation_by_ocr(result, documents, image_for)
    atomic_write_text(out_path, json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return n


def refresh_cnic_cards(run_dir: str | Path, *, progress: Callable[[str], None] | None = None) -> int:
    """Read the issue and expiry dates off every CNIC page of a finished run that lacks them.

    For runs extracted before ``cnic_cards`` existed. Re-reads only the CNIC pages (one
    confirming double read each), never the rest of the bundle, and appends to
    ``assertions.json`` atomically. Returns the number of pages read. A page that cannot be
    read is recorded under ``unreadable`` like any other, so the report says so.
    """
    run = Path(run_dir)
    out_path = run / ASSERTIONS
    if not out_path.exists():
        return 0
    result = json.loads(out_path.read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    image_for = {p["page"]: run / p["image_path"] for p in manifest["pages"]}
    documents = json.loads((run / "documents.json").read_text())
    have = {c["page"] for c in result.get("cnic_cards", [])}
    checked = set(result.get("cnic_cards_checked", []))
    read_pages = 0
    for doc in documents:
        if not doc["type"].startswith("CNIC") or not doc.get("pages"):
            continue
        page = doc["pages"][0]
        if page in have or page in checked or page not in image_for:
            continue
        if progress:
            progress(f"cnic cards  {doc['type']} p.{page}")
        result.setdefault("cnic_cards", []).extend(
            cnic_card_by_ocr(image_for[page], page, doc["type"], doc.get("person_named")))
        result.setdefault("cnic_cards_checked", []).append(page)
        read_pages += 1
        atomic_write_text(out_path, json.dumps(result, indent=2, ensure_ascii=False, default=str))
    atomic_write_text(out_path, json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return read_pages


def stage_assertions(
    run_dir: str | Path,
    *,
    progress: Callable[[str], None] | None = None,
    carry: dict | None = None,
) -> dict:
    """Collect the same fact as stated by each document. Resumable.

    Identifier pages are read with the confirming double read. A single misread digit here
    does not produce a wrong field -- it invents a personnel-number mismatch, and F-1 is a
    HIGH flag that blocks a PPO and sends a shortcoming letter to a department that did
    nothing wrong. A false accusation costs more than a second read.
    """
    run = Path(run_dir)
    out_path = run / ASSERTIONS
    done = read_checkpoint(out_path)
    if done is not None:
        return done

    manifest = json.loads((run / "manifest.json").read_text())
    image_for = {p["page"]: run / p["image_path"] for p in manifest["pages"]}
    documents = json.loads((run / "documents.json").read_text())

    # Resume from a checkpoint rather than restarting. Each document is ~83s of GPU.
    result: dict[str, Any] = {
        "assertions": [], "annex_a_family": [], "frc_family": [], "recoveries": [],
        "document_dates": [], "names": [], "issuing_offices": [], "unreadable": [],
        "payroll_deductions_noted": [], "cnic_cards": [], "disputed": [],
    }
    # A resubmission (pipeline.carryover): what the earlier round read from the pages this
    # round carries, under their new numbers, and only the new pages are read below. Facts
    # read from a page the department withdrew are dropped by the remap.
    only_pages: set[int] | None = None
    carried_counts: dict[str, int] = {}
    if carry:
        from pipeline import carryover
        only_pages = set(carry.get("new_pages") or [])
        base = carryover.remap(carryover.base_artefact(carry, ASSERTIONS) or {}, carryover.forward_map(carry)) or {}
        for key, value in base.items():
            if key == "carryover":
                continue
            result[key] = value
        carried_counts = {k: len(v) for k, v in base.items() if isinstance(v, list)}
    partial = run / (ASSERTIONS + ".partial")
    resumed = read_checkpoint(partial)
    if resumed:
        result.update(resumed)
    done_pages = {d["page"] for d in result.get("document_dates", [])}
    seen_pages: set[int] = set(done_pages)

    def checkpoint(final: bool = False) -> None:
        """Write after every document. BUILD §5.1.

        This stage originally wrote only on completion, and a crash on its last document
        discarded every page before it. The same principle already protects stage_identify;
        a stage that costs ten minutes of GPU must not be all-or-nothing.
        """
        target = out_path if final else partial
        atomic_write_text(target, json.dumps(result, indent=2, ensure_ascii=False, default=str))

    # -- identifiers, stated per document ------------------------------------------------
    # Ordered so the documents that DECIDE flags come first. The bundle order put twelve
    # No-Demand Certificates ahead of the LPC carrying the recovery and the Form D-I carrying
    # the sanction, so a sweep interrupted at twenty minutes had read almost nothing that
    # produces a finding. The NDCs only add corroboration to F-1; they can wait.
    _PRIORITY = {"FORM_D_I": 0, "FORM_D_II": 0, "LPC": 1, "SALARY_STATEMENT": 2, "FORWARDING_LETTER": 3,
                 "FILE_COVER": 4, "FPPO": 5, "BANK_OPTION_FORM": 6,
                 "SERVICE_STATEMENT": 7, "NDC": 8}
    ordered = sorted(documents, key=lambda d: (_PRIORITY.get(d["type"], 9), d.get("pages") or [0]))

    # Decide the work first, then fetch it concurrently, then fold the results in one at a
    # time. Each document is two vision calls (the confirming double read), and feeding them
    # to the server one at a time left three of its four batch slots idle: eight documents
    # took ten minutes on the 44-page case.
    #
    # Results are consumed in SUBMISSION order, not completion order, so the priority
    # ordering above still holds and the checkpoint after each document still means what it
    # meant -- the accumulation and the write stay on this thread.
    jobs: list[tuple[dict, int, str]] = []
    for doc in ordered:
        if doc["type"] not in _IDENTIFIER_DOCS or not doc["pages"]:
            continue
        page = doc["pages"][0]
        if page in seen_pages:
            continue
        if only_pages is not None and page not in only_pages:
            continue
        seen_pages.add(page)
        jobs.append((doc, page, _SCHEMA_FOR.get(doc["type"], "GENERIC_PAGE")))

    from pipeline import timing
    pool = ThreadPoolExecutor(max_workers=ASSERTION_CONCURRENCY)
    futures = [
        pool.submit(timing.carry(extract_page_confirmed, stage="assertions", page=pg), image_for[pg], schema_name=sch)
        for _doc, pg, sch in jobs
    ]
    # -- family, submitted with the pool above and folded at the end of the stage ---------
    # Measured on run 5407024d3f55 (21 Oct 2026): the pool above drained at t=107s and the
    # stage then ran to t=226s with exactly ONE request in flight the whole way -- 119s, 53%
    # of the stage and 41% of the case, strictly serial. Most of it was the family sweep:
    # Annex-A and the FRC one after the other, each a confirming double read, 22.2 + 23.6 +
    # 17.1 + 23.9s.
    #
    # The two documents are independent of everything else in the stage. Started after the
    # pool they simply queued behind it: on run 2429ac0a7f81 they began at t=116s, once the
    # pool had drained at 107s, and ran to 161s -- and because the two chains are unequal, the
    # Annex-A confirming read spent its last 21s as the only request in flight. Submitted with
    # the pool instead, a ~45s chain finishes well inside the pool's own 107s and costs the
    # stage nothing.
    #
    # So the reads start here and are folded in their old order below. Every mutation of
    # `result`, every progress line and every checkpoint still happens on this thread, in the
    # order it happened before; only the waiting moved.
    family_jobs: list[tuple[str, str, int]] = []
    for family_type, family_key in (("ANNEX_A", "annex_a_family"), ("NADRA_FRC", "frc_family")):
        family_doc = next((d for d in documents
                           if d["type"] == family_type and d["pages"]), None)
        if family_doc is None:
            continue
        family_page = family_doc["pages"][0]
        if only_pages is not None and family_page not in only_pages:
            continue                         # carried: the earlier round's reading stands
        family_jobs.append((family_type, family_key, family_page))

    family_pool = ThreadPoolExecutor(max_workers=max(1, len(family_jobs)))
    family_futures = [
        family_pool.submit(
            timing.carry(extract_page_confirmed, stage="assertions", page=pg),
            image_for[pg], schema_name=_SCHEMA_FOR[dt])
        for dt, _key, pg in family_jobs
    ]

    try:
        for (doc, page, schema), future in zip(jobs, futures):
            if progress:
                progress(f"stage 6  {doc['type']} p.{page}")
            try:
                # BOTH halves. extract_page_confirmed returns (extraction, agreement), and
                # taking only [0] applied half of decision H1: the reader blanks a disputed
                # figure or date, the page then contributes nothing, and NOTHING said why.
                # On the 78-page bundle p.60's document_date read four different values across
                # four attempts; it is absent from document_dates, absent from unreadable, and
                # raises no finding (20 Oct 2026). Stage 4 keeps its agreements and they reach
                # check_disputed_reads through fields.json; stage 6 dropped its own.
                #
                # "A check that silently did not run is worse than a missing field"
                # (rules.flags.check_disputed_reads).
                extraction, agreement = future.result()
                data = extraction.data
                if isinstance(agreement, dict) and not agreement.get("agree", True):
                    result["disputed"].append({
                        "page": page, "document": doc["type"],
                        "fields": list(agreement.get("disputed") or ("figures on the page",)),
                    })
            except Exception as exc:                 # noqa: BLE001
                # Do NOT just log this. An unreadable determination-critical document has to
                # reach the case report as a finding: LPC p.29 failed all three read attempts on
                # the real case, and because the failure only went to a progress line the report
                # showed no F-3 and no indication that the page carrying the recovery had never
                # been read. Silence is the worst possible rendering of "we could not read it".
                result["unreadable"].append({
                    "page": page, "document": doc["type"], "reason": str(exc)[:300],
                })
                if progress:
                    progress(f"stage 6  p.{page} UNREADABLE — recorded as a finding")
                # Skip the page. Without this the block below reads `data` from the PREVIOUS
                # document still bound to the name, and files that document's date and person
                # name under THIS page and type -- fabricated evidence, attributed to a page
                # that was never read, produced by the error handler itself.
                continue
            # F-5 needs a dated event per document; F-6 needs the name as THIS page spells it.
            for key, bucket in (("document_date", "document_dates"), ("person_name", "names"),
                                ("issuing_office", "issuing_offices")):
                node = data.get(key)
                if isinstance(node, dict) and node.get("value"):
                    result.setdefault(bucket, []).append({
                        "value": str(node["value"]).strip(),
                        "confidence": float(node.get("confidence") or 0.0),
                        "page": page, "document": doc["type"],
                    })

            # What the servant was drawing, and in which grade. Only from a pay document:
            # a sanction form quotes a figure the department typed, a pay certificate
            # prints what the office actually paid.
            if doc["type"] in _PAY_DOCS:
                basic = basic_pay_in(_pay_components(data, page,
                                                     data.get("gross_printed_rs")))
                if basic:
                    result["assertions"].append({
                        "field": "basic_pay", "value": str(basic),
                        "page": page, "document": doc["type"],
                    })
                # The grade, and on the AG's payroll statement the scale, the stage, the pay
                # and the servant's dates, are read by OCR, not by the vision model. Asked for
                # a grade the model once returned "BS. 12" for a BS-19 officer at confidence
                # 1.00, and every value here decides a rupee figure or which documents the
                # office demands (extraction.payroll).
                try:
                    from extraction.ocr import ocr_page as _ocr
                    from extraction.payroll import payroll_facts_on
                    from rules.case_type import pay_scale_from_form
                    pay_text = _ocr(image_for[page], page, max_tokens=3072).text
                    facts = payroll_facts_on(pay_text)
                    # An LPC prints the grade in a sentence rather than a field.
                    grade = facts.bps or pay_scale_from_form(pay_text)
                except Exception:                        # noqa: BLE001
                    pay_text, facts, grade = "", None, None
                if grade:
                    result["assertions"].append({
                        "field": "pay_scale_bps", "value": str(grade),
                        "page": page, "document": doc["type"],
                    })
                if facts:
                    if facts.basic_pay and not basic:
                        result["assertions"].append({
                            "field": "basic_pay", "value": str(facts.basic_pay),
                            "page": page, "document": doc["type"],
                        })
                    for field, value in (
                        ("pay_scale_year", facts.pay_scale_year),
                        ("pay_stage", facts.pay_stage),
                        ("date_of_birth", facts.date_of_birth),
                        ("date_first_entry", facts.entry_into_service),
                        ("length_of_service_stated", facts.length_of_service),
                        ("statement_month", facts.statement_month),
                        ("personnel_no", facts.personnel_no),
                        ("cnic", facts.cnic),
                    ):
                        if value is not None:
                            result["assertions"].append({
                                "field": field,
                                "value": value.isoformat() if hasattr(value, "isoformat")
                                         else str(value),
                                "page": page, "document": doc["type"],
                            })

            idents = data.get("identifiers") or {}
            if doc["type"] == "QUALIFYING_SERVICE_PROFORMA":
                result["assertions"].extend(proforma_assertions(data, page, page_ocr_text(run, page) or ""))
                # Its CNIC and personnel number come only from proforma_assertions, where OCR must
                # agree with the vision read. The sweep below takes the vision read alone, and on
                # the office's sample that read was wrong where OCR was right (12 Oct 2026).
                idents = {}
            # A CNIC is 13 digits, printed as 00000-0000000-0. Every page that quotes one is
            # kept, because the check that matters is whether the SAME person's number is the
            # same everywhere -- and because a CNIC card whose number is quoted nowhere else
            # in the case may be somebody else's card (SOP §6.1).
            on_this_page: list[dict] = []
            # A card carries ONE number and it is the holder's. CNIC_CARD asks for it in a
            # field of its own, more reliable than the identifier sweep on a page that prints
            # the same value in two scripts.
            if doc["type"].startswith("CNIC") and (data.get("attested_by") or "").strip():
                result.setdefault("attestation_checked", []).append({
                    "page": page, "marks": [str(data["attested_by"]).strip()[:120]],
                    "read_the_foot": True, "by": "vision card read",
                })
            if doc["type"].startswith("CNIC") and data.get("identity_number"):
                printed = "".join(c for c in str(data["identity_number"]) if c.isdigit())
                holder_name = data.get("person_name") or {}
                if len(printed) == 13 and not looks_fabricated(printed):
                    on_this_page.append({
                        "field": "cnic", "value": printed,
                        "person": (holder_name.get("value") or "").strip() or None,
                        "role": "holder",
                        "page": page, "document": doc["type"],
                    })
            for holder in idents.get("cnic") or []:
                if not isinstance(holder, dict):
                    continue
                digits = "".join(ch for ch in str(holder.get("number", "")) if ch.isdigit())
                if len(digits) != 13 or looks_fabricated(digits):
                    continue
                on_this_page.append({
                    "field": "cnic", "value": digits,
                    "person": (holder.get("person") or "").strip() or None,
                    "role": (holder.get("role") or "").strip() or None,
                    "page": page, "document": doc["type"],
                })
            # Only on a card. A form legitimately quotes one number for one person and
            # another for the next; it is a card that can carry only one.
            if doc["type"].startswith("CNIC"):
                on_this_page = one_holder_per_card(on_this_page)
                holders = list(idents.get("cnic") or [])
                # The card form states the dates at the top level, beside the one number.
                if data.get("identity_number") and (data.get("date_of_expiry")
                                                    or data.get("date_of_issue")):
                    holders.insert(0, {
                        "number": data["identity_number"],
                        "person": (data.get("person_name") or {}).get("value"),
                        "date_of_issue": _iso(str(data.get("date_of_issue") or "")) or None,
                        "date_of_expiry": _iso(str(data.get("date_of_expiry") or "")) or None,
                    })
                cards = cnic_cards_on(holders, page, doc["type"])
                # The printed dates are OCR's job (see cnic_dates_from_text); the vision read
                # is kept where it answered, OCR fills in where it did not.
                if not any(c.get("date_of_expiry") for c in cards):
                    cards = cnic_card_by_ocr(image_for[page], page, doc["type"],
                                             doc.get("person_named")) or cards
                result.setdefault("cnic_cards", []).extend(cards)
            result["assertions"].extend(on_this_page)
            for value in idents.get("personnel_no") or []:
                digits = "".join(ch for ch in str(value) if ch.isdigit())
                if len(digits) >= 6:                     # a personnel number, not a page number
                    result["assertions"].append({
                        "field": "personnel_no", "value": digits,
                        "page": page, "document": doc["type"],
                    })
            # F-3: the sanction form's own claim that nothing is recoverable.
            declared = data.get("recovery_declared")
            if isinstance(declared, dict) and declared.get("value"):
                result["form_recovery_declared"] = {
                    "text": declared["value"], "page": page, "document": doc["type"],
                }
            # F-3: the LPC's contradicting figure. BRAIN §8.3 makes the LPC the authority on
            # "recoveries and demands", so only an LPC contributes one. The salary statement
            # prints "Recoverable: 220,941.56" against Deductions - Income Tax: that is an
            # outstanding payroll deduction, not a departmental demand against the gratuity,
            # and letting it reach F-3 would raise a HIGH flag over the wrong rupees. It is
            # still recorded, under its own key, because evidence read and then discarded
            # silently is the failure this pipeline keeps re-learning.
            note = data.get("recovery_note")
            if isinstance(note, dict) and note.get("value"):
                amount = money_in_text(str(note["value"]))
                # Bounds match extraction.ocr.recoveries_in: a few rupees, or more than any
                # plausible pay run, is a misread rather than a demand.
                if amount is not None and 100 <= amount <= 10_000_000:
                    entry = {
                        "amount": int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
                        "amount_exact": str(amount),
                        "reason": str(note["value"])[:160],
                        "page": page, "document": doc["type"],
                    }
                    key = "recoveries" if doc["type"] == "LPC" else "payroll_deductions_noted"
                    result.setdefault(key, []).append(entry)
            checkpoint()
    finally:
        pool.shutdown(wait=False)
    # -- recoveries, read by OCR from every LPC ------------------------------------------
    # §8.3 puts the LPC above every other document on recoveries, so every LPC is read --
    # not just the first, and not only the ones the vision model managed. OCR is the reader
    # because a recovery is a printed figure beside a printed word.
    from extraction.ocr import ocr_page, recoveries_in

    lpc_pages = [page for doc in documents if doc["type"] == "LPC"
                 for page in doc["pages"]
                 if only_pages is None or page in only_pages]

    def _read_recoveries(page: int):
        """In the pool. Returns what was read, or the exception, for folding on the caller."""
        try:
            return recoveries_in(ocr_page(image_for[page], page))
        except Exception as exc:                     # noqa: BLE001
            return exc

    if OCR_SWEEP_CONCURRENCY <= 1 or len(lpc_pages) < 2:
        swept = [(p, _read_recoveries(p)) for p in lpc_pages]
    else:
        with ThreadPoolExecutor(max_workers=min(OCR_SWEEP_CONCURRENCY, len(lpc_pages))) as rp:
            swept = list(zip(lpc_pages, [f.result() for f in [
                rp.submit(timing.carry(_read_recoveries, stage="ocr", page=p), p)
                for p in lpc_pages]]))

    for page, found in swept:
        if isinstance(found, Exception):
            result["unreadable"].append({
                "page": page, "document": "LPC",
                "reason": f"OCR failed: {str(found)[:200]}",
            })
            continue
        already = {(r["page"], r["amount"]) for r in result["recoveries"]}
        for rec in found:
            if (rec["page"], rec["amount"]) in already:
                continue                # the vision reader already stated this same figure
            if progress:
                progress(f"stage 6  LPC p.{page} recovery {rec['amount']:,} (OCR)")
            result["recoveries"].append({
                **rec, "amount_exact": str(rec["amount"]), "document": "LPC",
            })
    checkpoint()

    # -- attestation, read a second time where the page reading saw none ----------------
    check_attestation_by_ocr(result, documents, image_for, progress=progress,
                             only_pages=only_pages)
    checkpoint()

    # -- family, as Annex-A states it and as NADRA records it -----------------------------
    for (doc_type, key, page), family_future in zip(family_jobs, family_futures):
        if progress:
            progress(f"stage 6  {doc_type} p.{page}")
        try:
            # (extraction, agreement), as the pool above also takes it; this sweep has only
            # ever used the extraction, and that is left exactly as it was.
            data = family_future.result()[0].data
        except Exception as exc:                     # noqa: BLE001
            if progress:
                progress(f"stage 6  {doc_type} p.{page} unreadable — {exc}")
            continue
        # `field_key`, not `key`: the enclosing loop binds `key` to the family bucket name
        # and the family loop below uses it. Shadowing it here made result[key] resolve to
        # "person_name" and killed the sweep on its LAST document, discarding 19 documents of
        # GPU work (2026-09-04).
        for field_key, bucket in (("document_date", "document_dates"),
                                  ("person_name", "names")):
            node = data.get(field_key)
            if isinstance(node, dict) and node.get("value"):
                result[bucket].append({
                    "value": str(node["value"]).strip(),
                    "confidence": float(node.get("confidence") or 0.0),
                    "page": page, "document": doc_type,
                })
        for m in data.get("family_members") or []:
            if not m.get("name"):
                continue
            result[key].append({
                "name": str(m["name"]).strip(),
                "relation": str(m.get("relation") or "").strip(),
                "marital_status": str(m.get("marital_status") or "").strip(),
                "page": page, "document": doc_type,
            })
        checkpoint()
    family_pool.shutdown(wait=False)

    if carry:
        result["carryover"] = {
            "reused": carried_counts,
            "run": {k: len(v) - carried_counts.get(k, 0) for k, v in result.items()
                    if isinstance(v, list)},
            "pages_read": sorted(only_pages or ()),
        }
    checkpoint(final=True)
    partial.unlink(missing_ok=True)
    return result
