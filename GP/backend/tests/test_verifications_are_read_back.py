"""A recorded verification must change what the officer is shown.

23 Oct 2026. Pressing "Record verified" and typing a note did nothing visible on some
observations: the note was stored, the case re-ran, and the same observation came back
wearing the same button. The store, the route and the browser were all correct -- the
fact was written to ``F["verifications"]`` every time. Five rules offered the button and
then never read the answer:

    ADV-LIMIT, FP-OLDAC, DEATH-HEIRS, BT-ADV (rules_family), DEATH-CLAIM (rules_custom)

A rule that offers a cure owns the other half of it. The first test here is the general
one -- every vid offered anywhere is read back somewhere -- and the rest walk the five.

    python3 -m pytest tests/test_verifications_are_read_back.py -q
"""
from __future__ import annotations

import ast
import pathlib

from gpf.rules_custom import _death_claim
from gpf.rules_family import _adv_limit, _bt_proforma, _death_heirs, _fp_oldac

RULES = sorted(pathlib.Path(__file__).resolve().parent.parent.glob("gpf/rules*.py"))


def _offered_and_read() -> tuple[dict, set]:
    """Every vid a cure offers, and every vid a rule reads back, across the rule modules."""
    offered: dict[str, str] = {}
    read: set[str] = set()
    for path in RULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = {k.value: v for k, v in zip(node.keys, node.values)
                        if isinstance(k, ast.Constant)}
                kind = keys.get("kind")
                if isinstance(kind, ast.Constant) and kind.value == "verify" and "vid" in keys:
                    offered[ast.unparse(keys["vid"])] = f"{path.name}:{node.lineno}"
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "verified" and len(node.args) == 2):
                read.add(ast.unparse(node.args[1]))
    return offered, read


def test_every_verification_offered_is_read_back_by_a_rule() -> None:
    """Offering the button is a promise that the answer is used. Five rules broke it."""
    offered, read = _offered_and_read()
    assert offered, "no verify cures found -- the scan is looking in the wrong place"
    assert {v: w for v, w in offered.items() if v not in read} == {}


def _v(ok: bool, note: str = "") -> dict:
    return {"ok": ok, "by": "A Officer", "desig": "Assistant Accounts Officer",
            "at": "23.10.2026 14:05", "note": note}


class TestAdvLimit:
    """The clause the advance was sanctioned under could not be matched to a limit."""

    F = {"docs": {"sanction": {"amount": 250000, "rule": None, "limitClause": None}}}

    def test_without_a_verification_the_button_is_offered(self) -> None:
        r = _adv_limit(dict(self.F))
        assert r["status"] == "conf"
        assert r["cure"] == {"kind": "verify", "vid": "ADV-LIMIT"}

    def test_a_confirmation_clears_it_and_carries_the_note(self) -> None:
        r = _adv_limit({**self.F, "verifications": {"ADV-LIMIT": _v(True, "Rule 13(1), half a year's pay")}})
        assert r["status"] == "ok"
        assert "Rs 250,000 is within its limit" in r["finding"]
        assert "Rule 13(1), half a year's pay" in r["finding"]
        assert "A Officer" in r["finding"]
        assert "cure" not in r

    def test_a_refusal_is_a_hard_stop(self) -> None:
        r = _adv_limit({**self.F, "verifications": {"ADV-LIMIT": _v(False)}})
        assert r["status"] == "hard"
        assert "does not permit" in r["finding"]


class TestFpOldac:
    """Field 16 blank, SAP holds no old number, and the ledger does not open at nil."""

    F = {"docs": {"changeForm": {"oldGpfNoState": "blank"}}, "sap": {"payslip": {"month": "Aug 2026"}}}

    def test_without_a_verification_the_button_is_offered(self) -> None:
        r = _fp_oldac(dict(self.F))
        assert r["status"] == "conf"
        assert r["cure"] == {"kind": "verify", "vid": "FP-OLDAC"}

    def test_a_confirmation_settles_it(self) -> None:
        r = _fp_oldac({**self.F, "verifications": {"FP-OLDAC": _v(True, "AG ledger vol. 7 f.112")}})
        assert r["status"] == "ok"
        assert "settled from the AG ledger" in r["finding"]
        assert "AG ledger vol. 7 f.112" in r["finding"]

    def test_a_refusal_is_a_hard_stop(self) -> None:
        assert _fp_oldac({**self.F, "verifications": {"FP-OLDAC": _v(False)}})["status"] == "hard"


