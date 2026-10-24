"""A year that does not add up says which cell to look at (24 Oct 2026).

PC-2026-000053 is thirty-one years of ledger, eight of which did not close. The hard stop
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
    """PC-2026-000053's 2013-14: out by Rs 60, and only the interest column can account for it
    with a single digit -- subscription would have to go 4,476 -> 4,536, which is two."""

    LEDGER = chain(
        year("01.07.2012", "30.06.2013", 59051, 59051),
        year("01.07.2013", "30.06.2014", 59051, 71826, subscription=4476, interest=8239),
        year("01.07.2014", "30.06.2015", 71826, 71826),
    )

    def test_one_cell_is_named_with_the_value_that_would_close_the_year(self) -> None:
        e = explain_row(self.LEDGER["rows"], 1)
        assert e["chain"] is True
        assert {c["column"] for c in e["oneDigit"]} == {"interest"}
        assert e["oneDigit"][0]["read"] == 8239 and e["oneDigit"][0]["needed"] == 8299

    def test_it_says_so_in_words(self) -> None:
        said = explain_in_words(self.LEDGER["rows"], 1)
        assert said.startswith("One figure is a digit out:")
        assert "interest reads Rs 8,239" in said and "Rs 8,299 would close the year" in said

    def test_the_finding_carries_it(self) -> None:
        bad = [d for d in recalc_discrepancies(self.LEDGER) if d["kind"] == "does-not-add-up"]
        assert len(bad) == 1 and "Rs 8,299" in bad[0]["says"]

    def test_a_year_that_adds_up_says_nothing(self) -> None:
        assert explain_in_words(self.LEDGER["rows"], 0) == ""


class TestWhenTwoCellsWouldBothExplainIt:
    """2002-03 on the same claim: out by Rs 400, and either the subscription (1,020 -> 1,420)
    or the interest (426 -> 826) is a single digit. The arithmetic cannot choose and does not
    pretend to; naming the wrong one would send an officer to the wrong cell."""

    LEDGER = chain(
        year("01.07.2001", "30.06.2002", 5142, 5142),
        year("01.07.2002", "30.06.2003", 5142, 6988, subscription=1020, interest=426),
        year("01.07.2003", "30.06.2004", 6988, 6988),
    )

    def test_both_are_offered(self) -> None:
        e = explain_row(self.LEDGER["rows"], 1)
        assert {c["column"] for c in e["oneDigit"]} == {"subscription", "interest"}

    def test_the_wording_says_one_of_them_rather_than_naming_one(self) -> None:
        said = explain_in_words(self.LEDGER["rows"], 1)
        assert said.startswith("One of these is a digit out:")
        assert "Rs 1,420" in said and "Rs 826" in said


class TestAFigureReadAsNil:

    LEDGER = chain(
        year("01.07.2016", "30.06.2017", 117387, 117387),
        year("01.07.2017", "30.06.2018", 117387, 140490, subscription=6557, interest=14277),
        year("01.07.2018", "30.06.2019", 140490, 140490),
    )

    def test_the_amount_is_named_and_the_nil_columns_listed(self) -> None:
        e = explain_row(self.LEDGER["rows"], 1)
        assert e["oneDigit"] == [], "no single digit explains 2,269"
        assert {c["needed"] for c in e["readAsNil"]} == {2269}
        assert {c["column"] for c in e["readAsNil"]} == {"adjustments", "recTempAdvance"}

    def test_it_does_not_pretend_to_choose_between_them(self) -> None:
        said = explain_in_words(self.LEDGER["rows"], 1)
        assert "one of these columns" in said
        assert "adjustment" in said and "temporary advance recovered" in said
        assert "Rs 2,269" in said


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
        assert "Rs 8,299" in r["finding"]
        assert "the page is the authority" in r["remedy"]

    def test_nothing_in_the_ledger_is_rewritten(self) -> None:
        rows = [dict(r) for r in TestADigitOut.LEDGER["rows"]]
        before = [dict(r) for r in rows]
        explain_row(rows, 1), recalc_discrepancies({"rows": rows})
        assert rows == before
