"""One request body may be 40 MB, and the three places that enforce it agree.

The office set this on 20 October 2026, down from 520 MB. The cap matters because it is
refused from the Content-Length alone, before a byte of the body is read -- a department that
sends a 2 GB file is turned away at the door rather than filling the disk first.

Measured on this box the same day, the largest bundle any department has actually sent is
35.0 MB: a 78-page scan, as a zip and as the merged PDF. So 40 MB is a deliberately tight
door with about 12.5% to spare, and a case much past ~90 pages will be refused.
PENSION_MAX_UPLOAD_MB is the way to open it without a redeploy, which is why the number is
not written into the code.

The three enforcers have to agree. nginx refuses first in production, so a
client_max_body_size below the API's limit means the officer gets nginx's HTML error page
instead of the API's sentence saying what the limit is -- which is how a size limit turns
into a support call.

    python3 -m unittest tests.test_upload_size_cap -v
"""
from __future__ import annotations

import importlib
import os
import re
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
NGINX_CONF = ROOT / "deploy" / "nginx" / "pension.conf"
ENV_EXAMPLE = ROOT / "deploy" / "pension.env.example"


class TheCap(unittest.TestCase):
    def test_it_is_forty_megabytes(self) -> None:
        from api import settings
        self.assertEqual(settings.MAX_REQUEST_BYTES, 40 * 1024 * 1024)

    def test_the_office_can_raise_it_without_a_redeploy(self) -> None:
        from api import settings
        with mock.patch.dict(os.environ, {"PENSION_MAX_UPLOAD_MB": "120"}):
            importlib.reload(settings)
            self.assertEqual(settings.MAX_REQUEST_BYTES, 120 * 1024 * 1024)
        importlib.reload(settings)
        self.assertEqual(settings.MAX_REQUEST_BYTES, 40 * 1024 * 1024)

    def test_a_nonsense_value_falls_back_rather_than_crashing_the_service(self) -> None:
        """Read at import. Raising here takes the whole API down at startup."""
        from api import settings
        with mock.patch.dict(os.environ, {"PENSION_MAX_UPLOAD_MB": "forty"}):
            importlib.reload(settings)
            self.assertEqual(settings.MAX_REQUEST_BYTES, 40 * 1024 * 1024)
        importlib.reload(settings)

    def test_zero_or_negative_cannot_shut_uploads_off_by_accident(self) -> None:
        from api import settings
        for value in ("0", "-5"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"PENSION_MAX_UPLOAD_MB": value}):
                importlib.reload(settings)
                self.assertEqual(settings.MAX_REQUEST_BYTES, 1024 * 1024)
        importlib.reload(settings)


class TheEnforcersAgree(unittest.TestCase):
    def test_the_api_and_the_portal_read_the_same_setting(self) -> None:
        from api import portal_server, server, settings
        self.assertEqual(portal_server.MAX_REQUEST_BYTES, settings.MAX_REQUEST_BYTES)
        self.assertEqual(server.MAX_REQUEST_BYTES, settings.MAX_REQUEST_BYTES)

    def test_nginx_does_not_refuse_before_the_api_does(self) -> None:
        """Below the API's limit and nginx answers first, with its own error page."""
        from api import settings
        text = NGINX_CONF.read_text()
        m = re.search(r"client_max_body_size\s+(\d+)m\s*;", text)
        self.assertIsNotNone(m, "deploy/nginx/pension.conf sets no client_max_body_size")
        self.assertGreaterEqual(int(m.group(1)) * 1024 * 1024, settings.MAX_REQUEST_BYTES,
                                "nginx would refuse an upload the API would have accepted")

    def test_the_setting_is_in_the_example_the_administrator_copies(self) -> None:
        self.assertIn("PENSION_MAX_UPLOAD_MB", ENV_EXAMPLE.read_text())


if __name__ == "__main__":
    unittest.main()
