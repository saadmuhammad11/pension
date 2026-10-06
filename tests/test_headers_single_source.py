"""A response header is set by nginx or by the application, never by both (audit 6 Oct 2026, L3).

    python3 -m unittest tests.test_headers_single_source -v

The portal server sets X-Frame-Options DENY and Referrer-Policy no-referrer on every response;
nginx added X-Frame-Options SAMEORIGIN and Referrer-Policy same-origin on top, so browsers got
two of each and applied whichever they chose. nginx now adds only what the application cannot
know: that the site is served over TLS (HSTS).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

NGINX = Path(__file__).resolve().parents[1] / "deploy" / "nginx" / "pension.conf"


class Headers(unittest.TestCase):
    def test_nginx_adds_only_what_the_application_cannot_know(self) -> None:
        from api import portal_server
        nginx_headers = {m.lower() for m in re.findall(r"^\s*add_header\s+(\S+)", NGINX.read_text(), re.M)}
        app_headers = ({k.lower() for k in portal_server.SECURITY_HEADERS}
                       | {k.lower() for k in portal_server.GPF_SECURITY_HEADERS})
        self.assertEqual(nginx_headers & app_headers, set())
        self.assertEqual(nginx_headers, {"strict-transport-security"})


if __name__ == "__main__":
    unittest.main()
