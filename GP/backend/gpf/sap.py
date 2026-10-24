"""SAP extract parsing and validation.

Faithful port of the parsing half of sap.js. The MVP accepts a text export in
the agreed layout (tabs or pipes) or a JSON payload; a PDF/image of the SAP
screen would instead run stages 1-4 of the reading pipeline. An extract whose
personnel number differs from the case is rejected (spec §6.1).
"""
from __future__ import annotations

import json
import re
from typing import Optional

from .format import amount, digits, fmt, num

PAYSLIP_KEYS = {
    "personnel no": "persNo", "pers no": "persNo", "name": "name", "designation": "designation",
    "cnic": "cnic", "month": "month", "bps": "bps", "ddo code": "ddoCode", "gpf no": "gpfNo",
    "old gpf no": "oldGpfNo", "gpf balance": "gpfBalance", "gpf subscription": "gpfSubscription",
    "gpf loan instalment": "loanInstalment", "gpf loan balance": "loanBalance", "osd post": "osdPost",
    "employment status": "status", "bank": "bank", "basic pay": "basicPay",
}
RECALC_COLS = ["start", "end", "opening", "subscription", "adjustments", "tempAdvance",
               "recTempAdvance", "permanentAdvance", "interest", "closing"]
#: Balances keep SAP's sign (a trailing minus is a debit); the rest are magnitudes (review C1, 9 Oct 2026).
_SIGNED_KEYS = ("gpfBalance", "loanBalance")
_AMOUNT_KEYS = ("gpfSubscription", "loanInstalment", "basicPay")
_NUM_KEYS = _SIGNED_KEYS + _AMOUNT_KEYS
#: Re-calculation report columns: opening, closing and adjustments carry a sign; the movements are magnitudes.
_SIGNED_COLS = ("opening", "closing", "adjustments")


def parse_sap_text(text: str) -> dict:
    out = {"payslip": None, "recalc": None, "warnings": []}
    section = None
    cur = None
    for raw in re.split(r"\r?\n", text):
        line = raw.strip()
        if not line:
            continue
        head = line.upper()
        if head.startswith("SAP EXTRACT:"):
            if "PAY SLIP" in head:
                section = "payslip"
                cur = out["payslip"] = {}
            elif "RE-CALCULATION" in head or "RECALCULATION" in head:
                section = "recalc"
                cur = out["recalc"] = {"rows": []}
            else:
                section = None
                out["warnings"].append("Unrecognised section: " + line)
            continue
        if not section:
            continue
        cells = [c.strip() for c in re.split(r"\t|\|", line)]
        if section == "recalc" and len(cells) >= 10:
            if re.search(r"start", cells[0], re.I):
                continue  # header row
            r = {}
            for i, k in enumerate(RECALC_COLS):
                r[k] = cells[i] if i < 2 else (num(cells[i]) if k in _SIGNED_COLS else amount(cells[i]))
            cur["rows"].append(r)
            continue
        m = re.match(r"^([^:]+):\s*(.*)$", line)
        if not m:
            continue
        key = m.group(1).strip().lower()
        val = m.group(2).strip()
        if section == "payslip":
            k = PAYSLIP_KEYS.get(key)
            if not k:
                out["warnings"].append("Ignored pay slip line: " + line)
                continue
            cur[k] = (num(val) if k in _SIGNED_KEYS else amount(val)) if k in _NUM_KEYS else val
        else:
            if key == "personnel no":
                cur["persNo"] = val
            elif key == "gpf reference no":
                cur["gpfRef"] = val
            elif key == "report date":
                cur["reportDate"] = val
            elif key == "name":
                cur["name"] = val
    return out


def parse_sap_file(name: str, text: str) -> dict:
    t = text.strip()
    if t.startswith("{"):
        j = json.loads(t)
        return {"payslip": j.get("payslip"), "recalc": j.get("recalc"), "warnings": []}
    return parse_sap_text(t)


def check_sap_against_case(ex: dict, F: dict) -> list[str]:
    """Validate an extract against the case before it is accepted (identity gate)."""
    issues = []
    want = digits(F.get("personnelNo"))
    for label, part in (("pay slip", ex.get("payslip")), ("re-calculation report", ex.get("recalc"))):
        if not part:
            continue
        got = digits(part.get("persNo"))
        if not got:
            issues.append("The " + label + " carries no personnel number.")
        elif want and got != want:
            issues.append("The " + label + " is for personnel no. " + str(part.get("persNo"))
                          + ", not " + str(F.get("personnelNo")) + ". It belongs to a different employee.")
    return issues


