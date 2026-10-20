#!/usr/bin/env python3
"""Where the time went in a benchmark run: tables from artifacts/bench/<label>/.

    python3 tools/bench_report.py baseline
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    d = ROOT / "artifacts" / "bench" / argv[1]
    cases = {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json")) if p.stem != "summary"}
    print(f"# {argv[1]}  ({(d / 'summary.json').exists() and json.loads((d / 'summary.json').read_text()).get('git')})\n")
    # conc max / queued are the tuning columns: how many requests the servers really ran at
    # once, and whether any waited for scheduler capacity. Raising concurrency past the point
    # where "queued" leaves zero buys queueing, not throughput.
    print(f"{'case':<8}{'state':<8}{'wall s':>8}{'conc mean':>10}{'conc max':>9}{'queued':>7}"
          f"{'kv%':>6}{'gpu% max':>9}{'RAM peak GB':>12}  flags  verdict")
    for name, r in cases.items():
        res = r.get("resources") or {}
        f = r.get("findings") or {}
        nflags = len(f.get("flags") or []) if "flags" in f else sum(len(v) for k, v in (f.get("items") or {}).items() if k in ("hard", "adv"))
        print(f"{name:<8}{str(r.get('state')):<8}{r.get('wall_s') or 0:>8.1f}"
              f"{str(res.get('model_running_mean')):>10}{str(res.get('model_running_max')):>9}"
              f"{str(res.get('model_waiting_capacity_max')):>7}{str(res.get('model_kv_cache_pct_max')):>6}"
              f"{str(res.get('gpu_util_max_pct')):>9}{str(res.get('ram_used_peak_gb')):>12}"
              f"  {nflags:<5}  {f.get('verdict') or (f.get('position') or {}).get('mayAdvance')}")
    # stages across cases
    print("\n## Time by stage (sum over cases, sorted)")
    stage_tot: Counter = Counter(); stage_by_case = defaultdict(dict)
    for name, r in cases.items():
        for st, v in ((r.get("timings") or {}).get("stages") or {}).items():
            if st == "run":
                continue
            stage_tot[st] += v["duration_s"]; stage_by_case[st][name] = v["duration_s"]
    total = sum(stage_tot.values()) or 1
    print(f"{'stage':<12}{'total s':>9}{'share':>7}  " + "".join(f"{n:>9}" for n in cases))
    for st, t in stage_tot.most_common():
        print(f"{st:<12}{t:>9.1f}{t / total * 100:>6.0f}%  " + "".join(f"{stage_by_case[st].get(n, 0):>9.1f}" for n in cases))
    # model calls
    print("\n## Model calls (sum over cases)")
    print(f"{'role':<22}{'calls':>6}{'round trip s':>13}{'mean s':>8}{'max s':>7}{'pool wait s':>12}{'errors':>7}{'prompt tok':>11}{'compl tok':>10}")
    agg: dict[str, dict] = {}
    schema_tot: dict[str, dict] = {}
    for r in cases.values():
        for role, m in ((r.get("timings") or {}).get("models") or {}).items():
            a = agg.setdefault(role, Counter())
            for k in ("calls", "total_s", "errors", "queue_s", "prompt_tokens", "completion_tokens"):
                a[k] += m.get(k) or 0
            a["max_s"] = max(a["max_s"], m.get("max_s") or 0)
            for sch, s in (m.get("by_schema") or {}).items():
                t = schema_tot.setdefault(f"{role}:{sch}", Counter()); t["calls"] += s["calls"]; t["total_s"] += s["total_s"]
    for role, a in sorted(agg.items(), key=lambda kv: -kv[1]["total_s"]):
        print(f"{role:<22}{a['calls']:>6}{a['total_s']:>13.1f}{a['total_s'] / max(a['calls'], 1):>8.1f}{a['max_s']:>7.1f}{a['queue_s']:>12.1f}{a['errors']:>7}{a['prompt_tokens']:>11}{a['completion_tokens']:>10}")
    print("\n## By schema")
    for key, t in sorted(schema_tot.items(), key=lambda kv: -kv[1]["total_s"]):
        print(f"{key:<40}{t['calls']:>6} calls {t['total_s']:>9.1f} s  mean {t['total_s'] / max(t['calls'], 1):.1f} s")
    # repeated reads
    print("\n## Pages read by the vision model more than once (pension cases; the H1 double read counts as 2)")
    for name, r in cases.items():
        rows = (r.get("timings") or {}).get("raw") or []
        per_page: Counter = Counter((row["page"], row["name"]) for row in rows if row["kind"] == "model" and row["stage"] == "vision" and row["page"])
        by_page: Counter = Counter()
        for (pg, sch), n in per_page.items():
            by_page[pg] += n
        rep = {pg: n for pg, n in sorted(by_page.items()) if n > 2}
        if rep or by_page:
            print(f"{name}: pages read >2 times: {rep or 'none'}; total vision calls {sum(by_page.values())} over {len(by_page)} pages")
            dup = sorted(((pg, sch, n) for (pg, sch), n in per_page.items() if n > 1), key=lambda x: -x[2])[:8]
            if dup:
                print("   same schema repeated:", dup)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
