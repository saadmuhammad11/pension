"""Run the module over a corpus case from the command line.

    python3 -m gpfund                       every case, four numbers each
    python3 -m gpfund refundable            one case, every check
    python3 -m gpfund refundable --no-sap   the same case as received without its SAP pages
    python3 -m gpfund refundable --pack     the issue pack, as JSON
    python3 -m gpfund --catalogue           every registered check, by group

No GPU, no network, no clock: this is the decision layer, and it runs anywhere Python does.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import rules                                                        # noqa: F401
from .casefile import CaseFile
from .contracts import ADV, CONF, HARD, NA, OK, SAP, SUB
from .corpus import CORPUS_ORDER, load_corpus_case
from .disposal import issue_pack, recalc_breaks
from .engine import RULE_SET_VERSION, evaluate, lists
from .rules import catalogue

_MARK = {OK: "ok", SUB: "sub", HARD: "HARD", ADV: "obs", CONF: "verify", SAP: "sap", NA: "n/a"}


def _summary() -> int:
    print(f"GP Fund pre-audit — {RULE_SET_VERSION['module']}, "
          f"rule set: {RULE_SET_VERSION['office_clarifications']}\n")
    print(f"{'case':<20}{'hard':>6}{'obs':>6}{'verify':>8}{'sap':>6}   report")
    for slug in CORPUS_ORDER:
        facts = load_corpus_case(slug)
        counts = lists(evaluate(facts)).counts()
        case = CaseFile(facts, by="cli", desk="AO", at="-")
        breaks = recalc_breaks(case)
        note = ("reconciles" if facts.recalc_rows and not breaks
                else f"{len(breaks)} row(s) do not add up" if breaks else "no report")
        print(f"{slug:<20}{counts['hard']:>6}{counts['adv']:>6}"
              f"{counts['conf']:>8}{counts['sap']:>6}   {note}")
    return 0


def _one_case(slug: str, without_sap: bool, as_pack: bool) -> int:
    try:
        facts = load_corpus_case(slug)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        return 2
    if without_sap:
        facts = facts.without_sap()

    if as_pack:
        case = CaseFile(facts, by="cli", desk="AO", at="-")
        print(json.dumps(issue_pack(case), indent=1, ensure_ascii=False))
        return 0

    results = evaluate(facts)
    found = lists(results)
    print(f"{facts.label} — {facts.data.get('subject')}")
    print(f"{facts.data.get('dept')}")
    print(f"personnel no. {facts.personnel_no}, {facts.gazetted}, "
          f"{'no SAP extracts' if without_sap else 'SAP extracts present'}\n")
    for result in results:
        print(f"  {_MARK[result.status]:<7}{result.id:<26}{result.finding[:96]}")
    print(f"\n  hard {len(found.hard)}   observations {len(found.advisory)}   "
          f"verification tasks {len(found.verifications)}   SAP items {len(found.sap)}")
    print(f"  may pass for payment: {found.may_pass_for_payment}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gpfund", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case", nargs="?", help=f"one of: {', '.join(CORPUS_ORDER)}")
    parser.add_argument("--no-sap", action="store_true",
                        help="as received without the SAP pages (specification §16.2)")
    parser.add_argument("--pack", action="store_true", help="print the issue pack as JSON")
    parser.add_argument("--catalogue", action="store_true",
                        help="print every registered check, by group")
    args = parser.parse_args(argv)

    if args.catalogue:
        for group, ids in sorted(catalogue().items()):
            print(f"{group} ({len(ids)})")
            for check_id in ids:
                print(f"    {check_id}")
        return 0
    if not args.case:
        return _summary()
    return _one_case(args.case, args.no_sap, args.pack)


if __name__ == "__main__":
    raise SystemExit(main())
