"""Corpus fixtures — the case facts objects for the eight-case corpus (spec §16).

In production these are produced by pipeline stages 1-5 (a facts object per
case, each field with confidence, page and bbox). Here they are the
hand-transcribed fixtures the prototype ships, loaded from `cases.json`
(extracted verbatim from the prototype's `CASES[...]`). This is the contract
between reading and rules: a build that does not produce the spec §16.2 results
from these facts is not working.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

_DIR = Path(__file__).parent
# Order matches the prototype's ORDER (facts_order.js).
ORDER = ["fp-non-gazetted", "fp-death", "fp-dismissal", "missing-credits",
         "residual", "refundable", "non-refundable", "balance-transfer"]

with (_DIR / "cases.json").open(encoding="utf-8") as _f:
    CASES: dict[str, dict] = json.load(_f)


def load_case(key: str, *, without_sap: bool = False) -> dict:
    """Return a deep copy of a case's facts.

    `without_sap=True` models "received without its SAP pages": the SAP-dependent
    checks then wait (`sap`) instead of passing, exactly as in production before
    the section pulls the extract (spec §16.2).
    """
    F = copy.deepcopy(CASES[key])
    if without_sap:
        F["sap"] = None
    return F


def all_case_keys() -> list[str]:
    return [k for k in ORDER if k in CASES]
