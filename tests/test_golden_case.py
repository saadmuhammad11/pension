"""The golden test. BRAIN §13.8, BUILD §12.1.

The twelve assertions in BRAIN §13.8 are the acceptance criteria for the family-pension path.
All twelve live here from the start, including the five that cannot pass yet -- BUILD §13
Phase 0 exits when "the golden-test harness runs and fails informatively", and a suite that
only contains the tests already passing cannot tell you what is left to build.

The five not-yet-buildable assertions fail with a message naming the missing component rather
than erroring on an import. Read the failure list as the Phase 1 worklist.

Run:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
from pathlib import Path

# So the file runs directly as well as under `-m unittest` from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest
from unittest import mock
from datetime import datetime
from decimal import Decimal

from rules import (
    Source,
    FamilyMember,
    AmbiguityCollapseError,
    CaseRecord,
    DeathInServiceCase,
    classify_case_type,
    MoneyError,
    UnknownReferenceValue,
    determine_family_pension_death_in_service,
    money,
    notify,
    reckon,
    recommend,
    rupees,
    run_battery,
    run_checklist,
    select_pack,
)

# Absolute, not relative: the ROOT shim above puts the project on sys.path, so this
# form works both under `-m unittest` and when the file is run directly.
from tests import golden_case as g

#: Fixed, not date.today(). BUILD §6.2 requirement 1: no system clock in the computation.
#: The determination must be byte-identical whenever the suite is run.
COMPUTED_AT = datetime(2026, 6, 3, 10, 0, 0)


def build_case():
    """The full deterministic pipeline over the golden case: emoluments -> checklist ->
    flags -> determination -> verdict. Each stage consumes the previous one's output, which
    is what makes assertion 10 a real test rather than a restatement of assertion 5."""
    pack = select_pack(effective_date=g.DATE_OF_DEATH)
    emol = reckon(g.PAY_COMPONENTS, pack, printed_total=g.PRINTED_TOTAL_PAY)
    record = g.build_case_record(emol)
    checklist = run_checklist(record)
    flags = run_battery(record, pack)
    _, determination = build_determination()
    return record, checklist, flags, determination, recommend(checklist, flags, determination)


def build_determination():
    pack = select_pack(effective_date=g.DATE_OF_DEATH)
    emol = reckon(g.PAY_COMPONENTS, pack, printed_total=g.PRINTED_TOTAL_PAY)
    case = DeathInServiceCase(
        case_ref=g.CASE_REF,
        date_of_birth=g.DATE_OF_BIRTH,
        date_of_first_entry=g.DATE_OF_FIRST_ENTRY,
        date_of_death=g.DATE_OF_DEATH,
        emoluments=emol,
        bps=g.BPS,
        stated_qualifying_service=g.STATED_QUALIFYING_SERVICE,
        notional_superannuation=g.NOTIONAL_SUPERANNUATION,
        eol_days=g.EOL_DAYS,
    )
    return emol, determine_family_pension_death_in_service(case, pack, COMPUTED_AT)


def not_built(component: str, assertion: str, needs: str) -> str:
    return (
        f"NOT BUILT YET - {component}.\n"
        f"    §13.8 assertion: {assertion}\n"
        f"    needs: {needs}"
    )


class GoldenCase(unittest.TestCase):
    """The twelve regression assertions, in order."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.emol, cls.det = build_determination()
        cls.record, cls.checklist, cls.flags, _, cls.recommendation = build_case()
        cls.case_type = classify_case_type(cls.record)

    # -- 1 ---------------------------------------------------------------------------------
    def test_01_case_type_classified(self):
        """FAMILY_PENSION_DEATH_IN_SERVICE with confidence >= 0.95."""
        ct = self.case_type
        self.assertEqual(ct.case_type, g.EXPECTED_CASE_TYPE)
        self.assertGreaterEqual(ct.confidence, 0.95)
        self.assertEqual(ct.prescribed_form, "D-I")
        self.assertFalse(ct.needs_human)
        self.assertEqual(ct.contradictions, ())
        # §4.1 rule 1: the evidence must be the form, not the narrative.
        self.assertIn("Form D-I", ct.evidence)

    def test_01a_b_iv_is_never_guessed_between_two_paths(self):
        """§4.1 rules 4 and 6: Form B-IV governs two paths with different bases.

        Invalid pension rests on a Category-A medical board; compulsory retirement is a
        penalty. With neither document present the classifier must route to a human rather
        than pick one.
        """
        from rules import Document

        bare = CaseRecord(
            case_ref="X", case_type="",
            documents=(Document("FORM_B_IV", (1,), signatory_is_psa=True),),
        )
        r = classify_case_type(bare)
        self.assertIsNone(r.case_type)
        self.assertTrue(r.needs_human)
        self.assertEqual(r.route, "ROUTE_MANUAL")
        self.assertEqual(
            set(r.alternatives), {"INVALID_PENSION", "COMPULSORY_RETIREMENT_PENSION"}
        )

        with_medical = CaseRecord(
            case_ref="X", case_type="",
            documents=(
                Document("FORM_B_IV", (1,), signatory_is_psa=True),
                Document("MEDICAL_BOARD_CERTIFICATE", (5,)),
            ),
        )
        self.assertEqual(classify_case_type(with_medical).case_type, "INVALID_PENSION")

    def test_01b_absent_form_is_a_defect_not_a_reclassification(self):
        """§4.1 rule 2. An inferred type stays below the accept threshold and says why."""
        from rules import Document

        no_form = CaseRecord(
            case_ref="X", case_type="",
            documents=(Document("NADRA_DEATH_CERTIFICATE", (3,)),),
        )
        r = classify_case_type(no_form)
        self.assertEqual(r.case_type, g.EXPECTED_CASE_TYPE)
        self.assertLess(r.confidence, 0.95, "an inference without the form is not decisive")
        self.assertTrue(r.contradictions)
        self.assertIn("checklist defect", r.contradictions[0])

    def test_01c_two_prescribed_forms_route_to_a_human(self):
        """Only one path can govern a case."""
        from rules import Document

        both = CaseRecord(
            case_ref="X", case_type="",
            documents=(
                Document("FORM_D_I", (19,), signatory_is_psa=True),
                Document("FORM_B_I", (30,), signatory_is_psa=True),
            ),
        )
        r = classify_case_type(both)
        self.assertIsNone(r.case_type)
        self.assertEqual(r.route, "ROUTE_MANUAL")
        self.assertIn("More than one", r.contradictions[0])

    # -- 2 ---------------------------------------------------------------------------------
    def test_02_reckonable_total_reconciled(self):
        """192,030 extracted AND reconciled against the form's printed total."""
        self.assertEqual(rupees(self.emol.reckonable_total), g.EXPECTED_RECKONABLE_TOTAL)
        self.assertTrue(
            self.emol.reconciled,
            "the component sum must agree with the form's printed total - BRAIN §8.4 "
            "calls this the single highest-value arithmetic check in the system",
        )
        self.assertEqual(self.emol.discrepancy, 0)

    # -- 3 ---------------------------------------------------------------------------------
    def test_03_allowance_classes_excluded(self):
        """All four allowance classes excluded; excluded total 161,765."""
        self.assertEqual(rupees(self.emol.excluded_total), g.EXPECTED_EXCLUDED_TOTAL)
        self.assertEqual(len(self.emol.excluded), 4, "four allowance classes")
        self.assertEqual(self.emol.unknown, (), "no pay line may be left unclassified")
        for c in self.emol.reckonable:
            self.assertIn(c.component, ("basic_pay", "personal_pay"))

    # -- 4 ---------------------------------------------------------------------------------
    def test_04_checklist_complete(self):
        """COMPLETE, 16/16, with deputation challans NOT_APPLICABLE."""
        cl = self.checklist
        self.assertEqual(cl.result, "COMPLETE")
        self.assertEqual(cl.missing, 0, "invariant 4: COMPLETE only when missing == 0")
        self.assertEqual(cl.required, g.EXPECTED_CHECKLIST_TOTAL)
        self.assertEqual(cl.satisfied, g.EXPECTED_CHECKLIST_TOTAL)
        deputation = cl.item("CL-08")
        self.assertEqual(deputation.status, "NOT_APPLICABLE")
        self.assertTrue(
            deputation.reason,
            "§7.3 forbids NOT_APPLICABLE without a reason grounded in the case facts",
        )
        # §7.3 / §16 item 6: completeness must not imply correctness.
        self.assertIn("not absent papers", cl.result_line)

    # -- 5 ---------------------------------------------------------------------------------
    def test_05_seven_flags_with_severities(self):
        """All seven flags, correct severities and classes -- plus the relation finding (H6, 7 Oct 2026)."""
        self.assertEqual(len(self.flags), 8, "the seven flags of §13.5, and the relation-not-stated finding")
        actual = {f.id: (f.severity, f.flag_class, f.blocks_ppo) for f in self.flags}
        self.assertEqual(actual, g.EXPECTED_FLAGS)

    def test_05a_f3_undeclared_recovery_is_the_one_that_costs_money(self):
        """§13.8: missing F-3 is a critical failure. Assert its substance, not just its id."""
        f3 = next(f for f in self.flags if f.flag_class == "RULE-UNDECLARED")
        self.assertEqual(f3.id, "F-3")
        self.assertEqual(f3.severity, "HIGH")
        self.assertTrue(f3.blocks_ppo)
        self.assertIn("126,355", f3.title)
        self.assertTrue(f3.affects_determination)
        self.assertEqual(f3.owner, "DEPARTMENT")

    def test_05b_f2_annex_a_contradicts_frc(self):
        """§13.8: missing F-2 is a critical failure - the one an eye skips over.

        Entitlement is unaffected (ENT-07, spouse precedes children) and it is still HIGH,
        because Annex-A is the attested declaration the sanction rests on (§8.3).
        """
        f2 = next(f for f in self.flags if f.flag_class == "CONTRA-FAMILY")
        self.assertEqual(f2.id, "F-2")
        self.assertEqual(f2.severity, "HIGH")
        self.assertIn("Usman Waqar", f2.title)
        self.assertIn("son", f2.finding)
        self.assertFalse(
            f2.affects_determination, "the spouse precedes children (ENT-07)"
        )
        self.assertIn("re-attestation", f2.required_action)

    def test_05c_precedence_not_majority_decides_f1(self):
        """F-1 resolves by §8.3 authority, not by counting documents.

        Flipping the count so the wrong value is asserted by more documents must not change
        which value the battery calls operative: the payroll chain still governs.
        """
        f1 = next(f for f in self.flags if f.flag_class == "CONTRA-IDENTITY")
        self.assertIn("90000857 vs 90000853", f1.title)

        from rules import Assertion, Source

        stuffed = tuple(
            a for a in self.record.assertions if a.field != "personnel_no"
        ) + (
            Assertion("personnel_no", "90000853", Source(6, "LPC")),
            Assertion("personnel_no", "90000857", Source(2, "FILE_COVER")),
            Assertion("personnel_no", "90000857", Source(19, "FORM_D_I")),
            Assertion("personnel_no", "90000857", Source(50, "DEPT_NOTE")),
            Assertion("personnel_no", "90000857", Source(51, "DEPT_NOTE")),
            Assertion("personnel_no", "90000857", Source(52, "DEPT_NOTE")),
        )
        record = CaseRecord(
            case_ref=self.record.case_ref,
            case_type=self.record.case_type,
            assertions=stuffed,
        )
        pack = select_pack(effective_date=g.DATE_OF_DEATH)
        flag = run_battery(record, pack)[0]
        self.assertIn(
            "90000857 vs 90000853",
            flag.title,
            "five restatements must still lose to one LPC - a restatement repeated is "
            "still a restatement (§8.3)",
        )

    # -- 6 ---------------------------------------------------------------------------------
    def test_06_gross_pension(self):
        """CALC-01: 192,030 x 30 x 7 / 300 = 134,421 exactly."""
        self.assertEqual(self.det.amount("CALC-01"), g.EXPECTED_GROSS_PENSION)

    # -- 7 ---------------------------------------------------------------------------------
    def test_07_family_pension_half_up(self):
        """FAM-IS-03 with FMT-01: 100,815.75 rounds half-up to 100,816."""
        self.assertEqual(self.det.amount("FAM-IS-03"), g.EXPECTED_FAMILY_PENSION)
        step = self.det.step("FAM-IS-03")
        self.assertTrue(step.rounded, "FMT-03 requires the engine to state where it rounded")
        self.assertIn("100815.75", step.to_dict()["exact_before_rounding"])

    # -- 8 ---------------------------------------------------------------------------------
    def test_08_gratuity_two_readings_never_one(self):
        """BLOCKING-06: two labelled readings, and no way to collapse them."""
        amb = self.det.ambiguity("FAM-IS-04")
        self.assertEqual(amb.blocking_id, "BLOCKING-06")
        self.assertEqual(len(amb.readings), 2)
        self.assertEqual(
            amb.reading("literal").presented, g.EXPECTED_GRATUITY_LITERAL
        )
        self.assertEqual(
            amb.reading("capitalised").presented, g.EXPECTED_GRATUITY_CAPITALISED
        )
        # The difference must be stated, not merely implied by printing two numbers.
        self.assertIn("148.5x", amb.spread_statement())
        # And the engine must refuse to produce a single figure.
        with self.assertRaises(AmbiguityCollapseError):
            self.det.amount("FAM-IS-04")
        with self.assertRaises(AmbiguityCollapseError):
            int(amb)

    # -- 9 ---------------------------------------------------------------------------------
    def test_09_medical_allowance_base_stated(self):
        """BLOCKING-03: emitted with its base stated, both readings present."""
        amb = self.det.ambiguity("ADD-02")
        self.assertEqual(amb.blocking_id, "BLOCKING-03")
        self.assertEqual(
            amb.reading("on_family_pension").presented, g.EXPECTED_MEDICAL_ON_FAMILY_PENSION
        )
        self.assertEqual(
            amb.reading("on_gross_pension").presented, g.EXPECTED_MEDICAL_ON_GROSS_PENSION
        )
        for r in amb.readings:
            self.assertIn("BPS 16+", r.basis, "the rate band must be stated")

    # -- 10 --------------------------------------------------------------------------------
    def test_10_verdict_return_for_correction(self):
        """RETURN_FOR_CORRECTION with blocking flags [F-1, F-2, F-3]."""
        rec = self.recommendation
        self.assertEqual(rec.verdict, g.EXPECTED_VERDICT)
        self.assertEqual(list(rec.blocking_flags), g.EXPECTED_BLOCKING_FLAGS)
        self.assertTrue(rec.human_decision_required, "the officer decides, every time")
        # The rationale must show both dimensions: complete checklist, defective data.
        self.assertIn("Checklist complete", rec.rationale)
        self.assertIn("HIGH flag", rec.rationale)

    def test_10a_high_flag_can_never_yield_forward(self):
        """§6.1 invariant 5: a blocks_ppo flag forces RETURN_FOR_CORRECTION or HOLD."""
        _, checklist, flags, det, _ = build_case()
        self.assertTrue(any(f.blocks_ppo for f in flags))
        self.assertNotEqual(recommend(checklist, flags, det).verdict, "FORWARD")

    # -- 11 --------------------------------------------------------------------------------
    def test_11_unverified_rules_engaged(self):
        """The determination names every BLOCKING item it touches, and is provisional."""
        for item in g.EXPECTED_BLOCKING_ENGAGED:
            self.assertIn(
                item,
                self.det.unverified_engaged,
                f"{item} is engaged by this case and must be named (BRAIN §14.1 rule 2)",
            )
        self.assertTrue(
            self.det.provisional,
            "a determination engaging an open BLOCKING item is provisional on its face",
        )

    # -- 12 --------------------------------------------------------------------------------
    def test_12_claimant_notification_bilingual(self):
        """Bilingual, and states that no action is required."""
        _, claimant = notify(self.record, self.checklist, self.flags, self.recommendation)
        self.assertTrue(claimant.bilingual, "§12.2 requires Urdu and English")
        self.assertFalse(
            claimant.requires_recipient_action,
            "every defect on this case is the department's; the claimant must not be asked "
            "to act on it (§15.3)",
        )
        self.assertIn("No action is required from you", claimant.body_en)
        self.assertIn("ضرورت نہیں", claimant.body_ur)
        self.assertIn("Three corrections are needed", claimant.body_en)
        self.assertIn("41759", claimant.body_en)
        self.assertIn("41759", claimant.body_ur)

    def test_12a_claimant_message_carries_no_jargon(self):
        """§12.2: plain language - no rule citations, no form numbers, no flag ids."""
        _, claimant = notify(self.record, self.checklist, self.flags, self.recommendation)
        for jargon in ("F-1", "F-2", "F-3", "BLOCKING", "Annex-A", "D-I", "§",
                       "CALC-", "FAM-IS-", "PPO", "Rs."):
            self.assertNotIn(jargon, claimant.body_en, f"{jargon!r} is jargon to a claimant")

    def test_12b_department_letter_is_itemised_and_actionable(self):
        """§12.2: what is wrong, where, and what to do - for each defect."""
        dept, _ = notify(self.record, self.checklist, self.flags, self.recommendation)
        self.assertTrue(dept.requires_recipient_action)
        for flag_id in g.EXPECTED_BLOCKING_FLAGS:
            self.assertIn(f"[{flag_id}]", dept.body_en)
        self.assertIn("Action  :", dept.body_en)
        self.assertIn("Where   :", dept.body_en)
        # A cap the AG applies and an SLA breach are not the department's to "correct".
        self.assertNotIn("[F-4]", dept.body_en)
        self.assertNotIn("[F-5]", dept.body_en)

    def test_12c_missing_document_asks_for_a_document_not_a_correction(self):
        """§7.3: MISSING and DEFECTIVE generate different letters.

        Drop the death certificate and the SOP class must change from CASE_RETURNED to
        ADDITIONAL_DOCUMENTS_REQUIRED - the department is being asked to send something,
        not to fix something.
        """
        from rules import run_checklist

        emol = self.emol
        full = g.build_case_record(emol)
        stripped = CaseRecord(
            case_ref=full.case_ref,
            case_type=full.case_type,
            assertions=full.assertions,
            documents=tuple(
                d for d in full.documents if d.type != "NADRA_DEATH_CERTIFICATE"
            ),
            annex_a_family=full.annex_a_family,
            frc_family=full.frc_family,
            recoveries=full.recoveries,
            timeline=full.timeline,
            aliases=full.aliases,
            emoluments=emol,
            stated_qualifying_service_years=32,
            diary_no=full.diary_no,
            forwarding_department=full.forwarding_department,
        )
        checklist = run_checklist(stripped)
        self.assertEqual(checklist.missing, 1)
        self.assertEqual(checklist.result, "INCOMPLETE")
        dept, _ = notify(stripped, checklist, self.flags, self.recommendation)
        self.assertEqual(dept.notification_class, "ADDITIONAL_DOCUMENTS_REQUIRED")
        self.assertIn("Documents not located", dept.body_en)


