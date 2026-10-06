"""The fund and advance balances printed in a SAP pay slip's LOAN/FUND block. 30 Sep 2026.

The printed pay slip puts them in a small table beside the deductions:

    LOAN/FUND        PRINCIPAL   REPAID      BALANCE
    GPF#:                                    255,534.00
    GPF ADV          60,000.00   4,000.00    56,000.00

Read from the page's OCR text (exact digits) rather than by the vision model, which passed over
the block. Deliberately narrow: "GPF Subscription 1,150.00-" in the deductions is a deduction, not
the fund, and must never be taken for it.
"""
from __future__ import annotations

import re

_NUM = r"(\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
#: The fund row: "GPF#: 255,534.00", "GPF # 255534", "G.P.Fund: 1,234.00" -- a label, then the balance.
_FUND = re.compile(r"\bG\.?\s*P\.?\s*F(?:UND)?\s*(?:#|NO\.?)\s*:?\s*" + _NUM + r"(?!\s*-)", re.I)
#: An advance row: "GPF ADV", "GPF Advance", "GPF Loan", "GPF Temp Adv" -- then principal, repaid, balance.
_ADV = re.compile(r"\bG\.?\s*P\.?\s*F(?:UND)?\s*(?:TEMP\w*\s*)?(?:ADV\w*|LOAN)\b[^\n\d]{0,20}"
                  + _NUM + r"\s+" + _NUM + r"\s+" + _NUM, re.I)
_BLOCK = re.compile(r"LOAN\s*/\s*FUND", re.I)


def _n(text: str) -> float:
    return float(text.replace(",", ""))


def fund_block(text: str) -> dict:
    """``{"gpf_balance": float|None, "gpf_loan_balance": float|None}`` from a pay slip's OCR text.

    The loan balance is 0 where the LOAN/FUND block is printed and has no GPF advance row: the slip
    then says, by omission, that no advance is being recovered. Without the block, both stay None.
    """
    out: dict = {"gpf_balance": None, "gpf_loan_balance": None}
    if not text:
        return out
    fund = _FUND.search(text)
    if fund:
        out["gpf_balance"] = _n(fund.group(1))
    adv = _ADV.search(text)
    if adv:
        out["gpf_loan_balance"] = _n(adv.group(3))
    elif _BLOCK.search(text) and fund:
        out["gpf_loan_balance"] = 0.0
    return out
