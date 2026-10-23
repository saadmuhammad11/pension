"""A page's own printed heading names the checklist document it is. ``TITLE-01``.

Found 17 Sep 2026 by comparing the checklist against the office's own sheet and against the
other deployment: page 5 of the disabled-son bundle is headed "LIST OF FAMILY MEMBERS OF
Abdul Waheed Qureshi", the identifier filed it as an AFFIDAVIT because it is sworn before an
oath commissioner, and AG-05 reported the list of family members MISSING while it sat in the
bundle. Nine pages across the sixteen real bundles were mislabelled this way.

Standard library only; no GPU and no network.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class WhatAHeadingNames(unittest.TestCase):
    def test_the_titles_the_office_sheet_names(self):
        from extraction.identify import titles_on_page
        self.assertEqual(titles_on_page("LIST OF FAMILY MEMBERS OF Abdul Waheed Qureshi"), ("ANNEX_A",))
        self.assertEqual(titles_on_page("SOLE FAMILY CERTIFICATE ... sole family member and widow"),
                         ("SOLE_WIDOW_CERTIFICATE",))
        self.assertEqual(titles_on_page("ENTITLEMENT OF ARREARS CERTIFICATE"),
                         ("ARREARS_ENTITLEMENT_CERTIFICATE",))
        self.assertEqual(titles_on_page("NO-REGULAR SOURCE OF INCOME CERTIFICATE"),
                         ("NO_REGULAR_INCOME_CERTIFICATE",))

    def test_a_bare_affidavit_names_nothing(self):
        from extraction.identify import titles_on_page
        self.assertEqual(titles_on_page("AFFIDAVIT sworn before an OATH COMMISSIONER, LAHORE"), ())
        self.assertEqual(titles_on_page(""), ())

    def test_a_page_printing_two_headings_names_both(self):
        from extraction.identify import titles_on_page
        self.assertEqual(titles_on_page("LIST OF FAMILY MEMBERS ... NO DEMAND CERTIFICATE"),
                         ("ANNEX_A", "NDC"))

    def test_three_certificates_on_one_sworn_page_are_all_found(self):
        """Case 71b639daac14 p.12: one affidavit sheet carrying three certificates."""
        from extraction.identify import titles_on_page
        text = ("SOLE WIDOW CERTIFICATE ... NO REGULAR SOURCE OF INCOME CERTIFICATE ... "
                "CERTIFICATE OF ENTITLEMENT OF ARREARS")
        self.assertEqual(titles_on_page(text), ("ARREARS_ENTITLEMENT_CERTIFICATE",
                                                "NO_REGULAR_INCOME_CERTIFICATE",
                                                "SOLE_WIDOW_CERTIFICATE"))

    def test_a_death_certificate_mentioned_in_a_form_is_not_a_title(self):
        """Form D-II's own text says "death certificate is attached"; that is not a heading."""
        from extraction.identify import titles_on_page
        self.assertEqual(titles_on_page("expired on 28-2-21 (death certificate is attached)"), ())


