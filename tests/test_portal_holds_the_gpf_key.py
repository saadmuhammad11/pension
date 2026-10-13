"""The portal's half of the key that the GP Fund module now demands (audit of 13 Oct 2026, C-04).

The module has no sign-in of its own. Until this key, the only thing between it and anyone else
on the box was its loopback bind, and every mutating endpoint trusted an ``officer`` string in
the request body -- so any local process could act as the Deputy AG and read any claimant's
scans. The module's own half is ``GP/backend/tests/test_module_needs_the_portals_key.py``; this
is the side that presents it: the portal's ``/gpf/`` proxy and the reconciler's bridge.

    python3 -m unittest tests.test_portal_holds_the_gpf_key -v
"""
from __future__ import annotations

import importlib.util
import json
import re
import stat
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from starlette.testclient import TestClient

from api import gpf_bridge, portal_server
from api.departments import AG_PORTAL_PORT


class _Recorder:
    """A session that answers 200 and keeps the headers it was asked to forward."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    def request(self, method, url, *, headers=None, **kw):
        self.headers = dict(headers or {})
        recorder = self

        class _Up:
            status = 200
            headers: dict[str, str] = {}

            async def read(self_inner):
                return b"{}"

        class _Ctx:
            async def __aenter__(self_inner):
                return _Up()

            async def __aexit__(self_inner, *exc):
                return False

        assert recorder is not None
        return _Ctx()


class ThePortalPresentsTheKey(unittest.TestCase):
    """Every request the portal passes to the module carries it, and only the portal's own."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-gpfkey-")
        self.addCleanup(self._tmp.cleanup)
        dist = Path(self._tmp.name)
        (dist / "index.html").write_text("<!doctype html><html><body><div id=root></div></body></html>")
        self.portal = portal_server.PortalApp(dist=dist, api="http://127.0.0.1:1", trust_port_header=True)
        self.portal.bound = [AG_PORTAL_PORT]
        self.recorder = _Recorder()
        self.portal.session = self.recorder

        async def signed_in(request):
            return "ao|Officer"
        self.portal.gpf_signed_in = signed_in

        async def allowed(request, sub):
            return None
        self.portal.gpf_act_refused = allowed
        self.portal.gpf_read_refused = allowed
        self.client = TestClient(self.portal.app)

    def _forwarded(self) -> dict[str, str]:
        return {k.lower(): v for k, v in self.recorder.headers.items()}

    def test_a_read_through_the_frame_carries_the_key(self) -> None:
        self.client.get("/gpf/api/cases")
        self.assertEqual(self._forwarded().get("x-gpf-key"), gpf_bridge.api_key())

    def test_a_write_through_the_frame_carries_the_key(self) -> None:
        self.client.post("/gpf/api/cases/abc/dispose", json={})
        self.assertEqual(self._forwarded().get("x-gpf-key"), gpf_bridge.api_key())

    def test_the_browser_s_own_key_header_is_dropped_and_replaced(self) -> None:
        """A page in the frame can set any header it likes; none of them is this one."""
        self.client.get("/gpf/api/cases", headers={"X-GPF-Key": "forged-by-the-browser"})
        forwarded = self._forwarded()
        self.assertEqual(forwarded.get("x-gpf-key"), gpf_bridge.api_key())
        self.assertNotIn("forged-by-the-browser", forwarded.values())

    def test_the_cookie_and_the_token_still_do_not_travel(self) -> None:
        """The key replaces nothing: what was dropped before is dropped still."""
        self.client.get("/gpf/api/cases", headers={"Authorization": "Bearer t", "X-GPF-Officer": "dag"})
        forwarded = self._forwarded()
        self.assertNotIn("authorization", forwarded)
        self.assertNotIn("cookie", forwarded)
        self.assertEqual(forwarded.get("x-gpf-officer"), "ao")      # the signed-in account's, not the browser's

    def test_an_unsigned_request_never_reaches_the_module_with_the_key(self) -> None:
        async def refused(request):
            return None
        self.portal.gpf_signed_in = refused
        r = self.client.get("/gpf/api/cases")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.recorder.headers, {})


class TheBridgePresentsTheKey(unittest.TestCase):
    """The reconciler reaches the module directly, not through the proxy, and needs it too."""

    def test_every_bridge_request_carries_the_key(self) -> None:
        seen: list[urllib.request.Request] = []

        class _Resp:
            status = 200

            def read(self_inner):
                return b"{}"

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        def fake_urlopen(req, timeout=None):
            seen.append(req)
            return _Resp()

        with mock.patch.object(gpf_bridge.urllib.request, "urlopen", fake_urlopen):
            gpf_bridge._request("GET", "/api/cases")
        self.assertEqual(len(seen), 1)
        sent = {k.lower(): v for k, v in seen[0].header_items()}
        self.assertEqual(sent.get(gpf_bridge.GPF_KEY_HEADER.lower()), gpf_bridge.api_key())


class TheTwoSidesAgree(unittest.TestCase):
    """The module's copy and this one must resolve the same key, or the module answers nothing."""

    def _module_apikey(self):
        path = Path(__file__).resolve().parents[1] / "GP" / "backend"
        spec = importlib.util.spec_from_file_location("gpf_apikey_under_test", path / "gpf" / "apikey.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("gpf_apikey_under_test", mod)
        spec.loader.exec_module(mod)
        return mod

    def test_the_header_the_file_and_the_variable_match(self) -> None:
        theirs = self._module_apikey()
        self.assertEqual(theirs.KEY_FILE, gpf_bridge._KEY_FILE)
        self.assertEqual(theirs.HEADER, gpf_bridge.GPF_KEY_HEADER.lower())
        self.assertEqual(theirs.api_key(), gpf_bridge.api_key())
        self.assertTrue(theirs.presented_is_right(gpf_bridge.api_key()))

    def test_the_environment_variable_wins_on_both_sides(self) -> None:
        """Set it where the two run on different hosts; it must be the same name in both."""
        theirs = self._module_apikey()
        with mock.patch.dict("os.environ", {"GPF_API_KEY": "the-same-on-both"}):
            gpf_bridge.forget_key()
            theirs.forget_key()
            self.assertEqual(gpf_bridge.api_key(), "the-same-on-both")
            self.assertEqual(theirs.api_key(), "the-same-on-both")
        gpf_bridge.forget_key()
        theirs.forget_key()
        self.assertNotEqual(gpf_bridge.api_key(), "the-same-on-both")

    def test_the_shared_file_is_readable_by_its_owner_only(self) -> None:
        """It is a credential: created 0600, as the session secret is."""
        gpf_bridge.api_key()                                        # created if it was not there
        mode = gpf_bridge._KEY_FILE.stat().st_mode
        self.assertFalse(mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH),
                         f"{gpf_bridge._KEY_FILE} is {stat.filemode(mode)}")

    def test_the_key_is_resolved_once_and_not_read_per_request(self) -> None:
        """The portal sets this header on dozens of requests per page of scans."""
        gpf_bridge.forget_key()
        gpf_bridge.api_key()
        with mock.patch.object(gpf_bridge, "_read_key", side_effect=AssertionError("read twice")):
            for _ in range(5):
                gpf_bridge.api_key()


class TheExampleEnvExplainsIt(unittest.TestCase):
    def test_the_variable_is_documented(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "deploy" / "pension.env.example").read_text(encoding="utf-8")
        self.assertIn("GPF_API_KEY", text)
        self.assertIn("artifacts/.gpf_api_key", text)


if __name__ == "__main__":
    unittest.main()
