"""A department sees no AI output, on any screen (28 Sep 2026 decision; audit 6 Oct 2026, Medium).

    python3 -m unittest tests.test_ddo_sees_no_ai_output -v

The case screen already hid the run's verdict, but the dashboard statistics carried the engine's
verdict counts, its findings histogram and the papers it found missing, and the verification's
summary remark ("... engine verdict hold, 1 HIGH finding(s)") reached the department in the case
history, the register's last event and the inventory rows.
"""
from __future__ import annotations

import json
import unittest

from tests import test_api_v2 as _v2


class DepartmentView(unittest.TestCase):
    report_to_write = _v2.FLAGS_ONLY_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def test_no_engine_verdict_or_finding_reaches_the_department(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        self.verify(reviewer, case_id)

        # The AG sees the engine's summary and the statistics.
        ag_case = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()
        engine_remark = next(e["remark"] for e in ag_case["events"] if e["action"] == "CHECK_DONE")
        self.assertTrue(engine_remark)
        ag_stats = self.client.get("/api/v2/stats", headers=reviewer).json()
        for key in ("verdicts", "high_flags", "deficiencies"):
            self.assertIn(key, ag_stats)

        # The department sees none of it, wherever it looks.
        seen = {
            "case": self.client.get(f"/api/v2/cases/{case_id}", headers=police).json(),
            "register": self.client.get("/api/v2/cases", headers=police).json(),
            "inventory": self.client.get("/api/v2/inventory", headers=police).json(),
            "stats": self.client.get("/api/v2/stats", headers=police).json(),
        }
        for name, body in seen.items():
            text = json.dumps(body)
            self.assertNotIn(engine_remark, text, name)
            for word in ("HIGH", "Unrecorded recovery", "HOLD", "RULE-UNDECLARED"):
                self.assertNotIn(word, text, f"{name} shows {word!r}")
        for key in ("verdicts", "high_flags", "deficiencies"):
            self.assertNotIn(key, seen["stats"])
        done = next(e for e in seen["case"]["events"] if e["action"] == "CHECK_DONE")
        self.assertEqual(done["remark"], "The verification is complete; the case is with the Office of the Accountant General.")
        self.assertEqual(seen["case"]["status"], "UNDER_REVIEW")


if __name__ == "__main__":
    unittest.main()
