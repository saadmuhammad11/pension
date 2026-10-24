"""Evaluation harness: read a case's real scans through the live pipeline and
score the resulting pre-audit against the curated fixture (spec §17).

    ./.venv/bin/python eval_reading.py refundable [more cases...]

For each case it prints the per-page classification, then compares the rules
result produced from the REAL reading against the result produced from the
hand-curated facts (the ground truth), as a per-check agreement table. This is
the honest measure of end-to-end reading quality: does the AI read the scans
well enough that the deterministic rules reach the same pre-audit?
"""
import glob
import sys
import time

from gpf import evaluate
from gpf.clients import VllmModelClient
from gpf.fixtures import CASES, load_case
from gpf.reading import Page, ReadingPipeline

ENDPOINTS = ["http://vision-host.internal:8011", "http://vision-host.internal:8012",
             "http://vision-host.internal:8093", "http://reasoning-host.internal:8001"]


def status_map(results):
    return {r["id"]: r["status"] for r in results}


def eval_case(pipeline, key):
    meta = CASES[key]
    pages_paths = sorted(glob.glob(f"../prototype/pages/{key}/*.jpg"))
    pages = [Page(i + 1, p) for i, p in enumerate(pages_paths)]
    print(f"\n{'='*74}\n{key}  ({meta.get('label')})  —  {len(pages)} pages")
    print("=" * 74)

    t = time.time()
    result = pipeline.run(pages, kind=meta.get("kind"), gazetted=meta.get("gazetted"))
    took = time.time() - t

    print("Page classification:")
    for pr in result.pages:
        print(f"  p{pr.page:<2} {pr.artefact:24} (conf {pr.classify_confidence}, {len(pr.fields)} fields)")
    print(f"needs-human fields: {len(result.needs_human)} · read time {took:.0f}s")
    print(f"personnelNo read: {result.facts.get('personnelNo')}  (expected {meta.get('personnelNo')})")

    real = status_map(evaluate(result.facts))
    expected = status_map(evaluate(load_case(key)))   # ground truth from curated facts

    ids = sorted(set(expected) | set(real))
    agree = sum(1 for i in ids if expected.get(i) == real.get(i))
    print(f"\nRules agreement: {agree}/{len(ids)} checks match the curated ground truth")
    diffs = [(i, expected.get(i), real.get(i)) for i in ids if expected.get(i) != real.get(i)]
    if diffs:
        print("Differences (check: expected -> from-scans):")
        for i, e, r in diffs:
            print(f"  {i:22} {str(e):5} -> {r}")
    return {"case": key, "pages": len(pages), "agree": agree, "total": len(ids),
            "persno_ok": result.facts.get("personnelNo") == meta.get("personnelNo"),
            "seconds": round(took)}


def main():
    cases = sys.argv[1:] or ["refundable"]
    pipeline = ReadingPipeline(VllmModelClient.from_discovery(ENDPOINTS, timeout=240))
    summary = [eval_case(pipeline, k) for k in cases]
    print(f"\n{'='*74}\nSUMMARY")
    for s in summary:
        pct = round(100 * s["agree"] / s["total"]) if s["total"] else 0
        print(f"  {s['case']:18} {s['agree']}/{s['total']} checks ({pct}%) · "
              f"persNo {'ok' if s['persno_ok'] else 'MISS'} · {s['pages']}p · {s['seconds']}s")


if __name__ == "__main__":
    main()
