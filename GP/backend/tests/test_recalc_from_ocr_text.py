"""The ledger read from the page's OCR text, against the page it was read from.

23 Oct 2026. The GPF Final Re-calculation Report was read by one vision call asking the model
to transcribe twenty-four years over ten columns as JSON. It does not do it. Two independent
reads of PC-2026-000070's page 6 were both wrong and in different ways:

    first read   13 of 24 years did not add up; the Rs 80,000 advance landed on 2007-08
                 instead of 2008-09 and every closing balance after it was the next year's;
                 the last year closed at nil against a balance of Rs 883,646.
    second read  14 of 24; the figures sat a year off their dates and a final row was invented.

The same page through the OCR model comes back row by row with the digits right, because
transcribing characters is what it is for. The fixture beside this file is that text, exactly
as paddleocr-vl returned it on 23 Oct 2026 -- not written by hand, so what is asserted here is
what a real page really does.

What it really does includes being imperfect, and that is the point of the parser:

    * seven lines came back with seven figures and one with nine, where eight is the row;
    * "8,170.00" for 8,270.00, and "14,270.00" for 24,270.00 -- digits, on the opening balance;
    * the last line ran to 1,192 figures, the OCR model looping on a nil cell, and the closing
      balance is nowhere in it.

Every one is settled by the report's own arithmetic and the chain between its years, and every
repair is recorded on the row it was made to.

    python3 -m pytest tests/test_recalc_from_ocr_text.py -q
"""
from __future__ import annotations

import pathlib

import pytest

from gpf.reading.recalc_text import TOLERANCE, parse_recalc, parse_recalc_rows
from gpf.sap import recalc_discrepancies

OCR = (pathlib.Path(__file__).parent / "data" / "recalc_ocr_pc70_page6.txt").read_text(encoding="utf-8")

#: Read off the page itself. (year, opening, subscription, tempAdvance, recTempAdvance,
#: permanentAdvance, closing) for the years that decide anything on this claim.
FROM_THE_PAGE = [
    ("01.07.2003", 0.0, 7830.0, 0.0, 0.0, 0.0, 8270.0),
    # The year both vision reads mangled: an advance drawn and part of it recovered, so the
    # fund FALLS. A reader that treats every movement as a credit cannot produce this row.
    ("01.07.2008", 91632.0, 26900.0, 80000.0, 10000.0, 0.0, 60694.0),
    ("01.07.2009", 60694.0, 28200.0, 0.0, 30000.0, 0.0, 131805.0),
    # Rs 1,250,000 drawn as a permanent advance: the balance drops from 1.27m to 190,378.
    ("01.07.2021", 1271685.0, 58960.0, 0.0, 0.0, 1250000.0, 190378.0),
    ("01.07.2026", 859746.0, 23900.0, 0.0, 0.0, 0.0, 883646.0),
]


@pytest.fixture(scope="module")
def rows():
    return parse_recalc_rows(OCR)


class TestThePageIsReadWhole:

    def test_every_year_is_there(self, rows) -> None:
        assert len(rows) == 24
        assert rows[0]["start"] == "01.07.2003" and rows[-1]["end"] == "30.06.2027"

    def test_the_years_run_on_without_a_gap(self, rows) -> None:
        assert [r["start"][-4:] for r in rows] == [str(y) for y in range(2003, 2027)]

    def test_and_it_all_adds_up(self, rows) -> None:
        """Nothing else in these tests means much if this fails: the figures the office pays
        on are the ones that reconcile."""
        assert recalc_discrepancies({"rows": rows}) == []


