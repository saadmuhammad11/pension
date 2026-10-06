"""Check registry and shared result helpers.

A *check* is a pure function of the case facts. It carries a stable id, the
circular/rule reference, and the code that prints on the rejection form. Its
run() returns one result dict, or a list of result dicts (each carrying a
`sub` key so it keeps a stable id across reprocessing).

Checks register themselves at import time via `check(...)`. Case-specific
anomalies register into CUSTOM_CHECKS and are attached to a case by its facts
(`F["custom"]`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

CHECKS: list["Check"] = []
CUSTOM_CHECKS: dict[str, "Check"] = {}


@dataclass
class Check:
    id: str
    run: Callable[[dict], Any]
    applies: Callable[[dict], bool] = lambda F: True
    group: Optional[str] = None
    ref: Optional[str] = None
    code: Optional[str] = None
    title: Optional[str] = None
    checklist: Any = None  # str, or callable(F)->str, or None


def check(*, custom_id: Optional[str] = None, **kw) -> Check:
    """Register a check. If custom_id is given, store in CUSTOM_CHECKS instead."""
    c = Check(**kw)
    if custom_id is not None:
        CUSTOM_CHECKS[custom_id] = c
    else:
        CHECKS.append(c)
    return c


# ── verification helpers (an officer's recorded decision becomes a fact) ──────
def verified(F: dict, vid: str):
    return (F.get("verifications") or {}).get(vid)


def verified_result(v: dict, ok_text: str, bad_text: str) -> dict:
    note = (": " + v["note"]) if v.get("note") else "."
    if v.get("ok"):
        return {"status": "ok",
                "finding": f"{ok_text} Verified by {v['by']} ({v['desig']}) on {v['at']}{note}"}
    return {"status": "hard",
            "finding": f"{bad_text} Recorded by {v['by']} ({v['desig']}) on {v['at']}{note}"}
