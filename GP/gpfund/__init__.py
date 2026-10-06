"""GP Fund AI pre-audit module for the Office of the Accountant General, Punjab.

Built to ``GP-FUND-AI-MODULE-BUILD-SPEC.md`` revision 2 (15-09-2026), which is the handover
document in ``GP/agofficegpfund/instructions/``. Where that document and the HTML prototype
beside it disagree, the document wins (its §0).

Governing authority, in the order the specification sets:

1. Office Circular No. G.P. Fund-I (Coord)/TR/127 of 21.12.2023 -- checklists A.1 to A.4,
   rejection reasons B1 and B2, the single-instance rule.
2. The Punjab General Provident Fund Rules 1978, Compendium 2008 -- advance limits, final
   payment, nominations, missing credits.
3. The clarifications the AG Punjab office gave on 15-09-2026, R1 to R15.

What is here is the part of the module that needs no model: phases 1 to 4 of the build order
at §19. The reading stage (§3 stages 1 to 5) produces a facts object; everything in this
package turns facts into results, deterministically.

    from gpfund import load_corpus_case, evaluate, lists

    facts = load_corpus_case("refundable")
    results = evaluate(facts)
    print(lists(results).counts())

The one rule that governs every module in this package, from §0 of the specification:

    The language model never decides anything. It reads. The rules decide, from facts.

So: no model call, no network, no clock and no randomness anywhere below this line. The same
facts and the same rule set produce the same results forever, which is what lets the office
re-check a case against the rules in force when it was examined (§15).
"""

from __future__ import annotations

from .contracts import (
    ADV,
    CONF,
    HARD,
    NA,
    OK,
    SAP,
    STATUSES,
    SUB,
    Evidence,
    Facts,
    Lists,
    Result,
    blocks_payment,
    is_issue,
)
from .corpus import CORPUS_ORDER, load_corpus_case
from .engine import RULE_SET_VERSION, checks_for, diff_runs, evaluate, lists
from .qr import Payload, format_cnic, parse_code, parse_payload, route_for

__all__ = [
    "ADV", "CONF", "HARD", "NA", "OK", "SAP", "SUB", "STATUSES",
    "Evidence", "Facts", "Lists", "Result",
    "blocks_payment", "is_issue",
    "CORPUS_ORDER", "load_corpus_case",
    "RULE_SET_VERSION", "checks_for", "diff_runs", "evaluate", "lists",
    "Payload", "format_cnic", "parse_payload", "parse_code", "route_for",
]
