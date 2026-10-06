"""The cure loop, the delegation bands and the disposal gates. §7, §13, §15, §17.

R2 is the office's second clarification and the one the whole workflow hangs on: every issue
must accept a document and be re-checked. §7.1 sets out the flow, and what is tested here is
that the loop is the ONLY way an item closes -- there is no mark-as-resolved path, so a cured
observation is closed by the same rule that raised it.

The §17 row "False-positive observations, with §16.3 as permanent regression cases" is in
:mod:`test_regressions`.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gpfund.rules                                                        # noqa: F401
from gpfund import evaluate, load_corpus_case, lists
from gpfund.casefile import CaseFile, DispositionRefused, NotPermitted
from gpfund.disposal import (
    HOLD,
    PASS_FOR_PAYMENT,
    REFER_TO_DAG,
    RETURN,
    disposal_gate,
    dispose,
    issue_pack,
    recalc_breaks,
    reconciles,
)
from gpfund.params import MIN_JUSTIFICATION, may


class ADocumentCuresAnObservation(unittest.TestCase):
    """§7.1, end to end, on the case the office walks through in its own README."""

    def setUp(self) -> None:
        self.case = CaseFile(load_corpus_case("missing-credits"), by="Harness", desk="AO",
                             at="2026-09-18 10:00")

    def test_the_hard_stop_is_the_missing_challan(self):
        """And the variance equals it exactly, which is what makes it actionable (§16.3)."""
        result = self.case.result("MC-CHALLANS")
        self.assertEqual(result.status, "hard")
        self.assertEqual(result.calc["variance"], 7960)
        self.assertIn("Sr. 4", result.finding)

    def test_uploading_the_challan_clears_it(self):
        self.case.upload_against(
            "MC-CHALLANS", file_name="challan-sr4.png", content=b"a scan",
            confirmed={"sr": "4", "amount": "7960", "bankStamp": "yes"},
            by="Sadia Rehman", desk="AO", at="2026-09-18 10:05")
        self.assertEqual(self.case.lists.counts()["hard"], 0)
        self.assertEqual(self.case.version, 2)

    def test_the_whole_case_is_re_evaluated_not_just_the_item(self):
        """§0: an upload changes the facts, and the case is evaluated again from the start."""
        before = {r.id for r in self.case.results}
        self.case.upload_against(
            "MC-CHALLANS", file_name="challan-sr4.png", content=b"a scan",
            confirmed={"sr": "4", "amount": "7960", "bankStamp": "yes"},
            by="Sadia Rehman", desk="AO", at="T1")
        after = {r.id for r in self.case.results}
        self.assertEqual(before, after)
        self.assertIsNotNone(self.case.last_diff)
        self.assertEqual([r.id for r, _ in self.case.last_diff.resolved], ["MC-CHALLANS"])

    def test_the_upload_is_recorded_with_its_hash(self):
        """§15: file name, SHA-256, officer and time against every upload."""
        self.case.upload_against(
            "MC-CHALLANS", file_name="challan-sr4.png", content=b"a scan",
            confirmed={"sr": "4", "amount": "7960", "bankStamp": "yes"},
            by="Sadia Rehman", desk="AO", at="T1")
        record = self.case.uploads[-1]
        self.assertEqual(record.file_name, "challan-sr4.png")
        self.assertEqual(len(record.sha256), 64)
        self.assertEqual(record.by, "Sadia Rehman")
        self.assertEqual(record.at, "T1")

    def test_a_challan_without_a_bank_stamp_does_not_cure_it(self):
        """The substitution rule is conditional: R14 and R15 accept challans that carry the
        bank's stamp. One that does not is still a challan, and still not the evidence."""
        self.case.upload_against(
            "MC-CHALLANS", file_name="challan-sr4.png", content=b"a scan",
            confirmed={"sr": "4", "amount": "7960", "bankStamp": "no"},
            by="Sadia Rehman", desk="AO", at="T1")
        statuses = {r.id: r.status for r in self.case.results}
        self.assertEqual(statuses["MC-DDO-CERT"], "hard")
        self.assertIn("no bank stamp", self.case.result("MC-DDO-CERT").finding)

    def test_an_item_with_no_document_cure_refuses_an_upload(self):
        with self.assertRaises(DispositionRefused):
            self.case.upload_against(
                "DOA:treasury", file_name="x.png", content=b"x", confirmed={},
                by="Sadia Rehman", desk="AO", at="T1")

    def test_there_is_no_way_to_mark_an_item_resolved(self):
        """§0: "There is no separate 'mark as resolved' path that could drift from the
        rules." Asserted against the class itself, because a helper added later with the best
        of intentions is exactly how that path appears."""
        forbidden = [name for name in dir(CaseFile)
                     if any(word in name.lower() for word in ("resolve", "clear", "close",
                                                              "override_status", "set_status"))]
        self.assertEqual(forbidden, [])


