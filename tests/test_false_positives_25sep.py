"""False HIGH flags found by comparing nine real cases with the Pension-AG deployment, 25 Sep 2026.

    python3 -m unittest tests.test_false_positives_25sep -v

Each test is one real misfire, reduced to the record that produced it, with the page reading
that settled it. The readers ported alongside (payroll statement, lakh recovery, Lifetime
cards) are pinned on the OCR text the real pages returned.
"""

from __future__ import annotations

import unittest
from datetime import date

from extraction.ocr import PageText, looks_degenerate, recoveries_in
from extraction.payroll import payroll_facts_on
from pipeline.extract import cnic_dates_from_text
from rules import Assertion, CaseRecord, Document, FamilyMember, Source, select_pack
from rules.flags import (
    check_cnic_cards_belong_to_the_case,
    check_family_consistency,
    check_identity_consistency,
    check_more_than_one_widow,
)

PACK = select_pack(effective_date=date(2026, 3, 1))
_A = Source(5, "ANNEX_A")
_F = Source(6, "NADRA_FRC")


def _record(**kw) -> CaseRecord:
    return CaseRecord(case_ref="t", case_type=kw.pop("case_type", ""), **kw)


class FamilyCheck(unittest.TestCase):
    def test_a_son_the_frc_omits_is_not_paired_with_his_brother(self) -> None:
        # 56e5: "Ahmad Raza" scored 0.86 against the FRC's "Hammad Raza" -- who is on
        # Annex-A too, and is that row's exact match.
        record = _record(
            annex_a_family=(FamilyMember("Hammad Raza", "Son", "Married", _A),
                            FamilyMember("Ahmad Raza", "Son", "Un-Married", _A)),
            frc_family=(FamilyMember("Hammad Raza", "Son", "Married", _F),))
        self.assertEqual(check_family_consistency(record, PACK), [])

    def test_nadra_child_is_a_son_or_a_daughter(self) -> None:
        # abdd: "Son" against the FRC's "Child".
        record = _record(
            annex_a_family=(FamilyMember("Muhammad Rizwan Elahi", "Son", "Un-Married", _A),),
            frc_family=(FamilyMember("Muhammad Rezwan Elahi", "Child", "Unmarried", _F),))
        self.assertEqual(check_family_consistency(record, PACK), [])

    def test_on_a_self_pension_a_real_difference_is_medium(self) -> None:
        record = _record(
            case_type="SUPERANNUATION_PENSION",
            annex_a_family=(FamilyMember("Arooj Akmal", "Daughter", "Married", _A),),
            frc_family=(FamilyMember("Arooj Akmal", "Child", "Unmarried", _F),))
        flags = check_family_consistency(record, PACK)
        self.assertEqual([f.severity for f in flags], ["MEDIUM"])

    def test_on_a_family_pension_the_same_difference_stays_high(self) -> None:
        record = _record(
            case_type="FAMILY_PENSION_DEATH_AFTER_RETIREMENT",
            annex_a_family=(FamilyMember("Arooj Akmal", "Daughter", "Married", _A),),
            frc_family=(FamilyMember("Arooj Akmal", "Child", "Unmarried", _F),))
        self.assertEqual([f.severity for f in check_family_consistency(record, PACK)], ["HIGH"])

    def test_a_column_label_read_as_the_relation_is_that_relation(self) -> None:
        # d368 re-read: the FRC reader returned "Mother Name" where the row says "Mother".
        from rules.flags import _RELATION, _norm_token
        self.assertEqual(_norm_token("Mother Name", _RELATION), "MOTHER")
        self.assertEqual(_norm_token("Father Name", _RELATION), "FATHER")

    def test_a_bracketed_note_does_not_change_the_marital_status(self) -> None:
        # e2c2: "Unmarried (Disabled)" on Annex-A, "Unmarried" on the FRC.
        from rules.flags import _marital
        self.assertEqual(_marital("Unmarried (Disabled)"), _marital("Unmarried"))

    def test_a_looping_frc_read_is_not_three_widows(self) -> None:
        # 27d5: "Zohra Bibi, Mother" four times and "Feroz Ud Din" among the mothers.
        rows = [("Muhammad Bashir", "Father"), ("Zohra Bibi", "Mother"),
                ("Feroz Ud Din", "Mother"), ("Hurmat Bibi", "Mother"),
                ("Zohra Bibi", "Mother"), ("Zohra Bibi", "Mother"), ("Zohra Bibi", "Mother")]
        record = _record(frc_family=tuple(FamilyMember(n, r, "Married", _F) for n, r in rows))
        self.assertEqual(check_more_than_one_widow(record, PACK), [])

    def test_two_real_mothers_are_still_raised(self) -> None:
        rows = [("Muhammad Bashir", "Father"), ("Zohra Bibi", "Mother"), ("Hurmat Bibi", "Mother")]
        record = _record(frc_family=tuple(FamilyMember(n, r, "Married", _F) for n, r in rows))
        self.assertEqual(len(check_more_than_one_widow(record, PACK)), 1)


