"""Application-service lifecycle: SAP cure, verify, dispositions, disposal gates."""
import copy
from pathlib import Path

import pytest

from gpf import doa as doa_mod
from gpf.clients import ManualUploadConnector
from gpf.service import CaseService, ServiceError
from gpf.store import CaseRepository, DocumentStore

SAMPLES = Path(__file__).resolve().parents[2] / "prototype" / "sap-samples"


@pytest.fixture
def svc(tmp_path):
    return CaseService(CaseRepository(), DocumentStore(tmp_path / "docs"), ManualUploadConnector())


@pytest.fixture(autouse=True)
def _restore_doa():
    snap = copy.deepcopy(doa_mod.DOA)
    yield
    doa_mod.DOA.clear()
    doa_mod.DOA.update(snap)


def test_intake_runs_initial_processing(svc):
    cid = svc.create_case("refundable", officer_id="ao")
    v = svc.view(cid)
    assert v["version"] == 1
    assert v["position"]["hard"] == 0
    assert any(a["what"] == "Case opened" for a in v["audit"])


def test_sap_cure_then_verify_then_pay(svc):
    cid = svc.create_case("refundable", without_sap=True, officer_id="ao")
    assert svc.view(cid)["position"]["sap"] == 5
    text = (SAMPLES / "SAP_EXTRACT_90000227.txt").read_text()
    svc.upload_sap(cid, "e.txt", text, officer_id="ao")
    v = svc.view(cid)
    assert v["position"]["sap"] == 0
    for r in v["lists"]["conf"]:
        svc.verify(cid, r["cure"]["vid"], True, "checked", officer_id="ao")
    for r in svc.view(cid)["lists"]["adv"]:
        svc.set_disposition(cid, r["id"], "waive", ground="R5", authority="AO", officer_id="ao")
    v = svc.view(cid)
    assert v["position"]["conf"] == 0 and v["position"]["open"] == 0
    pay = next(o for o in v["disposalOptions"] if o["action"] == "pay")
    assert pay["allowed"], pay["reason"]
    res = svc.dispose(cid, "pay", officer_id="ao")
    assert res["issued"] and "payment" in res["caseDisp"]


def test_wrong_sap_rejected_and_logged(svc):
    cid = svc.create_case("refundable", without_sap=True, officer_id="ao")
    text = (SAMPLES / "SAP_EXTRACT_90000687.txt").read_text()  # different person
    with pytest.raises(ServiceError):
        svc.upload_sap(cid, "bad.txt", text, officer_id="ao")
    assert any(a["what"] == "SAP extract rejected" for a in svc.view(cid)["audit"])


def test_dealing_assistant_cannot_waive_hard_stop(svc):
    cid = svc.create_case("residual", officer_id="da")
    hard = svc.view(cid)["lists"]["hard"][0]
    with pytest.raises(ServiceError) as e:
        svc.set_disposition(cid, hard["id"], "waive", ground="g", authority="a", officer_id="da")
    assert e.value.status == 403


def test_pay_blocked_while_hard_open(svc):
    cid = svc.create_case("residual", officer_id="ao")  # residual has a hard stop
    v = svc.view(cid)
    pay = next(o for o in v["disposalOptions"] if o["action"] == "pay")
    assert not pay["allowed"]
    with pytest.raises(ServiceError):
        svc.dispose(cid, "pay", officer_id="ao")


def test_cure_by_upload_doc_resolves_hard_stop(svc):
    """Missing-credits: uploading the missing challan Sr.4 clears the MC-CHALLANS hard stop."""
    cid = svc.create_case("missing-credits", officer_id="ao")
    v = svc.view(cid)
    hard = next(r for r in v["lists"]["hard"] if r["id"] == "MC-CHALLANS")
    values = {"sr": "4", "amount": "7960", "bankStamp": "yes"}
    diff = svc.cure(cid, "MC-CHALLANS", values, filename="challan4.jpg",
                    content=b"fake-image-bytes", officer_id="ao")
    ids = [d["id"] for d in diff["resolved"]]
    assert "MC-CHALLANS" in ids
    assert not any(r["id"] == "MC-CHALLANS" for r in svc.view(cid)["lists"]["hard"])


def test_create_case_from_scanned_facts(svc):
    """A case opened from the reading pipeline's facts is fully usable (view, issue pack)."""
    from gpf.clients import ExtractedField, ScriptedModelClient
    from gpf.reading import Artefact, Page, ReadingPipeline, field_map

    def ef(art, name, value, conf):
        return ExtractedField(value, conf, field_class=field_map(Artefact(art))[name].field_class)

    cls = {"p1": ExtractedField(Artefact.SANCTION_ORDER.value, 0.98, field_class="structural"),
           "p2": ExtractedField(Artefact.CNIC_SMART_FRONT.value, 0.98, field_class="structural")}
    ext = {"p1": {"order_no": ef(Artefact.SANCTION_ORDER.value, "order_no", "1/GPF", 0.98),
                  "date": ef(Artefact.SANCTION_ORDER.value, "date", "01-01-2026", 0.98),
                  "amount": ef(Artefact.SANCTION_ORDER.value, "amount", 50000, 0.98),
                  "rule": ef(Artefact.SANCTION_ORDER.value, "rule", "Rule 1.14(1)(d)(i)", 0.9),
                  "reason": ef(Artefact.SANCTION_ORDER.value, "reason", "house", 0.9),
                  "limit_clause": ef(Artefact.SANCTION_ORDER.value, "limit_clause", "1.14(1)(d)(i)", 0.9)},
           "p2": {"number": ef(Artefact.CNIC_SMART_FRONT.value, "number", "35201-1111111-1", 0.98),
                  "name": ef(Artefact.CNIC_SMART_FRONT.value, "name", "Test Person", 0.9)}}
    pipeline = ReadingPipeline(ScriptedModelClient(cls, ext))
    result = pipeline.run([Page(1, "p1"), Page(2, "p2")], kind="refundable", gazetted="non-gazetted")

    cid = svc.create_case_from_facts(result.facts, meta={"label": "Refundable (from scans)"}, officer_id="ao")
    v = svc.view(cid)
    assert v["meta"]["label"] == "Refundable (from scans)"
    assert v["meta"]["kind"] == "refundable"
    # sanction present -> ADV-SANCTION satisfied; no SAP -> limit waits
    ids = {r["id"]: r["status"] for grp in v["lists"].values() for r in grp}
    assert ids["ADV-SANCTION"] == "ok"
    assert ids["SAP-PAYSLIP"] == "sap"
    pack = svc.issue_pack(cid)
    assert pack["case"]["label"] == "Refundable (from scans)"


def test_second_return_needs_dag(svc):
    cid = svc.create_case("residual", officer_id="ao")
    svc.dispose(cid, "return", officer_id="ao")           # first return ok
    v = svc.view(cid)
    ret = next(o for o in v["disposalOptions"] if o["action"] == "return")
    assert not ret["allowed"] and "second return" in ret["reason"].lower()
    # DAG may do the second return
    svc.dispose(cid, "return", officer_id="dag")
    assert svc.view(cid)["returns"] == 2
