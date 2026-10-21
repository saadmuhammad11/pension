"""Vision-model client. Every request is schema-constrained; there is no other path.

Design rules carried from AGPB-BUILD:
  §6.2  AI extracts, code calculates. Nothing here computes a rupee figure.
  §5.1  Never silent-accept low confidence -- enforced in the pipeline, not left to the model.
  §2.2  Pin everything: weights, quantisation, prompt version, so a determination is
        reproducible by an auditor years later.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from extraction.classify import classify_pay_label
from extraction.model_auth import model_headers
from extraction.schemas import SCHEMAS

#: The vision model. PENSION_VISION_URL points a deployment at its own GPU box (docs/DEPLOYMENT.md F4).
from extraction import envfile as _envfile

DEFAULT_ENDPOINT = _envfile.endpoint("PENSION_VISION_URL", "vision")
DEFAULT_MODEL = "qwen3-vl-30b-a3b-fp8"

PROMPT_VERSION = "AGPB-EXTRACT-PROMPT-1.0"

SYSTEM = (
    "You read scanned Pakistani government pension documents for the Accountant General, Punjab.\n"
    "You extract and you report. You never calculate an amount and you never guess a value.\n"
    "An illegible value is null with a reason in `unreadable`; a plausible reconstruction is worse "
    "than an honest gap, because a gap gets checked and a plausible number gets paid.\n"
    "Report what each document says. You do not reconcile contradictions between documents -- "
    "a contradiction is a finding for code to raise, not an error for you to smooth over."
)

INSTRUCTION = (
    "Read this scanned page and populate the schema.\n"
    "Reckonable for pension means ONLY: basic pay, special pay, personal pay, qualification pay, "
    "technical pay, senior post allowance, and orderly allowance. House rent, medical, "
    "conveyance, special allowances, adhoc reliefs and all deductions are NOT reckonable.\n"
    "Where a form prints a dash for a component, its amount is null -- do not record it as 0.\n"
    "Record every monetary figure with the label printed beside it. Never place an identifier "
    "(CNIC, IBAN, account or personnel number, phone) or a date into a monetary field.\n"
    # The schema declared these fields and the instruction never asked for them, so the model
    # returned empty arrays on every page -- including a CNIC card. A schema constrains the
    # SHAPE of an answer; only the instruction asks the question.
    "Fill `identifiers` from the page as well. Record EVERY CNIC printed anywhere on it -- "
    "in a heading, a table row, a signature block, a stamp -- and for each one give the name "
    "printed with it and the word the page uses for that person. A page quoting two people's "
    "CNICs yields two entries. Include witnesses and attesting officers; say so in `role` "
    "rather than leaving them out.\n"
    # NOT asked for here, deliberately. Three lines asking for the card's 'Date of Issue' and
    # 'Date of Expiry' were added on 17 Sep 2026 and the very next read of the golden case's
    # CNIC page ran past 8,192 output tokens twice and produced nothing; the same page with
    # these lines removed read in 27 s. The two schema fields stay (the model may fill them
    # unprompted) and the printed dates are read by OCR instead -- pipeline.extract
    # .cnic_dates_from_text -- which is where a printed label and a printed date belong.
    "A CNIC is EXACTLY 13 digits, printed 00000-0000000-0. A number of any other length is "
    "not a CNIC: an 11-digit 0300-0000000 is a phone, a 9- to 12-digit number beside a bank "
    "is an account_no. Put those in their own fields and never in `cnic`.\n"
    # "EXACTLY 13 digits" on its own is an instruction to produce 13 digits, and on a blurred
    # scan the model obeyed it by padding what it could read with zeros: 35203-0000000-0 from
    # a card whose real number is 00001-0000111-8. A fabricated number is worse than a missing
    # one -- it corroborates itself across pages and contradicts the truth.
    "Never pad, complete or guess a CNIC to reach 13 digits. If some digits are illegible, "
    "omit the entry entirely and list the number under what you could not read. A partly "
    "read CNIC is not a CNIC.\n"
    # A CNIC card was reported with person "deceased" -- a role the model inferred from the
    # pension context, not a name printed anywhere on the card. Grouping by that would file a
    # widow's own card under the deceased and flag a sound case.
    # The card at p.5 of a real bundle returned its single number twice -- once for the
    # holder, once for the husband whose name is printed beside hers. He has his own card
    # with his own number, and recording hers against him makes the identity check compare
    # the wrong pair.
    "A CNIC card carries ONE identity number and it belongs to the holder. The father's or "
    "husband's name printed beside the holder's is a relation, not a second holder: do not "
    "repeat the number against them. Give one entry, `person` the holder's name and `role` "
    "\"holder\".\n"
    "`person` must be a NAME as printed. If the page shows a number with no name beside it, "
    "`person` is null -- never a role word, and never a guess from what the case is about. A "
    "CNIC card shows one person's name and number: report that name. You cannot tell from a "
    "card whether its holder is the deceased or the claimant, so do not say.\n"
    "Give your own confidence per value, and list everything you could not read."
)


class ExtractionError(RuntimeError):
    """The model returned something unusable. Never swallowed: a bad page must be visible."""


@dataclass(frozen=True)
class Extraction:
    """A single page's structured read, with the provenance an audit needs."""

    data: dict[str, Any]
    doc_type: str
    schema_name: str
    source: str
    model: str
    prompt_version: str
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    warnings: list[str] = field(default_factory=list)

    @property
    def low_confidence(self) -> list[tuple[str, float]]:
        """Values below the 0.80 accept threshold (BRAIN §5.3). These route to a human."""
        out: list[tuple[str, float]] = []

        def walk(node: Any, path: str) -> None:
            if isinstance(node, dict):
                conf = node.get("confidence")
                if isinstance(conf, (int, float)) and conf < 0.80:
                    out.append((path or "<root>", float(conf)))
                for k, v in node.items():
                    walk(v, f"{path}.{k}" if path else k)
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        walk(self.data, "")
        return out


