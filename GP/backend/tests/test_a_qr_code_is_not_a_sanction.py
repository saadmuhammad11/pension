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
    page 8   00001-0000001-1 ... 500000000001 ... 270-00-000001, and Urdu

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
CNIC_BACK = """00001-0000001-1
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
        assert not looks_like_a_cnic_back(SANCTION + "\nCNIC 00001-0000001-1")


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
    """It used to become UNKNOWN, and that was wrong (26 Oct 2026).

    PC-2026-000063 page 4 is an S&GAD ORDER reading "Sanction is hereby accorded to the grant
    of G.P Fund advance amounting to Rs.120,000/-", under a diary stamp and a page of red pen.
    The classifier called it SANCTION_ORDER at 0.98 and the OCR of it came back without the
    words, so this demoted it to UNKNOWN -- which reaches no merger, so the sanction left the
    case altogether and the checklist reported none on file. Four re-readings repeated it.

    Absence of corroboration is not evidence. The classifier reads the IMAGE -- letterhead,
    layout, signature block -- and OCR reads characters and can fail. A demotion needs
    POSITIVE evidence that the page is something else; the CNIC back above is that, and is
    what this guard was built for. Anything else keeps the reading and is put to a person.
    """

    NEITHER = ("Office of the Accountant General, Punjab. Acknowledgement of receipt "
               "of the papers listed below, received in this office on 12.09.2026.")

    def test_the_reading_is_kept(self) -> None:
        art, _ = settle(Artefact.SANCTION_ORDER.value, self.NEITHER)
        assert art == Artefact.SANCTION_ORDER.value

    def test_but_a_person_is_asked_to_confirm_the_page(self) -> None:
        _, why = settle(Artefact.SANCTION_ORDER.value, self.NEITHER)
        assert "nothing in the page's text corroborates that" in why
        assert "Confirm the page" in why

    def test_the_cnic_back_is_still_taken_away(self) -> None:
        """The failure this guard exists for is positive evidence and still demotes."""
        art, why = settle(Artefact.SANCTION_ORDER_QR.value,
                          "00001-0000001-1 500000000001 270-00-000001 Registrar General")
        assert art == Artefact.CNIC_SMART_BACK.value
        assert "it is the back of a CNIC" in why


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


# ── and the same question asked the other way round ───────────────────────────
class TestAPageTheClassifierWouldNotName:
    """26 Oct 2026, PC-2026-000063. Page 4 is an S&GAD ORDER -- "Sanction is hereby accorded
    to the grant of G.P Fund advance amounting to Rs.120,000/- ... under the Rule
    1.14(1)(a)(iv)" -- over a diary stamp, a hand-written token and a page of red pen. The
    classifier returned UNKNOWN at 0.98 confidence and the claim reported no sanction on file.

    UNKNOWN reaches no merger, so the page left no mark anywhere: the checklist said the
    sanction was absent and nothing on the case could say what page 4 had been called. The
    demotion above asks a page claiming to be the sanction to show that it is one; this asks
    a page nobody claimed whether it is one anyway. Same evidence, same answer.
    """

    ORDER = ("GOVERNMENT OF THE PUNJAB SERVICES & GENERAL ADMINISTRATION DEPARTMENT SECTION (P-III) "
             "Dated Lahore, the 5th October, 2026. ORDER No.SOP-III(S&GAD)2-223/2007 (302). "
             "Sanction is hereby accorded to the grant of G.P Fund advance amounting to Rs.120,000/- "
             "in favour of a Naib Qasid on refundable basis, for repair / renovation of house, under "
             "the Rule 1.14(1)(a)(iv) of the Punjab General Provident Fund Rules, 1978. "
             "DEPUTY SECRETARY (PERSONNEL) SECTION OFFICER (P-III)")

    def test_the_order_itself_is_recognised(self) -> None:
        from gpf.reading.sanction_claim import reads_as_a_sanction
        assert reads_as_a_sanction(self.ORDER)

    def test_a_page_that_only_mentions_a_sanction_is_not_promoted(self) -> None:
        """A noting and a covering letter both talk about the sanction. Neither is one, and
        promoting either would hang the sanctioning officer's signature on the wrong page --
        which is the mistake this whole file exists to stop."""
        from gpf.reading.sanction_claim import reads_as_a_sanction
        noting = ("Please put up the file. The sanction referred to above may be seen. G.P Fund case "
                  "of the official concerned is submitted for the orders of the competent authority "
                  "please. Noted and returned herewith for necessary action.")
        letter = ("Subject: GP FUND ADVANCE CASE. Enclosed please find the G.P Fund case complete in "
                  "all respects along with the sanction order for favour of necessary action at your "
                  "end. Encl: as above. Section Officer.")
        assert not reads_as_a_sanction(noting)
        assert not reads_as_a_sanction(letter)

    def test_a_page_that_did_not_read_is_left_alone(self) -> None:
        from gpf.reading.sanction_claim import reads_as_a_sanction
        assert not reads_as_a_sanction("")
        assert not reads_as_a_sanction("   ")
        assert not reads_as_a_sanction("00001-0000001-1 500000000001 270-00-000001")

    def test_the_formula_alone_is_not_enough_without_the_fund(self) -> None:
        """Departments sanction many things; only this fund's money is this module's."""
        from gpf.reading.sanction_claim import reads_as_a_sanction
        assert not reads_as_a_sanction(
            "ORDER. Sanction is hereby accorded to the purchase of office furniture amounting to "
            "Rs.120,000/- under the delegation of financial powers, in favour of the Section Officer "
            "(Admn), Government of the Punjab, for the current financial year, chargeable to the "
            "budget head concerned. DEPUTY SECRETARY (ADMN)")

    def test_the_promotion_is_put_to_a_person(self) -> None:
        """It is a reading the classifier did not make, so the officer is told it was made."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent / "gpf" / "reading" / "pipeline.py").read_text()
        block = src[src.index("elif artefact == Artefact.UNKNOWN.value:"):src.index("# stage 4")]
        assert 'out["needs_human"].append' in block
        assert "confirm the page" in block.lower()
