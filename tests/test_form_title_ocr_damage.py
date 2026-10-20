"""A form title damaged by OCR still identifies its form.

Three pages of a real 28-page bundle were a genuine Form B-I -- the vision model even
transcribed "FORM B-I" as the printed number. The reader returned the title as

    "NOTIFICATION/ORDERS OF RETIREMNT ON SUPERANNUATION AND SANCTION OF PENSION BENEFITS"

one letter short of RETIREMENT. form_titles_on tested with `phrase in text`, so it found
nothing; forms_printed_on had not captured the number either; _verify_form_claim read the
double silence as "this is not a Form B-I" and withdrew all three. The checklist then reported
the Pension Sanctioning Authority form MISSING against a department that had filed it
(20 Oct 2026).

_designations_in in the same module already matches this way, for the same stated reason: the
reader "dropped two characters out of the middle of the word, which is ordinary for a rubber
stamp on a photocopy of a photocopy". Titles are damaged by the same reader.

What must NOT be lost is discrimination -- _FORM_TITLES only holds phrases that separate one
form from its neighbours, and a loose match that let B-I's title confirm a B-II claim would
confirm exactly the false positive the check exists to stop.

The first version of this match compared the phrase with a same-length window as ONE STRING,
and lost exactly that. Swept over 500 real pages it read "Form B-I" off a Last Pay
Certificate, a Last Pay and Service Statement and an Annex-A undertaking, because a run of
near-misses averages out to a pass. The class below is those three pages. They are not a
miss but a FALSE POSITIVE, which is the worse half: _verify_form_claim accepts a title alone
where no number is printed, so a spurious title does not fail to find a form -- it confirms
the model's claim of the wrong one.

    python3 -m unittest tests.test_form_title_ocr_damage -v
"""
from __future__ import annotations

import unittest

from extraction.ocr import OCR_MODEL, PageText, _FORM_TITLES, form_titles_on


def _titles(text: str) -> tuple[str, ...]:
    return form_titles_on(PageText(page=1, text=text, model=OCR_MODEL))


#: Pages 21, 25 and 28, as the reader actually returned them.
DAMAGED = ("1 (To be issued by the Appointing authority 90 days before superannuation of the "
           "retiring Government servant). Subject:- NOTIFICATION/ORDERS OF RETIREMNT ON "
           "SUPERANNUATION AND SANCTION OF PENSION BENEFITS")
#: The same document read cleanly, which already worked.
CLEAN = ("(To be issued by the appointing Authority 90 days before superannuation of the "
         "retiring Government servant) Subject. NOTIFICATION/ORDERS OF RETIREMENT ON "
         "SUPERANNUATION AND SANCTION OF PENSIONARY BENEFITS")


#: Real pages, as the reader returned them, that are NOT the form their words brush against.
NOT_A_FORM = {
    "a Last Pay Certificate":
        "Last pay certificate Office of the DY.DEO (W-EE) TEHSIL SHALIMAR LAHORE. Name of "
        "Govt. Servant: Yasmin Hanif Designation: EST Scale of pay : BPS NO. 15 Proceeding "
        "due to: Retirement (Superannuation) She will be paid up to 18-08-2026",
    "a Last Pay and Service Statement":
        "Form No. 5 Last Pay and Service Statement Date 25.09.2025 Office: Accountant "
        "General-Punjab Lahore ABDUL WAIAD OSD DECEASED Retired on Superanuation w.e.f "
        "21,03,2023 at the following rates",
    "an Annex-A undertaking":
        "(Annex-A) (Under Articale-920 (1) CSR I Muhammad Shafique herby under take to refund "
        "the amount established against me. DECLARATION OF NON-RECEIPT OF PENSION/ "
        "ANTICIPATORY PENSION OR GRATUITY (Under Articale-922 (a) CSR",
}


class ADifferentWordIsNotADamagedOne(unittest.TestCase):
    """The slot has to hold THAT word, damaged -- not some other word that reads like it."""

    def test_none_of_these_pages_names_a_form(self) -> None:
        for what, text in NOT_A_FORM.items():
            with self.subTest(page=what):
                self.assertEqual(_titles(text), (), f"{what} must not name a form")

    def test_the_words_that_fooled_it_are_the_ones_being_rejected(self) -> None:
        """Named so the next person can see what the bar is actually doing: DUE is not
        RETIREMENT, RETIRED is not RETIREMENT, and OF is not FOR."""
        for phrase in ("Proceeding due to Retirement Superannuation",
                       "Retired on Superanuation w.e.f",
                       "non-receipt of pension anticipatory pension or gratuity"):
            with self.subTest(phrase=phrase):
                self.assertEqual(_titles(phrase), ())


class FormTitleOcrDamage(unittest.TestCase):
    def test_a_dropped_letter_still_identifies_the_form(self) -> None:
        self.assertEqual(_titles(DAMAGED), ("FORM_B_I",))

    def test_the_clean_reading_is_unaffected(self) -> None:
        self.assertEqual(_titles(CLEAN), ("FORM_B_I",))

    def test_every_title_still_matches_only_its_own_form(self) -> None:
        """Discrimination is the property _FORM_TITLES exists for; looseness must not cost it."""
        for name, phrases in _FORM_TITLES.items():
            for phrase in phrases:
                with self.subTest(form=name, phrase=phrase):
                    got = _titles(f"FAMILY PENSION FORM {phrase} of the government servant")
                    self.assertEqual(got, (name,), f"{phrase!r} must identify {name} alone")

    def test_a_page_with_no_form_title_matches_nothing(self) -> None:
        self.assertEqual(_titles("No demand certificate issued by the District Education "
                                 "Officer, Lahore, in respect of the above-named official."), ())

    def test_a_neighbouring_form_is_not_confirmed(self) -> None:
        """B-I's own title must never corroborate a B-II or B-IV claim."""
        got = _titles(CLEAN)
        self.assertNotIn("FORM_B_II", got)
        self.assertNotIn("FORM_B_IV", got)


if __name__ == "__main__":
    unittest.main()
