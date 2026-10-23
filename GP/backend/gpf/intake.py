"""What the department is asked to attach, per kind of claim, read off the checks themselves.

A pension case shows the documents its type requires as soon as the type is chosen, taken from
the very requirements the checklist is run on (rules.checklist.requirements_for). The GP Fund
module published no such list, so its filing screen could only say "attach every page of the
claim" and the department found out what was missing when the claim came back (23 Oct 2026).

A check does not declare which kinds it serves -- ``applies`` is a function of the case facts --
so the list is read the way the engine reads it, by asking each check whether it applies. It is
asked against facts carrying the SHAPE of a claim of that kind and none of its particulars:

  * ``Present`` is a document block the claim has by definition, nothing yet known about it: a
    death claim has a death block. It answers yes to "is there one?" and no to every question
    about what is in it, which is what an unread claim looks like.
  * ``Anything`` answers yes to everything. An item that applies only to those facts is one the
    department supplies WHEN IT APPLIES -- the widow's affidavit on a death claim -- and is
    listed apart, because asking every family for an affidavit is how a checklist stops being
    read.

Only a check carrying a ``checklist`` code is a paper the department attaches. The rest of the
group are checks ABOUT a paper already listed -- that the sanction quotes its rule, that the
form is signed by the DDO -- and listing them would ask for the same paper twice under two
names. The code is the item in the office's own circular (A.1 advances, A.2 final payment,
A.3 balance transfer, A.4 missing credits), so the list reads in the order the circular does.

Derived, never written down twice: a check added to the engine appears here without being
copied, and one whose wording changes cannot say one thing to the department and another to
the officer.
"""
from __future__ import annotations

import re
from typing import Any

from .format import ADVANCES, FINALS
from .registry import CHECKS

#: The document blocks a claim of a kind has by definition, before a page has been read.
#: Only what the kind IS belongs here -- never a paper the department might or might not send,
#: which is what the generous facts below are for.
SHAPE: dict[str, tuple[str, ...]] = {"death": ("death",)}

_ITEM = re.compile(r"^([A-Z]\d+)-([ivxl]+)$", re.I)
_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50}


class Present(dict):
    """A block the claim has, with nothing known about its contents."""

    def __bool__(self) -> bool:
        return True


class Anything(dict):
    """Facts that answer yes to every question, to find the conditional items."""

    def get(self, k: Any, default: Any = None) -> "Anything":
        return Anything()

    def __getitem__(self, k: Any) -> "Anything":
        return Anything()

    def __bool__(self) -> bool:
        return True


def _roman(s: str) -> int:
    total, prev = 0, 0
    for ch in reversed(s.lower()):
        v = _ROMAN.get(ch, 0)
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def _order(item: str) -> tuple[str, int, str]:
    """A checklist code in the circular's order: A2-v after A2-iv, not before it."""
    m = _ITEM.match(item or "")
    return (m.group(1), _roman(m.group(2)), "") if m else (item or "~", 0, item or "")


def _facts(kind: str, gazetted: str) -> dict:
    docs = {name: Present() for name in SHAPE.get(kind, ())}
    return {"kind": kind, "gazetted": gazetted, "docs": docs, "sap": {}, "claim": {}}


def _generous(kind: str, gazetted: str) -> dict:
    return {"kind": kind, "gazetted": gazetted, "docs": Anything(), "sap": Anything(), "claim": Anything()}


def _applies(check: Any, F: dict) -> bool:
    """Whether this check would run. A check that cannot tell is not listed: the engine turns
    that into an observation the officer sees (H-16), which is the right place for it -- a
    department reading the filing screen can do nothing with "the office is not sure"."""
    try:
        return bool(check.applies(F))
    except Exception:
        return False


def _code(check: Any, F: dict) -> str:
    item = check.checklist
    if callable(item):
        try:
            item = item(F)
        except Exception:
            return ""
    return str(item or "")


def checklist_for(kind: str, gazetted: str = "unknown") -> list[dict]:
    """The papers a claim of this kind is checked for, in the circular's order."""
    plain, rich = _facts(kind, gazetted), _generous(kind, gazetted)
    out = []
    for check in CHECKS:
        if check.group != "checklist":
            continue
        item = _code(check, plain)
        if not item:
            continue
        always = _applies(check, plain)
        if not always and not _applies(check, rich):
            continue
        out.append({"id": check.id, "item": item, "requirement": check.title or check.id,
                    "always": always})
    out.sort(key=lambda r: (_order(r["item"]), r["requirement"]))
    return out


#: Every kind of claim the checks know. The labels a department reads are the portal's
#: (api/gpf_bridge.KINDS), which offers the kinds it lets a DDO file -- a residual claim is
#: raised by the office on a final payment, not filed, so it is here and not there.
KINDS: tuple[str, ...] = (*ADVANCES, *FINALS, "missing_credits", "balance_transfer")


def checklists(gazetted: str = "unknown") -> dict[str, list[dict]]:
    """Every kind with its papers, so a screen can let the officer change kind without asking
    again. Keyed by kind and unlabelled: what a kind is called is the portal's business."""
    return {k: checklist_for(k, gazetted) for k in KINDS}
