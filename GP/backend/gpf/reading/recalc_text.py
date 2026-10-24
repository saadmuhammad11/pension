"""The GPF Final Re-calculation ledger, read from the page's OCR text rather than transcribed.

23 Oct 2026. The ledger was read by one vision call asking the model to transcribe a table of
twenty-four years over ten columns as JSON, and it does not do it reliably. Two independent
reads of PC-2026-000070's page 6 were both wrong, in different ways: the first put the
Rs 80,000 advance a year early and shifted every closing balance after it; the second put the
figures a year off their dates and invented a final row. Thirteen and fourteen years out of
twenty-four did not add up. Everything on a GP Fund case rests on this table.

The same page read by the OCR model comes back right, row by row, because transcribing
characters is what it does: the 2008-09 row both vision reads mangled arrives exactly.
This module is the other half of that -- turning those lines into rows. It is the lesson
payslip_text.py already learned about the LOAN/FUND block, applied to the table that matters
most.

OCR is not clean either, and the point of this parser is that it does not have to be. Three
things go wrong on a real page, and the report's own arithmetic settles all three:

  * A repeated nil cell is dropped, or one is added. Seven of the twenty-four lines came back
    with seven numbers and one with nine, where eight is the row. Which columns the figures
    belong to is then decided by the only arrangement that balances.
  * A digit is misread. The 2004-05 line opens at "8,170.00" where the year before closes at
    8,270.00, and only 8,270.00 makes the row add up -- so the chain repairs it.
  * The OCR model falls into a loop and repeats a cell to the end of its budget. The last line
    of that page runs to 1,192 numbers and its closing balance is lost inside them. What the
    other columns make it is what it was.

Every repair is recorded on the row it was made to. A figure the office did not read is not
the same as a figure the office read, and the officer is told which is which.

WHAT THIS DOES NOT FIX, and what was measured before leaving it (24 Oct 2026). Over the
sixteen ledgers on the deployment machine this reader wins on two -- the pages the OCR model
transcribes whole -- and both of those now reconcile completely. On the rest the OCR model
falls into its loop early, the read is short, and the vision read is taken instead on row
count. Two things were tried and did not help:

  * Reading the page in horizontal bands, as extraction/identify.py does for headings. Three
    bands: the first gave twenty clean rows, the other two looped. Six narrow bands with a
    1,500-token cap: three of the six looped. The loop is set off by the content -- long runs
    of identical nil cells -- and not by how much of the page is in view.
  * Nothing was tried on the vision side, because there is nothing to try. The same page read
    three times running, temperature 0, gave four, one and seven years that did not add up.
    It is not stable, so there is no "better single read" to reach for.

What would work is reading two or three times and taking, year by year, only the version that
balances and chains -- each read gets DIFFERENT years wrong, and the arithmetic makes it safe
to choose between them rather than guess. It was costed at two to six more minutes an
examination and the office chose not to spend it for now: a ledger that does not reconcile is
a hard stop (rules_common.RECALC-ADDS-UP), so the figures reach nobody who could pay on them,
and the section re-pulls the report from SAP instead.
"""
from __future__ import annotations

import itertools
import re
from typing import Optional

from ..format import amount

#: A ledger line: two dates, then its figures. Anything else on the page is not a row.
ROW = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})(.*)")
#: A figure as SAP prints it: grouped, two decimals, a trailing minus for a debit.
NUMBER = re.compile(r"-?[\d,]+\.\d{2}-?|-?\d+-?")
#: The movement columns between the opening and closing balances, in the report's order.
MOVEMENTS = ("subscription", "adjustments", "tempAdvance", "recTempAdvance",
             "permanentAdvance", "interest")
#: Rupees a row may be out by and still balance (gpf.sap.RECALC_TOLERANCE is the same figure).
TOLERANCE = 1.0
#: A run of this many identical figures at the end of a line is the OCR model looping, not a
#: ledger. The longest honest row has eight figures, so anything near this is not one.
LOOP_RUN = 10


def _close(opening: float, moves: tuple, closing: float) -> bool:
    sub, adj, temp, rec, perm, interest = moves
    return abs(opening + sub + adj - temp + rec - perm + interest - closing) <= TOLERANCE


def _placements(middle: list[float]):
    """Every way the figures between the balances could fill the six movement columns.

    Order is kept -- a reader drops and inserts cells, it does not shuffle them -- so this is
    only a choice of WHICH columns are nil, and there are at most fifteen of those.
    """
    if len(middle) > len(MOVEMENTS):
        # More figures than columns: the reader added cells, and an added cell is a nil one.
        spare = [i for i, v in enumerate(middle) if v == 0]
        extra = len(middle) - len(MOVEMENTS)
        if len(spare) < extra:
            return
        for drop in itertools.combinations(spare, extra):
            keep = [v for i, v in enumerate(middle) if i not in set(drop)]
            yield tuple(keep)
        return
    for slots in itertools.combinations(range(len(MOVEMENTS)), len(middle)):
        row = [0.0] * len(MOVEMENTS)
        for slot, value in zip(slots, middle):
            row[slot] = value
        yield tuple(row)


