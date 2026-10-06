"""Uploads are refused before their bodies are read, through the portal too (audit 6 Oct 2026, Medium).

    python3 -m unittest tests.test_upload_early_refusals -v

Two gaps: FastAPI parses a multipart body before the route's sign-in check runs, so an anonymous
caller made the API spool up to 520 MB per request on its way to a 401; and the portal's proxy
dropped Content-Length and sent the body on chunked, so the API's refusal-by-length never fired
behind it.
"""
from __future__ import annotations

import http.server
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests import test_api_v2 as _v2


class AnonymousUploadIsNotParsed(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login

    def test_no_session_no_parsing(self) -> None:
        from starlette import formparsers
        parsed = []
        real = formparsers.MultiPartParser.parse

        async def counting(self_):
            parsed.append(1)
            return await real(self_)
        with mock.patch.object(formparsers.MultiPartParser, "parse", counting):
            for headers in ({}, {"Authorization": "Bearer forged.token.value"}):
                r = self.client.post("/api/v2/cases", headers=headers, data={"case_type": "FRESH_SELF"},
                                     files=[("files", ("case.pdf", io.BytesIO(_v2.PDF), "application/pdf"))])
                self.assertEqual(r.status_code, 401, r.text)
            self.assertEqual(parsed, [], "the body of an anonymous upload was parsed")
            police = self.login("punjab-police", "punjab-police")
            r = self.client.post("/api/v2/cases", headers=police, data={"case_type": "FRESH_SELF"},
                                 files=[("files", ("case.pdf", io.BytesIO(_v2.PDF), "application/pdf"))])
            self.assertEqual(r.status_code, 201, r.text)
            self.assertEqual(len(parsed), 1)


class ProxyKeepsTheLength(unittest.TestCase):
    def setUp(self) -> None:
        from starlette.testclient import TestClient
        from api import portal_server
        heard = self.heard = []

        class Upstream(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                heard.append({"length": self.headers.get("Content-Length"),
                              "chunked": "chunked" in (self.headers.get("Transfer-Encoding") or "")})
                if self.headers.get("Content-Length"):
                    self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        self.upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self._tmp = tempfile.TemporaryDirectory()
        (Path(self._tmp.name) / "index.html").write_text("<!doctype html><html></html>")
        self.portal_server = portal_server
        app = portal_server.PortalApp(dist=Path(self._tmp.name),
                                      api=f"http://127.0.0.1:{self.upstream.server_address[1]}",
                                      trust_port_header=False)
        self.client = TestClient(app.app)

    def tearDown(self) -> None:
        self.upstream.shutdown()
        self.upstream.server_close()
        self._tmp.cleanup()

    def test_the_api_sees_the_length_and_an_oversized_body_stops_at_the_portal(self) -> None:
        body = b"x" * 5000
        with self.client as c:
            r = c.post("/api/v2/cases", content=body, headers={"Content-Type": "application/octet-stream"})
            self.assertEqual(r.status_code, 201)
            self.assertEqual(self.heard, [{"length": "5000", "chunked": False}])
            with mock.patch.object(self.portal_server, "MAX_REQUEST_BYTES", 4000):
                r = c.post("/api/v2/cases", content=body, headers={"Content-Type": "application/octet-stream"})
            self.assertEqual(r.status_code, 413)
            self.assertEqual(len(self.heard), 1, "the upstream never heard the oversized request")


if __name__ == "__main__":
    unittest.main()
