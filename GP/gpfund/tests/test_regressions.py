"""What the office's review overturned, and what the module must never do. §14, §16.3, §17.

§16.3 is a table of findings revision 1 raised that were wrong, or that the office does not
want raised. The specification is explicit about their status: *they are regression cases for
the evaluation harness*, and §17 names the target -- false-positive observations at 2% or
less, "with §16.3 as permanent regression cases".

They are here as tests rather than as a note because each one is a real letter that went, or
would have gone, to a department. A build that quietly reintroduces any of them is a build
that asks a department to cure something it did not do.

§14's fourteen prohibitions follow. Most are properties of code rather than outcomes on a
case, and where that is so the test says how it is held.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gpfund.rules                                                        # noqa: F401
from gpfund import CORPUS_ORDER, evaluate, lists, load_corpus_case
from gpfund.contracts import ADV, CONF, HARD, NA, OK, SAP, SUB


def status_of(slug: str) -> dict[str, str]:
    return {r.id: r.status for r in evaluate(load_corpus_case(slug))}


def result_of(slug: str, result_id: str):
    return next(r for r in evaluate(load_corpus_case(slug)) if r.id == result_id)


class BalanceTransferHasNoHardStops(unittest.TestCase):
    """§16.3 row 1. Revision 1 raised FOUR hard stops on a one-page proforma.

    "The personnel number keys the GP Fund account in SAP and the DAO confirmed it; the
    posting periods satisfy a required particular; forwarding letters are accepted (R3)."
    """

    def test_no_hard_stop_at_all(self):
        self.assertEqual(lists(evaluate(load_corpus_case("balance-transfer"))).hard, ())

    def test_the_personnel_number_in_column_5_is_accepted_on_the_dao_confirmation(self):
        result = result_of("balance-transfer", "BT-PROFORMA:dao-ac")
        self.assertEqual(result.status, OK)
        self.assertIn("keys the GP Fund account in SAP", result.finding)
        self.assertIn("respective DAO has confirmed", result.finding)

    def test_the_posting_periods_satisfy_the_particular(self):
        result = result_of("balance-transfer", "BT-PROFORMA:periods")
        self.assertEqual(result.status, OK)

    def test_the_old_account_column_waits_for_sap_rather_than_accusing_the_department(self):
        """§5.5: the old account number is read from SAP "before anything is raised against
        the department"."""
        result = result_of("balance-transfer", "BT-PROFORMA:old-ac")
        self.assertEqual(result.status, SAP)
        self.assertIn("before treating it as a department defect", result.finding)

    def test_the_forwarding_note_is_recorded_and_never_raised(self):
        result = result_of("balance-transfer", "COVER")
        self.assertEqual(result.status, OK)
        self.assertIn("R3", result.finding)


class MissingCreditsHasOneHardStopNotAnUnactionableCase(unittest.TestCase):
    """§16.3 row 2. Revision 1: "No certificate and unknown gazetted status: unactionable"."""

    def test_the_challans_substitute_for_both_certificates(self):
        statuses = status_of("missing-credits")
        self.assertEqual(statuses["MC-DDO-CERT"], SUB)      # R14
        self.assertEqual(statuses["MC-AG-CERT"], SUB)       # R15

    def test_an_unknown_gazetted_status_does_not_block(self):
        result = result_of("missing-credits", "MC-GAZ")
        self.assertEqual(result.status, SAP)
        self.assertIn("does not block", result.finding)

    def test_the_only_hard_stop_is_the_missing_challan(self):
        self.assertEqual([r.id for r in lists(evaluate(load_corpus_case("missing-credits"))).hard],
                         ["MC-CHALLANS"])


class TheOfficeSOwnHandIsNeverADepartmentEntry(unittest.TestCase):
    """§16.3 rows 3 and 4, and lesson 1: "Tell the department's hand from the office's hand."

    Revision 1 read the AG office's own pre-audit computations, written on a department form,
    as the department's figures -- twice. On the non-refundable case it reported Rs 12,274
    "struck off by the department"; on the dismissal case it reported two net payables on one
    sheet and a date off by one day. All four were the section's working.
    """

    def test_the_non_refundable_annotation_is_section_working(self):
        result = result_of("non-refundable", "NR-OFFICE-ANNOT")
        self.assertEqual(result.status, CONF)
        self.assertIn("Not a department defect", result.finding)
        self.assertEqual(result.code, "OFF_LIST")

    def test_sap_posts_the_full_non_refundable_amount(self):
        """The annotation changed nothing in SAP, which is how it is known to be working."""
        facts = load_corpus_case("non-refundable")
        posted = [r for r in facts.recalc_rows if r.get("permanentAdvance") == 490955]
        self.assertEqual(len(posted), 1)

    def test_the_dismissal_computations_are_section_working(self):
        result = result_of("fp-dismissal", "DIS-INTEREST")
        self.assertEqual(result.status, CONF)
        self.assertIn("section’s own working, not a department defect", result.finding)

    def test_the_dismissal_case_has_no_hard_stop(self):
        """Every circular document except the Service Book is in the scan."""
        self.assertEqual(lists(evaluate(load_corpus_case("fp-dismissal"))).hard, ())


