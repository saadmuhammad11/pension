"""QR and barcode payload parsing. Build specification §9.2, §9.3, §17.

The oracle for these tests is the corpus itself. Every ``compare`` row in the fact fixtures
was written by hand on 15-09-2026 from a payload the office had decoded, so a parser that
agrees with those rows is a parser that reproduces what the office read. That is the whole
point of building §9.2 separately from the §9.1 decoder: when the decoder lands, the
comparison rows are DERIVED rather than transcribed, and these tests are what says the
derivation still matches the transcription.

The §17 row this covers is the payload half of "QR decode rate on the corpus". The decode
half needs the images and zxing-cpp and is still phase 5.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gpfund.corpus import CORPUS_ORDER, HERE as CORPUS_DIR
from gpfund.qr import (
    BY_COMPARISON,
    DOCUMENT_NO,
    ESTAMP,
    NADRA_CRMS,
    NADRA_EFRC,
    NADRA_ESUCCESSION,
    ONLINE,
    SANCTION_TEXT,
    SMART_CNIC,
    UNKNOWN,
    format_cnic,
    parse,
    parse_code,
    route_for,
)


def _codes():
    """Every ``qr`` entry in the corpus, as ``(slug, code)``."""
    for slug in CORPUS_ORDER:
        data = json.loads((CORPUS_DIR / f"{slug}.json").read_text())
        for code in data.get("qr") or ():
            yield slug, code


def _compare_row(code, field):
    for row in code.get("compare") or ():
        if row.get("field") == field:
            return row
    return None


class SmartCnicBacks(unittest.TestCase):
    """§9.2 row 1: 26 digits -- a 12-digit card number, the 13-digit CNIC, one trailing digit."""

    def test_every_smart_cnic_in_the_corpus_parses_to_the_recorded_values(self):
        seen = 0
        for slug, code in _codes():
            if not code.get("decoded") or not isinstance(code.get("payload"), str):
                continue
            parsed = parse_code(code)
            if parsed.kind != SMART_CNIC:
                continue
            seen += 1
            with self.subTest(case=slug, code=code.get("id")):
                row = _compare_row(code, "CNIC number")
                self.assertIsNotNone(row, "a smart CNIC back always compares the CNIC")
                self.assertEqual(parsed.fields["cnic"], row["qrVal"])
                card = _compare_row(code, "card number")
                if card:
                    self.assertEqual(parsed.fields["card_number"], card["qrVal"])
        self.assertEqual(seen, 3, "the corpus has three decoded smart CNIC backs")

    def test_the_three_parts_partition_the_payload(self):
        parsed = parse("50459132685600001000010381")
        self.assertEqual(parsed.kind, SMART_CNIC)
        self.assertEqual(parsed.fields["card_number"], "504591326856")
        self.assertEqual(parsed.fields["cnic_digits"], "0000100001038")
        self.assertEqual(parsed.fields["trailing"], "1")
        self.assertEqual(
            parsed.fields["card_number"] + parsed.fields["cnic_digits"]
            + parsed.fields["trailing"],
            "50459132685600001000010381")

    def test_nothing_is_concluded_from_the_trailing_digit(self):
        """§9.2 calls it "of unknown meaning"; §14 rule 10 forbids accepting it as a check."""
        self.assertNotIn("check_digit", parse("50459132685600001000010381").fields)

    def test_a_payload_of_the_wrong_length_is_not_read_as_a_card(self):
        for bad in ("5045913268560000100001038", "504591326856000010000103812", "abc"):
            with self.subTest(payload=bad):
                self.assertNotEqual(parse(bad).kind, SMART_CNIC)

    def test_a_smart_cnic_is_verified_by_comparison_and_needs_no_portal(self):
        """§9.3: codes that carry their own data need no portal."""
        self.assertEqual(route_for(parse("50459132685600001000010381")), BY_COMPARISON)


class Portals(unittest.TestCase):
    """§9.2 rows 3 to 5, and the §9.3 routing."""

    def test_the_estamp_stamp_id_is_the_id_parameter(self):
        code = next(c for _, c in _codes() if c.get("id") == "estamp")
        parsed = parse_code(code)
        self.assertEqual(parsed.kind, ESTAMP)
        self.assertEqual(parsed.fields["stamp_id"],
                         _compare_row(code, "stamp id")["qrVal"])

    def test_a_label_in_front_of_the_url_is_stripped(self):
        """The corpus e-stamp payload reads "Url: https://..." as the decoder returned it."""
        parsed = parse("Url: https://es.punjab-zameen.gov.pk/eStampCitizenPortal/"
                       "GeneratePDF/Stamp_Receipt?id=PB-LHR-50661BB59AF39C23")
        self.assertEqual(parsed.fields["stamp_id"], "PB-LHR-50661BB59AF39C23")
        self.assertTrue(parsed.raw.startswith("Url:"), "the raw payload is kept intact")

    def test_the_succession_decline_document_number_matches_the_printed_number(self):
        code = next(c for _, c in _codes() if c.get("id") == "decline-qr")
        parsed = parse_code(code)
        self.assertEqual(parsed.kind, NADRA_ESUCCESSION)
        row = _compare_row(code, "document number")
        self.assertEqual(parsed.fields["document_no"], row["qrVal"])
        self.assertEqual(row["docVal"], row["qrVal"], "and it agrees with the certificate")

    def test_the_efrc_application_id_is_not_the_certificate_document_number(self):
        """The one trap in §9.2: the e-FRC QR carries an APPLICATION id.

        The document number printed on that certificate, EA80580288, comes off its Code 39
        barcode, not off this QR code. A parser that reported the QR's 505295769494 as the
        document number would raise a mismatch against a certificate that is perfectly sound.
        """
        code = next(c for _, c in _codes() if c.get("id") == "frc-qr")
        parsed = parse_code(code)
        self.assertEqual(parsed.kind, NADRA_EFRC)
        self.assertEqual(parsed.fields["application_id"], "505295769494")
        self.assertNotIn("document_no", parsed.fields)
        printed = _compare_row(code, "Code 39 document no.")["qrVal"]
        self.assertNotEqual(parsed.fields["application_id"], printed)

    def test_the_crms_tracking_id_keeps_its_base64_padding(self):
        """Splitting on every "=" instead of the first would truncate the id."""
        code = next(c for _, c in _codes() if c.get("id") == "death-cert-qr")
        parsed = parse_code(code)
        self.assertEqual(parsed.kind, NADRA_CRMS)
        self.assertEqual(parsed.fields["tracking_id"], "OxyaJaOyf6Rl2ZxYviapTA==")

    def test_the_crms_code_carries_nothing_to_compare(self):
        """Which is why its fixture ``compare`` list is empty: the record must come from NADRA."""
        code = next(c for _, c in _codes() if c.get("id") == "death-cert-qr")
        self.assertEqual(list(code.get("compare") or ()), [])

    def test_every_portal_payload_is_routed_online(self):
        for slug, code in _codes():
            if not code.get("decoded") or not isinstance(code.get("payload"), str):
                continue
            if "://" not in code["payload"]:
                continue
            with self.subTest(case=slug, code=code.get("id")):
                parsed = parse_code(code)
                self.assertEqual(route_for(parsed), ONLINE)
                self.assertIsNotNone(parsed.host)

    def test_the_host_matches_what_the_fixture_recorded(self):
        for slug, code in _codes():
            if not code.get("host"):
                continue
            with self.subTest(case=slug, code=code.get("id")):
                self.assertEqual(parse_code(code).host, code["host"])


class SanctionText(unittest.TestCase):
    """§9.2 row 2: the QR-coded School Education sanction, checked field by field."""

    def setUp(self):
        self.code = next(c for _, c in _codes() if c.get("id") == "sanction")
        self.parsed = parse_code(self.code)

    def test_it_is_recognised_as_a_sanction(self):
        self.assertEqual(self.parsed.kind, SANCTION_TEXT)

    def test_the_name_post_and_cnic_match_the_recorded_values(self):
        for field, key in (("name", "name"), ("CNIC", "cnic"), ("post", "post")):
            with self.subTest(field=field):
                self.assertEqual(self.parsed.fields[key],
                                 _compare_row(self.code, field)["qrVal"])

    def test_the_school_is_taken_as_the_code_wrote_it(self):
        """The fixture row prettifies to "GGHS R.A. Bazar, Lahore"; the code says otherwise.

        §9.2 checks the field against the printed sanction, and whether a difference in case
        or a trailing district matters is the rule layer's business. This module collapses
        runs of whitespace -- the payload really does read "GGHS  R.A. BAZAR" -- and changes
        nothing else.
        """
        self.assertEqual(self.parsed.fields["school"], "GGHS R.A. BAZAR")
        recorded = _compare_row(self.code, "school")["qrVal"]
        self.assertTrue(recorded.casefold().startswith(
            self.parsed.fields["school"].casefold()))

    def test_every_field_of_the_9_2_table_is_extracted(self):
        """"name, CNIC, post and scale, school, tehsil, district" -- all six, not five.

        Tehsil is named because an earlier single-pattern version of this parser silently
        dropped it: the school group consumed the word "Tehsil" that the next group needed.
        """
        for key in ("name", "cnic", "post", "school", "tehsil", "district"):
            with self.subTest(field=key):
                self.assertIn(key, self.parsed.fields)
        self.assertEqual(self.parsed.fields["tehsil"], "CANTT")
        self.assertEqual(self.parsed.fields["district"], "LAHORE")

    def test_it_parses_a_sanction_it_has_not_seen(self):
        """The corpus has one of these, so the patterns are checked against a second shape."""
        parsed = parse("Ali Raza CNIC# 3520112345671 posted as an SST (BS-16), "
                       "posted at GBHS Model Town, Tehsil MODEL TOWN, District LAHORE")
        self.assertEqual(parsed.kind, SANCTION_TEXT)
        self.assertEqual(parsed.fields["name"], "Ali Raza")
        self.assertEqual(parsed.fields["cnic"], "3520112345671")
        self.assertEqual(parsed.fields["post"], "SST (BS-16)")
        self.assertEqual(parsed.fields["school"], "GBHS Model Town")
        self.assertEqual(parsed.fields["tehsil"], "MODEL TOWN")
        self.assertEqual(parsed.fields["district"], "LAHORE")

    def test_a_sanction_carries_its_own_data_so_it_needs_no_portal(self):
        self.assertEqual(route_for(self.parsed), BY_COMPARISON)
        self.assertIsNone(self.parsed.host)


class UndecodedAndUnknown(unittest.TestCase):
    """§9.2: an unreadable code is an OBSERVATION, curable by a clearer copy -- never a crash."""

    def test_a_code_that_did_not_decode_parses_to_unknown_with_the_reason(self):
        code = next(c for _, c in _codes() if c.get("id") == "old-cnic-barcode")
        parsed = parse_code(code)
        self.assertEqual(parsed.kind, UNKNOWN)
        self.assertIn("faded photocopy", parsed.note)

    def test_every_undecoded_code_in_the_corpus_is_unknown_and_none_raises(self):
        seen = 0
        for slug, code in _codes():
            if code.get("decoded"):
                continue
            seen += 1
            with self.subTest(case=slug, code=code.get("id")):
                self.assertEqual(parse_code(code).kind, UNKNOWN)
        self.assertTrue(seen, "the corpus contains codes that did not decode")

    def test_parse_never_raises_and_never_returns_none(self):
        for payload in (None, "", "   ", "not a code", "?", "://", "https://",
                        "https://es.punjab-zameen.gov.pk/", "a" * 500, "\x00\x01"):
            with self.subTest(payload=payload):
                parsed = parse(payload)
                self.assertIsNotNone(parsed)
                self.assertIsInstance(parsed.kind, str)

    def test_an_unrecognised_portal_is_still_routed_online(self):
        parsed = parse("https://portal.example.gov.pk/verify?id=123")
        self.assertEqual(route_for(parsed), ONLINE)
        self.assertEqual(parsed.host, "portal.example.gov.pk")


class DocumentNumbers(unittest.TestCase):
    """§9.2 last row: Code 39 carries a document or tracking number and nothing else."""

    def test_a_bare_number_is_a_document_number(self):
        parsed = parse("EA80580288", symbology="Code 39")
        self.assertEqual(parsed.kind, DOCUMENT_NO)
        self.assertEqual(parsed.fields["document_no"], "EA80580288")

    def test_free_text_is_not_mistaken_for_a_document_number(self):
        for text in ("attested true copy", "see overleaf", "x"):
            with self.subTest(text=text):
                self.assertNotEqual(parse(text).kind, DOCUMENT_NO)


class CnicFormatting(unittest.TestCase):

    def test_thirteen_digits_become_the_card_format(self):
        self.assertEqual(format_cnic("0000100001038"), "00001-0000103-8")

    def test_an_already_formatted_cnic_survives_a_round_trip(self):
        self.assertEqual(format_cnic("00001-0000103-8"), "00001-0000103-8")

    def test_anything_that_is_not_a_cnic_is_returned_unchanged(self):
        for value in ("", "123", "not a cnic", "000010000103812"):
            with self.subTest(value=value):
                self.assertEqual(format_cnic(value), value)


class Coverage(unittest.TestCase):
    """Every decoded payload in the corpus is a shape this module knows. §17."""

    def test_no_decoded_corpus_payload_falls_through_to_unknown(self):
        checked = 0
        for slug, code in _codes():
            if not code.get("decoded") or not isinstance(code.get("payload"), str):
                continue
            checked += 1
            with self.subTest(case=slug, code=code.get("id")):
                self.assertNotEqual(
                    parse_code(code).kind, UNKNOWN,
                    f"{code.get('payload')!r} is not a shape §9.2 describes")
        self.assertEqual(checked, 8, "eight decoded payloads across the corpus")

    def test_parsing_is_deterministic(self):
        """§17 re-evaluation determinism, for this stage too."""
        for _, code in _codes():
            first, second = parse_code(code), parse_code(code)
            self.assertEqual((first.kind, dict(first.fields), first.route),
                             (second.kind, dict(second.fields), second.route))


if __name__ == "__main__":
    unittest.main()
