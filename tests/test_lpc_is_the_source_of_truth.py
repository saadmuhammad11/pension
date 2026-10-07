"""The LPC is the source of truth for pay components; nothing is summed across documents (decision H2, 7 Oct 2026).

    python3 -m unittest tests.test_lpc_is_the_source_of_truth -v

Until 7 Oct 2026 the pay lines of the prescribed form, the LPC and the salary statement were
pooled and de-duplicated on (component, amount): a component two documents printed at different
amounts was summed into the base. Now the base is one document's lines (the LPC where read, else
the prescribed form, else the salary statement), every line carries its document, and a
difference between the LPC and another document is a CONTRA-MONEY finding.
"""
from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from pipeline.extract import PAY_SOURCE_AUTHORITY, pay_line_document, single_source_pay_lines
from pipeline.report import pay_lines_from_fields
from rules.caserecord import CaseRecord, PayLine
from rules.flags import CONTRA_MONEY, HIGH, MEDIUM, check_pay_lines_against_lpc, run_battery
from rules.loader import load_pack

ROOT = Path(__file__).resolve().parents[1]
PACK = load_pack("PB-2026.02")


def _line(doc, page, component, label, amount):
    return {"document": doc, "page": page, "component": component, "printed_label": label, "amount": amount}


class OneDocumentOnly(unittest.TestCase):
    def test_the_order_of_authority(self):
        self.assertEqual(PAY_SOURCE_AUTHORITY[0], "LPC")
        self.assertIn("FORM_D_I", PAY_SOURCE_AUTHORITY)

    def test_lpc_lines_are_used_and_nothing_else_is_pooled(self):
        extracted = {"pay_components": [
            _line("FORM_D_I", 41, "basic_pay", "Basic Pay", 178440), _line("FORM_D_I", 41, "personal_pay", "Personal Pay", 13590),
            _line("LPC", 7, "basic_pay", "Basic Pay", 178440), _line("LPC", 7, "non_reckonable_allowance", "HRA", 13284),
            _line("SALARY_STATEMENT", 42, "non_reckonable_allowance", "Adhoc 2024", 38406),
        ]}
        lines, source = single_source_pay_lines(extracted)
        self.assertEqual(source, "LPC")
        self.assertEqual(sorted((c.printed_label, int(c.amount)) for c in lines), [("Basic Pay", 178440), ("HRA", 13284)])

    def test_without_an_lpc_the_prescribed_form_alone_is_used(self):
        extracted = {"pay_components": [
            _line("FORM_D_I", 41, "basic_pay", "Basic Pay", 178440),
            _line("SALARY_STATEMENT", 42, "basic_pay", "Basic Pay", 178440),
            _line("SALARY_STATEMENT", 42, "non_reckonable_allowance", "Adhoc 2024", 38406),
        ]}
        lines, source = single_source_pay_lines(extracted)
        self.assertEqual(source, "FORM_D_I")
        self.assertEqual([(c.printed_label, int(c.amount)) for c in lines], [("Basic Pay", 178440)])

    def test_a_line_restated_within_one_document_is_one_fact(self):
        extracted = {"pay_components": [_line("LPC", 7, "basic_pay", "Basic Pay", 100), _line("LPC", 8, "basic_pay", "Basic pay", 100)]}
        lines, _ = single_source_pay_lines(extracted)
        self.assertEqual(len(lines), 1)

    def test_no_pay_line_read(self):
        self.assertEqual(single_source_pay_lines({"pay_components": []}), ([], None))

    def test_old_records_without_a_document_tag_are_read_by_page(self):
        extracted = {"prescribed_form": "FORM_D_I", "prescribed_form_page": 41,
                     "printed_totals": {"form_total_pay": 192030, "salary_statement_gross": 353795}}
        self.assertEqual(pay_line_document({"page": 41}, extracted), "FORM_D_I")
        self.assertEqual(pay_line_document({"page": 42}, extracted), "SALARY_STATEMENT")
        self.assertEqual(pay_line_document({"page": 7, "document": "LPC"}, extracted), "LPC")

    def test_stage_4_tags_every_line_it_writes(self):
        src = (ROOT / "pipeline/extract.py").read_text()
        self.assertIn('"document": "FORM_D_I"}', src)
        self.assertIn('"document": doc_type}', src)


