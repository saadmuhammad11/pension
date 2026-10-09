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


def recalc_summary(recalc: Optional[dict]) -> Optional[dict]:
    if not recalc or not recalc.get("rows"):
        return None
    rows = recalc["rows"]
    last = rows[-1]
    temp_drawn = sum(r.get("tempAdvance") or 0 for r in rows)
    temp_rec = sum(r.get("recTempAdvance") or 0 for r in rows)
    return {"last": last, "tempDrawn": temp_drawn, "tempRec": temp_rec,
            "tempOutstanding": temp_drawn - temp_rec, "rows": rows}
