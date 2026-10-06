#!/usr/bin/env python3
"""Fold the demo build (portals/dist-demo) into ONE html file (default demo/pension-demo.html):
scripts and styles inlined, the TMC mark as a data URI, nothing fetched from anywhere.

    cd portals && npx vite build -c vite.demo.config.ts && python3 ../demo/build.py
    (the scripted variant: DEMO_ENTRY=demo.html npx vite build -c vite.demo.config.ts && python3 ../demo/build.py demo.html auto-demo.html)
"""
import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "portals" / "dist-demo"
ENTRY = sys.argv[1] if len(sys.argv) > 1 else "manual.html"
OUT = ROOT / "demo" / (sys.argv[2] if len(sys.argv) > 2 else "pension-demo.html")


def main() -> int:
    html = (DIST / ENTRY).read_text(encoding="utf-8")
    logo = base64.b64encode((ROOT / "portals" / "public" / "tmc-logo.png").read_bytes()).decode()
    logo_uri = f"data:image/png;base64,{logo}"

    def inline_script(m: re.Match) -> str:
        src = m.group(1).lstrip("./")
        js = (DIST / src).read_text(encoding="utf-8")
        js = js.replace("./tmc-logo.png", logo_uri).replace("</script", "<\\/script")
        return f'<script type="module">{js}</script>'

    def inline_style(m: re.Match) -> str:
        href = m.group(1).lstrip("./")
        css = (DIST / href).read_text(encoding="utf-8").replace("</style", "<\\/style")
        return f"<style>{css}</style>"

    html = re.sub(r'<script type="module" crossorigin src="([^"]+)"></script>', inline_script, html)
    html = re.sub(r'<link rel="stylesheet" crossorigin href="([^"]+)">', inline_style, html)
    html = html.replace('<link rel="modulepreload"', '<link rel="x-modulepreload"')
    html = html.replace("</title>", "</title>\n    <meta name=\"referrer\" content=\"no-referrer\" />", 1)
    if 'src="./' in html or 'href="./assets' in html:
        print("warning: some asset references remain", file=sys.stderr)
    OUT.write_text(html, encoding="utf-8")
    print(f"{OUT} ({OUT.stat().st_size / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
