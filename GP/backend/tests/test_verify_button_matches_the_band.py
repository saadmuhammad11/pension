"""A desk that may not verify is not offered the button (23 Oct 2026).

A Dealing Assistant is level 1 and ``engine.may("verify", ...)`` wants level 2, so every press
of "Record verified" answered 403. The screen offered the button to every desk all the same,
and the officer -- having no way to tell whose decision it was -- kept pressing it. The audit
log of final-scan-9811898b shows the same two items disposed of twelve times in five minutes.

The audit of 13 Oct 2026 settled exactly this for Uphold / Waive / Correct / Refer, which are
sent to the screen as ``dispositionOptions`` and drawn disabled with the reason. The verify
cure was left behind; it now travels as ``verifyOption``.

    python3 -m pytest tests/test_verify_button_matches_the_band.py -q
"""
from __future__ import annotations

import pathlib
import re

import pytest

from gpf.clients import ManualUploadConnector
from gpf.service import CaseService, ServiceError
from gpf.store import CaseRepository, DocumentStore

APP = (pathlib.Path(__file__).resolve().parent.parent / "web" / "js" / "app.js").read_text(encoding="utf-8")


@pytest.fixture
def svc(tmp_path):
    return CaseService(CaseRepository(), DocumentStore(tmp_path / "docs"), ManualUploadConnector())


def _verify_items(view):
    return [r for group in view["lists"].values() for r in group
            if (r.get("cure") or {}).get("kind") == "verify"]


def test_the_accounts_officer_is_offered_the_verification(svc):
    cid = svc.create_case("refundable", officer_id="ao")
    items = _verify_items(svc.view(cid, officer_id="ao"))
    assert items, "this case carries no verify cure -- the fixture has moved"
    for r in items:
        assert r["verifyOption"] == {"allowed": True, "reason": ""}


def test_the_dealing_assistant_is_told_whose_decision_it_is(svc):
    cid = svc.create_case("refundable", officer_id="ao")
    items = _verify_items(svc.view(cid, officer_id="da"))
    assert items
    for r in items:
        assert r["verifyOption"]["allowed"] is False
        assert r["verifyOption"]["reason"] == "Needs the Accounts Officer or above."


def test_the_service_still_refuses_it_whatever_the_screen_draws(svc):
    """The button is a courtesy; the gate is here. A hand-made POST gets the same answer."""
    cid = svc.create_case("refundable", officer_id="ao")
    vid = _verify_items(svc.view(cid, officer_id="ao"))[0]["cure"]["vid"]
    with pytest.raises(ServiceError) as e:
        svc.verify(cid, vid, True, "checked", officer_id="da")
    assert e.value.status == 403
    # And nothing was written: a refused verification is not a recorded one.
    assert not (svc.view(cid, officer_id="ao").get("F") or {}).get("verifications")


def test_the_screen_draws_the_refusal_rather_than_hiding_the_button() -> None:
    block = APP[APP.index("if (cure.kind === 'verify')"):APP.index("if (cure.kind === 'doc')")]
    assert "r.verifyOption" in block
    assert block.count("disabled title=") == 2          # both buttons, never removed
    assert "vo.allowed !== false" in block
    assert "esc(vwhy)" in block                          # and the reason is shown, not only hinted
