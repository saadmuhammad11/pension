"""Two reads of a page that disagree stop the figures and raise a finding (business decision H1, 7 Oct 2026).

    python3 -m unittest tests.test_disagreeing_reads_stop -v

Every determination-critical page is read twice. Until 7 Oct 2026 a disagreement was recorded
in fields.json and the second read's figures were used anyway; nothing read that record. Now the
reader blanks the page's figures and the disputed dates, names what differed, and the report
raises EXTRACT-DISAGREE (HIGH) so an officer reads the original page.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from extraction import client
from rules.caserecord import CaseRecord
from rules.flags import EXTRACT_DISAGREE, HIGH, check_disputed_reads, run_battery
from rules.loader import load_pack

ROOT = Path(__file__).resolve().parents[1]
PACK = load_pack("PB-2026.02")


def _make(data):
    return client.Extraction(data=data, doc_type="FORM_D_I", schema_name="FORM_D_I", source="test", model="test",
                             prompt_version="t", latency_s=0.0, prompt_tokens=0, completion_tokens=100)


def _reads(*datas):
    """Patch extract_page to return the given reads in order."""
    it = iter(datas)
    return mock.patch.object(client, "extract_page", lambda *a, **k: _make(next(it)))


FORM_A = {"date_of_birth": {"value": "1966-06-30", "confidence": 0.9}, "date_of_death": {"value": "2026-03-01", "confidence": 0.9},
          "deceased_name": {"value": "Mst. X", "confidence": 0.9}, "total_pay_printed_rs": 192030,
          "pay_components": [{"printed_label": "Basic Pay", "amount_rs": 178440}, {"printed_label": "Personal Pay", "amount_rs": 13590}]}
FORM_B_SAME = {**FORM_A, "pay_components": [dict(c) for c in FORM_A["pay_components"]]}
FORM_B_FIGURE = {**FORM_A, "pay_components": [{"printed_label": "Basic Pay", "amount_rs": 178400}, {"printed_label": "Personal Pay", "amount_rs": 13590}]}
FORM_B_DATE = {**FORM_A, "date_of_birth": {"value": "1956-06-30", "confidence": 0.9}}


class TheReader(unittest.TestCase):
    def test_agreeing_reads_keep_every_figure(self):
        with _reads(FORM_A, FORM_B_SAME):
            ext, agreement = client.extract_page_confirmed("p041.png", schema_name="FORM_D_I")
        self.assertTrue(agreement["agree"])
        self.assertNotIn("disputed", agreement)
        self.assertEqual(ext.data["total_pay_printed_rs"], 192030)
        self.assertEqual(len(ext.data["pay_components"]), 2)

    def test_a_differing_pay_line_blanks_the_page_s_figures(self):
        with _reads(FORM_A, FORM_B_FIGURE):
            ext, agreement = client.extract_page_confirmed("p041.png", schema_name="FORM_D_I")
        self.assertFalse(agreement["agree"])
        self.assertTrue(agreement["blanked"])
        self.assertEqual(agreement["disputed"], ["pay line 'Basic Pay'"])
        self.assertIn("No figure and no disputed date from this page is used", agreement["finding"])
        self.assertEqual(ext.data["pay_components"], [])                  # neither read's lines
        self.assertIsNone(ext.data["total_pay_printed_rs"])                # nor the printed total
        self.assertEqual(ext.data["date_of_birth"]["value"], "1966-06-30")   # the dates agreed; they stay
        self.assertEqual(ext.data["deceased_name"]["value"], "Mst. X")       # the page still identifies itself

    def test_a_differing_date_is_a_disagreement_and_that_date_is_blanked(self):
        with _reads(FORM_A, FORM_B_DATE):
            ext, agreement = client.extract_page_confirmed("p041.png", schema_name="FORM_D_I")
        self.assertFalse(agreement["agree"])
        self.assertEqual(agreement["disputed"], ["date_of_birth"])
        self.assertIsNone(ext.data["date_of_birth"]["value"])
        self.assertEqual(ext.data["date_of_birth"]["unreadable_reason"], "two reads disagreed")
        self.assertEqual(ext.data["date_of_death"]["value"], "2026-03-01")
        self.assertEqual(ext.data["pay_components"], [])                  # the page's figures go too

    def test_the_pipeline_tags_the_record_with_the_page(self):
        src = (ROOT / "pipeline/extract.py").read_text()
        self.assertIn('agreement.update({"document": form_type, "page": page})', src)
        self.assertIn('agree.update({"document": doc_type, "page": pg})', src)


class TheReport(unittest.TestCase):
    def test_disputed_pages_are_collected_from_stage_4_s_record(self):
        from pipeline.report import disputed_reads_from_fields
        fields = {
            "prescribed_form": "FORM_D_I", "prescribed_form_page": 41,
            "form_d_i_agreement": {"agree": False, "disputed": ["pay line 'Basic Pay'", "date_of_birth"]},   # old record: no page tag
            "salary_statement_agreement": {"agree": True, "document": "SALARY_STATEMENT", "page": 42},
            "lpc_agreement": {"agree": False, "document": "LPC", "page": 7, "disputed": ["gross_printed_rs"]},
            "pension_witnesses": [{"document": "PPO", "page": 44, "agreement": {"agree": False, "disputed": ["monthly_pension_rs"]}},
                                  {"document": "PENSION_SLIP", "page": 55, "agreement": {"agree": True}}],
        }
        self.assertEqual(disputed_reads_from_fields(fields), (
            ("FORM_D_I", 41, ("pay line 'Basic Pay'", "date_of_birth")),
            ("LPC", 7, ("gross_printed_rs",)),
            ("PPO", 44, ("monthly_pension_rs",)),
        ))
        self.assertEqual(disputed_reads_from_fields({}), ())
        self.assertEqual(disputed_reads_from_fields({"form_d_i_agreement": {"agree": True}}), ())

    def test_the_finding_is_high_names_the_page_and_blocks_auto_approval(self):
        record = CaseRecord(case_ref="t", case_type="FAMILY_PENSION",
                            disputed_reads=(("FORM_D_I", 41, ("pay line 'Basic Pay'", "date_of_birth")),))
        flags = check_disputed_reads(record, PACK)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f.severity, f.flag_class, f.owner), (HIGH, EXTRACT_DISAGREE, "AG"))
        self.assertTrue(f.affects_determination and f.blocks_ppo)
        self.assertIn("p.41", f.title)
        self.assertIn("pay line 'Basic Pay'", f.finding)
        self.assertIn("date_of_birth", f.finding)
        self.assertEqual([(s.page, s.document) for s in f.asserted], [(41, "FORM_D_I")])
        self.assertIn("transcribe", f.required_action)
        self.assertIn(EXTRACT_DISAGREE, [x.flag_class for x in run_battery(record, PACK)])
        self.assertEqual(check_disputed_reads(CaseRecord(case_ref="t", case_type="X"), PACK), [])

    def test_the_class_is_curated_labelled_and_cited(self):
        from pipeline.report import _FLAG_QUERY
        from rules import flag_curation
        self.assertIn(EXTRACT_DISAGREE, _FLAG_QUERY)
        self.assertIn(EXTRACT_DISAGREE, flag_curation._CLASS_ORDER)
        f = check_disputed_reads(CaseRecord(case_ref="t", case_type="X", disputed_reads=(("LPC", 7, ("gross_printed_rs",)),)), PACK)[0]
        self.assertIn("Two reads of the page disagree", flag_curation.summary(f))
        self.assertIn("'EXTRACT-DISAGREE'", (ROOT / "portals/src/shared/labels.ts").read_text())


if __name__ == "__main__":
    unittest.main()
