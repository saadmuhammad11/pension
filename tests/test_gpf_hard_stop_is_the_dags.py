"""GP Fund: only the DAG clears a hard stop, and every disposition carries written grounds (business decision G1, 7 Oct 2026).

    python3 -m unittest tests.test_gpf_hard_stop_is_the_dags -v

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
    def test_only_level_3_clears_a_hard_stop(self):
        from gpf.engine import OFFICERS, may, who_can
        by = {o["id"]: o for o in OFFICERS}
        for action in ("waive", "correct"):
            self.assertFalse(may(action, "hard", by["ao"]), action)
            self.assertFalse(may(action, "hard", by["da"]), action)
            self.assertTrue(may(action, "hard", by["dag"]), action)
            self.assertIn("Deputy Accountant General", who_can(action, "hard"))
        self.assertTrue(may("correct", "adv", by["ao"]))             # an advisory: the Accounts Officer still may
        self.assertTrue(may("uphold", "hard", by["da"]))              # anyone may uphold
        self.assertEqual(by["dag"]["level"], 3)

    def test_the_pension_side_maps_the_deputy_ag_to_the_dag_band(self):
        from api.gpf_bridge import OFFICER_FOR_ROLE
        self.assertEqual(OFFICER_FOR_ROLE.get("AG_DAG"), "dag")
        self.assertEqual(OFFICER_FOR_ROLE.get("AG_REVIEWER"), "ao")


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