class DocumentBoundaries(unittest.TestCase):
    """BRAIN §5: page order does not imply document boundaries."""

    def test_twelve_certificates_do_not_merge_into_one_document(self):
        """pp.24-36 of the golden case are twelve separate NDCs, not one 13-page document.

        Grouping on document type alone would merge them and lose the count; each page
        declaring itself a first page is what keeps them apart.
        """
        from extraction.identify import PageIdentity, assemble_documents

        pages = [
            PageIdentity(p, "NDC", 0.96, "No Demand Certificate", is_first_page=True)
            for p in range(24, 37)
        ]
        docs = assemble_documents(pages)
        self.assertEqual(len(docs), 13)
        self.assertTrue(all(d.type == "NDC" for d in docs))

    def test_a_document_spanning_two_pages_stays_one_document(self):
        from extraction.identify import PageIdentity, assemble_documents

        pages = [
            PageIdentity(19, "FORM_D_I", 0.97, "Form D-I", is_first_page=True,
                         signed_by_psa=True),
            PageIdentity(20, "FORM_D_I", 0.95, "continuation", is_first_page=False),
        ]
        docs = assemble_documents(pages)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].pages, (19, 20))
        self.assertTrue(docs[0].signatory_is_psa)

    def test_unidentified_pages_never_become_documents(self):
        """An OTHER page must not satisfy a checklist requirement."""
        from extraction.identify import PageIdentity, assemble_documents, low_confidence_pages

        pages = [
            PageIdentity(1, "OTHER", 0.4, "illegible", is_first_page=True),
            PageIdentity(2, "LPC", 0.93, "Last Pay Certificate", is_first_page=True),
        ]
        docs = assemble_documents(pages)
        self.assertEqual([d.type for d in docs], ["LPC"])
        self.assertEqual([p.page for p in low_confidence_pages(pages)], [1])


