"""A year that does not add up says which cell to look at (24 Oct 2026).

A live claim came in as thirty-one years of ledger, eight of which did not close. The hard stop
could say only that the table had been read wrongly and the figures were not the report's,
which is true and nearly useless: an officer's only move was to re-read all thirty-one years
against the page.

But the equation knows more. Where a year opens exactly where the one before it closed, and
the one after opens exactly where it closes, both balances are confirmed twice over and the
error is in a movement column. There is then one amount the year is out by, and for each
column one value that would close it. Two of those are worth saying out loud:

* a figure ONE DIGIT from what was read -- interest read as 426 where 826 closes the year --
  which is exactly what a misread of a printed table looks like;
* a column read as nil that would have to hold the amount. The report is mostly nil and that
  is what defeats the reader in the first place; several nil columns are equally possible and
  the check lists them rather than guessing.

Nothing is corrected. The page is the authority.

    python3 -m pytest tests/test_which_cell_was_read_wrongly.py -q
"""
from __future__ import annotations

from gpf.sap import explain_in_words, explain_row, recalc_discrepancies

#: Opening 1,000, subscription 600, interest 400 -> 2,000. Each fixture breaks one cell.
def year(start, end, opening, closing, **cells):
    row = {"start": start, "end": end, "opening": opening, "closing": closing,
           "subscription": 0, "adjustments": 0, "tempAdvance": 0,
           "recTempAdvance": 0, "permanentAdvance": 0, "interest": 0}
    row.update(cells)
    return row


def chain(*rows):
    return {"rows": list(rows)}


class TestADigitOut:
    """Out by Rs 600, and only the interest column accounts for it with a single digit: the
    subscription would have to change two. Figures invented -- a real subscriber's ledger does
    not belong in this repository, however anonymous a row of it looks."""

    LEDGER = chain(
        year("01.07.2012", "30.06.2013", 50000, 50000),
        year("01.07.2013", "30.06.2014", 50000, 60700, subscription=2960, interest=7140),
        year("01.07.2014", "30.06.2015", 60700, 60700),
    )

    def test_one_cell_is_named_with_the_value_that_would_close_the_year(self) -> None:
        e = explain_row(self.LEDGER["rows"], 1)
        assert e["chain"] is True
        assert {c["column"] for c in e["oneDigit"]} == {"interest"}
        assert e["oneDigit"][0]["read"] == 7140 and e["oneDigit"][0]["needed"] == 7740

    def test_it_says_so_in_words(self) -> None:
        said = explain_in_words(self.LEDGER["rows"], 1)
        assert said.startswith("One figure is a digit out:")
        assert "interest reads Rs 7,140" in said and "Rs 7,740 would close the year" in said

    def test_the_finding_carries_it(self) -> None:
        bad = [d for d in recalc_discrepancies(self.LEDGER) if d["kind"] == "does-not-add-up"]
        assert len(bad) == 1 and "Rs 7,740" in bad[0]["says"]

    def test_a_year_that_adds_up_says_nothing(self) -> None:
        assert explain_in_words(self.LEDGER["rows"], 0) == ""


class TestWhenTwoCellsWouldBothExplainIt:
    """Out by Rs 400, and either the subscription (2,030 -> 2,430) or the interest (515 ->
    915) is a single digit. The arithmetic cannot choose and does not pretend to; naming the
    wrong one would send an officer to the wrong cell."""

    LEDGER = chain(
        year("01.07.2001", "30.06.2002", 8000, 8000),
        year("01.07.2002", "30.06.2003", 8000, 10945, subscription=2030, interest=515),
        year("01.07.2003", "30.06.2004", 10945, 10945),
    )

    def test_both_are_offered(self) -> None:
        e = explain_row(self.LEDGER["rows"], 1)
        assert {c["column"] for c in e["oneDigit"]} == {"subscription", "interest"}

    def test_the_wording_says_one_of_them_rather_than_naming_one(self) -> None:
        said = explain_in_words(self.LEDGER["rows"], 1)
        assert said.startswith("One of these is a digit out:")
        assert "Rs 2,430" in said and "Rs 915" in said


class TestAFigureReadAsNil:

    LEDGER = chain(
        year("01.07.2016", "30.06.2017", 20000, 20000),
        year("01.07.2017", "30.06.2018", 20000, 31357, subscription=4000, interest=6000),
        year("01.07.2018", "30.06.2019", 31357, 31357),
    )

    def test_the_amount_is_named_and_the_nil_columns_listed(self) -> None:
        e = explain_row(self.LEDGER["rows"], 1)
        assert e["oneDigit"] == [], "no single digit explains 1,357"
        assert {c["needed"] for c in e["readAsNil"]} == {1357}
        assert {c["column"] for c in e["readAsNil"]} == {"adjustments", "recTempAdvance"}

    def test_it_does_not_pretend_to_choose_between_them(self) -> None:
        said = explain_in_words(self.LEDGER["rows"], 1)
        assert "one of these columns" in said
        assert "adjustment" in said and "temporary advance recovered" in said
        assert "Rs 1,357" in said