def usable_pay_rows(comps: list, printed_total: int | None) -> list[dict]:
    """The rows a determination would actually be built from, after deterministic cleaning.

    The same three filters ``pipeline.extract._pay_components`` applies before any figure is
    summed, and deliberately the same order:

    1.  a row with no amount is not a figure;
    2.  a row whose amount IS the printed total is the total line itself, or the phantom the
        model makes by pairing the total with the next label (on Form D-I, "Orderly Allowance
        192,030" -- reckonable, and summing it would double the pension for life);
    3.  a row whose label ``classify_pay_label`` does not recognise as a line item is not pay.
        That is what removes "Income Tax", "GPF Balance: 62,336.00", "Vendor Number: ...",
        "City: LAHORE" and a CNIC repeated to the schema cap.

    Kept here rather than imported from the pipeline because ``pipeline.extract`` imports this
    module; ``tests/test_pay_table_reads.py`` pins the two to the same answer on real payloads.
    """
    from .classify import classify_pay_label

    out = []
    for c in comps:
        amount = c.get("amount_rs")
        if not isinstance(amount, int):
            continue
        if printed_total is not None and amount == printed_total:
            continue
        if not classify_pay_label(str(c.get("printed_label") or "")).get("is_line_item"):
            continue
        out.append(c)
    return out


