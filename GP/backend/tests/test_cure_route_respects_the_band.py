"""The cure route is gated by the action it performs, not by the door it arrives at.

Audit of 13 October 2026, H-14 and H-15. ``cure`` checked ``may("upload", ...)``, which
returns True for every band including the Dealing Assistant (BS-16, level 1). Two of its
branches do not upload anything:

  * ``kind == "verify"`` records the officer's own verification -- the DOA signature check,
    the thumb impression, the death-claim check -- which the dedicated ``verify`` route
    reserves to the Accounts Officer or above.
  * ``kind == "qr"`` marks the sanction's QR code decoded and agreeing, which clears the
    sanction check.

Both also defaulted their result to "it passed": ``values.get("ok", True)`` and
``values.get("agrees", True)``, so a caller that sent nothing at all recorded a pass.

Together that is a Dealing Assistant clearing a hard stop with an empty payload, through a
route the UI does not even use for these kinds -- app.js calls api.verify for a verify item.
The audit recorded "No test covers this path." This is that test.
"""
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


def _a_verify_item(svc, cid):
    """An open item on a real case that is cured by recording a verification."""
    for rows in svc.view(cid)["lists"].values():
        for r in rows:
            if (r.get("cure") or {}).get("kind") == "verify":
                return r
    pytest.skip("this fixture case raised no verification item")


@pytest.fixture
def case_with_verify_item(svc):
    cid = svc.create_case("refundable", without_sap=True, officer_id="ao")
    text = (SAMPLES / "SAP_EXTRACT_90000227.txt").read_text()
    svc.upload_sap(cid, "e.txt", text, officer_id="ao")
    return cid, _a_verify_item(svc, cid)


class TestTheDealingAssistantMayNotVerify:
    def test_not_through_the_cure_route(self, svc, case_with_verify_item):
        cid, item = case_with_verify_item
        with pytest.raises(ServiceError) as e:
            svc.cure(cid, item["id"], {"ok": True, "note": "looks fine"}, officer_id="da")
        assert e.value.status == 403
        assert "Accounts Officer" in str(e.value)

    def test_nor_through_the_route_that_always_checked(self, svc, case_with_verify_item):
        """The dedicated route's guard is the one being matched; it must still hold."""
        cid, item = case_with_verify_item
        with pytest.raises(ServiceError) as e:
            svc.verify(cid, item["cure"]["vid"], True, "looks fine", officer_id="da")
        assert e.value.status == 403

    def test_and_nothing_was_recorded_by_the_refused_attempt(self, svc, case_with_verify_item):
        cid, item = case_with_verify_item
        before = svc.view(cid)["version"]
        with pytest.raises(ServiceError):
            svc.cure(cid, item["id"], {"ok": True}, officer_id="da")
        after = svc.view(cid)
        assert after["version"] == before, "a refused cure must not advance the case"
        assert not any("Cure by upload" in a["what"] for a in after["audit"][-3:])


class TestTheAccountsOfficerStillMay:
    def test_the_cure_route_works_for_the_band_that_may_verify(self, svc, case_with_verify_item):
        cid, item = case_with_verify_item
        svc.cure(cid, item["id"], {"ok": True, "note": "checked against the original"},
                 officer_id="ao")
        assert any("Cure by upload" in a["what"] for a in svc.view(cid)["audit"])


class TestAResultIsStatedNotDefaulted:
    def test_a_verification_with_no_result_is_refused(self, svc, case_with_verify_item):
        """`ok` defaulted to True: an empty payload recorded the check as passed."""
        cid, item = case_with_verify_item
        with pytest.raises(ServiceError) as e:
            svc.cure(cid, item["id"], {}, officer_id="ao")
        assert e.value.status == 400
        assert "explicit" in str(e.value)

    def test_a_negative_result_is_still_accepted(self, svc, case_with_verify_item):
        """Requiring the field must not make "it failed" harder to record than "it passed"."""
        cid, item = case_with_verify_item
        svc.cure(cid, item["id"], {"ok": False, "note": "does not match the original"},
                 officer_id="ao")
        assert any("Cure by upload" in a["what"] for a in svc.view(cid)["audit"])


