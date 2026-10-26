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


class TestWhichReadIsTaken:
    """The choice between the two readers, which is where this went wrong first.

    PC-2026-000048's page 7 is a thirty-nine year ledger, and the OCR model fell into its
    repeat-one-cell loop on the FIRST row -- so the OCR read was one year, and one year adds
    up. Choosing by arithmetic alone took it over a complete thirty-nine year read with seven
    years out, which is how a wrecked read can look like a perfect one.
    """

    from unittest import mock

    def _client(self, ocr_text, vision_rows, *, truncated=False):
        from gpf.clients.model_client import VllmModelClient
        c = VllmModelClient.__new__(VllmModelClient)

        # ocr_table_text returns its own truncation flag from 26 Oct 2026: the client is
        # shared by every page being read, so an instance flag let one ledger decide another's.
        c.ocr_table_text = lambda _ref: (ocr_text, truncated)
        c._recalc_rows_from_vision = lambda _ref: (vision_rows, 0.95)
        return c

    def _rows(self, n, *, bad=0):
        """n years that chain, the first `bad` of them not adding up."""
        out, opening = [], 0.0
        for i in range(n):
            sub = 1000.0
            closing = opening + sub + (500.0 if i < bad else 0.0)
            out.append({"start": f"01.07.{2000 + i}", "end": f"30.06.{2001 + i}",
                        "opening": opening, "subscription": sub, "adjustments": 0.0,
                        "tempAdvance": 0.0, "recTempAdvance": 0.0, "permanentAdvance": 0.0,
                        "interest": 0.0, "closing": closing})
            opening = closing
        return out

    def test_a_complete_read_beats_a_short_one_that_adds_up(self) -> None:
        client = self._client("01.07.2000 30.06.2001 0.00 1000.00 1000.00", self._rows(39, bad=7))
        rows, _ = client._extract_recalc_rows("p.png")
        assert len(rows) == 39, "one year must never beat thirty-nine"

    def test_and_where_both_are_complete_the_one_that_adds_up_wins(self) -> None:
        """PC-2026-000070's page 6: both readers returned all twenty-four years and only the
        OCR read reconciled."""
        ocr = "\n".join(f"01.07.{2000+i} 30.06.{2001+i} {i*1000}.00 1000.00 0.00 0.00 0.00 0.00 0.00 {i*1000+1000}.00"
                        for i in range(24))
        client = self._client(ocr, self._rows(24, bad=13))
        rows, conf = client._extract_recalc_rows("p.png")
        assert len(rows) == 24 and conf == 0.97

    def test_a_cut_off_read_of_one_row_is_not_a_ledger(self) -> None:
        """Even with nothing to compare it against: it would reach the officer looking whole."""
        client = self._client("01.07.2000 30.06.2001 0.00 1000.00 1000.00", [], truncated=True)
        rows, conf = client._extract_recalc_rows("p.png")
        assert rows == [] and conf == 0.0

    def test_but_a_cut_off_read_that_still_got_the_years_is_kept(self) -> None:
        """Page 6's OCR text DID hit the ceiling -- the loop ate the end of it -- and still
        carried every one of its twenty-four years."""
        ocr = "\n".join(f"01.07.{2000+i} 30.06.{2001+i} {i*1000}.00 1000.00 0.00 0.00 0.00 0.00 0.00 {i*1000+1000}.00"
                        for i in range(24))
        client = self._client(ocr, [], truncated=True)
        rows, _ = client._extract_recalc_rows("p.png")
        assert len(rows) == 24

    def test_neither_reader_getting_anything_is_no_rows(self) -> None:
        client = self._client("Subject: a covering letter.", [])
        assert client._extract_recalc_rows("p.png") == ([], 0.0)


class TestWhenTheSecondReadIsSkipped:
    """The ledger is read by both readers and the better taken, which costs the examination
    the vision read -- forty seconds on PC-2026-000070's page 6, against the OCR read's
    sixty-one. Where the OCR read is already complete and every year adds up, the vision read
    can only return the same ledger or a worse one, so it is not made (24 Oct 2026).

    "Complete" is the whole difficulty. Untruncated is not enough: PC-2026-000048's OCR read
    stopped after one year of thirty-nine and that one year added up. The page itself says
    how far the ledger should run -- the report is struck on a date and its last row is the
    year that date falls in -- and that is what is checked.
    """

    def test_a_ledger_that_runs_up_to_its_report_date_is_complete(self) -> None:
        from gpf.reading.recalc_text import parse_recalc, reaches_the_report_date
        assert reaches_the_report_date(parse_recalc(OCR)) is True

    def test_one_that_stops_sixteen_years_short_is_not(self) -> None:
        from gpf.reading.recalc_text import parse_recalc, reaches_the_report_date
        cut = "\n".join(OCR.splitlines()[:12])
        parsed = parse_recalc(cut)
        assert parsed["reportDate"] == "07.09.2026"
        assert int(parsed["rows"][-1]["end"].split(".")[-1]) < 2026
        assert reaches_the_report_date(parsed) is False

    def test_a_page_that_gives_no_date_is_never_called_complete(self) -> None:
        """Not knowing is not the same as knowing. Without the stamp the second read is made."""
        from gpf.reading.recalc_text import parse_recalc, reaches_the_report_date
        parsed = parse_recalc("01.07.2000 30.06.2001 0.00 1000.00 1000.00")
        assert parsed and not parsed.get("reportDate")
        assert reaches_the_report_date(parsed) is False

    def test_the_short_read_that_started_this_is_still_not_short_circuited(self) -> None:
        """PC-2026-000048: one year, adds up, and the vision read must still be made."""
        from unittest import mock
        from gpf.clients.model_client import VllmModelClient
        c = VllmModelClient.__new__(VllmModelClient)
        c.ocr_table_text = lambda _r: ("01.07.2000 30.06.2001 0.00 1000.00 1000.00", False)
        called = mock.Mock(return_value=([{"start": "01.07.2000", "end": "30.06.2001",
                                           "opening": 0.0, "subscription": 1000.0,
                                           "adjustments": 0.0, "tempAdvance": 0.0,
                                           "recTempAdvance": 0.0, "permanentAdvance": 0.0,
                                           "interest": 0.0, "closing": 1000.0}] * 39, 0.95))
        c._recalc_rows_from_vision = called
        c._extract_recalc_rows("p.png")
        assert called.called, "a short OCR read must never skip the second opinion"


