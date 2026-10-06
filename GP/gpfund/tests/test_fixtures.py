"""The acceptance test. Build specification §16.2 and §17, first row.

    Evaluated by the prototype's rules engine on the case facts. A build that does not
    produce these results from these facts is not working.

So this file pins the four numbers for each of the eight cases, every check id and status in
each, and the same for every case run WITHOUT its SAP pages. Any change to a rule that moves
one of these numbers is a change to what the office is told about a real case, and needs a
reviewed fixture update -- which is exactly the gate §17 asks for.
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
from gpfund.engine import CHECKS, CUSTOM_CHECKS, unknown_custom_checks

#: §16.2, exactly as the table prints it: (hard, observations, verification tasks, SAP items).
ACCEPTANCE: dict[str, tuple[int, int, int, int]] = {
    "fp-non-gazetted": (0, 3, 5, 0),
    "fp-death": (4, 4, 7, 0),
    "fp-dismissal": (0, 4, 6, 0),
    "missing-credits": (1, 1, 1, 4),
    "residual": (1, 1, 2, 0),
    "refundable": (0, 2, 4, 0),
    "non-refundable": (0, 2, 4, 0),
    "balance-transfer": (0, 0, 2, 5),
}

#: Which results carry each case. Taken from the prototype's own harness, which §16.2 makes
#: the behavioural reference. Keyed by result id so a rename is caught, not just a count.
EXPECTED_HARD: dict[str, tuple[str, ...]] = {
    "fp-non-gazetted": (),
    "fp-death": ("FP-GPF10", "FP-SB", "DEATH-HEIRS", "DEATH-AFFIDAVIT",),
    "fp-dismissal": (),
    "missing-credits": ("MC-CHALLANS",),
    "residual": ("FP-GPF10",),
    "refundable": (),
    "non-refundable": (),
    "balance-transfer": (),
}

EXPECTED_ADVISORY: dict[str, tuple[str, ...]] = {
    "fp-non-gazetted": ("PAYSLIP-ATTEST", "FP-GPF10", "FP-RESIDUAL",),
    "fp-death": ("QR:decline-qr", "QR:frc-qr", "QR:death-cert-qr", "FP-RESIDUAL",),
    "fp-dismissal": ("CNIC-ATTEST:p6", "PAYSLIP-ATTEST", "QR:order-qr", "QR:cnic-back",),
    "missing-credits": ("MC-STAMP:p2",),
    "residual": ("QR:cnic-back",),
    "refundable": ("CNIC-ATTEST:p2", "PAYSLIP-ATTEST",),
    "non-refundable": ("PAYSLIP-ATTEST", "ADV-FORM-CNIC",),
    "balance-transfer": (),
}

EXPECTED_VERIFICATIONS: dict[str, tuple[str, ...]] = {
    "fp-non-gazetted": ("DOA:gpf10-ddo", "FP-SB", "FP-POSTED", "NG-ADJUST", "NG-PERIOD",),
    "fp-death": ("DOA:gpf10-ddo", "THUMB:gpf10", "THUMB:form06", "FP-POSTED", "DEATH-PERSNO",
                 "DEATH-POSTDEATH", "DEATH-PERIOD"),
    "fp-dismissal": ("DOA:form06-ddo", "FP-SB", "FP-POSTED", "DIS-APPEAL", "DIS-CREDITS", "DIS-INTEREST"),
    "missing-credits": ("DOA:treasury",),
    "residual": ("DOA:form06-ddo", "RES-RECON",),
    "refundable": ("DOA:sanction", "DOA:form05-ddo", "SIG-CNIC", "REF-PAYROLL-UNIT",),
    "non-refundable": ("DOA:sanction", "DOA:form06-ddo", "SIG-CNIC", "NR-OFFICE-ANNOT",),
    "balance-transfer": ("DOA:ddo", "DOA:dao",),
}

EXPECTED_SAP: dict[str, tuple[str, ...]] = {
    "fp-non-gazetted": (),
    "fp-death": (),
    "fp-dismissal": (),
    "missing-credits": ("SAP-PAYSLIP", "SAP-RECALC", "MC-GAZ", "MC-NAME",),
    "residual": (),
    "refundable": (),
    "non-refundable": (),
    "balance-transfer": ("SAP-PAYSLIP", "SAP-RECALC", "BT-PROFORMA:old-ac", "BT-PROFORMA:last-ded",
                 "BT-PROFORMA:adv12"),
}

#: The same cases with their SAP pages removed. §16.2, last paragraph: "the SAP-dependent
#: checks must WAIT (`sap`) rather than pass".
ACCEPTANCE_WITHOUT_SAP: dict[str, tuple[int, int, int, int]] = {
    "fp-non-gazetted": (1, 0, 2, 2),
    "fp-death": (4, 3, 4, 4),
    "fp-dismissal": (0, 3, 3, 3),
    "missing-credits": (1, 1, 1, 4),
    "residual": (1, 1, 1, 4),
    "refundable": (0, 1, 3, 5),
    "non-refundable": (0, 1, 4, 4),
    "balance-transfer": (0, 0, 2, 5),
}


class TheEightCasesProduceTheAcceptanceResults(unittest.TestCase):
    """§16.2. The numbers the office signed off on."""

    def test_every_case_produces_its_four_numbers(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                found = lists(evaluate(load_corpus_case(slug)))
                self.assertEqual(
                    (len(found.hard), len(found.advisory), len(found.verifications),
                     len(found.sap)),
                    ACCEPTANCE[slug],
                    f"{slug}: hard/observations/verifications/SAP items moved. A change here is "
                    f"a change to what the office is told about a real case.")

    def test_the_hard_stops_are_the_expected_items(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                found = lists(evaluate(load_corpus_case(slug)))
                self.assertEqual(tuple(r.id for r in found.hard), EXPECTED_HARD[slug])

    def test_the_observations_are_the_expected_items(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                found = lists(evaluate(load_corpus_case(slug)))
                self.assertEqual(tuple(r.id for r in found.advisory), EXPECTED_ADVISORY[slug])

    def test_the_verification_tasks_are_the_expected_items(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                found = lists(evaluate(load_corpus_case(slug)))
                self.assertEqual(tuple(r.id for r in found.verifications),
                                 EXPECTED_VERIFICATIONS[slug])

    def test_the_sap_items_are_the_expected_items(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                found = lists(evaluate(load_corpus_case(slug)))
                self.assertEqual(tuple(r.id for r in found.sap), EXPECTED_SAP[slug])

    def test_hard_stops_lead_the_observation_list(self):
        """The rejection form leads with what stops the case. §13.1."""
        found = lists(evaluate(load_corpus_case("fp-death")))
        statuses = [r.status for r in found.observations]
        self.assertEqual(statuses, ["hard"] * 4 + ["adv"] * 4)


class EveryCaseAlsoRunsWithoutItsSapPages(unittest.TestCase):
    """§16.2, last paragraph. The half that catches a silent pass.

    "Also run each case with its SAP pages removed. The SAP-dependent checks must wait
    (`sap`) rather than pass." A build where a missing extract lets a limit test through is
    the defect the office found in revision 1, when every case had been judged without the
    pay slip and the re-calculation report.
    """

    def test_every_case_produces_its_four_numbers(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                found = lists(evaluate(load_corpus_case(slug).without_sap()))
                self.assertEqual(
                    (len(found.hard), len(found.advisory), len(found.verifications),
                     len(found.sap)),
                    ACCEPTANCE_WITHOUT_SAP[slug])

    def test_no_sap_dependent_check_passes_without_sap(self):
        """The specific prohibition: none of these may be ``ok`` with no extract."""
        must_wait = {"SAP-PAYSLIP", "SAP-RECALC"}
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                statuses = {r.id: r.status for r in evaluate(load_corpus_case(slug).without_sap())}
                for check_id in must_wait:
                    self.assertEqual(statuses.get(check_id), "sap",
                                     f"{slug}: {check_id} must wait for the extract, not pass.")

    def test_the_limit_test_never_passes_on_no_balance(self):
        """§11.2: with no balance the limit test waits. A limit tested against nothing is the
        one arithmetic error in this module that would authorise a payment."""
        for slug in ("refundable", "non-refundable"):
            with self.subTest(case=slug):
                statuses = {r.id: r.status for r in evaluate(load_corpus_case(slug).without_sap())}
                self.assertEqual(statuses.get("ADV-LIMIT"), "sap")

    #: The one result that legitimately does NOT come back when the section uploads the
    #: extract itself. R5 makes an unattested pay slip an observation because a DEPARTMENT
    #: supplied the copy; an extract this office pulled from SAP raises no attestation
    #: question at all, so the check stops applying rather than passing.
    UPLOAD_ONLY_DIFFERENCE = "PAYSLIP-ATTEST"

    def test_uploading_the_extract_returns_the_case_to_its_results(self):
        """§16.2: "uploading the sample extract must return each case to the results above".

        Asserted result by result rather than by count, and with the single documented
        exception named. Comparing only the four numbers would have let a real change hide
        behind a compensating one.
        """
        from gpfund.casefile import CaseFile
        from gpfund.sap import ManualUploadConnector

        samples = ROOT / "agofficegpfund" / "prototype" / "sap-samples"
        connector = ManualUploadConnector()
        for slug in ("refundable", "non-refundable", "fp-non-gazetted", "fp-death",
                     "fp-dismissal", "residual"):
            with self.subTest(case=slug):
                facts = load_corpus_case(slug)
                sample = samples / f"SAP_EXTRACT_{facts.personnel_no}.txt"
                self.assertTrue(sample.exists(), f"no sample extract for {slug}")

                as_received = {r.id: r.status for r in evaluate(facts)}
                case = CaseFile(facts.without_sap(), by="Harness", desk="AO", at="T0")
                self.assertTrue(case.lists.sap, f"{slug}: nothing was waiting for SAP")

                extract = connector.accept_upload(sample.name, sample.read_text(), facts,
                                                  officer="Harness", at="T1")
                case.accept_sap_extract(extract, by="Harness", desk="AO", at="T1")
                after = {r.id: r.status for r in case.results}

                self.assertEqual(case.lists.sap, (),
                                 f"{slug}: items are still waiting for SAP after the upload")
                expected = {k: v for k, v in as_received.items()
                            if k != self.UPLOAD_ONLY_DIFFERENCE}
                self.assertEqual({k: v for k, v in after.items()
                                  if k != self.UPLOAD_ONLY_DIFFERENCE}, expected,
                                 f"{slug}: uploading the extract did not reproduce the results")
                self.assertNotIn(self.UPLOAD_ONLY_DIFFERENCE, after)


class TheCatalogueIsWhollyLoaded(unittest.TestCase):
    """A case judged by fewer rules than the office expects looks exactly like a clean case."""

    def test_every_registered_check_has_an_authority(self):
        """§14 rule 2: nothing outside the circular, the Rules or the clarifications without a
        recorded justification. Every check names its authority in ``ref``."""
        for entry in list(CHECKS) + list(CUSTOM_CHECKS.values()):
            with self.subTest(check=entry.id):
                self.assertTrue(entry.ref.strip(), f"{entry.id} cites no authority")
                self.assertTrue(entry.title.strip(), f"{entry.id} has no title")

    def test_no_case_asks_for_a_check_this_build_lacks(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                self.assertEqual(unknown_custom_checks(load_corpus_case(slug)), ())

    def test_every_cure_a_rule_offers_can_be_applied(self):
        from gpfund.cures import missing_mappings

        self.assertEqual(missing_mappings(), ())

    def test_every_result_carries_a_code_for_the_form(self):
        """§4.4: ``code`` is what prints on the rejection form. A hard stop with no code is a
        line an officer cannot put on a form."""
        for slug in CORPUS_ORDER:
            for result in evaluate(load_corpus_case(slug)):
                if result.status in ("hard", "adv"):
                    with self.subTest(case=slug, result=result.id):
                        self.assertTrue(result.code.strip())

    def test_every_hard_stop_tells_the_department_what_to_do(self):
        """A defect with no remedy is a case that goes back and forward twice."""
        for slug in CORPUS_ORDER:
            for result in evaluate(load_corpus_case(slug)):
                if result.status == "hard":
                    with self.subTest(case=slug, result=result.id):
                        self.assertTrue(result.remedy.strip(),
                                        f"{result.id} stops the case but says nothing to cure it")


if __name__ == "__main__":
    unittest.main()