class CnicCards(unittest.TestCase):
    def _case(self, holder: str) -> CaseRecord:
        return _record(
            claimant_name="Mst. Sobia Munir",
            annex_a_family=(FamilyMember("Muhammad Munir", "Self", "Unknown", _A),),
            documents=(Document("CNIC", pages=(2,), person_named=holder),),
            assertions=(Assertion("cnic", "3520112345671", Source(2, "CNIC")),))

    def test_a_card_held_by_neither_party_is_medium(self) -> None:
        # d368: cards of Nadeem and Khalid, witnesses, raised HIGH.
        flags = check_cnic_cards_belong_to_the_case(self._case("Muhammad Naveed"), PACK)
        self.assertEqual([f.severity for f in flags], ["MEDIUM"])

    def test_a_partys_uncorroborated_card_stays_high(self) -> None:
        flags = check_cnic_cards_belong_to_the_case(self._case("Sobia Munir"), PACK)
        self.assertEqual([f.severity for f in flags], ["HIGH"])

    def test_a_card_one_digit_from_a_quoted_number_is_a_misread(self) -> None:
        # 27d5: the card read ...0858, the bank form quotes ...0868.
        record = _record(
            claimant_name="Khalida Bibi",
            documents=(Document("CNIC", pages=(2,), person_named="Khalida Bibi"),),
            assertions=(Assertion("cnic", "0000100001158", Source(2, "CNIC")),
                        Assertion("cnic", "0000100001168", Source(8, "BANK_OPTION_FORM"))))
        flags = check_cnic_cards_belong_to_the_case(record, PACK)
        self.assertEqual([(f.severity, "misread" in f.title) for f in flags], [("MEDIUM", True)])

    def test_lifetime_on_the_card_wins_over_a_misplaced_issue_date(self) -> None:
        # ecb2, as OCR returned it: the issue date lost its label and sits under "Expiry".
        text = ("Date of Birth\n02.06.1966\nDate of Expiry\n24.06.2025\nLifetime\n"
                "Hukher's Signature")
        self.assertEqual(cnic_dates_from_text(text)["date_of_expiry"], "LIFETIME")

    def test_a_dated_expiry_is_still_read(self) -> None:
        text = "Date of Issue 01.02.2015 Date of Expiry 01.02.2025 12345-1234567-1"
        self.assertEqual(cnic_dates_from_text(text)["date_of_expiry"], "2025-02-01")


class PersonnelNumbers(unittest.TestCase):
    def test_a_nine_digit_reading_is_not_a_second_number(self) -> None:
        # 56e5: "839923865" -- p.14 prints no such number.
        record = _record(assertions=(
            Assertion("personnel_no", "30106724", Source(15, "SALARY_STATEMENT")),
            Assertion("personnel_no", "839923865", Source(14, "BANK_OPTION_FORM"))))
        self.assertEqual(check_identity_consistency(record, PACK), [])

    def test_two_eight_digit_numbers_still_conflict(self) -> None:
        record = _record(assertions=(
            Assertion("personnel_no", "90000853", Source(15, "SALARY_STATEMENT")),
            Assertion("personnel_no", "90000857", Source(1, "FILE_COVER"))))
        self.assertEqual([f.severity for f in check_identity_consistency(record, PACK)], ["HIGH"])


class Readers(unittest.TestCase):
    def test_an_rop_note_in_lakh_grouping_is_a_recovery(self) -> None:
        # abdd LPC p.10, as OCR returned it ("REDADE" is its "recovered").
        text = ("Total Deductions 16,753.00\n**ROP OF PAY & ALLOWANCES WEF 18.02.2026 TO "
                "28.02.2026 @ RS.1,76,336/- MAY PLEASE REDADE IN PENSION**")
        found = recoveries_in(PageText(page=10, text=text, model="t"))
        self.assertEqual([r["amount"] for r in found], [176336])

    def test_the_original_recovery_wording_still_reads(self) -> None:
        text = "to 28.02.2026 (10 days) amounting to Rs. 126,355 is recoverable."
        self.assertEqual([r["amount"] for r in recoveries_in(PageText(29, text, "t"))], [126355])

    def test_the_payroll_statement_gives_the_dates_and_the_stage(self) -> None:
        text = ("Personnel Number: 90000113  CNIC: 0000100001582  NTN:  Date of Birth: "
                "19.02.1966  Entry into Govt. Service: 01.11.1993  Length of Service: 32 Years "
                "03 Months 001 Days  Pay scale: BPS For: 2022  Pay Scale Type: Civil BPS: 16  "
                "Pay Stage: 27  0001 Basic Pay 89,090.00")
        f = payroll_facts_on(text)
        self.assertEqual((f.date_of_birth, f.entry_into_service, f.bps, f.pay_stage,
                          f.basic_pay, f.pay_scale_year, f.personnel_no),
                         (date(1966, 2, 19), date(1993, 11, 1), 16, 27, 89090, 2022, "90000113"))

    def test_a_looping_transcription_is_recognised(self) -> None:
        text = "Deductions " + "Deduction Amount " * 60
        self.assertTrue(looks_degenerate(PageText(8, text, "t")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