class Reproducibility(unittest.TestCase):
    """BUILD §6.2 requirement 1: same inputs and pack, byte-identical output, forever."""

    def test_determination_is_deterministic(self):
        _, a = build_determination()
        _, b = build_determination()
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_pack_is_recorded_on_the_determination(self):
        _, det = build_determination()
        self.assertEqual(det.rule_pack_id, "PB-2026.02")   # the pack in force in 2021


class MoneyDiscipline(unittest.TestCase):
    """FMT-01, FMT-02."""

    def test_float_is_refused_as_money(self):
        with self.assertRaises(MoneyError):
            money(100815.75)

    def test_half_up_not_bankers_rounding(self):
        # Python's round() would give 100814 for the second of these.
        self.assertEqual(rupees("100815.5"), 100816)
        self.assertEqual(rupees("100814.5"), 100815)


class AuditString(unittest.TestCase):
    """BUILD §6.2 requirement 3: every step shows its work, and the work must be right.

    Regression for a bug that rendered ``178440 + 13590 = 192030`` as
    ``17844 + 1359 = 192030``: the components were formatted by stripping trailing zeros,
    which removed the significant ones too. The *result* stayed correct, so nothing failed --
    only the audit record was wrong, which is the half an auditor actually reads.
    """

    def test_components_render_with_their_trailing_zeros(self):
        emol, _ = build_determination()
        self.assertEqual(emol.computation_shown, "178440 + 13590 = 192030")

    def test_every_step_states_a_computation(self):
        _, det = build_determination()
        for step in det.steps:
            self.assertTrue(
                step.computation_shown.strip(),
                f"{step.rule_id} presents a figure with no working shown",
            )

    def test_every_reading_states_a_computation_and_a_basis(self):
        _, det = build_determination()
        for amb in det.ambiguities:
            for r in amb.readings:
                self.assertTrue(r.computation_shown.strip(), f"{amb.rule_id}/{r.label}")
                self.assertTrue(r.basis.strip(), f"{amb.rule_id}/{r.label}")


class DisputedComponents(unittest.TestCase):
    """BLOCKING-18: orderly allowance is neither summed nor silently dropped."""

    def setUp(self):
        self.pack = select_pack(effective_date=g.DATE_OF_DEATH)

    def test_orderly_allowance_is_not_in_the_reckonable_set(self):
        self.assertNotIn("orderly_allowance", self.pack.ref("reckonable_components"))
        self.assertIn("orderly_allowance", self.pack.ref("reckonable_disputed"))

    def test_a_case_carrying_one_routes_to_human_rather_than_summing_it(self):
        """Neither reading may be applied silently.

        Summing it overstates a pension for life; excluding it understates one. The engine
        refuses to determine at all, which is BRAIN §15.1: never resolve a BLOCKING item by
        reasoning.
        """
        from rules import PayComponent

        with_orderly = [
            *g.PAY_COMPONENTS,
            PayComponent("Orderly Allowance", "orderly_allowance", 9_000, page=41),
        ]
        emol = reckon(with_orderly, self.pack, printed_total=g.PRINTED_TOTAL_PAY)
        self.assertTrue(emol.needs_human)
        self.assertIn("orderly_allowance", [c.component for c in emol.unknown])
        self.assertNotIn(9_000, [int(c.amount) for c in emol.reckonable])
        self.assertNotIn(9_000, [int(c.amount) for c in emol.excluded])
        self.assertIn("BLOCKING-18", emol.finding())

    def test_the_golden_case_is_unaffected(self):
        """The real case prints the orderly-allowance field blank, so nothing changes."""
        emol = reckon(g.PAY_COMPONENTS, self.pack, printed_total=g.PRINTED_TOTAL_PAY)
        self.assertFalse(emol.needs_human)
        self.assertEqual(rupees(emol.reckonable_total), g.EXPECTED_RECKONABLE_TOTAL)


class ReferenceDataDiscipline(unittest.TestCase):
    """BUILD §6.2 requirement 7: unknown inputs raise; they do not default."""

    def test_commutation_factor_is_never_interpolated(self):
        pack = select_pack(effective_date=g.DATE_OF_DEATH)
        self.assertEqual(pack.age_factor(60), money("12.3719"))
        with self.assertRaises(UnknownReferenceValue) as ctx:
            pack.age_factor(65)  # between 60 and 70 - the tempting one
        self.assertIn("Interpolation is not permitted", str(ctx.exception))

    def test_unresolved_reference_value_raises_rather_than_defaulting(self):
        pack = select_pack(effective_date=g.DATE_OF_DEATH)
        # BLOCKING-02: the minimum-pension floors are not loaded. "Unknown" must not read
        # as "zero", which would silently pass every case through a floor check.
        with self.assertRaises(UnknownReferenceValue):
            pack.ref("minimum_pension", "family_pension")


class RecoveryParsing(unittest.TestCase):
    """F-3's rupees. Two separate bugs put the wrong number on a HIGH flag."""

    #: The sentence PaddleOCR returns from LPC p.29, verbatim.
    LPC_SENTENCE = (
        "ROP of Pay & Allow. w.e.f. 19.02.2026 to 28.02.2026 (10 days) amounting to "
        "Rs. 126,355 is recoverable."
    )

    def test_a_date_in_the_sentence_is_not_the_amount(self):
        """The first number in the sentence is 19.02 -- a date, not Rs. 19."""
        from pipeline.extract import money_in_text
        self.assertEqual(money_in_text(self.LPC_SENTENCE), Decimal("126355"))

    def test_a_decimal_amount_keeps_its_decimal_point(self):
        """Stripping non-digits read 220,941.56 as 22,094,156 -- wrong by a factor of 100.

        On a figure that is subtracted from a gratuity.
        """
        from pipeline.extract import money_in_text
        self.assertEqual(money_in_text("Recoverable: 220,941.56"), Decimal("220941.56"))

    def test_a_denial_yields_no_figure(self):
        """The sanction form's denial must parse as *absent*, which is what F-3 keys on."""
        from pipeline.extract import money_in_text
        for denial in ("No", "Nil", "amounting to Rs. .....", ""):
            self.assertIsNone(money_in_text(denial), denial)

    def test_the_ocr_pass_finds_the_recovery_in_the_page_text(self):
        from extraction.ocr import PageText, recoveries_in
        found = recoveries_in(PageText(page=29, text=self.LPC_SENTENCE, model="test"))
        self.assertEqual([r["amount"] for r in found], [126355])

    def test_a_bare_figure_without_a_recovery_word_is_not_a_recovery(self):
        """A number on an LPC is far more likely to be pay than a demand."""
        from extraction.ocr import PageText, recoveries_in
        found = recoveries_in(PageText(page=7, text="Basic Pay 178,440", model="test"))
        self.assertEqual(found, [])


class AbsentFactsStayAbsent(unittest.TestCase):
    """A required field over a fact the page does not carry obtains an invention."""

    def test_form_d_i_does_not_ask_for_a_psa_signature_date(self):
        """Form D-I's signature block is undated.

        Asking for the date anyway returned 2021-07-26 at high confidence -- a date on no
        page in the bundle, three days before the date of death -- and the 15-day SLA was
        then computed from it. The field is gone; the SLA runs on printed dates instead.
        """
        from extraction.schemas import FORM_D_I
        self.assertNotIn("psa_signature_date", FORM_D_I["properties"])
        self.assertNotIn("psa_signature_date", FORM_D_I["required"])


class PartyRoles(unittest.TestCase):
    """Which name is the deceased is decided from the page, not from the model's label."""

    def test_a_swapped_extraction_is_corrected_from_the_late_marker(self):
        from rules.case_type import resolve_parties
        p = resolve_parties("MR/MST. WAQAR ABDUL BASIT",
                            "MR/MST. NARGAS WAQAR (LATE)")
        self.assertIn("NARGAS", p.deceased)
        self.assertIn("WAQAR ABDUL BASIT", p.claimant)
        self.assertTrue(p.corrected)
        self.assertIsNone(p.unresolved_reason)

    def test_a_correct_extraction_is_left_alone(self):
        from rules.case_type import resolve_parties
        p = resolve_parties("MST. NARGAS WAQAR (LATE)", "MR. WAQAR ABDUL BASIT")
        self.assertIn("NARGAS", p.deceased)
        self.assertFalse(p.corrected)

    def test_the_death_certificate_outranks_the_late_marker(self):
        """NADRA is authoritative on who died (§8.3)."""
        from rules.case_type import resolve_parties
        p = resolve_parties("ALPHA BETA (LATE)", "GAMMA DELTA",
                            death_certificate_names=("Gamma Delta",))
        self.assertEqual(p.deceased, "GAMMA DELTA")
        self.assertTrue(p.corrected)

    def test_ambiguity_is_reported_rather_than_guessed(self):
        from rules.case_type import resolve_parties
        p = resolve_parties("ALPHA BETA", "GAMMA DELTA")
        self.assertIsNotNone(p.unresolved_reason)
        self.assertFalse(p.corrected)

    def test_the_swap_reaches_the_report_as_a_finding(self):
        """Corrected silently, one misread name becomes a letter to the wrong person."""
        from rules import CaseRecord, run_battery, select_pack
        rec = CaseRecord(case_ref="t", case_type="FAMILY_PENSION_DEATH_IN_SERVICE",
                         party_roles_corrected=True)
        classes = {f.flag_class for f in run_battery(rec, select_pack(
            effective_date=g.NOTIONAL_SUPERANNUATION))}
        self.assertIn("EXTRACT-ROLE-SWAP", classes)


