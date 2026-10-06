"""An advance balance nobody could read is not "no advance outstanding" (audit 6 Oct 2026, G4).

    python3 -m unittest gpfund.tests.test_unread_advance_balance -v

Without a re-calculation report, ADV-ACTIVE read the pay slip's advance balance; a balance the
reader left empty went through the same ``if not outstanding`` as a zero and the item passed.
Unread is now a verification task, with the SAP cure, until the figure is on the case.
"""
from __future__ import annotations

import unittest

from gpfund.contracts import CONF, OK, Facts
from gpfund.rules_advances import _adv_active


def _facts(loan_balance) -> Facts:
    return Facts({"kind": "refundable", "docs": {"sanction": {"amount": "50,000"}},
                  "sap": {"payslip": {"gpfBalance": 400000, "loanBalance": loan_balance}, "recalc": None}})


class UnreadAdvanceBalance(unittest.TestCase):
    def test_an_empty_balance_is_a_verification_task(self) -> None:
        for unread in (None, "", "n/a"):
            result = _adv_active(_facts(unread))
            self.assertEqual(result["status"], CONF, unread)
            self.assertIn("could not be read", result["finding"])
            self.assertEqual(result["cure"], {"kind": "sap"})

    def test_a_zero_balance_still_passes(self) -> None:
        for nil in (0, "0"):                                 # the engine's num() reads whole rupees only
            result = _adv_active(_facts(nil))
            self.assertEqual(result["status"], OK, nil)
            self.assertIn("no GPF advance outstanding", result["finding"])

    def test_a_balance_is_still_a_question_without_the_report(self) -> None:
        result = _adv_active(_facts("20,000"))
        self.assertEqual(result["status"], CONF)
        self.assertIn("Rs 20,000", result["finding"])


if __name__ == "__main__":
    unittest.main()
