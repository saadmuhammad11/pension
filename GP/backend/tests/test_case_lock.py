"""Mutations of one GP Fund case are serialised; different cases are not (audit 6 Oct 2026, G7).

The API serves requests on a thread pool and every mutation is read-modify-write on one
CaseState. Two officers acting on one case at once interleaved. The service now holds one
re-entrant lock per case for the whole of each mutating method.
"""
import threading
import time

from gpf.clients import ManualUploadConnector
from gpf.service import CaseService
from gpf.store import CaseRepository, DocumentStore


def _service(tmp_path) -> CaseService:
    return CaseService(CaseRepository(), DocumentStore(tmp_path / "docs"), ManualUploadConnector())


def test_a_mutation_waits_for_the_case_s_lock(tmp_path):
    svc = _service(tmp_path)
    cid = svc.create_case("refundable", without_sap=True, officer_id="ao")
    other = svc.create_case("refundable", without_sap=True, officer_id="ao")
    held = threading.Event()
    release = threading.Event()
    timeline: dict[str, float] = {}

    def holder():
        with svc._lock_for(cid):
            held.set()
            release.wait(5)
        timeline["released"] = time.monotonic()

    def actor(case_id: str, key: str):
        try:
            svc.upload_sap(case_id, "e.txt", "SAP EXTRACT: PAY SLIP\nPersonnel No: 1\n", officer_id="ao")
        except Exception:                                   # noqa: BLE001 -- the text is junk; only the timing matters
            pass
        timeline[key] = time.monotonic()

    threading.Thread(target=holder).start()
    assert held.wait(2)
    same = threading.Thread(target=actor, args=(cid, "same_case_done"))
    different = threading.Thread(target=actor, args=(other, "other_case_done"))
    same.start(); different.start()
    different.join(2)
    assert "other_case_done" in timeline                     # another case is not held up
    assert "same_case_done" not in timeline                  # this case waits for the lock
    time.sleep(0.2)
    release.set()
    same.join(5)
    assert timeline["same_case_done"] >= timeline["released"]


def test_the_lock_is_reentrant_and_per_case(tmp_path):
    svc = _service(tmp_path)
    cid = svc.create_case("refundable", without_sap=True, officer_id="ao")
    with svc._lock_for(cid):
        with svc._lock_for(cid):                              # the same thread may re-enter
            pass
    assert svc._lock_for(cid) is svc._lock_for(cid)
    assert svc._lock_for(cid) is not svc._lock_for("someone-else")


def test_every_mutating_method_is_wrapped():
    for name in ("upload_sap", "refresh_payslip_balances", "cure", "verify", "set_disposition", "dispose"):
        method = getattr(CaseService, name)
        assert getattr(method, "__wrapped__", None) is not None, name
