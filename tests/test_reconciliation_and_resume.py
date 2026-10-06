"""Why three real bundles produced no pension on 15-16 September, pinned. BRAIN §8.4, §15.2.

    python3 -m unittest tests.test_reconciliation_and_resume -v

Each class here is one failure observed on a real case file in the artifacts directory, and
each test asserts the behaviour that would have let the determination through:

* the OSD-post Form D-I (run 6b9b40577627) -- a Rs. 750 qualification pay the AG salary
  statement prints and the form's total omits stopped the whole determination, and the
  cross-document sweep died on a type error before it ran a single check;
* the divorced-daughter Proforma D-II (run d368727d936e) -- denied by an OCR pattern that
  was widened the same afternoon, and never re-examined because the denial had been written
  back over the model's claim;
* the salary statement whose second read flipped the sign of four deductions and was
  recorded as unusable, though every pay line agreed.

Standard library only; no GPU and no network.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _pack():
    from rules import select_pack
    # The OSD-post servant died 22-08-2023: the pre-amendment pack, on which qualification
    # pay is reckonable (EMOL-04). The December 2024 pack averages basic and personal pay
    # only, so on it the Rs. 750 line would be excluded, not mismatched.
    return select_pack(effective_date=date(2023, 8, 22))


#: The OSD-post pay lines, as the salary statement (p.8) and Form D-I (p.2) actually print
#: them. Basic pay 89,530 is the only line on the form, so it equals the form's total.
def _osd_components():
    from rules import PayComponent
    return [
        PayComponent("Basic Pay", "basic_pay", 89_530, page=8),
        PayComponent("Qualification Pay", "qualification_pay", 750, page=8),
        PayComponent("House Rent Allowance 45%", "non_reckonable_allowance", 6_650, page=8),
        PayComponent("Adhoc Relief All 2023 30%", "non_reckonable_allowance", 23_781, page=8),
    ]


# ==============================================================================================

class Stage6NoLongerDiesOnItsFirstPayDocument(unittest.TestCase):
    """``basic_pay_in`` was handed ``PayComponent`` objects and called ``.get`` on them."""

    def test_reads_the_basic_pay_off_pay_components(self):
        from pipeline.extract import basic_pay_in
        self.assertEqual(basic_pay_in(_osd_components()), 89_530)

    def test_still_reads_dicts(self):
        from pipeline.extract import basic_pay_in
        rows = [{"printed_label": "Adhoc Relief", "amount": 23_781},
                {"printed_label": "Basic Pay", "amount": 89_530}]
        self.assertEqual(basic_pay_in(rows), 89_530)

    def test_never_guesses_the_largest_line(self):
        from pipeline.extract import basic_pay_in
        from rules import PayComponent
        self.assertIsNone(basic_pay_in([
            PayComponent("Adhoc Relief All 2023 30%", "non_reckonable_allowance", 23_781),
        ]))


class ALoneBasicPayIsNotAMisreadTotal(unittest.TestCase):
    """The form prints "Basic Pay 89,530 / Total 89,530"; both lines are true."""

    def test_the_basic_pay_survives_equalling_the_total(self):
        from pipeline.extract import _pay_components
        out = _pay_components({"pay_components": [
            {"printed_label": "Basic Pay", "amount_rs": 89_530},
            {"printed_label": "Total", "amount_rs": 89_530},
        ]}, page=2, printed_total=89_530)
        self.assertEqual([(c.component, int(c.amount)) for c in out],
                         [("basic_pay", 89_530)])

    def test_a_label_that_borrowed_the_total_is_still_dropped(self):
        """The golden case's "Orderly Allowance 192,030" -- the reason the drop exists."""
        from pipeline.extract import _pay_components
        out = _pay_components({"pay_components": [
            {"printed_label": "Basic Pay", "amount_rs": 178_440},
            {"printed_label": "Personal Pay", "amount_rs": 13_590},
            {"printed_label": "Orderly Allowance", "amount_rs": 192_030},
        ]}, page=41, printed_total=192_030)
        self.assertNotIn("orderly_allowance", [c.component for c in out])


