"""SOP §8.4: the periodic statement. ``api/reports.py``. Standard library only."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _case(root: Path, rid: str, verdict: str | None, determination: bool, decisions: list[dict],
          case_type: str = "FAMILY_PENSION_DEATH_AFTER_RETIREMENT", gap: str | None = None):
    d = root / f"run-{rid}"
    d.mkdir()
    report = {"case_ref": f"run-{rid}", "case_type": {"case_type": case_type},
              "recommendation": {"verdict": verdict} if verdict else None,
              "determination": {"steps": []} if determination else None,
              "determination_gap": {"determine": gap} if gap else None,
              "case_variant": "WIDOW", "claimant_name": "X"}
    (d / "case_report.json").write_text(json.dumps(report))
    if decisions:
        (d / "decisions.jsonl").write_text("\n".join(json.dumps(e) for e in decisions) + "\n")
    return d


class TheStatement(unittest.TestCase):
    def test_counts_overrides_and_undetermined_reasons(self):
        from api.reports import disposal_statement
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dirs = [
                _case(root, "a", "RETURN_FOR_CORRECTION", True, [
                    {"action": "RETURN_FOR_CORRECTION", "officer": "A", "role": "Auditor",
                     "at": "t1", "overrides_recommendation": False},
                    {"action": "FORWARD", "officer": "B", "role": "DAG", "at": "t2",
                     "overrides_recommendation": True, "override_grounds": "HIGH F-1",
                     "justification": "verified against p.4, stamp present",
                     "recommended_verdict": "RETURN_FOR_CORRECTION"},
                ]),
                _case(root, "b", "HOLD", True, [{"action": "HOLD", "officer": "A", "role": "Auditor",
                                                  "at": "t3", "overrides_recommendation": False}]),
                _case(root, "c", "RETURN_FOR_CORRECTION", False, [],
                      case_type="SUPERANNUATION_PENSION", gap="needs the three annual pay figures"),
                _case(root, "d", None, False, [], case_type="", gap=None),
            ]
            (root / "run-d" / "case_report.json").write_text(json.dumps({
                **json.loads((root / "run-d" / "case_report.json").read_text()),
                "case_type": {"case_type": None,
                              "case_type_evidence": "No prescribed form and no death certificate"},
            }))
            st = disposal_statement(dirs)
        self.assertEqual(st["cases"], 4)
        self.assertEqual(st["by_decision"], {"FORWARD": 1, "RETURN_FOR_CORRECTION": 0,
                                             "HOLD": 1, "UNDECIDED": 2})
        self.assertEqual(st["overrides"]["count"], 1)
        self.assertEqual(st["overrides"]["entries"][0]["grounds"], "HIGH F-1")
        self.assertEqual(st["overrides"]["entries"][0]["desk"], "DAG")
        self.assertEqual(st["undetermined"]["count"], 2)
        self.assertEqual(st["undetermined"]["by_class"]["SUPERANNUATION_PENSION"][0]["reason"],
                         "needs the three annual pay figures")
        self.assertIn("UNCLASSIFIED", st["undetermined"]["by_class"])
        self.assertEqual(st["undetermined"]["by_class"]["UNCLASSIFIED"][0]["reason"],
                         "No prescribed form and no death certificate")
        self.assertEqual(st["by_recommendation"]["NO_RECOMMENDATION"], 1)

    def test_a_directory_without_a_report_is_not_a_case(self):
        from api.reports import disposal_statement
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "run-x").mkdir()
            self.assertEqual(disposal_statement([Path(tmp) / "run-x"])["cases"], 0)


if __name__ == "__main__":
    unittest.main()
