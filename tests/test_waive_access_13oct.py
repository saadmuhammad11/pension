"""Who is offered the waive and uphold controls, and who may use them (13 October 2026).

    /home/tmc/vllm_env/bin/python3 -m unittest tests.test_waive_access_13oct -v

The screen used to decide from the account's role alone, so every AG account was shown the
controls on every case and all but the tier holding it got a 409 on the press -- the officers
reported it as a waive button that did nothing. The server now answers the question itself, with
the same conditions it enforces on the way in, and the screen asks.

The rule on the pension side is unchanged (confirmed 13 Oct 2026): a finding is disposed of while
the case is under review, on its current examination, by the tier that holds it. The AG's desk and
the Deputy AG are bound by no tier.
"""
from __future__ import annotations

import unittest

from tests import test_api_v2 as _v2


class MayDisposeFollowsTheHoldingTier(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify
    sa = _v2.V2Test.sa
    aao = _v2.V2Test.aao
    ao = _v2.V2Test.ao

    def _case(self) -> str:
        ddo = self.login("punjab-police", "punjab-police")
        return self.create(ddo)["case"]["id"]

    def _may(self, case_id: str, headers: dict):
        r = self.client.get(f"/api/v2/cases/{case_id}", headers=headers)
        if r.status_code != 200:
            return r.status_code
        return r.json()["may_dispose"]

    def test_only_the_holding_tier_is_offered_the_controls(self) -> None:
        case_id = self._case()
        sa, aao = self.sa(), self.aao()

        # Filed, not yet verified: nothing to dispose of, and the case is not under review.
        self.assertIs(self._may(case_id, sa), False)

        self.verify(sa, case_id)
        self.assertIs(self._may(case_id, sa), True)        # the Senior Auditor holds it
        self.assertEqual(self._may(case_id, aao), 403)     # and it has not reached the AAO at all

        # Once the Senior Auditor forwards it, the controls move with the case.
        r = self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa,
                             json={"remark": "Papers complete; no finding."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIs(self._may(case_id, sa), False)       # no longer the Senior Auditor's
        self.assertIs(self._may(case_id, aao), True)

    def test_the_ag_desk_is_bound_by_no_tier(self) -> None:
        case_id = self._case()
        sa = self.sa()
        self.verify(sa, case_id)
        reviewer = self.login("ag.reviewer", "ag")
        self.assertIs(self._may(case_id, reviewer), True)

    def test_the_department_is_never_offered_them(self) -> None:
        case_id = self._case()
        ddo = self.login("punjab-police", "punjab-police")
        self.assertIs(self._may(case_id, ddo), False)

    def test_the_answer_matches_what_the_write_path_allows(self) -> None:
        """The whole point: if the screen offers it, the press must not 409."""
        case_id = self._case()
        sa = self.sa()
        self.verify(sa, case_id)
        c = self.client.get(f"/api/v2/cases/{case_id}", headers=sa).json()
        self.assertIs(c["may_dispose"], True)
        run_id = c["latest_run"]["run_id"]
        # An unknown finding: past every gate, refused only for what it names. A 403/409 here
        # would mean the screen offered a control the server would have refused.
        r = self.client.post(f"/api/v2/cases/{case_id}/runs/{run_id}/dispositions", headers=sa,
                             json={"flag_id": "F-404", "action": "WAIVE", "ground": "x" * 20})
        self.assertEqual(r.status_code, 404, r.text)
        self.assertIn("no finding", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
