"""A re-calculation report that does not add up is not a report (23 Oct 2026).

PC-2026-000070 was filed with the GPF Final Re-calculation Report on page 6 of the claim, and
the reader read it: twenty-four years of figures went onto the case. Thirteen of those years
did not add up. The reader had lost its place among ten columns that are nil down most of
their length: an advance of Rs 80,000 stood against 2007-08 instead of 2008-09, every closing
balance from 2008 on was the following year's, and the last year closed at nil when the
balance carried into it was Rs 883,646.

Nothing noticed. fund_position, the advance limits and the claim reconciliation all read this
table, so the examination ran on figures that were not the report's and the case reached the
officer looking as though the report had been understood. The SAP extracts page showed "Last
closing: Rs 0" and that was the only sign.

The page carries its own proof: the columns are an equation, and each year opens where the
year before it closed. Both are checked before anything is computed from them.

    python3 -m pytest tests/test_recalc_reconciles.py -q
"""
from __future__ import annotations

import pytest

from gpf.rules_common import _recalc_adds_up
from gpf.sap import recalc_discrepancies, row_should_close_at


def row(start, end, opening, closing, *, subscription=0.0, adjustments=0.0, tempAdvance=0.0,
        recTempAdvance=0.0, permanentAdvance=0.0, interest=0.0):
    return {"start": start, "end": end, "opening": opening, "closing": closing,
            "subscription": subscription, "adjustments": adjustments, "tempAdvance": tempAdvance,
            "recTempAdvance": recTempAdvance, "permanentAdvance": permanentAdvance,
            "interest": interest}


#: Four years off PC-2026-000070's own page, as the page prints them.
AS_PRINTED = [
    row("01.07.2007", "30.06.2008", 62906.0, 91632.0, subscription=19580.0, interest=9146.0),
    row("01.07.2008", "30.06.2009", 91632.0, 60694.0, subscription=26900.0, tempAdvance=80000.0,
        recTempAdvance=10000.0, interest=12162.0),
    row("01.07.2009", "30.06.2010", 60694.0, 131805.0, subscription=28200.0, recTempAdvance=30000.0,
        interest=12911.0),
    row("01.07.2021", "30.06.2022", 1271685.0, 190378.0, subscription=58960.0,
        permanentAdvance=1250000.0, interest=109733.0),
]

#: The same four years as the reader stored them: the advance a year early, the closings a
#: year late. Every figure here is one that is really on the case.
AS_READ = [
    row("01.07.2007", "30.06.2008", 62906.0, 91632.0, subscription=19550.0, tempAdvance=80000.0,
        recTempAdvance=10000.0, interest=9146.0),
    row("01.07.2008", "30.06.2009", 91632.0, 131805.0, subscription=26900.0, recTempAdvance=30000.0,
        interest=12162.0),
    row("01.07.2009", "30.06.2010", 131805.0, 213198.0, subscription=28200.0, recTempAdvance=30000.0,
        interest=12911.0),
]


class TestTheEquationIsTheReportS:

    @pytest.mark.parametrize("r", AS_PRINTED, ids=lambda r: r["start"])
    def test_every_printed_year_adds_up(self, r) -> None:
        """Including the year an advance was drawn and the year one was recovered, which is
        where a reader that treats the movements as all-positive goes wrong."""
        assert row_should_close_at(r) == pytest.approx(r["closing"])

    def test_an_advance_leaves_the_fund_and_a_recovery_returns_to_it(self) -> None:
        drawn = AS_PRINTED[1]
        assert drawn["closing"] < drawn["opening"], "Rs 80,000 drawn: the fund must fall"
        assert row_should_close_at(drawn) == pytest.approx(60694.0)

    def test_a_permanent_advance_leaves_it_too(self) -> None:
        assert row_should_close_at(AS_PRINTED[3]) == pytest.approx(190378.0)


