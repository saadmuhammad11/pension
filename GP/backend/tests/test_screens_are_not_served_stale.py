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
SCREENS = ["/", "/js/app.js", "/js/ui.js", "/js/api.js", "/js/pure.js", "/styles.css"]


@pytest.mark.parametrize("path", SCREENS)
def test_the_browser_is_told_to_ask(path) -> None:
    r = client.get(path)
    assert r.status_code == 200, path
    assert r.headers.get("cache-control") == "no-cache", path


@pytest.mark.parametrize("path", SCREENS)
def test_and_given_something_to_ask_with(path) -> None:
    """Without a validator "no-cache" means the file is fetched whole every time."""
    r = client.get(path)
    assert r.headers.get("etag") or r.headers.get("last-modified"), path


def test_asking_costs_nothing_when_nothing_changed(self=None) -> None:
    first = client.get("/js/app.js")
    again = client.get("/js/app.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert not again.content


def test_the_page_that_names_the_others_is_covered(self=None) -> None:
    """index.html was the one served by its own route rather than the static mount, so it
    was the file the fix would most easily have missed -- and the oldest, so the one a
    browser held longest."""
    assert client.get("/").headers.get("cache-control") == "no-cache"


def test_it_is_not_no_store(self=None) -> None:
    """The officer should not re-download every screen on every navigation: they may keep
    them, they must just ask."""
    for path in SCREENS:
        assert "no-store" not in (client.get(path).headers.get("cache-control") or ""), path
