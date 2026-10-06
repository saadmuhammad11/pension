"""Assemble the prototype into one HTML file and syntax-check the script with node."""
import subprocess, sys
from pathlib import Path

SRC = Path(__file__).parent
OUT = Path(r"C:\Users\ahmed.raza\Desktop\agofficegpfund\prototype\gp-fund-preaudit-poc.html")
JS_ORDER = (["sap.js", "doa.js", "doa_seed.js", "engine.js", "rules_common.js", "rules_family.js",
             "rules_custom.js", "facts_gen.js", "facts.js"]
            + sorted(p.name for p in SRC.glob("facts_case_*.js"))
            + ["facts_order.js", "app_core.js", "app_sap.js", "app_exam.js", "app_dispose.js", "app_admin.js"])

css = (SRC / "styles.css").read_text(encoding="utf-8")
js_parts = []
for name in JS_ORDER:
    p = SRC / name
    if p.exists():
        js_parts.append(f"/* ---- {name} ---- */\n" + p.read_text(encoding="utf-8"))
    else:
        print("missing", name)
js = "\n".join(js_parts)

tmp = SRC / "_bundle_check.js"
tmp.write_text(js, encoding="utf-8")
r = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
if r.returncode != 0:
    print("SYNTAX ERROR\n", r.stderr)
    sys.exit(1)

html = (SRC / "template.html").read_text(encoding="utf-8")
html = html.replace("/*__CSS__*/", css).replace("/*__JS__*/", js)
bad = [c for c in ("\u2014",) if c in html]
if bad:
    lines = [i + 1 for i, l in enumerate(html.splitlines()) if "\u2014" in l]
    print("EM DASH found on lines", lines[:20])
    sys.exit(1)
OUT.write_text(html, encoding="utf-8")
print("built", OUT, len(html), "bytes")
