"""An uploaded SAP extract adds to the case; it does not empty it (23 Oct 2026).

PC-2026-000070 was filed with the SAP pages in the bundle, and the reader lifted a twenty-four
year re-calculation report off page 6 of the claim. No pay slip was in it, which is ordinary --
the section pulls that from SAP (R1) and uploads it. Two faults stood in the way.

``apply_to_case`` assigned the parsed extract over ``F["sap"]`` whole. An upload carrying only
the pay slip -- the usual upload, the section having pulled the one thing the case lacked --
therefore threw the read ledger away. The case went from twenty-four years of figures to none,
and the examination was re-run against the hole.

And ``load_extract`` raised only on the identity gate, which checks a part only if that part
parsed. Text with neither section in it parsed to neither part, so nothing was checked and
nothing was raised: a stray paste -- the wrong clipboard, a covering letter, one stray word --
was ACCEPTED, logged in the audit as "SAP extract accepted", and emptied the case through the
assignment above.

    python3 -m pytest tests/test_sap_upload_merges_and_refuses.py -q
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from gpf.clients import ManualUploadConnector

SAMPLE = Path(__file__).resolve().parents[2] / "prototype" / "sap-samples" / "SAP_EXTRACT_90000216.txt"
PERS = "30000001"


@pytest.fixture
def extract() -> str:
    """A real sample, re-numbered to the case under test so the identity gate passes."""
    return SAMPLE.read_text(encoding="utf-8").replace("90000216", PERS)


@pytest.fixture
def payslip_only(extract) -> str:
    return extract.split("SAP EXTRACT: GPF FINAL")[0]


@pytest.fixture
def recalc_only(extract) -> str:
    return "SAP EXTRACT: GPF FINAL" + extract.split("SAP EXTRACT: GPF FINAL")[1]


@pytest.fixture
def case() -> dict:
    """A claim whose ledger was read off its own pages and which has no pay slip: the shape
    PC-2026-000070 was in when the section went to upload one."""
    rows = [{"start": "01.07.%d" % y, "end": "30.06.%d" % (y + 1), "opening": 0.0, "closing": 1000.0 * (y - 2002),
             "subscription": 1000.0, "interest": 0.0, "adjustments": 0.0, "tempAdvance": 0.0,
             "recTempAdvance": 0.0, "permanentAdvance": 0.0} for y in range(2003, 2027)]
    return {"personnelNo": PERS, "kind": "nonrefundable",
            "sap": {"source": "case", "recalc": {"page": 6, "rows": rows}}}


def _rows(F):
    return (F["sap"].get("recalc") or {}).get("rows") or []


class TestAnUploadAddsToWhatTheCaseHas:

    def test_a_pay_slip_upload_keeps_the_ledger_read_from_the_claim(self, case, payslip_only) -> None:
        """The fault that emptied PC-2026-000070's twenty-four years."""
        ManualUploadConnector().apply_to_case(case, "extract.txt", payslip_only)
        assert case["sap"]["payslip"], "the pay slip did not land"
        assert len(_rows(case)) == 24, "the ledger read off the claim was thrown away"

    def test_a_report_upload_keeps_a_pay_slip_already_on_the_case(self, case, recalc_only) -> None:
        case["sap"]["payslip"] = {"persNo": PERS, "name": "A B SAMPLE", "gpfBalance": 500.0}
        ManualUploadConnector().apply_to_case(case, "extract.txt", recalc_only)
        assert case["sap"]["payslip"]["name"] == "A B SAMPLE"
        assert _rows(case), "the uploaded report did not land"

    def test_a_fresher_report_replaces_the_one_it_is_fresher_than(self, case, extract) -> None:
        """Replacing a part the upload CARRIES is the point of uploading; the bug was
        replacing the parts it does not carry."""
        ManualUploadConnector().apply_to_case(case, "extract.txt", extract)
        assert len(_rows(case)) != 24, "the uploaded report should have replaced the read one"
        assert case["sap"]["payslip"]

    def test_each_half_remembers_where_it_came_from(self, case, payslip_only) -> None:
        """So the screen can say so: they need not have the same origin."""
        ManualUploadConnector().apply_to_case(case, "extract.txt", payslip_only)
        assert case["sap"]["payslipSource"] == "upload"
        assert case["sap"]["recalcSource"] == "case"