class TestWhereTheArithmeticCannotTell:

    def test_a_year_whose_balances_do_not_agree_with_its_neighbours_is_left_alone(self) -> None:
        """Both balances are then in doubt, so there is no fixed amount to attribute."""
        led = chain(year("01.07.2001", "30.06.2002", 1000, 2000, subscription=600, interest=400),
                    year("01.07.2002", "30.06.2003", 9999, 9999))     # does not follow on
        e = explain_row(led["rows"], 0)
        assert e["chain"] is False
        assert explain_in_words(led["rows"], 0) == ""

    def test_a_negative_or_fractional_cell_is_never_suggested(self) -> None:
        """A column cannot hold minus rupees, and the report prints whole ones."""
        led = chain(year("01.07.2001", "30.06.2002", 1000, 900, subscription=600, interest=400),
                    year("01.07.2002", "30.06.2003", 900, 900))
        for c in explain_row(led["rows"], 0)["readAsNil"] + explain_row(led["rows"], 0)["oneDigit"]:
            assert c["needed"] >= 0


class TestTheStopStillStops:
    """The point is to say where to look, not to decide that it is fine."""

    def test_a_ledger_that_does_not_reconcile_is_still_a_hard_stop(self) -> None:
        from gpf import rules_common
        F = {"sap": {"recalc": TestADigitOut.LEDGER}}
        r = rules_common._recalc_adds_up(F)
        assert r["status"] == "hard" and r["code"] == "R11"
        assert "Rs 7,740" in r["finding"]
        assert "the page is the authority" in r["remedy"]

    def test_nothing_in_the_ledger_is_rewritten(self) -> None:
        rows = [dict(r) for r in TestADigitOut.LEDGER["rows"]]
        before = [dict(r) for r in rows]
        explain_row(rows, 1), recalc_discrepancies({"rows": rows})
        assert rows == before


class TestARunOfYearsIsAColumnNotACell:
    """A run of failing years is a column the reader slipped in, not a cell in each.

    Found on 25 Oct 2026 by reading a live claim's ledger against its own scanned page. Four
    consecutive years failed, and each was told that a figure had been read as nil in one of
    two columns. The page said otherwise: part way down, the reader had slipped one row in
    the opening, interest and closing columns, so the later years carried the NEXT year's
    figures. Nothing had been read as nil and no single cell accounted for any of it -- the
    advice named four cells that were not the fault.

    One cell read wrongly is one year wrong. Neighbouring years failing together is a column.

    The figures below are invented and reproduce the shape, not the claim: a real ledger does
    not belong in this repository (deploy/check-release-pii.py, tests/test_no_real_case_material).
    """

    #: One year a digit out, then three in a row that nothing but a slipped column explains,
    #: then a clean year to close the run.
    LEDGER = chain(
        year("01.07.2010", "30.06.2011", 10000, 12120, subscription=1230, interest=490),
        year("01.07.2011", "30.06.2012", 12120, 15683, subscription=1230, interest=2000),
        year("01.07.2012", "30.06.2013", 15683, 19746, subscription=1230, interest=2500),
        year("01.07.2013", "30.06.2014", 19746, 24309, subscription=1230, interest=3000),
        year("01.07.2014", "30.06.2015", 24309, 29039, subscription=1230, interest=3500),
    )

    def test_every_failing_year_of_the_run_is_recognised_as_one(self) -> None:
        assert [explain_row(self.LEDGER["rows"], i)["run"] for i in range(4)] == [True] * 4

    def test_the_clean_year_that_ends_the_run_says_nothing_at_all(self) -> None:
        """It closes, so there is nothing wrong with it -- whatever the year before was doing.
        Without the guard for this the run reached a year that had been read perfectly."""
        assert explain_in_words(self.LEDGER["rows"], 4) == ""

    def test_a_year_inside_the_run_is_not_offered_a_cell_that_is_not_the_fault(self) -> None:
        said = explain_in_words(self.LEDGER["rows"], 2)
        assert "read as nil" not in said
        assert "slipped in" in said and "Read the run against the page" in said

    def test_a_digit_out_still_says_so_even_beside_a_run(self) -> None:
        """A run next door does not make a good answer a bad one: this year's interest really
        is one digit from the figure that closes it."""
        said = explain_in_words(self.LEDGER["rows"], 0)
        assert "Rs 890 would close the year" in said

    def test_a_year_failing_on_its_own_is_not_called_a_run(self) -> None:
        assert explain_row(TestWhenTwoCellsWouldBothExplainIt.LEDGER["rows"], 1)["run"] is False
