"""The GP Fund frame cookie is Secure where there is TLS, not merely where production is on.

20 October 2026. A GP Fund case had been examined, and the examination tab answered

    "The GP Fund module opens from a case in the pension portal, for the Accountant
     General's desk. Sign in at the portal and open the case there."

to an officer who had done exactly that. api/portal_server.py returns that page whenever the
frame cookie is absent, and the cookie was absent because the browser had thrown it away:
set_cookie carried `secure=production()`, and a browser silently DISCARDS a Secure cookie that
arrives over plain HTTP. It does not warn and it never sends it back.

The reasoning behind `secure=production()` is written in the code: "always in production,
where nginx is the only way in" (audit of 6 Oct 2026, L2). The premise is the problem -- on
this box nginx serves the distro's default page and the portal answers on its own port over
HTTP, so production mode was on and TLS was not. The flag now follows what is true rather
than what is intended.

Setting PENSION_BEHIND_TLS=0 weakens nothing TLS was protecting, because there is no TLS: the
sign-in password and the bearer token already cross the same connection in clear. It stops
the flag defending a connection that does not exist at the cost of a feature that does.

    python3 -m unittest tests.test_gpf_cookie_follows_real_tls -v
"""
from __future__ import annotations

import importlib
import os
import unittest
from unittest import mock

from api import settings


class TheSetting(unittest.TestCase):
    def tearDown(self) -> None:
        importlib.reload(settings)

    def test_production_still_implies_tls_when_nothing_says_otherwise(self) -> None:
        """A correct deployment sets nothing and keeps the behaviour the audit asked for."""
        with mock.patch.dict(os.environ, {"PENSION_ENV": "production"}, clear=False):
            os.environ.pop("PENSION_BEHIND_TLS", None)
            self.assertTrue(settings.behind_tls())

    def test_a_trial_without_tls_is_not_claimed_to_have_it(self) -> None:
        with mock.patch.dict(os.environ, {"PENSION_ENV": ""}, clear=False):
            os.environ.pop("PENSION_BEHIND_TLS", None)
            self.assertFalse(settings.behind_tls())

    def test_a_deployment_may_state_the_truth_either_way(self) -> None:
        for env, flag, expected in (("production", "0", False), ("", "1", True),
                                    ("production", "1", True), ("", "0", False)):
            with self.subTest(env=env, flag=flag), \
                    mock.patch.dict(os.environ, {"PENSION_ENV": env, "PENSION_BEHIND_TLS": flag}):
                self.assertIs(settings.behind_tls(), expected)


class TheCookie(unittest.TestCase):
    """What the browser is actually sent."""

    def _secure_flag(self, *, https: bool, behind_tls: bool) -> bool:
        """Reproduce the expression in api/v2.gpf_session without standing a server up."""
        with mock.patch.object(settings, "behind_tls", lambda: behind_tls):
            return https or settings.behind_tls()

    def test_https_always_gets_a_secure_cookie(self) -> None:
        self.assertTrue(self._secure_flag(https=True, behind_tls=False))
        self.assertTrue(self._secure_flag(https=True, behind_tls=True))

    def test_plain_http_behind_tls_still_gets_one(self) -> None:
        """nginx terminates TLS and proxies on loopback: the browser's connection IS secure."""
        self.assertTrue(self._secure_flag(https=False, behind_tls=True))

    def test_plain_http_with_no_tls_anywhere_gets_a_cookie_the_browser_will_keep(self) -> None:
        """The case this fixes. A Secure cookie here is discarded, and the frame breaks."""
        self.assertFalse(self._secure_flag(https=False, behind_tls=False))

    def test_the_route_reads_the_flag_and_not_production(self) -> None:
        """Pins the fix itself: reverting to settings.production() reintroduces the fault."""
        import inspect
        from api import v2
        src = inspect.getsource(v2.gpf_session)
        self.assertIn("settings.behind_tls()", src)
        self.assertNotIn("settings.production()", src)


class TheOperatorIsTold(unittest.TestCase):
    def test_production_without_tls_warns_at_every_start(self) -> None:
        """A security posture, not a preference: it must not go quiet."""
        import inspect
        from api import server
        src = inspect.getsource(server._production_startup_checks)
        self.assertIn("behind_tls", src)
        self.assertIn("clear", src.lower())


if __name__ == "__main__":
    unittest.main()