class TheSecondReadIsJudgedOnWhatTheDeterminationUses(unittest.TestCase):
    """Four deductions with their sign flipped are not a disagreement about pay."""

    def test_deduction_rows_are_not_compared(self):
        from extraction.client import _figures_that_matter
        read_a = {"pay_components": [
            {"printed_label": "Basic Pay", "amount_rs": 89_530},
            {"printed_label": "GPFS Subscription", "amount_rs": 6_350},
            {"printed_label": "Income Tax", "amount_rs": 8_356},
        ]}
        read_b = {"pay_components": [
            {"printed_label": "Basic Pay", "amount_rs": 89_530},
            {"printed_label": "GP Subscription", "amount_rs": -6_350},
            {"printed_label": "Income Tax", "amount_rs": -8_356},
        ]}
        self.assertEqual(_figures_that_matter(read_a), _figures_that_matter(read_b))

    def test_a_pay_line_that_differs_is_still_a_disagreement(self):
        from extraction.client import _figures_that_matter
        a = {"pay_components": [{"printed_label": "Basic Pay", "amount_rs": 89_530}]}
        b = {"pay_components": [{"printed_label": "Basic Pay", "amount_rs": 98_530}]}
        self.assertNotEqual(_figures_that_matter(a), _figures_that_matter(b))

    def test_the_d_ii_pension_figure_is_now_compared(self):
        """``pension_drawn_rs`` is the one figure a D-II determination rests on."""
        from extraction.client import _printed_figures
        a = {"pension_drawn_rs": 50_000, "net_pension_rs": 1_066, "claimant_name": {}}
        b = {"pension_drawn_rs": 50_000, "net_pension_rs": 1_606, "claimant_name": {}}
        self.assertNotEqual(_printed_figures(a), _printed_figures(b))
        self.assertNotIn("claimant_name", _printed_figures(a))


# ==============================================================================================

