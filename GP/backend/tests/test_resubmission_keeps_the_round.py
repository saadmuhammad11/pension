"""A resubmission is a second round of one examination, not a second examination.

Audit of 13 October 2026, H-19. Every GP Fund submission opened a brand-new module case and
the portal's pointer was overwritten to it. Every disposition, ground, authority and
verification the officer had recorded went with the old case -- which stayed in the database
holding the claimant's facts, unreachable and unauditable through the portal. The sweep behind
that audit found 17 such orphans among 61 cases.

The pension side has carried decisions across rounds since it was written (api.rounds
carry_decisions). The GP Fund path had no carry at all.

What carries is decided by what can be RECONCILED, and the module already had the machinery:
run_case -> reconcile_dispositions keeps a disposition whose observation has gone and marks it
cured, and marks one whose observation now says something else stale, so it counts as open
again until an officer looks at what it says now.

Verifications do not carry. There is no fingerprint to reconcile one against, it is a
statement about a page in a particular submission, and the department has just sent new pages
-- carrying one would let a statement about a replaced document go on satisfying a check.

    pytest tests/test_resubmission_keeps_the_round.py
"""
import copy

import pytest

from gpf import doa as doa_mod
from gpf.clients import ManualUploadConnector
from gpf.service import CaseService, ServiceError
from gpf.store import CaseRepository, DocumentStore


@pytest.fixture
def svc(tmp_path):
    return CaseService(CaseRepository(), DocumentStore(tmp_path / "docs"), ManualUploadConnector())


@pytest.fixture(autouse=True)
def _restore_doa():
    snap = copy.deepcopy(doa_mod.DOA)
    yield
    doa_mod.DOA.clear()
    doa_mod.DOA.update(snap)


def _facts(svc, key="refundable"):
    """A facts object of the shape the reading pipeline produces."""
    from gpf.fixtures import load_case
    return copy.deepcopy(load_case(key))


class TestTheSecondRoundIsTheSameCase:
    def test_re_reading_keeps_the_case_id(self, svc):
        first = svc.create_case_from_facts(_facts(svc), meta={"label": "Refundable (from scans)"})
        again = svc.create_case_from_facts(_facts(svc), meta={"label": "Refundable (from scans)"},
                                           into=first)
        assert again == first, "a resubmission opened a second case and orphaned the first"

    def test_without_into_it_still_opens_a_new_one(self, svc):
        """A first submission has no module case to re-read into."""
        a = svc.create_case_from_facts(_facts(svc), meta={"label": "x"})
        b = svc.create_case_from_facts(_facts(svc), meta={"label": "x"})
        assert a != b

    def test_re_reading_into_a_case_that_is_not_there_is_refused(self, svc):
        with pytest.raises(ServiceError) as e:
            svc.create_case_from_facts(_facts(svc), meta={"label": "x"}, into="no-such-case")
        assert e.value.status == 404

    def test_the_round_is_on_the_record(self, svc):
        cid = svc.create_case_from_facts(_facts(svc), meta={"label": "x"})
        svc.create_case_from_facts(_facts(svc), meta={"label": "x"}, into=cid)
        assert any("Re-read from scans" in a["what"] for a in svc.view(cid)["audit"])


class TestTheOfficersDecisionsSurvive:
    def _an_observation(self, svc, cid):
        """A hard stop or an advisory: the two statuses a disposition may be recorded against."""
        lists = svc.view(cid)["lists"]
        for bucket in ("hard", "adv"):
            for r in lists.get(bucket) or []:
                return r
        pytest.skip("this fixture raised no observation to dispose of")

    def test_a_disposition_is_not_thrown_away(self, svc):
        cid = svc.create_case_from_facts(_facts(svc), meta={"label": "x"})
        obs = self._an_observation(svc, cid)
        svc.set_disposition(cid, obs["id"], "waive", ground="checked against the original order",
                            authority="Rule 1.14(1)", officer_id="dag")
        before = len(svc.view(cid)["dispositions"])
        assert before >= 1

        svc.create_case_from_facts(_facts(svc), meta={"label": "x"}, into=cid)
        after = svc.view(cid)["dispositions"]
        assert len(after) == before, "the officer's disposition was abandoned by the resubmission"
        assert any(d.get("ground") for d in after.values()), "the written ground went with it"

    def test_a_verification_is_asked_for_again(self, svc):
        """It cannot be reconciled, and the department has just sent new pages."""
        cid = svc.create_case_from_facts(_facts(svc), meta={"label": "x"})
        s = svc.repo.get(cid)
        s.F.setdefault("verifications", {})["SOME-VID"] = {
            "ok": True, "by": "Sadia Rehman", "desig": "Accounts Officer", "at": "20-10-2026", "note": "checked"}
        svc.repo.save(cid, s)
        assert "SOME-VID" in svc.repo.get(cid).F["verifications"]

        svc.create_case_from_facts(_facts(svc), meta={"label": "x"}, into=cid)
        assert not (svc.repo.get(cid).F.get("verifications") or {}), \
            "a verification of a page the department may have replaced was carried forward"


class TestNothingIsOrphaned:
    def test_one_module_case_however_many_rounds(self, svc):
        cid = svc.create_case_from_facts(_facts(svc), meta={"label": "x"})
        for _ in range(3):
            svc.create_case_from_facts(_facts(svc), meta={"label": "x"}, into=cid)
        assert svc.repo.list_ids() == [cid], \
            f"rounds left orphaned cases behind: {svc.repo.list_ids()}"
