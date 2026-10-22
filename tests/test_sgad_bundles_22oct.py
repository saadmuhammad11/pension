"""The S&GAD bundles of 22 Oct 2026: PC-2026-000033 to -000041.

Nine fresh cases from one department came back with the Pension Sanctioning Authority form
reported MISSING on eight of them and the photographs MISSING on six, and every one of those
papers was in the bundle. Three separate faults, none of them about S&GAD using different
forms -- which was the first hypothesis, and wrong:

* The proforma's title arrived from OCR as "QUALIFYING SERV ICE FOR PENSION", one word split
  by a space, and ``PROFORMA_TITLE`` could not span it. The model had already recognised the
  page; the denial threw its answer away (PC-33 p.4, PC-38 p.4, PC-39 p.10).

* PaddleOCR reads only part of some S&GAD pages -- 859 characters of PC-37 p.3, which carries
  well over two thousand -- stopping after the pay table, never reaching the "FORM B-I" title
  at the top or the sanction clauses at the foot. ``looks_degenerate`` does not catch an
  incomplete read, so ``_verify_form_claim`` refused a correct classification for want of
  corroboration that was printed on the page. ``_forms_in_bands`` looks again before denying.

* A photograph pasted onto the descriptive roll was reported by the model in
  ``other_documents_on_page`` and then dropped: nothing in the tree ever turned that field
  into a document.

No figures from a real servant's papers appear here.

    python3 -m unittest tests.test_sgad_bundles_22oct -v
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
    ALSO_ON_PAGE_TRUSTED, PROFORMA_TITLE, titles_on_page,
)

#: The title as PaddleOCR actually returned it from the S&GAD proforma.
SPLIT = "proposed performa for qualifying serv ice for pension (for use in administrative"
#: And the other way the same word can break.
SPLIT_2 = "performa for qualifying ser vice for pension"
#: Form B-I's clause 3 speaks of qualifying service for pension and is not this form.
FORM_B_I_CLAUSE = ("his date of birth is 01.01.1966. total length of qualifying service for "
                   "pension is 33 years 06 months 20 days.")


class TheProformaTitleSurvivesOcrSplittingTheWord(unittest.TestCase):

    def test_the_split_the_sgad_bundles_produced(self) -> None:
        self.assertIsNotNone(re.search(PROFORMA_TITLE, SPLIT))
        self.assertIn("QUALIFYING_SERVICE_PROFORMA", titles_on_page(SPLIT))

    def test_the_other_place_the_word_can_break(self) -> None:
        self.assertIsNotNone(re.search(PROFORMA_TITLE, SPLIT_2))

    def test_the_unsplit_spellings_still_match(self) -> None:
        for s in ("performa for qualifying service for pension",
                  "proforma for qualifying service for pension",
                  "proposed performa for qualifying sevice for pension"):
            with self.subTest(title=s):
                self.assertIsNotNone(re.search(PROFORMA_TITLE, s))

    def test_a_form_that_merely_mentions_qualifying_service_is_not_the_proforma(self) -> None:
        """The words either side -- "qualifying" before, "for pension" after -- are the guard."""
        self.assertIsNone(re.search(PROFORMA_TITLE, FORM_B_I_CLAUSE))
        self.assertNotIn("QUALIFYING_SERVICE_PROFORMA", titles_on_page(FORM_B_I_CLAUSE))


class OnlyAPhotographIsTakenOnTheModelsWord(unittest.TestCase):

    def test_exactly_one_type_is_trusted_from_other_documents_on_page(self) -> None:
        """Everything else this module adds is corroborated by a second reader. OCR reads
        characters and a photograph has none, so for that one type the model's word is all
        there is. Widening this set means adding something that COULD have been corroborated
        and was not."""
        self.assertEqual(ALSO_ON_PAGE_TRUSTED, frozenset({"PHOTOGRAPHS"}))


class TheDepartmentsOwnSanctionOrderAnswersAgO4(unittest.TestCase):
    """Not every department sanctions on a prescribed form. S&GAD issues a numbered office
    order on its own letterhead, signed by an Additional or Deputy Secretary described as the
    Pension Sanctioning Authority, and AG-04 read MISSING on eight of nine bundles because of
    it (office decision, 22 Oct 2026)."""

    #: The operative clause, as OCR returned it from PC-2026-000034 p.3.
    GRANTS = ("(8) administrative and financial sanction for grant of pension with commutation "
              "@ (25%), as determined by the accountant general, punjab, is hereby accorded in "
              "favour of mr. a b sample")
    #: The last page of the same document: signature block, no heading of its own.
    SIGNS = "mudasir ahm additional secretary s&gad/pension sanctioning note:- the sanction accorded"
    #: A PPO refers to the sanction in words of its own, and is not one.
    PPO = "pension payment order ... the sanction accorded, as above, is subject to change"

    def test_the_clause_that_grants_the_pension_identifies_it(self) -> None:
        from extraction.identify import titles_on_page
        self.assertIn("PENSION_SANCTION_ORDER", titles_on_page(self.GRANTS))

    def test_so_does_a_signature_block_naming_the_sanctioning_authority(self) -> None:
        """The document runs to two pages and the second carries no heading."""
        from extraction.identify import titles_on_page
        self.assertIn("PENSION_SANCTION_ORDER", titles_on_page(self.SIGNS))

    def test_a_ppo_referring_to_the_sanction_is_not_the_sanction(self) -> None:
        """"The sanction accorded, as above" was in this pattern until it matched a PPO."""
        from extraction.identify import titles_on_page
        self.assertNotIn("PENSION_SANCTION_ORDER", titles_on_page(self.PPO))

    def test_it_satisfies_ag_04_on_every_column(self) -> None:
        from rules import CaseRecord
        from rules.caserecord import Document
        from rules.checklist import ALL_VARIANTS, PRESENT, requirements_for, run_checklist
        docs = (Document(type="PENSION_SANCTION_ORDER", pages=(3,)),)
        for variant in ALL_VARIANTS:
            if "AG-04" not in {r.id for r in requirements_for(variant)}:
                continue
            with self.subTest(variant=variant):
                cl = run_checklist(CaseRecord(case_ref="t", case_type="", case_variant=variant,
                                              documents=docs), variant=variant)
                self.assertEqual(cl.item("AG-04").status, PRESENT)

    def test_the_prescribed_form_is_still_narrowed_per_column(self) -> None:
        """What this adds is the sanction that prints NO form number. A bundle carrying the
        wrong prescribed form is still wrong: a Form D-II does not answer a self-pension."""
        from rules import CaseRecord
        from rules.caserecord import Document
        from rules.checklist import MISSING, run_checklist
        cl = run_checklist(CaseRecord(case_ref="t", case_type="", case_variant="FRESH_SELF",
                                      documents=(Document(type="FORM_D_II", pages=(3,)),)),
                           variant="FRESH_SELF")
        self.assertEqual(cl.item("AG-04").status, MISSING)

    def test_nothing_filed_is_still_missing(self) -> None:
        from rules import CaseRecord
        from rules.checklist import MISSING, run_checklist
        cl = run_checklist(CaseRecord(case_ref="t", case_type="", case_variant="FRESH_SELF"),
                           variant="FRESH_SELF")
        self.assertEqual(cl.item("AG-04").status, MISSING)


class ABandIsReadWhenTheWholePageSaidNothing(unittest.TestCase):

    def test_the_bands_cover_the_page_and_overlap(self) -> None:
        """A heading on a band boundary must be whole in one of them."""
        from extraction.identify import _BANDS
        self.assertAlmostEqual(_BANDS[0][0], 0.0)
        self.assertAlmostEqual(_BANDS[-1][1], 1.0)
        for (_, prev_end), (next_start, _) in zip(_BANDS, _BANDS[1:]):
            self.assertLess(next_start, prev_end, "consecutive bands must overlap")

    def test_an_unreadable_image_is_silence_not_a_denial(self) -> None:
        """No second look is not evidence against the first reading -- the same rule
        _deny_pay_claim_on_a_card and _verify_proforma_claim already follow."""
        from extraction.identify import _forms_in_bands
        self.assertEqual(_forms_in_bands("/nonexistent/page.png", 1), ((), ()))


if __name__ == "__main__":
    unittest.main()
