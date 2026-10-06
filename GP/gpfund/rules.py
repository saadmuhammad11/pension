"""Loads the whole rule catalogue, in the order §5 sets it out.

Importing this module registers every check. ``gpfund/__init__.py`` imports it, so any caller
that reaches the engine has the full catalogue -- a partially loaded catalogue would evaluate
a case against fewer rules than the office expects, and a case with rules missing looks
exactly like a clean case.
"""

from __future__ import annotations

from . import rules_common          # §5.1  across families                          # noqa: F401
from . import rules_advances        # §5.2  refundable and non-refundable            # noqa: F401
from . import rules_final           # §5.3  final payments, death, dismissal         # noqa: F401
from . import rules_missing_credits # §5.4, §5.5  missing credits, balance transfer  # noqa: F401
from . import rules_statutory       # §5.3  the statutory guard on R13               # noqa: F401
from . import rules_custom          # §5    case-specific checks                     # noqa: F401
from .engine import CHECKS, CUSTOM_CHECKS


def catalogue() -> dict[str, list[str]]:
    """Every registered check id, by group. For the office record and the §17 harness."""
    out: dict[str, list[str]] = {}
    for entry in CHECKS:
        out.setdefault(entry.group, []).append(entry.id)
    out["case-specific"] = sorted(CUSTOM_CHECKS)
    return out
