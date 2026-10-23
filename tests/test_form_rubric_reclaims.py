"""A prescribed form that prints no number is still recognised, by its own printed rubric.

Form B-I IS the retirement notification -- "NOTIFICATION/ORDERS OF RETIREMENT ON
SUPERANNUATION AND SANCTION OF PENSION BENEFITS" -- so a vision model that files the page as
SUPERANNUATION_ORDER is describing it correctly and still costs the office the line, because
the checklist asks for the PRESCRIBED form. Where the page also prints no form number that
OCR catches, there was nothing left to reclaim it on.

Swept over 503 real pages on 20 Oct 2026: eleven genuine Form B-I pages across nine bundles
were filed as SUPERANNUATION_ORDER or ANNEX_A for exactly that reason.

The second phrase comes off the page instead -- the instruction printed at the head of the
blank form:

    "(To be issued by the Appointing authority 90 days before superannuation of the
     retiring Government servant)"

On those 503 pages it appeared on 17, every one a genuine prescribed form, and on nothing
else. Not on the forwarding letter that lists "Annex-B-I (Form)" among its enclosures, and
not on the departmental checklist that lists "Annexure Pension form B-I" -- the two documents
that print a form's NUMBER without being one, and which the number-only rule already had to
be careful of.

It says the page is a prescribed form. It does not say WHICH -- the B and D forms share it --
so it corroborates and never decides.

    python3 -m unittest tests.test_form_rubric_reclaims -v
"""
from __future__ import annotations

import unittest
import unittest.mock

from extraction import identify as I
from extraction.ocr import OCR_MODEL, PageText, form_rubric_on

RUBRIC = ("(To be issued by the Appointing authority 90 days before superannuation of the "
          "retiring Government servant).")

#: run-2a871e80e5d2 p.15. A genuine Form B-I. OCR reads the title (one letter short of
#: RETIREMENT) and no number; the model called it SUPERANNUATION_ORDER and transcribed no
#: number at all. Before the rubric there was nothing to reclaim it on.
NO_NUMBER_ANYWHERE = (
    RUBRIC + "\nSubject:-\nNOTIFICATION/ORDERS OF RETIREMNT ON SUPERANNUATION AND SANCTION "
    "OF PENSION BENEFITS.\nNotification / Order No.154-2025 Dated 05-06-2025 issued by "
    "OFFICE OT THE PRINCIPAL Govt. Pilot Higher Secondary School, Wahdat Colony, Lahore.")

#: run-ffd0a4b6ad49 p.1. The same form, whose subject line prints the words the other way
#: round -- "ORDERS OF SUPERANUATION RETIREMENT" -- so no title phrase matches it at all.
#: The model transcribed "FORM B-I", and the rubric is what makes that safe to take.
TITLE_UNRECOGNISABLE = (
    RUBRIC + "\nSubject: -NOTIFICATION/ORDERS OF SUPERANUATION RETIREMENT AND SANCTIONOF "
    "PENSION BENEFITS.\nNotification of the District Education Officer (W-EE) Lahore O/O "
    "No. 3764/ LHR/ 2025 dated 06-05-2025 on superannuation retirement, Mst. Syada Alae "
    "Batool Naqvi EST BS=15.")

#: run-53fbf89a8c6c p.2. Prints a form NUMBER and is a covering letter.
FORWARDING_LETTER = (
    "To\nThe Office of the Accountant General Punjab, Lahore.\nPension case of Mr. Safdar Ali received in "
    "this office through District Education Officer (SE) Lahore. The same case alongwith all "
    "relevant papers is hereby submitted.\nDocuments Details are as under:\n1. Annex-A "
    "(Form).\n2. Annex-B-I (Form).\n3. Retirement Notification.\n4. Copy if CNIC.")

#: run-896d259e3dfb p.3. Prints a form NUMBER and is a departmental checklist.
CHECKLIST = (
    "No. Application. Attested copy of CNIC on full page. Original Retirement Notification. "
    "Last Pay certificate issued by the accountant General Punjab, Lahore. Annexure Pension "
    "form B-I . List of family members duly countersigned by DEO concerned.(Annex-A)")