class WhichPagesAreReconsidered(unittest.TestCase):
    def _run(self, tmp: Path, rows, ocr):
        import json
        (tmp / "manifest.json").write_text(json.dumps(
            {"pages": [{"page": r["page"], "image_path": f"pages/p{r['page']:03}.png"} for r in rows]}))
        (tmp / "ocr_text.json").write_text(json.dumps({str(p): t for p, t in ocr.items()}))
        return rows

    def test_an_affidavit_headed_as_a_list_adds_the_list_and_keeps_the_affidavit(self):
        import tempfile
        from pipeline.run import documents_named_by_their_own_heading
        from rules.caserecord import Document
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            rows = self._run(tmp, [{"page": 5, "document_type": "AFFIDAVIT", "attested": True}],
                             {5: "LIST OF FAMILY MEMBERS OF Abdul Waheed Qureshi. I solemnly declare"})
            existing = (Document("AFFIDAVIT", (5,)),)
            added = documents_named_by_their_own_heading(tmp, rows, existing)
        self.assertEqual([d.type for d in added], ["ANNEX_A"])
        self.assertEqual(added[0].pages, (5,))
        self.assertTrue(added[0].present)
        self.assertEqual(added[0].defects, ())          # present is not defective
        self.assertIs(added[0].attested, True)

    def test_the_commutation_option_printed_on_an_annexure_a_counts(self):
        """Agriculture, 29 Sep 2026: page 6 is the office's Annexure-A, whose own section reads
        "I hereby opt full pension without commutation or commutation @ ..."; the identifier
        filed it as ANNEX_A and AG-07 reported the option for commutation MISSING."""
        import tempfile
        from extraction.identify import statements_on_page
        from pipeline.run import documents_named_by_their_own_heading
        from rules.caserecord import Document
        self.assertEqual(statements_on_page("ANNEX_A", "Annexure-A ... I hereby opt full pension without commutation or commutation @---"), ("COMMUTATION_OPTION",))
        self.assertEqual(statements_on_page("ANNEX_A", "OPTION FOR COMMUTATION of pension"), ("COMMUTATION_OPTION",))
        self.assertEqual(statements_on_page("ANNEX_A", "LIST OF FAMILY MEMBERS only"), ())
        self.assertEqual(statements_on_page("LPC", "I hereby opt full pension without commutation"), ())   # only pages that carry it
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            # OCR of the poor scan missed the line; the identifier's own quotation of it stands in.
            rows = self._run(tmp, [{"page": 6, "document_type": "ANNEX_A", "attested": True,
                                    "evidence": "The page contains the heading 'Annexure-A' and includes a section with the text "
                                                "'I hereby opt full pension without commutation or commutation @---'"}],
                             {6: "Annexure-A descriptive roll"})
            added = documents_named_by_their_own_heading(tmp, rows, (Document("ANNEX_A", (6,)),))
        self.assertEqual([(d.type, d.pages, d.present, d.attested) for d in added], [("COMMUTATION_OPTION", (6,), True, True)])
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            rows = self._run(tmp, [{"page": 6, "document_type": "ANNEX_A"}], {6: "Annexure-A descriptive roll, undertaking"})
            self.assertEqual(documents_named_by_their_own_heading(tmp, rows, (Document("ANNEX_A", (6,)),)), ())

    def test_an_other_page_is_named_by_the_heading_the_model_quoted(self):
        """PC-2026-000042 p.8, 23 Oct 2026: the proforma the office filed and the sheet missed.

        OCR read 555 characters of the page's body -- "PARTICULARS OF EMPLOYEE" and the
        numbered particulars under it -- then degenerated into "OI - OZ - 2O26" five times
        over, never reaching the title line or section 2, so neither the proforma's title
        pattern nor its section pattern could match. The identifier had answered OTHER and
        quoted the title verbatim in its evidence. AG-26 was reported missing against a
        department that had filed the document, twice.
        """
        import tempfile
        from pipeline.run import documents_named_by_their_own_heading
        ocr = ("1. PARTICULARS OF EMPLOYEE I. Name of Employee: II. Father's Name/Husband's Name: "
               "MUHAMMAD IBRAHIM III. CNIC Number: 35102-0300 880-1 IV. Nationality PAKISTANT "
               "XI. Date of Superauuantion OI - OZ - 2O26 OI - OZ - 2O26 OI - OZ - 2O26")
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            rows = self._run(tmp, [{"page": 8, "document_type": "OTHER",
                                    "evidence": "PERFORMA FOR QUALIFYING SERVICE FOR PENSION"}],
                             {8: ocr})
            added = documents_named_by_their_own_heading(tmp, rows, ())
        self.assertEqual([d.type for d in added], ["QUALIFYING_SERVICE_PROFORMA"])
        self.assertEqual(added[0].pages, (8,))
        self.assertTrue(added[0].present)

    def test_the_ocr_alone_still_names_what_it_can_read(self):
        """The quotation is a second reading, not a replacement: OCR on its own still counts."""
        import tempfile
        from pipeline.run import documents_named_by_their_own_heading
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            rows = self._run(tmp, [{"page": 8, "document_type": "OTHER", "evidence": ""}],
                             {8: "PERFORMA FOR QUALIFYING SERVICE FOR PENSION. 1. PARTICULARS OF EMPLOYEE"})
            added = documents_named_by_their_own_heading(tmp, rows, ())
        self.assertEqual([d.type for d in added], ["QUALIFYING_SERVICE_PROFORMA"])

    def test_a_page_the_model_merely_describes_gains_no_document(self):
        """Evidence that talks ABOUT a page rather than quoting it must not name a document."""
        import tempfile
        from pipeline.run import documents_named_by_their_own_heading
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            rows = self._run(tmp, [{"page": 17, "document_type": "OTHER",
                                    "evidence": "The page contains a stamped and signed document with Urdu "
                                                "text, a QR code, and a reference number. There is no printed "
                                                "form number (e.g., FORM B-I)."}],
                             {17: "stamped page, urdu text"})
            self.assertEqual(documents_named_by_their_own_heading(tmp, rows, ()), ())

    def test_a_specifically_labelled_page_is_left_alone(self):
        import tempfile
        from pipeline.run import documents_named_by_their_own_heading
        from rules.caserecord import Document
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            rows = self._run(tmp, [{"page": 7, "document_type": "NADRA_FRC"}],
                             {7: "LIST OF FAMILY MEMBERS ..."})
            added = documents_named_by_their_own_heading(tmp, rows, (Document("NADRA_FRC", (7,)),))
        self.assertEqual(added, ())

    def test_nothing_is_added_twice(self):
        import tempfile
        from pipeline.run import documents_named_by_their_own_heading
        from rules.caserecord import Document
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            rows = self._run(tmp, [{"page": 5, "document_type": "OTHER"}],
                             {5: "LIST OF FAMILY MEMBERS"})
            added = documents_named_by_their_own_heading(tmp, rows, (Document("ANNEX_A", (5,)),))
        self.assertEqual(added, ())