class TestWhatTheReaderActuallyProduced:

    def test_the_misread_years_are_caught(self) -> None:
        bad = recalc_discrepancies({"rows": AS_READ})
        assert {d["start"] for d in bad} >= {"01.07.2007", "01.07.2008"}

    def test_the_printed_years_are_not(self) -> None:
        assert recalc_discrepancies({"rows": AS_PRINTED[:3]}) == []

    def test_a_dropped_figure_breaks_the_chain_even_where_each_row_adds_up(self) -> None:
        """The two checks cover different faults. A reader that drops one closing balance and
        shifts the rest keeps every row's arithmetic and breaks the chain between them."""
        rows = [row("01.07.2020", "30.06.2021", 100.0, 200.0, subscription=100.0),
                row("01.07.2021", "30.06.2022", 900.0, 1000.0, subscription=100.0)]
        kinds = {d["kind"] for d in recalc_discrepancies({"rows": rows})}
        assert kinds == {"does-not-follow-on"}

    def test_a_rounding_of_a_rupee_is_not_a_misreading(self) -> None:
        r = row("01.07.2020", "30.06.2021", 100.0, 201.0, subscription=100.0)
        assert recalc_discrepancies({"rows": [r]}) == []

    def test_the_last_year_may_show_interest_it_has_not_credited(self) -> None:
        """A report struck for payment computes the interest to the date of payment and does
        not roll it into the closing balance. fp-dismissal closes at its own opening with
        Rs 2,239 beside it; the residual case is out by exactly its Rs 20,807. Every other
        year on every fixture credits it, so the carve-out is one row and one amount."""
        stub = row("01.07.2024", "30.06.2025", 17968.0, 17968.0, interest=2239.0)
        assert recalc_discrepancies({"rows": [row("01.07.2023", "30.06.2024", 0.0, 17968.0,
                                                  subscription=17968.0), stub]}) == []

    def test_but_only_on_the_last_year(self) -> None:
        stub = row("01.07.2023", "30.06.2024", 17968.0, 17968.0, interest=2239.0)
        after = row("01.07.2024", "30.06.2025", 17968.0, 17968.0)
        bad = recalc_discrepancies({"rows": [stub, after]})
        assert [d["kind"] for d in bad] == ["does-not-add-up"]

    def test_and_only_for_exactly_that_interest(self) -> None:
        """PC-2026-000070's last year is out by Rs 883,646 against nil interest, which is the
        whole point: the carve-out must not swallow a row the reader simply failed to read."""
        stub = row("01.07.2026", "30.06.2027", 883646.0, 0.0)
        bad = recalc_discrepancies({"rows": [row("01.07.2025", "30.06.2026", 0.0, 883646.0,
                                                 subscription=883646.0), stub]})
        assert [d["kind"] for d in bad] == ["does-not-add-up"]
        assert bad[0]["expected"] == 883646.0 and bad[0]["found"] == 0.0

    def test_an_empty_or_absent_report_raises_nothing(self) -> None:
        assert recalc_discrepancies(None) == []
        assert recalc_discrepancies({}) == []
        assert recalc_discrepancies({"rows": []}) == []


class TestWhatTheOfficerIsTold:

    def _run(self, rows, **extra):
        return _recalc_adds_up({"sap": {"recalc": {"rows": rows, "page": 6}}, **extra})

    def test_a_report_that_adds_up_is_satisfied_and_says_so(self) -> None:
        r = self._run(AS_PRINTED[:3])
        assert r["status"] == "ok"
        assert "3 years" in r["finding"]

    def test_a_report_that_does_not_is_a_hard_stop(self) -> None:
        """Hard, because what rests on these figures is a payment."""
        r = self._run(AS_READ)
        assert r["status"] == "hard"
        assert r["code"] == "R11"

    def test_it_names_the_years_and_both_figures(self) -> None:
        r = self._run(AS_READ)
        assert "01.07.2007 to 30.06.2008" in r["finding"]
        assert "Rs 21,602" in r["finding"] and "Rs 91,632" in r["finding"]

    def test_it_says_how_many_rather_than_listing_two_dozen(self) -> None:
        many = AS_READ * 4
        r = self._run(many)
        assert "and " in r["finding"] and "more" in r["finding"]

    def test_it_says_what_cannot_be_relied_on(self) -> None:
        """The officer has to know the balances are not the report's, not merely that a row
        looked odd: every limit test on the case was computed from them."""
        r = self._run(AS_READ)
        assert "nothing computed from them can be relied on" in r["finding"]
        assert "balances on this case are not the report's" in r["finding"]
        assert "pull it from SAP again" in r["remedy"]

    def test_it_points_at_the_page_it_was_read_from(self) -> None:
        assert self._run(AS_READ)["evidence"][0]["page"] == 6

    def test_the_officer_who_checked_it_against_the_original_can_say_so(self) -> None:
        r = self._run(AS_READ)
        assert r["cure"] == {"kind": "verify", "vid": "RECALC-ADDS-UP"}
        cleared = self._run(AS_READ, verifications={
            "RECALC-ADDS-UP": {"ok": True, "by": "A Officer", "desig": "AO",
                               "at": "23.10.2026 18:00", "note": "checked against page 6"}})
        assert cleared["status"] == "ok"
        assert "checked against page 6" in cleared["finding"]

    def test_and_recording_that_it_does_not_stand_keeps_it_stopped(self) -> None:
        r = self._run(AS_READ, verifications={
            "RECALC-ADDS-UP": {"ok": False, "by": "A Officer", "desig": "AO", "at": "x", "note": ""}})
        assert r["status"] == "hard"


class TestItRunsOnEveryCaseThatHasAReport:

    def test_it_applies_wherever_there_are_rows(self) -> None:
        from gpf.registry import CHECKS
        c = next(c for c in CHECKS if c.id == "RECALC-ADDS-UP")
        assert c.applies({"sap": {"recalc": {"rows": AS_PRINTED}}}) is True

    def test_and_not_where_there_is_no_report(self) -> None:
        from gpf.registry import CHECKS
        c = next(c for c in CHECKS if c.id == "RECALC-ADDS-UP")
        for facts in ({}, {"sap": {}}, {"sap": {"recalc": {}}}, {"sap": {"recalc": {"rows": []}}}):
            assert not c.applies(facts), facts
