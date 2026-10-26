"""What the department is told to attach, per kind of claim (23 Oct 2026).

A pension case shows the documents its type requires the moment the type is chosen, from the
same requirements the checklist runs on. The GP Fund filing screen could only say "attach every
page of the claim", so the department learnt what was missing when the claim came back.

gpf.intake reads the list off the checks instead of keeping a second copy, by asking each one
whether it applies to facts carrying the shape of a claim of that kind and none of its
particulars. These tests pin the three judgements that shape makes:

  * a paper every claim of the kind needs is listed as required;
  * a paper needed only when it applies is listed, but apart;
  * a check ABOUT a paper already listed is not listed again as a paper.

    python3 -m pytest tests/test_intake_checklists.py -q
"""
from __future__ import annotations

import pytest

from gpf.intake import KINDS, Anything, Present, checklist_for, checklists
from gpf.registry import CHECKS


def _items(rows):
    return {r["requirement"] for r in rows}


def _required(kind, gazetted="unknown"):
    return {r["requirement"] for r in checklist_for(kind, gazetted) if r["always"]}


def _conditional(kind, gazetted="unknown"):
    return {r["requirement"] for r in checklist_for(kind, gazetted) if not r["always"]}


class TestTheListIsTheCircularS:
    """A.1 advances, A.2 final payment, A.3 balance transfer, A.4 missing credits."""

    @pytest.mark.parametrize("kind,section", [
        ("refundable", "A1"), ("nonrefundable", "A1"),
        ("final", "A2"), ("death", "A2"), ("dismissal", "A2"),
        ("balance_transfer", "A3"), ("missing_credits", "A4"),
    ])
    def test_each_kind_answers_to_its_own_section(self, kind, section) -> None:
        rows = checklist_for(kind)
        assert rows, f"{kind} lists no papers at all"
        assert {r["item"].split("-")[0] for r in rows} == {section}

    def test_the_items_come_back_in_the_circulars_order(self) -> None:
        """Sorted as roman numerals, not as text: sorted() would put A2-ix before A2-v."""
        ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
        for kind in KINDS:
            ranks = [ROMAN.index(r["item"].split("-")[1]) for r in checklist_for(kind, "non-gazetted")]
            assert ranks == sorted(ranks), kind

    def test_a_roman_numeral_past_the_point_text_sorting_breaks(self) -> None:
        """The guard itself: ix is the ninth item, and as text it sorts before v."""
        from gpf.intake import _order
        assert _order("A2-ix") > _order("A2-v")
        assert sorted(["A2-ix", "A2-v"]) == ["A2-ix", "A2-v"]   # which is why _order exists


class TestWhatEveryClaimOfTheKindNeeds:

    def test_an_advance_wants_the_sanction_the_cnic_and_the_form(self) -> None:
        assert _required("refundable") == {
            "Original sanction of the competent authority",
            "Copy of CNIC of the subscriber",
            "Form 5 (refundable) or Form 6-B (non-refundable)",
        }

    def test_a_final_payment_wants_the_five_of_a2(self) -> None:
        assert _required("final") == {
            "Covering / forwarding letter",
            "G.P.F. Form 10, properly filled and signed",
            "Retirement, dismissal or obituary notification",
            "Copy of CNIC of the subscriber",
            "Change Form-06 signed by DDO and subscriber",
        }

    def test_a_death_claim_wants_the_heirs_papers_as_well(self) -> None:
        """A death claim HAS heirs, so their CNICs are required and not merely possible. That
        is what the Present facts are for: the block exists, nothing is known about it."""
        assert "CNIC copies of all legal heirs" in _required("death")
        assert "Succession certificate, or OSD post created" in _required("death")
        assert _required("final") < _required("death")

    def test_a_living_subscribers_claim_is_not_asked_for_them(self) -> None:
        for kind in ("final", "dismissal"):
            assert "CNIC copies of all legal heirs" not in _items(checklist_for(kind)), kind


class TestWhatIsOnlyWantedWhenItApplies:

    def test_the_widows_affidavit_is_listed_but_not_among_the_required(self) -> None:
        """It is wanted when a widow claims and not otherwise. A list that asks every family
        for one is a list the department stops reading."""
        assert "Original affidavit for lawful widow" in _conditional("death")
        assert "Original affidavit for lawful widow" not in _required("death")

    def test_everything_listed_is_one_or_the_other(self) -> None:
        for kind in KINDS:
            rows = checklist_for(kind)
            assert all(isinstance(r["always"], bool) for r in rows), kind


