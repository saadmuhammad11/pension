"""API surface tests via FastAPI TestClient."""
import copy
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gpf import doa as doa_mod
from gpf.api import app

SAMPLES = Path(__file__).resolve().parents[2] / "prototype" / "sap-samples"
client = TestClient(app)


@pytest.fixture(autouse=True)
def _restore_doa():
    snap = copy.deepcopy(doa_mod.DOA)
    yield
    doa_mod.DOA.clear()
    doa_mod.DOA.update(snap)


def test_health_and_meta():
    assert client.get("/api/health").json()["ok"] is True
    assert {o["id"] for o in client.get("/api/officers").json()} == {"da", "ao", "dag"}
    assert len(client.get("/api/case-templates").json()) == 8
    rules = client.get("/api/rules").json()
    assert len(rules["officeClarifications"]) == 15
    assert rules["officeCapPct"] == 80


def test_case_lifecycle_over_http():
    cid = client.post("/api/cases", json={"templateKey": "refundable", "withoutSap": True,
                                          "officer": "ao"}).json()["id"]
    v = client.get(f"/api/cases/{cid}").json()
    assert v["position"]["sap"] == 5

    text = (SAMPLES / "SAP_EXTRACT_90000227.txt").read_text()
    r = client.post(f"/api/cases/{cid}/sap", json={"filename": "e.txt", "text": text, "officer": "ao"})
    assert r.status_code == 200
    assert "SAP-PAYSLIP" in [d["id"] for d in r.json()["diff"]["resolved"]]
    assert r.json()["case"]["position"]["sap"] == 0


def test_wrong_sap_returns_400():
    cid = client.post("/api/cases", json={"templateKey": "refundable", "withoutSap": True}).json()["id"]
    bad = (SAMPLES / "SAP_EXTRACT_90000687.txt").read_text()
    r = client.post(f"/api/cases/{cid}/sap", json={"filename": "bad.txt", "text": bad})
    assert r.status_code == 400 and "different employee" in r.json()["detail"]


def test_cure_multipart_over_http():
    cid = client.post("/api/cases", json={"templateKey": "missing-credits", "officer": "ao"}).json()["id"]
    r = client.post(f"/api/cases/{cid}/cure",
                    data={"resultId": "MC-CHALLANS", "officer": "ao",
                          "values": '{"sr":"4","amount":"7960","bankStamp":"yes"}'},
                    files={"file": ("challan4.jpg", b"bytes", "image/jpeg")})
    assert r.status_code == 200
    assert "MC-CHALLANS" in [d["id"] for d in r.json()["diff"]["resolved"]]


def test_disposal_gate_forbidden_over_http():
    cid = client.post("/api/cases", json={"templateKey": "residual", "officer": "ao"}).json()["id"]
    r = client.post(f"/api/cases/{cid}/dispose", json={"disposal": "pay", "officer": "ao"})
    assert r.status_code == 403


def test_reading_endpoints():
    arts = client.get("/api/reading/artefacts").json()
    assert "SAP_PAYSLIP" in arts["types"] and "SECTION_WORKING" in arts["types"]
    schema = client.get("/api/reading/schema/SANCTION_ORDER").json()
    assert "order_no" in schema["properties"] and "amount" in schema["required"]
    assert client.get("/api/reading/schema/NOPE").status_code == 404


def test_from_scans_without_vision_model_returns_503():
    # default app uses StubModelClient -> reading is not available
    r = client.post("/api/cases/from-scans",
                    data={"kind": "refundable", "gazetted": "non-gazetted", "officer": "ao"},
                    files={"files": ("p1.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert r.status_code == 503 and "vision model" in r.json()["detail"]


def test_frontend_served():
    r = client.get("/")
    assert r.status_code == 200 and "GP Fund" in r.text


def test_scan_reading_job_reports_failure_instead_of_hanging():
    """The UI starts a job and polls it. Without a vision model the job must fail with the
    same clear notice the synchronous endpoint gives -- and must fail, not sit at 'running',
    because a job that never resolves is exactly the dead screen this replaced."""
    start = client.post("/api/cases/from-scans/start",
                        data={"kind": "refundable", "gazetted": "non-gazetted", "officer": "ao"},
                        files={"files": ("p1.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert start.status_code == 202
    job_id = start.json()["jobId"]

    for _ in range(100):
        job = client.get(f"/api/reading/jobs/{job_id}").json()
        if job["state"] != "running":
            break
        time.sleep(0.05)

    assert job["state"] == "error"
    assert job["statusCode"] == 503 and "vision model" in job["detail"]
    assert job["total"] == 1


def test_unknown_reading_job_is_404():
    r = client.get("/api/reading/jobs/job-nope")
    assert r.status_code == 404


def test_a_claim_read_from_scans_serves_its_own_evidence_pages(tmp_path):
    """30 Sep 2026: the screen looked for a scanned claim's pages among the demo cases' assets,
    so every evidence image on a real claim was blank."""
    from gpf import api
    page = api.DATA_DIR / "uploads" / "scan-test" / "p1.jpg"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(b"\xff\xd8\xff jpeg")
    api.save_page_refs("refundable-scan-test", [str(page)])
    r = client.get("/api/cases/refundable-scan-test/pages/1")
    assert r.status_code == 200 and r.content == b"\xff\xd8\xff jpeg"
    assert client.get("/api/cases/refundable-scan-test/pages/2").status_code == 404
    # A path outside the module's data and the portal's case files is never served.
    outside = tmp_path / "secret.jpg"; outside.write_bytes(b"x")
    api.save_page_refs("refundable-scan-evil", [str(outside)])
    assert client.get("/api/cases/refundable-scan-evil/pages/1").status_code == 404


def test_a_claims_specimen_is_shown_on_its_signature_checks():
    """30 Sep 2026: the department's specimen, filed with the claim, sits beside the signature
    the officer compares on 'Signatories and delegation of authority'. The officer decides."""
    from gpf import api
    r = client.post("/api/cases", json={"templateKey": "refundable"})
    cid = r.json()["id"]
    spec = api.DATA_DIR / "uploads" / "spec-test" / "s.jpg"
    spec.parent.mkdir(parents=True, exist_ok=True); spec.write_bytes(b"\xff\xd8\xff spec")
    api.save_specimens(cid, [{"path": str(spec), "label": "S Signature (DIG Commandment)"}])
    view = client.get(f"/api/cases/{cid}").json()
    assert view["specimens"] == [{"n": 1, "label": "S Signature (DIG Commandment)"}]
    doa = [i for k in ("hard", "adv", "conf", "ok") for i in view["lists"][k] if i["id"].startswith("DOA:")]
    assert doa, "the demo case has signatures to check"
    for item in doa:
        shown = [e for e in item["evidence"] if e.get("specimen")]
        assert shown and shown[0]["url"] == f"api/cases/{cid}/specimens/1"
        assert "No specimen signature is on the register yet." not in (item.get("finding") or "")
    assert client.get(f"/api/cases/{cid}/specimens/1").content == b"\xff\xd8\xff spec"
    assert client.get(f"/api/cases/{cid}/specimens/2").status_code == 404
