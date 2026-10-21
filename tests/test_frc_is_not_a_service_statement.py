"""The NADRA family register is described well enough to be told from a service record.

    python3 -m unittest tests.test_frc_is_not_a_service_statement -v

Page 18 of run b3b0e3f35d7c is an ordinary NADRA Family Registration Certificate: entirely in
Urdu, a CRC number and barcode at the top, a table of the family one member per row, and a
school's stamp attesting the copy. It was classified SERVICE_STATEMENT at confidence 0.95, with
the attestation stamp quoted as the letterhead -- so a family register went into a real case as
a service record, where the FRC family checks look for it and the service-record lines do not
want it.

The vocabulary entry said only "NADRA 'Family Registration Certificate' listing family members",
which describes an English FRC that departments do not file. Nothing else could correct it: the
page defeats OCR (the reader loops and looks_degenerate rejects the text), and re-identifying it
turned 90 or 270 degrees does not help -- it was read as a service statement at every rotation.
The description is the only reader there is, which is why this test guards its content.

Measured after the rewrite, two trials each on the filed page: 0 degrees (how the page is
stored) NADRA_FRC twice, 270 degrees NADRA_FRC twice, and Annex-A, the real service statement
and the CNIC card on the same bundle all unchanged.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extraction.schemas import DOCUMENT_TYPES, DOCUMENT_TYPE_GLOSS  # noqa: E402


def _frc_description() -> str:
    """The words the model is given for NADRA_FRC (DOCUMENT_TYPE_GLOSS, identify.py:75)."""
    return DOCUMENT_TYPE_GLOSS["NADRA_FRC"]


class TheFrcDescriptionDiscriminates(unittest.TestCase):

    def test_it_says_the_page_is_usually_in_urdu(self) -> None:
        """The filed copy has no English heading; a description that assumes one is useless."""
        self.assertIn("URDU", _frc_description().upper())

    def test_it_names_the_crc_number_and_barcode(self) -> None:
        d = _frc_description().upper()
        self.assertIn("CRC", d)
        self.assertIn("BARCODE", d)

    def test_it_says_several_cnics_are_the_strongest_sign(self) -> None:
        self.assertIn("CNIC", _frc_description().upper())

    def test_it_warns_that_an_attestation_stamp_is_not_a_letterhead(self) -> None:
        """The exact error made on the real page: the school's stamp read as the issuing office."""
        d = _frc_description().lower()
        self.assertIn("attest", d)
        self.assertIn("letterhead", d)
        self.assertIn("service statement", d)

    def test_the_type_is_still_in_the_closed_vocabulary(self) -> None:
        self.assertIn("NADRA_FRC", DOCUMENT_TYPES)


if __name__ == "__main__":
    unittest.main()
