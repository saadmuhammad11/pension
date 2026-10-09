"""The GP Fund frame cookie is Secure over HTTPS and always in production (audit 6 Oct 2026, L2).

    python3 -m unittest tests.test_gpf_cookie_secure -v

The cookie took its Secure flag from the request's scheme alone, so in production a request that
reached the API without the forwarded-proto header set a cookie the browser would also send over
plain HTTP. In production the flag is now set regardless; the HTTP-only trial is unchanged.
"""
from __future__ import annotations

import unittest
from unittest import mock

from tests import test_api_v2 as _v2

PROD = {"PENSION_ENV": "production"}


class FrameCookie(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide

    def _cookie(self, headers: dict) -> str:
        r = self.client.post("/api/v2/auth/gpf-session", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.headers["set-cookie"].lower()

    def test_https_sets_secure(self) -> None:
        reviewer = self.sa()
        self.assertIn("secure", self._cookie({**reviewer, "X-Forwarded-Proto": "https"}))

    def test_plain_http_in_the_trial_does_not(self) -> None:
        reviewer = self.sa()
        cookie = self._cookie(reviewer)
        self.assertNotIn("secure", cookie)
        for part in ("httponly", "samesite=strict", "path=/gpf"):
            self.assertIn(part, cookie)

    def test_production_sets_secure_whatever_the_request_says(self) -> None:
        reviewer = self.sa()
        with mock.patch.dict("os.environ", PROD):
            cookie = self._cookie(reviewer)                 # plain HTTP, no forwarded-proto header
        self.assertIn("secure", cookie)


if __name__ == "__main__":
    unittest.main()