class AVerificationBecomesAFact(unittest.TestCase):
    """§7.2 ``verify`` and §7.3. Recording "did not verify" has a consequence."""

    def setUp(self) -> None:
        self.case = CaseFile(load_corpus_case("refundable"), by="Harness", desk="AO", at="T0")

    def test_a_successful_verification_closes_the_task(self):
        self.case.record_verification("DOA:sanction", ok=True,
                                      note="SP Headquarters holds written delegation.",
                                      by="Sadia Rehman", desk="AO", at="T1")
        self.assertEqual({r.id: r.status for r in self.case.results}["DOA:sanction"], "ok")

    def test_a_failed_verification_makes_it_a_hard_stop(self):
        self.case.record_verification("DOA:sanction", ok=False,
                                      note="Not an approved signatory for this unit.",
                                      by="Sadia Rehman", desk="AO", at="T1")
        result = next(r for r in self.case.results if r.id == "DOA:sanction")
        self.assertEqual(result.status, "hard")
        self.assertEqual(result.code, "B1-ii")
        self.assertIn("Not an approved signatory", result.finding)

    def test_the_officer_and_the_time_are_on_the_face_of_the_result(self):
        self.case.record_verification("DOA:sanction", ok=True, note="Checked.",
                                      by="Sadia Rehman", desk="AO", at="2026-09-18 11:00",
                                      designation="Accounts Officer, GP Fund-I")
        result = next(r for r in self.case.results if r.id == "DOA:sanction")
        self.assertIn("Sadia Rehman", result.finding)
        self.assertIn("Accounts Officer, GP Fund-I", result.finding)
        self.assertIn("2026-09-18 11:00", result.finding)

    def test_a_dealing_assistant_may_not_record_a_verification(self):
        """§13.2: recording a verification is the Accounts Officer's or above."""
        with self.assertRaises(NotPermitted):
            self.case.record_verification("DOA:sanction", ok=True, note="x",
                                          by="Muhammad Adnan", desk="DA", at="T1")


class TheDelegationBands(unittest.TestCase):
    """§13.2. Configuration, and open item GPF-O13."""

    def test_the_bands_are_as_the_specification_sets_them(self):
        expected = {
            ("DA", "uphold"): True, ("DA", "upload_document"): True,
            ("DA", "settle_in_office"): False, ("DA", "waive_advisory"): False,
            ("DA", "pass_for_payment"): False, ("DA", "waive_hard"): False,
            ("AO", "settle_in_office"): True, ("AO", "waive_advisory"): True,
            ("AO", "pass_for_payment"): True, ("AO", "waive_hard"): False,
            ("AO", "second_return"): False, ("AO", "upload_specimen"): True,
            ("DAG", "waive_hard"): True, ("DAG", "second_return"): True,
            ("DAG", "add_signatory"): True, ("DAG", "finalise_register"): True,
        }
        for (desk, action), allowed in expected.items():
            with self.subTest(desk=desk, action=action):
                self.assertEqual(may(desk, action), allowed)

    def test_waiving_a_hard_stop_needs_the_dag(self):
        case = CaseFile(load_corpus_case("residual"), by="Harness", desk="AO", at="T0")
        with self.assertRaises(NotPermitted):
            case.dispose_of("FP-GPF10", "waive", by="Sadia Rehman", desk="AO", at="T1",
                            ground="The Form 10 filed with the original payment covers it.",
                            authority="Rule 1.35 Explanation")
        disposition = case.dispose_of(
            "FP-GPF10", "waive", by="Fatima Hameed", desk="DAG", at="T1",
            ground="The Form 10 filed with the original final payment covers the residual.",
            authority="Rule 1.35 Explanation")
        self.assertEqual(disposition.action, "waive")

    def test_a_waiver_needs_a_ground_and_an_authority(self):
        """§8.3 of the SOP-side circular: the ground and the authority are both mandatory."""
        case = CaseFile(load_corpus_case("residual"), by="Harness", desk="AO", at="T0")
        with self.assertRaises(DispositionRefused):
            case.dispose_of("FP-GPF10", "waive", by="Fatima Hameed", desk="DAG", at="T1",
                            ground="ok", authority="Rule 1.35")
        with self.assertRaises(DispositionRefused):
            case.dispose_of("FP-GPF10", "waive", by="Fatima Hameed", desk="DAG", at="T1",
                            ground="A ground long enough to satisfy the floor.", authority="")

    def test_the_justification_floor_is_enforced(self):
        self.assertGreaterEqual(MIN_JUSTIFICATION, 15)