#: Rupees a row may be out by and still be called right: the report prints whole rupees, so
#: anything above this is a figure read wrongly, not a rounding.
RECALC_TOLERANCE = 1.0


def _n(row: dict, key: str) -> float:
    v = row.get(key)
    return float(v) if isinstance(v, (int, float)) else 0.0


def row_should_close_at(row: dict) -> float:
    """What a year's closing balance has to be, from the year's own movements.

    The report's columns are an equation, and it is the only check on the reading that needs
    nothing but the page itself: the fund is opened, subscribed to and credited with interest,
    an advance drawn comes out of it and a recovery goes back in.
    """
    return (_n(row, "opening") + _n(row, "subscription") + _n(row, "adjustments")
            - _n(row, "tempAdvance") + _n(row, "recTempAdvance")
            - _n(row, "permanentAdvance") + _n(row, "interest"))


#: Each movement column's sign in the equation above. A year that does not close is out by
#: some amount, and any one of these cells, read wrongly, would put it out by exactly that --
#: which is what lets the arithmetic name the cell to look at.
_MOVEMENTS = {"subscription": 1, "adjustments": 1, "tempAdvance": -1,
              "recTempAdvance": 1, "permanentAdvance": -1, "interest": 1}

#: What the columns are called on the page, for a finding an officer reads.
COLUMN_WORDS = {"opening": "opening balance", "subscription": "subscription",
                "adjustments": "adjustment", "tempAdvance": "temporary advance drawn",
                "recTempAdvance": "temporary advance recovered",
                "permanentAdvance": "permanent advance", "interest": "interest",
                "closing": "closing balance"}


def _one_digit_apart(a: float, b: float) -> bool:
    """Same number of digits, differing in exactly one place: 426 and 826, 37 and 97.

    This is what a misread does to a printed figure. A reader that loses a column or a row
    produces something else entirely, and that is caught by the chain rather than here.
    """
    x, y = str(int(a)), str(int(b))
    return len(x) == len(y) and sum(p != q for p, q in zip(x, y)) == 1


def explain_row(rows: list[dict], i: int) -> dict:
    """Which cell of a year that does not add up would account for it (24 Oct 2026).

    A year is ten figures and an equation between them, and when it does not close the hard
    stop could say only that the table had been read wrongly -- all thirty-one years of it,
    for eight bad ones. But the equation knows more than that. Where the year opens exactly
    where the one before it closed, and the one after opens exactly where it closes, those two
    figures are each confirmed twice and the error is in a movement column. There is then an
    amount the row is out by, and for each movement column one value that would close it.

    Two kinds of candidate are worth putting to an officer:

    * a figure ONE DIGIT from the one that was read -- 426 against 826 -- which is what a
      misread looks like, and is strong enough to name;
    * a column read as nil that would have to hold the amount. The report is mostly nil and
      that is precisely what defeats the reader, so this is common; but several nil columns
      are equally possible arithmetically and the check does not pretend to choose between
      them. It says the amount and lists them.

    Nothing is corrected. The page is the authority and the officer reads it; this only says
    where to look, so a thirty-one year stop becomes four cells to glance at.
    """
    row = rows[i]
    out: dict = {"delta": _n(row, "closing") - row_should_close_at(row), "chain": True,
                 "oneDigit": [], "readAsNil": []}
    opening_confirmed = i == 0 or abs(_n(row, "opening") - _n(rows[i - 1], "closing")) <= RECALC_TOLERANCE
    closing_confirmed = (i == len(rows) - 1
                         or abs(_n(rows[i + 1], "opening") - _n(row, "closing")) <= RECALC_TOLERANCE)
    if not (opening_confirmed and closing_confirmed):
        # The two balances do not agree with their neighbours, so they are in doubt too and
        # there is no fixed amount to attribute to a movement column.
        out["chain"] = False
        return out
    for col, sign in _MOVEMENTS.items():
        read = _n(row, col)
        needed = read + out["delta"] / sign
        if needed < 0 or abs(needed - round(needed)) > 0.001:
            continue                                   # no negative amounts, whole rupees only
        needed = float(round(needed))
        if read and _one_digit_apart(read, needed):
            out["oneDigit"].append({"column": col, "read": read, "needed": needed})
        elif not read and needed:
            out["readAsNil"].append({"column": col, "needed": needed})
    return out


