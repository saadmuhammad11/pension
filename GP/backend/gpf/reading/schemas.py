"""Per-artefact extraction schemas (spec §4.2).

One schema per artefact type. Every field carries a *field class* that decides
its confidence threshold (spec §4.5) — the model never auto-accepts a financial
or identity field below threshold; those go to a person. The schemas also build
the JSON Schema handed to vLLM for guided/structured decoding, so the model can
only emit `{value, confidence, page, bbox}` per field — never free prose that
another component parses (spec §0 rule 2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .artefacts import Artefact

# field classes -> thresholds live in gpf.clients.model_client.THRESHOLDS
FINANCIAL = "financial"     # account numbers, CNIC, amounts, dates -> 0.95
IDENTITY = "identity"       # names -> 0.85
STRUCTURAL = "structural"   # signature/stamp present -> 0.90
NARRATIVE = "narrative"     # rule text, reasons -> 0.70
SERVICE_BOOK = "service_book"  # any Service Book field -> 0.98


@dataclass(frozen=True)
class FieldSpec:
    name: str
    field_class: str
    required: bool = False
    identifier: bool = False   # a "three-state" identifier field (§4.2): empty / wrong-kind / correct
    kind: str = "string"       # string | number | bool
    desc: str = ""
    enum: tuple = ()           # if set, guided decoding constrains the value to these choices


def _f(name, fc, **kw):
    if "enum" in kw and isinstance(kw["enum"], (list, tuple)):
        kw["enum"] = tuple(kw["enum"])
    return FieldSpec(name, fc, **kw)


#: Advance-limit clauses the sanction can quote (matches ADV_LIMITS keys in rules_family).
CLAUSE_ENUM = ["1.14(1)(c)(i)", "1.14(1)(d)(i)", "1.14(1)(e)(i)-car", "1.14(1)(e)(i)-motorcycle",
               "1.14(1)(e)(i)-bicycle", "1.15(a)", "1.15(b)", "1.15(c)", "1.15(d)", "1.16", "1.18"]


SCHEMAS: dict[Artefact, list[FieldSpec]] = {
    Artefact.SAP_PAYSLIP: [
        _f("pers_no", FINANCIAL, required=True, identifier=True),
        _f("name", IDENTITY, required=True),
        _f("designation", NARRATIVE),
        _f("cnic", FINANCIAL, identifier=True),
        _f("month", FINANCIAL),
        _f("bps", IDENTITY),
        _f("ddo_code", IDENTITY),
        _f("gpf_no", FINANCIAL, identifier=True),
        _f("old_gpf_no", FINANCIAL, identifier=True),
        # The printed SAP pay slip carries the fund and any advance in its LOAN/FUND block --
        # columns PRINCIPAL, REPAID, BALANCE -- not under a "GPF Balance" label (30 Sep 2026: the
        # balance on PC-2026-000050, "GPF#: 255,534.00", was read as nothing).
        _f("gpf_balance", FINANCIAL, kind="number",
           desc="the GP Fund balance: in the LOAN/FUND block, the BALANCE figure on the row headed 'GPF#' "
                "(or 'GPF', 'G.P. Fund'); on a text extract, the 'GPF Balance' line"),
        _f("gpf_subscription", FINANCIAL, kind="number",
           desc="the monthly GP Fund subscription deducted: the 'GPF Subscription' deduction amount"),
        _f("gpf_loan_instalment", FINANCIAL, kind="number",
           desc="the monthly recovery of a GP Fund advance: the 'GPF Advance/Loan' deduction amount, if any"),
        _f("gpf_loan_balance", FINANCIAL, kind="number",
           desc="the GP Fund advance still to be recovered: in the LOAN/FUND block, the BALANCE on a row for a "
                "GPF advance or loan (not the GPF# fund row, not income tax or house building); 0 where the "
                "block shows no GPF advance; on a text extract, the 'GPF Loan Balance' line"),
        _f("basic_pay", FINANCIAL, kind="number"),
        _f("osd_post", NARRATIVE),
        _f("gazetted_flag", STRUCTURAL),
        _f("attested", STRUCTURAL, kind="bool"),
    ],
    Artefact.SAP_GPF_RECALC_REPORT: [
        _f("pers_no", FINANCIAL, required=True, identifier=True),
        _f("name", IDENTITY),
        _f("gpf_reference", FINANCIAL, identifier=True),
        _f("report_date", FINANCIAL),
        _f("sap_user", NARRATIVE),
        # rows are handled separately (a table), see extract_table()
    ],
    Artefact.SANCTION_ORDER: [
        _f("order_no", FINANCIAL, required=True, identifier=True),
        _f("date", FINANCIAL, required=True),
        _f("dept", NARRATIVE),
        _f("printed_authority", NARRATIVE),
        _f("actual_signatory", IDENTITY),
        _f("for_marker", STRUCTURAL, kind="bool"),
        _f("amount", FINANCIAL, required=True, kind="number"),
        _f("rule", NARRATIVE),
        _f("reason", NARRATIVE),
        _f("limit_clause", NARRATIVE, enum=CLAUSE_ENUM,
           desc=("the advance-limit clause, chosen by the PURPOSE/reason of the advance (and the letter in "
                 "the quoted rule). House or plot — build, buy or REPAIR a house, or purchase a plot → "
                 "1.14(1)(d)(i). Car/scooter/motorcycle/bicycle → 1.14(1)(e)(i)-*. General temporary "
                 "(illness, passage, ceremonies, Haj, marriage, education, other) → 1.14(1)(c)(i). "
                 "Non-refundable after age 50 → 1.15(a)-(d) or 1.16; house at 45+ → 1.18. If the quoted "
                 "rule text contains a bracketed letter (c)/(d)/(e), it usually identifies the sub-clause.")),
        _f("basic_pay_stated", FINANCIAL, kind="number"),
        _f("balance_stated", FINANCIAL, kind="number"),
        _f("qr_present", STRUCTURAL, kind="bool"),
    ],
    Artefact.FORM_PAY_05: [
        _f("personal_no", FINANCIAL, required=True, identifier=True),
        _f("name", IDENTITY),
        _f("cnic", FINANCIAL, identifier=True),
        _f("sig_kind", STRUCTURAL, enum=["signature", "thumb", "none"],
           desc="how the subscriber signed: 'signature', 'thumb' (thumb impression), or 'none'"),
        _f("ddo_signed", STRUCTURAL, kind="bool",
           desc="true if the form bears the DDO's signature and/or an office stamp/seal in the DDO block"),
        _f("ddo_stamp", NARRATIVE, desc="the text of the DDO's stamp/seal, if any"),
    ],
    Artefact.FORM_PAY_06: [
        _f("personal_no", FINANCIAL, required=True, identifier=True),
        _f("name", IDENTITY),
        _f("cnic", FINANCIAL, identifier=True),
        _f("old_gpf_no", FINANCIAL, identifier=True),
        _f("sig_kind", STRUCTURAL, enum=["signature", "thumb", "none"],
           desc="how the subscriber signed: 'signature', 'thumb' (thumb impression), or 'none'"),
        _f("ddo_signed", STRUCTURAL, kind="bool",
           desc="true if the form bears the DDO's signature and/or an office stamp/seal in the DDO block"),
        _f("ddo_stamp", NARRATIVE, desc="the text of the DDO's stamp/seal, if any"),
    ],
    Artefact.GPF_FORM_10: [
        _f("account_no", FINANCIAL, identifier=True),
        _f("old_gpf_no", FINANCIAL, identifier=True),
        _f("signed", STRUCTURAL, kind="bool"),
        _f("ddo_signed", STRUCTURAL, kind="bool"),
    ],
    Artefact.CNIC_SMART_FRONT: [
        _f("number", FINANCIAL, required=True, identifier=True),
        _f("name", IDENTITY, required=True),
        _f("holder_signature_present", STRUCTURAL, kind="bool"),
        _f("expiry", FINANCIAL),
        _f("attested", STRUCTURAL, kind="bool"),
    ],
    Artefact.CNIC_SMART_BACK: [
        _f("card_number", FINANCIAL, identifier=True),
        _f("qr_present", STRUCTURAL, kind="bool"),
    ],
    Artefact.CNIC_OLD_FRONT: [
        _f("number", FINANCIAL, required=True, identifier=True),
        _f("name", IDENTITY, required=True),
        _f("attested", STRUCTURAL, kind="bool"),
    ],
    Artefact.CNIC_OLD_BACK: [
        _f("thumbprint_present", STRUCTURAL, kind="bool"),
        _f("pdf417_present", STRUCTURAL, kind="bool"),
    ],
    Artefact.CHALLAN_32A: [
        _f("sr", IDENTITY, identifier=True),
        _f("amount", FINANCIAL, required=True, kind="number"),
        _f("bank_stamp_present", STRUCTURAL, kind="bool"),
        _f("treasury_verified", STRUCTURAL, kind="bool"),
        _f("period", NARRATIVE),
        _f("cheque", FINANCIAL, identifier=True),
    ],
    Artefact.RETIREMENT_NOTIF: [
        _f("no", FINANCIAL, identifier=True), _f("date", FINANCIAL), _f("label", NARRATIVE),
    ],
    Artefact.PUNISHMENT_ORDER: [
        _f("no", FINANCIAL, identifier=True), _f("date", FINANCIAL),
        _f("qr_present", STRUCTURAL, kind="bool"),
    ],
    Artefact.OBITUARY_NOTIF: [
        _f("no", FINANCIAL, identifier=True), _f("date", FINANCIAL),
    ],
    Artefact.SERVICE_BOOK_PAGE: [
        _f("dor", SERVICE_BOOK, kind="bool", desc="date of retirement entered"),
        _f("order", SERVICE_BOOK, kind="bool", desc="order of retirement entered"),
        _f("leave", SERVICE_BOOK, kind="bool", desc="leave account present"),
        _f("date_of_appointment", SERVICE_BOOK),
    ],
    Artefact.BALANCE_TRANSFER_PROF: [
        _f("name", IDENTITY), _f("father", IDENTITY), _f("designation", NARRATIVE),
        _f("old_ac", FINANCIAL, identifier=True), _f("new_ac", FINANCIAL, identifier=True),
        _f("last_deduction", FINANCIAL), _f("periods", NARRATIVE),
        _f("dao_confirmed", NARRATIVE),
    ],
}

#: The re-calculation report's ledger columns (a table, not scalar fields).
#: These are the *engine* keys (camelCase) so extracted rows drop straight into
#: facts.sap.recalc.rows with no translation.
RECALC_ROW_KEYS = ["start", "end", "opening", "subscription", "adjustments", "tempAdvance",
                   "recTempAdvance", "permanentAdvance", "interest", "closing"]
RECALC_COLUMNS = RECALC_ROW_KEYS  # kept for back-compat


def recalc_rows_json_schema() -> dict:
    """JSON Schema for guided extraction of the GPF re-calculation ledger (a table)."""
    props = {}
    for c in RECALC_ROW_KEYS:
        props[c] = {"type": ["string"]} if c in ("start", "end") else {"type": ["number", "null"]}
    return {
        "type": "object",
        "properties": {
            "rows": {"type": "array", "items": {
                "type": "object", "properties": props, "required": RECALC_ROW_KEYS,
                "additionalProperties": False}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["rows", "confidence"],
        "additionalProperties": False,
    }


def field_map(artefact: Artefact) -> dict[str, FieldSpec]:
    return {f.name: f for f in SCHEMAS.get(artefact, [])}


def to_json_schema(artefact: Artefact) -> dict:
    """Build the JSON Schema for vLLM guided decoding of this artefact.

    Each field must be emitted as {value, confidence, page, bbox}. Required
    fields must be present; the model returns confidence so gating can run.
    """
    specs = SCHEMAS.get(artefact, [])
    props = {}
    for s in specs:
        value_type = {"number": ["number", "null"], "bool": ["boolean", "null"]}.get(s.kind, ["string", "null"])
        value_schema = {"type": value_type}
        if s.enum:
            value_schema["enum"] = [*s.enum, None]
        props[s.name] = {
            "type": "object",
            "properties": {
                "value": value_schema,
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "page": {"type": ["integer", "null"]},
                "bbox": {"type": ["array", "null"], "items": {"type": "number"}},
            },
            "required": ["value", "confidence"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": props,
        "required": [s.name for s in specs if s.required],
        "additionalProperties": False,
    }