class TestTheSubscriberNarrowsTheList:
    """A missing-credits claim needs the DDO's certificate for a non-gazetted period and the
    AG office's for a gazetted one. Not stated asks for both, which is the honest answer."""

    DDO = "Manual deduction certificate by DDO, with bills and acquaintance roll (non-gazetted period)"
    AG = "Manual deduction certificate by AG Office (gazetted period)"

    def test_not_stated_asks_for_both(self) -> None:
        assert {self.DDO, self.AG} <= _required("missing_credits", "unknown")

    def test_a_gazetted_subscriber_is_asked_only_for_the_ag_offices(self) -> None:
        got = _items(checklist_for("missing_credits", "gazetted"))
        assert self.AG in got and self.DDO not in got

    def test_a_non_gazetted_subscriber_is_asked_only_for_the_ddos(self) -> None:
        got = _items(checklist_for("missing_credits", "non-gazetted"))
        assert self.DDO in got and self.AG not in got

    def test_a_non_gazetted_final_payment_also_wants_the_proforma(self) -> None:
        """A2-vii. The gazetted answer bears on more than the missing-credits certificates, and
        this check wants "non-gazetted" exactly -- "Not stated" does not ask for it. So a
        department that says which it is gets told about a paper it would otherwise send late.

        Named "Proforma For Service" from 26 Oct 2026: A2-vii says Original Service Book, and
        what the office actually receives in its place is the proforma. The line an officer
        reads should name the paper that is in the file."""
        book = "Proforma For Service (non-gazetted)"
        assert book in _required("final", "non-gazetted")
        assert book not in _items(checklist_for("final", "gazetted"))
        assert book not in _items(checklist_for("final", "unknown"))

    def test_it_changes_nothing_where_it_bears_on_nothing(self) -> None:
        for kind in ("refundable", "nonrefundable", "balance_transfer"):
            assert checklist_for(kind, "gazetted") == checklist_for(kind, "non-gazetted"), kind


class TestAPaperIsAskedForOnceUnderOneName:

    def test_a_check_about_a_listed_paper_is_not_listed_as_a_paper(self) -> None:
        """"Rule and reason quoted on the sanction" and "Form signed by the DDO" are checks on
        papers A1-i and A1-iii already ask for. They carry no checklist code, which is how
        they are told apart, and listing them would ask for the same paper twice."""
        got = _items(checklist_for("refundable"))
        assert "Rule and reason quoted on the sanction" not in got
        assert "Form signed by the DDO" not in got

    def test_only_a_check_carrying_a_checklist_code_is_a_paper(self) -> None:
        coded = {c.id for c in CHECKS if c.group == "checklist" and c.checklist}
        for kind in KINDS:
            assert {r["id"] for r in checklist_for(kind)} <= coded, kind

    def test_every_row_says_what_the_paper_is(self) -> None:
        for kind in KINDS:
            for row in checklist_for(kind):
                assert row["requirement"] and row["requirement"] != row["id"], (kind, row)
                assert row["item"], (kind, row)


class TestTheProbeFacts:
    """The two stand-in fact objects, which is where this module could go quietly wrong."""

    def test_present_is_a_block_that_exists_and_says_nothing(self) -> None:
        p = Present()
        assert bool(p) is True
        assert p.get("widowClaim") is None

    def test_anything_answers_yes_all_the_way_down(self) -> None:
        a = Anything()
        assert bool(a) is True
        assert bool(a.get("death")) is True
        assert bool(a["death"].get("widowClaim")) is True

    def test_a_check_that_cannot_decide_is_left_out_rather_than_guessed(self) -> None:
        """The engine turns that into an observation the officer sees (H-16). A department
        reading the filing screen can do nothing with "the office is not sure"."""
        from gpf.registry import Check
        boom = Check(id="BOOM", group="checklist", checklist="A2-ix", title="Explodes",
                     applies=lambda F: (_ for _ in ()).throw(KeyError("sap")),
                     run=lambda F: {"status": "ok", "finding": ""})
        CHECKS.append(boom)
        try:
            assert "Explodes" not in _items(checklist_for("final"))
        finally:
            CHECKS.remove(boom)


class TestEveryKindIsServed:

    def test_the_kinds_a_ddo_may_file_all_have_a_list(self) -> None:
        """The portal offers these seven (api/gpf_bridge.KINDS); a residual claim the office
        raises itself, so the module knows it and the department never files one."""
        filable = ("refundable", "nonrefundable", "final", "death", "dismissal",
                   "missing_credits", "balance_transfer")
        everything = checklists("unknown")
        for kind in filable:
            assert everything.get(kind), kind
        assert "residual" in everything, "the module's own kinds are the ones it checks"

    def test_the_answer_is_keyed_by_kind_and_carries_no_labels(self) -> None:
        """What a kind is CALLED is the portal's (gpf_bridge.KINDS); this side owns the papers."""
        everything = checklists("unknown")
        assert set(everything) == set(KINDS)
        assert all(isinstance(v, list) for v in everything.values())
