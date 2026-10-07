"""A fixed list of eligible family-pension relations, with the proof each needs (business decision H6, 7 Oct 2026).

    python3 -m unittest tests.test_eligible_relations -v

The relation text used to be read with child markers first, so "Wife d/o Ali Ahmad" was paid
as a daughter and lost the spouse's term; grandchildren, in-laws and adult sons were all
"unmarried child" at 75%, and no proof was asked for. Now rules.relations holds the draft list
(decision sheet, Appendix B), parse_relation reads the form's wording against it, and the
report raises RELATION-INELIGIBLE or RELATIONSHIP-UNPROVED.
"""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from rules.caserecord import CaseRecord, Document, FamilyMember, Source
from rules.flags import MEDIUM, RELATION_INELIGIBLE, RELATIONSHIP_UNPROVED, check_claimant_relation, run_battery
from rules.loader import load_pack
from rules.relations import ELIGIBLE_RELATIONS, SON_AGE_LIMIT_YEARS, appendix_markdown, parse_relation

ROOT = Path(__file__).resolve().parents[1]
PACK = load_pack("PB-2026.02")


class TheParser(unittest.TestCase):
    def test_a_relation_word_beside_a_parentage_marker_is_the_relation(self):
        self.assertEqual(parse_relation("Wife d/o Ali Ahmad").key, "spouse")          # the misread
        self.assertEqual(parse_relation("Widow w/o Khan Bahadur").key, "spouse")
        self.assertEqual(parse_relation("Son s/o Akbar").key, "son")

    def test_a_marker_alone_speaks_for_itself(self):
        self.assertEqual(parse_relation("d/o Muhammad Munir").key, "unmarried_daughter")
        self.assertEqual(parse_relation("w/o Khan Bahadur").key, "spouse")
        self.assertEqual(parse_relation("s/o Akbar").key, "son")

    def test_the_forms_wordings(self):
        for text, key in (("widow", "spouse"), ("Widow / Widower", "spouse"), ("Husband", "spouse"), ("wife", "spouse"),
                          ("widow daughter of late Muhammad Bashir", "widowed_daughter"), ("widowed daughter", "widowed_daughter"),
                          ("divorce daughter", "divorced_daughter"), ("unmarried daughter", "unmarried_daughter"),
                          ("Son, Disable", "disabled_child"), ("disabled son", "disabled_child"), ("Mother", "parent"),
                          ("father", "parent"), ("sister", "sister"), ("child", "child")):
            with self.subTest(text=text):
                self.assertEqual(parse_relation(text).key, key)

    def test_relations_off_the_list(self):
        for text in ("nephew", "grand daughter", "granddaughter", "daughter-in-law", "son in law", "brother", "step son", "cousin", "friend"):
            with self.subTest(text=text):
                p = parse_relation(text)
                self.assertIsNone(p.key, text)
                self.assertFalse(p.eligible)
        self.assertIn("not stated", parse_relation("").reason)
        self.assertIn("not stated", parse_relation(None).reason)

    def test_every_entry_names_its_proofs_and_what_to_confirm(self):
        keys = [r.key for r in ELIGIBLE_RELATIONS]
        self.assertEqual(keys[0], "spouse")                                        # ENT-07: the spouse first
        for r in ELIGIBLE_RELATIONS:
            self.assertTrue(r.proofs, r.key); self.assertTrue(r.confirm, r.key); self.assertTrue(r.share_key, r.key)
            for p in r.proofs:
                self.assertTrue(p.documents, (r.key, p.kind))


class TheShareKey(unittest.TestCase):
    def test_dii_reads_the_relation_through_the_list(self):
        from rules.dii import CaseTypeNotImplemented, InputMissing, _share_key_for
        self.assertEqual(_share_key_for("Wife d/o Ali Ahmad"), "widow_percent")
        self.assertEqual(_share_key_for("widow daughter of late X"), "regrant_daughter_percent")
        self.assertEqual(_share_key_for("d/o Muhammad Munir"), "unmarried_child_percent")
        self.assertEqual(_share_key_for("Son, Disable"), "disabled_child_percent")
        with self.assertRaises(CaseTypeNotImplemented):
            _share_key_for("grand daughter")
        with self.assertRaises(CaseTypeNotImplemented):
            _share_key_for("nephew")
        with self.assertRaises(InputMissing):
            _share_key_for("")


def _record(relation, docs=(), frc=(), claimant="Mst. Rubina", case_type="FAMILY_PENSION_DEATH_AFTER_RETIREMENT",
            entitlement=date(2026, 7, 1)):
    documents = (Document(type="FORM_D_II", pages=(4,), present=True),) + tuple(Document(type=d, pages=(9,), present=True) for d in docs)
    return CaseRecord(case_ref="t", case_type=case_type, documents=documents, claimant_name=claimant,
                      claimant_relation=relation, frc_family=tuple(frc), entitlement_date=entitlement)


