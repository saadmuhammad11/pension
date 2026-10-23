"""The declared case type (29 Sep 2026): the office's own types (the columns of its document sheet)
in one shared list, the pipeline paths they map to, the finding when the papers disagree, and the
report running on the declaration.

    python3 -m unittest tests.test_case_types -v
"""
from __future__ import annotations

import unittest

from rules.case_type import (CASE_TYPES, OFFICE_CASE_TYPES, OFFICE_CASE_TYPE_LABELS, PRESCRIBED_FORM, CaseTypeResult,
                             canonical_case_type, canonical_office_type, case_type_label, declared_case_type_result,
                             load_case_types, office_type_for, pipeline_types_for, variants_for_case_type)
from rules.caserecord import CaseRecord, Document
from rules.checklist import ALL_VARIANTS, VARIANT_LABELS
from rules.flags import DECLARED_TYPE_MISMATCH, HIGH, MEDIUM, check_declared_case_type


class SharedConfig(unittest.TestCase):
    def test_the_config_and_the_rules_agree(self) -> None:
        cfg = load_case_types()
        office = [t["id"] for t in cfg["case_types"]]
        self.assertEqual(tuple(office), OFFICE_CASE_TYPES)
        # The eleven columns of the office sheet, in its order, each a checklist column the rules know.
        self.assertEqual(office, ["FRESH_SELF", "FRESH_INVALID", "REVISED", "DEATH_IN_SERVICE", "WIDOW", "UNMARRIED_CHILD",
                                  "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING", "PARENT", "SISTER"])
        self.assertEqual(set(office), set(ALL_VARIANTS))
        for t in cfg["case_types"]:
            self.assertTrue(t["label"].strip() and t["hint"].strip(), t["id"])
            for pt in t["pipeline_types"]:
                self.assertIn(pt, CASE_TYPES, f"{t['id']} names a pipeline path that does not exist: {pt}")
                self.assertEqual(PRESCRIBED_FORM[pt], t["prescribed_form"], f"{t['id']}: form of {pt}")
        self.assertEqual(tuple(t["id"] for t in cfg["pipeline_types"]), CASE_TYPES)
        for t in cfg["pipeline_types"]:
            self.assertEqual(PRESCRIBED_FORM[t["id"]], t["prescribed_form"])

    def test_labels_mappings_and_lookups(self) -> None:
        self.assertEqual(OFFICE_CASE_TYPE_LABELS["WD_DAUGHTER"], "Widowed daughter")
        self.assertEqual(case_type_label("WIDOW"), "Widow / Widower")
        self.assertEqual(case_type_label("FAMILY_PENSION_DEATH_OF_PENSIONER"), "Family pension — death of a pensioner")
        self.assertIsNone(canonical_office_type("SUPERANNUATION_PENSION"))
        self.assertEqual(canonical_case_type("FAMILY_PENSION_DEATH_OF_PENSIONER"), "FAMILY_PENSION_DEATH_AFTER_RETIREMENT")
        self.assertEqual(pipeline_types_for("FRESH_SELF"), ("SUPERANNUATION_PENSION", "RETIRING_PENSION"))
        self.assertEqual(pipeline_types_for("REVISED"), ())
        self.assertEqual(variants_for_case_type("WIDOW"), ("WIDOW",))
        self.assertEqual(len(variants_for_case_type("FAMILY_PENSION_DEATH_AFTER_RETIREMENT")), 7)
        self.assertEqual(office_type_for("FAMILY_PENSION_DEATH_IN_SERVICE"), "DEATH_IN_SERVICE")
        self.assertEqual(office_type_for("INVALID_PENSION"), "FRESH_INVALID")
        self.assertIsNone(office_type_for("FAMILY_PENSION_DEATH_AFTER_RETIREMENT"))       # seven columns: the papers must say
        self.assertEqual(office_type_for("FAMILY_PENSION_DEATH_AFTER_RETIREMENT", "PARENT"), "PARENT")
        self.assertIsNone(office_type_for("ANTICIPATORY_PENSION"))                       # no column on the sheet
        # The intake labels are the checklist's own column headings.
        for v in ALL_VARIANTS:
            self.assertEqual(VARIANT_LABELS[v].split(" ")[0], OFFICE_CASE_TYPE_LABELS[v].split(" ")[0], v)

    def test_a_declaration_names_its_path(self) -> None:
        r = declared_case_type_result("DEATH_IN_SERVICE")
        self.assertEqual((r.case_type, r.prescribed_form, r.route, r.confidence), ("FAMILY_PENSION_DEATH_IN_SERVICE", "D-I", "CLASSIFIED", 1.0))
        # Fresh – Self is Form B-I, two paths: the papers pick where they land inside it, else the first.
        self.assertEqual(declared_case_type_result("FRESH_SELF").case_type, "SUPERANNUATION_PENSION")
        read = CaseTypeResult(case_type="RETIRING_PENSION", confidence=0.98, evidence="", prescribed_form="B-I")
        self.assertEqual(declared_case_type_result("FRESH_SELF", read).case_type, "RETIRING_PENSION")
        other = CaseTypeResult(case_type="FAMILY_PENSION_DEATH_AFTER_RETIREMENT", confidence=0.98, evidence="", prescribed_form="D-II")
        self.assertEqual(declared_case_type_result("FRESH_SELF", other).case_type, "SUPERANNUATION_PENSION")
        self.assertEqual(declared_case_type_result("FRESH_SELF", other).route, "CLASSIFIED")
        # A revision is whatever the papers read as.
        self.assertEqual(declared_case_type_result("REVISED", other).case_type, "FAMILY_PENSION_DEATH_AFTER_RETIREMENT")
        self.assertIsNone(declared_case_type_result("REVISED").case_type)
        with self.assertRaises(KeyError):
            declared_case_type_result("SUPERANNUATION_PENSION")

    def test_the_portal_reads_the_same_file(self) -> None:
        from pathlib import Path
        src = Path(__file__).resolve().parents[1] / "portals" / "src" / "shared" / "caseTypes.ts"
        self.assertIn("../../../config/case_types.json", src.read_text(encoding="utf-8"))