class SubstitutedCnicCard(unittest.TestCase):
    """A CNIC copy belonging to someone else must not pass as "CNIC present".

    Swapping one page of a real bundle for a stranger's CNIC produced no finding at all.
    The check that should have caught it was in the battery the whole time; the card was
    simply never read, because CNIC document types had been left out of the identifier
    sweep while CNIC verification was parked.
    """

    def _pack(self):
        from rules import select_pack
        return select_pack(effective_date=g.NOTIONAL_SUPERANNUATION)

    def _record(self, card_number: str, quoted_elsewhere: str):
        from rules.caserecord import Assertion, CaseRecord, Document, Source
        return CaseRecord(
            case_ref="t", case_type="SUPERANNUATION_PENSION",
            documents=(Document(type="CNIC", pages=(5,), person_named="A Person"),
                       Document(type="BANK_OPTION_FORM", pages=(13,))),
            assertions=(
                Assertion(field="cnic", value=card_number, source=Source(5, "CNIC"),
                          person="A Person"),
                Assertion(field="cnic", value=quoted_elsewhere,
                          source=Source(13, "BANK_OPTION_FORM"), person="A Person"),
            ),
        )

    def test_a_card_quoted_nowhere_else_is_flagged(self):
        from rules.flags import check_cnic_cards_belong_to_the_case
        flags = check_cnic_cards_belong_to_the_case(
            self._record("0000100001118", "0000100001140"), self._pack())
        self.assertEqual([f.flag_class for f in flags], ["CNIC-UNCORROBORATED"])
        self.assertEqual(flags[0].severity, "HIGH")

    def test_a_card_the_bundle_quotes_is_not_flagged(self):
        from rules.flags import check_cnic_cards_belong_to_the_case
        self.assertEqual(check_cnic_cards_belong_to_the_case(
            self._record("0000100001118", "0000100001118"), self._pack()), [])

    def test_the_cnic_card_is_read_for_identifiers(self):
        """The check keys on the card's own number, so the card has to be swept."""
        from pipeline.extract import _IDENTIFIER_DOCS
        self.assertIn("CNIC", _IDENTIFIER_DOCS)

    def test_a_card_records_one_holder_not_two(self):
        """The card at p.5 returned its one number twice: holder, and the husband whose
        name is printed beside hers. He has his own card with his own number, and the
        identity check groups by person -- so his real number would contradict hers."""
        from pipeline.extract import one_holder_per_card
        kept = one_holder_per_card([
            {"field": "cnic", "value": "0000100001118", "person": "A Person",
             "role": "Holder", "page": 5, "document": "CNIC"},
            {"field": "cnic", "value": "0000100001118", "person": "Another Person",
             "role": "Spouse", "page": 5, "document": "CNIC"},
        ])
        self.assertEqual([(e["person"], e["role"]) for e in kept], [("A Person", "Holder")])

    def test_an_unattributable_card_number_is_kept_without_a_person(self):
        """Enough to corroborate the card, not enough to accuse anyone. Guessing here
        files a widow's card under the deceased."""
        from pipeline.extract import one_holder_per_card
        kept = one_holder_per_card([
            {"field": "cnic", "value": "0000100001118", "person": "A Person",
             "role": None, "page": 5, "document": "CNIC"},
            {"field": "cnic", "value": "0000100001118", "person": "Another Person",
             "role": None, "page": 5, "document": "CNIC"},
        ])
        self.assertEqual(len(kept), 1)
        self.assertIsNone(kept[0]["person"])
        self.assertEqual(kept[0]["value"], "0000100001118")

    def test_two_real_numbers_on_one_page_both_survive(self):
        """The rule is one number per card, not one entry per page."""
        from pipeline.extract import one_holder_per_card
        kept = one_holder_per_card([
            {"field": "cnic", "value": "0000100001118", "person": "A Person",
             "role": "Holder", "page": 5, "document": "CNIC"},
            {"field": "cnic", "value": "0000100001140", "person": "Another Person",
             "role": "Spouse", "page": 5, "document": "CNIC"},
        ])
        self.assertEqual(len(kept), 2)

    def test_a_padded_cnic_never_reaches_the_record(self):
        """Told a CNIC is exactly 13 digits, the model padded what it could read with
        zeros. Such a number appears on several pages, so it clears the corroboration
        guard and then contradicts the number that is real."""
        from pipeline.extract import looks_fabricated
        for padded in ("3520300000000", "3802140000000", "3520200000000", "1111111111111"):
            self.assertTrue(looks_fabricated(padded), padded)
        for real in ("0000100001118", "0000100001380", "0000100001140"):
            self.assertFalse(looks_fabricated(real), real)


class NoCaseLiteralsInProductionCode(unittest.TestCase):
    """The engine must not carry this case's particulars.

    ``build_report`` held four of them -- diary 41759, "the School Education Department",
    its Urdu rendering, and the claimant "Waqar Abdul Basit" -- in the middle of the
    production path, so a second bundle would have produced shortcoming letters naming this
    case's claimant and this case's department. This test walks the AST of every production
    module and inspects string and number literals that are NOT docstrings, so the
    explanatory comments and docstrings that cite the golden case stay legal while a value
    the code actually uses does not.
    """

    #: Directories that run in production. tests/ and verify.py are fixtures and expectations.
    PRODUCTION = ("rules", "extraction", "pipeline", "api")

    FORBIDDEN_TEXT = ("waqar", "nargas", "nargis", "abdul basit", "41759",
                      "90000857", "90000853", "school education", "mussarat",
                      "0aee822c760e")
    FORBIDDEN_NUMBERS = (41759, 90000857, 90000853, 126355, 192030, 161765, 134421)

    def _literals(self, tree):
        """Every Constant in the tree except docstrings."""
        import ast
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", None)
                if body and isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Constant) and \
                        isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and id(node) not in docstrings:
                yield node

    def test_no_production_module_hardcodes_a_case_particular(self):
        import ast
        root = Path(__file__).resolve().parent.parent
        offences = []
        for package in self.PRODUCTION:
            for path in sorted((root / package).rglob("*.py")):
                # Reference data, not a rule: the fixed list of Punjab departments has to
                # name the School Education Department to exist at all (api/departments.py).
                if path.name in ("departments.py", "themes.py"):
                    continue
                tree = ast.parse(path.read_text(), filename=str(path))
                for node in self._literals(tree):
                    v = node.value
                    if isinstance(v, str):
                        low = v.lower()
                        for needle in self.FORBIDDEN_TEXT:
                            # A bare "late"/"mst" pattern is legitimate; a full name is not.
                            if needle in low:
                                offences.append(
                                    f"{path.relative_to(root)}:{node.lineno} "
                                    f"string contains {needle!r}"
                                )
                    elif isinstance(v, int) and not isinstance(v, bool):
                        if v in self.FORBIDDEN_NUMBERS:
                            offences.append(
                                f"{path.relative_to(root)}:{node.lineno} number {v}"
                            )
        self.assertEqual(offences, [], "case particulars in production code:\n  "
                                       + "\n  ".join(offences))


class PrescribedFormNumbers(unittest.TestCase):
    """A form number is printed in Roman on some copies and in arabic on others."""

    def test_both_notations_are_recognised(self):
        """The FD blank-forms compendium prints "Form B-1"; departments print "FORM B-I".

        Matching only Roman meant OCR could not find the number on a genuine form, so the
        classification was withdrawn and a valid case went to manual review -- this check
        exists to catch a fabricated form claim, and it was rejecting real ones instead.
        """
        from extraction.ocr import PageText, forms_printed_on
        for text, expected in (
            ("Form B-1 Pension Form", ("FORM_B_I",)),
            ("FORM B-I Pension Form", ("FORM_B_I",)),
            ("Form D-1 FAMILY PENSION FORM", ("FORM_D_I",)),
            ("FORM D-II", ("FORM_D_II",)),
            ("Form B-4 PENSION FORM", ("FORM_B_IV",)),
            ("Form B-IV PENSION FORM", ("FORM_B_IV",)),
        ):
            self.assertEqual(forms_printed_on(PageText(1, text, "t")), expected, text)

    def test_a_page_with_no_form_number_still_reports_none(self):
        """The guard must stay strict: absence of a number is what denies a false claim."""
        from extraction.ocr import PageText, forms_printed_on
        self.assertEqual(forms_printed_on(PageText(1, "Descriptive Roll of family", "t")), ())