class TheDisposalGates(unittest.TestCase):
    """§13.3, and §14 rule 9 -- the prohibition that governs payment."""

    def test_no_case_is_disposed_of_while_an_observation_is_undisposed(self):
        case = CaseFile(load_corpus_case("fp-death"), by="Harness", desk="AO", at="T0")
        gate = disposal_gate(case, RETURN, "AO")
        self.assertFalse(gate)
        self.assertIn("no disposition recorded", gate.reason)

    def test_a_case_with_nothing_to_say_cannot_be_returned(self):
        case = CaseFile(load_corpus_case("balance-transfer"), by="Harness", desk="AO", at="T0")
        gate = disposal_gate(case, RETURN, "AO")
        self.assertFalse(gate)
        self.assertIn("nothing to return", gate.reason)

    def test_payment_is_blocked_by_a_verification_task(self):
        case = CaseFile(load_corpus_case("fp-non-gazetted"), by="Harness", desk="AO", at="T0")
        for observation in case.lists.observations:
            case.dispose_of(observation.id, "uphold", by="Sadia Rehman", desk="AO", at="T1")
        gate = disposal_gate(case, PASS_FOR_PAYMENT, "AO")
        self.assertFalse(gate)
        self.assertIn("verification task", gate.reason)

    def test_payment_is_blocked_by_an_open_sap_item(self):
        case = CaseFile(load_corpus_case("balance-transfer"), by="Harness", desk="AO", at="T0")
        gate = disposal_gate(case, PASS_FOR_PAYMENT, "AO")
        self.assertFalse(gate)
        self.assertIn("SAP item", gate.reason)

    def test_a_second_return_needs_the_dag(self):
        """Para 3 of the circular."""
        case = CaseFile(load_corpus_case("residual"), by="Harness", desk="AO", at="T0")
        for observation in case.lists.observations:
            case.dispose_of(observation.id, "uphold", by="Sadia Rehman", desk="AO", at="T1")
        dispose(case, RETURN, by="Sadia Rehman", desk="AO", at="T2")
        self.assertEqual(case.returns, 1)
        gate = disposal_gate(case, RETURN, "AO")
        self.assertFalse(gate)
        self.assertIn("second return", gate.reason)
        self.assertEqual(gate.needs_desk, "DAG")
        self.assertTrue(disposal_gate(case, RETURN, "DAG"))

    def test_hold_and_refer_are_always_open(self):
        case = CaseFile(load_corpus_case("fp-death"), by="Harness", desk="DA", at="T0")
        self.assertTrue(disposal_gate(case, HOLD, "DA"))
        for observation in case.lists.observations:
            case.dispose_of(observation.id, "uphold", by="Muhammad Adnan", desk="DA", at="T1")
        self.assertTrue(disposal_gate(case, REFER_TO_DAG, "DA"))

    def test_a_case_never_passes_on_a_report_that_does_not_reconcile(self):
        """§12, last rule. The residual report closes in DEBIT."""
        case = CaseFile(load_corpus_case("residual"), by="Harness", desk="AO", at="T0")
        self.assertFalse(reconciles(case))
        self.assertTrue(recalc_breaks(case))

    def test_the_two_reports_the_specification_names_are_the_two_that_break(self):
        """§12: "Holds on every row except residual 2024-25 and dismissal 2024-25"."""
        from gpfund import CORPUS_ORDER

        broken = {}
        for slug in CORPUS_ORDER:
            case = CaseFile(load_corpus_case(slug), by="Harness", desk="AO", at="T0")
            breaks = recalc_breaks(case)
            if breaks:
                broken[slug] = [b["period"] for b in breaks]
        self.assertEqual(sorted(broken), ["fp-dismissal", "residual"])
        self.assertEqual(broken["residual"], ["01.07.2024 to 30.06.2025"])
        self.assertEqual(broken["fp-dismissal"], ["01.07.2024 to 30.06.2025"])


