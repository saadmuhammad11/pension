"""See the engine work: evaluate a case and print its four lists (spec §13.1).

    python demo.py                # list the cases
    python demo.py refundable     # evaluate one case
    python demo.py refundable --no-sap
"""
import argparse

from gpf import evaluate, lists
from gpf.fixtures import CASES, all_case_keys, load_case

BUCKETS = [
    ("HARD STOPS  (rejection form)", "hard"),
    ("OBSERVATIONS(advisory memo)", "adv"),
    ("VERIFY TASKS(officer decides)", "conf"),
    ("SAP ITEMS   (section pulls)", "sap"),
    ("SATISFIED", "ok"),
    ("SATISFIED BY SUBSTITUTE", "sub"),
]


def show(key: str, without_sap: bool):
    F = load_case(key, without_sap=without_sap)
    results = evaluate(F)
    by_status = {}
    for r in results:
        by_status.setdefault(r["status"], []).append(r)
    meta = CASES[key]
    print(f"\n{'='*80}\n{meta.get('label')}  —  {meta.get('subject')}")
    print(f"personnel no. {meta.get('personnelNo')} · {meta.get('gazetted')}"
          + ("  · [received WITHOUT SAP pages]" if without_sap else ""))
    print("=" * 80)
    for title, status in BUCKETS:
        items = by_status.get(status, [])
        if not items:
            continue
        print(f"\n  {title}  ({len(items)})")
        for r in items:
            code = f"[{r.get('code')}] " if r.get("code") else ""
            print(f"    • {r['id']:<22} {code}{(r.get('title') or r.get('doc') or '')}")
    print(f"\n  totals: "
          + ", ".join(f"{s}={len(by_status.get(s, []))}" for _, s in BUCKETS if by_status.get(s)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case", nargs="?", help="case key (omit to list all)")
    ap.add_argument("--no-sap", action="store_true", help="evaluate as if received without SAP pages")
    args = ap.parse_args()
    if not args.case:
        print("Cases:")
        for k in all_case_keys():
            print(f"  {k:<18} {CASES[k].get('label')}")
        return
    show(args.case, args.no_sap)


if __name__ == "__main__":
    main()
