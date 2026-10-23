"""The SAP extract can be uploaded as a file, and the case is examined again either way.

23 Oct 2026. The extracts page offered a paste box and nothing else, so a section that had
exported the extract from SAP had to open the file, select it and copy it out. The route for
a file has been there since the module was built (/api/cases/{id}/sap-file); the screen simply
never offered it. Both routes end in service.upload_sap, which merges the extract into the
case's SAP facts and runs every check again.

The file route decoded whatever arrived as UTF-8 with errors replaced. A PDF or a scan came
through as a page of replacement characters and was refused as "nothing here reads as a SAP
extract" -- true, and no help: what the officer needed to be told is that a picture of a pay
slip is not what this box takes.

    python3 -m pytest tests/test_sap_file_upload.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gpf import apikey
from gpf.api import app

SAMPLES = Path(__file__).resolve().parents[2] / "prototype" / "sap-samples"
client = TestClient(app, headers={apikey.HEADER: apikey.api_key() or ""})


@pytest.fixture
def case_without_sap() -> str:
    return client.post("/api/cases", json={"templateKey": "refundable", "withoutSap": True,
                                           "officer": "ao"}).json()["id"]


def _post(cid: str, name: str, body: bytes, ctype: str = "text/plain"):
    return client.post(f"/api/cases/{cid}/sap-file", data={"officer": "ao"},
                       files={"file": (name, body, ctype)})


class TestTheFileRouteDoesWhatThePasteRouteDoes:

    def test_an_exported_extract_is_accepted_and_the_case_re_examined(self, case_without_sap) -> None:
        cid = case_without_sap
        before = client.get(f"/api/cases/{cid}").json()
        assert before["position"]["sap"] == 5, "this fixture should start short of its SAP items"
        text = (SAMPLES / "SAP_EXTRACT_90000227.txt").read_bytes()
        r = _post(cid, "SAP_EXTRACT_90000227.txt", text)
        assert r.status_code == 200, r.text
        after = r.json()["case"]
        assert after["sap"]["present"] is True
        assert after["sap"]["payslip"], "the pay slip did not land"
        # Every check ran again on the new facts: the SAP items the case was waiting on are gone
        # and the version moved. That is what "the whole case is run again" means.
        assert after["position"]["sap"] == 0
        assert after["version"] > before["version"]

    def test_the_answer_carries_what_changed(self, case_without_sap) -> None:
        """The screen shows the diff and jumps to the examination; it needs it in the reply."""
        text = (SAMPLES / "SAP_EXTRACT_90000227.txt").read_bytes()
        body = _post(case_without_sap, "extract.txt", text).json()
        assert set(body) == {"diff", "case"}
        assert set(body["diff"]) == {"resolved", "raised", "changed"}
        assert body["diff"]["resolved"], "clearing five SAP items should show as resolved"

    def test_an_extract_for_another_employee_is_refused(self, case_without_sap) -> None:
        text = (SAMPLES / "SAP_EXTRACT_90000216.txt").read_bytes()
        r = _post(case_without_sap, "SAP_EXTRACT_90000216.txt", text)
        assert r.status_code == 400
        assert "different employee" in r.json()["detail"]


class TestAPictureOfAPaySlipIsNotAnExtract:

    @pytest.mark.parametrize("name,body,word", [
        ("payslip.pdf", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj", "a PDF"),
        ("payslip.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "a PNG image"),
        ("payslip.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF", "a JPEG image"),
        ("scan.tif", b"II*\x00\x08\x00\x00\x00", "a TIFF image"),
        ("export.xlsx", b"PK\x03\x04\x14\x00\x06\x00", "a zip or Office file"),
    ])
    def test_it_is_named_for_what_it_is(self, case_without_sap, name, body, word) -> None:
        r = _post(case_without_sap, name, body, "application/octet-stream")
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert word in detail
        assert name in detail
        # And it says where a scanned pay slip DOES belong, which is as a page of the claim.
        assert "page of the claim" in detail

    def test_other_binary_is_refused_without_guessing_what_it_is(self, case_without_sap) -> None:
        r = _post(case_without_sap, "odd.bin", b"\x01\x02\x00\x03rubbish", "application/octet-stream")
        assert r.status_code == 400
        assert "does not look like text" in r.json()["detail"]

    def test_a_refused_file_leaves_the_case_untouched(self, case_without_sap) -> None:
        cid = case_without_sap
        before = client.get(f"/api/cases/{cid}").json()
        _post(cid, "payslip.pdf", b"%PDF-1.7 whatever", "application/pdf")
        after = client.get(f"/api/cases/{cid}").json()
        assert after["version"] == before["version"]
        assert after["sap"]["present"] == before["sap"]["present"]


class TestTextThatIsNotAnExtract:

    def test_a_text_file_with_no_section_in_it_is_refused(self, case_without_sap) -> None:
        r = _post(case_without_sap, "letter.txt", b"Subject: forwarding of the GP Fund case.")
        assert r.status_code == 400
        assert "SAP EXTRACT: PAY SLIP" in r.json()["detail"]
