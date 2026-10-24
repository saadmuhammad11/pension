"""The module's own screens are served so a browser asks before it reuses them.

24 Oct 2026. An officer re-examined PC-2026-000070 and saw no Checklist tab and a SAP panel
with six blank rows where the pay slip would be -- both of them screens that had been fixed
hours earlier, neither of them delivered. The API was answering correctly the whole time: the
case carried its twenty-four reconciling years and its checklist, and the browser was running
the JavaScript of that morning.

This module is a buildless SPA. index.html, app.js and styles.css keep their names for ever,
so nothing in an address tells a browser that a file has changed -- unlike the portal, whose
bundler puts a hash of the contents into every file name and whose index.html is no-store.
These were served with an ETag and a Last-Modified and no Cache-Control at all, and a browser
given no instruction is entitled to guess how long a file stays fresh. The usual guess is a
tenth of its age, so index.html, being the oldest file, was held the longest.

"no-cache" is not "no-store": the browser may keep the file, it must just ask first, and the
ETag already on the response makes the answer a 304 with no body.

    python3 -m pytest tests/test_screens_are_not_served_stale.py -q
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gpf import apikey
from gpf.api import app

client = TestClient(app, headers={apikey.HEADER: apikey.api_key() or ""})

#: Every file the officer's browser holds between one screen and the next.
SCRIPTS = ["/js/app.js", "/js/ui.js", "/js/api.js", "/js/pure.js"]


class TestThePageThatNamesTheRest:

    def test_index_is_never_stored(self) -> None:
        """Two kilobytes, fetched every time. Telling a browser to revalidate only binds it
        once it asks, and a browser holding a copy it believes is fresh does not ask -- which
        is how a header set in the morning fixed every load after the next one, and not the
        next one."""
        r = client.get("/")
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-store"

    def test_everything_it_names_carries_the_version(self) -> None:
        from gpf.api import web_version
        html = client.get("/").text
        v = web_version()
        assert f'href="./styles.css?v={v}"' in html
        assert f'src="./js/app.js?v={v}"' in html

    def test_an_address_a_browser_has_never_seen_cannot_be_served_from_its_cache(self) -> None:
        """Which is the whole point: the fix must not depend on the officer clearing anything."""
        import pathlib as _p
        from gpf.api import WEB_DIR, web_version
        before = web_version()
        f = _p.Path(WEB_DIR) / "js" / "ui.js"
        original = f.read_bytes()
        try:
            f.write_bytes(original + b"\n// a screen changed\n")
            assert web_version() != before
        finally:
            f.write_bytes(original)
        assert web_version() == before


class TestTheWholeImportGraphMovesTogether:
    """A fresh entry point that pulls in yesterday's ui.js is the same bug wearing a hat."""

    @pytest.mark.parametrize("path", SCRIPTS)
    def test_a_scripts_own_imports_are_stamped(self, path) -> None:
        from gpf.api import web_version
        body = client.get(path).text
        for line in body.splitlines():
            if line.startswith("import ") and "'./" in line:
                assert f"?v={web_version()}'" in line, (path, line)

    def test_app_js_pulls_in_the_versioned_modules(self) -> None:
        from gpf.api import web_version
        body = client.get("/js/app.js").text
        v = web_version()
        for mod in ("api.js", "ui.js", "pure.js"):
            assert f"./{mod}?v={v}" in body, mod

    @pytest.mark.parametrize("path", SCRIPTS)
    def test_and_may_then_be_kept_for_ever(self, path) -> None:
        """The address can never name the wrong file, so there is nothing to revalidate."""
        r = client.get(path)
        assert r.status_code == 200
        assert "immutable" in r.headers["cache-control"]

    def test_a_script_that_does_not_exist_is_a_404_not_a_traversal(self) -> None:
        assert client.get("/js/nope.js").status_code == 404
        assert client.get("/js/..%2F..%2Fapi.js").status_code in (404, 400)


class TestTheRestOfTheScreens:

    def test_the_stylesheet_is_asked_about(self) -> None:
        """It is named with a version too, so this is belt and braces."""
        assert client.get("/styles.css").headers.get("cache-control") == "no-cache"

    def test_nothing_is_served_without_a_cache_instruction(self) -> None:
        """A browser given no instruction guesses, and the usual guess is a tenth of the
        file's age -- which is what served an officer the morning's screens."""
        for path in ["/", "/styles.css", *SCRIPTS]:
            assert client.get(path).headers.get("cache-control"), path
