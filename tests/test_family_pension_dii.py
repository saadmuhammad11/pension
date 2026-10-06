"""Family pension on the death of a PENSIONER. Form D-II / Proforma D-II.

Standard library only; no GPU and no network.

The D-II path exists because the pipeline had exactly one family-pension calculator -- a
death IN SERVICE -- and two real bundles arrived for the other event entirely: a pensioner
who had retired, drawn his pension for years and then died. Both bundles carried their
prescribed form correctly. Stage 4 rejected them as having "no prescribed form", the screen
reported "the module does not determine this kind of case in this build", and a day went
into an OCR bug that was never the cause.

So the tests below pin two things equally hard: that the D-II path computes when its rules
are confirmed, and that it REFUSES, distinctly and by name, when they are not.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ==============================================================================================
# Classification
# ==============================================================================================

class WhichPathTheBundleIsOn(unittest.TestCase):
    """The class decides which arithmetic runs, so it never guesses."""

    def test_form_d_i_is_a_death_in_service(self):
        from rules.dii import DEATH_IN_SERVICE, classify_case
        self.assertEqual(classify_case(prescribed_form="FORM_D_I").case, DEATH_IN_SERVICE)

    def test_form_d_ii_is_a_death_after_retirement(self):
        from rules.dii import DEATH_AFTER_RETIREMENT, classify_case
        self.assertEqual(classify_case(prescribed_form="FORM_D_II").case,
                         DEATH_AFTER_RETIREMENT)

    def test_a_second_death_on_the_form_makes_it_a_regrant(self):
        """The divorced-daughter bundle: the pensioner died in 2010, the widow who was
        drawing the family pension died in 2018, and the daughter claims in 2026."""
        from rules.dii import REGRANT_AFTER_WIDOW_DEATH, classify_case
        got = classify_case(prescribed_form="FORM_D_II",
                            date_of_death=date(2010, 5, 23),
                            prior_pensioner_death=date(2018, 1, 30))
        self.assertEqual(got.case, REGRANT_AFTER_WIDOW_DEATH)
        self.assertIn("2018-01-30", got.evidence)

    def test_no_form_and_no_dates_is_unknown(self):
        from rules.dii import UNKNOWN, classify_case
        got = classify_case(prescribed_form=None)
        self.assertEqual(got.case, UNKNOWN)
        self.assertFalse(got.determinable)

    def test_a_death_after_a_retirement_date_is_not_a_death_in_service(self):
        """Inferred only in the safe direction. A servant who has retired is not serving."""
        from rules.dii import DEATH_AFTER_RETIREMENT, classify_case
        got = classify_case(prescribed_form=None,
                            date_of_retirement=date(1997, 10, 1),
                            date_of_death=date(2025, 9, 17))
        self.assertEqual(got.case, DEATH_AFTER_RETIREMENT)

    def test_a_missing_retirement_date_is_never_read_as_service(self):
        """The reverse inference is not made: an absent date is not evidence."""
        from rules.dii import UNKNOWN, classify_case
        self.assertEqual(
            classify_case(prescribed_form=None, date_of_death=date(2025, 9, 17)).case, UNKNOWN)


# ==============================================================================================
# The config
# ==============================================================================================

def _case(**over):
    from rules.dii import DeathAfterRetirementCase
    base = dict(case_ref="T-DII", sanctioned_pension=Decimal("2512"),
                claimant_relation="widow",
                date_of_death_of_pensioner=date(2025, 9, 17))
    base.update(over)
    return DeathAfterRetirementCase(**base)


def _populated(tmp: Path) -> "object":
    """A config with the values confirmed, for testing the computing path only.

    The numbers here are FIXTURE values invented for this test. They are not the Punjab
    rule, they are not taken from any bundle, and nothing outside this file may read them.
    """
    from rules.dii import DIIRules
    tmp.write_text(
        "id: PB-DII-TEST\n"
        "share:\n"
        "  widow_percent: 75\n"
        "  regrant_daughter_percent: 50\n"
        "  unmarried_child_percent: UNSET\n"
        "base:\n"
        "  definition: pension_in_payment\n"
        "commencement:\n"
        "  on_death_of_pensioner: day_after_death\n"
        "  on_regrant: death_of_prior_pensioner\n",
        encoding="utf-8",
    )
    return DIIRules.load(tmp, confirmations=[])


class TheShippedConfigIsProvisional(unittest.TestCase):
    """The values ship, and ship marked as unconfirmed. A figure with no authority behind it
    must be visible as such on every determination that uses it -- BRAIN §14.1 rules 3-4."""

    def test_the_file_is_marked_provisional_not_confirmed(self):
        from rules.dii import DIIRules
        rules = DIIRules.load(confirmations=[])
        self.assertFalse(rules.file_confirmed)
        self.assertEqual(rules.values["status"], "provisional")
        self.assertTrue(rules.values.get("provisional_source"))

    def test_the_share_is_stated_and_its_source_is_the_documentation(self):
        from rules.dii import DIIRules
        rules = DIIRules.load(confirmations=[])
        for key in ("widow_percent", "regrant_daughter_percent"):
            self.assertEqual(rules.values["share"][key], "75")
            self.assertFalse(rules.is_confirmed("share", key))
        self.assertIn("FAM-AR-02", rules.values["provisional_source"])

    def test_the_base_definition_stays_open(self):
        """Two figures on the form and no rule saying which: the engine emits both."""
        from rules.dii import UNSET, DIIRules
        self.assertEqual(DIIRules.load(confirmations=[]).values["base"]["definition"], UNSET)

    def test_no_provisional_value_is_ever_confirmed_by_the_file_itself(self):
        from rules.dii import CONFIG_PATH
        body = CONFIG_PATH.read_text(encoding="utf-8")
        status = [l.split("#", 1)[0].strip() for l in body.splitlines()
                  if l.split("#", 1)[0].strip().startswith("status:")]
        self.assertEqual(status, ["status: provisional"])


class ComputingOnTheShippedProvisionalRules(unittest.TestCase):
    """What the office sees today: a figure, marked provisional, engaging BLOCKING-07."""

    def _rules(self):
        from rules.dii import DIIRules
        return DIIRules.load(confirmations=[])

    def test_a_widow_gets_a_figure_and_it_is_provisional(self):
        from rules.dii import classify_case, determine_family_pension_death_after_retirement
        det = determine_family_pension_death_after_retirement(
            _case(), self._rules(), classify_case(prescribed_form="FORM_D_II"),
            datetime(2026, 6, 3))
        self.assertTrue(det.provisional)
        self.assertEqual(det.unverified_engaged, ("BLOCKING-07",))
        self.assertEqual(det.step("FAM-AR-02").presented, 1884)      # 2512 x 75%
        self.assertIn("share.widow_percent", det.inputs["provisional_keys"])
        self.assertTrue(any("PROVISIONAL" in c and "share.widow_percent = 75" in c
                            for c in det.caveats))
        self.assertTrue(any("Deputy Accountant General (Pension)" in c for c in det.caveats))

    def test_two_figures_on_the_form_become_two_readings_not_one(self):
        """Khan Bahadur: pension in payment 50,000, net pension 1,066. Nobody picks."""
        from rules.dii import classify_case, determine_family_pension_death_after_retirement
        from rules.types import AmbiguityCollapseError
        det = determine_family_pension_death_after_retirement(
            _case(sanctioned_pension=Decimal("50000"), net_pension=Decimal("1066")),
            self._rules(), classify_case(prescribed_form="FORM_D_II"), datetime(2026, 6, 3))
        amb = det.ambiguity("FAM-AR-02")
        self.assertEqual(amb.blocking_id, "BLOCKING-07")
        self.assertEqual(amb.reading("on_pension_in_payment").presented, 37_500)
        self.assertEqual(amb.reading("on_net_pension").presented, 800)      # 1066 x 75% = 799.5
        with self.assertRaises(AmbiguityCollapseError):
            det.amount("FAM-AR-02")
        self.assertEqual([s.rule_id for s in det.steps].count("FAM-AR-01"), 2)

    def test_one_figure_on_the_form_is_a_single_step(self):
        from rules.dii import classify_case, determine_family_pension_death_after_retirement
        det = determine_family_pension_death_after_retirement(
            _case(sanctioned_pension=Decimal("82575"), net_pension=Decimal("82575")),
            self._rules(), classify_case(prescribed_form="FORM_D_II"), datetime(2026, 6, 3))
        self.assertEqual(det.ambiguities, ())
        self.assertEqual(det.step("FAM-AR-02").presented, 61_931)      # 82575 x 75% = 61931.25

    def test_a_regrant_with_no_commencement_rule_states_the_dates_and_no_date(self):
        from rules.dii import classify_case, determine_family_pension_death_after_retirement
        klass = classify_case(prescribed_form="FORM_D_II",
                              prior_pensioner_death=date(2018, 1, 30))
        det = determine_family_pension_death_after_retirement(
            _case(claimant_relation="divorce daughter", prior_pensioner_name="Soghran Begum",
                  prior_pensioner_death=date(2018, 1, 30),
                  date_of_death_of_pensioner=date(2010, 5, 23)),
            self._rules(), klass, datetime(2026, 6, 3))
        self.assertEqual(det.step("FAM-AR-03").presented, 1884)
        commence = det.step("FAM-AR-05")
        self.assertIsNone(commence.amount)
        self.assertIn("not determined", commence.computation_shown)
        self.assertIn("2018-01-30", commence.computation_shown)
        self.assertIn("2010-05-23", commence.computation_shown)
        self.assertIn("commencement.on_regrant", det.inputs["provisional_keys"])

    def test_a_confirmation_in_force_makes_the_share_final(self):
        from rules.dii import DIIRules, classify_case, determine_family_pension_death_after_retirement
        rules = DIIRules.load(confirmations=[
            {"key": "share.widow_percent", "value": "75", "authority": "FD-SR-III-4-57/2013"},
            {"key": "base.definition", "value": "pension_in_payment", "authority": "x" * 12},
            {"key": "commencement.on_death_of_pensioner", "value": "day_after_death",
             "authority": "x" * 12},
            # The pensioner died after 2 December 2024, so the spouse's ten-year term
            # (rule 4.10(1) as substituted) is a value in use too and must be confirmed
            # before the determination is final. tests/test_amendment_2024_spouse_term.py.
            {"key": "cessation.spouse_term_years", "value": "10", "authority": "x" * 12},
            {"key": "cessation.spouse_term_applies_to_deaths_from", "value": "2024-12-02",
             "authority": "x" * 12},
        ])
        det = determine_family_pension_death_after_retirement(
            _case(sanctioned_pension=Decimal("50000"), net_pension=Decimal("1066")),
            rules, classify_case(prescribed_form="FORM_D_II"), datetime(2026, 6, 3))
        self.assertFalse(det.provisional)
        self.assertEqual(det.unverified_engaged, ())
        self.assertEqual(det.ambiguities, ())
        self.assertEqual(det.step("FAM-AR-02").presented, 37_500)
        self.assertEqual(det.inputs["provisional_keys"], [])

    def test_a_confirmation_can_overrule_a_provisional_figure(self):
        from rules.dii import DIIRules, classify_case, determine_family_pension_death_after_retirement
        rules = DIIRules.load(confirmations=[{"key": "share.widow_percent", "value": "50"}])
        det = determine_family_pension_death_after_retirement(
            _case(), rules, classify_case(prescribed_form="FORM_D_II"), datetime(2026, 6, 3))
        self.assertEqual(det.step("FAM-AR-02").presented, 1256)      # 2512 x 50%
        self.assertNotIn("share.widow_percent", det.inputs["provisional_keys"])


class RefusingOnAnUnconfirmedRule(unittest.TestCase):
    """Where UNSET cannot be handled honestly, the refusal must name the rule. "Not computed"
    is what cost us the day."""

    def _unset(self):
        import tempfile
        from rules.dii import DIIRules
        tmp = Path(tempfile.mkdtemp()) / "dii.yaml"
        tmp.write_text(
            "id: PB-DII-TEST\n"
            "status: provisional\n"
            "share:\n"
            "  widow_percent: UNSET\n"
            "base:\n"
            "  definition: UNSET\n"
            "commencement:\n"
            "  on_death_of_pensioner: UNSET\n",
            encoding="utf-8",
        )
        return DIIRules.load(tmp, confirmations=[])

    def test_it_refuses_and_names_the_missing_share(self):
        from rules.dii import (RuleNotSet, classify_case,
                               determine_family_pension_death_after_retirement)
        with self.assertRaises(RuleNotSet) as ctx:
            determine_family_pension_death_after_retirement(
                _case(), self._unset(), classify_case(prescribed_form="FORM_D_II"),
                datetime(2026, 6, 3))
        message = str(ctx.exception)
        self.assertIn("share.widow_percent", message)
        self.assertIn("AG Punjab", message)

    def test_it_does_not_fall_back_to_a_default(self):
        from rules.dii import (RuleNotSet, classify_case,
                               determine_family_pension_death_after_retirement)
        with self.assertRaises(RuleNotSet):
            determine_family_pension_death_after_retirement(
                _case(), self._unset(), classify_case(prescribed_form="FORM_D_II"),
                datetime(2026, 6, 3))

    def test_a_refusal_is_not_the_same_exception_as_a_missing_input(self):
        """Four different causes, four different types, so the screen can say which."""
        from rules.dii import (CaseTypeNotDetermined, CaseTypeNotImplemented,
                               DIIError, InputMissing, RuleNotSet)
        for exc in (RuleNotSet, CaseTypeNotDetermined, CaseTypeNotImplemented, InputMissing):
            self.assertTrue(issubclass(exc, DIIError))
        self.assertEqual(len({RuleNotSet, CaseTypeNotDetermined,
                              CaseTypeNotImplemented, InputMissing}), 4)


class ComputingOnceTheRulesAreConfirmed(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.rules = _populated(Path(self._dir.name) / "dii.yaml")

    def tearDown(self):
        self._dir.cleanup()

    def test_a_widow_takes_the_widow_share(self):
        from rules.dii import classify_case, determine_family_pension_death_after_retirement
        det = determine_family_pension_death_after_retirement(
            _case(), self.rules, classify_case(prescribed_form="FORM_D_II"),
            datetime(2026, 6, 3))
        self.assertEqual(det.step("FAM-AR-02").presented, 1884)      # 2512 x 75%

    def test_a_regrant_takes_the_regrant_share_not_the_widow_one(self):
        from rules.dii import classify_case, determine_family_pension_death_after_retirement
        klass = classify_case(prescribed_form="FORM_D_II",
                              prior_pensioner_death=date(2018, 1, 30))
        det = determine_family_pension_death_after_retirement(
            _case(claimant_relation="divorce daughter",
                  prior_pensioner_name="Soghran Begum",
                  prior_pensioner_death=date(2018, 1, 30)),
            self.rules, klass, datetime(2026, 6, 3))
        self.assertEqual(det.step("FAM-AR-03").presented, 1256)      # 2512 x 50%
        self.assertFalse(any(s.rule_id == "FAM-AR-02" for s in det.steps))

    def test_every_input_resolves_in_the_provenance_trail(self):
        """Required for the Annual Certification Audit: each figure traceable to its rule,
        its config value and the page it was read from."""
        from rules.dii import classify_case, determine_family_pension_death_after_retirement
        from rules.dii import Provenance
        det = determine_family_pension_death_after_retirement(
            _case(provenance=(Provenance("pension_drawn_rs", "2512", 7, "FORM_D_II"),)),
            self.rules, classify_case(prescribed_form="FORM_D_II"), datetime(2026, 6, 3))
        trail = det.inputs["provenance"]
        fields = {p["field"]: p for p in trail}
        self.assertIn("pension_drawn_rs", fields)
        self.assertEqual(fields["pension_drawn_rs"]["page"], 7)
        self.assertIn("base.definition", fields)
        self.assertIn("share.widow_percent", fields)
        self.assertTrue(fields["share.widow_percent"]["source"].startswith("rule:"))

    def test_the_determination_records_the_class_and_its_evidence(self):
        from rules.dii import classify_case, determine_family_pension_death_after_retirement
        det = determine_family_pension_death_after_retirement(
            _case(), self.rules, classify_case(prescribed_form="FORM_D_II"),
            datetime(2026, 6, 3))
        self.assertEqual(det.inputs["case_class"], "DEATH_AFTER_RETIREMENT")
        self.assertIn("Form D-II", det.inputs["case_class_evidence"])

    def test_it_keeps_the_recommendation_only_framing(self):
        from rules.dii import classify_case, determine_family_pension_death_after_retirement
        det = determine_family_pension_death_after_retirement(
            _case(), self.rules, classify_case(prescribed_form="FORM_D_II"),
            datetime(2026, 6, 3))
        self.assertTrue(any("Auditor" in c for c in det.caveats))

    def test_an_unreadable_base_refuses_as_a_missing_input_not_a_missing_rule(self):
        from rules.dii import (InputMissing, classify_case,
                               determine_family_pension_death_after_retirement)
        with self.assertRaises(InputMissing):
            determine_family_pension_death_after_retirement(
                _case(sanctioned_pension=None), self.rules,
                classify_case(prescribed_form="FORM_D_II"), datetime(2026, 6, 3))

    def test_an_unknown_relation_is_never_paid_as_a_widow(self):
        from rules.dii import (CaseTypeNotImplemented, classify_case,
                               determine_family_pension_death_after_retirement)
        with self.assertRaises(CaseTypeNotImplemented):
            determine_family_pension_death_after_retirement(
                _case(claimant_relation="nephew"), self.rules,
                classify_case(prescribed_form="FORM_D_II"), datetime(2026, 6, 3))

    def test_a_class_with_no_confirmed_share_refuses_by_name(self):
        from rules.dii import (RuleNotSet, classify_case,
                               determine_family_pension_death_after_retirement)
        with self.assertRaises(RuleNotSet) as ctx:
            determine_family_pension_death_after_retirement(
                _case(claimant_relation="unmarried daughter"), self.rules,
                classify_case(prescribed_form="FORM_D_II"), datetime(2026, 6, 3))
        self.assertIn("unmarried_child_percent", str(ctx.exception))

    def test_the_d_i_calculator_is_never_reached_from_here(self):
        from rules.dii import (CaseTypeNotImplemented, CaseClass, DEATH_IN_SERVICE,
                               determine_family_pension_death_after_retirement)
        with self.assertRaises(CaseTypeNotImplemented):
            determine_family_pension_death_after_retirement(
                _case(), self.rules, CaseClass(DEATH_IN_SERVICE, "in service"),
                datetime(2026, 6, 3))


# ==============================================================================================
# Stage 3: the two identification misreads
# ==============================================================================================

class IdentifyingTheFormsInTheRealBundles(unittest.TestCase):

    def _text(self, body: str):
        from extraction.ocr import PageText
        return PageText(page=1, text=body, model="test")

    def test_page_9_proforma_d_ii_is_a_form_number(self):
        """The divorced-daughter sanction is headed "Proforma D-II", not "Form D-II". OCR
        matched nothing, _verify_form_claim withdrew a CORRECT classification, and the
        prescribed form dropped out of the bundle."""
        from extraction.ocr import forms_printed_on
        self.assertEqual(
            forms_printed_on(self._text(
                "Proforma D-II OFFICE OF THE SUPERINTENDENT, GOVERNMENT PRINTING PRESS")),
            ("FORM_D_II",))

    def test_the_local_spelling_performa_also_reads(self):
        from extraction.ocr import forms_printed_on
        self.assertEqual(forms_printed_on(self._text("Performa D-II")), ("FORM_D_II",))

    def test_form_d_i_still_reads_and_is_not_confused_with_d_ii(self):
        from extraction.ocr import forms_printed_on
        self.assertEqual(forms_printed_on(self._text("FORM D-I")), ("FORM_D_I",))
        self.assertEqual(forms_printed_on(self._text("Form D-II")), ("FORM_D_II",))

    def test_page_5_cnic_reverse_is_not_a_pay_document(self):
        """The model answered LPC at confidence 1.00 for the reverse of a CNIC, citing the
        card's own serial as its evidence."""
        from extraction.ocr import looks_like_identity_card
        self.assertTrue(looks_like_identity_card(self._text(
            "D23M2Q  00001-0000110-4  گمشدہ کارڈ ملنے پر قریبی لیٹر بکس میں ڈال دیں")))

    def test_a_real_last_pay_certificate_is_not_denied(self):
        """A genuine LPC quotes the servant's CNIC too. Denying those would drop the pay
        document the pipeline most needs, so pay vocabulary settles it."""
        from extraction.ocr import looks_like_identity_card
        self.assertFalse(looks_like_identity_card(self._text(
            "LAST PAY CERTIFICATE  Substantive pay 10,395  Officiating pay 861  "
            "DEDUCTION G.P.F.  00001-0000110-4")))


