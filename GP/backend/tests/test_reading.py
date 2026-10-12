"""Reading pipeline (spec §3-§4): schemas, confidence gating, and the full
reading -> facts -> rules seam driven by a scripted model (no Spark needed)."""
import pytest

from gpf import evaluate
from gpf.clients import ExtractedField, ScriptedModelClient
from gpf.reading import (Artefact, Page, ReadingPipeline, SCHEMAS, ScriptedBarcodeDecoder,
                         field_map, to_json_schema)
from gpf.reading.barcodes import DecodedCode


# ── schemas ───────────────────────────────────────────────────────────────────
def test_every_schema_builds_valid_json_schema():
    for art in SCHEMAS:
        js = to_json_schema(art)
        assert js["type"] == "object"
        assert set(js["required"]).issubset(js["properties"].keys())
        for name, prop in js["properties"].items():
            assert "value" in prop["properties"] and "confidence" in prop["properties"]


def test_identifier_fields_are_financial_or_identity():
    for art, specs in SCHEMAS.items():
        for s in specs:
            if s.identifier:
                assert s.field_class in ("financial", "identity"), (art, s.name)


# ── confidence gating (§4.5) ──────────────────────────────────────────────────
def test_financial_field_below_threshold_needs_human():
    ef = ExtractedField(value="90000227", confidence=0.90, field_class="financial")  # < 0.95
    assert ef.needs_human
    ef2 = ExtractedField(value="90000227", confidence=0.97, field_class="financial")
    assert not ef2.needs_human


def test_narrative_field_tolerates_lower_confidence():
    assert not ExtractedField(value="repair of house", confidence=0.75, field_class="narrative").needs_human
    assert ExtractedField(value="x", confidence=0.60, field_class="narrative").needs_human


# ── end-to-end: scripted reading of a refundable advance -> facts -> rules ────
def _ef(art, name, value, conf):
    fc = field_map(Artefact(art))[name].field_class
    return ExtractedField(value=value, confidence=conf, field_class=fc)


def _fields(art, spec):
    return {name: _ef(art, name, val, conf) for name, (val, conf) in spec.items()}


RECALC_ROWS = [
    {"start": "01.07.2025", "end": "30.06.2026", "opening": 54194, "subscription": 18000,
     "adjustments": 0, "tempAdvance": 0, "recTempAdvance": 0, "permanentAdvance": 0,
     "interest": 7705, "closing": 79899},
    {"start": "01.07.2026", "end": "30.06.2027", "opening": 79899, "subscription": 3000,
     "adjustments": 0, "tempAdvance": 58000, "recTempAdvance": 2000, "permanentAdvance": 0,
     "interest": 0, "closing": 26899},
]


