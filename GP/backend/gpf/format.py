"""Shared helpers: number/string normalisation and small predicates.

Faithful port of the helper functions scattered through the prototype
(sap.js, rules_common.js, rules_family.js). Nothing here reads an image
or calls a model.
"""
from __future__ import annotations

import re
from typing import Any

FINALS = ("final", "death", "dismissal", "residual")
ADVANCES = ("refundable", "nonrefundable")


def num(v: Any):
    """Parse a loose numeric string (commas, spaces, trailing '/-') to a signed number.

    Returns None when empty, not a number, or signed twice ("-1,234-"). Mirrors sap.js `num`.
    SAP prints a debit with a trailing minus ("1,234.00-"): that is a negative figure, not 1,234
    (audit 6 Oct 2026, G3); "1,234/-" is the rupee sign-off and positive. Use this for a BALANCE
    or a closing figure, where the sign carries meaning; a subscription, an instalment or an
    amount is a magnitude -- read those with ``amount()`` (9 Oct 2026, review C1: a deduction
    printed "GPF Subscription 1,150.00-" is Rs 1,150 deducted, not a negative subscription).
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else v
    s = str(v).replace(",", "").replace(" ", "")
    s = re.sub(r"/-$", "", s)
    trailing = s.endswith("-")
    if trailing:
        s = s[:-1]
    leading = s.startswith("-")
    if leading and trailing:
        return None                                   # "-1,234-": signed twice, not a figure
    if leading:
        s = s[1:]
    if s == "" or s.startswith("-") or s.endswith("-"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    if trailing or leading:
        f = -f
    return int(f) if f.is_integer() else f


def amount(v: Any):
    """A magnitude: ``num()`` without its sign. For subscriptions, instalments, advances and
    claimed amounts, where SAP's deduction minus (or an OCR that lost the slash of "50,000/-")
    must not turn the figure negative. None stays None."""
    n = num(v)
    return None if n is None else abs(n)


def fmt(n: Any) -> str:
    """Group a number with thousands separators (display only). Mirrors `fmt`."""
    if n is None:
        return ""
    try:
        val = float(n)
    except (TypeError, ValueError):
        return ""
    if val != val:  # NaN
        return ""
    return f"{int(round(val)):,}"


def digits(v: Any) -> str:
    """Keep only the digits of a value. Mirrors `digits`."""
    return re.sub(r"\D", "", str(v if v is not None else ""))


def name_key(n: Any) -> str:
    s = str(n if n is not None else "").lower()
    s = re.sub(r"\b(mr|mrs|ms|mst|miss|dr)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def same_name(a: Any, b: Any):
    """Tri-state name comparison. Returns True/False/None (unknown). Mirrors `sameName`."""
    x, y = name_key(a), name_key(b)
    if not x or not y:
        return None
    return x == y or x in y or y in x


def yes(v: Any) -> bool:
    return v is True or v == "yes"


def KIND(F: dict, *kinds: str) -> bool:
    return F.get("kind") in kinds


def D(F: dict) -> dict:
    return F.get("docs") or {}


def ev(page, label=None, crop=None, bbox=None) -> dict:
    return {"page": page, "label": label, "crop": crop, "bbox": bbox}
