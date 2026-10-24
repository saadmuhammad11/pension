"""The module and the portal are one product, so they wear one skin (24 Oct 2026).

styles.css declared ``@font-face { font-family: "Geist"; src: url("./fonts/Geist.woff2") }``
and there was no ``web/fonts`` directory at all. Every load asked for the face, got 404 and
fell back to Segoe UI -- while the portal framing it rendered IBM Plex Sans, which it ships.
Nothing looked broken; the frame simply read as a different product, which is what an officer
notices first and can least explain.

The general lesson is the one this file guards: a @font-face that points at nothing fails
silently. So every url a stylesheet declares is resolved against the disk.

    python3 -m pytest tests/test_the_module_wears_the_portals_type.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
CSS = WEB / "styles.css"
TEXT = CSS.read_text(encoding="utf-8")
PORTAL_FONTS = Path(__file__).resolve().parents[3] / "portals" / "public" / "fonts"


def test_every_font_the_stylesheet_asks_for_is_on_the_disk() -> None:
    urls = re.findall(r'@font-face[^}]*?src:\s*url\("([^"]+)"', TEXT, re.S)
    assert urls, "the stylesheet declares no faces at all"
    for url in urls:
        assert (CSS.parent / url).resolve().is_file(), f"{url} is declared and does not exist"


def test_the_face_is_the_portals_own() -> None:
    """The word may still appear in the note above the rules, which is why that happened; what
    must not appear is a rule or a url that asks for it."""
    assert '"IBM Plex Sans"' in TEXT
    rules = re.sub(r"/\*.*?\*/", "", TEXT, flags=re.S)
    assert "Geist" not in rules, "Geist was never shipped; it resolved to Segoe UI"


def test_the_body_font_names_it_first() -> None:
    """Both :root blocks: the second overrides the first, and a reader of either should see
    the same answer rather than having to know which one wins."""
    for line in re.findall(r"^\s*--font:\s*(.+);$", TEXT, re.M):
        assert line.startswith('"IBM Plex Sans"'), line


def test_the_files_are_the_same_bytes_the_portal_serves() -> None:
    """Copied rather than linked, so the module stands up on its own port too -- but copied
    means they can drift, and two weights of the same name is worse than one of another."""
    for f in (WEB / "fonts").glob("*.woff2"):
        twin = PORTAL_FONTS / f.name
        assert twin.is_file(), f"{f.name} is not one of the portal's faces"
        assert f.read_bytes() == twin.read_bytes(), f"{f.name} has drifted from the portal's copy"


def test_no_face_is_fetched_from_the_internet() -> None:
    """A government box with restricted egress would fall back silently, and the page would
    look different for some officers and not others (the portal's fonts.css says the same)."""
    assert "fonts.googleapis.com" not in TEXT and "fonts.gstatic.com" not in TEXT


class TestTheTokensAreOneFileAndNotTwo:
    """Thirteen of thirty-nine shared tokens had drifted apart, six of them plainly to the eye
    (dE > 3): all three greens, the body ink, the muted grey, the gold. The module held the
    skin of the 29 Sep mock-up; the portal had moved to the office's sign-in mock-up of
    22 Oct. Neither was wrong on its own, which is how it survived so long.

    So there is one file now. It is copied rather than linked -- the module must stand up on
    its own port with no build step -- and a copy drifts unless something checks it.
    """

    PORTAL_TOKENS = Path(__file__).resolve().parents[3] / "portals" / "src" / "shared" / "styles" / "tokens.css"
    MODULE_TOKENS = WEB / "tokens.css"

    def test_the_module_has_the_portals_token_file_to_the_byte(self) -> None:
        assert self.MODULE_TOKENS.read_bytes() == self.PORTAL_TOKENS.read_bytes()

    def test_the_page_reads_it_before_its_own_stylesheet(self) -> None:
        """Order is the whole mechanism: tokens first, then the module's own on top.

        The link tags, not the first mention: the comment above them names styles.css."""
        html = (WEB / "index.html").read_text(encoding="utf-8")
        sheets = re.findall(r'<link[^>]+href="\./([^"]+\.css)"', html)
        assert sheets[:2] == ["tokens.css", "styles.css"], sheets

    def test_the_module_does_not_redeclare_a_shared_token(self) -> None:
        """What put the two skins out of step: a second copy, edited on one side only."""
        shared = self._declared(self.PORTAL_TOKENS)
        own = self._declared(WEB / "styles.css")
        assert not (shared & own), f"redeclared on both sides: {sorted(shared & own)}"

    def test_what_is_the_modules_own_stays_its_own(self) -> None:
        """The seven examination states and the fill ramp are not the portal's business."""
        own = self._declared(WEB / "styles.css")
        for t in ("--conf", "--sap", "--na", "--f1", "--good-bg"):
            assert t in own, t

    def test_the_fill_ramp_follows_the_brand_rather_than_a_mockup(self) -> None:
        """So a retint of the greens carries to the bars instead of leaving them behind."""
        css = (WEB / "styles.css").read_text(encoding="utf-8")
        assert "--f1: var(--green)" in css and "--f2: var(--green2)" in css

    def test_nothing_asks_for_a_token_that_no_longer_exists(self) -> None:
        have = self._declared(self.MODULE_TOKENS) | self._declared(WEB / "styles.css")
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", (WEB / "styles.css").read_text(encoding="utf-8")))
        assert not (used - have), f"undefined: {sorted(used - have)}"

    @staticmethod
    def _declared(path: Path) -> set[str]:
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        out: set[str] = set()
        for block in re.findall(r":root\s*\{(.*?)\}", css, re.S):
            out |= set(re.findall(r"(--[a-z0-9-]+)\s*:", block))
        return out
