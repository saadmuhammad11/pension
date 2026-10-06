"""Per-case verification sheet: can an officer check this result without re-reading the file?

    python3 verify_case.py artifacts/run-b39c0973954a

``verify.py`` answers "is the engine right" against a case whose every figure was verified by
hand. This answers a different question, the one that applies to a case nobody has checked:
**where would this result be wrong, and which page do I open to find out.**

Three sections, in the order a doubt arises:

  1. THE COLUMN      which checklist was applied, and on what evidence. Everything downstream
                     is measured against this, so if it is wrong nothing else matters.

  2. THE LINES       every requirement, with the page that satisfied it. A PRESENT line is
                     checkable in one look: open that page and see whether it is that document.

  3. UNACCOUNTED     pages that produced no document at all. This is where a false MISSING
                     comes from, and it is the section worth reading first. On the widow case
                     AG-25 reported no affidavit while page 12 -- a Rs. 100 stamp paper in the
                     claimant's name -- sat unclassified. The checklist was not wrong about
                     what it could see; it could not see the page.

Reads only artefacts already on disk. No model, no GPU, so it can be run on a case long after
the services are down.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

C_OK, C_BAD, C_WARN, C_DIM, C_OFF = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"

MARK = {
    "PRESENT": (C_OK, "OK "),
    "MISSING": (C_BAD, "MISS"),
    "DEFECTIVE": (C_BAD, "DEF"),
    "NOT_APPLICABLE": (C_DIM, "n/a"),
}


def _load(run: Path, name: str) -> dict | list | None:
    path = run / name
    return json.loads(path.read_text()) if path.exists() else None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    run = Path(sys.argv[1])
    report = _load(run, "case_report.json")
    if report is None:
        print(f"no case_report.json in {run}")
        return 2

    manifest = _load(run, "manifest.json") or {"pages": []}
    identities = _load(run, "identities.json") or []
    by_page = {r["page"]: r for r in identities}

    print(f"\nVERIFICATION SHEET — {run.name}")
    print(f"{C_DIM}{report.get('source', {}).get('file', '')}{C_OFF}")

    # -- 1. the column -------------------------------------------------------------------
    print(f"\n{C_DIM}1. WHICH CHECKLIST WAS APPLIED{C_OFF}\n")
    variant = report.get("case_variant")
    source = report.get("case_variant_source")
    print(f"  column   {variant or '(none)'}   [{source or 'not determined'}]")
    print(f"  evidence {report.get('case_variant_evidence', '')}")
    if report.get("case_variant_candidates") and not variant:
        print(f"  {C_WARN}could also be{C_OFF} {', '.join(report['case_variant_candidates'])}")
    if source == "detected":
        print(f"  {C_DIM}To check: open the prescribed form and confirm it is that kind of "
              f"case.{C_OFF}")

    # -- 2. the lines --------------------------------------------------------------------
    checklist = report.get("checklist")
    if not checklist:
        print(f"\n  {C_BAD}no checklist ran{C_OFF} — {report.get('checklist_gap', '')}")
        return 1
    print(f"\n{C_DIM}2. EVERY REQUIREMENT, AND THE PAGE THAT SATISFIED IT{C_OFF}\n")
    doc_at: dict[int, str] = {}
    for d in report.get("documents", []):
        for pg in d.get("pages", []):
            doc_at[pg] = d["type"]
    for item in checklist["items"]:
        colour, mark = MARK[item["status"]]
        pages = list(item.get("located") or [])
        where = ""
        if pages:
            kinds = {doc_at.get(p, "?") for p in pages}
            where = f"p.{pages[0]}  {'/'.join(sorted(kinds))}"
        print(f"  {colour}{mark:<4}{C_OFF} {item['id']}  {item['requirement'][:50]:<50} {where}")
        if item["status"] in ("MISSING", "NOT_APPLICABLE", "DEFECTIVE") and item.get("reason"):
            print(f"        {C_DIM}{item['reason'][:96]}{C_OFF}")

    # -- 3. unaccounted pages -------------------------------------------------------------
    print(f"\n{C_DIM}3. PAGES THAT PRODUCED NO DOCUMENT — where a false MISSING hides{C_OFF}\n")
    counted = set(doc_at)
    loose = [p["page"] for p in manifest["pages"] if p["page"] not in counted]
    if not loose:
        print(f"  {C_OK}none{C_OFF} — every page in the bundle is accounted for")
    for page in loose:
        row = by_page.get(page, {})
        why = row.get("document_type", "not classified")
        if row.get("downgraded_from"):
            why += f" (claimed {row['downgraded_from']}, denied by OCR)"
        print(f"  {C_WARN}p.{page:<3}{C_OFF} {why}")
        if row.get("evidence"):
            print(f"        {C_DIM}the reader saw: {str(row['evidence'])[:88]}{C_OFF}")
    if loose:
        missing = [i["id"] for i in checklist["items"] if i["status"] == "MISSING"]
        if missing:
            print(f"\n  {C_WARN}Check these pages against the {len(missing)} missing "
                  f"line(s): {', '.join(missing)}{C_OFF}")

    # -- low-confidence reads, worth a second look ---------------------------------------
    weak = [r for r in identities if r.get("confidence", 1) < 0.9 or r.get("needs_human")]
    if weak:
        print(f"\n{C_DIM}4. READS THE SYSTEM IS NOT SURE OF{C_OFF}\n")
        for r in weak:
            print(f"  p.{r['page']:<3} {r['document_type']:<26} confidence {r.get('confidence')}")

    print(f"\n{C_DIM}SUMMARY{C_OFF}\n")
    print(f"  {checklist['result']}  {checklist['satisfied']}/{checklist['required']}"
          f"   ·   {len(report.get('documents', []))} documents"
          f"   ·   {len(loose)} page(s) unaccounted for")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
