"""The proforma the department sends instead of the Service Book is read as one (26 Oct 2026).

PC-2026-000073 carried "PROFORMA FOR GP FUND FINAL PAYMENT" on page 1 -- particulars of the
employee, a service record summary, signed by the DDO -- and the checklist reported no Service
Book on file. The classifier was not wrong so much as speechless: thirty classes and not one
of them described that page, so whatever it was called had no merger, nothing reached
F["docs"], and A2-vii answered from an empty slot.

Two things come out of that. The class exists now, with a legend that separates it from the
bound Service Book it replaces. And every page's classification is recorded on the case, so
the next time a paper that is plainly there is reported missing, the case itself says what the
page was taken to be instead of needing to be read again to find out.

    python3 -m pytest tests/test_the_proforma_stands_for_the_service_book.py -q
"""
from __future__ import annotations

from gpf import rules_family
from gpf.clients.model_client import ExtractedField
from gpf.reading.artefacts import Artefact
from gpf.reading.pipeline import PageResult, assemble_facts


def field(value, page=1):
    return ExtractedField(value=value, confidence=0.95, page=page)


def proforma(page=1, **over):
    f = {"name": field("A B Sample"), "personnel_no": field("30000001"),
         "date_of_retirement": field("15-12-2024"), "type_of_retirement": field("Superannuation"),
         "leave_summary_filled": field(True), "ddo_signed": field(True)}
    f.update({k: field(v) for k, v in over.items()})
    return PageResult(page=page, artefact=Artefact.FP_PROFORMA.value, classify_confidence=0.96, fields=f)


def facts(*pages, kind="final", gazetted="non-gazetted"):
    return assemble_facts(list(pages), kind=kind, gazetted=gazetted)


class TestItFillsTheServiceBooksSlot:

    def test_the_proforma_is_the_paper_on_file(self) -> None:
        sb = facts(proforma(page=1))["docs"]["serviceBook"]
        assert sb["present"] and sb["proforma"] and sb["page"] == 1

    def test_the_check_passes_and_names_what_it_found(self) -> None:
        r = rules_family._fp_sb(facts(proforma(page=1)))
        assert r["status"] == "ok"
        assert "Proforma For Service at page 1" in r["finding"]

    def test_a_blank_line_on_it_is_still_asked_for(self) -> None:
        """It is not a free pass: what the proforma does not record, it does not record."""
        r = rules_family._fp_sb(facts(proforma(page=1, leave_summary_filled=False)))
        assert r["status"] == "conf"
        assert "leave account" in r["finding"]
        assert "cannot be seen" not in r["finding"], "the whole paper IS in the case"

    def test_nothing_on_file_still_stops_the_claim(self) -> None:
        r = rules_family._fp_sb(facts(kind="final", gazetted="non-gazetted"))
        assert r["status"] == "hard"
        assert "No Proforma For Service is on file" in r["finding"]


class TestTheBalanceTransferKeepsItsOwnProforma:
    """Both are called a proforma and the mergers were briefly one function, which wired the
    final-payment one and then let the other overwrite it."""

    def test_the_two_mergers_are_different_functions(self) -> None:
        from gpf.reading.pipeline import _MERGERS
        assert _MERGERS[Artefact.FP_PROFORMA.value] is not _MERGERS[Artefact.BALANCE_TRANSFER_PROF.value]

    def test_the_balance_transfer_still_fills_its_own_slot(self) -> None:
        pr = PageResult(page=2, artefact=Artefact.BALANCE_TRANSFER_PROF.value, classify_confidence=0.9,
                        fields={"name": field("A B Sample", 2), "old_ac": field("01700000001", 2)})
        F = assemble_facts([pr], kind="balance_transfer")
        assert F["docs"]["proforma"]["page"] == 2
        assert "serviceBook" not in F["docs"]


class TestEveryPageSaysWhatItWasTakenToBe:
    """The record that would have answered PC-2026-000063 and PC-2026-000073 in a minute."""

    def test_each_page_is_listed_with_its_class_and_confidence(self) -> None:
        F = facts(proforma(page=1))
        assert F["pages"] == [{"page": 1, "artefact": "FP_PROFORMA", "confidence": 0.96,
                               "merged": True,
                               "fields": ["date_of_retirement", "ddo_signed", "leave_summary_filled",
                                          "name", "personnel_no", "type_of_retirement"]}]

    def test_a_page_that_merged_into_nothing_is_recorded_too(self) -> None:
        """This is the case that used to vanish: classified, no merger, no trace."""
        pr = PageResult(page=3, artefact=Artefact.UNKNOWN.value, classify_confidence=0.41, fields={})
        F = assemble_facts([pr], kind="final")
        assert F["pages"] == [{"page": 3, "artefact": "UNKNOWN", "confidence": 0.41,
                               "merged": False, "fields": []}]

    def test_the_rules_do_not_read_it(self) -> None:
        """It is the reading's account of itself, not a fact to examine."""
        import pathlib
        for name in ("rules_common.py", "rules_family.py"):
            src = (pathlib.Path(__file__).resolve().parent.parent / "gpf" / name).read_text(encoding="utf-8")
            assert 'F["pages"]' not in src and "F.get(\"pages\")" not in src


class TestTheClassifierIsToldHowToTellThemApart:

    def test_the_legend_describes_the_proforma_and_says_what_it_is_not(self) -> None:
        from gpf.reading.artefacts import CLASSIFY_HINTS
        hint = CLASSIFY_HINTS[Artefact.FP_PROFORMA]
        assert "PROFORMA FOR GP FUND FINAL PAYMENT" in hint
        assert "NOT a page of a Service Book" in hint
