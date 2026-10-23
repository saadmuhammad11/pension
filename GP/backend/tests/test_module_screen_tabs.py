"""The GP Fund module's own screen shows the examination, not the case's outcome.

23 Oct 2026. The module had five tabs. Two of them -- Disposal and Issue pack -- are the
portal's work and have been since the decisions of 7 and 9 Oct 2026: "passed for payment" in
the module stopped approving the pension-side case (M1), a RETURN in the module stopped
returning it, and the AG now disposes of a case on the case screen with a remark. The portal
draws the issue pack itself (/api/v2/cases/{id}/gpf-issue-pack). So an officer working inside
the frame met two screens offering to decide a case that is decided elsewhere.

Both ROUTES stay on the module: the portal relays a disposal through them and fetches the
pack from them. What goes is the module's own second way in.

And the strip above the tabs counted SAP items beside hard stops, observations and
verifications. The others are findings an officer answers; a SAP item is the section's own
errand and has its own tab, which says what is missing and takes the extract.

    python3 -m pytest tests/test_module_screen_tabs.py -q
"""
from __future__ import annotations

import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
APP = (WEB / "js" / "app.js").read_text(encoding="utf-8")
API_JS = (WEB / "js" / "api.js").read_text(encoding="utf-8")
PURE = (WEB / "js" / "pure.js").read_text(encoding="utf-8")
API_PY = (pathlib.Path(__file__).resolve().parent.parent / "gpf" / "api.py").read_text(encoding="utf-8")

SUBNAV = APP[APP.index('<div class="subnav"'):APP.index('<div id="tabc">')]


def test_the_screen_has_three_tabs() -> None:
    assert re.findall(r"tabBtn\('(\w+)'", SUBNAV) == ["overview", "sap", "exam"]


def test_neither_removed_tab_can_be_reached() -> None:
    """Not merely hidden: the dispatch no longer knows them, so a stale #/ or a kept
    state.tab lands nowhere rather than on a half-drawn screen."""
    dispatch = APP[APP.index("function renderTab"):APP.index("const stat =")]
    for gone in ("'disposal'", "'issue'"):
        assert gone not in dispatch, gone


def test_their_screens_are_gone_with_them() -> None:
    for gone in ("viewDisposal", "wireDisposal", "renderIssue", "DISPOSAL_LABEL",
                 "disposalConfirmText", "api.dispose", "issuePack"):
        assert gone not in APP, gone


def test_and_what_only_they_used_is_not_left_lying_about() -> None:
    assert "disposalConfirmText" not in PURE
    assert "dispose:" not in API_JS and "issuePack:" not in API_JS


def test_but_the_routes_stay_because_the_portal_uses_them() -> None:
    """The portal relays a disposal to the module and fetches the pack from it. Removing the
    screen must not remove the case system's way in."""
    assert '"/api/cases/{case_id}/dispose"' in API_PY
    assert '"/api/cases/{case_id}/issue-pack"' in API_PY


def test_the_strip_counts_findings_and_not_errands() -> None:
    strip = APP[APP.index('<div class="statstrip"'):APP.index('<div class="subnav"')]
    assert "'SAP items'" not in strip
    for kept in ("Hard stops", "Observations", "Verify", "Satisfied"):
        assert kept in strip, kept


def test_the_sap_tab_still_says_what_is_missing() -> None:
    """The count left the strip; the errand itself did not leave the screen."""
    assert "tabBtn('sap', 'SAP extracts')" in SUBNAV
    assert "No SAP pay slip or re-calculation report is in the case" in APP


class TestTheOverviewReadsLikeAPensionSummary:
    """A pension case opens on a Summary: a short table of what this case IS. The module's
    Overview was the reading record and nothing else -- the machine's account of itself,
    worth keeping and kept, but not what an officer wants on opening a claim."""

    #: The whole Overview section, its helpers included -- sapLine, which says what the office
    #: holds, is drawn by this tab and sits above the function.
    OVERVIEW = APP[APP.index("// ── overview ──"):APP.index("// ── SAP tab")]

    def test_it_opens_on_a_summary(self) -> None:
        assert "<h2>Summary</h2>" in self.OVERVIEW

    def test_it_says_whose_claim_it_is_and_of_what_kind(self) -> None:
        for line in ("Kind of claim", "Subscriber", "Personnel no.", "Department",
                     "Subscriber status", "Pages read", "SAP extracts", "Examination"):
            assert f"'{line}'" in self.OVERVIEW, line

    def test_the_reading_record_is_kept_below_it(self) -> None:
        assert "What the reading stage lifted" in self.OVERVIEW

    def test_a_missing_extract_says_whose_errand_it_is(self) -> None:
        """Rather than a blank line: the same answer the SAP tab gives."""
        assert "the section pulls it from SAP (R1)" in APP

    def test_a_ledger_that_does_not_add_up_says_so_here_too(self) -> None:
        assert "do not add up" in self.OVERVIEW or "doNotReconcile" in self.OVERVIEW