def _scripted_refundable():
    A = Artefact
    classifications = {
        "p1": ExtractedField(A.SANCTION_ORDER.value, 0.98, field_class="structural"),
        "p2": ExtractedField(A.CNIC_SMART_FRONT.value, 0.98, field_class="structural"),
        "p3": ExtractedField(A.CNIC_SMART_BACK.value, 0.97, field_class="structural"),
        "p4": ExtractedField(A.FORM_PAY_05.value, 0.97, field_class="structural"),
        "p5": ExtractedField(A.SAP_PAYSLIP.value, 0.99, field_class="structural"),
        "p6": ExtractedField(A.SAP_GPF_RECALC_REPORT.value, 0.99, field_class="structural"),
    }
    extractions = {
        "p1": _fields(A.SANCTION_ORDER.value, {
            "order_no": ("1463/GPF-Ops", 0.98), "date": ("07-08-2026", 0.98),
            "dept": ("Punjab Police", 0.97), "printed_authority": ("Deputy Inspector General of Police, Operations, Lahore", 0.95),
            "actual_signatory": ("SP Headquarters", 0.9), "for_marker": (True, 0.95),
            "amount": (58000, 0.98), "rule": ("Rule 1.14(1)(a)(iv)(d)(i)", 0.9),
            "reason": ("Repair of house", 0.9), "limit_clause": ("1.14(1)(d)(i)", 0.9),
            "basic_pay_stated": (19040, 0.5),  # deliberately low -> needs human
        }),
        "p2": _fields(A.CNIC_SMART_FRONT.value, {
            "number": ("00001-0000101-3", 0.98), "name": ("Subscribar F. Test", 0.9),
            "holder_signature_present": (True, 0.95), "attested": (False, 0.95)}),
        "p3": _fields(A.CNIC_SMART_BACK.value, {"qr_present": (True, 0.95), "card_number": ("108261290869", 0.9)}),
        "p4": _fields(A.FORM_PAY_05.value, {
            "personal_no": ("90000227", 0.98), "name": ("Subscriber F. Test", 0.9), "cnic": ("", 0.9),
            "sig_kind": ("signature", 0.95), "ddo_signed": (True, 0.95),
            "ddo_stamp": ("SP Headquarters for DIG Operations, Lahore", 0.9)}),
        "p5": _fields(A.SAP_PAYSLIP.value, {
            "pers_no": ("90000227", 0.99), "name": ("SUBSCRIBER F. TEST", 0.95), "month": ("August 2026", 0.95),
            "gpf_balance": (19194, 0.97), "gpf_loan_balance": (56000, 0.95), "basic_pay": (22890, 0.96),
            "attested": (False, 0.95)}),
        "p6": {**_fields(A.SAP_GPF_RECALC_REPORT.value, {
            "pers_no": ("90000227", 0.99), "report_date": ("10.09.2026", 0.95)}),
            "rows": ExtractedField(value=RECALC_ROWS, confidence=0.97, field_class="financial")},
    }
    return classifications, extractions


def test_pipeline_reads_refundable_and_rules_accept_it():
    classifications, extractions = _scripted_refundable()
    model = ScriptedModelClient(classifications, extractions)
    barcodes = ScriptedBarcodeDecoder({3: [DecodedCode("QR code", "10826129086900001000010131", 3)]})
    pipeline = ReadingPipeline(model, barcodes)
    pages = [Page(i + 1, f"p{i + 1}") for i in range(6)]

    result = pipeline.run(pages, kind="refundable", gazetted="non-gazetted")
    F = result.facts

    # the assembler produced the right facts shape
    assert F["personnelNo"] == "90000227"
    assert F["docs"]["sanction"]["amount"] == 58000
    assert F["docs"]["changeForm"]["label"] == "FORM PAY 05"
    assert len(F["docs"]["cnics"]) == 1 and F["docs"]["cnics"][0]["type"] == "smart"
    assert F["sap"]["payslip"]["persNo"] == "90000227"
    assert len(F["sap"]["recalc"]["rows"]) == 2
    assert any(q["decoded"] for q in F["qr"])

    # the low-confidence financial field was routed to a person, not guessed
    assert any(n["field"] == "basic_pay_stated" for n in result.needs_human)

    # and the rules engine accepts the assembled facts
    results = {r["id"]: r["status"] for r in evaluate(F)}
    assert results["ADV-SANCTION"] == "ok"
    assert results["ADV-CNIC"] == "ok"
    assert results["ADV-FORM"] == "ok"
    assert results["SAP-PAYSLIP"] == "ok"
    assert results["SAP-RECALC"] == "ok"
    assert results["ADV-LIMIT"] == "ok"          # Rs 58,000 within the Rule 1.14(1)(d)(i) limit
    assert results["SAP-IDENTITY"] == "ok"


def test_unknown_artefact_escalates_without_crashing():
    model = ScriptedModelClient({"p1": ExtractedField("UNKNOWN", 0.4, field_class="structural")}, {})
    result = ReadingPipeline(model).run([Page(1, "p1")], kind="refundable")
    assert result.pages[0].artefact == "UNKNOWN"
    assert result.pages[0].fields == {}


