"""A scanned or PDF SAP pay slip, read and put on the case (23 Oct 2026).

The SAP extracts step took the text SAP exports and nothing else, so a section holding a
printout or a PDF of the pay slip could not give it to the case: the claim sat on an open SAP
item (R1) with the paper in the officer's hand. PC-2026-000070 is that case exactly -- nine
pages, no pay slip among them, and the only route in was a paste box.

The module already reads both artefacts; a pay slip and the re-calculation report are two of
the types its pipeline classifies. What was missing was a door into that reader for a page
arriving on its own, after the claim has been read, to be merged into a case that exists. So
this is the claim reader pointed at one or two pages with everything that is not a SAP extract
discarded -- and the merge functions are the pipeline's own, so a page read here lands in the
same shape a page of the claim would.

    python3 -m pytest tests/test_sap_scan.py -q
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest import mock

import pytest

from gpf.clients import ManualUploadConnector
from gpf.reading.artefacts import Artefact
from gpf.reading.pipeline import PageResult, ReadingResult
from gpf.sap_scan import ScanError, read_sap_pages, read_upload, render_pages
from gpf.service import CaseService, ServiceError
from gpf.store import CaseRepository, DocumentStore

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 24


def field(value, confidence=0.95):
    from gpf.clients.model_client import ExtractedField
    return ExtractedField(value=value, confidence=confidence, page=1)


def payslip_page(page=1):
    return PageResult(page=page, artefact=Artefact.SAP_PAYSLIP.value, classify_confidence=0.96,
                      fields={"pers_no": field("30000001"), "name": field("A B SAMPLE"),
                              "month": field("August 2026"), "gpf_balance": field(883646.0),
                              "basic_pay": field(210000.0)})


def other_page(page=1, artefact=Artefact.CNIC_SMART_FRONT.value):
    return PageResult(page=page, artefact=artefact, classify_confidence=0.9, fields={})


def pipeline_reading(*pages):
    """A pipeline whose read returns these page results; no model is dialled."""
    p = mock.Mock()
    p.run.return_value = ReadingResult(pages=list(pages), facts={}, needs_human=[],
                                       illegible_pages=[])
    return p


@pytest.fixture
def svc(tmp_path):
    return CaseService(CaseRepository(), DocumentStore(tmp_path / "docs"), ManualUploadConnector())


class TestTurningAnUploadIntoPages:

    def test_an_image_passes_through(self, tmp_path) -> None:
        pages = render_pages([("payslip.png", PNG)], tmp_path / "w")
        assert len(pages) == 1 and Path(pages[0]).read_bytes() == PNG

    def test_several_files_keep_the_order_they_were_given(self, tmp_path) -> None:
        pages = render_pages([("a.png", PNG), ("b.jpg", PNG)], tmp_path / "w")
        assert [Path(p).name for p in pages] == ["d01.png", "d02.jpg"]

    @pytest.mark.skipif(not shutil.which("pdftoppm"), reason="poppler is not on this machine")
    def test_a_real_pdf_is_rendered_to_pages(self, tmp_path) -> None:
        """Rendered with poppler at the resolution the claim's own pages use, so a page read
        here is the picture the reader was tuned on (api/gpf_bridge.page_images)."""
        pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
               b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
               b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
               b"trailer<</Root 1 0 R>>\n")
        try:
            pages = render_pages([("slip.pdf", pdf)], tmp_path / "w")
        except ScanError:
            pytest.skip("this stand-in PDF is too minimal for the installed poppler")
        assert pages and all(p.endswith(".jpg") for p in pages)

    def test_something_that_is_not_a_page_is_refused_by_name(self, tmp_path) -> None:
        with pytest.raises(ScanError) as caught:
            render_pages([("extract.docx", b"PK\x03\x04")], tmp_path / "w")
        assert "extract.docx is not a page" in str(caught.value)
        assert "text SAP exports" in str(caught.value)

    def test_nothing_uploaded_is_refused(self, tmp_path) -> None:
        with pytest.raises(ScanError):
            render_pages([], tmp_path / "w")


class TestOnlyWhatSapSpeaksFor:

    def test_a_pay_slip_is_read(self) -> None:
        found = read_sap_pages(pipeline_reading(payslip_page()), ["p1.png"])
        assert found["payslip"]["persNo"] == "30000001"
        assert found["payslip"]["gpfBalance"] == 883646.0
        assert found["recalc"] is None

    def test_a_page_that_is_something_else_is_discarded(self) -> None:
        """The claim's own reading is the claim's. A CNIC handed in here changes nothing --
        and the pages it saw are reported, so the officer is told why."""
        found = read_sap_pages(pipeline_reading(other_page()), ["p1.png"])
        assert found["payslip"] is None and found["recalc"] is None
        assert found["pages"] == [{"page": 1, "artefact": Artefact.CNIC_SMART_FRONT.value}]

    def test_the_pay_slip_is_taken_from_among_other_pages(self) -> None:
        found = read_sap_pages(pipeline_reading(other_page(1), payslip_page(2)), ["a.png", "b.png"])
        assert found["payslip"]["persNo"] == "30000001"

    def test_the_kind_and_gazetted_of_the_case_reach_the_reader(self) -> None:
        p = pipeline_reading(payslip_page())
        read_sap_pages(p, ["p1.png"], kind="final", gazetted="non-gazetted")
        assert p.run.call_args.kwargs["kind"] == "final"
        assert p.run.call_args.kwargs["gazetted"] == "non-gazetted"

    def test_the_rendered_pages_do_not_outlive_the_read(self, tmp_path) -> None:
        seen = {}

        def remember(pages, **kw):
            seen["dir"] = Path(pages[0].image_ref).parent
            assert seen["dir"].exists(), "the page must be on disk while it is being read"
            return ReadingResult(pages=[payslip_page()], facts={}, needs_human=[], illegible_pages=[])

        p = mock.Mock()
        p.run.side_effect = remember
        read_upload(p, [("slip.png", PNG)])
        assert not seen["dir"].exists(), "and gone once it has been"


class TestPuttingItOnTheCase:

    def _case(self, svc):
        cid = svc.create_case("refundable", without_sap=True, officer_id="ao")
        return cid

    def test_the_pay_slip_lands_and_the_case_is_examined_again(self, svc) -> None:
        cid = self._case(svc)
        before = svc.view(cid)
        found = read_sap_pages(pipeline_reading(payslip_page()), ["p1.png"])
        svc.apply_sap_scan(cid, found, "payslip.png", officer_id="ao")
        after = svc.view(cid)
        assert after["sap"]["payslip"]["persNo"] == "30000001"
        assert after["version"] > before["version"], "every check must run again"
        assert any(a["what"] == "SAP scan read" for a in after["audit"])

    def test_a_ledger_already_on_the_case_is_not_thrown_away(self, svc) -> None:
        """The same rule the text upload follows: the part that arrived replaces that part,
        and a part that did not is left alone."""
        cid = self._case(svc)
        s = svc.repo.get(cid)
        s.F["sap"] = {"source": "case", "recalc": {"page": 6, "rows": [{"start": "a", "end": "b"}]}}
        svc.repo.save(cid, s)
        found = read_sap_pages(pipeline_reading(payslip_page()), ["p1.png"])
        svc.apply_sap_scan(cid, found, "payslip.png", officer_id="ao")
        sap = svc.view(cid)["sap"]
        assert sap["recalc"]["rows"] == 1
        assert sap["recalcSource"] == "case" and sap["payslipSource"] == "upload"

    def test_a_scan_that_is_neither_is_refused_and_changes_nothing(self, svc) -> None:
        cid = self._case(svc)
        before = svc.view(cid)
        found = read_sap_pages(pipeline_reading(other_page()), ["p1.png"])
        with pytest.raises(ServiceError) as caught:
            svc.apply_sap_scan(cid, found, "whatever.png", officer_id="ao")
        assert caught.value.status == 400
        assert "Neither a SAP pay slip nor a GPF re-calculation report" in str(caught.value)
        # And it says what the page WAS, so the officer is not left guessing.
        assert "cnic smart front" in str(caught.value)
        after = svc.view(cid)
        assert after["version"] == before["version"]
        assert any(a["what"] == "SAP scan rejected" for a in after["audit"])


class TestARefusalReadsAsOne:

    def test_a_deliberate_refusal_is_not_dressed_as_a_crash(self) -> None:
        """Anything else a runner raises is reported as "TypeName: message", because an
        unexpected failure has to be diagnosable. A refusal is already in the officer's
        words, and the class name in front of it makes it look like a fault."""
        from gpf.reading.jobs import JobRegistry, ReadingRefused
        reg = JobRegistry()

        def runner(_report):
            raise ReadingRefused("Neither a pay slip nor a report could be read on this page.", 400)

        job = reg.start(runner, total=1)
        for _ in range(200):
            if job.state != "running":
                break
            import time
            time.sleep(0.01)
        view = job.view()
        assert view["state"] == "error"
        assert view["detail"] == "Neither a pay slip nor a report could be read on this page."
        assert view["statusCode"] == 400

    def test_an_unexpected_failure_still_names_itself(self) -> None:
        from gpf.reading.jobs import JobRegistry
        reg = JobRegistry()

        def runner(_report):
            raise KeyError("sap")

        job = reg.start(runner, total=1)
        for _ in range(200):
            if job.state != "running":
                break
            import time
            time.sleep(0.01)
        assert job.view()["detail"].startswith("KeyError")
        assert job.view()["statusCode"] == 500