def amounts_look_unread(data: dict) -> bool:
    """Did this read come back with labels where the figures should be? See the caller.

    Split out of ``extract_page`` so the decision can be exercised without a model behind it:
    it is the test that decides whether a determination-critical page is usable, and it was
    only reachable through a live vLLM call.

    Judging on the raw row count rejected two pages that were read correctly, and cost the
    golden case its determination on 2026-09-15. Both pages carry real figures wrapped in
    noise the pipeline already discards:

        p041 (Form D-I)          24 rows,  4 amounts -- 4 pro-forma dashes, the printed total
                                 tagged as a pay row, a phantom orderly allowance, and a CNIC
                                 repeated 11 times to the schema cap.
        p042 (salary statement)  24 rows, 11 amounts -- 9 real pay rows summing exactly to the
                                 printed gross, plus an income-tax deduction, a GPF balance,
                                 and 13 rows of vendor number, bank details and domicile.

    After cleaning, p041 is 178,440 + 13,590 = 192,030 against a printed Total Pay of 192,030,
    and p042 is nine rows summing to 353,795 against a printed Gross of 353,795. Both reads
    were complete; only the packaging was noisy.

    So the test is whether the rows a determination would actually use reconcile with the total
    the form itself prints. The real pathology -- the page is legible and the digits are simply
    not emitted -- still fails it, because rows that were never read cannot add up.
    """
    comps = data.get("pay_components") or []
    filled = [c for c in comps if isinstance(c.get("amount_rs"), int)]
    if len(comps) < 3 or len(filled) * 2 >= len(comps):
        return False

    # Without the form's own total there is no independent witness, and a majority of nulls
    # cannot vouch for itself. Rejected, as before.
    printed_total = data.get("total_pay_printed_rs") or data.get("gross_printed_rs")
    if not isinstance(printed_total, int) or printed_total <= 0:
        return True

    usable = usable_pay_rows(comps, printed_total)
    return sum(c["amount_rs"] for c in usable) != printed_total