class TestWhatIsNotAnExtractIsRefused:

    @pytest.mark.parametrize("text", [
        "hello, this is the wrong thing pasted",
        "   x   ",
        "Subject: forwarding of the GP Fund case of Mr A B Sample for final payment.",
        "Personnel No: 30000001\nGPF Balance: 260522",      # fields with no section heading
    ])
    def test_it_is_refused_rather_than_accepted_as_an_empty_extract(self, case, text) -> None:
        before = copy.deepcopy(case["sap"])
        with pytest.raises(ValueError) as caught:
            ManualUploadConnector().apply_to_case(case, "extract.txt", text)
        assert "not" in str(caught.value).lower()
        assert case["sap"] == before, "a refused upload must leave the case as it was"

    def test_the_refusal_says_what_the_text_has_to_carry(self, case) -> None:
        with pytest.raises(ValueError) as caught:
            ManualUploadConnector().apply_to_case(case, "extract.txt", "wrong clipboard")
        said = str(caught.value)
        assert "SAP EXTRACT: PAY SLIP" in said
        assert "RE-CALCULATION REPORT" in said

    def test_an_extract_for_another_employee_is_still_refused(self, case, extract) -> None:
        """The identity gate that was already there, which this must not have loosened."""
        before = copy.deepcopy(case["sap"])
        with pytest.raises(ValueError) as caught:
            ManualUploadConnector().apply_to_case(case, "extract.txt", extract.replace(PERS, "90000999"))
        assert "different employee" in str(caught.value)
        assert case["sap"] == before


class TestTheScreenIsToldEnoughToBeHonest:
    """What viewSap draws from. A half that is absent must be absent, not blank."""

    def test_a_case_with_no_pay_slip_says_so_rather_than_showing_empty_fields(self, case) -> None:
        from gpf.service import CaseService
        from gpf.store import CaseRepository, DocumentStore
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            svc = CaseService(CaseRepository(), DocumentStore(Path(d)), ManualUploadConnector())
            cid = svc.create_case("refundable", officer_id="ao")
            s = svc.repo.get(cid)
            s.F["sap"] = copy.deepcopy(case["sap"])
            svc.repo.save(cid, s)
            sap = svc.view(cid, officer_id="ao")["sap"]
        assert sap["present"] is True
        assert sap["payslip"] is None, "nothing read means None, which the screen explains"
        assert sap["recalc"]["rows"] == 24
        assert sap["recalcSource"] == "case"

    def test_the_last_period_travels_with_its_closing(self, case) -> None:
        """"Last closing: Rs 0" read as an empty fund on PC-2026-000070, where the final row
        was the year still running and the balance carried into it was Rs 883,646."""
        from gpf.service import CaseService
        from gpf.store import CaseRepository, DocumentStore
        import tempfile
        case["sap"]["recalc"]["rows"].append(
            {"start": "01.07.2026", "end": "30.06.2027", "opening": 883646.0, "closing": 0.0,
             "subscription": 0.0, "interest": 0.0, "adjustments": 0.0, "tempAdvance": 0.0,
             "recTempAdvance": 0.0, "permanentAdvance": 0.0})
        with tempfile.TemporaryDirectory() as d:
            svc = CaseService(CaseRepository(), DocumentStore(Path(d)), ManualUploadConnector())
            cid = svc.create_case("refundable", officer_id="ao")
            s = svc.repo.get(cid)
            s.F["sap"] = copy.deepcopy(case["sap"])
            svc.repo.save(cid, s)
            rc = svc.view(cid, officer_id="ao")["sap"]["recalc"]
        assert (rc["lastStart"], rc["lastEnd"]) == ("01.07.2026", "30.06.2027")
        assert rc["lastOpening"] == 883646.0
        assert rc["lastClosing"] == 0.0
