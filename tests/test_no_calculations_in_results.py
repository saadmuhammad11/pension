"""This release computes no pension: no computed amount is stored in a report, served or shown.

    python3 -m unittest tests.test_no_calculations_in_results -v

Business decision of 7 Oct 2026 (docs/pension-rules-decisions.md, scope). The rules engine may
run -- its date checks, rule-pack selection and provisional items are checks the officer needs
-- but every computed figure (pension, commutation, gratuity, family-pension share, qualifying
service as a payable figure, the emoluments totals) is removed where the case report is built
(pipeline.report) and again where it is served (api.artefacts, the old register's routes), so a
report written before the decision leaves the server scrubbed too. Values a document itself
prints stay: they are readings, not calculations.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rules.scope import CALCULATIONS_IN_SCOPE, has_computed_amount, scrub_determination, scrub_emoluments, scrub_report

ROOT = Path(__file__).resolve().parents[1]

DET = {
    "case_ref": "t", "rule_pack_id": "PB-2026.02", "effective_date": "2026-06-30", "computed_at": "2026-07-01T10:00:00",
    "provisional": True, "unverified_rules_engaged": ["BLOCKING-07"],
    "steps": [
        {"rule_id": "EMOL-BASE", "description": "Reckonable emoluments", "computation_shown": "178,440 + 13,590", "amount": 192030, "unit": "Rs./month", "note": None},
        {"rule_id": "CALC-01", "description": "Gross pension", "computation_shown": "192,030 x 70%", "amount": 134421, "unit": "Rs./month", "note": None},
        {"rule_id": "QS-10", "description": "Retirement against birth", "computation_shown": "60th birthday 2026-06-30", "amount": None, "unit": "date", "note": "agrees"},
    ],
    "ambiguities": [{"rule_id": "FAM-IS-05", "blocking_id": "BLOCKING-06", "question": "Gratuity reading?", "difference": "Rs 4,955,525 apart",
                     "resolve_with": "AG Punjab", "readings": [{"label": "literal", "amount": 33605, "computation_shown": "25% x 134,421", "basis": "the words"},
                                                               {"label": "capitalised", "amount": 4989130, "computation_shown": "x table", "basis": "the table"}]}],
    "caveats": ["AI extracted the inputs."], "inputs": {"date_of_birth": "1966-06-30", "bps": 19, "reckonable_emoluments": 192030, "excluded_allowances": 0},
}
EMOL = {"reckonable_total": 192030, "excluded_total": 161765, "printed_total": 192030, "reconciled": True,
        "components": [{"printed_label": "Basic Pay", "component": "basic_pay", "amount": 178440, "reckonable": True, "page": 41},
                       {"printed_label": "House Rent", "component": "house_rent", "amount": 50000, "reckonable": False, "page": 42}]}


class Scrubbing(unittest.TestCase):
    def test_the_release_computes_nothing(self):
        self.assertFalse(CALCULATIONS_IN_SCOPE)

    def test_steps_keep_the_check_and_lose_the_figure(self):
        d = scrub_determination(DET)
        self.assertEqual([s["rule_id"] for s in d["steps"]], ["EMOL-BASE", "CALC-01", "QS-10"])
        for s in d["steps"]:
            self.assertNotIn("amount", s); self.assertNotIn("computation_shown", s); self.assertNotIn("unit", s)
        self.assertEqual(d["steps"][2]["note"], "agrees")
        self.assertEqual(d["unverified_rules_engaged"], ["BLOCKING-07"])
        self.assertTrue(d["provisional"])
        self.assertEqual(d["inputs"], {"date_of_birth": "1966-06-30", "bps": 19})   # the two sums are gone
        self.assertEqual(d["calculations"], "not in this release")

    def test_ambiguities_keep_the_question_and_lose_the_readings_figures(self):
        a = scrub_determination(DET)["ambiguities"][0]
        self.assertEqual((a["rule_id"], a["blocking_id"], a["question"]), ("FAM-IS-05", "BLOCKING-06", "Gratuity reading?"))
        self.assertNotIn("difference", a)
        self.assertEqual([r["label"] for r in a["readings"]], ["literal", "capitalised"])
        for r in a["readings"]:
            self.assertNotIn("amount", r); self.assertNotIn("computation_shown", r)

    def test_emoluments_keep_the_printed_lines_and_lose_the_totals(self):
        e = scrub_emoluments(EMOL)
        self.assertEqual(set(e), {"printed_total", "components"})
        self.assertEqual(e["printed_total"], 192030)                       # the form prints it: a reading
        self.assertEqual([(c["printed_label"], c["amount"], c["page"]) for c in e["components"]],
                         [("Basic Pay", 178440, 41), ("House Rent", 50000, 42)])
        for c in e["components"]:
            self.assertNotIn("reckonable", c)

    def test_scrub_report_is_idempotent_and_marks_the_scope(self):
        rep = {"determination": DET, "emoluments": EMOL, "flags": [], "recommendation": {"verdict": "FORWARD"}}
        once = scrub_report(rep); twice = scrub_report(once)
        self.assertEqual(once, twice)
        self.assertFalse(once["calculations_in_scope"])
        self.assertEqual(has_computed_amount(rep), [
            "determination.steps[0].amount", "determination.steps[0].computation_shown", "determination.steps[0].unit",
            "determination.steps[1].amount", "determination.steps[1].computation_shown", "determination.steps[1].unit",
            "determination.steps[2].amount", "determination.steps[2].computation_shown", "determination.steps[2].unit",
            "determination.ambiguities[0].difference",
            "determination.ambiguities[0].readings[0].amount", "determination.ambiguities[0].readings[0].computation_shown",
            "determination.ambiguities[0].readings[1].amount", "determination.ambiguities[0].readings[1].computation_shown",
            "determination.inputs.reckonable_emoluments", "determination.inputs.excluded_allowances",
            "emoluments.reckonable_total", "emoluments.excluded_total", "emoluments.reconciled",
            "emoluments.components[0].reckonable", "emoluments.components[1].reckonable"])
        self.assertEqual(has_computed_amount(once), [])
        self.assertEqual(has_computed_amount({"determination": None, "emoluments": None}), [])
        self.assertIsNone(scrub_report(None))


class WhereItIsApplied(unittest.TestCase):
    def test_an_old_report_on_disk_is_served_scrubbed(self):
        """Reports written before 7 Oct 2026 carry amounts; the API strips them on the way out."""
        from api.artefacts import report
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "case_report.json").write_text(json.dumps({"determination": DET, "emoluments": EMOL, "flags": [],
                                                                  "checklist": None, "recommendation": None}))
            served = report(SimpleNamespace(run_dir=run_dir, state="done"))
        self.assertEqual(has_computed_amount(served), [])
        self.assertFalse(served["calculations_in_scope"])
        self.assertEqual(served["determination"]["steps"][1]["rule_id"], "CALC-01")

    def test_the_report_builder_and_every_serving_route_scrub(self):
        report_src = (ROOT / "pipeline/report.py").read_text()
        self.assertIn('"emoluments": scrub_emoluments(stage4.get("emoluments"))', report_src)
        self.assertIn('"determination": scrub_determination(stage4.get("determination"))', report_src)
        for path, n in (("api/artefacts.py", 1), ("api/server.py", 2), ("api/v2.py", 1)):
            src = (ROOT / path).read_text()
            self.assertGreaterEqual(src.count("scrub_report("), n, path)

    def test_the_run_log_carries_no_figure(self):
        src = (ROOT / "api/runs.py").read_text()
        self.assertNotIn("reckonable_total", src)
        self.assertNotIn("excluded_total", src)
        self.assertIn("no amount computed for this release", src)

    def test_the_portal_shows_no_computed_total(self):
        tsx = (ROOT / "portals/src/shared/screens/CaseFindings.tsx").read_text()
        for word in ("reckonable_total", "excluded_total", "Reckonable total", "Excluded (non-reckonable)"):
            self.assertNotIn(word, tsx)
        types = (ROOT / "portals/src/shared/types.ts").read_text()
        self.assertNotIn("reckonable_total", types)
        self.assertIn("amount?: number | null", types)

    def test_no_wording_promises_a_calculation(self):
        for path in ("rules/verdict.py", "rules/flags.py"):
            src = (ROOT / path).read_text()
            self.assertNotIn("fully calculable", src, path)
            self.assertNotIn("Figures pre-filled", src, path)
            self.assertNotIn("The determination shown is computed", src, path)


if __name__ == "__main__":
    unittest.main()