def extract_page(
    image: str | Path,
    schema_name: str = "GENERIC_PAGE",
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
    timeout_s: int = 900,
    extra_instruction: str | None = None,
    instruction_override: str | None = None,
    _retry_on_suspect: bool = True,
) -> Extraction:
    """Read one page image under a schema. Raises rather than returning something doubtful."""
    if schema_name not in SCHEMAS:
        raise KeyError(f"unknown schema {schema_name!r}; have {sorted(SCHEMAS)}")
    schema = SCHEMAS[schema_name]

    img = Path(image)
    b64 = base64.b64encode(img.read_bytes()).decode()
    # instruction_override REPLACES the default rather than appending to it. The default is
    # five lines about reckonable pay and monetary fields, which is the right framing for
    # field extraction and pure noise for a "which document is this page" task -- appending to
    # it made page identification confidently wrong (Form D-I read as DEPUTATION_CHALLANS at
    # 0.90 confidence, 2026-09-04).
    base = instruction_override or INSTRUCTION
    instruction = base if not extra_instruction else f"{base}\n{extra_instruction}"

    payload = {
        "model": model,
        "temperature": 0,               # determinism: same page, same read
        "max_tokens": max_tokens,
        # The whole point. Without this the model emits prose-wrapped JSON that can be invalid
        # (a leading-zero phone number in an int array killed a real page) and costs 3-7x
        # the output tokens.
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name.lower(), "schema": schema, "strict": True},
        },
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": instruction},
            ]},
        ],
    }

    req = urllib.request.Request(endpoint, json.dumps(payload).encode(), model_headers())
    started = time.time()
    from pipeline import timing
    try:
        raw = urllib.request.urlopen(req, timeout=timeout_s).read()
    except urllib.error.HTTPError as exc:                       # noqa: PERF203
        timing.model_call("vision", started=started, ended=time.time(), schema=schema_name, page=timing.page_of(img),
                          status="error", detail={"http": exc.code})
        raise ExtractionError(
            f"{img.name}: vision service returned HTTP {exc.code}: "
            f"{exc.read()[:400].decode(errors='replace')}"
        ) from exc
    except OSError as exc:
        timing.model_call("vision", started=started, ended=time.time(), schema=schema_name, page=timing.page_of(img),
                          status="error", detail={"error": str(exc)[:200]})
        raise ExtractionError(
            f"{img.name}: cannot reach the vision service at {endpoint} ({exc}). "
            "Check: systemctl status vllm-qwen3-vl"
        ) from exc
    elapsed = time.time() - started

    body = json.loads(raw)
    usage = (json.loads(raw).get("usage") or {}) if raw else {}
    timing.model_call("vision", started=started, ended=time.time(), schema=schema_name, page=timing.page_of(img),
                      detail={"prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                              "max_tokens": max_tokens})
    choice = body["choices"][0]
    content = choice["message"]["content"]
    usage = body.get("usage", {})

    warnings: list[str] = []
    if choice.get("finish_reason") == "length":
        # Fail, do not warn. A truncated extraction is missing fields with no marker saying
        # which, and a half-read pension form is exactly the kind of plausible-looking input
        # that must never reach a determination.
        raise ExtractionError(
            f"{img.name}: output hit max_tokens={max_tokens} and was truncated "
            f"({usage.get('completion_tokens', '?')} tokens emitted). The page is denser than "
            f"the budget. Re-read with a higher max_tokens; never use a truncated extraction."
        )

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        # With grammar-constrained decoding this should be unreachable. If it fires, the
        # constraint is not being applied -- check --structured-outputs-config on the server.
        raise ExtractionError(
            f"{img.name}: schema-constrained output did not parse ({exc}). "
            f"First 300 chars: {content[:300]!r}"
        ) from exc

    # First-request-after-restart defect, observed reproducibly across two restarts of this
    # service on 2026-09-02:
    #
    #   request #1 : 14 rows, 0 amounts filled, 1298 output tokens   -- WRONG
    #   requests #2-5: 13 rows, 13 amounts filled, 1329 tokens       -- correct, byte-identical
    #
    # Every printed_label came back correct while every amount_rs came back null, so the page was
    # legible and the digits were simply not emitted. A warmup request was tried and did NOT
    # prevent it, because that warmup used a different prompt and schema -- the real request was
    # still the first of its kind. The mechanism is not established (prefix caching, the
    # multimodal processor cache and first-use grammar compilation are all candidates), so this
    # guard deliberately does not depend on knowing it: it detects the symptom and re-reads.
    #
    # A pay table whose labels all read but whose amounts are all null is pathological, never a
    # legitimate result. Retrying costs one request; accepting it would feed a determination a
    # page of nulls.
    # Threshold, learned the hard way: an earlier version of this guard tested "no amount is an
    # integer" and FAILED TO FIRE on the real defect, because 1 row out of 14 (the recovery line)
    # did carry a figure. A pay table that reads 14 labels and one amount is just as pathological
    # as one that reads none, so the test is a MAJORITY of rows missing their amount.
    # A PRO-FORMA defeats the row-count test on its own. Form D-I prints six pay slots and the
    # department dashes the ones that do not apply, so on the golden case four of six are
    # legitimately empty and a faithful read IS a majority of nulls. The schema no longer asks
    # for those rows (see extraction/schemas.py, amount_rs), but a model that drifts back to
    # emitting them must not cost a case its determination a second time -- so the symptom is
    # checked against arithmetic rather than against an instruction the model may ignore.
    #
    # The form states its own Total Pay. Where the rows that DID carry figures already add up
    # to that total, the read is demonstrably complete and the empty labels are the form's own
    # blank slots. Where they do not, the figures really are missing and the guard stands. This
    # is the §8.4 reconciliation used as evidence of a complete read, and it cannot be talked
    # round by a prompt.
    comps = data.get("pay_components") or []
    filled = sum(1 for c in comps if isinstance(c.get("amount_rs"), int))
    if amounts_look_unread(data):
        symptom = (
            f"{img.name}: {len(comps)} pay rows were read with labels but only {filled} carry an "
            "amount. A legible pay table does not yield labels without figures."
        )
        if _retry_on_suspect:
            return extract_page(
                image, schema_name, endpoint=endpoint, model=model, max_tokens=max_tokens,
                timeout_s=timeout_s, extra_instruction=extra_instruction,
                _retry_on_suspect=False,
            )
        raise ExtractionError(
            symptom + " Retrying was disabled for this call, so no re-read was attempted. "
            "Do not use this extraction. Note that this page's FIRST read in a fresh server "
            "instance reproducibly fails this way while re-reads succeed, so a retry is the "
            "normal recovery; if retries also fail, re-read at higher resolution and have an "
            "officer transcribe the pay block."
        )

    return Extraction(
        data=data,
        doc_type=str(data.get("doc_type", "")),
        schema_name=schema_name,
        source=img.name,
        model=model,
        prompt_version=PROMPT_VERSION,
        latency_s=elapsed,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        warnings=warnings,
    )


def classified_lines(ext: Extraction) -> list[dict[str, Any]]:
    """Attach the deterministic classification to each transcribed pay line."""
    out = []
    for c in ext.data.get("pay_components") or []:
        cls = classify_pay_label(c.get("printed_label", ""))
        # The model's layout call and the rule table must agree on whether this is a line item.
        # Disagreement is itself a signal worth surfacing rather than silently resolving.
        model_says_line = c.get("line_kind") == "pay_or_allowance"
        row = {**c, **cls}
        row["is_line_item"] = cls["is_line_item"] and model_says_line
        row["kind_disagreement"] = (
            None if cls["is_line_item"] == model_says_line
            else f"model read this row as {c.get('line_kind')!r}; "
                 f"the rule table classifies it as {cls['component']!r}"
        )
        out.append(row)
    return out


def _reconcile(ext: Extraction, printed_field: str, subset: str, what: str) -> dict[str, Any]:
    """Compare a sum of transcribed lines against a total the page itself prints.

    BRAIN §8.4: 'The reckonable total on the form equals the sum of the components you
    extracted -- this is the single highest-value arithmetic check in the system.'

    It earns that. Two real errors on the golden case were caught by exactly this comparison and
    by nothing else:

      * Form D-I (p41): the model duplicated 13,590 into special and personal pay. Sum 205,620
        vs printed 192,030 -- would have inflated gross pension by ~9,513/month, for life.
      * AG certificate (p29): a clean single-digit misread of 'Adhoc Relief 2025' as 15,203
        instead of 19,203, a Rs. 4,000 error, reported at **confidence 1.00**.

    The second is the reason confidence is not a safety net and arithmetic is. Deterministic
    Python throughout: it compares two numbers the model read and reports whether they agree.
    It computes no entitlement and no pension.
    """
    lines = [c for c in classified_lines(ext) if c["is_line_item"]]
    if subset == "reckonable":
        lines = [c for c in lines if c["reckonable"]]
    summed = sum(c["amount_rs"] for c in lines if isinstance(c.get("amount_rs"), int))
    printed = ext.data.get(printed_field)
    unknown = [c["printed_label"] for c in classified_lines(ext) if c["needs_human"]]

    result: dict[str, Any] = {
        "sum_rs": summed, "printed_rs": printed, "lines_counted": len(lines),
        "unclassified_labels": unknown, "reconciles": None, "delta_rs": None, "finding": None,
    }
    if unknown:
        result["finding"] = (
            f"UNCLASSIFIED: {unknown} matched no rule in extraction.classify, so they were "
            "excluded from the sum. An officer must decide whether each is reckonable before "
            "any figure is used -- guessing would either understate or overstate a pension."
        )
        return result
    if not isinstance(printed, int):
        result["finding"] = (
            f"No printed {what} on this page, so the lines cannot be independently checked. "
            "Corroborate against the LPC or salary statement before relying on them."
        )
        return result

    result["reconciles"] = summed == printed
    result["delta_rs"] = summed - printed
    if not result["reconciles"]:
        dupes = sorted({c["amount_rs"] for c in lines
                        if isinstance(c.get("amount_rs"), int)
                        and [x["amount_rs"] for x in lines].count(c["amount_rs"]) > 1})
        hint = f" Duplicated amount(s) across lines: {dupes}." if dupes else ""
        result["finding"] = (
            f"CONTRA-MONEY: {what} lines sum to {summed:,} but the page prints {printed:,} "
            f"(delta {summed - printed:+,}). A line is misread, missing or double-counted."
            f"{hint} Have an officer confirm every line before any figure is used, and do not "
            "rely on the per-field confidence: a clean single-digit misread arrives at 1.00."
        )
    return result


def extract_page_confirmed(
    image: str | Path,
    schema_name: str = "GENERIC_PAGE",
    **kwargs: Any,
) -> tuple[Extraction, dict[str, Any]]:
    """Read a page twice and require the two reads to agree. Use for determination-critical pages.

    Why two reads
    -------------
    A page's FIRST read in a fresh server instance can be wrong in a way no per-field confidence
    reveals. Observed reproducibly on source page 29 of the golden case:

        read #1 : 14 rows, 1 amount,  1298 output tokens   -- WRONG
        read #2 : 13 rows, 13 amounts, 1329 tokens         -- correct
        read #3 : identical to #2
        read #4 : identical to #2

    Five explanations were tested and excluded by toggling one flag at a time against a
    controlled instance: Triton JIT / cold start (a warmup request did not prevent it, and a
    different page of identical geometry read correctly as the very first request); the synthetic
    warmup image as trigger (reproduces with no warmup at all); prefix caching
    (``--no-enable-prefix-caching`` reproduces); the multimodal processor cache
    (``--mm-processor-cache-gb 0`` reproduces, and reads #2-4 still succeed without it); and
    asynchronous scheduling (``--no-async-scheduling`` reproduces).

    The mechanism is therefore NOT established. That is exactly why this function does not depend
    on it: it exploits the one stable property observed across every variant -- reads after the
    first are byte-identical -- and requires agreement rather than trusting any single read.

    Cost is 2x inference (~60s rather than ~30s per page on the pilot hardware). For a
    determination that authorises a pension for the rest of someone's life, that is cheap; for
    bulk triage of non-critical pages, use :func:`extract_page` and rely on the
    majority-amounts-null guard and the arithmetic reconciliation instead.

    Issuing the two reads AT ONCE does not work, and was measured (21 Oct 2026)
    ------------------------------------------------------------------------
    It is the obvious optimisation -- stage 6 is 80% of a case and its critical path is these
    two reads in series -- so it was built behind a flag and put to five pages that had each
    produced a real extract-disagree finding, twice each, both ways. It failed on both counts:

        ef969066 p.14   sequential  61.6s  disputed document_date
                        sequential  56.2s  disputed document_date
                        concurrent  66.9s  AGREED            <- the dispute was lost
                        concurrent  66.4s  disputed document_date

    It is SLOWER (every page was level or worse: 66.9 against 61.6, 6.6 against 4.4), because
    the engine gives nothing away for batching two decodes -- two at once cost what two in a
    row cost. And it is less safe: two simultaneous reads are both FIRST reads, so the one
    property this function rests on is gone, and on that page it cost a real disagreement one
    time in two.

    Do not reach for it again without re-running that comparison. The code was written and
    reverted; the measurement is the part worth keeping.

    Returns ``(extraction, agreement)`` where the extraction is the SECOND read and agreement
    records whether the two agreed and on what. When the reads disagree on a figure or a date
    (business decision H1, 7 Oct 2026) the page's figures and the disputed dates are BLANKED in
    the returned read -- ``pay_components`` emptied, every ``*_rs`` field and each disputed date
    set to None -- and ``agreement["disputed"]`` names what differed, so nothing from the page is
    used and the report raises it for a person to read (rules.flags.check_disputed_reads).
    """
    kwargs.pop("_retry_on_suspect", None)

    # Read up to three times, tolerating a rejected read rather than aborting on it. An earlier
    # version called the inner read with retrying disabled, so a suspect FIRST read raised and
    # the comparison this function exists to perform never happened -- the guard defeated the
    # confirmation. A rejected read is data: it is recorded and the loop continues.
    reads: list[Extraction] = []
    rejected: list[str] = []
    for _ in range(3):
        try:
            reads.append(extract_page(image, schema_name, _retry_on_suspect=False, **kwargs))
        except ExtractionError as exc:
            rejected.append(str(exc)[:160])
        if len(reads) >= 2:
            break

    if len(reads) < 2:
        raise ExtractionError(
            f"{Path(image).name}: could not obtain two usable reads in three attempts. "
            f"Rejected: {rejected}. Do not use this page; have an officer transcribe it."
        )

    first, second = reads[-2], reads[-1]
    # Identifiers are compared too (ported from the Pension-AG deployment). Two reads of one
    # page returned 0000100001155 and 0000100001955, one digit apart, and those numbers are
    # acted on: an uncorroborated card returns a case, two numbers for one person is a HIGH
    # identity flag. A disagreement does not discard the page -- an identifier is not the
    # page's purpose -- but only the identifiers BOTH reads saw are kept.
    ids_a, ids_b = _identifiers(first.data), _identifiers(second.data)
    unconfirmed: dict[str, list[str]] = {}
    for field in set(ids_a) | set(ids_b):
        only_one = (ids_a.get(field, set()) ^ ids_b.get(field, set())) - {""}
        if only_one:
            unconfirmed[field] = sorted(only_one)
    if unconfirmed:
        kept = {}
        for field, values in (second.data.get("identifiers") or {}).items():
            agreed = ids_a.get(field, set()) & ids_b.get(field, set())
            kept[field] = [v for v in values or [] if _identifier_digits(v) in agreed]
        second.data["identifiers"] = kept
        # The card's own number field is held to the same test.
        if "identity_number" in second.data and \
                _identifier_digits(second.data.get("identity_number")) != \
                _identifier_digits(first.data.get("identity_number")):
            second.data["identity_number"] = None
    a, b = _figures_that_matter(first.data), _figures_that_matter(second.data)
    printed_a, printed_b = _printed_figures(first.data), _printed_figures(second.data)
    dates_a, dates_b = _dated_fields(first.data), _dated_fields(second.data)
    agree = a == b and printed_a == printed_b and dates_a == dates_b

    agreement = {
        "agree": agree,
        "reads_attempted": len(reads) + len(rejected),
        "reads_rejected": rejected,
        "read1_rows": len(a), "read2_rows": len(b),
        "read1_amounts": sum(1 for _, v in a if isinstance(v, int)),
        "read2_amounts": sum(1 for _, v in b if isinstance(v, int)),
        "read1_tokens": first.completion_tokens, "read2_tokens": second.completion_tokens,
        "identifiers_unconfirmed": unconfirmed,
        "finding": None,
    }
    if rejected:
        agreement["finding"] = (
            f"FIRST-READ REJECTED ({len(rejected)}x) then two agreeing reads obtained. "
            "This is the known wrong-first-read failure mode; the confirmed value is used, and "
            "the rejection is recorded so the rate can be monitored: "
            f"{rejected[0]}"
        )
    if not agree:
        only_a = [x for x in a if x not in b]
        only_b = [x for x in b if x not in a]
        disputed = sorted(
            {f"pay line '{label}'" for label, _ in (*only_a, *only_b)}
            | {k for k in set(printed_a) | set(printed_b) if printed_a.get(k) != printed_b.get(k)}
            | {k for k in set(dates_a) | set(dates_b) if dates_a.get(k) != dates_b.get(k)}
        )
        agreement["disputed"] = disputed
        agreement["blanked"] = True
        agreement["finding"] = (
            "READ-DISAGREEMENT: two reads of the same page differ on "
            + ", ".join(disputed[:6]) + (" …" if len(disputed) > 6 else "") + ". "
            f"Read A gave {len(a)} rows / {agreement['read1_amounts']} amounts; read B gave "
            f"{len(b)} rows / {agreement['read2_amounts']} amounts. "
            "No figure and no disputed date from this page is used; an officer reads the page "
            "and transcribes it (decision H1, 7 Oct 2026)."
        )
        _blank_disputed(second.data, disputed_dates={k for k in set(dates_a) | set(dates_b)
                                                     if dates_a.get(k) != dates_b.get(k)})
    return second, agreement


def _dated_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Every date the page states, as the schema names it (``date_of_birth``, ``date_of_death``,
    ``date_first_entry`` ...). A second read that moves a date has disagreed about something a
    determination runs from (H1, 7 Oct 2026); the self-pension refusal on a misread year is
    the shape of the harm."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        if "date" not in k or isinstance(v, (list, tuple)):
            continue
        out[k] = v.get("value") if isinstance(v, dict) else v
    return out


def _blank_disputed(data: dict[str, Any], disputed_dates: set[str]) -> None:
    """Take every figure, and each disputed date, out of a read whose twin disagreed. The page
    still identifies itself (names, form number, identifiers both reads saw) -- those are what
    tell the officer which page to read -- but nothing from it reaches a check or a figure."""
    data["pay_components"] = []
    for k, v in list(data.items()):
        if k.endswith("_rs") and not isinstance(v, (list, dict)):
            data[k] = None
    for k in disputed_dates:
        if isinstance(data.get(k), dict):
            data[k] = {**data[k], "value": None, "unreadable_reason": "two reads disagreed"}
        else:
            data[k] = None


def _identifier_digits(value: Any) -> str:
    """The digits of an identifier; a CNIC arrives as {number, person, role}, the rest bare."""
    raw = value.get("number") if isinstance(value, dict) else value
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def _identifiers(data: dict[str, Any]) -> dict[str, set[str]]:
    """Each identifier field's numbers as digits. Only the NUMBER is compared: the role a page
    gives a person is a judgement, and two readings of it differing says nothing about digits."""
    return {field: {_identifier_digits(v) for v in values or []}
            for field, values in (data.get("identifiers") or {}).items()}


def _figures_that_matter(data: dict[str, Any]) -> list[tuple[str, Any]]:
    """The pay rows a second read must reproduce: the LINE ITEMS, and only those.

    Deductions, printed totals and recoveries are never summed into a base, so a second
    read that renders "GPF Subscription -6,350" where the first wrote "GPFS Subscription
    6,350" has not disagreed about anything the determination uses. Counting it did:
    the OSD-post salary statement failed its confirmation on exactly that -- four deduction
    rows with their sign flipped -- while every pay line agreed to the rupee, and the page
    was recorded as unusable.
    """
    from .classify import classify_pay_label

    rows: list[tuple[str, Any]] = []
    for c in data.get("pay_components") or []:
        label = c.get("printed_label", "") or ""
        if not classify_pay_label(label)["is_line_item"]:
            continue
        rows.append((label, c.get("amount_rs")))
    return rows


def _printed_figures(data: dict[str, Any]) -> dict[str, Any]:
    """Every stated rupee figure on the page, whichever schema read it.

    Was the pair (gross_printed_rs, total_pay_printed_rs), which are Form D-I / pay
    certificate fields. Form D-II states the pension the deceased was drawing in
    ``pension_drawn_rs`` -- the one figure its whole determination rests on -- and a double
    read of that form compared nothing at all.
    """
    return {k: v for k, v in data.items()
            if k.endswith("_rs") and not isinstance(v, (list, dict))}


def reconcile_pay_components(ext: Extraction) -> dict[str, Any]:
    """Reckonable subtotal vs the form's printed 'Total Pay' (Form D-I / B-series)."""
    return _reconcile(ext, "total_pay_printed_rs", "reckonable", "reckonable pay")


def reconcile_gross(ext: Extraction) -> dict[str, Any]:
    """All pay lines vs the page's printed gross (LPC / AG pay certificate)."""
    return _reconcile(ext, "gross_printed_rs", "all", "gross pay")
