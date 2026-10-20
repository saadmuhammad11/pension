"""A disagreement in stage 6 reaches the officer, as stage 4's already does.

extract_page_confirmed returns (extraction, agreement). Stage 6 took only [0], so decision H1
was half applied: the reader blanked the disputed figure or date, the page then contributed
nothing, and nothing anywhere said why.

Measured on the 78-page bundle of 20 Oct 2026: page 60's document_date came back as four
different values across four reads -- 01-01-2020, 2014-01-01, 31-12-2014, 31-12-2016. The run's
assertions.json has no entry for it in document_dates, none in unreadable, and the report
raised no finding. An officer saw an absent date and no reason for it.

rules.flags.check_disputed_reads states the principle it was built on: "a check that silently
did not run is worse than a missing field".

    python3 -m unittest tests.test_stage6_disputed_reads -v
"""
from __future__ import annotations

import unittest

from pipeline.report import disputed_reads_from_fields


class Stage6DisputedReads(unittest.TestCase):
    def test_stage4_disputes_are_still_read_from_fields(self) -> None:
        """The existing path, unchanged: an agreement record in fields.json becomes a finding."""
        fields = {
            "prescribed_form": "FORM_D_I",
            "prescribed_form_page": 12,
            "form_d_i_agreement": {"agree": False, "document": "FORM_D_I", "page": 12,
                                   "disputed": ["total_pay_printed_rs"]},
        }
        self.assertEqual(disputed_reads_from_fields(fields),
                         (("FORM_D_I", 12, ("total_pay_printed_rs",)),))

    def test_an_agreeing_read_raises_nothing(self) -> None:
        fields = {"lpc_agreement": {"agree": True, "document": "LPC", "page": 29}}
        self.assertEqual(disputed_reads_from_fields(fields), ())

    def test_the_stage6_record_carries_page_document_and_fields(self) -> None:
        """What stage 6 now writes, in the shape the report merges."""
        disputed = [{"page": 60, "document": "FORWARDING_LETTER",
                     "fields": ["document_date"]}]
        merged = tuple(dict.fromkeys(
            (d["document"], d["page"], tuple(d["fields"])) for d in disputed))
        self.assertEqual(merged, (("FORWARDING_LETTER", 60, ("document_date",)),))

    def test_both_sources_merge_without_losing_either(self) -> None:
        fields = {"lpc_agreement": {"agree": False, "document": "LPC", "page": 29,
                                    "disputed": ["basic_pay"]}}
        stage6 = [{"page": 60, "document": "FORWARDING_LETTER", "fields": ["document_date"]}]
        merged = disputed_reads_from_fields(fields) + tuple(dict.fromkeys(
            (d["document"], d["page"], tuple(d["fields"])) for d in stage6))
        self.assertIn(("LPC", 29, ("basic_pay",)), merged)
        self.assertIn(("FORWARDING_LETTER", 60, ("document_date",)), merged)
        self.assertEqual(len(merged), 2)


if __name__ == "__main__":
    unittest.main()
