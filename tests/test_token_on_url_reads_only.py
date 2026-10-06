"""The old register accepts ``?token=`` for reads only (audit 6 Oct 2026, L12).

    python3 -m unittest tests.test_token_on_url_reads_only -v

``?token=`` exists for <img> and EventSource, which cannot send an Authorization header. The old
``/api/*`` routes accepted it on every method, so a decision, a recompute or a removal could be
made by a link alone, with the session token left in proxy logs and browser history.
"""
from __future__ import annotations

import unittest

from tests import test_api_v2 as _v2


class TokenOnTheAddress(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login

    def _token(self) -> str:
        return self.login("admin", "ag")["Authorization"].split(" ", 1)[1]

    def test_a_read_may_carry_the_token_on_the_address(self) -> None:
        r = self.client.get("/api/runs", params={"token": self._token()})
        self.assertEqual(r.status_code, 200, r.text)

    def test_a_write_may_not(self) -> None:
        token = self._token()
        for path in ("/api/runs/0123456789ab/recompute", "/api/runs/0123456789ab/remove",
                     "/api/runs/0123456789ab/decision"):
            r = self.client.post(path, params={"token": token}, json={})
            self.assertEqual(r.status_code, 401, (path, r.text))
            self.assertIn("Authorization header", r.json()["detail"])
        # The same write with the token where it belongs gets past the sign-in check (404: no such run).
        r = self.client.post("/api/runs/0123456789ab/recompute", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 404, r.text)


if __name__ == "__main__":
    unittest.main()
