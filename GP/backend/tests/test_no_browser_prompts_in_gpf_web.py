"""The GP Fund screens ask for a note in the page, never in a browser prompt (23 Oct 2026).

The pension portal has had this rule since 6 Oct 2026 (tests/test_admin_screen_has_no_browser_
prompts.py) but it reads portals/src only, so this module was never covered and three prompt()
windows survived in it: the verification note, the disposition reason, and the note on a return.

window.prompt is a window the page does not own. It carries none of this screen's wording, it
shows no validation message of its own, it blocks the tab while it stands, and a browser that
declines to draw one -- which one inside a frame may -- returns null, which is what Cancel also
returns. An officer who typed a verification and pressed OK could therefore have it dropped with
nothing said. ui.inlineNote puts the box under the item's own buttons instead.

    python3 -m pytest tests/test_no_browser_prompts_in_gpf_web.py -q
"""
from __future__ import annotations

import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
#: A call to one of the browser's own modal windows. confirmDialog() is this app's own and passes.
CALL = re.compile(r"\b(?:window\.)?(?:prompt|confirm|alert)\s*\(")


def _code(line: str) -> str:
    """The line's code, comments dropped: the ban is on calls, not on prose about them -- the
    note helper's own docblock explains at length why prompt() is gone."""
    s = line.strip()
    if s.startswith("*") or s.startswith("/*") or s.startswith("//"):
        return ""
    return line.split("//")[0]


def test_no_screen_opens_a_browser_prompt() -> None:
    offenders = []
    for path in sorted(WEB.rglob("*.js")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if CALL.search(_code(line)):
                offenders.append(f"{path.relative_to(WEB)}:{n}: {line.strip()}")
    assert offenders == []


def test_the_verification_note_is_taken_in_the_item() -> None:
    app = (WEB / "js" / "app.js").read_text(encoding="utf-8")
    verify = app[app.index("act === 'verify-ok'"):app.index("act === 'disp-waive'")]
    assert "inlineNote(btn, {" in verify
    # What was typed reaches the service: the panel hands its text to submit, unchanged.
    assert "api.verify(id, r.cure.vid, ok, note, state.officer)" in verify


def test_the_panel_keeps_the_note_when_the_service_refuses() -> None:
    """The reason a toast was not enough: the prompt had already closed, taking the text."""
    ui = (WEB / "js" / "ui.js").read_text(encoding="utf-8")
    body = ui[ui.index("export function inlineNote"):]
    body = body[:body.index("\nexport ", 1)]
    assert "catch (e) { fail(e.message || String(e)); }" in body
    assert "if (text.length < min)" in body          # the minimum is enforced before sending
    assert "box.focus()" in body                     # and the officer is put back in the box