# ── progress reporting (so the officer is not left watching a dead screen) ─────
def test_run_reports_progress_without_changing_what_is_read():
    """The callback is advisory: same facts with it and without it, and it names every
    page and stage in order so a bar can be a measurement rather than a guess."""
    model = ScriptedModelClient(
        {"p1": ExtractedField("SANCTION_ORDER", 0.98, field_class="structural"),
         "p2": ExtractedField("CNIC_SMART", 0.97, field_class="structural")},
        {("p1", "SANCTION_ORDER"): {}, ("p2", "CNIC_SMART"): {}})
    pages = [Page(1, "p1"), Page(2, "p2")]

    quiet = ReadingPipeline(model).run(pages, kind="refundable")
    events: list[dict] = []
    loud = ReadingPipeline(model).run(pages, kind="refundable", on_progress=events.append)

    assert loud.facts == quiet.facts          # advisory, never load-bearing

    stages = [e["stage"] for e in events]
    assert stages[0] == "ingest" and stages[-1] == "done"
    assert "assemble" in stages
    assert stages.count("classify") == 2 and stages.count("extract") == 2

    assert all(e["total"] == 2 for e in events)
    done = [e["done"] for e in events]
    assert done == sorted(done) and done[-1] == 2      # never goes backwards
    assert [e["page"] for e in events if e["stage"] == "classify"] == [1, 2]


def test_illegible_pages_are_reported_and_still_counted():
    model = ScriptedModelClient({"p2": ExtractedField("CNIC_SMART", 0.97, field_class="structural")},
                                {("p2", "CNIC_SMART"): {}})
    events: list[dict] = []
    result = ReadingPipeline(model).run([Page(1, "p1", illegible=True), Page(2, "p2")],
                                        kind="refundable", on_progress=events.append)
    assert result.illegible_pages == [1]
    assert any(e["stage"] == "illegible" and e["page"] == 1 for e in events)
    # the bar must still reach the end when a page is skipped
    assert events[-1]["done"] == 2


# ── resubmission: the per-case page cache (30 Sep 2026) ─────────────────────
class _Counting:
    """A model client that records every page it was asked about."""
    def __init__(self, inner):
        self.inner, self.seen = inner, []

    def classify_document(self, image_ref):
        self.seen.append(image_ref)
        return self.inner.classify_document(image_ref)

    def extract_fields(self, image_ref, artefact_type):
        return self.inner.extract_fields(image_ref, artefact_type)


def test_a_resubmission_reads_only_its_new_pages_and_assembles_the_same_case(tmp_path):
    from gpf.reading.page_cache import PageCache
    classifications, extractions = _scripted_refundable()
    barcodes = ScriptedBarcodeDecoder({3: [DecodedCode("QR code", "10826129086900001000010131", 3)]})
    cache = PageCache(tmp_path, "portal-case-x")

    # Round 1: the payslip and recalculation report (p5, p6) are missing. Every page is read.
    model = _Counting(ScriptedModelClient(classifications, extractions))
    r1 = ReadingPipeline(model, barcodes).run(
        [Page(i + 1, f"p{i + 1}") for i in range(4)], kind="refundable", gazetted="non-gazetted",
        cache=cache, page_keys=[f"docA:{k}" for k in range(1, 5)])
    assert model.seen == ["p1", "p2", "p3", "p4"] and r1.reused_pages == []

    # Round 2: the same document plus the two new pages. Only p5 and p6 reach the model.
    model = _Counting(ScriptedModelClient(classifications, extractions))
    events: list[dict] = []
    r2 = ReadingPipeline(model, barcodes).run(
        [Page(i + 1, f"p{i + 1}") for i in range(6)], kind="refundable", gazetted="non-gazetted",
        cache=cache, page_keys=[f"docA:{k}" for k in range(1, 5)] + ["docB:1", "docB:2"], on_progress=events.append)
    assert model.seen == ["p5", "p6"]
    assert r2.reused_pages == [1, 2, 3, 4]
    assert sum(1 for e in events if e.get("reused")) == 4

    # The case assembled from the reused pages is the case a full read produces.
    full = ReadingPipeline(ScriptedModelClient(classifications, extractions), barcodes).run(
        [Page(i + 1, f"p{i + 1}") for i in range(6)], kind="refundable", gazetted="non-gazetted")
    assert r2.facts == full.facts
    assert r2.needs_human == full.needs_human


