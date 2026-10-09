"""The served rules: an advance balance nobody could read is a question, not "no advance" (G4,
ported to GP/backend/gpf/rules_family.py on 9 Oct 2026, review C2). The fix of 6 Oct went into
GP/gpfund/rules_advances.py, which the served backend never imports."""
from gpf.rules_family import _adv_active


def _facts(loan_balance):
    return {"kind": "refundable", "docs": {"sanction": {"amount": 50000}},
            "sap": {"payslip": {"gpfBalance": 400000, "loanBalance": loan_balance}, "recalc": None}}


def test_an_unread_balance_is_a_verification_task_with_the_sap_cure():
    for unread in (None, "", "n/a"):
        r = _adv_active(_facts(unread))
        assert r["status"] == "conf", unread
        assert "could not be read" in r["finding"]
        assert r["cure"] == {"kind": "sap"}


def test_a_zero_balance_still_passes_and_a_figure_is_still_a_question():
    for nil in (0, "0", 0.0):
        assert _adv_active(_facts(nil))["status"] == "ok", nil
    r = _adv_active(_facts("20,000"))
    assert r["status"] == "conf" and "Rs 20,000" in r["finding"]
