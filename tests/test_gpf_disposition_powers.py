"""GP Fund: who may dispose of an observation, and the written grounds every disposition carries.

    python3 -m unittest tests.test_gpf_disposition_powers -v

Business decision G1 (7 Oct 2026) reserved both routes out of a hard stop -- the waiver and the
correction -- to the DAG. Both were opened on 13 Oct 2026: every examining tier waives and
records corrected, hard stops included, because the office needs the Senior Auditor, the
Assistant AO and the Accounts Officer to clear findings on the cases they hold. What survives of
G1 is a written reason on every disposition, recorded under the officer's own name
(docs/pension-rules-decisions.md, 13 Oct 2026). The same day the office reduced both screens to
two buttons -- Approve, which sets the observation aside, and Reject, which leaves it standing --
with one reason box of at least ten characters and nothing else asked. This file was
test_gpf_hard_stop_is_the_dags.py.

The module's own tests (GP/backend/tests/test_service.py) pin the service; this file pins what
the pension side relies on: the permission table, and that both screens -- the module's and the
portal's -- ask for grounds on every disposition and never send an empty one.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "GP" / "backend"))


class ThePermissionTable(unittest.TestCase):
    def test_every_examining_tier_clears_an_observation(self):
        """Office decision of 13 Oct 2026, retiring G1 of 7 Oct 2026.

        Both routes out of an observation are open to all three tiers, on a hard stop as on an
        advisory: waive it, or record it corrected. Upholding was always anyone's.
        """
        from gpf.engine import OFFICERS, may
        by = {o["id"]: o for o in OFFICERS}
        for band in ("da", "ao", "dag"):
            for sev in ("hard", "adv"):
                self.assertTrue(may("waive", sev, by[band]), (band, sev))
                self.assertTrue(may("correct", sev, by[band]), (band, sev))
                self.assertTrue(may("uphold", sev, by[band]), (band, sev))
        self.assertEqual(by["dag"]["level"], 3)

    def test_what_the_bands_still_decide(self):
        """Not everything is open: these two still follow the band."""
        from gpf.engine import OFFICERS, may
        by = {o["id"]: o for o in OFFICERS}
        self.assertFalse(may("verify", None, by["da"]))      # a verification needs the AO or above
        self.assertTrue(may("verify", None, by["ao"]))
        self.assertFalse(may("refer", "hard", by["dag"]))    # nothing above the DAG to refer to

    def test_the_pension_side_maps_the_deputy_ag_to_the_dag_band(self):
        from api.gpf_bridge import OFFICER_FOR_ROLE
        self.assertEqual(OFFICER_FOR_ROLE.get("AG_DAG"), "dag")
        self.assertEqual(OFFICER_FOR_ROLE.get("AG_REVIEWER"), "dag")   # the AG's desk acts as the DAG (decision S10, 9 Oct 2026)
        self.assertEqual(OFFICER_FOR_ROLE.get("AG_SENIOR_AUDITOR"), "da")
        self.assertEqual(OFFICER_FOR_ROLE.get("AG_AO"), "ao")


class TheScreensAskForAReason(unittest.TestCase):
    def test_the_portal_sends_no_empty_reason(self):
        # GP Fund dispositions are made in the module's own frame (GpfFindings.tsx, which nothing
        # imported, was removed on 9 Oct 2026); the pension findings screen asks for grounds the same way.
        tsx = (ROOT / "portals/src/shared/screens/CaseFindings.tsx").read_text()
        self.assertNotIn("onDispose('uphold', '', '')", tsx)
        self.assertIn("ground.trim().length < MIN_REASON", tsx)
        self.assertIn("export const MIN_REASON = 10", tsx)
        # Two buttons, in the officer's words (13 Oct 2026).
        self.assertIn(">\n          Approve\n        </button>", tsx)
        self.assertIn(">\n          Reject\n        </button>", tsx)
        self.assertFalse((ROOT / "portals/src/shared/screens/GpfFindings.tsx").exists())

    def test_the_module_s_own_screen_asks_too(self):
        js = (ROOT / "GP/backend/web/js/app.js").read_text()
        self.assertNotIn("'uphold', '', ''", js)
        # The minimum is held by the panel the reason is typed into (ui.inlineNote), which the
        # module's screen opens with `min: MIN_REASON`. It was a prompt() window until 23 Oct 2026.
        self.assertIn("min: MIN_REASON", js)
        ui = (ROOT / "GP/backend/web/js/ui.js").read_text()
        self.assertIn("if (text.length < min)", ui)
        self.assertIn("const MIN_REASON = 10", js)
        self.assertIn("'Approve'", js)
        self.assertIn("'Reject'", js)
        self.assertNotIn("Refer upward", js)                       # one pair of buttons, not three

    def test_both_sides_hold_the_same_minimum(self):
        from gpf.service import MIN_GROUND
        from api.dispositions import MIN_GROUND as PENSION_MIN
        self.assertEqual(MIN_GROUND, 10)
        self.assertEqual(PENSION_MIN, 10)


if __name__ == "__main__":
    unittest.main()