# ==============================================================================================
# What the five real D-II bundles of 16 September taught: the model fills the prior-pensioner
# fields with the claimant, and the forms word the relation five different ways.
# ==============================================================================================

class ThePriorPensionerIsVettedNotBelieved(unittest.TestCase):
    def test_the_claimant_named_as_the_prior_pensioner_is_discarded(self):
        """Ghulam Zainab, the living widow, was reported dead on her retirement date."""
        from rules.dii import vet_prior_pensioner
        name, death, note = vet_prior_pensioner(
            claimant_name="Mst. Ghulam Zainab", deceased_name="Mr. Akbar Hussain",
            prior_name="Mst. Ghulam Zainab", prior_death=date(2023, 6, 20),
            other_dates=(date(2026, 7, 3), date(2023, 6, 20), None))
        self.assertIsNone(name); self.assertIsNone(death)
        self.assertIn("claimant herself", note)
        self.assertIn("first grant", note)

    def test_a_copied_date_alone_is_enough_to_discard(self):
        from rules.dii import vet_prior_pensioner
        name, death, note = vet_prior_pensioner(
            claimant_name="Mst. Sobia Munir", deceased_name="Muhammad Munir",
            prior_name="Mst. Soghran Begum", prior_death=date(2023, 9, 5),
            other_dates=(date(2010, 5, 23), date(1995, 2, 1), date(2023, 9, 5)))
        self.assertIsNone(name)
        self.assertIn("another dated event", note)

    def test_a_genuine_prior_pensioner_is_kept(self):
        from rules.dii import vet_prior_pensioner
        name, death, note = vet_prior_pensioner(
            claimant_name="Mst. Sobia Munir", deceased_name="Muhammad Munir",
            prior_name="Mst. Soghran Begum", prior_death=date(2018, 1, 30),
            other_dates=(date(2010, 5, 23), date(1995, 2, 1), date(2023, 9, 5)))
        self.assertEqual((name, death, note), ("Mst. Soghran Begum", date(2018, 1, 30), None))

    def test_nothing_read_is_nothing_said(self):
        from rules.dii import vet_prior_pensioner
        self.assertEqual(vet_prior_pensioner(claimant_name="A", deceased_name="B",
                                             prior_name=None, prior_death=None),
                         (None, None, None))

    def test_honorifics_do_not_hide_the_same_name(self):
        from rules.dii import _name_key
        self.assertEqual(_name_key("Mst. Gulshan Jan"), _name_key("GULSHAN JAN"))
        self.assertNotEqual(_name_key("Mst. Soghran Begum"), _name_key("Mst. Sobia Munir"))