class ADeniedFormIsReExaminedOnEveryRun(unittest.TestCase):
    """The denial used to be written over the model's claim, and the fix never reached it."""

    def _run_dir(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        (tmp / "pages").mkdir()
        (tmp / "pages" / "p009.png").write_bytes(b"")
        (tmp / "manifest.json").write_text(json.dumps({
            "pages": [{"page": 9, "image_path": "pages/p009.png"}],
        }))
        (tmp / "identities.json").write_text(json.dumps([{
            "page": 9, "document_type": "OTHER", "downgraded_from": "FORM_D_II",
            "needs_human": True, "confidence": 1.0, "evidence": "Proforma D-II",
            "is_first_page_of_document": True, "signed_by_psa": True, "attested": False,
            "printed_form_number": "D-II",
        }]))
        return tmp

    def test_the_original_claim_is_what_gets_verified(self):
        from pipeline.run import stage_verify_forms
        seen: list[str] = []

        def fake_verify(identities, image_for):
            seen.extend(i.document_type for i in identities)
            return tuple(identities)          # OCR now corroborates every claim

        fake_verify.form_text = {}
        with mock.patch("extraction.identify.verify_with_ocr", fake_verify):
            rows = stage_verify_forms(self._run_dir())
        self.assertEqual(seen, ["FORM_D_II"])
        self.assertEqual(rows[0]["document_type"], "FORM_D_II")
        self.assertNotIn("downgraded_from", rows[0])
        self.assertNotIn("needs_human", rows[0])

    def test_a_denial_that_stands_still_stands(self):
        from extraction.identify import PageIdentity
        from pipeline.run import stage_verify_forms

        def fake_verify(identities, image_for):
            i = identities[0]
            return (PageIdentity(page=i.page, document_type="OTHER", confidence=i.confidence,
                                 evidence=i.evidence, is_first_page=i.is_first_page,
                                 downgraded_from=i.document_type),)

        fake_verify.form_text = {}
        with mock.patch("extraction.identify.verify_with_ocr", fake_verify):
            rows = stage_verify_forms(self._run_dir())
        self.assertEqual(rows[0]["document_type"], "OTHER")
        self.assertEqual(rows[0]["downgraded_from"], "FORM_D_II")

    def test_a_page_the_re_read_placed_elsewhere_is_left_alone(self):
        """AFFIDAVIT with downgraded_from FORM_D_II is a settled re-read, not an open denial."""
        from pipeline.run import stage_verify_forms
        run = self._run_dir()
        rows = json.loads((run / "identities.json").read_text())
        rows[0]["document_type"] = "AFFIDAVIT"
        (run / "identities.json").write_text(json.dumps(rows))
        seen: list[str] = []

        def fake_verify(identities, image_for):
            seen.extend(i.document_type for i in identities)
            return tuple(identities)

        fake_verify.form_text = {}
        with mock.patch("extraction.identify.verify_with_ocr", fake_verify):
            stage_verify_forms(run)
        self.assertEqual(seen, ["AFFIDAVIT"])


# ==============================================================================================

class AMismatchIsComputedThroughAndSaidOnItsFace(unittest.TestCase):
    """BRAIN §8.4: return the discrepancy for a flag. Not: compute nothing."""

    def _case(self, components, printed_total):
        from rules import reckon
        from rules.engine import DeathInServiceCase
        emol = reckon(components, _pack(), printed_total=printed_total)
        return DeathInServiceCase(
            case_ref="osd", date_of_birth=date(1966, 6, 11),
            date_of_first_entry=date(1984, 8, 20), date_of_death=date(2023, 8, 22),
            emoluments=emol, bps=17,
        ), emol

    def test_the_determination_is_produced_provisional_on_the_pay_records(self):
        from rules.engine import EMOL_RECONCILE, determine_family_pension_death_in_service
        case, emol = self._case(_osd_components(), printed_total=89_530)
        self.assertFalse(emol.reconciled)
        det = determine_family_pension_death_in_service(case, _pack(), datetime(2026, 9, 16))
        self.assertTrue(det.provisional)
        self.assertIn(EMOL_RECONCILE, det.unverified_engaged)
        self.assertEqual(det.amount("EMOL-BASE"), 90_280)
        self.assertIn("89,530", det.step("EMOL-BASE").note)
        self.assertIn("750", det.step("EMOL-BASE").note)

    def test_a_reconciled_case_engages_nothing_extra(self):
        from rules.engine import EMOL_RECONCILE, determine_family_pension_death_in_service
        case, _ = self._case(_osd_components(), printed_total=90_280)
        det = determine_family_pension_death_in_service(case, _pack(), datetime(2026, 9, 16))
        self.assertNotIn(EMOL_RECONCILE, det.unverified_engaged)

    def test_an_unsummable_line_still_refuses(self):
        from rules import PayComponent
        from rules.engine import determine_family_pension_death_in_service
        case, _ = self._case(
            [*_osd_components(), PayComponent("Hill Allowance", "unknown", 9_000, page=8)],
            printed_total=89_530,
        )
        with self.assertRaises(ValueError) as ctx:
            determine_family_pension_death_in_service(case, _pack(), datetime(2026, 9, 16))
        self.assertIn("cannot be summed", str(ctx.exception))

    def test_stage_determine_no_longer_refuses_on_a_mismatch(self):
        """The pipeline seam: the refusal used to happen before the engine was reached."""
        import inspect
        from pipeline import extract
        src = inspect.getsource(extract.stage_determine)
        self.assertNotIn("emoluments do not reconcile", src)
        self.assertIn("emol.unknown", src)


class TheMismatchReachesTheOfficerAsAFlag(unittest.TestCase):
    def _record(self, components, printed_total):
        from rules import CaseRecord, Document, reckon
        emol = reckon(components, _pack(), printed_total=printed_total)
        return CaseRecord(
            case_ref="osd", case_type="FAMILY_PENSION_DEATH_IN_SERVICE",
            documents=(Document("FORM_D_I", (2,)), Document("SALARY_STATEMENT", (8,))),
            emoluments=emol,
        )

    def test_high_and_names_the_omitted_line(self):
        from rules.flags import CONTRA_MONEY, HIGH, check_emoluments_reconciliation
        flags = check_emoluments_reconciliation(self._record(_osd_components(), 89_530), _pack())
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual(f.severity, HIGH)
        self.assertEqual(f.flag_class, CONTRA_MONEY)
        self.assertTrue(f.blocks_ppo)
        self.assertTrue(f.affects_determination)
        self.assertIn("Qualification Pay", f.finding)
        self.assertIn("Rs. 750", f.finding)
        self.assertIn("omits", f.finding)
        self.assertEqual([(s.page, s.document) for s in f.asserted], [(8, "SALARY_STATEMENT")])
        self.assertEqual([(s.page, s.document) for s in f.contradicted_by], [(2, "FORM_D_I")])

    def test_silent_when_reconciled(self):
        from rules.flags import check_emoluments_reconciliation
        self.assertEqual(
            check_emoluments_reconciliation(self._record(_osd_components(), 90_280), _pack()), [])

    def test_silent_when_there_was_nothing_to_reconcile_against(self):
        from rules.flags import check_emoluments_reconciliation
        self.assertEqual(
            check_emoluments_reconciliation(self._record(_osd_components(), None), _pack()), [])

    def test_a_mismatch_no_single_line_explains_says_so(self):
        from rules.flags import check_emoluments_reconciliation
        flags = check_emoluments_reconciliation(self._record(_osd_components(), 89_000), _pack())
        self.assertIn("No single pay line accounts for it", flags[0].finding)

    def test_it_is_in_the_battery_and_drives_return_for_correction(self):
        from rules import run_battery
        from rules.flags import BATTERY, check_emoluments_reconciliation
        self.assertIn(check_emoluments_reconciliation, BATTERY)
        flags = run_battery(self._record(_osd_components(), 89_530), _pack())
        self.assertTrue(any(f.flag_class == "CONTRA-MONEY" and f.blocks_ppo for f in flags))

    def test_report_rebuilds_the_emoluments_from_the_artefact(self):
        from pipeline.report import _emoluments_from
        emol = _emoluments_from({
            "reckonable_total": 90_280, "excluded_total": 30_431, "printed_total": 89_530,
            "reconciled": False,
            "components": [
                {"printed_label": "Basic Pay", "component": "basic_pay", "amount": 89_530,
                 "reckonable": True, "page": 8},
                {"printed_label": "Qualification Pay", "component": "qualification_pay",
                 "amount": 750, "reckonable": True, "page": 8},
                {"printed_label": "House Rent Allowance 45%",
                 "component": "non_reckonable_allowance", "amount": 6_650,
                 "reckonable": False, "page": 8},
            ],
        })
        self.assertEqual(emol.reckonable_total, Decimal(90_280))
        self.assertEqual(emol.printed_total, Decimal(89_530))
        self.assertFalse(emol.reconciled)
        self.assertIsNone(_emoluments_from(None))


class AReportSurvivesADateNoPackCovers(unittest.TestCase):
    """The Widow Daughter pensioner died in 2011; the earliest pack starts in 2017."""

    def test_the_nearest_pack_is_used_for_the_checks_only_and_said_so(self):
        import inspect
        from pipeline import report
        src = inspect.getsource(report.build_report)
        self.assertIn("except PackError", src)
        self.assertIn("nearest", src)

    def test_the_d_ii_death_date_is_the_entitlement_date(self):
        import inspect
        from pipeline import report
        self.assertIn("date_of_death_of_pensioner", inspect.getsource(report.build_report))


# ==============================================================================================
# The NADRA FRC speaks from the seat of whoever requested it. 16 September: this put a HIGH
# flag on every member of every real family and left the office unable to forward anything.
# ==============================================================================================

def _family(rows):
    from rules import FamilyMember, Source
    return tuple(FamilyMember(n, r, m, Source(p, d)) for n, r, m, p, d in rows)


def _record(annex, frc):
    from rules import CaseRecord
    return CaseRecord(case_ref="T", case_type="FAMILY_PENSION_DEATH_AFTER_RETIREMENT",
                      annex_a_family=_family(annex), frc_family=_family(frc))


#: The Ghulam Zainab bundle, as extracted. The FRC's "Self" is the son, so the deceased reads
#: "Father", the widow "Mother" and a daughter "Sister".
GHULAM_AYESHA_ANNEX = [
    ("Akbar Hussain", "Husband", "Died on 03.07.2026", 5, "ANNEX_A"),
    ("Ghulam Zainab", "Self", "Widow", 5, "ANNEX_A"),
    ("Syed Bilal Akbar", "Son", "Married", 5, "ANNEX_A"),
    ("Amna Batool", "Daughter", "Married", 5, "ANNEX_A"),
]
GHULAM_AYESHA_FRC = [
    ("Akbar Hussain", "Father", "Married", 7, "NADRA_FRC"),
    ("Ghulam Zainab", "Mother", "Widowed", 7, "NADRA_FRC"),
    ("Syed Bilal Akbar", "Self", "Married", 7, "NADRA_FRC"),
    ("Amna Batool", "Sister", "Married", 7, "NADRA_FRC"),
]


class AnFrcFromAnotherSeatIsNotAContradiction(unittest.TestCase):
    def test_no_high_flag_on_a_family_that_agrees(self):
        from rules.flags import HIGH, check_family_consistency
        flags = check_family_consistency(_record(GHULAM_AYESHA_ANNEX, GHULAM_AYESHA_FRC),
                                         _pack())
        self.assertEqual([f for f in flags if f.severity == HIGH], [])

    def test_the_frame_is_recorded_rather_than_hidden(self):
        from rules.flags import LOW, check_family_consistency
        flags = check_family_consistency(_record(GHULAM_AYESHA_ANNEX, GHULAM_AYESHA_FRC),
                                         _pack())
        self.assertEqual([f.severity for f in flags], [LOW])
        self.assertIn("relative to the family member who requested it", flags[0].finding)
        self.assertFalse(flags[0].blocks_ppo)

    def test_a_real_contradiction_still_fires_through_the_frame(self):
        """The golden case's F-2: Annex-A calls a married son an unmarried daughter."""
        from rules.flags import HIGH, check_family_consistency
        annex = [*GHULAM_AYESHA_ANNEX,
                 ("Usman Waqar", "Daughter", "Un-Married", 5, "ANNEX_A")]
        frc = [*GHULAM_AYESHA_FRC, ("Usman Waqqar", "Brother", "Married", 7, "NADRA_FRC")]
        high = [f for f in check_family_consistency(_record(annex, frc), _pack())
                if f.severity == HIGH]
        self.assertEqual(len(high), 1)
        self.assertIn("Usman Waqar", high[0].title)
        self.assertIn("marital status", high[0].finding)
        self.assertIn("allowed for", high[0].finding)

    def test_a_relation_the_seat_does_not_explain_still_fires(self):
        from rules.flags import HIGH, check_family_consistency
        annex = [*GHULAM_AYESHA_ANNEX, ("Kamran Shah", "Son", "Married", 5, "ANNEX_A")]
        frc = [*GHULAM_AYESHA_FRC, ("Kamran Shah", "Father", "Married", 7, "NADRA_FRC")]
        high = [f for f in check_family_consistency(_record(annex, frc), _pack())
                if f.severity == HIGH]
        self.assertEqual([f.title for f in high],
                         ["Annex-A contradicts NADRA FRC for Kamran Shah"])

    def test_one_odd_pair_does_not_veto_the_frame_for_the_rest(self):
        """A single mis-paired name put four HIGH flags back on the divorced-daughter case."""
        from rules.flags import HIGH, check_family_consistency
        annex = [*GHULAM_AYESHA_ANNEX, ("Tahir Munir", "Son", "Married", 5, "ANNEX_A")]
        frc = [*GHULAM_AYESHA_FRC, ("Tahir Munir", "Mother", "Married", 7, "NADRA_FRC")]
        high = [f for f in check_family_consistency(_record(annex, frc), _pack())
                if f.severity == HIGH]
        self.assertEqual(len(high), 1)
        self.assertIn("Tahir Munir", high[0].title)

    def test_two_documents_in_the_same_frame_are_compared_directly(self):
        """An FRC headed by the widow: no shift, and a real difference is still caught."""
        from rules.flags import HIGH, check_family_consistency
        annex = [("Ghulam Zainab", "Widow", "Widow", 5, "ANNEX_A"),
                 ("Amna Batool", "Daughter", "Un-Married", 5, "ANNEX_A")]
        frc = [("Ghulam Zainab", "Self", "Widowed", 7, "NADRA_FRC"),
               ("Amna Batool", "Daughter", "Married", 7, "NADRA_FRC")]
        flags = check_family_consistency(_record(annex, frc), _pack())
        self.assertEqual([f.severity for f in flags], [HIGH])
        self.assertIn("marital status", flags[0].finding)

    def test_a_blank_marital_column_is_unstated_not_a_disagreement(self):
        from rules.flags import check_family_consistency
        annex = [("Soghran Begum", "Wife", "Unknown", 5, "ANNEX_A"),
                 ("Huma Rauf", "Daughter", "Married", 5, "ANNEX_A")]
        frc = [("Sughran Begum", "Mother", "Married", 7, "NADRA_FRC"),
               ("Huma Rauf", "Sister", "Married", 7, "NADRA_FRC")]
        self.assertEqual(
            [f.title for f in check_family_consistency(_record(annex, frc), _pack())
             if f.severity == "HIGH"], [])

    def test_a_widow_the_frc_still_calls_married_is_not_accused(self):
        """NADRA updates that column when someone reports the death; the certificate does not."""
        from rules.flags import check_family_consistency
        annex = [("Gulshan Jan", "widow", "Widow", 5, "ANNEX_A"),
                 ("Khurshid Begum", "daughter", "Married", 5, "ANNEX_A")]
        frc = [("Gulshaan Jan", "mother", "Married", 7, "NADRA_FRC"),
               ("Khurshid Begum", "sister", "Married", 7, "NADRA_FRC")]
        self.assertEqual(
            [f.title for f in check_family_consistency(_record(annex, frc), _pack())
             if f.severity == "HIGH"], [])

    def test_the_deceased_marital_column_is_never_compared(self):
        from rules.flags import _marital
        for text in ("Died on 03.07.2026", "Late", "Expired", "deceased"):
            self.assertEqual(_marital(text), "DECEASED", text)
        self.assertEqual(_marital("Un-Married"), "UNMARRIED")
        self.assertEqual(_marital("Widow"), "WIDOWED")


# ==============================================================================================
# The unmarried-daughter bundle (run a181349b84b8, 69 pages): the form's money fields were left
# blank, the relation reads a bare "Daughter", and the family columns are abbreviated.
# ==============================================================================================

class ABareDaughterStillGetsAChecklist(unittest.TestCase):
    def _suggest(self, **kw):
        from rules import suggest_variant
        from rules.case_type import FAMILY_PENSION_DEATH_AFTER_RETIREMENT
        return suggest_variant(FAMILY_PENSION_DEATH_AFTER_RETIREMENT, kw.pop("form_text", ""),
                               **kw)

    def test_nadra_marital_status_settles_the_column(self):
        got = self._suggest(claimant_relation="Daughter", claimant_marital="Unmarried")
        self.assertEqual(got.variant, "UNMARRIED_CHILD")
        self.assertIn("NADRA record", got.evidence)

    def test_a_widowed_or_divorced_daughter_takes_her_own_column(self):
        self.assertEqual(self._suggest(claimant_relation="Daughter",
                                       claimant_marital="Widow").variant, "WD_DAUGHTER")
        self.assertEqual(self._suggest(claimant_relation="Daughter",
                                       claimant_marital="Divorced").variant,
                         "DIVORCED_DAUGHTER")

    def test_without_a_marital_status_the_field_is_narrowed_to_three_not_seven(self):
        got = self._suggest(claimant_relation="Daughter")
        self.assertIsNone(got.variant)
        self.assertEqual(list(got.candidates),
                         ["UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER"])
        self.assertIn("separates the three daughter columns", got.evidence)

    def test_an_explicit_wording_still_wins_over_the_marital_status(self):
        got = self._suggest(claimant_relation="divorced daughter", claimant_marital="Unmarried")
        self.assertEqual(got.variant, "DIVORCED_DAUGHTER")

    def test_a_son_takes_the_child_column(self):
        self.assertEqual(self._suggest(claimant_relation="Son").variant, "UNMARRIED_CHILD")


class AFormWithNoPensionFigureIsADefectNotJustAGap(unittest.TestCase):
    def _record(self, blanks):
        from rules import CaseRecord, Document
        return CaseRecord(case_ref="T", case_type="FAMILY_PENSION_DEATH_AFTER_RETIREMENT",
                          documents=(Document("FORM_D_II", (32,)),),
                          prescribed_form_blanks=blanks)

    def test_it_is_high_and_names_the_fields(self):
        from rules.flags import HIGH, check_prescribed_form_is_complete
        flags = check_prescribed_form_is_complete(
            self._record(('the pension in payment, "Net pension" and "Total pension"',)),
            _pack())
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].severity, HIGH)
        self.assertTrue(flags[0].blocks_ppo)
        self.assertTrue(flags[0].affects_determination)
        self.assertIn("Net pension", flags[0].finding)
        self.assertEqual([(s.page, s.document) for s in flags[0].asserted],
                         [(32, "FORM_D_II")])
        self.assertIn("re-signed", flags[0].required_action)

    def test_silent_where_the_form_is_complete(self):
        from rules.flags import check_prescribed_form_is_complete
        self.assertEqual(check_prescribed_form_is_complete(self._record(()), _pack()), [])

    def test_it_is_in_the_battery(self):
        from rules.flags import BATTERY, check_prescribed_form_is_complete
        self.assertIn(check_prescribed_form_is_complete, BATTERY)


