import subprocess, glob, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(HERE, "poc_src") if os.path.isdir(os.path.join(HERE, "poc_src")) else HERE
order = ["sap.js","doa.js","doa_seed.js","engine.js","rules_common.js","rules_family.js","facts_gen.js","facts.js"] + \
        sorted(os.path.basename(p) for p in glob.glob(os.path.join(SRC, "facts_case_*.js"))) + ["facts_order.js"]
parts = [open(os.path.join(SRC, f), encoding="utf-8").read() for f in order if os.path.exists(os.path.join(SRC, f))]
runner = r"""
const only = process.argv[2];
for (const k of ORDER){
  if (only && k !== only) continue;
  for (const nosap of [false, true]){
    const S = newState(k, nosap); const r = evaluate(S.F); const L = lists(r);
    console.log((k + (nosap ? ' (no SAP)' : '')).padEnd(28) + ' hard ' + L.hard.length + ' adv ' + L.adv.length + ' conf ' + L.conf.length + ' sap ' + L.sap.length +
      ' || hard: ' + L.hard.map(x=>x.id+(x.sub?':'+x.sub:'')).join(', ') + ' || adv: ' + L.adv.map(x=>x.id+(x.sub?':'+x.sub:'')).join(', ') +
      ' || conf: ' + L.conf.map(x=>x.id+(x.sub?':'+x.sub:'')).join(', ') + ' || sap: ' + L.sap.map(x=>x.id+(x.sub?':'+x.sub:'')).join(', '));
    if (only && !nosap) r.forEach(x=>console.log('   ' + x.status.padEnd(5) + ' ' + x.id + (x.sub?':'+x.sub:'') + '  ' + (x.finding||'').slice(0,170)));
  }
}
"""
out = os.path.join(os.environ.get("TEMP", HERE), "gpf_harness_run.js")
open(out, "w", encoding="utf-8").write("\n".join(parts) + runner)
res = subprocess.run(["node", out] + sys.argv[1:], capture_output=True, text=True, encoding="utf-8")
print(res.stdout); print(res.stderr[-3000:])