class TheNonGazettedMisreadingsAreGone(unittest.TestCase):
    """§16.3 row 5. "For the month of" is the processing month; the code is LO5361."""

    def test_the_processing_month_is_not_read_as_a_deduction_month(self):
        form = load_corpus_case("fp-non-gazetted").doc("changeForm")
        self.assertIn("processing month", form["note"])
        self.assertEqual(status_of("fp-non-gazetted")["FP-FORM06"], OK)

    def test_the_ddo_code_is_not_misread(self):
        payslip = load_corpus_case("fp-non-gazetted").sap_payslip
        self.assertTrue(payslip["ddoCode"].startswith("LO5361"))

    def test_the_missing_old_account_number_is_an_observation_not_a_hard_stop(self):
        """SAP holds it, so §5.3's "missing identifiers held in SAP reduce to adv" applies."""
        result = result_of("fp-non-gazetted", "FP-GPF10")
        self.assertEqual(result.status, ADV)
        self.assertIn("noted only", result.finding)

    def test_the_scale_discrepancy_is_recorded_and_not_raised(self):
        """§14 rule 2: not on the circular's list, and it cannot change a GP Fund payment."""
        result = result_of("fp-non-gazetted", "NG-SCALE")
        self.assertEqual(result.status, OK)
        self.assertIn("not raised", result.finding)


class TheResidualCaseRaisesNeitherOfTheTwoWrongThings(unittest.TestCase):
    """§16.3 row 6. "SAP keys on the personnel number and the ledger opens at nil; R3"."""

    def test_the_absent_old_account_number_is_explained_not_raised(self):
        result = result_of("residual", "FP-OLDAC")
        self.assertEqual(result.status, OK)
        self.assertIn("opens at nil", result.finding)

    def test_the_subscriber_s_own_application_is_accepted_as_the_covering_letter(self):
        result = result_of("residual", "COVER")
        self.assertEqual(result.status, OK)

    def test_the_one_hard_stop_is_the_absent_form_10(self):
        self.assertEqual([r.id for r in lists(evaluate(load_corpus_case("residual"))).hard],
                         ["FP-GPF10"])


class TheRefundableCaseRaisesNeitherOfTheTwoWrongThings(unittest.TestCase):
    """§16.3 row 7. "Unattested CNIC and eleven blank Form 5 fields as hard stops" -> R5, R6."""

    def test_an_unattested_cnic_is_an_observation(self):
        card = load_corpus_case("refundable").cnics[0]
        result = result_of("refundable", f"CNIC-ATTEST:p{card['page']}")
        self.assertEqual(result.status, ADV)
        self.assertIn("not required", result.finding)
        self.assertEqual(result.remedy, "None required. Noted for the department’s record.")

    def test_only_the_personal_number_and_signatures_are_examined_on_form_5(self):
        result = result_of("refundable", "ADV-FORM")
        self.assertEqual(result.status, OK)
        self.assertIn("loan details box is not examined", result.finding)

    def test_a_sanction_with_no_qr_code_does_not_trigger_b1_iii(self):
        """§9.2: B1-iii concerns a QR-coded sanction the department has not verified."""
        result = result_of("refundable", "QR-SANCTION")
        self.assertEqual(result.status, NA)
        self.assertIn("carries no QR code", result.finding)

    def test_the_case_has_no_hard_stop(self):
        self.assertEqual(lists(evaluate(load_corpus_case("refundable"))).hard, ())