class TheColumnsAreAbbreviatedOnRealForms(unittest.TestCase):
    def test_dst_and_dgt_are_daughters(self):
        from rules.flags import _RELATION, _norm_token
        for token in ("DST", "DGT", "DTR"):
            self.assertEqual(_norm_token(token, _RELATION), "DAUGHTER", token)

    def test_a_single_letter_marital_column_reads(self):
        from rules.flags import _marital
        self.assertEqual(_marital("M"), "MARRIED")
        self.assertEqual(_marital("U"), "UNMARRIED")
        self.assertEqual(_marital("W"), "WIDOWED")

    def test_an_abbreviated_family_that_agrees_raises_nothing(self):
        from rules.flags import check_family_consistency
        annex = [("Zalikha", "DST", "M", 30, "ANNEX_A"),
                 ("Hamida Bibi", "DGT", "M", 30, "ANNEX_A")]
        frc = [("Zulikha", "Sister", "Married", 44, "NADRA_FRC"),
               ("Hamida Bibi", "Sister", "Married", 44, "NADRA_FRC")]
        self.assertEqual(
            [f.title for f in check_family_consistency(_record(annex, frc), _pack())
             if f.severity == "HIGH"], [])

    def test_a_real_marital_contradiction_survives_the_abbreviation(self):
        """The claimant declares herself married on Annex-A; NADRA says unmarried."""
        from rules.flags import check_family_consistency
        annex = [("Nafisa Bibi", "DST", "M", 30, "ANNEX_A"),
                 ("Zalikha", "DST", "M", 30, "ANNEX_A")]
        frc = [("Nafisa Bibi", "Sister", "Unmarried", 44, "NADRA_FRC"),
               ("Zulikha", "Sister", "Married", 44, "NADRA_FRC")]
        high = [f for f in check_family_consistency(_record(annex, frc), _pack())
                if f.severity == "HIGH"]
        self.assertEqual([f.title for f in high],
                         ["Annex-A contradicts NADRA FRC for Nafisa Bibi"])