class ConditionalRequirements(unittest.TestCase):
    """Conditions printed inside a checklist line, not in its tick."""

    FRC = (
        FamilyMember("Nargis Waqqar", "Spouse", "Married", Source(28, "NADRA_FRC")),
        FamilyMember("Waqqar Abdul Basit", "Father", "Widowed", Source(28, "NADRA_FRC")),
        FamilyMember("Waqqar Abdul Basit", "Father", "Widowed", Source(28, "NADRA_FRC")),
    )

    # Item 22 (Nikah Nama "in case applicant not Shown in FRC") is a MEDIUM finding, not a
    # checklist line, since 24 Sep 2026 -- rules.flags.check_nikah_nama, on the same condition.
    def _nikah(self, claimant, frc, variant="DEATH_IN_SERVICE", documents=()):
        from rules.flags import check_nikah_nama
        rec = CaseRecord(case_ref="t", case_type="", frc_family=frc, claimant_name=claimant,
                         case_variant=variant, documents=documents)
        return check_nikah_nama(rec, None)

    def test_the_nikah_nama_is_no_longer_a_checklist_line(self):
        from rules import run_checklist
        rec = CaseRecord(case_ref="t", case_type="")
        ids = [i.id for i in run_checklist(rec, variant="DEATH_IN_SERVICE").items]
        self.assertNotIn("AG-22", ids)

    def test_an_applicant_in_the_frc_does_not_need_a_nikah_nama(self):
        """WAQAR vs WAQQAR must match."""
        self.assertEqual(self._nikah("Waqar Abdul Basit", self.FRC), [])

    def test_duplicate_frc_entries_are_one_person_not_an_ambiguity(self):
        """This FRC prints the same person three times; that must still resolve."""
        self.assertEqual(self._nikah("Waqar Abdul Basit", self.FRC), [])

    def test_an_applicant_absent_from_the_frc_is_a_medium_finding(self):
        flags = self._nikah("Someone Else Entirely", self.FRC)
        self.assertEqual([(f.severity, f.flag_class) for f in flags],
                         [("MEDIUM", "RELATIONSHIP-UNPROVED")])

    def test_an_unread_frc_never_excuses_it(self):
        """Absence of evidence is not evidence: an empty family list means it was not read."""
        self.assertEqual(len(self._nikah("Waqar Abdul Basit", ())), 1)
        self.assertEqual(len(self._nikah(None, self.FRC)), 1)

    def test_a_nikah_nama_in_the_bundle_raises_nothing(self):
        from rules.caserecord import Document
        doc = (Document(type="NIKAH_NAMA", pages=(9,), present=True),)
        self.assertEqual(self._nikah("Someone Else Entirely", self.FRC, documents=doc), [])

    def test_a_column_that_never_asked_for_one_raises_nothing(self):
        self.assertEqual(self._nikah("Someone Else Entirely", self.FRC, variant="FRESH_SELF"), [])
        self.assertEqual(self._nikah("Someone Else Entirely", self.FRC, variant=None), [])

    def test_neither_service_record_line_is_asked_for_any_more(self):
        """AG-09 stopped being required on 12 Oct 2026 (S16) and AG-10 on 20 Oct 2026. Neither
        can make a checklist INCOMPLETE, whatever the grade."""
        from rules import run_checklist
        for bps in (19, 15, None):
            for variant in ("FRESH_SELF", "DEATH_IN_SERVICE"):
                cl = run_checklist(CaseRecord(case_ref="t", case_type="", pay_scale_bps=bps),
                                   variant=variant)
                with self.subTest(bps=bps, variant=variant):
                    self.assertEqual(cl.item("AG-09").status, "NOT_REQUIRED")
                    self.assertEqual(cl.item("AG-10").status, "NOT_REQUIRED")

    def test_a_service_record_on_file_is_still_cited(self):
        """Removed, not deleted: a paper that IS filed is acknowledged with its page."""
        from rules import run_checklist
        from rules.caserecord import Document
        for doc, item_id in (("SERVICE_STATEMENT", "AG-09"), ("SERVICE_BOOK", "AG-10")):
            cl = run_checklist(
                CaseRecord(case_ref="t", case_type="",
                           documents=(Document(type=doc, pages=(9,)),)), variant="FRESH_SELF")
            with self.subTest(document=doc):
                self.assertEqual((cl.item(item_id).status, cl.item(item_id).located),
                                 ("FOUND_NOT_REQUIRED", (9,)))

    def test_bps_16_is_gazetted(self):
        """The boundary itself, pinned: 16 is gazetted, 15 is not.

        Read through AG-08 now. It was read through AG-10 until that line stopped being a
        requirement; the Last Pay Certificate still turns on the same distinction, because a
        gazetted officer's last pay is certified by Audit/Payrolls (decision S15)."""
        from rules import run_checklist
        for bps, expected in ((16, "NOT_APPLICABLE"), (15, "MISSING")):
            # AG-08's rule reads record.case_variant, so the record carries it too.
            rec = CaseRecord(case_ref="t", case_type="", pay_scale_bps=bps,
                             case_variant="FRESH_SELF")
            self.assertEqual(
                run_checklist(rec, variant="FRESH_SELF").item("AG-08").status, expected, bps)

    def test_without_a_grade_the_bundle_decides(self):
        """An AG service statement is issued only to gazetted officers, so its presence says so.
        Also read through AG-08 since AG-10 stopped asking."""
        from rules import run_checklist
        from rules.caserecord import Document
        rec = CaseRecord(case_ref="t", case_type="", case_variant="FRESH_SELF",
                         documents=(Document(type="SERVICE_STATEMENT", pages=(9,)),))
        cl = run_checklist(rec, variant="FRESH_SELF")
        self.assertEqual((cl.item("AG-09").status, cl.item("AG-09").located), ("FOUND_NOT_REQUIRED", (9,)))
        self.assertEqual(cl.item("AG-08").status, "NOT_APPLICABLE")
        self.assertIn("gazetted", cl.item("AG-08").reason)

    def test_with_neither_grade_nor_document_the_pay_certificate_stays_required(self):
        """Nothing establishes which record applies, so the Last Pay Certificate may not be
        excused. A grade that cannot be told keeps the requirement, so the line asks."""
        from rules import run_checklist
        cl = run_checklist(CaseRecord(case_ref="t", case_type="", case_variant="FRESH_SELF"),
                           variant="FRESH_SELF")
        self.assertEqual(cl.item("AG-08").status, "MISSING")

    def test_the_ppo_book_and_bank_file_are_never_required(self):
        """Items 23/24, office rule of 30 Sep 2026: not required in any case type. Absent they
        read "Not Required" -- never "Not found", never a deficiency."""
        from rules import run_checklist
        for variant in ("WIDOW", "DEATH_IN_SERVICE", "PARENT"):
            cl = run_checklist(CaseRecord(case_ref="t", case_type=""), variant=variant)
            for item_id in ("AG-23", "AG-24"):
                item = cl.item(item_id)
                self.assertEqual(item.status, "NOT_REQUIRED")
                self.assertNotIn("located in the bundle", item.reason)
            self.assertNotIn("AG-23", [i.id for i in cl.items if i.status == "MISSING"])

    def test_a_ppo_book_on_file_is_found_not_required_and_cited(self):
        from rules import run_checklist
        from rules.caserecord import Document
        rec = CaseRecord(case_ref="t", case_type="", documents=(Document(type="PPO", pages=(6, 7)),))
        item = run_checklist(rec, variant="WIDOW").item("AG-23")
        self.assertEqual((item.status, item.located), ("FOUND_NOT_REQUIRED", (6, 7)))


class OfficerDecisions(unittest.TestCase):
    """SOP §6.4: the module keeps a log of each entry. A log that can be edited is not one."""

    REPORT = {
        "recommendation": {"verdict": "RETURN_FOR_CORRECTION",
                           "blocking_flags": ["F-1", "F-3"], "rationale": "x"},
        "checklist": {"result": "INCOMPLETE", "missing": 1, "satisfied": 15, "required": 16},
        "case_variant": "DEATH_IN_SERVICE",
    }
    CLEAN = {
        "recommendation": {"verdict": "FORWARD", "blocking_flags": [], "rationale": "x"},
        "checklist": {"result": "COMPLETE", "missing": 0, "satisfied": 16, "required": 16},
    }

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()

    def _record(self, **kw):
        from api.decisions import record_decision
        kw.setdefault("report", self.REPORT)
        return record_decision(self.dir, run_id="t", **kw)

    def test_forwarding_a_blocked_case_needs_a_written_reason(self):
        """rules.verdict cannot recommend FORWARD over a HIGH flag; this is the other half."""
        from api.decisions import DecisionError
        with self.assertRaises(DecisionError) as ctx:
            self._record(action="FORWARD", officer="S. Ahmad")
        self.assertIn("F-1", str(ctx.exception))
        with self.assertRaises(DecisionError):
            self._record(action="FORWARD", officer="S. Ahmad", justification="ok")

    def test_a_justified_override_is_recorded_as_an_override(self):
        entry = self._record(action="FORWARD", officer="S. Ahmad",
                             justification="Department confirmed the recovery in writing.")
        self.assertTrue(entry["overrides_recommendation"])
        self.assertIn("F-1", entry["override_grounds"])

    def test_forwarding_a_clean_case_needs_no_justification(self):
        entry = self._record(action="FORWARD", officer="S. Ahmad", report=self.CLEAN)
        self.assertFalse(entry["overrides_recommendation"])

    def test_returning_a_case_needs_no_justification(self):
        self._record(action="RETURN_FOR_CORRECTION", officer="S. Ahmad")

    def test_a_decision_must_have_an_author(self):
        from api.decisions import DecisionError
        with self.assertRaises(DecisionError):
            self._record(action="HOLD", officer="   ")

    def test_an_unknown_action_is_refused(self):
        from api.decisions import DecisionError
        with self.assertRaises(DecisionError):
            self._record(action="APPROVE", officer="S. Ahmad")

    def test_the_log_appends_and_never_replaces(self):
        from api.decisions import current_decision, decisions_for
        self._record(action="RETURN_FOR_CORRECTION", officer="A")
        self._record(action="HOLD", officer="B")
        self._record(action="FORWARD", officer="C",
                     justification="Shortcomings cleared by the department on 09-09-2026.")
        history = decisions_for(self.dir)
        self.assertEqual([d["action"] for d in history],
                         ["RETURN_FOR_CORRECTION", "HOLD", "FORWARD"])
        self.assertEqual(current_decision(self.dir)["officer"], "C")

    def test_the_recommendation_is_captured_with_the_decision(self):
        """An audit must show what the officer saw, not what the report says years later."""
        entry = self._record(action="RETURN_FOR_CORRECTION", officer="S. Ahmad")
        self.assertEqual(entry["recommended_verdict"], "RETURN_FOR_CORRECTION")
        self.assertEqual(entry["blocking_flags"], ["F-1", "F-3"])
        self.assertEqual(entry["checklist_satisfied"], 15)
        self.assertEqual(entry["case_variant"], "DEATH_IN_SERVICE")

    def test_an_undecided_case_has_no_decision(self):
        from api.decisions import current_decision, decisions_for
        self.assertEqual(decisions_for(self.dir), [])
        self.assertIsNone(current_decision(self.dir))


class VariantDetection(unittest.TestCase):
    """The prescribed form decides the checklist column; the officer only confirms it."""

    FORM_D_II = ("FAMILY PENSION FORM (To be forwarded by the Appointing Authority / PSA in "
                 "the event of death of the pensioner) IN RESPECT OF MST. GHULAM ZAINAB "
                 "WIDOW OF AKBAR HUSSAIN RETIRED (LATE) INSPECTOR")

    def test_one_form_one_column(self):
        from rules import suggest_variant
        for case_type, expected in (
            ("FAMILY_PENSION_DEATH_IN_SERVICE", "DEATH_IN_SERVICE"),
            ("SUPERANNUATION_PENSION", "FRESH_SELF"),
            ("RETIRING_PENSION", "FRESH_SELF"),
            ("INVALID_PENSION", "FRESH_INVALID"),
            ("COMPULSORY_RETIREMENT_PENSION", "FRESH_INVALID"),
        ):
            self.assertEqual(suggest_variant(case_type).variant, expected, case_type)

    def test_form_d_ii_is_narrowed_by_the_claimant_it_names(self):
        """One form serves seven claimants; the form itself says which is filing."""
        from rules import suggest_variant
        s = suggest_variant("FAMILY_PENSION_DEATH_AFTER_RETIREMENT", self.FORM_D_II)
        self.assertEqual(s.variant, "WIDOW")
        self.assertIn("widow of", s.evidence)

    def test_a_widowed_daughter_is_not_read_as_a_widow(self):
        """Longest phrase first, or "widowed daughter" collapses into the widow column."""
        from rules import suggest_variant
        s = suggest_variant("FAMILY_PENSION_DEATH_AFTER_RETIREMENT",
                            "IN RESPECT OF MRS X, WIDOWED DAUGHTER OF Y")
        self.assertEqual(s.variant, "WD_DAUGHTER")

    def test_form_d_ii_without_a_named_relationship_asks_rather_than_guesses(self):
        from rules import suggest_variant
        s = suggest_variant("FAMILY_PENSION_DEATH_AFTER_RETIREMENT", "no relationship stated")
        self.assertIsNone(s.variant)
        self.assertEqual(len(s.candidates), 7)

    def test_an_undecided_case_type_can_still_decide_the_column(self):
        """Form B-I governs two case types that share one column, so there is nothing to ask."""
        from rules import suggest_variant
        s = suggest_variant(None, "", alternatives=("SUPERANNUATION_PENSION", "RETIRING_PENSION"))
        self.assertEqual(s.variant, "FRESH_SELF")

    def test_a_case_type_with_no_column_says_so(self):
        from rules import suggest_variant
        s = suggest_variant("ANTICIPATORY_PENSION")
        self.assertIsNone(s.variant)
        self.assertIn("no column", s.evidence)


