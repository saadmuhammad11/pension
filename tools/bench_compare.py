#!/usr/bin/env python3
"""Hold one benchmark run to another: findings must be IDENTICAL, times may differ.

    python3 tools/bench_compare.py artifacts/bench/baseline artifacts/bench/after-xyz
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _load(d: Path) -> dict:
    return {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json")) if p.stem != "summary"}


def main(argv: list[str]) -> int:
    base, other = Path(argv[1]), Path(argv[2])
    a, b = _load(base), _load(other)
    identical = True
    print(f"{'case':<8} {'baseline s':>11} {'after s':>9} {'change':>8}  {'gpu% mean':>9}  {'ram peak GB':>11}  findings")
    for name in sorted(set(a) | set(b)):
        ra, rb = a.get(name), b.get(name)
        if not ra or not rb:
            print(f"{name:<8} missing in {'baseline' if not ra else 'after'}"); identical = False; continue
        same = json.dumps(ra.get("findings"), sort_keys=True) == json.dumps(rb.get("findings"), sort_keys=True)
        identical &= same
        wa, wb = ra.get("wall_s") or 0, rb.get("wall_s") or 0
        change = f"{(wb - wa) / wa * 100:+.0f}%" if wa else "n/a"
        res = rb.get("resources") or {}
        print(f"{name:<8} {wa:>11.1f} {wb:>9.1f} {change:>8}  {str(res.get('gpu_util_mean_pct')):>9}  {str(res.get('ram_used_peak_gb')):>11}  "
              f"{'IDENTICAL' if same else 'DIFFERENT'}")
        if not same:
            fa, fb = ra.get("findings") or {}, rb.get("findings") or {}
            for key in sorted(set(fa) | set(fb)):
                if json.dumps(fa.get(key), sort_keys=True) != json.dumps(fb.get(key), sort_keys=True):
                    print(f"         - {key}: baseline={json.dumps(fa.get(key), ensure_ascii=False)[:160]}")
                    print(f"           after   ={json.dumps(fb.get(key), ensure_ascii=False)[:160]}")
    print("RESULT:", "IDENTICAL findings on every case" if identical else "FINDINGS DIFFER")
    return 0 if identical else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