class TestUploadingIsStillEveryonesToDo:
    def test_the_band_gate_did_not_spread_to_document_cures(self, svc):
        """Only the two branches that verify are gated. A Dealing Assistant still sends the
        document a remedy asks for -- that is the clerk's job, and the point of `cure`."""
        from gpf.engine import may
        da = {"id": "da", "level": 1}
        assert may("upload", None, da) is True
        assert may("verify", None, da) is False


class TestTheQrCureIsAVerificationToo:
    """H-15. The QR cure sets decoded=True and writes a `match`, which clears the sanction
    check -- a verification in substance, reached under the same unguarded may("upload")."""

    @pytest.fixture
    def case_with_qr_item(self, svc):
        cid = svc.create_case("residual", officer_id="ao")
        for rows in svc.view(cid)["lists"].values():
            for r in rows:
                if (r.get("cure") or {}).get("kind") == "qr":
                    return cid, r
        pytest.skip("this fixture case raised no QR item")

    def test_a_dealing_assistant_may_not_send_one(self, svc, case_with_qr_item):
        cid, item = case_with_qr_item
        with pytest.raises(ServiceError) as e:
            svc.cure(cid, item["id"], {"payload": "x", "agrees": True}, officer_id="da")
        assert e.value.status == 403

    def test_it_will_not_assume_the_code_agrees(self, svc, case_with_qr_item):
        """`agrees` defaulted to True, so a payload saying nothing produced a match."""
        cid, item = case_with_qr_item
        with pytest.raises(ServiceError) as e:
            svc.cure(cid, item["id"], {"payload": "x"}, officer_id="ao")
        assert e.value.status == 400
        assert "explicit" in str(e.value)

    def test_the_accounts_officer_may_record_either_answer(self, svc, case_with_qr_item):
        cid, item = case_with_qr_item
        svc.cure(cid, item["id"], {"payload": "x", "agrees": False}, officer_id="ao")
        assert any("Cure by upload" in a["what"] for a in svc.view(cid)["audit"])


class TestACheckThatCannotDecideDoesNotDisappear:
    """H-16. `except Exception: applies = False` meant a check that threw while deciding
    whether it applied vanished from the case, with nothing logged and nothing shown -- so a
    case that had lost a hard stop read clean."""

    def test_it_becomes_a_confirmation_naming_itself(self):
        from gpf import engine
        from gpf.registry import Check

        def explodes(F):
            raise KeyError("sap")                      # what a malformed fact object does

        broken = Check(id="BOOM", run=lambda F: {"status": "hard", "finding": "a hard stop"},
                       applies=explodes, title="A check that cannot tell if it applies")
        original = list(engine.CHECKS)
        engine.CHECKS.append(broken)
        try:
            out = engine.evaluate({})
        finally:
            engine.CHECKS[:] = original

        mine = [r for r in out if r["id"] == "BOOM"]
        assert mine, "the check vanished from the case"
        assert mine[0]["status"] == "conf", "it must reach a human, not pass silently"
        assert "could not decide whether it applies" in mine[0]["finding"]
        assert "sap" in mine[0]["finding"], "the error has to say what went wrong"

    def test_a_check_that_simply_does_not_apply_is_still_dropped(self):
        """The fix must not turn every inapplicable check into noise on every case."""
        from gpf import engine
        from gpf.registry import Check

        quiet = Check(id="QUIET", run=lambda F: {"status": "hard", "finding": "x"},
                      applies=lambda F: False, title="Not for this case")
        original = list(engine.CHECKS)
        engine.CHECKS.append(quiet)
        try:
            out = engine.evaluate({})
        finally:
            engine.CHECKS[:] = original
        assert not [r for r in out if r["id"] == "QUIET"]