class FormTitleCorroboration(unittest.TestCase):
    """A departmental form often prints its title and no number at all."""

    def test_a_title_corroborates_a_form_that_prints_no_number(self):
        from extraction.identify import PageIdentity, _verify_form_claim
        ident = PageIdentity(page=4, document_type="FORM_D_II", confidence=1.0,
                             evidence="FAMILY PENSION FORM", is_first_page=True)
        kept = _verify_form_claim(ident, (), ("FORM_D_II",))
        self.assertEqual(kept.document_type, "FORM_D_II")

    def test_a_number_for_another_form_still_denies_the_claim(self):
        """Silence admits the weaker evidence; a contradicting number never does."""
        from extraction.identify import PageIdentity, _verify_form_claim
        ident = PageIdentity(page=4, document_type="FORM_D_II", confidence=1.0,
                             evidence="", is_first_page=True)
        self.assertEqual(
            _verify_form_claim(ident, ("FORM_D_I",), ("FORM_D_II",)).document_type, "OTHER")

    def test_no_number_and_no_title_is_still_a_denial(self):
        from extraction.identify import PageIdentity, _verify_form_claim
        ident = PageIdentity(page=22, document_type="FORM_D_I", confidence=1.0,
                             evidence="", is_first_page=True)
        self.assertEqual(_verify_form_claim(ident, (), ()).document_type, "OTHER")

    def test_family_pension_form_alone_proves_nothing(self):
        """That heading sits on both D-I and D-II, so it must not corroborate either."""
        from extraction.ocr import PageText, form_titles_on
        self.assertEqual(form_titles_on(PageText(1, "FAMILY PENSION FORM", "t")), ())


class UrduDocuments(unittest.TestCase):
    """A page whose body is in Urdu is still identifiable, and must not fall to OTHER."""

    def test_the_affidavit_gloss_names_what_identifies_one(self):
        """Both readers missed a widow's affidavit because its body is Urdu.

        The e-stamp header is English and OCR read it three times over; the vision model
        described the advocate's stamp without recognising the document. What identifies it
        is the heading and the oath-commissioner stamp, so the gloss has to say so -- an enum
        constrains shape, the gloss constrains meaning.
        """
        from extraction.schemas import DOCUMENT_TYPE_GLOSS
        gloss = DOCUMENT_TYPE_GLOSS["AFFIDAVIT"]
        for marker in ("بیان حلفی", "OATH COMMISSIONER", "stamp paper", "URDU"):
            self.assertIn(marker, gloss, f"the affidavit gloss must mention {marker!r}")

    def test_the_reader_is_told_that_urdu_is_normal(self):
        """Answering OTHER because the body is unreadable drops a document the case needs."""
        from extraction.identify import IDENTIFY_INSTRUCTION
        self.assertIn("URDU", IDENTIFY_INSTRUCTION)
        self.assertIn("بیان حلفی", IDENTIFY_INSTRUCTION)


class ClaimantFromTheForm(unittest.TestCase):
    """Who is claiming, taken from the sentence the PSA signed."""

    def test_the_subject_line_names_the_claimant(self):
        from rules import claimant_from_form
        for text, expected in (
            ("IN RESPECT OF MST. GHULAM ZAINAB WIDOW OF AKBAR HUSSAIN", "Ghulam Zainab"),
            ("IN RESPECT OF MR. WAQAR ABDUL BASIT WIDOWER OF MST. NARGAS",
             "Waqar Abdul Basit"),
            ("IN RESPECT OF MRS ZAINAB WIDOWED DAUGHTER OF KARIM BUX", "Zainab"),
        ):
            self.assertEqual(claimant_from_form(text), expected, text)

    def test_a_qualifier_belongs_to_the_relationship_not_the_name(self):
        """"SANA BIBI UNMARRIED DAUGHTER OF" names Sana Bibi, not Sana Bibi Unmarried."""
        from rules import claimant_from_form
        self.assertEqual(
            claimant_from_form("IN RESPECT OF MISS SANA BIBI UNMARRIED DAUGHTER OF ALLAH RAKHA"),
            "Sana Bibi",
        )

    def test_a_sentence_fragment_is_not_a_name(self):
        """This decides whose CNIC satisfies which line, so a guess is worse than nothing."""
        from rules import claimant_from_form
        for text in ("IN RESPECT OF THE WIDOW OF AKBAR HUSSAIN",
                     "IN RESPECT OF THE LATE SON OF X",
                     "no such clause"):
            self.assertIsNone(claimant_from_form(text), text)

    def test_a_rank_before_the_name_is_not_part_of_it(self):
        """On a self pension the claimant IS the pensioner, so the name is wanted -- but the
        post they held is not part of it and must not reach a letter."""
        from rules import claimant_from_form
        self.assertEqual(
            claimant_from_form("GRANT OF PENSION IN RESPECT OF SUB INSPECTOR JAMSHAID ULLAH"),
            "Jamshaid Ullah",
        )


class BatteryIsNotGatedOnCaseType(unittest.TestCase):
    """A case the ladder cannot type is still a case that can contradict itself."""

    def test_checks_run_without_a_derived_case_type(self):
        """The self-pension bundle reported zero flags because of this gate.

        Form B-I governs superannuation and retiring pension, so §4.1 declines to choose --
        and the battery was skipped entirely, taking the identity, family, alias and
        unreadable-page checks with it. Only the succession-certificate check needs a case
        type, and it guards itself.
        """
        from rules import Assertion, CaseRecord, Source, run_battery, select_pack
        record = CaseRecord(
            case_ref="t", case_type="",          # undetermined
            assertions=(
                Assertion("personnel_no", "30041520", Source(1, "FORWARDING_LETTER")),
                Assertion("personnel_no", "30041999", Source(9, "BANK_OPTION_FORM")),
            ),
        )
        flags = run_battery(record, select_pack(effective_date=g.DATE_OF_DEATH))
        self.assertIn("CONTRA-IDENTITY", {f.flag_class for f in flags})

    def test_a_self_pension_has_no_deceased_to_confuse(self):
        """"Roles not independently confirmed" on a self pension is a finding about nothing."""
        from rules import CaseRecord, run_battery, select_pack
        pack = select_pack(effective_date=g.DATE_OF_DEATH)
        for variant, expected in (("FRESH_SELF", False), ("WIDOW", True)):
            record = CaseRecord(case_ref="t", case_type="", case_variant=variant,
                                party_roles_note="only one party name was extracted")
            raised = "EXTRACT-ROLE-SWAP" in {f.flag_class for f in run_battery(record, pack)}
            self.assertEqual(raised, expected, variant)


class DeniedFormPagesAreReRead(unittest.TestCase):
    """A denial says what a page is not. Something has to say what it is."""

    def test_the_new_service_record_types_exist_and_are_glossed(self):
        """Both were found unclassified in real bundles, holding documents the office wants."""
        from extraction.schemas import DOCUMENT_TYPES, DOCUMENT_TYPE_GLOSS
        for t in ("CHARGE_REPORT", "CHARACTER_SERVICE_ROLL"):
            self.assertIn(t, DOCUMENT_TYPES)
            self.assertGreater(len(DOCUMENT_TYPE_GLOSS[t]), 60, t)

    def test_the_superannuation_gloss_distinguishes_an_order_from_a_sanction(self):
        """That page claimed Form B-I, was rightly denied, and then vanished as OTHER."""
        gloss = __import__("extraction.schemas", fromlist=["x"]).DOCUMENT_TYPE_GLOSS
        text = gloss["SUPERANNUATION_ORDER"]
        self.assertIn("SUPERANNUATION NOTIFICATION", text)
        self.assertIn("not Form B-I", text)

    def test_a_page_that_still_cannot_be_placed_stays_other(self):
        """Forcing a type onto an unplaceable page would satisfy a requirement falsely."""
        from extraction.identify import PageIdentity, _reclassify_after_denial
        stuck = PageIdentity(page=22, document_type="OTHER", confidence=0.95, evidence="",
                             is_first_page=True, downgraded_from="FORM_D_I")
        # No model reachable in the test environment, so the re-read raises and the denial
        # must stand rather than the page being invented into something.
        out = _reclassify_after_denial(stuck, "/nonexistent.png", "")
        self.assertEqual(out.document_type, "OTHER")
        self.assertFalse(out.reclassified)

    #: The re-read's answer: the denied Form B-I page is, it says, Form B-III.
    _RE_READ_AS_B_III = {
        "document_type": "FORM_B_III", "document_type_confidence": 0.9,
        "evidence": "headed FINAL PENSION PAYMENT ORDER", "is_first_page_of_document": True,
    }

    def _re_read(self):
        from extraction.client import Extraction
        return mock.patch("extraction.identify.extract_page", return_value=Extraction(
            data=dict(self._RE_READ_AS_B_III), doc_type="PAGE_IDENTITY", schema_name="PAGE_IDENTITY",
            source="p.pdf", model="m", prompt_version="v", latency_s=0.0, prompt_tokens=0,
            completion_tokens=0))

    def test_a_re_read_that_names_another_form_is_taken_when_ocr_prints_it(self):
        """The corroborating OCR read raised NameError until 12 Oct 2026: ``ocr_page`` was never
        imported into ``_reclassify_after_denial``, so a denied form that came back as another
        form failed the whole run after the vision stage rather than being checked."""
        from extraction.identify import PageIdentity, _reclassify_after_denial
        from extraction.ocr import PageText
        denied = PageIdentity(page=9, document_type="OTHER", confidence=0.95, evidence="",
                              is_first_page=True, downgraded_from="FORM_B_I")
        printed = PageText(9, "FORM B-III FINAL PENSION PAYMENT ORDER in respect of Mr Test", "t")
        with self._re_read(), mock.patch("extraction.ocr.ocr_page", return_value=printed):
            out = _reclassify_after_denial(denied, "/page-9.png", "")
        self.assertEqual(out.document_type, "FORM_B_III")
        self.assertTrue(out.reclassified)
        self.assertEqual(out.downgraded_from, "FORM_B_I")

    def test_a_re_read_whose_ocr_check_fails_keeps_the_denial(self):
        """No second reading is no corroboration: the page keeps what the denial left it, and
        the run goes on, rather than the re-read being accepted on the model's word or the
        OCR failure taking the run down."""
        from extraction.identify import PageIdentity, _reclassify_after_denial
        from extraction.ocr import OcrError
        denied = PageIdentity(page=9, document_type="OTHER", confidence=0.95, evidence="",
                              is_first_page=True, downgraded_from="FORM_B_I")
        with self._re_read(), mock.patch("extraction.ocr.ocr_page",
                                         side_effect=OcrError("reader returned nothing")):
            out = _reclassify_after_denial(denied, "/page-9.png", "")
        self.assertEqual(out.document_type, "OTHER")
        self.assertEqual(out.downgraded_from, "FORM_B_I")
        self.assertFalse(out.reclassified)


