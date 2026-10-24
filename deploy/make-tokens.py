#!/usr/bin/env python3
"""Write the shared design tokens from the one place the palette is decided.

    python3 deploy/make-tokens.py            # write both copies
    python3 deploy/make-tokens.py --check    # exit 1 if either is out of date

There were three truths about what colour this system is, and all three were live at once
(24 Oct 2026):

  * ``portals/src/shared/styles/base.css``  -- what the portal looks like before its JavaScript
    runs, and what anyone reading the repository would take for the answer;
  * ``api/themes.py``                       -- the palette the server actually sends, which
    ``portals/src/shared/theme/apply.ts`` pours into the same variable names on every page
    load, so this is what an officer sees;
  * ``GP/backend/web/styles.css``           -- the GP Fund module's own copy, taken from the
    29 Sep mock-up and never revised.

They disagreed. The module drew the brand in #1B4332 while the office had moved to #0E3527.
The portal's stylesheet set --muted to #656D76, chosen on 21 Oct for contrast, and the theme
overwrote it with #5F6B64 before the first paint -- so the considered value never once
rendered, and the one that did is better anyway (5.13:1 against 4.84:1 on the page, and
#656D76 actually fails on --sage2 at 4.40:1).

So: api/themes.py decides, and this writes the stylesheet both front ends read. The GP Fund
module is framed only by the Accountant General's own desks and the administrator (api.v2
case_gpf is gated on workflow.AG_READERS, which holds no department role), so the palette it
is built with is the "ag" one, which is also what the AG portal is served.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.themes import theme_for                                    # noqa: E402

PORTAL = ROOT / "portals" / "src" / "shared" / "styles" / "tokens.css"
MODULE = ROOT / "GP" / "backend" / "web" / "tokens.css"


def rgba(hex_colour: str, alpha: float) -> str:
    """apply.ts's own helper, in Python: the two must agree to the character."""
    h = hex_colour.lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    n = int(h, 16)
    return f"rgba({(n >> 16) & 255}, {(n >> 8) & 255}, {n & 255}, {alpha})"


def tokens_css() -> str:
    t = theme_for("ag", title="SERVE PUNJAB")
    return f'''/* The design tokens. GENERATED -- do not edit; run deploy/make-tokens.py.
 *
 * Written from api/themes.py, which is where the palette is decided and where the server
 * reads it to send to the browser. One file, two readers: the portal imports it from
 * styles/base.css, the GP Fund module links GP/backend/web/tokens.css, and the two copies are
 * required by test to be the same bytes. A copy rather than a link because the module must
 * stand up on its own port, air-gapped, with no build step.
 *
 * These are the "ag" palette's values, which is what both the AG portal and the module wear:
 * the module is framed only by the Accountant General's desks and the administrator. On a
 * department's portal theme/apply.ts overwrites the themed ones below with that department's
 * at run time, into these same variable names -- on the Police portal --green is navy. The
 * names are historical; the values are whoever's portal it is.
 *
 * What is NOT here is what belongs to one side: the module's seven examination states
 * (--conf, --sap, --na) and its fill ramp stay in its own stylesheet, below its link to this.
 */
:root {{
  /* ---- from api/themes.py THEMES["ag"] -- the office's own, off its sign-in mock-up of
     22 Oct 2026. Overwritten per department at run time by theme/apply.ts. ---- */
  --green: {t["primary"]};  --green2: {t["primary2"]}; --green3: {t["primary3"]};
  --sage:  {t["tint"]};  --sage2:  {t["tint2"]}; --gold:   {t["accent"]}; --gold2: {t["accent2"]};
  --ink:   {t["ink"]};  --muted:  {t["muted"]}; --line:   {t["line"]};
  --bg:    {t["bg"]};

  /* ---- derived from the palette, exactly as theme/apply.ts derives them ---- */
  --ring: {rgba(t["primary3"], 0.28)};
  --accent-a18: {rgba(t["accent"], 0.18)};
  --accent-a55: {rgba(t["accent"], 0.55)};
  --overlay: {rgba(t["primary"], 0.72)};
  /* Flat surfaces (28 Sep 2026): a hairline instead of a shadow; one soft shadow for what floats. */
  --shadow-1: none;
  --shadow-2: 0 8px 24px -12px rgba(23,33,28,.18);

  /* ---- not themed: the same on every portal ---- */
  /* The severity ramp. A finding is red, amber or green whoever is looking at it. */
  --red:   #B42318;  --redbg:  #FEF0EE; --amber:  #B54708; --amberbg: #FFF6E6;
  --ok:    #1E7B4F;  --okbg:   #E9F6EF;

  /* IBM Plex Sans is shipped with both (styles/fonts.css, GP/backend/web/fonts). The rest is
     what a Windows desktop in the office falls back to if the face has not loaded yet. */
  --font: "IBM Plex Sans", "Segoe UI", system-ui, -apple-system, Arial, sans-serif;
  --font-ur: "Jameel Noori Nastaleeq", "Noto Nastaliq Urdu", "Urdu Typesetting", serif;
  --font-mono: Consolas, Menlo, ui-monospace, monospace;

  /* One scale, so spacing is chosen rather than typed. */
  --s1: 4px;  --s2: 8px;  --s3: 12px; --s4: 16px;
  --s5: 22px; --s6: 30px; --s7: 40px; --s8: 56px;

  /* A type scale with real steps. The screens were monotone at 12-14px throughout, which
     is why nothing led the eye: every label competed with every heading. */
  --t-micro: 11px; --t-small: 12px; --t-body: 14.5px; --t-lead: 14.5px;
  --t-h3: 16px;    --t-h2: 19px;    --t-h1: 26px;     --t-figure: 30px;

  /* The technical log on the analysis screen: a dark panel, so its own small palette.
     All three clear AA on --log-bg (11.8, 8.4, 9.9). */
  --log-bg: #18201C; --log-fg: #D5DBD7; --log-err: #FF9E93; --log-warn: #E7C55B;
}}
'''


def main() -> int:
    css = tokens_css()
    check = "--check" in sys.argv
    stale = [p for p in (PORTAL, MODULE) if not p.is_file() or p.read_text(encoding="utf-8") != css]
    if check:
        for p in stale:
            print(f"out of date: {p.relative_to(ROOT)}", file=sys.stderr)
        if stale:
            print("run: python3 deploy/make-tokens.py", file=sys.stderr)
        return 1 if stale else 0
    for p in (PORTAL, MODULE):
        p.write_text(css, encoding="utf-8")
    print(f"wrote {PORTAL.relative_to(ROOT)} and {MODULE.relative_to(ROOT)}"
          + (" (changed)" if stale else " (unchanged)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
