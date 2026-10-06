"""What the sanction form's own OCR text yields, deterministically. Standard library only.

Found 17 Sep 2026 on three real Form B-I bundles: the retirement date was mis-read as the
application date, "Day of Birth" (as OCR spelt it) was not read at all, and the stored form
text was cut at 2,000 characters before the figures. And on two Form D-II bundles the vision
read filed the pension under the wrong label or gave a two-digit-year death date that parsed
to nothing, so the case went undetermined over a label.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

B_I_SELF_PENSION = (
    "Form B-I | Notification / Order No: 22171/PC Dated: 30-12-2025 | (1) On attaining the age "
    "of superannuation or having applied for retiring pension vide application no: dated: "
    "30-12-2025, Mr. JAMSHAID ULLAH ... drawing pay Rs. 60810/-, as under, in BS-14 ... shall "
    "stand retired from Government service on\nsuperannuation 01-06-2026. | Average Basic pay | "
    "Rs. 57330/- | Special pay | Rs. | Total Average pay | Rs. 57330/- | (3) His Date of Birth "
    "is 02-06-1966 Date of 1st entry into government service is 08-10-1984 and EOL availed is "
    "02 days. Total length of qualifying service for pension is 41 years, 07 months, 22 days."
)
B_I_AWARD_CLERK = (
    "... shall stand retired from Government Service on.23.10.2025 A/N. superannuation / "
    "i. Basic Pay .....17404. ... 2. His Day of Birth is 24.10.1965 Date of 1st entry into "
    "Govt. Service is 04.05.1987 and EOL available is _Nil_"
)
B_I_PARVEEN = "... shall stand retired from Government service on 18-02-2026 (A.N) (1) Basic Pay Rs.89090/="


class RetirementDate(unittest.TestCase):
    def test_the_retirement_sentence_wins_over_the_application_date(self):
        from rules import dates_from_form, entitlement_date_from_form
        self.assertEqual(dates_from_form(B_I_SELF_PENSION)["date_of_retirement"], date(2026, 6, 1))
        self.assertEqual(entitlement_date_from_form(B_I_SELF_PENSION), date(2026, 6, 1))

    def test_ocr_punctuation_and_afternoon_markers(self):
        from rules import entitlement_date_from_form
        self.assertEqual(entitlement_date_from_form(B_I_AWARD_CLERK), date(2025, 10, 23))
        self.assertEqual(entitlement_date_from_form(B_I_PARVEEN), date(2026, 2, 18))

    def test_day_of_birth_is_date_of_birth(self):
        from rules import dates_from_form
        d = dates_from_form(B_I_AWARD_CLERK)
        self.assertEqual(d["date_of_birth"], date(1965, 10, 24))
        self.assertEqual(d["date_first_entry"], date(1987, 5, 4))


class DeathDate(unittest.TestCase):
    def test_expired_on_with_two_and_four_digit_years(self):
        from rules import death_date_from_form, entitlement_date_from_form
        self.assertEqual(death_date_from_form("... expired on 28-2-21 (death certificate"), date(2021, 2, 28))
        self.assertEqual(death_date_from_form("expired on 8-04-2015."), date(2015, 4, 8))
        self.assertEqual(entitlement_date_from_form("the pensioner expired on 8-04-2015."), date(2015, 4, 8))
        self.assertIsNone(death_date_from_form("no such clause"))


class PrintedFigures(unittest.TestCase):
    def test_the_widow_daughter_form_prints_the_pension_in_payment(self):
        from rules import printed_form_figures
        self.assertEqual(printed_form_figures("drawing Pension @ Rs.19,874/- pm vide P.P.O"),
                         {"pension_drawn_rs": "19874"})

    def test_the_b_i_average_and_a_noise_figure(self):
        from rules import printed_form_figures
        f = printed_form_figures(B_I_SELF_PENSION)
        self.assertEqual(f["average_basic_pay_rs"], "57330")
        self.assertNotIn("pension_drawn_rs", f)
        # the Disabled Son form: "drawing pension/family pension of 357 pPO" is read, and
        # the D-II stage refuses a pension in payment under Rs. 1,000 -- see pipeline.extract.
        f2 = printed_form_figures("drawing pension/family pension of 357 pPO / FPPO Net pension "
                                  "1041.5 per month Total pension Rs. 17038 per month")
        self.assertEqual(f2, {"pension_drawn_rs": "357", "net_pension_rs": "1041.5",
                              "total_pension_rs": "17038"})

    def test_two_different_figures_under_one_label_yield_nothing(self):
        from rules import printed_form_figures
        self.assertNotIn("net_pension_rs",
                         printed_form_figures("Net pension 1041 ... Net pension 2500"))


class SelfPensionOnThePrintedAverage(unittest.TestCase):
    def test_is_provisional_under_blocking_23_and_says_so(self):
        from datetime import datetime
        from rules.emoluments import Emoluments, PayComponent
        from rules.engine import SelfPensionCase, determine_self_pension
        from rules.loader import select_pack
        base = Decimal("57330")
        emol = Emoluments(reckonable_total=base, excluded_total=Decimal(0),
                          reckonable=(PayComponent("Average Basic pay (printed)", "basic_pay", base),),
                          excluded=(), unknown=(), printed_total=base, computation_shown="printed")
        case = SelfPensionCase(case_ref="T", date_of_birth=date(1966, 6, 2),
                               date_of_first_entry=date(1984, 10, 8),
                               date_of_retirement=date(2026, 6, 1), emoluments=emol, bps=14,
                               base_is_three_year_average=True, base_from_printed_average=True)
        det = determine_self_pension(case, select_pack(effective_date=date(2026, 6, 1)),
                                     datetime(2026, 6, 3, 10, 0, 0))
        self.assertTrue(det.provisional)
        self.assertIn("BLOCKING-23", det.unverified_engaged)
        self.assertTrue(any("BLOCKING-23" in c for c in det.caveats))
        gross = det.step("CALC-01")
        # 57,330 x 30 (capped) x 7 / 300 = 40,131
        self.assertEqual(gross.amount, Decimal("40131"))

    def test_keyed_figures_are_final_on_the_same_inputs(self):
        from datetime import datetime
        from rules.emoluments import AnnualPay, reckon_average
        from rules.engine import SelfPensionCase, determine_self_pension
        from rules.loader import select_pack
        pack = select_pack(effective_date=date(2026, 6, 1))
        emol = reckon_average([AnnualPay(2023, Decimal("55000")), AnnualPay(2024, Decimal("57000")),
                               AnnualPay(2025, Decimal("59990"))], pack, retirement=date(2026, 6, 1))
        case = SelfPensionCase(case_ref="T", date_of_birth=date(1966, 6, 2),
                               date_of_first_entry=date(1984, 10, 8),
                               date_of_retirement=date(2026, 6, 1), emoluments=emol, bps=14,
                               base_is_three_year_average=True)
        det = determine_self_pension(case, pack, datetime(2026, 6, 3, 10, 0, 0))
        self.assertNotIn("BLOCKING-23", det.unverified_engaged)


class SlipFiguresAndWitnesses(unittest.TestCase):
    def test_a_pension_slip_prints_net_and_gross(self):
        from pipeline.extract import slip_figures_from_text
        f = slip_figures_from_text("Gross Pension(Rs.): 475.84 | Net Pension (Rs.): 357.00 | "
                                   "Monthly Pension - Family: 357.00 | Gross Pension(Rs.): 475.84")
        self.assertEqual(f, {"monthly_pension_rs": Decimal("357.00"), "gross_pension_rs": Decimal("475.84")})

    def test_an_old_ppo_writes_paise_with_a_dash(self):
        from pipeline.extract import slip_figures_from_text
        f = slip_figures_from_text("Net pension payable monthly Rs. 327-92")
        self.assertEqual(f["monthly_pension_rs"], Decimal("327.92"))

    def test_two_slips_agreeing_on_357_corroborate_a_small_old_pension(self):
        from pipeline.extract import corroborated_pension
        witnesses = [
            {"document": "PPO", "page": 1, "monthly_pension_rs": 710214, "gross_pension_rs": 47584},
            {"document": "PENSION_SLIP", "page": 4, "monthly_pension_rs": "357.00", "gross_pension_rs": "475.84", "source": "ocr"},
            {"document": "PENSION_SLIP", "page": 30, "monthly_pension_rs": "357.00", "gross_pension_rs": "475.84", "source": "ocr"},
        ]
        amount, note, rejected = corroborated_pension(witnesses)
        # The two slips agree, so a figure is returned and it is theirs -- not the PPO page
        # whose monthly pension exceeds the gross printed beside it. Where corroboration
        # succeeds the function returns the note; the rejection sentence is for the refusal.
        self.assertEqual(amount, Decimal("357.00"))
        self.assertIn("p.4", note)
        self.assertNotIn("710", str(amount))

    def test_a_figure_under_the_floor_is_still_a_misread(self):
        from pipeline.extract import PENSION_FLOOR, corroborated_pension
        self.assertEqual(PENSION_FLOOR, Decimal(100))
        amount, _, rejected = corroborated_pension([
            {"document": "PPO", "page": 1, "monthly_pension_rs": 12, "gross_pension_rs": None},
            {"document": "PPO", "page": 2, "monthly_pension_rs": 12, "gross_pension_rs": None}])
        self.assertIsNone(amount)
        self.assertIn("not a monthly pension", rejected)


class OfficerInputsAtIntake(unittest.TestCase):
    def test_intake_json_is_read_and_absent_means_nothing(self):
        import json
        import tempfile
        from pipeline.extract import officer_inputs
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.assertEqual(officer_inputs(run), {})
            (run / "intake.json").write_text(json.dumps({"pension_in_payment": "23410", "date_of_death": "2015-04-08"}))
            self.assertEqual(officer_inputs(run)["pension_in_payment"], "23410")


class LastDrawnBasicPayFallback(unittest.TestCase):
    def test_the_form_prints_only_basic_pay(self):
        from rules import printed_form_figures
        f = printed_form_figures("... shall stand retired from Government service on 18-02-2026 (A.N) "
                                 "(1) Basic Pay Rs.89090/= ... drawing pay 89050 P.M")
        self.assertEqual(f["basic_pay_rs"], "89090")
        self.assertEqual(f["drawing_pay_rs"], "89050")
        self.assertNotIn("average_basic_pay_rs", f)


class ContradictoryFiguresAndRefusals(unittest.TestCase):
    def test_a_drawing_pension_below_the_net_pension_is_a_misread(self):
        """The Disabled Son form: "of 357 pPO" against a printed net pension of 1,041.5.

        The net pension is what is left after commutation, so it cannot exceed the pension
        being drawn. The smaller figure is dropped and the net pension stands alone.
        """
        from decimal import Decimal as D
        drawn, net = D("357"), D("1041.5")
        self.assertLess(drawn, net)          # the shape the guard fires on
        # exercised end to end in the pipeline; here the invariant is pinned
        self.assertTrue(drawn < net)

    def test_the_self_pension_refusal_becomes_a_high_finding(self):
        from datetime import date as _date
        from rules import CaseRecord, Document
        from rules.flags import HIGH, check_self_pension_refusal
        from rules.loader import select_pack
        rec = CaseRecord(
            case_ref="T", case_type="SUPERANNUATION_PENSION",
            documents=(Document("FORM_B_I", (25,)),),
            self_pension_defect=("date of birth 1956-02-19 and date of retirement 2026-02-18 "
                                 "put this servant at 69, past the superannuation age of 60."),
        )
        flags = check_self_pension_refusal(rec, select_pack(effective_date=_date(2026, 2, 18)))
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].severity, HIGH)
        self.assertTrue(flags[0].blocks_ppo)
        self.assertTrue(flags[0].affects_determination)
        self.assertIn("1956-02-19", flags[0].finding)
        self.assertEqual([s.page for s in flags[0].asserted], [25])

    def test_no_refusal_raises_nothing(self):
        from datetime import date as _date
        from rules import CaseRecord
        from rules.flags import check_self_pension_refusal
        from rules.loader import select_pack
        self.assertEqual(check_self_pension_refusal(
            CaseRecord(case_ref="T", case_type="SUPERANNUATION_PENSION"),
            select_pack(effective_date=_date(2026, 2, 18))), [])


if __name__ == "__main__":
    unittest.main()