class TestDeathHeirs:
    """No heir could be established from the papers."""

    F = {"docs": {"death": {}}}

    def test_without_a_verification_the_button_is_offered(self) -> None:
        r = _death_heirs(dict(self.F))
        assert r["status"] == "conf"
        assert r["cure"] == {"kind": "verify", "vid": "DEATH-HEIRS"}

    def test_a_confirmation_clears_it(self) -> None:
        r = _death_heirs({**self.F, "verifications": {"DEATH-HEIRS": _v(True, "Widow and two sons, NADRA FRC seen")}})
        assert r["status"] == "ok"
        assert "Widow and two sons, NADRA FRC seen" in r["finding"]

    def test_a_refusal_is_a_hard_stop(self) -> None:
        assert _death_heirs({**self.F, "verifications": {"DEATH-HEIRS": _v(False)}})["status"] == "hard"


class TestBtAdv:
    """A sub-item of the transfer proforma: advances in the last twelve months. The
    verification replaces its status and finding and leaves the column it belongs to."""

    F = {"docs": {"proforma": {"name": "A B Sample", "father": "C D Sample",
                               "designation": "Junior Clerk", "lastDeduction": "TV 221 of 06.2026"}},
         "personnelNo": "90000417",
         "sap": {"recalc": {"rows": [{"start": "01.07.2025", "end": "30.06.2026",
                                      "subscription": 12720, "tempAdvance": 50000}]}}}

    def _item(self, F):
        return next(o for o in _bt_proforma(F) if o["sub"] == "adv12")

    def test_without_a_verification_the_button_is_offered(self) -> None:
        o = self._item(dict(self.F))
        assert o["status"] == "conf"
        assert o["cure"] == {"kind": "verify", "vid": "BT-ADV"}

    def test_a_confirmation_clears_it_and_keeps_the_column(self) -> None:
        o = self._item({**self.F, "verifications": {"BT-ADV": _v(True, "Recovery schedule attached")}})
        assert o["status"] == "ok"
        assert o["doc"] == "Advances in the last twelve months (column 7)"
        assert "carried with the transfer" in o["finding"]
        assert "Recovery schedule attached" in o["finding"]
        assert "cure" not in o

    def test_a_refusal_is_a_hard_stop(self) -> None:
        o = self._item({**self.F, "verifications": {"BT-ADV": _v(False)}})
        assert o["status"] == "hard"
        assert o["sub"] == "adv12"


class TestDeathClaim:
    """The re-calculation report has no row closing on 30-06-2025 to test the claim against."""

    F = {"claim": {"amount": 92482},
         "sap": {"recalc": {"rows": [{"start": "01.07.2023", "end": "30.06.2024", "closing": 80000}]},
                 "payslip": {"gpfSubscription": 1060}}}

    def test_without_a_verification_the_button_is_offered(self) -> None:
        r = _death_claim(dict(self.F))
        assert r["status"] == "conf"
        assert r["cure"] == {"kind": "verify", "vid": "DEATH-CLAIM"}

    def test_a_confirmation_clears_it(self) -> None:
        r = _death_claim({**self.F, "verifications": {"DEATH-CLAIM": _v(True, "Checked against the manual ledger")}})
        assert r["status"] == "ok"
        assert "Checked against the manual ledger" in r["finding"]

    def test_a_refusal_is_a_hard_stop(self) -> None:
        assert _death_claim({**self.F, "verifications": {"DEATH-CLAIM": _v(False)}})["status"] == "hard"