class TheForwardingLetterNamesTheClaimant(unittest.TestCase):
    """The department's own subject line is a variant source. Found 17 Sep 2026.

    The disabled-son bundle's Form D-II yielded a claimant relation of "Husband" -- the page
    read degenerately -- and the case went to the WIDOW column, which asks for a sole-widow
    certificate and a non-remarriage certificate on a claim by two disabled children.
    """

    SUBJECT = ("To: Accountant General Punjab Lahore. Subject: FAMILY PENSION PAPERS OF "
               "MISS. ASIA BIBI QURESHI (MENTALLY DISABLE DAUGHTER) AND MR. MUHAMMAD "
               "HARIS QURESHI (MENTALLY DISABLED SON)")

    def test_the_letter_outranks_a_single_word_in_a_handwritten_relation_box(self):
        from rules.case_type import suggest_variant
        got = suggest_variant("FAMILY_PENSION_DEATH_AFTER_RETIREMENT", "",
                              claimant_relation="Husband", forwarding_subject=self.SUBJECT)
        self.assertEqual(got.variant, "DISABLED_CHILD_SIBLING")
        self.assertIn("forwarding letter", got.evidence)

    def test_disable_without_the_d_is_still_disabled(self):
        from rules.case_type import suggest_variant
        got = suggest_variant("FAMILY_PENSION_DEATH_AFTER_RETIREMENT", "",
                              claimant_relation="Son, Disable")
        self.assertEqual(got.variant, "DISABLED_CHILD_SIBLING")

    def test_every_relation_the_real_bundles_state_still_maps_the_same_way(self):
        from rules.case_type import suggest_variant
        for relation, expected in (("widow", "WIDOW"),
                                   ("w/o Khan Bahadur", "WIDOW"),
                                   ("widow daughter of late Muhammad Bashir", "WD_DAUGHTER"),
                                   ("divorce daughter", "DIVORCED_DAUGHTER")):
            got = suggest_variant("FAMILY_PENSION_DEATH_AFTER_RETIREMENT", "",
                                  claimant_relation=relation)
            self.assertEqual(got.variant, expected, relation)

    def test_a_letter_that_names_no_class_decides_nothing(self):
        from rules.case_type import suggest_variant
        got = suggest_variant("FAMILY_PENSION_DEATH_AFTER_RETIREMENT", "",
                              claimant_relation="",
                              forwarding_subject="Subject: PENSION CASE of Mst. Saima Rasheed PST")
        self.assertIsNone(got.variant)


class OneDeathDatePerCase(unittest.TestCase):
    """The determination's resolved date governs the checklist too. Found 17 Sep 2026.

    The disabled-son report carried two: the pension was computed on 2021-02-28, read from
    the form's "expired on" clause, while item 19 measured lateness from 2024-02-28 -- the
    field read, which the model had also put in the retirement box -- and so called a
    five-year-old case recent and asked the department for no explanation.
    """

    def test_the_report_prefers_the_determination_date_over_the_field_read(self):
        import json
        import tempfile
        from datetime import date
        from pipeline.report import _as_date
        with tempfile.TemporaryDirectory() as t:
            run = Path(t)
            (run / "determination.json").write_text(json.dumps(
                {"determination": {"inputs": {"date_of_death_of_pensioner": "2021-02-28"}}}))
            got = json.loads((run / "determination.json").read_text())
            resolved = _as_date(str(got["determination"]["inputs"]["date_of_death_of_pensioner"]))
        self.assertEqual(resolved, date(2021, 2, 28))
        # the field read on the same bundle, which must not win -- and since 7 Oct 2026 (L1)
        # cannot: a two-digit year is refused by the parser and raised for the officer instead
        self.assertIsNone(_as_date("28-2-24"))


if __name__ == "__main__":
    unittest.main()