class TestTheTwoReadsRunTogether:
    """The ledger page was the whole of a claim's read (26 Oct 2026).

    PC-2026-000055: six pages, 107.1s, and page 6 alone was 104s of it -- the OCR
    transcription and the vision read of the same table, one after the other, on a ledger that
    does not reconcile and so pays for both. Five pages finished inside that one page's time.

    They start together now. What must NOT change is which read is preferred, or that a clean
    OCR read finishes the page without the vision read ever being waited for.
    """

    from unittest import mock

    def _client(self, *, ocr_text, vision_rows, vision_delay=0.0, truncated=False):
        import time
        from gpf.clients.model_client import VllmModelClient
        c = VllmModelClient.__new__(VllmModelClient)
        c.started = []
        c.ocr_table_text = lambda _r: (c.started.append("ocr"), (ocr_text, truncated))[1]

        def vision(_r):
            c.started.append("vision")
            if vision_delay:
                time.sleep(vision_delay)
            return (vision_rows, 0.95)

        c._recalc_rows_from_vision = vision
        return c

    def _good(self, n):
        rows, opening = [], 0.0
        for i in range(n):
            rows.append({"start": f"01.07.{2000 + i}", "end": f"30.06.{2001 + i}",
                         "opening": opening, "subscription": 1000.0, "adjustments": 0.0,
                         "tempAdvance": 0.0, "recTempAdvance": 0.0, "permanentAdvance": 0.0,
                         "interest": 0.0, "closing": opening + 1000.0})
            opening += 1000.0
        return rows

    def test_the_vision_read_is_already_under_way_when_the_ocr_read_lands(self) -> None:
        """Started, not merely available: that is the whole of the saving."""
        c = self._client(ocr_text="not a ledger at all", vision_rows=self._good(3))
        c._extract_recalc_rows("p.png")
        assert c.started[0] == "vision", "the vision read starts first and runs alongside"
        assert "ocr" in c.started

    def test_a_clean_ocr_read_still_finishes_the_page_on_its_own(self) -> None:
        """The fast path must stay fast: a ledger that adds up and runs to the report's date
        is the whole ledger, and the page returns without waiting for the second opinion. The
        vision read here sleeps far longer than the test would tolerate if it were waited on.
        """
        import time
        text = "\n".join(
            f"{r['start']} {r['end']} {r['opening']:.2f} 1000.00 0.00 0.00 0.00 0.00 0.00 {r['closing']:.2f}"
            for r in self._good(3))
        c = self._client(ocr_text=text, vision_rows=self._good(99), vision_delay=30.0)
        from gpf.reading import recalc_text
        with self.mock.patch.object(recalc_text, "reaches_the_report_date", return_value=True):
            began = time.monotonic()
            rows, conf = c._extract_recalc_rows("p.png")
        assert time.monotonic() - began < 5, "the page did not wait for the vision read"
        assert len(rows) == 3 and conf == 0.97

    def test_and_where_the_ocr_read_is_no_good_the_vision_read_still_decides(self) -> None:
        c = self._client(ocr_text="", vision_rows=self._good(12))
        rows, _ = c._extract_recalc_rows("p.png")
        assert len(rows) == 12

    def test_a_vision_read_that_raises_leaves_the_ocr_read_standing(self) -> None:
        from gpf.clients.model_client import VllmModelClient
        c = VllmModelClient.__new__(VllmModelClient)
        text = "\n".join(
            f"{r['start']} {r['end']} {r['opening']:.2f} 1000.00 0.00 0.00 0.00 0.00 0.00 {r['closing']:.2f}"
            for r in self._good(4))
        c.ocr_table_text = lambda _r: (text, False)

        def boom(_r):
            raise RuntimeError("the vision server went away")

        c._recalc_rows_from_vision = boom
        rows, _ = c._extract_recalc_rows("p.png")
        assert len(rows) == 4