def test_without_keys_the_cache_is_never_used(tmp_path):
    from gpf.reading.page_cache import PageCache
    classifications, extractions = _scripted_refundable()
    cache = PageCache(tmp_path, "portal-case-y")
    for _ in range(2):
        model = _Counting(ScriptedModelClient(classifications, extractions))
        ReadingPipeline(model).run([Page(1, "p1"), Page(2, "p2")], kind="refundable", cache=cache)
        assert model.seen == ["p1", "p2"]


# ── fund and advance balances (30 Sep 2026) ──────────────────────────────────
def test_the_fund_block_of_a_printed_pay_slip_is_read_exactly():
    from gpf.reading.payslip_text import fund_block
    # PC-2026-000050's slip, as OCR reads it: the balance sits in the LOAN/FUND block.
    text = ("PAYMENTS AMOUNT DEDUCTIONS AMOUNT LOAN/FUND PRINCIPAL REPAID BALANCE\n"
            "0001 Basic Pay 31,130.00 3003 GPF Subscription 1,150.00-   GPF#: 255,534.00\n")
    assert fund_block(text) == {"gpf_balance": 255534.0, "gpf_loan_balance": 0.0}
    with_advance = "LOAN/FUND PRINCIPAL REPAID BALANCE\nGPF#: 19,194.00\nGPF ADV 58,000.00 2,000.00 56,000.00"
    assert fund_block(with_advance) == {"gpf_balance": 19194.0, "gpf_loan_balance": 56000.0}
    # A subscription deduction is never the fund; no block, no figures.
    assert fund_block("3003 GPF Subscription 1,150.00-\nNET PAY 65,418.00") == {"gpf_balance": None, "gpf_loan_balance": None}


def test_fund_position_is_what_the_pay_slip_prints_never_a_calculation():
    from gpf.rules_family import fund_position
    F = {"kind": "refundable", "sap": {"payslip": {"gpfBalance": 19194, "loanBalance": 56000, "month": "August 2026", "page": 5},
                                       "recalc": {"rows": RECALC_ROWS}}}
    pos = fund_position(F)
    assert pos["gpf"] == {"value": 19194, "source": "payslip", "page": 5, "month": "August 2026"}
    assert pos["loan"] == {"value": 56000, "source": "payslip", "page": 5, "month": "August 2026"}
    assert pos["reportClosing"] == {"value": 26899, "asOf": "30.06.2027"}      # for reference only
    # Not printed on the pay slip: reported as not printed, never worked out from the report.
    missing = fund_position({"sap": {"payslip": {"month": "08.2026"}, "recalc": {"rows": RECALC_ROWS}}})
    assert missing["gpf"] is None and missing["loan"] is None
    assert fund_position({}) == {"gpf": None, "loan": None, "reportClosing": None, "payslip": False}


def test_an_item_shows_the_pages_of_the_papers_it_compares():
    """30 Sep 2026: 'Applicant on the form is the subscriber' compares three papers and showed no page."""
    from gpf.reference_pages import reference_pages
    F = {"docs": {"changeForm": {"page": 3, "label": "FORM PAY 05"}, "cnics": [{"page": 5}], "sanction": {"page": 2}},
         "sap": {"payslip": {"page": 4}, "recalc": {"page": 1}}}
    item = {"id": "ADV-APPLICANT", "title": "Applicant on the form is the subscriber",
            "finding": "Name on the FORM PAY 05 is Langri Rauf; SAP pay slip reads MUHAMMAD RAUF; CNIC reads Muhammad Rauf."}
    assert [(p["page"], p["label"]) for p in reference_pages(item, F)] == [(3, "Application form · page 3"), (4, "SAP pay slip · page 4"), (5, "CNIC copy · page 5")]
    # A paper that is not in the case has no page to show.
    missing = {"id": "FP-FORM06", "title": "Change Form-06 signed by DDO and subscriber", "finding": "Change Form-06 is not attached."}
    assert reference_pages(missing, {"docs": {}, "sap": {}}) == []
    # A page the finding quotes is shown too.
    quoted = {"id": "CNIC-ATTEST", "title": "Attestation", "finding": "The copy at page 7 is not attested."}
    assert 7 in [p["page"] for p in reference_pages(quoted, {})]