class TheDeathCaseClaimNowReconciles(unittest.TestCase):
    """§16.3 row 8. Revision 1: the figure was "not derivable", the advance never set off, and
    no succession certificate."""

    def test_the_claim_reconciles_to_the_report(self):
        result = result_of("fp-death", "DEATH-CLAIM")
        self.assertEqual(result.status, OK)
        self.assertIn("87,182", result.finding)
        self.assertIn("five months", result.finding)

    def test_the_unrecovered_advance_is_already_netted(self):
        result = result_of("fp-death", "DEATH-CLAIM")
        self.assertIn("Rs 60,000", result.finding)
        self.assertIn("already netted", result.finding)

    def test_no_succession_certificate_is_required(self):
        """One widow, and the heirs are all family, so circular A.2(vi) does not require one."""
        result = result_of("fp-death", "DEATH-SUCCESSION")
        self.assertEqual(result.status, OK)
        self.assertIn("Not required", result.finding)

    def test_the_statutory_guard_agrees_on_these_claimants(self):
        """§5.3's guard fires only where a payee is OUTSIDE Rule 1.2(1)(c). Here all three
        are family, so section 4(1)(c) does not bite -- and the guard says so rather than
        staying silent, so an auditor can see the question was asked."""
        result = result_of("fp-death", "DEATH-SECTION4")
        self.assertEqual(result.status, OK)
        self.assertIn("Rule 1.2(1)(c)", result.finding)

    def test_the_guard_does_fire_for_a_payee_outside_the_family(self):
        facts = load_corpus_case("fp-death").with_changes(
            lambda data: data["docs"]["death"]["heirs"].append(
                {"name": "A Creditor", "relation": "assignee", "cnicCopy": True}))
        result = next(r for r in evaluate(facts) if r.id == "DEATH-SECTION4")
        self.assertEqual(result.status, CONF)
        self.assertIn("section 4(1)(c)", result.finding)
        self.assertIn("This stands even where an OSD post", result.finding)


class AFinalPaymentAlreadyPostedIsNotADoublePayment(unittest.TestCase):
    """§16.3 lesson 5, and §12. The corpus is retrospective."""

    def test_all_three_final_payments_are_posted_and_none_is_an_accusation(self):
        for slug in ("fp-non-gazetted", "fp-death", "fp-dismissal"):
            with self.subTest(case=slug):
                result = result_of(slug, "FP-POSTED")
                self.assertEqual(result.status, CONF)
                self.assertIn("most likely the claim itself", result.finding)
                self.assertIn("record the pay order", result.remedy)

    def test_the_alternative_is_stated_without_being_alleged(self):
        result = result_of("fp-death", "FP-POSTED")
        self.assertIn("If it were a separate earlier payment", result.finding)

    def test_what_is_left_after_the_posting_is_a_residual(self):
        for slug, left in (("fp-non-gazetted", "8,154"), ("fp-death", "9,131")):
            with self.subTest(case=slug):
                result = result_of(slug, "FP-RESIDUAL")
                self.assertEqual(result.status, ADV)
                self.assertIn(left, result.finding)


class APartialScanIsNotAMissingDocument(unittest.TestCase):
    """§16.3 lesson 6. "Entries not on the pages scanned are checked on the original"."""

    def test_a_service_book_scanned_in_part_is_a_verification_not_a_hard_stop(self):
        result = result_of("fp-non-gazetted", "FP-SB")
        self.assertEqual(result.status, CONF)
        self.assertIn("does not show they are missing from the original", result.finding)

    def test_a_service_book_reported_attached_is_a_verification(self):
        result = result_of("fp-dismissal", "FP-SB")
        self.assertEqual(result.status, CONF)
        self.assertIn("not in the scanned case", result.finding)

    def test_a_service_book_that_is_simply_absent_is_a_hard_stop(self):
        """The distinction has to hold in both directions, or it is not a distinction."""
        result = result_of("fp-death", "FP-SB")
        self.assertEqual(result.status, HARD)
        self.assertIn("No Service Book is on file", result.finding)


