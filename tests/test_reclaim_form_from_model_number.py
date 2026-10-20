"""A form the model mislabelled while reading its number correctly is still reclaimed.

On the 78-page bundle of 20 Oct 2026 page 17 was the department's Form B-I. The vision model
filed it ANNEX_A at confidence 1.00 and, in the same read, reported printed_form_number
"Annex-B-1". OCR read the page cleanly and recognised the scenario title as Form B-I's, but
never transcribed the label in the corner -- so forms_printed_on() was empty, _reclaim_form
required one printed number, nothing was reclaimed, and the checklist reported the Pension
Sanctioning Authority form MISSING against a department that had filed it.

Why this is allowed to overrule the model when its self-report normally corroborates nothing:
the model is CONTRADICTING itself. The number it transcribed says Form B-I and the label it
concluded says ANNEX_A, and the independent reader's title agrees with the number. The weaker
of the two readings is the model's own conclusion, not its transcription.

The bar is otherwise unchanged, and these tests hold that: a number OCR found still decides on
its own terms, the title must still agree, and a reader that looped supplies nothing.

    python3 -m unittest tests.test_reclaim_form_from_model_number -v
"""
from __future__ import annotations

import unittest
import unittest.mock

from extraction import identify as I
from extraction.ocr import OCR_MODEL, PageText

#: Form B-I's own scenario title, as the page prints it, with no form number anywhere.
TITLE_ONLY = ("(To be issued by the appointing Authority 90 days before superannuation of the "
              "retiring Government servant) Subject. NOTIFICATION/ORDERS OF RETIREMENT ON "
              "SUPERANNUATION AND SANCTION OF PENSIONARY BENEFITS. On attaining the age of "
              "superannuation, MR. SAFDAR ALI S/o Muhammad Ashiq, Designation EST (V), "
              "drawing pay Rs. 84570 reckonable for pension, in BS 15, is hereby retired.")


#: The same page without the forms' printed rubric -- the scenario title and nothing else.
#: What the model's own transcribed number has to carry on its own.
NO_RUBRIC = ("Subject. NOTIFICATION/ORDERS OF RETIREMENT ON SUPERANNUATION AND SANCTION OF "
             "PENSIONARY BENEFITS. On attaining the age of superannuation, MR. SAFDAR ALI "
             "S/o Muhammad Ashiq, Designation EST (V), drawing pay Rs. 84570, in BS 15.")


def _ident(label: str, printed: str | None) -> I.PageIdentity:
    return I.PageIdentity(page=17, document_type=label, confidence=1.0, evidence=printed or "",
                          is_first_page=True, printed_form_number=printed)


def _reclaim(ident: I.PageIdentity, text: str):
    page = PageText(page=17, text=text, model=OCR_MODEL)
    with unittest.mock.patch("extraction.ocr.ocr_page", lambda *a, **k: page):
        return I._reclaim_form(ident, "/img/p17.png")[0]


class ReclaimFromModelNumber(unittest.TestCase):
    def test_the_fixture_is_the_case_as_measured(self) -> None:
        from extraction.ocr import form_titles_on, forms_printed_on
        page = PageText(page=17, text=TITLE_ONLY, model=OCR_MODEL)
        self.assertEqual(forms_printed_on(page), (), "OCR must find no printed number")
        self.assertIn("FORM_B_I", form_titles_on(page), "but must recognise the title")

    def test_the_model_s_own_number_reclaims_the_form(self) -> None:
        out = _reclaim(_ident("ANNEX_A", "Annex-B-1"), TITLE_ONLY)
        self.assertEqual(out.document_type, "FORM_B_I")
        self.assertEqual(out.promoted_from, "ANNEX_A")

    def test_a_number_that_disagrees_with_the_title_reclaims_nothing(self) -> None:
        """Two readings must agree. B-II's number against B-I's title is not agreement."""
        out = _reclaim(_ident("ANNEX_A", "Annex-B-2"), TITLE_ONLY)
        self.assertEqual(out.document_type, "ANNEX_A")
        self.assertIsNone(out.promoted_from)

    def test_without_the_rubric_the_model_must_supply_the_number(self) -> None:
        """A title on its own has never been enough to overrule the model, and still is not."""
        out = _reclaim(_ident("ANNEX_A", None), NO_RUBRIC)
        self.assertEqual(out.document_type, "ANNEX_A")

    def test_a_label_that_is_not_a_form_reclaims_nothing(self) -> None:
        """Annex-A is a descriptive roll; it parses to no prescribed form, and without the
        rubric there is no second phrase to carry the page on its own."""
        out = _reclaim(_ident("ANNEX_A", "Annex-A"), NO_RUBRIC)
        self.assertEqual(out.document_type, "ANNEX_A")

    def test_a_reader_that_looped_reclaims_nothing(self) -> None:
        looped = "Form of leave account\n" + "In terms of full pay\n" * 60
        out = _reclaim(_ident("ANNEX_A", "Annex-B-1"), looped)
        self.assertEqual(out.document_type, "ANNEX_A",
                         "loop-garbage is not a second reading and cannot promote either")

    def test_a_number_ocr_itself_found_still_governs(self) -> None:
        out = _reclaim(_ident("ANNEX_A", "Annex-B-2"), "Annex-B-1 " + TITLE_ONLY)
        self.assertEqual(out.document_type, "FORM_B_I",
                         "OCR's own number decides on its own terms, not the model's")


if __name__ == "__main__":
    unittest.main()