class TheIssuePack(unittest.TestCase):
    """§13.4. Everything the pack must carry."""

    def _disposed_case(self) -> CaseFile:
        case = CaseFile(load_corpus_case("fp-death"), by="Harness", desk="AO", at="T0")
        for observation in case.lists.observations:
            case.dispose_of(observation.id, "uphold", by="Sadia Rehman", desk="AO", at="T1")
        dispose(case, RETURN, by="Sadia Rehman", desk="AO", at="T2",
                note="Returned with four shortcomings.")
        return case

    def test_the_pack_carries_every_part_the_specification_lists(self):
        pack = issue_pack(self._disposed_case())
        for key in ("rejection_form", "advisory_memorandum", "verifications_recorded",
                    "sap_items", "office_copy", "all_checks", "uploads", "sap_extracts",
                    "case_history", "audit_trail", "payment_register_entry", "portal_comment",
                    "rule_set"):
            with self.subTest(part=key):
                self.assertIn(key, pack)

    def test_missing_and_defective_go_on_separate_lists(self):
        pack = issue_pack(self._disposed_case())
        self.assertEqual(len(pack["rejection_form"]), 4)
        self.assertEqual(len(pack["advisory_memorandum"]), 4)

    def test_the_office_s_own_work_is_not_on_the_department_s_form(self):
        """§6.1 and §14 rule 9: an SAP item or a verification is never a department defect."""
        pack = issue_pack(self._disposed_case())
        department_ids = {line["id"] for line in pack["rejection_form"]} | \
                         {line["id"] for line in pack["advisory_memorandum"]}
        office_ids = {line["id"] for line in pack["verifications_recorded"]} | \
                     {line["id"] for line in pack["sap_items"]}
        self.assertEqual(department_ids & office_ids, set())

    def test_every_line_on_the_form_carries_a_code_and_a_remedy(self):
        pack = issue_pack(self._disposed_case())
        for line in pack["rejection_form"]:
            with self.subTest(line=line["id"]):
                self.assertTrue(line["code"])
                self.assertTrue(line["remedy"])

    def test_the_portal_comment_quotes_no_code_at_the_subscriber(self):
        """The codes are the office's internal reference; what the subscriber needs to know is
        whether anything is required of them."""
        pack = issue_pack(self._disposed_case())
        comment = pack["portal_comment"]
        self.assertIn("You need do nothing", comment)
        for code in ("B2-i", "A2-iv", "A2-vi", "B2-viii", "R11", "R13"):
            self.assertNotIn(code, comment)

    def test_the_rule_set_is_recorded_on_the_pack(self):
        """§15: a case is re-checked against the rule set in force when it was examined."""
        pack = issue_pack(self._disposed_case())
        self.assertIn("circular", pack["rule_set"])
        self.assertIn("21.12.2023", pack["rule_set"]["circular"])
        self.assertIn("R1 to R15", pack["rule_set"]["office_clarifications"])


class TheAuditTrail(unittest.TestCase):
    """§15. Append-only, with actor, desk, time, case version and before/after."""

    def test_the_log_cannot_be_amended_or_removed_from(self):
        case = CaseFile(load_corpus_case("refundable"), by="Harness", desk="AO", at="T0")
        log = case.audit
        self.assertIsInstance(log, tuple)
        with self.assertRaises(AttributeError):
            log.append("a forged entry")             # type: ignore[attr-defined]

    def test_every_action_is_logged_with_its_actor_and_version(self):
        case = CaseFile(load_corpus_case("missing-credits"), by="Harness", desk="AO", at="T0")
        case.upload_against("MC-CHALLANS", file_name="c.png", content=b"x",
                            confirmed={"sr": "4", "amount": "7960", "bankStamp": "yes"},
                            by="Sadia Rehman", desk="AO", at="T1")
        actions = [entry.action for entry in case.audit]
        self.assertEqual(actions, ["evaluate", "upload", "evaluate"])
        for entry in case.audit:
            with self.subTest(action=entry.action):
                self.assertTrue(entry.by)
                self.assertTrue(entry.desk)
                self.assertTrue(entry.at)
                self.assertGreaterEqual(entry.case_version, 1)
                self.assertIn("circular", entry.rule_set)

    def test_a_refused_sap_extract_is_still_logged(self):
        """§6.1: "the rejection is logged"."""
        case = CaseFile(load_corpus_case("refundable"), by="Harness", desk="AO", at="T0")
        case.log_sap_rejection("SAP_EXTRACT_90000374.txt",
                               "belongs to a different employee", by="Sadia Rehman",
                               desk="AO", at="T1")
        self.assertEqual(case.audit[-1].action, "sap-rejected")
        self.assertIn("different employee", case.audit[-1].detail)

    def test_the_grade_is_recorded_beside_the_desk(self):
        case = CaseFile(load_corpus_case("refundable"), by="Harness", desk="DAG", at="T0")
        self.assertEqual(case.audit[0].grade, "BS-20")


if __name__ == "__main__":
    unittest.main()
