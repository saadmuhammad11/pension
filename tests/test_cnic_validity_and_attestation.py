"""The claimant's CNIC must be in force, and required photocopies must be attested.

SOP §5.2 AG-02 ("Copies of the CNIC ... attested by the DDO"; FD checklist "valid CNIC"),
SOP §5.1(1) (every photocopy attested). The card's own printed 'Date of Expiry' is read at
extraction (``cnic_cards``) and put on the timeline under whose card it is; the checklist marks
AG-02 DEFECTIVE and the battery raises ``DOC-EXPIRED``; attestation not seen raises
``ATTEST-MISSING`` at MEDIUM for the officer to verify.

Standard library only; no GPU and no network.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _record(expiries: dict[int, date] | None = None, submitted: date | None = date(2026, 7, 6),
            processed: date | None = date(2026, 9, 17), attested: dict[int, bool | None] | None = None,
            variant: str = "WIDOW"):
    from rules import CaseRecord, Document
    from rules.caserecord import Source, TimelineEvent
    expiries = expiries or {}
    attested = attested or {}
    timeline = [TimelineEvent("CNIC_CLAIMANT_EXPIRES", d, Source(p, "CNIC_CLAIMANT"))
                for p, d in expiries.items()]
    docs = [Document("CNIC_CLAIMANT", (p,), attested=attested.get(p)) for p in (expiries or {4: None})]
    docs.append(Document("NADRA_FRC", (6,), attested=attested.get(6)))
    docs.append(Document("FORWARDING_LETTER", (1,), attested=attested.get(1)))
    return CaseRecord(case_ref="T-CNIC", case_type="FAMILY_PENSION_DEATH_AFTER_RETIREMENT",
                      documents=tuple(docs), timeline=tuple(timeline), submitted_date=submitted,
                      processed_on=processed, case_variant=variant)


def _pack():
    from rules.loader import select_pack
    return select_pack(effective_date=date(2026, 2, 18))


class ClaimantCnicValidity(unittest.TestCase):
    def test_a_card_in_force_at_submission_and_processing_raises_nothing(self):
        from rules.flags import check_cnic_expiry
        self.assertEqual(check_cnic_expiry(_record({4: date(2031, 1, 1)}), _pack()), [])

    def test_a_card_expired_before_submission_is_high_and_defective(self):
        from rules.checklist import DEFECTIVE, run_checklist
        from rules.flags import DOC_EXPIRED, HIGH, check_cnic_expiry
        rec = _record({4: date(2026, 5, 10)})            # forwarded 2026-07-06
        flags = check_cnic_expiry(rec, _pack())
        self.assertEqual(len(flags), 1)
        self.assertEqual((flags[0].severity, flags[0].flag_class, flags[0].owner),
                         (HIGH, DOC_EXPIRED, "DEPARTMENT"))
        self.assertTrue(flags[0].blocks_ppo)
        self.assertIn("p.4", flags[0].title)
        self.assertIn("2026-05-10", flags[0].title)
        item = next(i for i in run_checklist(rec, variant="WIDOW").items if i.id == "AG-02")
        self.assertEqual(item.status, DEFECTIVE)
        self.assertIn("valid CNIC is required", item.reason)

    def test_the_expiry_day_itself_is_still_valid(self):
        from rules.flags import check_cnic_expiry
        # Expires on the day it is forwarded and processed: in force on both, nothing raised.
        self.assertEqual(check_cnic_expiry(
            _record({4: date(2026, 7, 6)}, processed=date(2026, 7, 6)), _pack()), [])

    def test_a_card_that_lapsed_after_submission_is_medium_for_the_office_not_the_department(self):
        from rules.checklist import PRESENT, run_checklist
        from rules.flags import DOC_EXPIRED, MEDIUM, check_cnic_expiry
        rec = _record({4: date(2026, 8, 1)})             # valid on 2026-07-06, lapsed by 2026-09-17
        flags = check_cnic_expiry(rec, _pack())
        self.assertEqual(len(flags), 1)
        self.assertEqual((flags[0].severity, flags[0].flag_class, flags[0].owner),
                         (MEDIUM, DOC_EXPIRED, "AG_OFFICE"))
        self.assertFalse(flags[0].blocks_ppo)
        self.assertIn("2026-09-17", flags[0].finding)
        item = next(i for i in run_checklist(rec, variant="WIDOW").items if i.id == "AG-02")
        self.assertEqual(item.status, PRESENT)

    def test_no_submission_date_still_reports_a_lapse_against_the_processing_date(self):
        from rules.flags import MEDIUM, check_cnic_expiry
        flags = check_cnic_expiry(_record({4: date(2020, 1, 1)}, submitted=None), _pack())
        self.assertEqual([f.severity for f in flags], [MEDIUM])

    def test_nothing_measurable_raises_nothing(self):
        from rules.flags import check_cnic_expiry
        self.assertEqual(check_cnic_expiry(_record({4: date(2020, 1, 1)}, submitted=None,
                                                   processed=None), _pack()), [])

    def test_lifetime_and_unparsed_cards_never_reach_the_timeline(self):
        """The report skips LIFETIME and unparseable expiries; the rules see no event."""
        from rules.flags import check_cnic_expiry
        self.assertEqual(check_cnic_expiry(_record({}), _pack()), [])


class CnicCardsFromTheExtraction(unittest.TestCase):
    def test_only_cards_with_a_date_are_kept_and_fabricated_numbers_are_dropped(self):
        from pipeline.extract import cnic_cards_on
        holders = [
            {"number": "00001-0000108-3", "person": "Waqar Abdul Basit", "role": "holder",
             "date_of_issue": "2022-09-14", "date_of_expiry": "LIFETIME"},
            {"number": "00001-0000108-3", "person": "Mian Muhammad Abdul Basit", "role": "father"},
            {"number": "35203-0000000-0", "person": "x", "role": "holder", "date_of_expiry": "2030-01-01"},
        ]
        cards = cnic_cards_on(holders, 34, "CNIC")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["number"], "0000100001083")
        self.assertEqual(cards[0]["date_of_expiry"], "LIFETIME")
        self.assertEqual(cards[0]["page"], 34)


class CnicDatesFromOcr(unittest.TestCase):
    """The printed dates are read from the OCR transcript, deterministically."""

    def test_the_golden_card_is_lifetime(self):
        from pipeline.extract import cnic_dates_from_text
        text = ("Identity Number | 00001-0000108-3 | Date of Issue | 14.09.2022 | Date of Birth | "
                "17.02.1962 | Date of Expiry | Lifetime | Holder's Signature | Date of Expiry | Lifetime")
        read = cnic_dates_from_text(text)
        self.assertEqual(read["date_of_expiry"], "LIFETIME")
        self.assertEqual(read["date_of_issue"], "2022-09-14")
        self.assertEqual(read["number"], "0000100001083")

    def test_a_dated_expiry_in_dd_mm_yyyy(self):
        from pipeline.extract import cnic_dates_from_text
        read = cnic_dates_from_text("Date of Expiry 30.01.2029 | Date of Issue 30.01.2019 | Date of Expiry 30.01.2029")
        self.assertEqual(read["date_of_expiry"], "2029-01-30")
        self.assertEqual(read["date_of_issue"], "2019-01-30")

    def test_two_cards_with_different_expiries_yield_nothing(self):
        from pipeline.extract import cnic_dates_from_text
        read = cnic_dates_from_text("Date of Expiry 30.01.2029 | Date of Expiry 14.09.2027")
        self.assertIsNone(read["date_of_expiry"])
        self.assertEqual(read["expiry_readings"], ["2027-09-14", "2029-01-30"])

    def test_a_blank_scan_yields_nothing_but_the_number(self):
        from pipeline.extract import cnic_dates_from_text
        read = cnic_dates_from_text("2 | 2 | 00001-0000112-2")
        self.assertIsNone(read["date_of_expiry"])
        self.assertEqual(read["number"], "0000100001122")

    def test_an_expiry_before_the_scheme_or_before_issue_is_a_misread(self):
        from pipeline.extract import cnic_dates_from_text
        # The Widow Daughter bundle: OCR paired the expiry label with the 1966 date of birth.
        self.assertIsNone(cnic_dates_from_text("Date of Birth | Date of Expiry 01.01.1966")["date_of_expiry"])
        self.assertIsNone(cnic_dates_from_text(
            "Date of Issue 30.01.2019 | Date of Expiry 30.01.2009")["date_of_expiry"])
        self.assertEqual(cnic_dates_from_text(
            "Date of Issue 30.01.2019 | Date of Expiry 30.01.2029")["date_of_expiry"], "2029-01-30")

    def test_a_fabricated_number_is_not_kept(self):
        from pipeline.extract import cnic_dates_from_text
        self.assertIsNone(cnic_dates_from_text("35203-0000000-0 Date of Expiry Lifetime")["number"])


class Attestation(unittest.TestCase):
    def test_unattested_required_copies_raise_one_medium_flag_naming_the_pages(self):
        from rules.flags import ATTEST_MISSING, MEDIUM, check_attestation
        rec = _record({4: date(2031, 1, 1)}, attested={4: False, 6: False, 1: False})
        flags = check_attestation(rec, _pack())
        self.assertEqual(len(flags), 1)
        self.assertEqual((flags[0].severity, flags[0].flag_class), (MEDIUM, ATTEST_MISSING))
        self.assertFalse(flags[0].blocks_ppo)
        # The pages are named, in the words an officer uses rather than our schema
        # constants: the title counts them, the finding says which and what they are.
        self.assertIn("p.4 (claimant's CNIC)", flags[0].finding)
        self.assertIn("2 photocopies", flags[0].title)
        self.assertIn("p.6 (family certificate)", flags[0].finding)
        # The forwarding letter is an original, not a photocopy the SOP asks to be attested.
        self.assertNotIn("forwarding letter", flags[0].finding)

    def test_not_judged_is_not_reported(self):
        from rules.flags import check_attestation
        self.assertEqual(check_attestation(_record({4: date(2031, 1, 1)}, attested={4: None}), _pack()), [])
        self.assertEqual(check_attestation(_record({4: date(2031, 1, 1)}, attested={4: True}), _pack()), [])

    def test_both_checks_are_in_the_battery(self):
        from rules.flags import BATTERY, check_attestation, check_cnic_expiry
        self.assertIn(check_cnic_expiry, BATTERY)
        self.assertIn(check_attestation, BATTERY)


if __name__ == "__main__":
    unittest.main()