def _trailing_run(values: list[float]) -> int:
    """How many identical figures the line ends on."""
    if not values:
        return 0
    n, last = 1, values[-1]
    for v in reversed(values[:-1]):
        if v != last:
            break
        n += 1
    return n


#: The columns a rule tests: an advance drawn, an advance recovered, a final payment. Which of
#: the others a figure landed in is not worth saying anything about -- a subscription read as
#: an adjustment changes no decision, and both balance.
DECIDING = (MOVEMENTS.index("tempAdvance"), MOVEMENTS.index("recTempAdvance"),
            MOVEMENTS.index("permanentAdvance"))


def _solve(opening: float, middle: list[float], closing: float):
    """The arrangement of the movement columns that makes the row add up, if there is one.

    The arrangements are tried leftmost-first, which is how the table reads: the figure after
    the opening balance is the subscription unless the arithmetic says otherwise. Where more
    than one balances, the row is marked only if they disagree about an advance -- that is the
    one disagreement that could change what the office decides.
    """
    fits = [p for p in _placements(middle) if _close(opening, p, closing)]
    if not fits:
        return None, False
    ambiguous = any(any(fits[0][i] != other[i] for i in DECIDING) for other in fits[1:])
    return fits[0], ambiguous


def parse_recalc_rows(text: str) -> list[dict]:
    """The ledger's rows, read off the page's OCR text, with every repair recorded."""
    rows: list[dict] = []
    for line in (text or "").splitlines():
        m = ROW.search(line)
        if not m:
            continue
        figures = [amount(x) or 0.0 for x in NUMBER.findall(m.group(3))]
        if len(figures) < 3:
            continue
        repairs: list[str] = []

        looping = _trailing_run(figures) >= LOOP_RUN
        if looping:
            run = _trailing_run(figures)
            figures = figures[:len(figures) - run]
            repairs.append("a repeated figure ran to the end of the line and was cut")

        previous = rows[-1]["closing"] if rows else None
        opening, closing = figures[0], figures[-1]
        middle = figures[1:-1]

        moves, ambiguous = _solve(opening, middle, closing)
        # The year before it closed where this one opens. Where the line disagrees and the
        # chain makes the row add up, the line misread a digit (8,170 for 8,270).
        if moves is None and previous is not None:
            chained, chained_ambiguous = _solve(previous, middle, closing)
            if chained is not None:
                opening, moves, ambiguous = previous, chained, chained_ambiguous
                repairs.append(f"opening taken from the year before ({previous:,.0f}), which is "
                               f"the only figure that makes the row add up")
        if moves is None and looping:
            # The closing was swallowed by the run and is nowhere on the page. What the other
            # columns make it is what it was.
            middle = [v for v in figures[1:] if v]
            moves = tuple(list(middle)[:len(MOVEMENTS)] + [0.0] * (len(MOVEMENTS) - len(middle)))
            opening = figures[0]
            sub, adj, temp, rec, perm, interest = moves
            closing = opening + sub + adj - temp + rec - perm + interest
            repairs.append("closing balance computed from the other columns; the figure itself "
                           "was lost in the repeated run")
        if moves is None:
            # Nothing balances. The row is kept as read, positionally, and gpf.sap's check
            # will say so: a row nobody can make sense of is not one to quietly mend.
            padded = (middle + [0.0] * len(MOVEMENTS))[:len(MOVEMENTS)]
            moves = tuple(padded)
            repairs.append("the row does not add up however its columns are arranged")
        elif ambiguous:
            repairs.append("more than one arrangement of the columns adds up")

        row = {"start": m.group(1), "end": m.group(2), "opening": opening, "closing": closing}
        row.update(dict(zip(MOVEMENTS, moves)))
        if repairs:
            row["repairs"] = repairs
        rows.append(row)
    return rows


def parse_recalc(text: str) -> Optional[dict]:
    """The report as the case holds it, or None where the page carries no ledger."""
    rows = parse_recalc_rows(text)
    if not rows:
        return None
    out: dict = {"rows": rows, "read": "ocr-text"}
    head = re.search(r"EMPLOYEE\s+NUMBER\s*:?\s*(\d+)", text or "", re.I)
    if head:
        out["persNo"] = head.group(1)
    date = re.search(r"(\d{2}\.\d{2}\.\d{4})\s+\w*PR[FP]", text or "")
    if date:
        out["reportDate"] = date.group(1)
    return out
