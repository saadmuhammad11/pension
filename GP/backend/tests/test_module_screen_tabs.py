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


class TestTheOfficerIsNotShownTheMachinesWorking:
    """A rule that computes a limit carries its working as `calc`, and the item view printed
    it as raw JSON under a finding that already said the same thing in words:

        Rs 108,000 is within the limit. Rule 1.14(1)(d)(i) (temporary advance for a plot or
        house) allows the lesser of 80% of the balance and 24 months' pay (Rs 25,450 a
        month): Rs 121,738.

        {"amount": 108000, "balance": 152173, "byPct": 121738, "officePct": 80, ...}

    The same arithmetic twice, once in the office's language and once in the machine's.
    """

    def test_no_result_prints_its_working_as_json(self) -> None:
        item = APP[APP.index("const calc ="):APP.index("function wireExam")]
        assert "JSON.stringify" not in item

    def test_the_finding_is_what_says_the_figures(self) -> None:
        """The words the officer reads are built by the rule, not by the screen, so taking the
        dump away takes nothing with it."""
        rules = (pathlib.Path(__file__).resolve().parent.parent / "gpf" / "rules_family.py").read_text()
        assert '"% of the balance"' in rules or "% of the balance" in rules
        assert "allows " in rules

    def test_the_figures_are_still_on_the_result_for_a_caller_that_wants_them(self) -> None:
        service = (pathlib.Path(__file__).resolve().parent.parent / "gpf" / "service.py").read_text()
        assert '"calc"' in service, "the API keeps the working; only the screen stopped printing it"


class TestTheHeaderSaysEachThingOnce:
    """A case read from scans is labelled by its kind -- "Refundable (from scans)" -- and
    carries no family, subject or department. The header drew "refundable" above a heading
    that already said it, and then a line holding nothing but a separator:

        refundable
        Refundable (from scans)
        ·
        Personnel no. 30000002 · non-gazetted · version 1
    """

    #: "async function renderCase" is a prefix of "async function renderCases", which comes
    #: first in the file -- the signature disambiguates them.
    CASE_FN = "async function renderCase(app, id"
    HEAD = APP[APP.index(CASE_FN):APP.index('<div class="statstrip"')]
    HELPER = APP[APP.index("const dotted ="):APP.index(CASE_FN)]

    def test_a_part_the_heading_already_states_is_not_said_again(self) -> None:
        assert "!label.includes(String(x).toLowerCase())" in self.HEAD

    def test_a_line_with_nothing_in_it_is_not_drawn(self) -> None:
        for line in ("${kindLine ? ", "${whoLine ? "):
            assert line in self.HEAD, line

    def test_the_separator_goes_between_the_parts_there_are(self) -> None:
        assert ".filter(Boolean)" in self.HELPER and ".join(" in self.HELPER

    def test_neither_line_is_built_by_hand_any_more(self) -> None:
        """Both were a template with a literal separator in the middle of it, which is what
        printed a dot with nothing on either side."""
        assert "${esc(c.meta.family || \'\')} · " not in self.HEAD
        assert "${esc(c.meta.subject || \'\')} · " not in self.HEAD

    def test_the_rule_applied_to_the_case_that_showed_it(self) -> None:
        """The same rule in Python, against that case's own meta."""
        def dotted(*parts):
            return " \u00b7 ".join(p for p in ("" if x is None else str(x).strip() for x in parts) if p)

        meta = {"label": "Refundable (from scans)", "kind": "refundable", "family": "",
                "subject": "", "dept": "", "personnelNo": "30000002"}
        label = meta["label"].lower()
        kind_line = dotted(*[x for x in (meta["family"], meta["kind"])
                             if x and x.lower() not in label])
        assert kind_line == "", "nothing above a heading that already says it"
        assert dotted(meta["subject"], meta["dept"]) == "", "and no bare separator under it"

    def test_but_a_family_the_heading_does_not_say_is_still_shown(self) -> None:
        def dotted(*parts):
            return " \u00b7 ".join(p for p in ("" if x is None else str(x).strip() for x in parts) if p)

        meta = {"label": "Refundable advance — Mr A B Sample", "kind": "refundable",
                "family": "advances", "subject": "Mr A B Sample", "dept": "S&GAD"}
        label = meta["label"].lower()
        assert dotted(*[x for x in (meta["family"], meta["kind"])
                        if x and x.lower() not in label]) == "advances"
        assert dotted(meta["subject"], meta["dept"]) == "Mr A B Sample \u00b7 S&GAD"
