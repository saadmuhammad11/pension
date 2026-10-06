"""The sign-in token on an address never reaches nginx's access log (audit 6 Oct 2026, S1).

    python3 -m unittest tests.test_nginx_access_log_redacts_token -v

Scan images and the live progress stream carry the token as ?token=..., the one place a browser
cannot put a header. nginx's default log kept every officer's 12-hour token in plain text. The
site now logs with a format whose request line is rewritten to token=[redacted].
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

NGINX = Path(__file__).resolve().parents[1] / "deploy" / "nginx" / "pension.conf"


class AccessLog(unittest.TestCase):
    def _map_pattern(self) -> str:
        m = re.search(r"map \$request_uri \$pension_uri_logged \{\s*~(\S+)\s+\"([^\"]+)\";", NGINX.read_text())
        self.assertIsNotNone(m, "the map that redacts ?token= is missing")
        return m.group(1)

    def test_every_server_block_logs_with_the_redacting_format(self) -> None:
        text = NGINX.read_text()
        self.assertIn("log_format pension", text)
        self.assertIn("$pension_uri_logged", text)
        self.assertNotIn("$request_uri $server_protocol", text)   # the raw request line is never logged
        servers = text.count("\nserver {")
        self.assertEqual(text.count("access_log /var/log/nginx/pension.access.log pension;"), servers)

    def test_the_redaction_pattern_catches_the_token_wherever_it_sits(self) -> None:
        pattern = re.compile(self._map_pattern().replace("(?<", "(?P<"))   # PCRE named group -> Python
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig"
        for uri in (f"/api/v2/cases/abc/runs/def/pages/3?token={token}",
                    f"/api/v2/cases/abc/runs/def/events?since=4&token={token}",
                    f"/api/v2/cases/abc/documents/d1?token={token}&download=1"):
            m = pattern.match(uri)
            self.assertIsNotNone(m, uri)
            logged = f"{m.group('before')}token=[redacted]{m.group('after')}"
            self.assertNotIn(token, logged)
            self.assertIn("token=[redacted]", logged)
            self.assertTrue(logged.startswith(uri.split("?")[0]))
        self.assertIsNone(pattern.match("/api/v2/cases?status_filter=APPROVED&tokens=2"))   # not a token


if __name__ == "__main__":
    unittest.main()