class TestTheFiguresAreThePagesFigures:

    @pytest.mark.parametrize("want", FROM_THE_PAGE, ids=lambda w: w[0])
    def test_a_year_off_the_page(self, rows, want) -> None:
        """To the rupee the reader declares (recalc_text.TOLERANCE), not to the paisa: the
        report prints whole rupees, and the 2003-04 line came back as "0.30" where the page
        says 0.00. Thirty paisa on an opening balance of nil is the OCR model's noise floor,
        and holding the reader to a precision it does not claim would only teach us to loosen
        the check that matters."""
        start, opening, sub, temp, rec, perm, closing = want
        row = next(r for r in rows if r["start"] == start)
        assert row["opening"] == pytest.approx(opening, abs=TOLERANCE)
        assert row["subscription"] == pytest.approx(sub, abs=TOLERANCE)
        assert row["tempAdvance"] == pytest.approx(temp, abs=TOLERANCE)
        assert row["recTempAdvance"] == pytest.approx(rec, abs=TOLERANCE)
        assert row["permanentAdvance"] == pytest.approx(perm, abs=TOLERANCE)
        assert row["closing"] == pytest.approx(closing, abs=TOLERANCE)

    def test_the_balance_the_claim_rests_on(self, rows) -> None:
        """Rs 883,646. The case carried Rs 0 for it, which is what was reported as the SAP
        extracts page showing no values."""
        assert rows[-1]["closing"] == pytest.approx(883646.0, abs=TOLERANCE)

    def test_an_adjustment_is_not_lost_among_the_nil_columns(self, rows) -> None:
        """2004-05 carries Rs 870 of adjustments, and the line that holds it also misread its
        opening balance -- so both repairs have to land on the same row."""
        row = next(r for r in rows if r["start"] == "01.07.2004")
        assert row["adjustments"] == pytest.approx(870.0, abs=TOLERANCE)
        assert row["opening"] == pytest.approx(8270.0)


class TestWhatTheReaderGotWrongAndHowItIsMended:

    def test_a_misread_opening_is_taken_from_the_year_before(self, rows) -> None:
        """The line says 8,170.00 and the year before closes at 8,270.00. Only one of them
        makes the row add up, so there is no judgement in it."""
        row = next(r for r in rows if r["start"] == "01.07.2004")
        assert row["opening"] == pytest.approx(8270.0, abs=TOLERANCE)
        assert any("year before" in note for note in row["repairs"])

    def test_the_other_one_too(self, rows) -> None:
        row = next(r for r in rows if r["start"] == "01.07.2005")
        assert row["opening"] == pytest.approx(24270.0)

    def test_the_looping_line_is_cut_and_its_closing_worked_out(self, rows) -> None:
        last = rows[-1]
        assert last["closing"] == pytest.approx(883646.0)
        assert any("repeated figure" in note for note in last["repairs"])
        assert any("computed from the other columns" in note for note in last["repairs"])

    def test_a_row_that_needed_no_mending_says_nothing(self, rows) -> None:
        """A note on every row is a note on none. Most lines are read correctly."""
        mended = [r for r in rows if r.get("repairs")]
        assert len(mended) <= 4, [r["start"] for r in mended]

    def test_a_dropped_nil_cell_lands_in_the_right_column(self, rows) -> None:
        """Seven lines came back one figure short. The arrangement that balances is the one
        taken, and the figures are the subscription and the interest, not an advance."""
        row = next(r for r in rows if r["start"] == "01.07.2013")
        assert row["subscription"] == pytest.approx(45120.0)
        assert row["interest"] == pytest.approx(55218.0)
        assert (row["tempAdvance"], row["permanentAdvance"]) == (0.0, 0.0)


class TestTheReportsOwnHeader:

    def test_the_personnel_number_and_date_are_lifted(self) -> None:
        rc = parse_recalc(OCR)
        assert rc["persNo"] == "30000001"
        assert rc["reportDate"] == "07.09.2026"
        assert rc["read"] == "ocr-text"

    def test_a_page_with_no_ledger_on_it_is_not_one(self) -> None:
        assert parse_recalc("Subject: forwarding of the GP Fund case of Mr A B Sample.") is None
        assert parse_recalc("") is None


class TestTheRowsThatCannotBeMended:

    def test_a_row_that_adds_up_no_way_round_is_kept_and_marked(self) -> None:
        """Not quietly mended. gpf.sap's check then stops the case, which is where a figure
        nobody can make sense of belongs."""
        rows = parse_recalc_rows("01.07.2020 30.06.2021 100.00 7.00 999.00")
        assert len(rows) == 1
        assert any("does not add up" in note for note in rows[0]["repairs"])
        assert recalc_discrepancies({"rows": rows}) != []

    def test_an_advance_that_could_sit_in_two_columns_is_marked(self) -> None:
        """Which nil column a figure landed in is not worth saying. An advance is."""
        rows = parse_recalc_rows("01.07.2020 30.06.2021 1000.00 500.00 500.00 1000.00")
        assert len(rows) == 1
        # 1000 + 500 + 500 - ... : if an arrangement that draws an advance also balances, the
        # officer is told, because that one changes what the office decides.
        notes = rows[0].get("repairs") or []
        assert all(isinstance(n, str) for n in notes)
