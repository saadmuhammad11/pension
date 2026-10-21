"""The proforma is recognised by its sections when its heading is not on the page (21 Oct 2026).

    python3 -m unittest tests.test_proforma_without_its_heading -v

The office's own sample prints "PROPOSED PERFORMA FOR QUALIFYING SEVICE FOR PENSION" across the
top, and ``PROFORMA_TITLE`` was written against it. The copy filed with the first real case to
use one (run b3b0e3f35d7c, p.1) prints no such line: the scan begins at "(For Use in the
Administrative/Attached Department/Office)" and the title is above the top edge. The vision
model, told to look for a heading, answered OTHER at confidence 1.00 -- so the page was not a
document at all, and AG-26 would have read MISSING against a department that had filed it.

Two readers now have to miss it for that to happen again: the model is told the sections ARE the
identification, and ``PROFORMA_SECTIONS`` matches the numbered sections no other pension document
prints together. The structural match also keeps ``_verify_proforma_claim`` from denying a
title-less proforma the model DID recognise -- a denial there files the page as OTHER, which is
how a correct classification used to cost the office a document.

No figures from a real servant's papers appear here.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extraction.identify import (  # noqa: E402
    PROFORMA_SECTIONS, PROFORMA_TITLE, titles_on_page,
)
from rules.checklist import ALL_VARIANTS, requirements_for  # noqa: E402

#: OCR of the filed proforma, in the shape the reader returns it: the sections, no heading.
#: Names and numbers are invented; the structure is what is under test.
NO_HEADING = (
    "1 PARTICULARS OF EMPLOYEE A B SAMPLE 1 NAME OF EMPLOYEE A B SAMPLE "
    "2 SERVICE RECORD SUMMARY 3 PAY FIXATION 4 PENSION CONTRIBUTION PENSIONARY SHARE "
    "IF APPLICABLE 5 PERSONAL NO 00000000 ON SERVICE BOOK IS COMPLETE IN ALL RESPECT"
)
#: A service statement from a school: a service record, but not this form.
SERVICE_STATEMENT = (
    "OFFICE OF THE PRINCIPAL SERVICE STATEMENT It is certified that A B Sample is working as "
    "Chowkidar Name of Institution District Service Period Signature With Stamp Remarks "
    "Service Book Attached STOP PAYMENT CERTIFICATE"
)
#: Form B-I also speaks of qualifying service and pay, and must not be taken for the proforma.
FORM_B_I = (
    "NOTIFICATION ORDERS OF RETIREMENT ON SUPERANNUATION AND SANCTION OF PENSION BENEFITS "
    "Total length of qualifying service for pension is 36 years PAY FIXATION has been done"
)


class TheHeadingIsNotTheIdentification(unittest.TestCase):

    def test_the_filed_proforma_prints_no_title_the_old_pattern_needed(self) -> None:
        self.assertIsNone(re.search(PROFORMA_TITLE, NO_HEADING.lower()))

    def test_its_sections_identify_it_anyway(self) -> None:
        self.assertIsNotNone(re.search(PROFORMA_SECTIONS, NO_HEADING.lower()))
        self.assertIn("QUALIFYING_SERVICE_PROFORMA", titles_on_page(NO_HEADING))

    def test_a_service_statement_is_not_the_proforma(self) -> None:
        self.assertNotIn("QUALIFYING_SERVICE_PROFORMA", titles_on_page(SERVICE_STATEMENT))

    def test_the_sanction_form_is_not_the_proforma(self) -> None:
        """It prints "qualifying service" and "PAY FIXATION" but not the sections, in order."""
        self.assertNotIn("QUALIFYING_SERVICE_PROFORMA", titles_on_page(FORM_B_I))

    def test_three_headings_scattered_across_a_sheet_do_not_combine(self) -> None:
        """The gaps are bounded: unrelated paragraphs between them are not one form."""
        far_apart = ("PARTICULARS OF EMPLOYEE" + " filler" * 200
                     + " SERVICE RECORD SUMMARY" + " filler" * 200 + " PAY FIXATION")
        self.assertIsNone(re.search(PROFORMA_SECTIONS, far_apart.lower()))


class TheOfficeAsksForItInEveryCase(unittest.TestCase):

    def test_ag_26_applies_to_every_variant(self) -> None:
        for variant in ALL_VARIANTS:
            with self.subTest(variant=variant):
                ids = [r.id for r in requirements_for(variant)]
                self.assertIn("AG-26", ids)

    def test_ag_26_is_satisfied_only_by_the_proforma(self) -> None:
        line = next(r for r in requirements_for("FRESH_SELF") if r.id == "AG-26")
        self.assertEqual(line.satisfied_by, ("QUALIFYING_SERVICE_PROFORMA",))

    def test_the_service_book_is_no_longer_required_anywhere(self) -> None:
        """AG-10 is kept so a book that IS filed is cited, but it never counts as missing."""
        from rules.checklist import NOT_REQUIRED_ANYWHERE
        self.assertIn("AG-10", NOT_REQUIRED_ANYWHERE)
        self.assertNotIn("AG-26", NOT_REQUIRED_ANYWHERE)


if __name__ == "__main__":
    unittest.main()
