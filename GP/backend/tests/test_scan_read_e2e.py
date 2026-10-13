"""A GP Fund claim read from scans, end to end through the HTTP API (audit 6 Oct 2026, item 4).

Upload -> stored pages -> reading pipeline (stages 1-5) -> facts -> rules -> an open case, on
both the synchronous route and the job route the portal uses. The model is scripted (the same
canned refundable-advance reading as test_reading.py), so this runs with no Spark.

Until 6 Oct 2026 every such read ended in NameError: _read_scans passed `request` to _acting(),
and `request` is not in its scope -- the callers had already resolved the officer. The stub
model raised earlier than that line, so no test reached it.
"""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gpf import api
from gpf import apikey
from gpf.clients import ScriptedModelClient
from gpf.reading import ReadingPipeline, ScriptedBarcodeDecoder
from gpf.reading.barcodes import DecodedCode
from test_reading import _scripted_refundable

client = TestClient(api.app, headers={apikey.HEADER: apikey.api_key() or ''})
PAGES = [f"p{i}" for i in range(1, 7)]


class _ByUploadName(ScriptedModelClient):
    """The scripted reading keyed by the name each page was uploaded under (p1.jpg -> "p1").

    A stored upload is ``<hash>_<original name>``, so the page is found from its stored path.
    """
    @staticmethod
    def _key(image_ref: str) -> str:
        return Path(image_ref).name.rsplit("_", 1)[-1].split(".")[0]

    def classify_document(self, image_ref):
        return super().classify_document(self._key(image_ref))

    def extract_fields(self, image_ref, artefact_type):
        return super().extract_fields(self._key(image_ref), artefact_type)


@pytest.fixture
def scripted_model(monkeypatch):
    classifications, extractions = _scripted_refundable()
    barcodes = ScriptedBarcodeDecoder({3: [DecodedCode("QR code", "10826129086900001000010131", 3)]})
    monkeypatch.setattr(api, "reading_pipeline",
                        ReadingPipeline(_ByUploadName(classifications, extractions), barcodes))


def _files():
    # Distinct bytes per page: the store names files by content hash.
    return [("files", (f"{p}.jpg", b"\xff\xd8\xff" + p.encode(), "image/jpeg")) for p in PAGES]


def _assert_opened(body, officer):
    case = body["case"]
    assert body["pagesTotal"] == 6
    assert case["officer"]["id"] == officer
    # The case is assembled from the reading: the sanction, the card and the SAP pay slip.
    assert case["meta"]["personnelNo"] == "90000227"
    # Its pages are kept, in reading order, for the evidence panes.
    refs = api.page_refs(body["id"])
    assert [Path(r).name.rsplit("_", 1)[-1] for r in refs] == [f"{p}.jpg" for p in PAGES]


def test_synchronous_scan_read_opens_a_case(scripted_model):
    r = client.post("/api/cases/from-scans",
                    data={"kind": "refundable", "gazetted": "non-gazetted", "officer": "ao"},
                    files=_files())
    assert r.status_code == 200, r.text
    _assert_opened(r.json(), "ao")


def test_job_scan_read_opens_a_case_as_the_portal_officer(scripted_model):
    # The portal's proxy fixes the officer by header; the body's claim must lose to it.
    start = client.post("/api/cases/from-scans/start",
                        data={"kind": "refundable", "gazetted": "non-gazetted", "officer": "ao"},
                        files=_files(), headers={api.ACTING_OFFICER_HEADER: "dag"})
    assert start.status_code == 202, start.text
    job_id = start.json()["jobId"]
    for _ in range(200):
        job = client.get(f"/api/reading/jobs/{job_id}").json()
        if job["state"] in ("done", "failed", "error"):
            break
        time.sleep(0.05)
    assert job["state"] == "done", job
    _assert_opened(job["result"], "dag")
