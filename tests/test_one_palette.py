"""There is one answer to what colour this system is (24 Oct 2026).

There were three, all live at once. api/themes.py held the palette the server sends;
portals/src/shared/styles/base.css held a second copy, which is what the portal looks like
before its JavaScript runs and what a reader of the repository would take for the truth; and
GP/backend/web/styles.css held a third, taken from the 29 Sep mock-up and never revised.

The visible result was that the GP Fund module drew the brand in #1B4332 inside a portal
drawing it in #0E3527, and an officer met a second product in a frame. The invisible one was
that --muted was set to #656D76 in base.css on 21 Oct, deliberately, for contrast -- and
overwritten by the theme with #5F6B64 before the first paint, so the considered value never
rendered once.

deploy/make-tokens.py writes the stylesheet from api/themes.py. These checks are what stops
the third copy coming back.

    python3 -m pytest tests/test_one_palette.py -q
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "deploy" / "make-tokens.py"
PORTAL = ROOT / "portals" / "src" / "shared" / "styles" / "tokens.css"
MODULE = ROOT / "GP" / "backend" / "web" / "tokens.css"


def declared(path: Path) -> dict[str, str]:
    css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    out: dict[str, str] = {}
    for block in re.findall(r":root\s*\{(.*?)\}", css, re.S):
        for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", block):
            out[name] = " ".join(value.split())
    return out


class TheStylesheetIsWhatThemesPySays(unittest.TestCase):

    def test_both_copies_are_up_to_date(self) -> None:
        """Edit the palette and forget to run the generator, and this is what says so."""
        done = subprocess.run([sys.executable, str(GENERATOR), "--check"],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_two_copies_are_the_same_bytes(self) -> None:
        self.assertEqual(PORTAL.read_bytes(), MODULE.read_bytes())

    def test_the_themed_tokens_hold_the_ag_palette(self) -> None:
        from api.themes import theme_for
        t = theme_for("ag", title="x")
        have = declared(PORTAL)
        for token, slot in (("--green", "primary"), ("--green2", "primary2"), ("--green3", "primary3"),
                            ("--sage", "tint"), ("--sage2", "tint2"), ("--gold", "accent"),
                            ("--gold2", "accent2"), ("--ink", "ink"), ("--muted", "muted"),
                            ("--line", "line"), ("--bg", "bg")):
            self.assertEqual(have[token], t[slot], token)

    def test_it_says_it_is_generated(self) -> None:
        self.assertIn("GENERATED", PORTAL.read_text(encoding="utf-8")[:200])

    def test_no_stylesheet_keeps_a_second_copy_of_a_shared_token(self) -> None:
        """base.css and portals.css had their own :root; that is how the drift started."""
        shared = set(declared(PORTAL))
        for other in (ROOT / "portals" / "src" / "shared" / "styles" / "base.css",
                      ROOT / "portals" / "src" / "shared" / "styles" / "portals.css",
                      ROOT / "GP" / "backend" / "web" / "styles.css"):
            again = shared & set(declared(other))
            self.assertFalse(again, f"{other.name} redeclares {sorted(again)}")

    def test_the_portal_imports_it(self) -> None:
        base = (ROOT / "portals" / "src" / "shared" / "styles" / "base.css").read_text(encoding="utf-8")
        self.assertIn('@import "./tokens.css";', base)


class WhatTheBrowserEndsUpWith(unittest.TestCase):
    """apply.ts pours the theme into these same names on every page load, so the file and the
    run time must agree -- or the file is decoration and the drift is invisible again."""

    def test_the_file_matches_what_apply_ts_sets_for_the_ag_palette(self) -> None:
        from api.themes import theme_for
        t = theme_for("ag", title="x")
        have = declared(PORTAL)
        self.assertEqual(have["--shadow-1"], "none", "apply.ts flattens surfaces")
        self.assertEqual(have["--shadow-2"], "0 8px 24px -12px rgba(23,33,28,.18)")
        self.assertEqual(have["--ring"], _rgba(t["primary3"], 0.28))
        self.assertEqual(have["--accent-a18"], _rgba(t["accent"], 0.18))
        self.assertEqual(have["--accent-a55"], _rgba(t["accent"], 0.55))
        self.assertEqual(have["--overlay"], _rgba(t["primary"], 0.72))

    def test_the_generator_and_apply_ts_derive_them_the_same_way(self) -> None:
        """Both turn a hex and an alpha into rgba(); if the TS ever stops matching, say so."""
        ts = (ROOT / "portals" / "src" / "shared" / "theme" / "apply.ts").read_text(encoding="utf-8")
        for token, alpha in (("--ring", "0.28"), ("--accent-a18", "0.18"),
                             ("--accent-a55", "0.55"), ("--overlay", "0.72")):
            self.assertRegex(ts, rf"'{token}'.*?{alpha}", token)


class TheMutedGreyPassesWhereItIsUsed(unittest.TestCase):
    """The reason the two copies mattered: #656D76, the value base.css chose for AA, measures
    4.40:1 on --sage2 and fails. #5F6B64, the one the theme actually applies, is 4.67."""

    def test_it_clears_aa_on_every_background_it_sits_on(self) -> None:
        have = declared(PORTAL)
        for bg in ("--bg", "--sage", "--sage2", "#FFFFFF"):
            colour = have.get(bg, bg)
            self.assertGreaterEqual(round(_ratio(have["--muted"], colour), 2), 4.5,
                                    f"--muted on {bg} ({colour})")


def _rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    n = int("".join(c * 2 for c in h) if len(h) == 3 else h, 16)
    return f"rgba({(n >> 16) & 255}, {(n >> 8) & 255}, {n & 255}, {alpha})"


def _ratio(a: str, b: str) -> float:
    def lum(h: str) -> float:
        h = h.lstrip("#")
        ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        ch = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in ch]
        return .2126 * ch[0] + .7152 * ch[1] + .0722 * ch[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + .05) / (lo + .05)


if __name__ == "__main__":
    unittest.main()
