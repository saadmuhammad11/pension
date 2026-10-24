"""The papers a claim is checked for, and what the examination made of each.

23 Oct 2026. The module showed its findings grouped by severity and never showed a checklist,
so there was nowhere to see that a paper had simply NOT BEEN FOUND: the officer read a list
of what was wrong and had to infer what was missing from the gaps in it. A pension case has
had this since its checklist was built.

The expected papers are gpf.intake's, read off the checks themselves, so the list an officer
sees here and the list the department is shown when it files are the same list.

    python3 -m pytest tests/test_case_checklist_view.py -q
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from gpf.clients import ManualUploadConnector
from gpf.intake import checklist_for
from gpf.service import CaseService
from gpf.store import CaseRepository, DocumentStore


@pytest.fixture
def svc():
    with tempfile.TemporaryDirectory() as d:
        yield CaseService(CaseRepository(), DocumentStore(Path(d)), ManualUploadConnector())


def _checklist(svc, template, **kw):
    return svc.view(svc.create_case(template, officer_id="ao", **kw))["checklist"]


class TestItIsTheSameListTheDepartmentWasShown:

    def test_it_is_the_papers_intake_names_for_the_kind(self, svc) -> None:
        got = _checklist(svc, "refundable")
        want = checklist_for("refundable", "unknown")
        assert [r["item"] for r in got] == [r["item"] for r in want]
        assert [r["requirement"] for r in got] == [r["requirement"] for r in want]

    def test_the_subscriber_narrows_it_here_too(self, svc) -> None:
        """A non-gazetted final payment wants the service book (A2-vii), and a case whose
        facts say gazetted is not asked for it."""
        items = {r["item"] for r in _checklist(svc, "fp-non-gazetted")}
        assert "A2-vii" in items

    def test_it_reads_in_the_circulars_order(self, svc) -> None:
        got = [r["item"] for r in _checklist(svc, "fp-death")]
        assert got == sorted(got, key=lambda i: ["i", "ii", "iii", "iv", "v", "vi", "vii"]
                             .index(i.split("-")[1]))


class TestWhatEachPaperIsSaidToBe:

    def test_a_satisfied_check_reads_present(self, svc) -> None:
        rows = _checklist(svc, "refundable")
        assert {r["word"] for r in rows} == {"Present"}

    def test_a_paper_the_examination_stopped_on_is_not_called_not_found(self, svc) -> None:
        """A hard stop on a checklist item is usually a paper that is absent and sometimes
        one that is present and wrong. Saying "not found" of a paper that is in the bundle is
        the error the office most wants to avoid, so the word is "Not satisfied" and the
        finding beneath it says which."""
        rows = [r for r in _checklist(svc, "fp-death") if r["status"] == "hard"]
        assert rows, "this fixture should stop on something"
        for r in rows:
            assert r["word"] == "Not satisfied"
            assert "not found" not in r["word"].lower()

    def test_and_the_finding_is_carried_so_it_can_say_which(self, svc) -> None:
        rows = [r for r in _checklist(svc, "fp-death") if r["status"] == "hard"]
        assert all(r["findings"] for r in rows)

    def test_the_sap_extracts_are_not_on_the_departments_checklist(self, svc) -> None:
        """They are the section's errand, not a paper the department failed to send -- the
        same reason they came off the strip of counts. A claim filed without them shows no
        new row here; the SAP tab says what is missing and takes it."""
        with_sap = _checklist(svc, "fp-death")
        without = _checklist(svc, "fp-death", without_sap=True)
        assert [r["item"] for r in without] == [r["item"] for r in with_sap]
        assert not any("SAP" in r["item"] for r in without)

    def test_a_paper_wanted_only_sometimes_is_marked(self, svc) -> None:
        """The widow's affidavit on a death claim. It is listed -- the officer should know it
        exists -- but it is not counted against the case when no widow claims."""
        rows = {r["requirement"]: r for r in _checklist(svc, "fp-death")}
        affidavit = rows["Original affidavit for lawful widow"]
        assert affidavit["always"] is False

    def test_an_item_whose_check_never_ran_is_not_read_as_satisfied(self, svc) -> None:
        """The quietest way for a checklist to lie: a rule that did not run leaving a blank
        that reads as a tick."""
        from gpf import service as service_mod
        assert service_mod.CaseService._CHECKLIST_WORD.get("ok") == "Present"
        rows = _checklist(svc, "fp-death")
        for r in rows:
            assert r["word"] != ""
            if not r["findings"]:
                assert r["word"] in ("Not required for this claim", "Not reached", "Present")


class TestTheWorstResultIsTheOnesThatCounts:

    def test_a_check_with_several_results_takes_the_worst(self, svc) -> None:
        """CNIC attestation runs once per CNIC. One bad copy must not be hidden by three
        good ones."""
        order = list(CaseService._CHECKLIST_WORD)
        assert order.index("hard") < order.index("conf") < order.index("ok")


class TestTheScreenDrawsIt:

    APP = (Path(__file__).resolve().parent.parent / "web" / "js" / "app.js").read_text(encoding="utf-8")

    def test_there_is_a_checklist_tab(self) -> None:
        subnav = self.APP[self.APP.index('<div class="subnav"'):self.APP.index('<div id="tabc">')]
        assert "tabBtn('checklist', 'Checklist')" in subnav

    def test_it_is_drawn_from_the_service_and_not_recomputed(self) -> None:
        panel = self.APP[self.APP.index("function viewChecklist"):self.APP.index("// ── SAP tab")]
        assert "c.checklist" in panel
        assert "intake" not in panel.lower(), "the expected papers are the service's to decide"

    def test_it_says_how_many_are_satisfied(self) -> None:
        panel = self.APP[self.APP.index("function viewChecklist"):self.APP.index("// ── SAP tab")]
        assert "of ${rows.length} satisfied" in panel

    def test_a_kind_with_no_list_says_so_rather_than_drawing_nothing(self) -> None:
        panel = self.APP[self.APP.index("function viewChecklist"):self.APP.index("// ── SAP tab")]
        assert "keeps no list of papers" in panel
