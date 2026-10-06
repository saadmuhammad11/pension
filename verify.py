"""Verification harness: is the pipeline's output actually right? BUILD §12.3.

    python3 verify.py [artifacts/run-0aee822c760e]

Answers the only question that matters about an extraction pipeline -- *how do I know it read
the page correctly* -- by checking the pipeline's own output against evidence it never saw.

Four independent checks, reported separately because a blended score hides the one that is
failing (BUILD §2.1 makes the same point about handwriting versus printed text):

  1. GROUNDING     every extracted value must appear in the human transcription of the page
                   it was read from. The digitised source carries a typed transcription of all
                   43 pages; the vision model is only ever shown the scan image. So the
                   transcription is independent testimony, and this is the check that catches
                   a value the model invented rather than read.

  2. ARITHMETIC    figures the rules engine derived, against BRAIN §13.6, whose every value was
                   hand-verified by a human. Also re-derives them here from first principles,
                   so a bug shared between engine and expectation cannot hide.

  3. CLASSIFICATION per document type against the header titles the digitised copy prints.

  4. COMPLETENESS  which stages ran, which of the seven expected flags fired, and what is
                   missing. Absence is reported as absence, never as success.

Nothing here trusts a confidence score. The model reported 1.00 while reading BS-19 as 12, and
0.9994 on a citation that was wrong; a self-reported confidence is a claim, not evidence.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent

C_OK, C_BAD, C_WARN, C_DIM, C_OFF = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"


def line(status: str, label: str, detail: str = "") -> None:
    colour = {"PASS": C_OK, "FAIL": C_BAD, "WARN": C_WARN, "----": C_DIM}[status]
    print(f"  {colour}{status:<5}{C_OFF} {label:<44} {detail}")


def norm(text: str) -> str:
    """Fold to comparable form: strip accents, punctuation and case, squeeze spaces.

    Grounding must survive formatting differences that carry no meaning -- "19-02-1966" in the
    extraction against "19.02.1966" in the transcription, "Rs. 192,030" against "192030".
    """
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9]+", " ", t)).strip().lower()


def digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def date_grounded(value: str, page_text: str) -> bool | None:
    """Is an ISO date findable on the page in any of the orders a form prints it?

    ``None`` when the value is not a date, so the caller falls through to its own test.

    Needed because the extraction normalises to YYYY-MM-DD while the page prints
    DD-MM-YYYY. Comparing digit runs then fails on every correctly-read date -- four of
    them here -- and that noise is not harmless: it sat in the same column as
    ``psa_signature_date``, which was a genuine fabrication, and made the two look alike.
    A check that cries wolf is worse than no check, because it hides the wolf.
    """
    m = _ISO.match((value or "").strip())
    if not m:
        return None
    y, mo, d = m.groups()
    page = digits(page_text)
    # Accept the date only as a contiguous run, in one of the orders a Punjab form uses.
    return any(order in page for order in (y + mo + d, d + mo + y, mo + d + y))


# ---------------------------------------------------------------------------------------------
# 1. GROUNDING
# ---------------------------------------------------------------------------------------------

def check_grounding(run: Path) -> tuple[int, int]:
    """Every extracted value must be findable in the transcription of its own page."""
    print(f"\n{C_DIM}1. GROUNDING — extracted values against the human transcription "
          f"of the same page{C_OFF}\n")
    manifest = json.loads((run / "manifest.json").read_text())
    pages = {p["page"]: p["transcription"] for p in manifest["pages"]}

    fields_path = run / "fields.json"
    if not fields_path.exists():
        line("----", "fields.json absent", "stage 4 has not run")
        return 0, 0
    data = json.loads(fields_path.read_text())

    passed = total = 0
    for f in data.get("fields", []):
        value, page = f.get("value"), f.get("page")
        if not value or page not in pages:
            continue
        total += 1
        page_norm, page_digits = norm(pages[page]), digits(pages[page])
        v_norm, v_digits = norm(str(value)), digits(str(value))
        as_date = date_grounded(str(value), pages[page])
        if as_date is not None:
            found = as_date
        else:
            # An amount is grounded if its digits appear; free text if its words do.
            found = (len(v_digits) >= 4 and v_digits in page_digits) or \
                    (len(v_norm) >= 3 and v_norm in page_norm)
        passed += found
        line("PASS" if found else "FAIL", f["name"], f"{str(value)[:34]!r} on p.{page}")

    for c in data.get("pay_components", []):
        page = c.get("page")
        if page not in pages:
            continue
        total += 1
        found = digits(str(c["amount"])) in digits(pages[page])
        passed += found
        line("PASS" if found else "FAIL", f"pay: {c['printed_label'][:28]}",
             f"{c['amount']:,} on p.{page}")

    printed = data.get("printed_totals", {}).get("form_total_pay")
    if printed:
        total += 1
        form_page = next((f["page"] for f in data["fields"] if f["name"] == "date_of_birth"), None)
        found = form_page in pages and digits(str(printed)) in digits(pages[form_page])
        passed += found
        line("PASS" if found else "FAIL", "printed total on the form", f"{printed:,}")

    return passed, total


# ---------------------------------------------------------------------------------------------
# 2. ARITHMETIC
# ---------------------------------------------------------------------------------------------

#: BRAIN §13.6 and §13.3. Every figure hand-verified by a human against the real case.
EXPECTED = {
    "reckonable_total": 192_030,
    "excluded_total": 161_765,
    "CALC-01": 134_421,
    "FAM-IS-03": 100_816,
    "gratuity_literal": 33_605,
    "gratuity_capitalised": 4_989_130,
    "medical_on_family_pension": 20_163,
    "medical_on_gross_pension": 26_884,
}


def check_arithmetic(run: Path) -> tuple[int, int]:
    print(f"\n{C_DIM}2. ARITHMETIC — engine output against BRAIN §13.6, and re-derived "
          f"independently here{C_OFF}\n")
    det_path = run / "determination.json"
    if not det_path.exists():
        line("----", "determination.json absent", "stage 7 has not run")
        return 0, 0
    payload = json.loads(det_path.read_text())
    det, emol = payload["determination"], payload["emoluments"]

    def step(rid):
        return next((s["amount"] for s in det["steps"] if s["rule_id"] == rid), None)

    amb = {a["rule_id"]: {r["label"]: r["amount"] for r in a["readings"]}
           for a in det["ambiguities"]}

    got = {
        "reckonable_total": emol["reckonable_total"],
        "excluded_total": emol["excluded_total"],
        "CALC-01": step("CALC-01"),
        "FAM-IS-03": step("FAM-IS-03"),
        "gratuity_literal": amb.get("FAM-IS-04", {}).get("literal"),
        "gratuity_capitalised": amb.get("FAM-IS-04", {}).get("capitalised"),
        "medical_on_family_pension": amb.get("ADD-02", {}).get("on_family_pension"),
        "medical_on_gross_pension": amb.get("ADD-02", {}).get("on_gross_pension"),
    }
    passed = total = 0
    for key, want in EXPECTED.items():
        total += 1
        ok = got[key] == want
        passed += ok
        line("PASS" if ok else "FAIL", key,
             f"{got[key]:,}" if got[key] is not None else "absent"
             + ("" if ok else f"   expected {want:,}"))

    # Re-derive from first principles: an error shared by engine and expectation would
    # otherwise pass both. 192030 x 30 x 7 / 300, then 75% of that, half-up.
    from decimal import ROUND_HALF_UP, Decimal
    gross = Decimal(emol["reckonable_total"]) * 30 * 7 / 300
    fam = (gross * 75 / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    total += 2
    for label, mine, theirs in (("gross re-derived", int(gross), step("CALC-01")),
                                ("family pension re-derived", int(fam), step("FAM-IS-03"))):
        ok = mine == theirs
        passed += ok
        line("PASS" if ok else "FAIL", label, f"{mine:,} vs engine {theirs:,}")

    total += 1
    reconciled = emol["reconciled"]
    passed += reconciled
    line("PASS" if reconciled else "FAIL", "reckonable total reconciles with the form",
         f"printed {emol['printed_total']:,}" if emol["printed_total"] else "no printed total")
    return passed, total


# ---------------------------------------------------------------------------------------------
# 3. CLASSIFICATION
# ---------------------------------------------------------------------------------------------

def check_classification(run: Path) -> tuple[int, int]:
    print(f"\n{C_DIM}3. CLASSIFICATION — per document type, against the header titles the "
          f"digitised copy prints{C_OFF}\n")
    sys.path.insert(0, str(ROOT))
    from pipeline.run import classification_eval

    ev = classification_eval(run)
    for name, v in ev["per_type"].items():
        line("PASS" if v["accuracy"] == 1.0 else "FAIL", name, f"{v['correct']}/{v['n']}")
    line("----", "overall (keyword-scorable pages only)",
         f"{ev['correct']}/{ev['scored']} = {ev['accuracy']}   "
         f"({ev['unlabelled_by_keyword']} of {ev['pages']} pages carry no scorable header)")
    if ev["low_confidence_pages"]:
        line("WARN", "pages routed to human confirmation", str(ev["low_confidence_pages"]))
    return ev["correct"], ev["scored"]


# ---------------------------------------------------------------------------------------------
# 4. COMPLETENESS
# ---------------------------------------------------------------------------------------------

#: BRAIN §13.5. The seven findings a correct system raises on this case.
EXPECTED_FLAGS = {
    "CONTRA-IDENTITY": "HIGH   personnel number 90000857 vs 90000853",
    "CONTRA-FAMILY": "HIGH   Annex-A calls Asad a daughter; the FRC records a married son",
    "RULE-UNDECLARED": "HIGH   unrecorded Rs. 126,355 recovery",
    "RULE-CAP": "MEDIUM QS stated 32 years against the 30-year cap",
    "SLA-BREACH": "MEDIUM 15-day sanction requirement exceeded",
    "ALIAS-RESOLVED": "LOW    Nargas/Nargis name variants",
    "SCOPE-CONFUSION": "LOW    succession certificate in a family-pension case",
}

STAGES = (
    ("1  ingest", "manifest.json"),
    ("3  identify", "identities.json"),
    ("3b assemble", "documents.json"),
    ("3c classify", "case_type.json"),
    ("4  extract", "fields.json"),
    ("6  assertions", "assertions.json"),
    ("7  determine", "determination.json"),
    ("   report", "case_report.json"),
)


def check_completeness(run: Path) -> tuple[int, int]:
    print(f"\n{C_DIM}4. COMPLETENESS — which stages ran, and which of the seven expected "
          f"findings fired{C_OFF}\n")
    for label, artefact in STAGES:
        present = (run / artefact).exists()
        line("PASS" if present else "FAIL", f"stage {label}",
             artefact if present else "not run")

    report_path = run / "case_report.json"
    if not report_path.exists():
        return 0, len(EXPECTED_FLAGS)
    report = json.loads(report_path.read_text())
    raised = {f["class"] for f in report["flags"]}

    print()
    passed = 0
    for cls, desc in EXPECTED_FLAGS.items():
        hit = cls in raised
        passed += hit
        line("PASS" if hit else "FAIL", cls, desc)
    spurious = raised - set(EXPECTED_FLAGS)
    if spurious:
        line("WARN", "flags raised but NOT expected", str(sorted(spurious)))

    cl = report.get("checklist") or {}
    print()
    line("----", "checklist", f"{cl.get('result')} {cl.get('satisfied')}/{cl.get('required')}")
    line("----", "verdict", f"{(report.get('recommendation') or {}).get('verdict')}   "
                            f"blocking {(report.get('recommendation') or {}).get('blocking_flags')}")
    return passed, len(EXPECTED_FLAGS)


def main() -> int:
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "run-0aee822c760e"
    if not run.exists():
        print(f"no run directory at {run}")
        return 2
    print(f"\nVERIFICATION — {run}")

    results = [
        ("grounding", *check_grounding(run)),
        ("arithmetic", *check_arithmetic(run)),
        ("classification", *check_classification(run)),
        ("completeness", *check_completeness(run)),
    ]
    print(f"\n{C_DIM}SUMMARY{C_OFF}\n")
    worst = 0
    for name, passed, total in results:
        pct = f"{passed}/{total}" if total else "n/a"
        status = "PASS" if total and passed == total else ("FAIL" if total else "----")
        worst = max(worst, 1 if status == "FAIL" else 0)
        line(status, name, pct)
    print()
    return worst


if __name__ == "__main__":
    sys.exit(main())
