"""GP Fund: who clears a hard stop, and the written grounds every disposition carries.

    python3 -m unittest tests.test_gpf_hard_stop_is_the_dags -v

Business decision G1 (7 Oct 2026) reserved a hard stop to the DAG. Its **waiver** half was
reversed on 13 Oct 2026: every examining tier waives, hard stops included, because the office
needs the Senior Auditor, the Assistant AO and the Accounts Officer to clear findings on the
cases they hold. Recording a hard stop **corrected** is still the DAG's, and the grounds and the
authority are still required of everyone (docs/pension-rules-decisions.md, 13 Oct 2026).

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
    def test_only_level_3_records_a_hard_stop_corrected(self):
        from gpf.engine import OFFICERS, may, who_can
        by = {o["id"]: o for o in OFFICERS}
        self.assertFalse(may("correct", "hard", by["ao"]))
        self.assertFalse(may("correct", "hard", by["da"]))
        self.assertTrue(may("correct", "hard", by["dag"]))
        self.assertIn("Deputy Accountant General", who_can("correct", "hard"))
        self.assertTrue(may("correct", "adv", by["ao"]))             # an advisory: the Accounts Officer still may
        self.assertTrue(may("uphold", "hard", by["da"]))              # anyone may uphold
        self.assertEqual(by["dag"]["level"], 3)

    def test_every_examining_tier_waives_a_hard_stop(self):
        """Office decision of 13 Oct 2026, reversing the waiver half of G1."""
        from gpf.engine import OFFICERS, may
        by = {o["id"]: o for o in OFFICERS}
        for band in ("da", "ao", "dag"):
            self.assertTrue(may("waive", "hard", by[band]), band)
            self.assertTrue(may("waive", "adv", by[band]), band)

    def test_the_pension_side_maps_the_deputy_ag_to_the_dag_band(self):
        from api.gpf_bridge import OFFICER_FOR_ROLE
        self.assertEqual(OFFICER_FOR_ROLE.get("AG_DAG"), "dag")
        self.assertEqual(OFFICER_FOR_ROLE.get("AG_REVIEWER"), "dag")   # the AG's desk acts as the DAG (decision S10, 9 Oct 2026)
        self.assertEqual(OFFICER_FOR_ROLE.get("AG_SENIOR_AUDITOR"), "da")
        self.assertEqual(OFFICER_FOR_ROLE.get("AG_AO"), "ao")


class TheScreensAskForGrounds(unittest.TestCase):
    def test_the_portal_sends_no_empty_grounds(self):
        # GP Fund dispositions are made in the module's own frame (GpfFindings.tsx, which nothing
        # imported, was removed on 9 Oct 2026); the pension findings screen asks for grounds the same way.
        tsx = (ROOT / "portals/src/shared/screens/CaseFindings.tsx").read_text()
        self.assertNotIn("onDispose('uphold', '', '')", tsx)
        self.assertIn("ground.trim().length < 15", tsx)
        self.assertFalse((ROOT / "portals/src/shared/screens/GpfFindings.tsx").exists())

    def test_the_module_s_own_screen_asks_too(self):
        js = (ROOT / "GP/backend/web/js/app.js").read_text()
        self.assertNotIn("'uphold', '', ''", js)
        self.assertNotIn("'refer', '', ''", js)
        self.assertIn("ground.text.length < 15", js)               # the prompt's text, trimmed by noteFromPrompt (F1)

    def test_the_service_refuses_short_grounds(self):
        from gpf.service import MIN_GROUND
        self.assertEqual(MIN_GROUND, 15)


if __name__ == "__main__":
    unittest.main()
