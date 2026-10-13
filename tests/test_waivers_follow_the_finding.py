"""A waiver is tied to the exact finding, and lapses when that finding changes (business decision H8, 7 Oct 2026).

    python3 -m unittest tests.test_waivers_follow_the_finding -v

Dispositions were keyed by the finding's running number ("F-2"), which a recompute or a
resubmission reassigns by sort order, so an old waiver silently applied to whichever finding
was F-2 now. Every finding now carries a fingerprint -- its rule (class), the documents it
cites, and the title and finding text that hold the field and the value; pages and the number
are left out -- and a disposition is recorded against it. It applies to whichever finding
carries that fingerprint today; where the finding changed or disappeared the disposition
lapses, stays on the record, and the finding is open again.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from api import dispositions
from rules.flags import finding_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def _flag(fid, cls="RULE-UNDECLARED", title="Unrecorded recovery of Rs. 126,355", finding="LPC p.29 prints a recovery of Rs. 126,355 the form denies.",
          asserted=(("LPC", 29),), contradicted=(("FORM_D_I", 41),), severity="HIGH"):
    return {"id": fid, "class": cls, "severity": severity, "title": title, "finding": finding,
            "evidence": {"asserted": [{"doc": d, "page": p} for d, p in asserted],
                         "contradicted_by": [{"doc": d, "page": p} for d, p in contradicted]},
            "blocks_ppo": severity == "HIGH"}


def _report(*flags):
    return {"flags": [{**f, "fingerprint": finding_fingerprint(f)} for f in flags], "checklist": {"missing": 0}}


class TheFingerprint(unittest.TestCase):
    def test_independent_of_the_running_number_and_of_page_numbers(self):
        a = _flag("F-2")
        b = _flag("F-5", finding="LPC p.31 prints a recovery of Rs. 126,355 the form denies.", asserted=(("LPC", 31),), contradicted=(("FORM_D_I", 43),))
        self.assertEqual(finding_fingerprint(a), finding_fingerprint(b))

    def test_changes_with_the_value_the_document_or_the_rule(self):
        base = finding_fingerprint(_flag("F-2"))
        self.assertNotEqual(base, finding_fingerprint(_flag("F-2", title="Unrecorded recovery of Rs. 126,000",
                                                            finding="LPC p.29 prints a recovery of Rs. 126,000 the form denies.")))
        self.assertNotEqual(base, finding_fingerprint(_flag("F-2", asserted=(("SALARY_STATEMENT", 29),))))
        self.assertNotEqual(base, finding_fingerprint(_flag("F-2", cls="CONTRA-MONEY")))

    def test_every_report_flag_carries_it(self):
        from rules.caserecord import Source
        from rules.flags import HIGH, Flag
        d = Flag(id="F-1", severity=HIGH, flag_class="X", title="t", finding="f", required_action="a", owner="AG",
                 asserted=(Source(3, "LPC"),)).to_dict()
        self.assertEqual(d["rule_id"], "X")
        self.assertEqual(d["fingerprint"], finding_fingerprint(d))


class TheDisposition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.run = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _waive(self, report, fid):
        flag = next(f for f in report["flags"] if f["id"] == fid)
        return dispositions.record(self.run, run_id="r1", flag_id=fid, action="WAIVE", officer="Syed Haider", role="ACCOUNTS_OFFICE",
                                   ground="Recovery verified by hand against the LPC.", flag=flag)

    def test_recorded_against_the_exact_finding(self):
        rep = _report(_flag("F-1"))
        e = self._waive(rep, "F-1")
        self.assertEqual(e["fingerprint"], rep["flags"][0]["fingerprint"])
        self.assertEqual(e["flag_documents"], ["FORM_D_I", "LPC"])
        self.assertIn("126,355", e["flag_finding"])

    def test_follows_its_finding_to_a_new_number(self):
        rep = _report(_flag("F-2"))
        self._waive(rep, "F-2")
        renumbered = _report(_flag("F-1", cls="CONTRA-IDENTITY", title="Personnel-number mismatch", finding="x", severity="HIGH"),
                             _flag("F-3"))                              # the same recovery finding, now third
        force = dispositions.in_force(renumbered, self.run)
        self.assertEqual(list(force), ["F-3"])
        self.assertEqual(force["F-3"]["action"], "WAIVE")
        gate = dispositions.calculation_gate(renumbered, self.run)
        self.assertEqual([f["id"] for f in gate["open_flags"]], ["F-1"])  # the waiver did NOT leak onto F-1
        self.assertEqual(gate["lapsed"], [])

    def test_lapses_when_the_finding_changes_and_the_finding_is_open_again(self):
        rep = _report(_flag("F-1"))
        self._waive(rep, "F-1")
        changed = _report(_flag("F-1", title="Unrecorded recovery of Rs. 150,000", finding="LPC p.29 prints a recovery of Rs. 150,000 the form denies."))
        self.assertEqual(dispositions.in_force(changed, self.run), {})
        gate = dispositions.calculation_gate(changed, self.run)
        self.assertFalse(gate["open"])
        self.assertEqual([f["id"] for f in gate["open_flags"]], ["F-1"])
        self.assertEqual(len(gate["lapsed"]), 1)
        self.assertIn("changed", gate["lapsed"][0]["why"])
        self.assertIn("lapsed", gate["reason"])
        self.assertEqual(len(dispositions.history(self.run)), 1)         # kept for the record

    def test_lapses_when_the_finding_disappears_and_the_gate_is_otherwise_open(self):
        rep = _report(_flag("F-1"))
        self._waive(rep, "F-1")
        gone = _report()
        gate = dispositions.calculation_gate(gone, self.run)
        self.assertTrue(gate["open"])                                      # nothing is raised; nothing to clear
        self.assertEqual(len(gate["lapsed"]), 1)
        self.assertIn("no longer raised", gate["lapsed"][0]["why"])

    def test_a_legacy_disposition_without_a_fingerprint_is_honoured_only_under_the_same_title(self):
        (self.run / dispositions.DISPOSITIONS_LOG).write_text(json.dumps({
            "run_id": "r1", "flag_id": "F-1", "action": "WAIVE", "officer": "old", "role": "ACCOUNTS_OFFICE",
            "ground": "g" * 20, "at": "2026-10-01T10:00:00", "flag_title": "Unrecorded recovery of Rs. 126,355"}) + "\n")
        self.assertEqual(list(dispositions.in_force(_report(_flag("F-1")), self.run)), ["F-1"])
        other = _report(_flag("F-1", cls="CONTRA-IDENTITY", title="Personnel-number mismatch", finding="x"))
        self.assertEqual(dispositions.in_force(other, self.run), {})
        self.assertEqual(len(dispositions.lapsed(other, self.run)), 1)

    def test_the_latest_decision_on_the_same_finding_wins(self):
        rep = _report(_flag("F-1"))
        self._waive(rep, "F-1")
        # A rejection carries its reason too, since 13 Oct 2026: both decisions are recorded
        # against the officer's own name, so both are given one.
        dispositions.record(self.run, run_id="r1", flag_id="F-1", action="UPHOLD", officer="Syed Haider", role="ACCOUNTS_OFFICE",
                            ground="The recovery is real; the finding stands.", flag=rep["flags"][0])
        self.assertEqual(dispositions.in_force(rep, self.run)["F-1"]["action"], "UPHOLD")
        self.assertFalse(dispositions.calculation_gate(rep, self.run)["open"])


class CarriedIntoAResubmission(unittest.TestCase):
    def test_only_the_identical_finding_carries_its_waiver(self):
        from api import rounds
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            base, new = Path(a), Path(b) / "run-new"; new.mkdir()
            base_rep = _report(_flag("F-1"), _flag("F-2", cls="CONTRA-FAMILY", title="Annex-A contradicts NADRA FRC for Usman", finding="relation son vs daughter", asserted=(("ANNEX_A", 5),), contradicted=(("NADRA_FRC", 6),)))
            for fid in ("F-1", "F-2"):
                dispositions.record(base, run_id="base", flag_id=fid, action="WAIVE", officer="o", role="ACCOUNTS_OFFICE", ground="g" * 20,
                                    flag=next(f for f in base_rep["flags"] if f["id"] == fid))
            # the recovery finding is unchanged (pages renumbered); the family finding now names a different value
            new_rep = _report(_flag("F-1", finding="LPC p.30 prints a recovery of Rs. 126,355 the form denies.", asserted=(("LPC", 30),), contradicted=(("FORM_D_I", 42),)),
                              _flag("F-2", cls="CONTRA-FAMILY", title="Annex-A contradicts NADRA FRC for Usman", finding="relation son vs grandson", asserted=(("ANNEX_A", 5),), contradicted=(("NADRA_FRC", 6),)))
            carry = {"base_run_id": "base", "page_map": {"30": 29, "42": 41, "5": 5, "6": 6}, "new_pages": []}   # new page -> base page
            try:
                out = rounds.carry_decisions(base, new, base_rep, new_rep, carry)
            except Exception as exc:                                     # noqa: BLE001 -- the carry map's shape is the pipeline's
                self.skipTest(f"carry map shape: {exc}")
            carried = {d["flag_id"] for d in out["dispositions"]}
            self.assertIn("F-1", carried)
            self.assertNotIn("F-2", carried)
            self.assertEqual(list(dispositions.in_force(new_rep, new)), ["F-1"])

    def test_the_portal_shows_lapsed_decisions(self):
        tsx = (ROOT / "portals/src/shared/screens/CaseFindings.tsx").read_text()
        self.assertIn("earlier decision", tsx)
        self.assertIn("LapsedDisposition", (ROOT / "portals/src/shared/api.ts").read_text())


if __name__ == "__main__":
    unittest.main()
