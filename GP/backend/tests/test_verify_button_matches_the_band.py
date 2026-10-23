"""Who may record a verification, and what the screen offers them (23 Oct 2026).

Two office decisions, a day apart in the reading of them.

The module wanted level 2 to verify, so a Senior Auditor -- who arrives here in the ``da``
band (api/gpf_bridge.OFFICER_FOR_ROLE) -- was answered 403 on every press of "Record
verified". That contradicted the tier design the portal has carried since 9 Oct 2026, which
reads "the Senior Auditor verifies and talks to the department; the Accounts Officer decides"
(api/v2.capabilities, C3). Verifying now sits with waive, correct and upload: every examining
tier records one, under their own name, with their note, and the rule reads it back.

Separately, the screen offered the button to every desk whatever the service would say, so a
refusal arrived only as a 403. The audit log of final-scan-9811898b shows the same two items
disposed of twelve times in five minutes -- an officer pressing a button that did nothing.
``verifyOption`` now travels with each result, the way ``dispositionOptions`` has since the
audit of 13 Oct 2026, and the screen draws the refusal rather than hiding the button. That
machinery is what keeps a future restriction honest, so it is tested against ``engine.may``
itself rather than against today's answer.

    python3 -m pytest tests/test_verify_button_matches_the_band.py -q
"""
from __future__ import annotations

import pathlib

import pytest

from gpf.clients import ManualUploadConnector
from gpf.engine import OFFICERS, may, who_can
from gpf.service import CaseService, _officer
from gpf.store import CaseRepository, DocumentStore

APP = (pathlib.Path(__file__).resolve().parent.parent / "web" / "js" / "app.js").read_text(encoding="utf-8")

#: Every band the module knows: Dealing Assistant, Accounts Officer, Deputy AG (Funds).
BANDS = [o["id"] for o in OFFICERS]


@pytest.fixture
def svc(tmp_path):
    return CaseService(CaseRepository(), DocumentStore(tmp_path / "docs"), ManualUploadConnector())


def _verify_items(view):
    return [r for group in view["lists"].values() for r in group
            if (r.get("cure") or {}).get("kind") == "verify"]


def test_every_examining_tier_may_verify() -> None:
    """The decision of 23 Oct 2026. The Senior Auditor is the ``da`` band and was the desk
    being refused; a verification is the Senior Auditor's own work."""
    assert BANDS == ["da", "ao", "dag"]
    for band in BANDS:
        assert may("verify", None, _officer(band)) is True, band


@pytest.mark.parametrize("band", BANDS)
def test_the_screen_offers_the_verification_to_that_desk(svc, band) -> None:
    cid = svc.create_case("refundable", officer_id="ao")
    items = _verify_items(svc.view(cid, officer_id=band))
    assert items, "this case carries no verify cure -- the fixture has moved"
    for r in items:
        assert r["verifyOption"] == {"allowed": True, "reason": ""}


@pytest.mark.parametrize("band", BANDS)
def test_what_the_screen_is_told_is_what_the_service_enforces(svc, band) -> None:
    """The option is not a second opinion: it is engine.may, asked ahead of the press. Written
    this way the pair stays in step if verifying is ever restricted again."""
    cid = svc.create_case("refundable", officer_id="ao")
    for r in _verify_items(svc.view(cid, officer_id=band)):
        assert r["verifyOption"]["allowed"] == may("verify", None, _officer(band))


def test_the_dealing_assistant_s_verification_is_recorded_and_sticks(svc) -> None:
    """What the officer was trying to do on 23 Oct 2026, now from the band she was in."""
    cid = svc.create_case("refundable", officer_id="ao")
    r = _verify_items(svc.view(cid, officer_id="da"))[0]
    svc.verify(cid, r["cure"]["vid"], True, "seen against the register", officer_id="da")
    view = svc.view(cid, officer_id="da")
    after = next((x for group in view["lists"].values() for x in group if x["id"] == r["id"]), None)
    assert after is not None
    # The rule read it back: the observation is answered and carries who recorded it.
    assert after["status"] == "ok"
    assert "seen against the register" in after["finding"]
    assert _officer("da")["name"] in after["finding"]
    assert any(a["what"] == "Verification recorded" for a in view["audit"])


def test_the_wording_for_a_refusal_no_longer_names_one_desk() -> None:
    """who_can is what the screen would print if verifying were restricted again."""
    assert who_can("verify", None) == "any examining officer, who signs the verification with their note"


def test_the_screen_draws_a_refusal_rather_than_hiding_the_button() -> None:
    block = APP[APP.index("if (cure.kind === 'verify')"):APP.index("if (cure.kind === 'doc')")]
    assert "r.verifyOption" in block
    assert block.count("disabled title=") == 2          # both buttons, never removed
    assert "vo.allowed !== false" in block
    assert "esc(vwhy)" in block                          # and the reason is shown, not only hinted
