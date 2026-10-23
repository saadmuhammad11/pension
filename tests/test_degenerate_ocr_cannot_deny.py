"""A reader that looped has not read the page, and may not withdraw a form classification.

On a real 78-page bundle the vision model called pages 74, 76 and 78 FORM_B_I at confidence
0.95. The OCR second reading came back 97% repeated -- "In terms of full pay", 319 times,
cut off mid-word at the token cap -- and printed no form number. _verify_form_claim read that
silence as "no Form B-I number is printed here", downgraded all three to OTHER, and the
checklist reported the Pension Sanctioning Authority form MISSING against the department
while it sat in the bundle (20 Oct 2026).

looks_degenerate() already existed for this: "it is not noise, it is confident noise". It was
applied to the card and attestation paths and not to this one.

The distinction this holds: a DEGENERATE read does not verify and does not deny; a CLEAN read
that finds no form number still denies, which is the check's whole purpose.

    python3 -m unittest tests.test_degenerate_ocr_cannot_deny -v
"""
from __future__ import annotations

import unittest

from extraction.identify import PageIdentity, _verify_form_claim
from extraction.ocr import OCR_MODEL, PageText, form_titles_on, forms_printed_on, looks_degenerate

#: What the reader actually returned for page 74, in miniature.
LOOPED = PageText(page=74, text=("Form of leave account of Mr./Miss Mrs.\n"
                                 + "In terms of full pay\n" * 60), model=OCR_MODEL)
#: A real reading of a page that simply prints no form number.
CLEAN = PageText(page=23, text=("Office of the District Education Officer, Lahore. "
                                "This is to certify that no demand is outstanding against "
                                "the government servant named below, who retired on "
                                "superannuation. Signed, Deputy District Education Officer, "
                                "dated December 30 2025, for onward submission to the office "
                                "of the Office of the Accountant General Punjab for further necessary action."),
                 model=OCR_MODEL)


def _claim(page: int, doc_type: str) -> PageIdentity:
    return PageIdentity(page=page, document_type=doc_type, confidence=0.95,
                        evidence="form heading", is_first_page=True)


def _verify(ident: PageIdentity, text: PageText) -> PageIdentity:
    """The call site's rule, as verify_with_ocr applies it."""
    unreadable = looks_degenerate(text)
    return _verify_form_claim(ident,
                              None if unreadable else forms_printed_on(text),
                              None if unreadable else form_titles_on(text))


class DegenerateOcrCannotDeny(unittest.TestCase):
    def test_the_fixture_reproduces_the_two_readings(self) -> None:
        self.assertTrue(looks_degenerate(LOOPED), "the looping read must register as degenerate")
        self.assertFalse(looks_degenerate(CLEAN), "the clean read must not")
        self.assertEqual(forms_printed_on(LOOPED), ())
        self.assertEqual(forms_printed_on(CLEAN), ())

    def test_a_looping_read_does_not_withdraw_the_claim(self) -> None:
        out = _verify(_claim(74, "FORM_B_I"), LOOPED)
        self.assertEqual(out.document_type, "FORM_B_I")
        self.assertIsNone(out.downgraded_from)

    def test_a_clean_read_with_no_form_number_still_denies(self) -> None:
        """The check's purpose. Losing this would let any claim through unverified."""
        out = _verify(_claim(23, "FORM_B_II"), CLEAN)
        self.assertEqual(out.document_type, "OTHER")
        self.assertEqual(out.downgraded_from, "FORM_B_II")

    def test_the_old_behaviour_is_what_broke(self) -> None:
        """Passing the looped read as evidence -- what the code did -- denies a real form."""
        out = _verify_form_claim(_claim(74, "FORM_B_I"),
                                 forms_printed_on(LOOPED), form_titles_on(LOOPED))
        self.assertEqual(out.document_type, "OTHER")


if __name__ == "__main__":
    unittest.main()