class TheFrcNamesAMarriedCouple(unittest.TestCase):
    """FRC-03/04/05: the Father and Mother rows of a child-headed FRC are man and wife."""

    def _frc(self, rows):
        return _family(rows)

    def test_one_father_and_one_mother_are_the_couple(self):
        from rules.flags import frc_spouse_pair
        pair = frc_spouse_pair(self._frc([
            ("Akbar Hussain", "Father", "Married", 7, "NADRA_FRC"),
            ("Ghulam Zainab", "Mother", "Widowed", 7, "NADRA_FRC"),
            ("Amna Batool", "Sister", "Married", 7, "NADRA_FRC"),
        ]))
        self.assertIsNotNone(pair)
        self.assertEqual((pair[0].name, pair[1].name), ("Akbar Hussain", "Ghulam Zainab"))

    def test_the_same_woman_listed_four_times_is_still_one_mother(self):
        from rules.flags import frc_spouse_pair
        pair = frc_spouse_pair(self._frc([
            ("Muhammad Bashir", "Father", "Married", 7, "NADRA_FRC"),
            *[("Zohra Bibi", "Mother", "Married", 7, "NADRA_FRC")] * 4,
        ]))
        self.assertIsNotNone(pair)
        self.assertEqual(pair[1].name, "Zohra Bibi")

    def test_two_family_units_on_one_certificate_are_never_paired(self):
        """FRC-04: the unmarried-daughter bundle prints two fathers and two mothers."""
        from rules.flags import frc_spouse_pair
        self.assertIsNone(frc_spouse_pair(self._frc([
            ("Gul Janan", "Father", "Married", 44, "NADRA_FRC"),
            ("Gul Khan", "Father", "Married", 44, "NADRA_FRC"),
            ("Raheema", "Mother", "Married", 44, "NADRA_FRC"),
            ("Nawab Jan", "Mother", "Married", 44, "NADRA_FRC"),
        ])))

    def test_the_corroboration_is_stated_in_the_note(self):
        from rules.flags import LOW, check_family_consistency
        flags = check_family_consistency(_record(GHULAM_AYESHA_ANNEX, GHULAM_AYESHA_FRC),
                                         _pack())
        note = next(f for f in flags if f.severity == LOW)
        self.assertIn("FRC-03", note.finding)
        self.assertIn("Akbar Hussain", note.finding)
        self.assertIn("married to each other", note.finding)

    def test_two_mothers_against_one_father_raise_the_second_wife_question(self):
        from rules.flags import MEDIUM, check_more_than_one_widow
        rec = _record([], [])
        from dataclasses import replace
        rec = replace(rec, frc_family=self._frc([
            ("Muhammad Munir", "Father", "Married", 7, "NADRA_FRC"),
            ("Sughran Begum", "Mother", "Married", 7, "NADRA_FRC"),
            ("Hurmat Bibi", "Mother", "Married", 7, "NADRA_FRC"),
        ]))
        flags = check_more_than_one_widow(rec, _pack())
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].severity, MEDIUM)
        self.assertFalse(flags[0].blocks_ppo)      # noisy tables must not block a sound case
        self.assertTrue(flags[0].affects_determination)
        # Still the consequence that matters -- one widow or several changes what each is
        # paid -- said in words a claimant at the counter would follow.
        self.assertIn("split equally between them", flags[0].finding)
        # The authority is still shown to the officer, on the action line rather than in the
        # finding: the finding is what a claimant at the counter reads, and a rule number in
        # the middle of it is the thing that makes these unreadable (office, 22 Sep 2026).
        self.assertIn("4.10(1)", flags[0].required_action)

    def test_one_wife_raises_nothing(self):
        from dataclasses import replace
        from rules.flags import check_more_than_one_widow
        rec = replace(_record([], []), frc_family=self._frc([
            ("Muhammad Munir", "Father", "Married", 7, "NADRA_FRC"),
            ("Sughran Begum", "Mother", "Married", 7, "NADRA_FRC"),
        ]))
        self.assertEqual(check_more_than_one_widow(rec, _pack()), [])

    def test_it_is_in_the_battery(self):
        from rules.flags import BATTERY, check_more_than_one_widow
        self.assertIn(check_more_than_one_widow, BATTERY)