class TheRelationAsTheFormsWordIt(unittest.TestCase):
    def _key(self, relation):
        from rules.dii import _share_key_for
        return _share_key_for(relation)

    def test_spouse_wordings(self):
        for r in ("widow", "Widow / Widower", "w/o Khan Bahadur", "wife", "Husband"):
            self.assertEqual(self._key(r), "widow_percent", r)

    def test_a_widow_daughter_is_a_daughter_not_a_widow(self):
        self.assertEqual(self._key("widow daughter of late Muhammad Bashir"),
                         "regrant_daughter_percent")
        self.assertEqual(self._key("widowed daughter"), "regrant_daughter_percent")
        self.assertEqual(self._key("divorce daughter"), "regrant_daughter_percent")

    def test_other_children(self):
        self.assertEqual(self._key("unmarried daughter"), "unmarried_child_percent")
        self.assertEqual(self._key("disabled son"), "disabled_child_percent")
        self.assertEqual(self._key("d/o Muhammad Munir"), "unmarried_child_percent")

    def test_the_commencement_rule_is_the_spouses_only(self):
        """A daughter's entitlement arises on her own event, not on the pensioner's death."""
        from rules.dii import DIIRules, classify_case, determine_family_pension_death_after_retirement
        rules = DIIRules.load(confirmations=[])
        det = determine_family_pension_death_after_retirement(
            _case(claimant_relation="divorce daughter",
                  date_of_death_of_pensioner=date(2010, 5, 23),
                  date_of_divorce=date(2023, 9, 5)),
            rules, classify_case(prescribed_form="FORM_D_II"), datetime(2026, 6, 3))
        commence = det.step("FAM-AR-05")
        self.assertIsNone(commence.amount)
        self.assertIn("2023-09-05", commence.computation_shown)
        self.assertNotIn("day_after_death", commence.computation_shown)
        widow = determine_family_pension_death_after_retirement(
            _case(), rules, classify_case(prescribed_form="FORM_D_II"), datetime(2026, 6, 3))
        self.assertIn("day_after_death from 2025-09-17", widow.step("FAM-AR-05").computation_shown)