class FactsComeFromTheFormNotTheCalculation(unittest.TestCase):
    """A document check must not wait on a determination that may never run."""

    D_I = ("FORM D-I FAMILY PENSION FORM SUBJECT: NOTIFICATION / ORDERS FOR SANTION OF "
           "FAMILY PENSION IN RESPECT OF MST/MR ... WAQIAR ABDUL BASIT Notification / "
           "Order No: SO(SE-II)PF-4046/2013 Dated: 12-10-2021 Designation Principal BS-19")

    def test_the_grade_is_read_from_the_sanction_form(self):
        """Read from the determination, a clean run had no grade and asked a BS-19 officer
        for both a service book and an AG service statement -- only one of which exists."""
        from rules import pay_scale_from_form
        self.assertEqual(pay_scale_from_form(self.D_I), 19)
        self.assertEqual(pay_scale_from_form("Ex-Principal (BPS-16), CPO Lahore"), 16)
        self.assertIsNone(pay_scale_from_form("no grade printed here"))

    def test_a_blank_form_placeholder_is_stepped_over(self):
        """The prescribed forms print "MST/MR ......" with the name written after the dots."""
        from rules import claimant_from_form
        self.assertEqual(claimant_from_form(self.D_I), "Waqiar Abdul Basit")

    def test_form_vocabulary_after_the_name_is_not_part_of_it(self):
        """"... ABDUL BASIT Notification / Order No" must not yield "Ala Notification"."""
        from rules import claimant_from_form
        self.assertEqual(
            claimant_from_form("IN RESPECT OF MST/MR ... KASHIF ALI KHAN Notification / Order"),
            "Kashif Ali Khan",
        )
        self.assertIsNone(claimant_from_form("IN RESPECT OF THE LATE SON OF X"))


class DepartmentalFormNaming(unittest.TestCase):
    """The same sanction form is headed differently by different offices."""

    def test_annex_b_1_is_form_b_i(self):
        """A real case carried the sanction on a proforma headed "Annex-B-1".

        The check looked for the word FORM, found none, denied the model's correct answer,
        and the case lost the one document that decides its type -- reported as "Pension
        Sanctioning Authority form ... not found" with the form sitting at page 9.
        """
        from extraction.ocr import PageText, forms_printed_on
        for text, expected in (
            ("Annex-B-1 (To be issued by the appointing Authority)", ("FORM_B_I",)),
            ("ANNEXURE B-IV", ("FORM_B_IV",)),
            ("Annex-D-I (Form)", ("FORM_D_I",)),
            ("Form B-1", ("FORM_B_I",)),
            ("FORM D-II", ("FORM_D_II",)),
        ):
            self.assertEqual(forms_printed_on(PageText(1, text, "t")), expected, text)

    def test_annexure_a_is_not_a_sanction_form(self):
        """Annexure-A is the descriptive roll; widening the prefix must not sweep it in."""
        from extraction.ocr import PageText, forms_printed_on
        self.assertEqual(forms_printed_on(PageText(1, "Annexure-A Descriptive Roll", "t")), ())


class ServiceBookPages(unittest.TestCase):
    """A bound service book is twenty pages, and only one of them looks like a title page."""

    def test_the_gloss_describes_the_pages_not_the_book(self):
        """Twenty-one of 44 pages fell to OTHER because the gloss named the document rather
        than what its pages look like: numbered particulars, a service-history table, a
        leave account."""
        from extraction.schemas import DOCUMENT_TYPE_GLOSS
        gloss = DOCUMENT_TYPE_GLOSS["SERVICE_BOOK"]
        for marker in ("Name of post", "finger-impressions", "Interior pages",
                       "NON-GAZETTED", "sideways"):
            self.assertIn(marker, gloss, f"the service-book gloss must mention {marker!r}")


class LateSubmission(unittest.TestCase):
    """Item 19, the reason for late submission: not required in any case type (office rule,
    30 Sep 2026), however old the case. The three-year test no longer decides it."""

    def _status(self, began, sent, variant="WIDOW", documents=()):
        from rules import CaseRecord, run_checklist
        rec = CaseRecord(case_ref="t", case_type="", case_variant=variant,
                         entitlement_date=began, submitted_date=sent, documents=documents)
        return run_checklist(rec, variant=variant).item("AG-19")

    def test_never_missing_whatever_the_age_of_the_case(self):
        from datetime import date
        for began, sent in ((date(2026, 7, 3), date(2026, 7, 29)), (date(2021, 7, 29), date(2026, 5, 20)),
                            (None, date(2026, 5, 1)), (date(2021, 1, 1), None)):
            self.assertEqual(self._status(began, sent).status, "NOT_REQUIRED")
            self.assertEqual(self._status(began, sent, variant="FRESH_SELF").status, "NOT_REQUIRED")

    def test_a_reason_on_file_is_found_not_required(self):
        from datetime import date
        from rules.caserecord import Document
        item = self._status(date(2021, 7, 29), date(2026, 5, 20),
                            documents=(Document(type="LATE_SUBMISSION_REASON", pages=(3,)),))
        self.assertEqual((item.status, item.located), ("FOUND_NOT_REQUIRED", (3,)))


class OfficeRulesOf30September(unittest.TestCase):
    """Meaning-based matching of the no-income certificate, and AG-16 for an unmarried daughter."""

    def test_the_no_income_certificate_is_found_under_any_of_its_titles(self):
        from extraction.identify import title_found, titles_on_page
        for heading in ("NON SOURCE OF INCOME CERTIFICATE", "Non-Source of Income Certificate",
                        "No Source of Income Certificate", "Certificate of No Regular Income",
                        "NO INCOME CERTIFICATE", "No Regular Source of Income Certificate",
                        "It is certified that the claimant has no regular source of income."):
            text = f"GOVERNMENT OF THE PUNJAB\n{heading}\nSigned"
            self.assertIn("NO_REGULAR_INCOME_CERTIFICATE", titles_on_page(text), heading)
            self.assertEqual(title_found("NO_REGULAR_INCOME_CERTIFICATE", text), heading)
        self.assertNotIn("NO_REGULAR_INCOME_CERTIFICATE", titles_on_page("Income tax certificate for 2024"))

    def test_a_sworn_certificate_stating_no_income_also_satisfies_the_line(self):
        from extraction.identify import statements_on_page
        text = "SOLE WIDOW CERTIFICATE ... she has no other source of income and has not remarried"
        self.assertIn("NO_REGULAR_INCOME_CERTIFICATE", statements_on_page("SOLE_WIDOW_CERTIFICATE", text))

    def test_the_sole_widow_certificate_is_not_required_for_an_unmarried_daughter(self):
        from rules import run_checklist
        from rules.caserecord import Document
        absent = run_checklist(CaseRecord(case_ref="t", case_type=""), variant="UNMARRIED_CHILD").item("AG-16")
        self.assertEqual(absent.status, "NOT_REQUIRED")
        rec = CaseRecord(case_ref="t", case_type="", documents=(Document(type="SOLE_WIDOW_CERTIFICATE", pages=(4,)),))
        self.assertEqual(run_checklist(rec, variant="UNMARRIED_CHILD").item("AG-16").status, "FOUND_NOT_REQUIRED")
        # Every other column that asks for it still does.
        for variant in ("WIDOW", "DEATH_IN_SERVICE", "WD_DAUGHTER", "PARENT"):
            self.assertEqual(run_checklist(CaseRecord(case_ref="t", case_type=""), variant=variant).item("AG-16").status,
                             "MISSING", variant)

    def test_only_not_found_counts_as_a_deficiency(self):
        from rules import run_checklist
        cl = run_checklist(CaseRecord(case_ref="t", case_type=""), variant="UNMARRIED_CHILD")
        missing = {i.id for i in cl.items if i.status == "MISSING"}
        self.assertFalse(missing & {"AG-16", "AG-19", "AG-23", "AG-24"})
        self.assertEqual(cl.satisfied + cl.missing + cl.defective, cl.required)