def _ident(label: str, printed: str | None) -> I.PageIdentity:
    return I.PageIdentity(page=15, document_type=label, confidence=1.0, evidence=printed or "",
                          is_first_page=True, printed_form_number=printed)


def _reclaim(ident: I.PageIdentity, text: str) -> I.PageIdentity:
    page = PageText(page=15, text=text, model=OCR_MODEL)
    with unittest.mock.patch("extraction.ocr.ocr_page", lambda *a, **k: page):
        return I._reclaim_form(ident, "/img/p15.png")[0]


def _page(text: str) -> PageText:
    return PageText(page=15, text=text, model=OCR_MODEL)


class TheRubricMarksAPrescribedForm(unittest.TestCase):
    def test_it_is_on_the_forms(self) -> None:
        self.assertTrue(form_rubric_on(_page(NO_NUMBER_ANYWHERE)))
        self.assertTrue(form_rubric_on(_page(TITLE_UNRECOGNISABLE)))

    def test_it_is_not_on_the_documents_that_merely_list_a_form(self) -> None:
        """These two are why the rubric is worth having: both print a form NUMBER."""
        self.assertFalse(form_rubric_on(_page(FORWARDING_LETTER)))
        self.assertFalse(form_rubric_on(_page(CHECKLIST)))


class ReclaimOnTheRubric(unittest.TestCase):
    def test_a_form_nobody_numbered_is_reclaimed_on_its_title(self) -> None:
        out = _reclaim(_ident("SUPERANNUATION_ORDER", ""), NO_NUMBER_ANYWHERE)
        self.assertEqual(out.document_type, "FORM_B_I")
        self.assertEqual(out.promoted_from, "SUPERANNUATION_ORDER")

    def test_a_title_past_recognition_falls_back_to_the_model_s_number(self) -> None:
        out = _reclaim(_ident("SUPERANNUATION_ORDER", "FORM B-I"), TITLE_UNRECOGNISABLE)
        self.assertEqual(out.document_type, "FORM_B_I")

    def test_without_the_rubric_that_same_page_is_left_alone(self) -> None:
        """The rubric is doing the work, not the title: the identical text without the
        instruction line reclaims nothing."""
        without = NO_NUMBER_ANYWHERE.replace(RUBRIC, "")
        self.assertEqual(_reclaim(_ident("SUPERANNUATION_ORDER", ""), without).document_type,
                         "SUPERANNUATION_ORDER")

    def test_a_covering_letter_is_not_a_form(self) -> None:
        for label, text in (("OTHER", FORWARDING_LETTER), ("OTHER", CHECKLIST)):
            with self.subTest(text=text[:40]):
                self.assertEqual(_reclaim(_ident(label, ""), text).document_type, "OTHER")

    def test_a_model_number_naming_another_form_blocks_it(self) -> None:
        """The readers disagree about which form it is; that is left for a person."""
        out = _reclaim(_ident("SUPERANNUATION_ORDER", "FORM B-II"), NO_NUMBER_ANYWHERE)
        self.assertEqual(out.document_type, "SUPERANNUATION_ORDER")
        self.assertIsNone(out.promoted_from)

    def test_two_titles_on_one_sheet_are_left_for_a_person(self) -> None:
        both = NO_NUMBER_ANYWHERE + " APPLICATION FOR ANTICIPATORY PENSION under article 922"
        self.assertEqual(_reclaim(_ident("SUPERANNUATION_ORDER", ""), both).document_type,
                         "SUPERANNUATION_ORDER")

    def test_a_reader_that_looped_reclaims_nothing(self) -> None:
        looped = RUBRIC + "\n" + "In terms of full pay\n" * 60
        self.assertEqual(_reclaim(_ident("SUPERANNUATION_ORDER", "FORM B-I"), looped).document_type,
                         "SUPERANNUATION_ORDER")


if __name__ == "__main__":
    unittest.main()