# ==============================================================================================
# BRAIN §8.3 makes the PPO/FPPO the authority on the pension in payment, and FAM-AR-01 computes
# a D-II pension "from the pension in payment as stated on the PPO/FPPO and Form D-II". Stage 4
# read only the form, so a bundle whose form was left blank -- with seven PPO pages in it --
# produced no figure at all.
# ==============================================================================================

class ThePpoIsTheAuthorityOnThePensionInPayment(unittest.TestCase):
    """§8.3 says the PPO governs the pension in payment; §8.4 says one source is not evidence."""

    def _determine(self, extracted):
        import tempfile
        from datetime import datetime
        from pathlib import Path as P
        from pipeline.extract import _determine_death_after_retirement
        from rules.dii import classify_case
        return _determine_death_after_retirement(
            P(tempfile.mkdtemp()), extracted, classify_case(prescribed_form="FORM_D_II"),
            datetime(2026, 9, 16))

    def _extracted(self, witnesses=(), **totals):
        base = {"fields": [
            {"name": "claimant_relation", "value": "widow", "confidence": 0.9,
             "page": 32, "document": "FORM_D_II", "unreadable_reason": None},
            {"name": "date_of_death_of_pensioner", "value": "2015-04-08", "confidence": 0.9,
             "page": 32, "document": "FORM_D_II", "unreadable_reason": None},
        ], "printed_totals": {"pension_drawn_rs": None, "net_pension_rs": None,
                              "total_pension_rs": None},
            "prescribed_form": "FORM_D_II", "prescribed_form_page": 32,
            "pension_witnesses": list(witnesses)}
        base["printed_totals"].update(totals)
        return base

    @staticmethod
    def _w(doc, page, monthly, gross=None):
        return {"document": doc, "page": page, "monthly_pension_rs": monthly,
                "gross_pension_rs": gross}

    def test_two_documents_that_agree_are_evidence(self):
        det = self._determine(self._extracted([
            self._w("PPO", 44, 19874), self._w("PENSION_SLIP", 55, 19874)]))["determination"]
        self.assertEqual(det["steps"][0]["amount"], 19874)
        self.assertTrue(any("corroborated by" in c for c in det["caveats"]))
        trail = {p["field"] for p in det["inputs"]["provenance"]}
        self.assertIn("pension_in_payment", trail)

    def test_one_document_alone_is_an_assertion_and_is_refused(self):
        from rules.dii import InputMissing
        with self.assertRaises(InputMissing) as ctx:
            self._determine(self._extracted([self._w("PPO", 44, 19874)]))
        self.assertIn("§8.4", str(ctx.exception))

    def test_the_form_can_be_the_second_witness(self):
        det = self._determine(self._extracted(
            [self._w("PPO", 44, 19874)], pension_drawn_rs=19874))["determination"]
        self.assertEqual(det["steps"][0]["amount"], 19874)
        self.assertTrue(any("corroborated by the prescribed form" in c
                            for c in det["caveats"]))

    def test_a_monthly_pension_larger_than_its_own_gross_is_never_used(self):
        """The real defect: PPO p.1 read Rs 710,214 monthly against Rs 47,584 gross, and a
        family pension of Rs 532,661 a month was computed for a constable's daughter."""
        from pipeline.extract import corroborated_pension
        amount, note, rejected = corroborated_pension(
            [self._w("PPO", 1, 710_214, 47_584), self._w("PPO", 44, 710_214, 47_584)])
        self.assertIsNone(amount)
        self.assertIn("710,214", rejected)
        self.assertIn("47,584", rejected)

    def test_a_figure_that_is_not_a_monthly_pension_is_rejected(self):
        from pipeline.extract import corroborated_pension
        for absurd in (12, 9_000_000):
            amount, _n, rejected = corroborated_pension(
                [self._w("PPO", 1, absurd), self._w("PPO", 2, absurd)])
            self.assertIsNone(amount, absurd)
            self.assertIn("not a monthly pension", rejected)

    def test_documents_that_disagree_are_named_and_none_is_chosen(self):
        from pipeline.extract import corroborated_pension
        amount, _n, rejected = corroborated_pension(
            [self._w("PPO", 44, 19_874), self._w("PENSION_SLIP", 55, 21_000)])
        self.assertIsNone(amount)
        self.assertIn("do not agree with each other", rejected)
        self.assertIn("PPO p.44", rejected)

    def test_where_both_speak_and_differ_the_ppo_governs_and_it_is_said(self):
        det = self._determine(self._extracted(
            [self._w("PPO", 44, 19874), self._w("PENSION_SLIP", 55, 19874)],
            pension_drawn_rs=18000))["determination"]
        self.assertEqual(det["inputs"]["sanctioned_pension"], 19874)
        self.assertTrue(any("authority on the pension in payment" in c
                            for c in det["caveats"]))

    def test_the_refusal_names_the_pages_not_the_absence(self):
        from rules.dii import InputMissing
        with self.assertRaises(InputMissing) as ctx:
            self._determine(self._extracted([self._w("PPO", 1, 710_214, 47_584)]))
        message = str(ctx.exception)
        self.assertIn("PPO p.1", message)
        self.assertIn("officer must read the PPO", message)

    def test_neither_source_still_refuses_by_name(self):
        from rules.dii import InputMissing
        with self.assertRaises(InputMissing):
            self._determine(self._extracted())

    def test_the_ppo_schema_is_registered(self):
        from extraction.schemas import SCHEMAS
        self.assertIn("PPO", SCHEMAS)
        self.assertIn("monthly_pension_rs", SCHEMAS["PPO"]["properties"])


class TheRelationClauseAsRealFormsWriteIt(unittest.TestCase):
    """Real D-II forms print "um daughters", "wd daughter", "daughters" -- not the textbook
    wording. A clause that matched nothing left the case with no checklist and no verdict."""

    def _v(self, relation, marital=""):
        from rules import suggest_variant
        from rules.case_type import FAMILY_PENSION_DEATH_AFTER_RETIREMENT
        return suggest_variant(FAMILY_PENSION_DEATH_AFTER_RETIREMENT, "",
                               claimant_relation=relation, claimant_marital=marital)

    def test_the_clause_can_state_the_marital_status_itself(self):
        self.assertEqual(self._v("um daughters").variant, "UNMARRIED_CHILD")
        self.assertEqual(self._v("wd daughter").variant, "WD_DAUGHTER")

    def test_a_plural_is_still_a_daughter(self):
        got = self._v("daughters")
        self.assertIsNone(got.variant)
        self.assertEqual(list(got.candidates),
                         ["UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER"])

    def test_the_clause_beats_a_marital_column_that_disagrees(self):
        self.assertEqual(self._v("um daughters", "Married").variant, "UNMARRIED_CHILD")


if __name__ == "__main__":
    unittest.main()
