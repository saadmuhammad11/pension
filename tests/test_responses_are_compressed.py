"""The portal and the API compress what they send.

Nothing did. No middleware on the portal, none on the API, and nginx -- which would normally
do this -- is not in front on this deployment: it still serves the distro's default page
while the portal answers on its own port. So every byte went out raw over a public address.

Measured on 20 October 2026, opening a case's GP Fund examination tab:

    portal js      357.3 KB -> 106.6 KB   70.1%
    portal css      59.0 KB ->  13.4 KB   77.3%
    gpf app.js      43.0 KB ->  13.0 KB   69.8%
    gpf styles      31.5 KB ->   8.6 KB   72.5%
    gpf case json   11.8 KB ->   3.1 KB   73.4%
    ------------------------------------------
    total          502.6 KB -> 144.8 KB   71.2%

which is 2.1s against 0.6s on a 2 Mbit link, before a single round trip is counted. That is
most of why the examination tab felt slow to open: the module's assets are proxied through
the portal, so they were uncompressed too.

The floor is 500 bytes. Below it a gzip header costs more than it saves, and the case screen
polls small JSON replies that are better left alone.

    python3 -m unittest tests.test_responses_are_compressed -v
"""
from __future__ import annotations

import gzip
import unittest


class ThePortalCompresses(unittest.TestCase):
    def test_the_middleware_is_installed_before_the_security_headers(self) -> None:
        """Before, so it wraps the proxied GP Fund assets as well as the portal's own."""
        import inspect
        from api import portal_server
        src = inspect.getsource(portal_server)
        self.assertIn("GZipMiddleware", src)
        gz = src.index("Middleware(GZipMiddleware")
        sec = src.index("Middleware(SecurityHeaders)", gz - 400 if gz > 400 else 0)
        self.assertLess(gz, sec, "gzip must wrap the proxy, so it goes on first")

    def test_the_floor_leaves_small_replies_alone(self) -> None:
        import inspect
        from api import portal_server
        self.assertIn("minimum_size=500", inspect.getsource(portal_server))


class TheApiCompresses(unittest.TestCase):
    def test_the_middleware_is_installed(self) -> None:
        import inspect
        from api import server
        src = inspect.getsource(server)
        self.assertIn("GZipMiddleware", src)
        self.assertIn("minimum_size=500", src)

    def test_a_large_json_reply_comes_back_gzipped(self) -> None:
        try:
            from starlette.testclient import TestClient
        except Exception as exc:                            # pragma: no cover
            self.skipTest(f"no test client: {exc}")
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.middleware.gzip import GZipMiddleware
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        async def big(_request):
            return JSONResponse({"rows": [{"id": i, "text": "x" * 40} for i in range(200)]})

        app = Starlette(routes=[Route("/big", big)],
                        middleware=[Middleware(GZipMiddleware, minimum_size=500)])
        client = TestClient(app)
        r = client.get("/big", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(r.headers.get("content-encoding"), "gzip")
        # and it is really the same payload, not a truncated one
        self.assertEqual(len(r.json()["rows"]), 200)

    def test_a_small_reply_is_left_alone(self) -> None:
        try:
            from starlette.testclient import TestClient
        except Exception as exc:                            # pragma: no cover
            self.skipTest(f"no test client: {exc}")
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.middleware.gzip import GZipMiddleware
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        app = Starlette(routes=[Route("/small", lambda r: JSONResponse({"ok": True}))],
                        middleware=[Middleware(GZipMiddleware, minimum_size=500)])
        r = TestClient(app).get("/small", headers={"Accept-Encoding": "gzip"})
        self.assertIsNone(r.headers.get("content-encoding"))


class TheSavingIsWorthHaving(unittest.TestCase):
    def test_the_portal_bundle_really_does_compress(self) -> None:
        """Guards the premise: if the bundle ever stops compressing, the middleware is cost
        with no benefit and this should be revisited rather than assumed."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        js = sorted((root / "portals" / "dist" / "assets").glob("*.js"), key=lambda p: -p.stat().st_size)
        if not js:
            self.skipTest("no built portal bundle on this machine")
        raw = js[0].read_bytes()
        self.assertLess(len(gzip.compress(raw, 6)) / len(raw), 0.5,
                        "the bundle should compress to well under half")


if __name__ == "__main__":
    unittest.main()