def _record(*, declared, detected, confidence=0.98, alternatives=(), docs=("FORM_D_II",), detected_variant=None) -> CaseRecord:
    return CaseRecord(
        case_ref="t", case_type=detected or "",
        documents=tuple(Document(type=d, pages=(i + 1,)) for i, d in enumerate(docs)),
        declared_case_type=declared, declared_pipeline_types=pipeline_types_for(declared),
        detected_case_type=detected, detected_case_variant=detected_variant,
        detected_case_type_confidence=confidence, detected_case_type_evidence="Form D-II on p.1, signed.",
        detected_case_type_alternatives=tuple(alternatives),
    )


class MismatchFinding(unittest.TestCase):
    pack = None   # the check reads the record, not the pack

    def test_a_form_of_another_path_is_a_high_finding(self) -> None:
        flags = check_declared_case_type(_record(declared="FRESH_SELF", detected="FAMILY_PENSION_DEATH_AFTER_RETIREMENT"), self.pack)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f.severity, f.flag_class, f.title), (HIGH, DECLARED_TYPE_MISMATCH, "Declared case type may not match documents"))
        self.assertIn("Fresh – Self", f.finding)
        self.assertIn("Family pension — death of a pensioner", f.finding)
        self.assertTrue(f.blocks_ppo)
        self.assertEqual([s.page for s in f.asserted], [1])

    def test_an_inferred_reading_is_medium(self) -> None:
        flags = check_declared_case_type(_record(declared="FRESH_SELF", detected="FAMILY_PENSION_DEATH_IN_SERVICE",
                                                 confidence=0.70, docs=("DEATH_CERTIFICATE",)), self.pack)
        self.assertEqual(flags[0].severity, MEDIUM)
        self.assertFalse(flags[0].blocks_ppo)

    def test_the_claimant_column_is_checked_too(self) -> None:
        flags = check_declared_case_type(_record(declared="WIDOW", detected="FAMILY_PENSION_DEATH_AFTER_RETIREMENT",
                                                 detected_variant="UNMARRIED_CHILD"), self.pack)
        self.assertEqual(flags[0].severity, MEDIUM)
        self.assertIn("Unmarried daughter / Underage son", flags[0].finding)
        self.assertEqual(check_declared_case_type(_record(declared="WIDOW", detected="FAMILY_PENSION_DEATH_AFTER_RETIREMENT",
                                                          detected_variant="WIDOW"), self.pack), [])

    def test_agreement_no_declaration_or_no_reading_says_nothing(self) -> None:
        self.assertEqual(check_declared_case_type(_record(declared="FRESH_INVALID", detected="INVALID_PENSION"), self.pack), [])
        self.assertEqual(check_declared_case_type(_record(declared="FRESH_INVALID", detected="COMPULSORY_RETIREMENT_PENSION"), self.pack), [])
        self.assertEqual(check_declared_case_type(_record(declared=None, detected="INVALID_PENSION"), self.pack), [])
        self.assertEqual(check_declared_case_type(_record(declared="FRESH_INVALID", detected=None, docs=()), self.pack), [])
        self.assertEqual(check_declared_case_type(_record(declared="REVISED", detected="INVALID_PENSION"), self.pack), [])
        # Undecided between two paths, one of them inside the declaration: no finding.
        self.assertEqual(check_declared_case_type(_record(declared="FRESH_SELF", detected=None,
                                                          alternatives=("SUPERANNUATION_PENSION", "RETIRING_PENSION"), docs=("FORM_B_I",)), self.pack), [])
        # Undecided between two paths, neither in the declaration: a MEDIUM finding naming both.
        flags = check_declared_case_type(_record(declared="DEATH_IN_SERVICE", detected=None,
                                                 alternatives=("INVALID_PENSION", "COMPULSORY_RETIREMENT_PENSION"), docs=("FORM_B_IV",)), self.pack)
        self.assertEqual(flags[0].severity, MEDIUM)
        self.assertIn("Invalid pension or Compulsory retirement pension", flags[0].finding)


