"""SAP text parsing, the identity gate, and cure-by-upload re-evaluation (spec §6, §7)."""
from pathlib import Path

import pytest

from gpf import evaluate
from gpf.clients import ManualUploadConnector
from gpf.fixtures import load_case
from gpf.sap import check_sap_against_case, parse_sap_file

SAMPLES = Path(__file__).resolve().parents[2] / "prototype" / "sap-samples"


def _read(pers_no):
    return (SAMPLES / f"SAP_EXTRACT_{pers_no}.txt").read_text(encoding="utf-8")


def test_parse_sample_extract():
    parsed = parse_sap_file("SAP_EXTRACT_90000227.txt", _read("90000227"))
    assert parsed["payslip"]["persNo"] == "90000227"
    assert parsed["payslip"]["gpfBalance"] == 19194
    assert parsed["payslip"]["basicPay"] == 22890
    assert parsed["recalc"]["persNo"] == "90000227"
    assert parsed["recalc"]["rows"], "re-calculation rows should parse"
    # numeric columns are numbers, date columns are strings
    row = parsed["recalc"]["rows"][0]
    assert isinstance(row["opening"], (int, float))
    assert isinstance(row["start"], str)


def test_identity_gate_rejects_wrong_employee():
    F = load_case("refundable")            # personnel no. 90000227
    wrong = parse_sap_file("x.txt", _read("90000687"))  # residual case, different person
    issues = check_sap_against_case(wrong, F)
    assert issues and "different employee" in issues[0]


def test_manual_upload_connector_rejects_wrong_extract():
    F = load_case("refundable")
    conn = ManualUploadConnector()
    with pytest.raises(ValueError):
        conn.load_extract(F, "wrong.txt", _read("90000687"))


def test_cure_by_upload_resolves_sap_items():
    """Received without SAP -> upload the extract -> SAP checks flip from `sap` to `ok`."""
    F = load_case("refundable", without_sap=True)
    before = {r["id"]: r["status"] for r in evaluate(F)}
    assert before["SAP-PAYSLIP"] == "sap"
    assert before["SAP-RECALC"] == "sap"
    assert before["ADV-LIMIT"] == "sap"   # limit cannot be tested without a balance

    conn = ManualUploadConnector()
    conn.apply_to_case(F, "SAP_EXTRACT_90000227.txt", _read("90000227"))
    after = {r["id"]: r["status"] for r in evaluate(F)}

    assert after["SAP-PAYSLIP"] == "ok"
    assert after["SAP-RECALC"] == "ok"
    assert after["ADV-LIMIT"] == "ok"     # Rs 58,000 within the Rule 1.14(1)(d)(i) limit
    # No SAP-dependent check is left waiting after the extract is supplied.
    assert "sap" not in after.values()