class TheFourteenProhibitions(unittest.TestCase):
    """§14. What the module must never do."""

    def test_1_nothing_is_approved_rejected_or_sanctioned(self):
        """"It recommends; the officer disposes." No status means approved, and every
        disposal goes through a gate that names a desk."""
        from gpfund.contracts import STATUSES
        for word in ("approve", "approved", "reject", "sanctioned", "granted"):
            self.assertNotIn(word, STATUSES)

    def test_2_every_finding_cites_an_authority(self):
        for slug in CORPUS_ORDER:
            for result in evaluate(load_corpus_case(slug)):
                if result.status in (HARD, ADV):
                    with self.subTest(case=slug, result=result.id):
                        self.assertTrue(result.ref.strip(),
                                        f"{result.id} is raised against no authority")

    def test_3_the_covering_letter_is_never_raised(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                cover = next((r for r in evaluate(load_corpus_case(slug)) if r.id == "COVER"),
                             None)
                if cover is not None:
                    self.assertEqual(cover.status, OK)

    def test_4_attestation_is_never_more_than_an_observation(self):
        for slug in CORPUS_ORDER:
            for result in evaluate(load_corpus_case(slug)):
                if result.id.startswith("CNIC-ATTEST") or result.id == "PAYSLIP-ATTEST":
                    with self.subTest(case=slug, result=result.id):
                        self.assertIn(result.status, (OK, ADV))

    def test_5_no_fingerprint_match_or_mismatch_is_ever_claimed(self):
        """§10: tested on the whole corpus and not feasible. Do not build it."""
        for slug in CORPUS_ORDER:
            for result in evaluate(load_corpus_case(slug)):
                if result.id.startswith("THUMB"):
                    with self.subTest(case=slug, result=result.id):
                        self.assertEqual(result.status, CONF)
                        self.assertIn("does not match thumb impressions", result.finding)
                        for word in ("matched", "mismatch", "does match", "identical"):
                            self.assertNotIn(word, result.finding.lower())

    def test_5b_no_fingerprint_matcher_exists_in_the_package(self):
        """The prohibition is "do not build it", so the test is about the code, not a case."""
        import re
        banned = re.compile(r"\b(minutia|minutiae|gabor|ridge_|fingerprint_match)\b", re.I)
        for path in sorted((ROOT / "gpfund").glob("*.py")):
            with self.subTest(module=path.name):
                code = "\n".join(line.split("#")[0] for line in path.read_text().splitlines())
                self.assertEqual(banned.findall(code), [])

    def test_6_no_signature_is_passed_or_failed_from_a_score(self):
        for slug in CORPUS_ORDER:
            for result in evaluate(load_corpus_case(slug)):
                if result.pair or result.id.startswith("DOA:"):
                    with self.subTest(case=slug, result=result.id):
                        self.assertNotIn("similarity", result.finding.lower())

    def test_7_a_provisional_register_raises_no_hard_stop(self):
        for slug in CORPUS_ORDER:
            for result in evaluate(load_corpus_case(slug)):
                if result.id.startswith("DOA:"):
                    with self.subTest(case=slug, result=result.id):
                        self.assertNotEqual(result.status, HARD)

    def test_8_a_limit_is_never_tested_against_a_balance_that_includes_the_advance(self):
        from gpfund.rules_advances import balance_before
        for slug in ("refundable", "non-refundable"):
            with self.subTest(case=slug):
                facts = load_corpus_case(slug)
                basis = balance_before(facts)
                self.assertNotEqual(basis["value"], facts.sap_payslip["gpfBalance"])
                self.assertTrue(basis["posted"])

    def test_9_payment_is_blocked_while_anything_is_open(self):
        from gpfund.casefile import CaseFile
        from gpfund.disposal import PASS_FOR_PAYMENT, disposal_gate
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                case = CaseFile(load_corpus_case(slug), by="H", desk="AO", at="T0")
                for observation in case.lists.observations:
                    case.dispose_of(observation.id, "uphold", by="H", desk="AO", at="T1")
                if case.lists.verifications or case.lists.sap or case.lists.hard:
                    self.assertFalse(disposal_gate(case, PASS_FOR_PAYMENT, "AO"))

    def test_10_a_below_threshold_field_is_never_accepted_silently(self):
        """§4.5: the thresholds exist and the financially material ones are the strictest."""
        from gpfund.params import threshold_for
        self.assertEqual(threshold_for("amount"), 0.95)
        self.assertEqual(threshold_for("cnic"), 0.95)
        self.assertEqual(threshold_for("persNo"), 0.95)
        # Anything unlisted falls to the loosest class, so a new financially material field
        # has to be added deliberately rather than inheriting leniency.
        self.assertEqual(threshold_for("some_new_field"), 0.70)

    def test_11_no_case_data_leaves_the_package(self):
        """§14 rule 11: nothing leaves the Sparks. The decision layer opens no socket."""
        import re
        banned = re.compile(r"\b(requests\.|urllib|httpx|socket\.|http\.client|smtplib)\b")
        for path in sorted((ROOT / "gpfund").glob("*.py")):
            with self.subTest(module=path.name):
                code = "\n".join(line.split("#")[0] for line in path.read_text().splitlines())
                self.assertEqual(banned.findall(code), [],
                                 f"gpfund/{path.name} can reach the network")

    def test_the_seventh_status_exists_so_the_office_s_work_is_never_a_defect(self):
        """§6.1: a missing extract is an action for this section, not a department defect."""
        for slug in ("missing-credits", "balance-transfer"):
            with self.subTest(case=slug):
                for result in evaluate(load_corpus_case(slug)):
                    if result.status == SAP:
                        self.assertNotIn(result.status, (HARD, ADV))


if __name__ == "__main__":
    unittest.main()
