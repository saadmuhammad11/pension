"""The inventory poll stops at sign-out and never asks as nobody (audit 6 Oct 2026, L5).

    python3 -m unittest tests.test_polling_stops_at_sign_out -v

The portal asked the server for the inventory version every 3 seconds for the life of the tab,
signed in or not, and kept the last officer's rows in memory for the next person at the PC.
The portal has no JavaScript test runner, so this reads the two source files the way the
sign-out test does, and the release build's type check keeps them honest.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "portals" / "src" / "shared"


class PollingStops(unittest.TestCase):
    def test_sign_out_stops_the_poll_and_forgets_the_rows(self) -> None:
        inventory = (SRC / "data" / "inventory.ts").read_text()
        stop = inventory[inventory.index("export function stopInventoryPolling"):]
        stop = stop[:stop.index("\n}\n") + 3]
        self.assertIn("clearTimeout(polling)", stop)          # a chained timeout since F16 (9 Oct 2026)
        self.assertIn("removeEventListener('visibilitychange', checkVersion)", stop)
        self.assertIn("removeEventListener('focus', checkVersion)", stop)
        self.assertIn("cache.clear()", stop)

    def test_the_poll_asks_nothing_without_a_session(self) -> None:
        inventory = (SRC / "data" / "inventory.ts").read_text()
        check = inventory[inventory.index("async function checkVersion"):inventory.index("function ensurePolling")]
        self.assertLess(check.index("if (!getToken()) return"), check.index("await get<"))
        self.assertRegex(inventory, r"import \{ getToken \} from '../auth/session'")

    def test_every_way_a_session_ends_stops_the_poll(self) -> None:
        source = (SRC / "auth" / "AuthProvider.tsx").read_text()
        end = source[source.index("const end = useCallback"):source.index("const logout = useCallback")]
        self.assertIn("stopInventoryPolling()", end)          # sign-out, idle timeout and 401 all go through end()
        self.assertRegex(source, r"import \{ stopInventoryPolling \} from '../data/inventory'")
        self.assertEqual(len(re.findall(r"stopInventoryPolling\(\)", source)), 1)


if __name__ == "__main__":
    unittest.main()