class TheFinding(unittest.TestCase):
    def _record(self, *lines):
        return CaseRecord(case_ref="t", case_type="FAMILY_PENSION",
                          pay_lines=tuple(PayLine(d, p, c, l, Decimal(a)) for d, p, c, l, a in lines))

    def test_a_component_another_document_prints_differently_is_high(self):
        rec = self._record(("LPC", 7, "basic_pay", "Basic Pay", 178440), ("LPC", 7, "personal_pay", "Personal Pay", 13590),
                           ("FORM_D_I", 41, "basic_pay", "Basic Pay", 178400), ("FORM_D_I", 41, "personal_pay", "Personal Pay", 13590),
                           ("SALARY_STATEMENT", 42, "basic_pay", "Basic Pay", 178440))
        flags = check_pay_lines_against_lpc(rec, PACK)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f.severity, f.flag_class, f.owner), (HIGH, CONTRA_MONEY, "DEPARTMENT"))
        self.assertIn("basic pay", f.title)
        self.assertIn("LPC prints Rs. 178,440", f.finding.replace("Rs 178,440", "Rs. 178,440"))
        self.assertIn("178,400", f.finding)
        self.assertIn("not summed", f.finding)
        self.assertEqual([(s.page, s.document) for s in f.asserted], [(7, "LPC")])
        self.assertEqual([(s.page, s.document) for s in f.contradicted_by], [(41, "FORM_D_I")])
        self.assertIn(CONTRA_MONEY, [x.flag_class for x in run_battery(rec, PACK)])

    def test_agreeing_documents_raise_nothing(self):
        rec = self._record(("LPC", 7, "basic_pay", "Basic Pay", 178440), ("FORM_D_I", 41, "basic_pay", "Basic Pay", 178440),
                           ("SALARY_STATEMENT", 42, "non_reckonable_allowance", "HRA", 13284))   # a line the LPC lacks is not a difference
        self.assertEqual(check_pay_lines_against_lpc(rec, PACK), [])

    def test_no_lpc_lines_is_a_medium_finding_when_other_documents_carry_pay_lines(self):
        rec = self._record(("FORM_D_I", 41, "basic_pay", "Basic Pay", 178440), ("SALARY_STATEMENT", 42, "basic_pay", "Basic Pay", 178440))
        flags = check_pay_lines_against_lpc(rec, PACK)
        self.assertEqual(len(flags), 1)
        self.assertEqual((flags[0].severity, flags[0].owner), (MEDIUM, "AG"))
        self.assertIn("No LPC pay lines read", flags[0].title)
        self.assertEqual(check_pay_lines_against_lpc(self._record(), PACK), [])

    def test_the_report_builds_the_lines_from_stage_4_s_record(self):
        fields = {"prescribed_form": "FORM_D_I", "prescribed_form_page": 41, "printed_totals": {"salary_statement_gross": 1},
                  "pay_components": [{"page": 41, "component": "basic_pay", "printed_label": "Basic Pay", "amount": 178440},
                                     {"page": 42, "component": "basic_pay", "printed_label": "Basic Pay", "amount": 178440, "document": "SALARY_STATEMENT"},
                                     {"page": 7, "component": "basic_pay", "printed_label": "Basic Pay"}]}      # no amount: skipped
        lines = pay_lines_from_fields(fields)
        self.assertEqual([(l.document, l.page, int(l.amount)) for l in lines], [("FORM_D_I", 41, 178440), ("SALARY_STATEMENT", 42, 178440)])
        self.assertEqual(pay_lines_from_fields({}), ())

    def test_summary_knows_both_shapes(self):
        from rules import flag_curation
        rec = self._record(("LPC", 7, "basic_pay", "Basic Pay", 1), ("FORM_D_I", 41, "basic_pay", "Basic Pay", 2))
        self.assertIn("differs from the LPC", flag_curation.summary(check_pay_lines_against_lpc(rec, PACK)[0]))
        rec = self._record(("FORM_D_I", 41, "basic_pay", "Basic Pay", 2))
        self.assertIn("No LPC pay lines read", flag_curation.summary(check_pay_lines_against_lpc(rec, PACK)[0]))


if __name__ == "__main__":
    unittest.main()
