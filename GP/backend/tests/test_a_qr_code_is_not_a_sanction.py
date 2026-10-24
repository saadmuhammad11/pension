"""A page is not the sanction order because it has a QR code on it.

24 Oct 2026, PC-2026-000070. Page 8 of that claim is the BACK of the subscriber's smart CNIC:
a CNIC number, a card number, three lines of Urdu and a large QR code. The classifier called
it SANCTION_ORDER_QR at 0.95, which merges as the sanction (pipeline._MERGERS), so the case
recorded its sanction on page 8 and hung the sanctioning officer's signature there. Every
"Signatories and delegation of authority" task the officer opened showed them the back of a
CNIC and asked whether the signature on it was the competent authority's.

Two of the classes describe a page with a QR code and only one of them is the sanction, so
this is an easy mistake and it will be made again. The page's own text settles it, and the
two are not close -- the real sanction is page 3 of the same claim:

    page 3   GOVERNMENT OF THE PUNJAB ... Sanction is hereby accorded to the grant of
             G.P. Fund advance amounting to Rs.850,000/- ... NO.SO(S-II)PF/558/M/2026
    page 8   35202-0000001-1 ... 500000000001 ... 270-00-000001, and Urdu

    python3 -m pytest tests/test_a_qr_code_is_not_a_sanction.py -q
"""
from __future__ import annotations

import pytest

from gpf.reading.artefacts import Artefact
from gpf.reading.sanction_claim import looks_like_a_cnic_back, settle

#: Page 3 of PC-2026-000070, as the OCR model returned it.
SANCTION = """GOVERNMENT OF THE PUNJAB SERVICES & GENERAL ADMINISTRATION DEPARTMENT
SECTION (SERVICES-II)
Dated Lahore, the 17th September, 2026
NO.SO(S-II)PF/558/M/2026.
Sanction is hereby accorded to the grant of G.P. Fund advance amounting to Rs.850,000/-
(Rupees eight lac & fifty thousand only), in favour of MR. A B SAMPLE (BS-20),
an officer of the Government of the Punjab"""

#: Page 8 of the same claim. Almost no Latin letters: the page is Urdu and numbers, and it
#: reads perfectly well -- which is why "was this page read?" cannot be asked of Latin.
CNIC_BACK = """35202-0000001-1
مکان نمبر ۱، محلہ نمونہ
5
500000000001
270-00-000001
گمشدہ کارڈ ملنے پر قریبی لیٹر بکس میں ڈال دیں"""


class TestTheRealSanctionIsLeftAlone:

    @pytest.mark.parametrize("claimed", [Artefact.SANCTION_ORDER.value, Artefact.SANCTION_ORDER_QR.value])
    def test_a_page_that_says_it_is_one(self, claimed) -> None:
        assert settle(claimed, SANCTION) == (claimed, "")

    def test_the_words_it_is_recognised_by(self) -> None:
        for text in ("Sanction is hereby accorded to the grant of G.P. Fund advance",
                     "sanctioned by the competent authority",
                     "NO.SO(S-II)PF/558/M/2026 dated 17.09.2026"):
            art, why = settle(Artefact.SANCTION_ORDER.value, text + " " * 0 + " x" * 12)
            assert art == Artefact.SANCTION_ORDER.value, text[:40]


class TestTheBackOfACnicIsNot:

    def test_it_is_named_for_what_it_is(self) -> None:
        art, why = settle(Artefact.SANCTION_ORDER_QR.value, CNIC_BACK)
        assert art == Artefact.CNIC_SMART_BACK.value
        assert "back of a CNIC" in why

    def test_it_is_recognised_without_any_latin_at_all(self) -> None:
        """The page is Urdu. A reader that asks "are there English words?" to decide whether
        the page came through would call this one unread and leave it as the sanction."""
        assert looks_like_a_cnic_back(CNIC_BACK)
        assert sum(c.isascii() and c.isalpha() for c in CNIC_BACK) < 5

    def test_a_page_of_prose_with_a_cnic_in_it_is_not_a_cnic_back(self) -> None:
        """A sanction names the subscriber and may quote their CNIC."""
        assert not looks_like_a_cnic_back(SANCTION + "\nCNIC 35202-0000001-1")


class TestWhatIsNotTouched:

    @pytest.mark.parametrize("artefact", [Artefact.CNIC_SMART_FRONT.value, Artefact.SAP_PAYSLIP.value,
                                          Artefact.GPF_FORM_10.value, Artefact.UNKNOWN.value])
    def test_only_a_claim_to_be_the_sanction_is_questioned(self, artefact) -> None:
        assert settle(artefact, CNIC_BACK) == (artefact, "")

    def test_a_page_that_did_not_read_keeps_its_classification(self) -> None:
        """No corroboration is not evidence against the reading -- the rule the pension side
        arrived at for the same class of error (extraction.identify, 22 Oct 2026). A scan too
        poor to read must not be demoted for being unreadable."""
        for text in ("", "   ", "\n\n", "%%%"):
            assert settle(Artefact.SANCTION_ORDER.value, text) == (Artefact.SANCTION_ORDER.value, "")

    def test_this_only_ever_takes_a_claim_away(self) -> None:
        """It never promotes a page TO the sanction: a page the classifier did not call one
        has not been looked at for the things a sanction says."""
        art, _ = settle(Artefact.CNIC_SMART_BACK.value, SANCTION)
        assert art == Artefact.CNIC_SMART_BACK.value


class TestAPageThatIsNeither:

    def test_it_goes_to_a_person_rather_than_to_the_sanction(self) -> None:
        art, why = settle(Artefact.SANCTION_ORDER.value,
                          "Office of the Accountant General, Punjab. Acknowledgement of receipt "
                          "of the papers listed below, received in this office on 12.09.2026.")
        assert art == Artefact.UNKNOWN.value
        assert "nothing on the page speaks of a sanction" in why


class TestThePipelineAsksTheQuestion:

    def test_it_is_asked_only_where_the_claim_is_made(self) -> None:
        """One OCR call per page claimed as a sanction, which on a claim is one or two pages,
        and none at all on the rest."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent / "gpf" / "reading" / "pipeline.py").read_text()
        assert "sanction_claim.is_a_sanction_claim(artefact)" in src
        assert "sanction_claim.settle(artefact, self.model.ocr_text(pg.image_ref))" in src

    def test_a_demotion_is_put_to_a_person(self) -> None:
        """The classifier was confident and wrong; the officer is told the page changed hands."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent / "gpf" / "reading" / "pipeline.py").read_text()
        block = src[src.index("is_a_sanction_claim(artefact)"):src.index("# stage 4")]
        assert 'out["needs_human"].append' in block
        assert '"field": "document type"' in block

    def test_and_a_reader_that_throws_leaves_the_reading_alone(self) -> None:
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent / "gpf" / "reading" / "pipeline.py").read_text()
        block = src[src.index("is_a_sanction_claim(artefact)"):src.index("# stage 4")]
        assert "except Exception" in block and "settled, why = artefact, \"\"" in block