class ReportWiring(unittest.TestCase):
    def test_build_report_runs_on_the_declared_type_and_keeps_the_reading(self) -> None:
        """On the golden artefacts (a Form D-I case): declared Fresh – Self, the report runs the rules
        as a superannuation pension on the Fresh – Self column, keeps the D-I reading beside it,
        and raises the mismatch finding; declared Death during service, it agrees with itself."""
        import shutil, tempfile
        from pathlib import Path
        from pipeline.report import build_report
        golden = Path(__file__).resolve().parents[1] / "artifacts" / "golden"
        if not (golden / "identities.json").exists():
            raise unittest.SkipTest("no golden artefacts")
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "golden"
            shutil.copytree(golden, run)
            plain = build_report(run, with_citations=False)
            self.assertEqual(plain["case_type"]["source"], "detected")
            self.assertIsNone(plain["case_type"]["declared"])
            self.assertEqual(plain["case_type"]["case_type"], "FAMILY_PENSION_DEATH_IN_SERVICE")
            self.assertFalse([f for f in plain["flags"] if f["class"] == DECLARED_TYPE_MISMATCH])

            declared = build_report(run, with_citations=False, case_type="FRESH_SELF")
            self.assertEqual(declared["case_type"]["case_type"], "SUPERANNUATION_PENSION")
            self.assertEqual(declared["case_type"]["source"], "declared")
            self.assertEqual(declared["case_type"]["declared"], "FRESH_SELF")
            self.assertEqual(declared["case_type"]["detected"], "FAMILY_PENSION_DEATH_IN_SERVICE")
            self.assertEqual(declared["case_type_detected"]["case_type"], "FAMILY_PENSION_DEATH_IN_SERVICE")
            self.assertEqual((declared["case_variant"], declared["case_variant_source"]), ("FRESH_SELF", "declared"))
            mismatch = [f for f in declared["flags"] if f["class"] == DECLARED_TYPE_MISMATCH]
            self.assertEqual(len(mismatch), 1)
            self.assertEqual(mismatch[0]["severity"], HIGH)
            self.assertIn(mismatch[0]["id"], declared["recommendation"]["blocking_flags"])

            same = build_report(run, with_citations=False, case_type="DEATH_IN_SERVICE")
            self.assertEqual(same["case_type"]["source"], "declared")
            self.assertEqual((same["case_variant"], same["case_variant_source"]), ("DEATH_IN_SERVICE", "declared"))
            self.assertFalse([f for f in same["flags"] if f["class"] == DECLARED_TYPE_MISMATCH])
            self.assertEqual(same["checklist"]["result"], plain["checklist"]["result"])
            self.assertEqual([f["class"] for f in same["flags"]], [f["class"] for f in plain["flags"]])


if __name__ == "__main__":
    unittest.main()