class TheFindings(unittest.TestCase):
    def test_a_relation_off_the_list_is_a_medium_check_for_the_reviewer(self):
        """Advisory only (owner's decision of 7 Oct 2026): the list is a draft, so it never blocks."""
        flags = check_claimant_relation(_record("grand daughter", docs=("NADRA_FRC",)), PACK)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f.severity, f.flag_class, f.owner), (MEDIUM, RELATION_INELIGIBLE, "AG"))
        self.assertFalse(f.blocks_ppo); self.assertFalse(f.affects_determination)
        self.assertEqual(f.title, "Verify relation eligibility: grand daughter is not on the draft list")
        self.assertIn("pending the rules owner", f.finding)
        self.assertEqual([(s.page, s.document) for s in f.asserted], [(4, "FORM_D_II")])
        self.assertIn(RELATION_INELIGIBLE, [x.flag_class for x in run_battery(_record("nephew"), PACK)])

    def test_a_relation_not_stated_is_medium_for_the_department(self):
        flags = check_claimant_relation(_record(""), PACK)
        self.assertEqual((flags[0].severity, flags[0].flag_class, flags[0].owner), (MEDIUM, RELATIONSHIP_UNPROVED, "DEPARTMENT"))
        self.assertTrue(flags[0].title.startswith("Verify relation eligibility"))

    def test_missing_proof_is_named_with_the_documents_that_supply_it(self):
        flags = check_claimant_relation(_record("divorce daughter", docs=("NADRA_FRC",),
                                                frc=(FamilyMember("Mst. Rubina", "DAUGHTER", "Divorced", Source(9, "NADRA_FRC")),)), PACK)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f.severity, f.flag_class, f.owner), (MEDIUM, RELATIONSHIP_UNPROVED, "DEPARTMENT"))
        self.assertEqual(f.title, "Proof of marital status / income not found (claim as divorced daughter)")
        self.assertNotIn("relationship", f.title)                                  # the FRC names her
        self.assertFalse(f.blocks_ppo); self.assertFalse(f.affects_determination)
        self.assertIn("DIVORCE_CERTIFICATE".replace("_", " ").lower()[:7], f.required_action.lower())
        self.assertIn("ENT-03", f.finding)

    def test_every_proof_present_raises_nothing(self):
        flags = check_claimant_relation(_record("divorce daughter", docs=("NADRA_FRC", "DIVORCE_CERTIFICATE", "NO_REGULAR_INCOME_CERTIFICATE"),
                                                frc=(FamilyMember("Mst. Rubina", "DAUGHTER", "Divorced", Source(9, "NADRA_FRC")),)), PACK)
        self.assertEqual(flags, [])
        flags = check_claimant_relation(_record("widow", docs=("NIKAH_NAMA", "NON_REMARRIAGE_CERTIFICATE")), PACK)
        self.assertEqual(flags, [])

    def test_an_unmarried_daughter_the_frc_records_as_married_is_a_medium_check(self):
        flags = check_claimant_relation(_record("unmarried daughter", docs=("NADRA_FRC",),
                                                frc=(FamilyMember("Mst. Rubina", "DAUGHTER", "Married", Source(9, "NADRA_FRC")),)), PACK)
        self.assertEqual([(f.severity, f.flag_class) for f in flags], [(MEDIUM, RELATION_INELIGIBLE)])
        self.assertTrue(flags[0].title.startswith("Verify relation eligibility"))
        self.assertIn("married", flags[0].title)

    def test_nothing_here_is_ever_high(self):
        for rec in (_record("nephew"), _record(""), _record("unmarried daughter", docs=("NADRA_FRC",),
                    frc=(FamilyMember("Mst. Rubina", "DAUGHTER", "Married", Source(9, "NADRA_FRC")),)),
                    _record("son", docs=("NADRA_FRC",), claimant="Ahmad",
                            frc=(FamilyMember("Ahmad", "SON", "Unmarried", Source(9, "NADRA_FRC"), birth_year=1990),))):
            for f in check_claimant_relation(rec, PACK):
                self.assertEqual(f.severity, MEDIUM, f.title)
                self.assertFalse(f.blocks_ppo, f.title)
                self.assertFalse(f.affects_determination, f.title)

    def test_a_son_past_the_draft_age_limit_is_medium_and_says_the_limit_is_unconfirmed(self):
        flags = check_claimant_relation(_record("son", docs=("NADRA_FRC", "CNIC"), claimant="Ahmad",
                                                frc=(FamilyMember("Ahmad", "SON", "Unmarried", Source(9, "NADRA_FRC"), birth_year=1990),)), PACK)
        self.assertEqual([(f.severity, f.flag_class) for f in flags], [(MEDIUM, RELATION_INELIGIBLE)])
        self.assertIn(str(SON_AGE_LIMIT_YEARS), flags[0].title)
        self.assertIn("BLOCKING-08", flags[0].finding)
        young = check_claimant_relation(_record("son", docs=("NADRA_FRC", "CNIC"), claimant="Ahmad",
                                                frc=(FamilyMember("Ahmad", "SON", "Unmarried", Source(9, "NADRA_FRC"), birth_year=2010),)), PACK)
        self.assertEqual(young, [])

    def test_a_self_pension_is_not_judged(self):
        self.assertEqual(check_claimant_relation(_record("nephew", case_type="SUPERANNUATION_PENSION"), PACK), [])

    def test_the_sheet_carries_the_draft_list_and_the_portal_the_label(self):
        sheet = (ROOT / "docs/pension-rules-decisions.md").read_text()
        self.assertIn("## Appendix B", sheet)
        for r in ELIGIBLE_RELATIONS:
            self.assertIn(f"| {r.label} |", sheet, r.key)
        self.assertIn(appendix_markdown().splitlines()[2], sheet)
        self.assertIn("'RELATION-INELIGIBLE'", (ROOT / "portals/src/shared/labels.ts").read_text())
        from pipeline.report import _FLAG_QUERY
        self.assertIn(RELATION_INELIGIBLE, _FLAG_QUERY)


if __name__ == "__main__":
    unittest.main()
