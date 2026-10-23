"""A page opened in the GP Fund module turns and zooms, as it does on the pension side.

23 Oct 2026. Clicking an evidence crop opened the image and nothing else. Scans arrive as they
were fed -- a landscape table, a CNIC copied sideways, a form upside down -- and a page the
officer cannot read is a finding the officer cannot check. The pension portal has had Rotate
left / Rotate right / Actual size on its page preview for weeks (portals PagePreview.tsx);
this module had none of it.

Turning is for the officer's eyes: no case fact changes, and the next open starts straight.

    python3 -m pytest tests/test_page_viewer_tools.py -q
"""
from __future__ import annotations

import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
UI = (WEB / "js" / "ui.js").read_text(encoding="utf-8")
APP = (WEB / "js" / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "styles.css").read_text(encoding="utf-8")

VIEWER = UI[UI.index("export function openImageModal"):]
VIEWER = VIEWER[:VIEWER.index("\nexport ", 1)]


def test_the_viewer_offers_the_same_three_tools_the_pension_side_does() -> None:
    for label in ("Rotate left", "Rotate right", "Actual size"):
        assert label in VIEWER, label
    assert "Fit to width" in VIEWER, "the zoom button has to say what pressing it does next"


def test_the_keys_match_the_pension_side() -> None:
    """L and R, as PagePreview binds them. An officer reading a finding has a hand on the keys."""
    assert "'r' || e.key === 'R'" in VIEWER
    assert "'l' || e.key === 'L'" in VIEWER


def test_a_key_typed_into_a_field_is_the_fields() -> None:
    """The listener is on the document, so without this an L typed into a reason turns the page."""
    assert "HTMLInputElement" in VIEWER and "HTMLTextAreaElement" in VIEWER


def test_turning_is_in_right_angles_and_wraps() -> None:
    assert "(turn + by + 360) % 360" in VIEWER
    assert "rotate(-90)" in VIEWER and "rotate(90)" in VIEWER


def test_the_frame_is_sized_to_the_turned_shape() -> None:
    """A CSS rotation does not change the space an element takes up, so a page turned on its
    side spills out of the pane unless the box around it is sized for the turned shape."""
    assert "turn % 180 === 90" in VIEWER
    assert "sideways ? h : w" in VIEWER and "sideways ? w : h" in VIEWER


def test_the_image_is_hidden_until_it_has_been_measured() -> None:
    """An absolutely positioned image with no size draws at its natural width first, which on
    a 300dpi scan is a flash of something enormous."""
    assert "visibility: hidden" in CSS
    assert "img.style.visibility = 'visible'" in VIEWER


def test_the_evidence_thumbnails_open_it(self=None) -> None:
    assert "openImageModal(" in APP
    assert re.search(r"import \{[^}]*\bopenImageModal\b[^}]*\} from '\./ui\.js'", APP)


def test_nothing_else_still_opens_a_bare_image_modal() -> None:
    """The old call built an <img> into a plain modal. If one comes back, it comes back
    without the tools and nobody notices until an officer meets a sideways page."""
    assert "openModal('Evidence'" not in APP


def test_the_listeners_let_go_when_the_modal_closes() -> None:
    assert "removeEventListener('keydown', onKey)" in VIEWER
    assert "ro.disconnect()" in VIEWER
