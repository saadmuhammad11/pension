"""The portal server: the right portal config on each port, the bundle served, secrets never.

    python3 -m unittest tests.test_portal_server -v
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from api import portal_server
from api.departments import AG_PORTAL_PORT, BY_SLUG


class PortalServer(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-portals-")
        dist = Path(self._tmp.name)
        (dist / "assets").mkdir()
        (dist / "assets" / "index-abc.js").write_text("console.log('bundle')")
        (dist / "index.html").write_text("<!doctype html><html><head><title>x</title></head><body><div id=root></div></body></html>")
        (dist / "tmc-logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (dist / "credentials.html").write_text("SECRET")
        self.portal = portal_server.PortalApp(dist=dist, api="http://127.0.0.1:1", trust_port_header=True)
        self.portal.bound = [AG_PORTAL_PORT, 5182]
        self.client = TestClient(self.portal.app)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _config(self, port: int) -> dict:
        r = self.client.get("/", headers={"X-Portal-Port": str(port)})
        self.assertEqual(r.status_code, 200)
        m = re.search(r"window\.__PORTAL__=(\{.*?\})</script>", r.text)
        self.assertIsNotNone(m, r.text)
        return json.loads(m.group(1))

    def test_each_port_gets_its_own_portal_config(self) -> None:
        ag = self._config(AG_PORTAL_PORT)
        self.assertEqual((ag["kind"], ag["slug"]), ("ag", "ag"))
        agri = self._config(BY_SLUG["agriculture"].port)
        self.assertEqual((agri["kind"], agri["slug"], agri["code"]), ("department", "agriculture", "AGRICULTURE"))
        self.assertEqual(agri["theme"]["primary"], "#245C2E")
        police = self._config(BY_SLUG["ctd"].port)
        self.assertEqual(police["theme"]["primary"], "#140D44")
        self.assertTrue(police["is_police"])

    def test_deep_links_get_the_page_and_assets_are_served(self) -> None:
        r = self.client.get("/cases/abc", headers={"X-Portal-Port": "5182"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("__PORTAL__", r.text)
        self.assertEqual(self.client.get("/assets/index-abc.js").status_code, 200)
        self.assertEqual(self.client.get("/tmc-logo.png").status_code, 200)

    def test_every_response_carries_the_security_headers_and_the_config_script_its_nonce(self) -> None:
        r = self.client.get("/", headers={"X-Portal-Port": str(AG_PORTAL_PORT)})
        for h in ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy", "Content-Security-Policy"):
            self.assertIn(h, r.headers, h)
        self.assertIn(f"'nonce-{portal_server.NONCE}'", r.headers["Content-Security-Policy"])
        self.assertIn(f'<script nonce="{portal_server.NONCE}">', r.text)
        self.assertEqual(self.client.get("/assets/index-abc.js").headers.get("X-Frame-Options"), "DENY")

    def test_secrets_in_dist_are_never_served(self) -> None:
        r = self.client.get("/credentials.html")
        self.assertEqual(r.status_code, 404)

    def test_the_sign_in_sheet_is_on_the_ag_port_only(self) -> None:
        from unittest import mock
        from api import db
        sheet = Path(self._tmp.name) / "credentials.html"
        sheet.write_text("<html>Pension portals — sign-in credentials<script>var q=1;</script></html>")
        with mock.patch.object(db, "CREDENTIALS_HTML", sheet):
            r = self.client.get("/start.html", headers={"X-Portal-Port": str(AG_PORTAL_PORT)})
            self.assertEqual(r.status_code, 200)
            self.assertIn("sign-in credentials", r.text)
            # The sheet's search box is an inline script: it runs only with this server's CSP nonce.
            from api.portal_server import NONCE
            self.assertIn(f'<script nonce="{NONCE}">', r.text)
            self.assertIn(f"'nonce-{NONCE}'", r.headers["content-security-policy"])
            self.assertEqual(self.client.get("/start.html", headers={"X-Portal-Port": "5182"}).status_code, 404)

    def test_portals_listing_and_unknown_port(self) -> None:
        r = self.client.get("/__portals")
        self.assertEqual(r.json()["bound"], [AG_PORTAL_PORT, 5182])
        self.assertEqual(self._config(5999)["kind"], "unknown")

    def test_api_proxy_reports_an_unreachable_backend_as_502(self) -> None:
        with self.client:                                      # runs startup: the aiohttp session
            r = self.client.get("/api/v2/portals", headers={"X-Portal-Port": "5182"})
        self.assertEqual(r.status_code, 502)
        self.assertIn("not reachable", r.json()["detail"])

    def test_all_ports_are_unique_and_include_the_ag_portal(self) -> None:
        ports = portal_server.all_ports()
        self.assertEqual(len(ports), len(set(ports)), "duplicate port")
        self.assertIn(AG_PORTAL_PORT, ports)
        self.assertEqual(len(ports), 1 if portal_server.SINGLE_PORTAL else 87)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class GpfProxyPaths(PortalServer):
    """The path under /gpf/ is normalised once and used for both the check and the forwarded
    request; dot segments and escapes are refused (frontend review F3, 9 Oct 2026)."""

    class _NoModule:
        """A session whose every request fails to connect, as with nothing on 127.0.0.1:1."""
        def request(self, *a, **k):
            import aiohttp

            class _Ctx:
                async def __aenter__(self_inner):
                    raise aiohttp.ClientConnectionError("no module")

                async def __aexit__(self_inner, *exc):
                    return False
            return _Ctx()

    def _signed_in(self) -> None:
        async def yes(request):
            return "ao|Officer"
        self.portal.gpf_signed_in = yes
        self.portal.session = self._NoModule()

    def test_dot_segments_escapes_and_empty_segments_are_refused(self) -> None:
        g = portal_server.gpf_subpath
        seen_checks: list = []

        async def check(request, sub):
            seen_checks.append(sub)
            return None
        for bad in ("api/cases/nonexistent/../REAL/dispose", "api/cases/%2e%2e/REAL/dispose", "api/cases//REAL/dispose",
                    "api/cases/a%252e/dispose", "api/cases/./REAL/dispose", "api/cases/REAL%5c../dispose", "api/cases/x%00/y"):
            self.assertIsNone(g(bad), bad)
        # Starlette hands the route the path decoded once, so what reaches gpf_subpath for
        # "a%252e" is "a%2e" -- an escape left over, refused.
        self.assertEqual(g("api/cases/abc/dispose"), "/api/cases/abc/dispose")
        # Through the server: an escape the browser would not collapse reaches the route and is refused
        # before the action check or any request upstream (the fake session would answer 502).
        self._signed_in()
        self.portal.gpf_act_refused = check
        for bad in ("api/cases/%2e%2e/REAL/dispose", "api/cases/REAL%5c../dispose", "api/cases/x%00/y"):
            r = self.client.post(f"/gpf/{bad}", json={})
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn("not a valid GP Fund path", r.text)
        self.assertEqual(seen_checks, [])                         # refused before the action check

    def test_the_normalised_path_is_what_the_check_and_the_upstream_see(self) -> None:
        self._signed_in()
        seen = {}

        async def check(request, sub):
            seen["check"] = sub
            return None
        self.portal.gpf_act_refused = check
        r = self.client.post("/gpf/api/cases/ab%20c/dispose", json={})
        self.assertEqual(seen["check"], "/api/cases/ab c/dispose")
        self.assertEqual(r.status_code, 502)                  # the path was accepted; no module behind the fake session