class TheChecklistColumnFollowsTheClaimant(unittest.TestCase):
    def test_the_stated_relation_beats_the_forms_opening_clause(self):
        from rules import suggest_variant
        from rules.case_type import FAMILY_PENSION_DEATH_AFTER_RETIREMENT
        got = suggest_variant(
            FAMILY_PENSION_DEATH_AFTER_RETIREMENT,
            "Proforma D-II ... Mst. Soghran Begum widow of late Muhammad Munir ...",
            claimant_relation="divorce daughter")
        self.assertEqual(got.variant, "DIVORCED_DAUGHTER")
        self.assertIn("claimant's stated relation", got.evidence)

    def test_widow_daughter_and_w_o(self):
        from rules import suggest_variant
        from rules.case_type import FAMILY_PENSION_DEATH_AFTER_RETIREMENT
        self.assertEqual(suggest_variant(FAMILY_PENSION_DEATH_AFTER_RETIREMENT, "",
                                         claimant_relation="widow daughter of late Muhammad Bashir").variant,
                         "WD_DAUGHTER")
        self.assertEqual(suggest_variant(FAMILY_PENSION_DEATH_AFTER_RETIREMENT, "",
                                         claimant_relation="w/o Khan Bahadur").variant, "WIDOW")
        self.assertEqual(suggest_variant(FAMILY_PENSION_DEATH_AFTER_RETIREMENT, "",
                                         claimant_relation="widow").variant, "WIDOW")

    def test_the_form_text_still_decides_where_no_relation_was_read(self):
        from rules import suggest_variant
        from rules.case_type import FAMILY_PENSION_DEATH_AFTER_RETIREMENT
        got = suggest_variant(FAMILY_PENSION_DEATH_AFTER_RETIREMENT,
                              "IN RESPECT OF MST. GHULAM ZAINAB WIDOW OF AKBAR HUSSAIN")
        self.assertEqual(got.variant, "WIDOW")


if __name__ == "__main__":
    unittest.main()
