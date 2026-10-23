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

from .format import amount, digits, num

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
                        "end": row.get("end"), "expected": want, "found": got})
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