class AmendedBase(unittest.TestCase):
    """The December 2024 amendment: rule 4.4(4) substituted, base becomes a 3-year average."""

    def _pack(self):
        from datetime import date
        from rules import select_pack
        return select_pack(effective_date=date(2026, 2, 27))

    def _years(self):
        from decimal import Decimal
        from rules.emoluments import AnnualPay
        return [AnnualPay(2023, Decimal("58000")), AnnualPay(2024, Decimal("60500")),
                AnnualPay(2025, Decimal("62550"))]

    def test_the_average_is_of_three_years_and_shown_in_full(self):
        from rules.emoluments import reckon_average
        emol = reckon_average(self._years(), self._pack())
        self.assertEqual(emol.reckonable_total, 60350)
        self.assertIn("1 Jul 2023", emol.computation_shown)
        self.assertIn("/ 3 =", emol.computation_shown)

    def test_a_short_list_raises_rather_than_averaging_what_it_has(self):
        """The missing year is the earliest and lowest, so a mean of the rest is too high."""
        from rules.emoluments import EmolumentsError, reckon_average
        with self.assertRaises(EmolumentsError):
            reckon_average(self._years()[:2], self._pack())

    def test_the_same_year_three_times_is_not_three_years(self):
        from decimal import Decimal
        from rules.emoluments import AnnualPay, EmolumentsError, reckon_average
        with self.assertRaises(EmolumentsError):
            reckon_average([AnnualPay(2025, Decimal(n)) for n in ("1", "2", "3")], self._pack())

    def _last_drawn_case(self):
        from datetime import date
        from rules.emoluments import reckon_average
        from rules.engine import SelfPensionCase
        pack = self._pack()
        return SelfPensionCase(
            case_ref="t", date_of_birth=date(1966, 2, 28),
            date_of_first_entry=date(1987, 11, 1), date_of_retirement=date(2026, 2, 27),
            emoluments=reckon_average(self._years(), pack), bps=14,
            base_is_three_year_average=False,        # the caller has not said it averaged
        ), pack

    def test_a_last_drawn_base_is_refused_once_a_figure_is_published(self):
        """One pay slip is not the average, and on a rising scale it is always larger.

        The refusal is conditional on rules.scope.CALCULATIONS_IN_SCOPE from 20 Oct 2026: it
        is there to stop an overstated figure reaching an officer, and this release publishes
        no figure at all. With calculations back in scope it must still refuse, which is what
        this pins -- see tests.test_base_guard_follows_scope for the other half.
        """
        from datetime import datetime
        from unittest import mock
        from rules import engine, scope
        from rules.engine import determine_self_pension
        case, pack = self._last_drawn_case()
        with mock.patch.object(scope, "CALCULATIONS_IN_SCOPE", True), \
                mock.patch.object(engine.scope, "CALCULATIONS_IN_SCOPE", True):
            with self.assertRaises(ValueError) as ctx:
                determine_self_pension(case, pack, datetime(2026, 9, 10))
        self.assertIn("three years", str(ctx.exception))

    def test_with_no_figure_published_it_is_provisional_instead_of_refused(self):
        """The officer still gets the dates, the rule pack and the BLOCKING items; the case
        is marked provisional and says why. Every self-pension bundle hit this -- 21 runs of
        21 on 20 Oct 2026 -- because the three 1 July figures are keyed at intake."""
        from datetime import datetime
        from rules.engine import determine_self_pension
        case, pack = self._last_drawn_case()
        det = determine_self_pension(case, pack, datetime(2026, 9, 10))
        self.assertIn("BLOCKING-23", det.unverified_engaged)
        self.assertTrue(any("three basic-pay figures" in c for c in det.caveats),
                        f"no caveat explaining the base: {det.caveats}")

    def test_superannuation_takes_no_voluntary_reduction(self):
        from datetime import date, datetime
        from rules.emoluments import reckon_average
        from rules.engine import SelfPensionCase, determine_self_pension
        pack = self._pack()
        det = determine_self_pension(SelfPensionCase(
            case_ref="t", date_of_birth=date(1966, 2, 28),
            date_of_first_entry=date(1987, 11, 1), date_of_retirement=date(2026, 2, 27),
            emoluments=reckon_average(self._years(), pack), bps=14,
            base_is_three_year_average=True), pack, datetime(2026, 9, 10))
        self.assertFalse(any(s.rule_id == "VOL-RED-01" for s in det.steps))
        self.assertEqual(next(s.amount for s in det.steps if s.rule_id == "CALC-01"), 42245)

    # -- the two printed dates have to agree with each other (QS-10) -------------------

    def _case(self, **over):
        from datetime import date
        from rules.emoluments import reckon_average
        from rules.engine import SelfPensionCase
        kw = dict(case_ref="t", date_of_birth=date(1966, 2, 28),
                  date_of_first_entry=date(1987, 11, 1),
                  date_of_retirement=date(2026, 2, 27),
                  emoluments=reckon_average(self._years(), self._pack()), bps=14,
                  base_is_three_year_average=True)
        kw.update(over)
        return SelfPensionCase(**kw)

    def test_retirement_past_the_superannuation_age_is_refused(self):
        """A real case printed born 1956, retired 2026 -- retiring at 69 completed years.

        Nothing caught it, and the pension was computed on the pair regardless. One of the
        two dates is a misprint and we cannot tell which, so the case goes to a human.
        """
        from datetime import date, datetime
        from rules.engine import RetirementDateMismatch, determine_self_pension
        with self.assertRaises(RetirementDateMismatch) as ctx:
            determine_self_pension(self._case(date_of_birth=date(1956, 2, 19),
                                              date_of_retirement=date(2026, 2, 18)),
                                   self._pack(), datetime(2026, 9, 10))
        self.assertIn("at 69", str(ctx.exception))
        self.assertIn("rule pack", str(ctx.exception))

    def test_an_extension_order_on_the_file_lets_late_service_stand(self):
        from datetime import date, datetime
        from rules.engine import determine_self_pension
        det = determine_self_pension(
            self._case(date_of_birth=date(1956, 2, 19),
                       date_of_retirement=date(2026, 2, 18),
                       service_extension_evidenced=True),
            self._pack(), datetime(2026, 9, 10))
        self.assertTrue(any("extension order" in c for c in det.caveats))

    def test_the_day_before_the_sixtieth_birthday_is_not_a_mismatch(self):
        """The convention retires a servant at 59 completed years. Off-by-one here would
        refuse nearly every sound superannuation case."""
        from datetime import datetime
        from rules.engine import determine_self_pension
        det = determine_self_pension(self._case(), self._pack(), datetime(2026, 9, 10))
        self.assertFalse(any("superannuation age" in c for c in det.caveats))

    def test_a_superannuation_pension_years_before_sixty_is_refused(self):
        from datetime import date, datetime
        from rules.engine import RetirementDateMismatch, determine_self_pension
        with self.assertRaises(RetirementDateMismatch) as ctx:
            determine_self_pension(self._case(date_of_birth=date(1976, 2, 28)),
                                   self._pack(), datetime(2026, 9, 10))
        self.assertIn("short of the superannuation age", str(ctx.exception))

    def test_an_early_retiring_pension_is_not_a_mismatch(self):
        """Leaving early is what a retiring pension is; only superannuation must fall at 60."""
        from datetime import date, datetime
        from rules.engine import determine_self_pension
        det = determine_self_pension(
            self._case(date_of_birth=date(1969, 2, 28), pension_kind="RETIRING_PENSION"),
            self._pack(), datetime(2026, 9, 10))
        self.assertTrue(any(s.rule_id == "VOL-RED-01" for s in det.steps))

    def test_the_determination_survives_being_written_to_json(self):
        """A date object in ``inputs`` fails at the write, and the run records nothing.

        The report is serialised with a plain ``json.dumps``, so anything in a
        determination that json cannot encode does not degrade the report -- it
        destroys it, and the officer sees a failed run with no reason on the page.
        """
        import json
        from datetime import date, datetime
        from rules.emoluments import reckon_average
        from rules.engine import SelfPensionCase, determine_self_pension
        pack = self._pack()
        det = determine_self_pension(SelfPensionCase(
            case_ref="t", date_of_birth=date(1966, 2, 28),
            date_of_first_entry=date(1987, 11, 1), date_of_retirement=date(2026, 2, 27),
            emoluments=reckon_average(self._years(), pack), bps=14,
            base_is_three_year_average=True), pack, datetime(2026, 9, 10))
        written = json.dumps(det.to_dict())          # no default=; the writer has none either
        self.assertIn("2026-02-27", written)

    def test_voluntary_retirement_is_reduced_by_age(self):
        from datetime import date, datetime
        from rules.emoluments import reckon_average
        from rules.engine import SelfPensionCase, determine_self_pension
        pack = self._pack()
        det = determine_self_pension(SelfPensionCase(
            case_ref="t", date_of_birth=date(1966, 2, 28),
            date_of_first_entry=date(1987, 11, 1), date_of_retirement=date(2026, 2, 27),
            emoluments=reckon_average(self._years(), pack), bps=14,
            pension_kind="RETIRING_PENSION", base_is_three_year_average=True),
            pack, datetime(2026, 9, 10))
        step = next(s for s in det.steps if s.rule_id == "VOL-RED-01")
        self.assertEqual(step.amount, 41400)        # 42,245 less 2% at age 59

    def test_an_age_outside_the_table_raises(self):
        """BLOCKING-19: a missing factor is not a zero factor."""
        from datetime import date, datetime
        from rules.emoluments import reckon_average
        from rules.engine import SelfPensionCase, determine_self_pension
        from rules.loader import UnknownReferenceValue
        pack = self._pack()
        with self.assertRaises(UnknownReferenceValue):
            determine_self_pension(SelfPensionCase(
                case_ref="t", date_of_birth=date(1966, 2, 28),
                date_of_first_entry=date(1987, 11, 1), date_of_retirement=date(2020, 2, 27),
                emoluments=reckon_average(self._years(), pack), bps=14,
                pension_kind="RETIRING_PENSION", base_is_three_year_average=True),
                pack, datetime(2026, 9, 10))

    def test_commutation_ceiling_came_down_to_25_percent(self):
        # Stored as a string on purpose: the loader refuses bare JSON numbers so a
        # money value can never arrive as a float (FMT-02).
        self.assertEqual(int(self._pack().ref("commutation", "max_percent_of_gross")), 25)

    def test_the_pack_in_force_before_the_amendment_is_still_reachable(self):
        """A pension sanctioned under the old rules must remain recomputable."""
        from datetime import date
        from rules import select_pack
        self.assertEqual(select_pack(effective_date=date(2021, 7, 29)).id, "PB-2026.02")
        self.assertEqual(select_pack(effective_date=date(2026, 2, 27)).id, "PB-2024.12")


if __name__ == "__main__":
    unittest.main(verbosity=2)
