"""GP Fund AI pre-audit module — deterministic rules engine (Phase 1).

    scan -> [READ: vision model] -> facts -> [RULES ENGINE: plain code] -> results

This package is the RULES ENGINE half: ordinary, unit-tested, versioned code
with no model calls (spec §0). Importing it registers the full rule catalogue.
The reading half plugs in behind `gpf.clients` when the DGX Spark is online.
"""
from __future__ import annotations

# Importing the rule modules registers every check into the registry.
from . import rules_common, rules_family, rules_custom  # noqa: F401
from .engine import (CaseState, OFFICERS, diff_runs, evaluate, lists, may,
                     new_state, position, run_case, who_can)
from .registry import CHECKS, CUSTOM_CHECKS

__all__ = [
    "evaluate", "lists", "diff_runs", "run_case", "position", "new_state",
    "CaseState", "OFFICERS", "may", "who_can", "CHECKS", "CUSTOM_CHECKS",
]