def explain_in_words(rows: list[dict], i: int) -> str:
    """``explain_row`` as the sentence that goes under the finding, or "" if it has nothing."""
    e = explain_row(rows, i)
    if not e["chain"]:
        return ""
    if e["oneDigit"]:
        parts = [COLUMN_WORDS[c["column"]] + " reads Rs " + fmt(c["read"])
                 + " where Rs " + fmt(c["needed"]) + " would close the year" for c in e["oneDigit"]]
        lead = ("One figure is a digit out: " if len(parts) == 1
                else "One of these is a digit out: ")
        return lead + "; ".join(parts) + "."
    if e["readAsNil"]:
        amount = fmt(abs(e["delta"]))
        cols = ", ".join(COLUMN_WORDS[c["column"]] for c in e["readAsNil"])
        return ("The year is out by Rs " + amount + " and its balances both agree with the years "
                "either side, so a figure of Rs " + amount + " was read as nil in one of these "
                "columns: " + cols + ".")
    return ""


def recalc_discrepancies(recalc: Optional[dict]) -> list[dict]:
    """The years of a re-calculation report that do not add up, and the breaks in its chain.

    Added 23 Oct 2026, after PC-2026-000070. The report is a table of ten columns, several of
    them nil down most of their length, and the reader lost its place in them: on that claim
    thirteen of twenty-four years did not add up, an advance of Rs 80,000 sat against the wrong
    year, and the last year closed at nil when the balance was Rs 883,646. Nothing noticed. The
    examination ran on those figures, the balance tests with them, and the case reached the
    officer reading as though the report had been understood.

    A misread ledger is not a rare event to be designed around later: it is what a sparse
    printed table does to a reader. The page carries its own proof and this is it.
    """
    rows = (recalc or {}).get("rows") or []
    out: list[dict] = []
    for i, row in enumerate(rows):
        want = row_should_close_at(row)
        got = _n(row, "closing")
        # The last year of a report struck for payment shows the interest computed to the date
        # of payment WITHOUT crediting it to the closing balance -- fp-dismissal closes at its
        # own opening with Rs 2,239 interest beside it, and the residual case is out by exactly
        # its Rs 20,807. Every other year on every fixture credits it, and so does the last year
        # where the payout itself is in the report (fp-non-gazetted draws Rs 74,178 through the
        # permanent advance column and balances). So the carve-out is this one row and this one
        # amount, and it is narrow on purpose: PC-2026-000070's last year is out by Rs 883,646
        # against nil interest and is still caught.
        last_year_interest_not_credited = (
            i == len(rows) - 1 and abs(want - _n(row, "interest") - got) <= RECALC_TOLERANCE)
        if abs(want - got) > RECALC_TOLERANCE and not last_year_interest_not_credited:
            out.append({"row": i + 1, "kind": "does-not-add-up", "start": row.get("start"),
                        "end": row.get("end"), "expected": want, "found": got,
                        # Which cell to look at, where the arithmetic can say (24 Oct 2026).
                        "cell": explain_row(rows, i), "says": explain_in_words(rows, i)})
        # Each year opens where the year before it closed. A reader that drops a figure keeps
        # the chain intact while shifting every row after it, so this catches what the sum
        # above does not and the sum catches what this does not; both are cheap.
        if i and abs(_n(row, "opening") - _n(rows[i - 1], "closing")) > RECALC_TOLERANCE:
            out.append({"row": i + 1, "kind": "does-not-follow-on", "start": row.get("start"),
                        "end": row.get("end"), "expected": _n(rows[i - 1], "closing"),
                        "found": _n(row, "opening")})
    return out


def recalc_summary(recalc: Optional[dict]) -> Optional[dict]:
    if not recalc or not recalc.get("rows"):
        return None
    rows = recalc["rows"]
    last = rows[-1]
    temp_drawn = sum(r.get("tempAdvance") or 0 for r in rows)
    temp_rec = sum(r.get("recTempAdvance") or 0 for r in rows)
    return {"last": last, "tempDrawn": temp_drawn, "tempRec": temp_rec,
            "tempOutstanding": temp_drawn - temp_rec, "rows": rows}
