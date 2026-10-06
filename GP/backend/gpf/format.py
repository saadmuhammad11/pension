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
    """Parse a loose numeric string (commas, spaces, trailing '/-') to a number.

    Returns None when empty or not a number. Mirrors sap.js `num`.
    """
    if v is None:
        return None
    s = str(v).replace(",", "").replace(" ", "")
    s = re.sub(r"/-$", "", s)
    s = re.sub(r"-$", "", s)
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


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
