"""The module and the portal are one product, so they are set in one typeface (24 Oct 2026).

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
