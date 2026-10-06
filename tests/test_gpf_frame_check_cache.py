"""The portal's memory of a frame cookie's sign-in check is short and ends at sign-out (audit 6 Oct 2026, L11).

    python3 -m unittest tests.test_gpf_frame_check_cache -v

A "yes" from the API for the GP Fund frame cookie was remembered for 30 seconds, so for half a
minute after signing out (or being disabled) the frame's reads still went through. The memory is
now 10 seconds, and a sign-out through the portal forgets the cookie's entry at once.
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from starlette.testclient import TestClient

from api import portal_server
from api.departments import AG_PORTAL_PORT


class _Upstream:
    """The least an aiohttp response needs to look like for the proxy."""
    status = 200
    headers = {"content-type": "application/json"}

    class content:
        @staticmethod
        async def iter_any():
            yield b'{"ok": true}'

    def release(self) -> None:
        pass


class FrameCheckCache(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-frame-")
        dist = Path(self._tmp.name)
        (dist / "index.html").write_text("<!doctype html><html><body></body></html>")
        self.portal = portal_server.PortalApp(dist=dist, api="http://127.0.0.1:1", trust_port_header=True)
        self.portal.bound = [AG_PORTAL_PORT]
        self.client = TestClient(self.portal.app)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_the_memory_is_short(self) -> None:
        self.assertLessEqual(portal_server.GPF_CHECK_TTL_S, 10)

    def test_a_remembered_yes_is_used_until_it_lapses(self) -> None:
        async def run() -> tuple[str | None, str | None]:
            now = asyncio.get_running_loop().time()
            self.portal._gpf_ok["tok"] = (now + portal_server.GPF_CHECK_TTL_S, "ao")
            request = SimpleNamespace(cookies={"pension_gpf": "tok"})
            fresh = await self.portal.gpf_signed_in(request)
            self.portal._gpf_ok["tok"] = (now - 1, "ao")               # lapsed: asked again, API down -> None
            self.portal.session = None
            lapsed = await self.portal.gpf_signed_in(request)
            return fresh, lapsed
        self.assertEqual(asyncio.run(run()), ("ao", None))

    def test_signing_out_through_the_portal_forgets_the_cookie_at_once(self) -> None:
        with self.client:                                             # startup: the aiohttp session exists
            loop = asyncio.new_event_loop()
            far_ahead = loop.time() + 10_000                          # the loop clock the cache is kept in
            loop.close()
            self.portal._gpf_ok["tok"] = (far_ahead, "ao")
            self.portal._gpf_ok["other"] = (far_ahead, "dag")

            async def fake_request(method, url, **kw):
                return _Upstream()

            with mock.patch.object(self.portal.session, "request", fake_request):
                r = self.client.post("/api/v2/auth/logout", cookies={"pension_gpf": "tok"},
                                     headers={"X-Portal-Port": str(AG_PORTAL_PORT)})
            self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("tok", self.portal._gpf_ok)                   # this browser's frame sign-in is gone
        self.assertIn("other", self.portal._gpf_ok)                    # nobody else's is


if __name__ == "__main__":
    unittest.main()
