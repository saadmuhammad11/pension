"""SAP extracts: parsing, identity and the connector. Build specification §6, §17.

Two §17 rows live here:

    SAP text-export parsing                 100% on the sample extracts
    SAP extract identity rejection          100%

and the §6.5 balance-timing trap, which is the one arithmetic mistake in this module that
would have failed two sound advances.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gpfund.rules                                                        # noqa: F401
from gpfund import CORPUS_ORDER, evaluate, load_corpus_case
from gpfund.rules_advances import balance_before
from gpfund.sap import (
    ManualUploadConnector,
    SapConnector,
    SapConnectorUnavailable,
    SapExtractRejected,
    check_against_case,
    extract_template,
    parse_sap_file,
    parse_sap_text,
    recalc_summary,
)

SAMPLES = ROOT / "agofficegpfund" / "prototype" / "sap-samples"


class TheSampleExtractsAllParse(unittest.TestCase):
    """§17: 100% on the sample extracts. Transcribed from the SAP pages of five corpus cases."""

    def test_every_sample_parses_with_no_warnings(self):
        self.assertTrue(list(SAMPLES.glob("*.txt")), "no sample extracts found")
        for path in sorted(SAMPLES.glob("*.txt")):
            with self.subTest(sample=path.name):
                parsed = parse_sap_text(path.read_text())
                self.assertEqual(parsed["warnings"], [],
                                 f"{path.name} produced parser warnings")
                self.assertIsNotNone(parsed["payslip"])
                self.assertIsNotNone(parsed["recalc"])
                self.assertTrue(parsed["recalc"]["rows"])

    def test_the_personnel_number_in_the_file_name_matches_the_content(self):
        for path in sorted(SAMPLES.glob("*.txt")):
            with self.subTest(sample=path.name):
                expected = path.stem.replace("SAP_EXTRACT_", "")
                parsed = parse_sap_text(path.read_text())
                self.assertEqual(parsed["payslip"]["persNo"], expected)
                self.assertEqual(parsed["recalc"]["persNo"], expected)

    def test_money_is_parsed_as_money_and_dates_are_left_alone(self):
        parsed = parse_sap_text((SAMPLES / "SAP_EXTRACT_90000227.txt").read_text())
        payslip = parsed["payslip"]
        self.assertEqual(payslip["gpfBalance"], 19194)
        self.assertEqual(payslip["basicPay"], 22890)
        self.assertEqual(payslip["month"], "August 2026")
        first = parsed["recalc"]["rows"][0]
        self.assertEqual(first["start"], "01.07.2022")
        self.assertEqual(first["closing"], 10303)

    def test_a_debit_keeps_its_sign(self):
        """SAP prints a debit with a trailing minus. The residual case closes Rs 340,330
        DEBIT, and reading that as a credit is how a payment is made against a debit (§12)."""
        parsed = parse_sap_text((SAMPLES / "SAP_EXTRACT_90000687.txt").read_text())
        self.assertEqual(parsed["recalc"]["rows"][-1]["closing"], -340330)

    def test_an_unreadable_figure_is_none_and_not_zero(self):
        """Nil and unknown are different facts. A balance that reads as zero because nobody
        could read it is how a wrong limit is passed."""
        parsed = parse_sap_text(
            "SAP EXTRACT: PAY SLIP\nPersonnel No: 1\nGPF Balance: \nBasic Pay: ----\n")
        self.assertIsNone(parsed["payslip"]["gpfBalance"])
        self.assertIsNone(parsed["payslip"]["basicPay"])

    def test_tabs_are_accepted_as_well_as_pipes(self):
        piped = (SAMPLES / "SAP_EXTRACT_90000227.txt").read_text()
        tabbed = piped.replace("|", "\t")
        self.assertEqual(parse_sap_text(tabbed), parse_sap_text(piped))

    def test_json_is_accepted(self):
        parsed = parse_sap_file("x.json",
                                '{"payslip": {"persNo": "1"}, "recalc": {"persNo": "1", "rows": []}}')
        self.assertEqual(parsed["payslip"]["persNo"], "1")

    def test_a_drifted_layout_is_reported_not_half_read(self):
        parsed = parse_sap_text(
            "SAP EXTRACT: PAY SLIP\nPersonnel No: 1\nSome New Field: 7\n")
        self.assertEqual(parsed["payslip"]["persNo"], "1")
        self.assertTrue(any("Some New Field" in w for w in parsed["warnings"]))

    def test_the_template_names_the_case(self):
        template = extract_template(load_corpus_case("refundable"))
        self.assertIn("Personnel No: 90000227", template)
        self.assertIn("GPF FINAL RE-CALCULATION REPORT", template)

    def test_the_summary_totals_the_temporary_advances(self):
        parsed = parse_sap_text((SAMPLES / "SAP_EXTRACT_90000374.txt").read_text())
        summary = recalc_summary(parsed["recalc"]["rows"])
        self.assertEqual(summary["tempDrawn"], 49600)
        self.assertEqual(summary["tempRecovered"], 49100)
        # §16.2: "Rs 500 of advance recovery not credited back."
        self.assertEqual(summary["tempOutstanding"], 500)


class AnExtractForAnotherEmployeeIsRefused(unittest.TestCase):
    """§17: 100% on identity rejection. §16.1 records why it matters -- the refundable case's
    own CNIC page carries a fragment of a DIFFERENT employee's SAP report."""

    def setUp(self) -> None:
        self.facts = load_corpus_case("refundable")
        self.connector = ManualUploadConnector()

    def test_the_right_extract_is_accepted(self):
        text = (SAMPLES / "SAP_EXTRACT_90000227.txt").read_text()
        extract = self.connector.accept_upload("x.txt", text, self.facts,
                                               officer="Sadia Rehman", at="T1")
        self.assertEqual(extract.payslip.personnel_no, "90000227")
        self.assertEqual(extract.source, "upload")
        self.assertEqual(len(extract.sha256), 64)
        self.assertEqual(extract.officer, "Sadia Rehman")

    def test_every_other_sample_is_refused_against_this_case(self):
        for path in sorted(SAMPLES.glob("*.txt")):
            if path.stem.endswith("90000227"):
                continue
            with self.subTest(sample=path.name):
                with self.assertRaises(SapExtractRejected) as caught:
                    self.connector.accept_upload(path.name, path.read_text(), self.facts)
                self.assertIn("different employee", str(caught.exception))

    def test_an_extract_with_no_personnel_number_is_refused(self):
        with self.assertRaises(SapExtractRejected) as caught:
            self.connector.accept_upload(
                "x.txt", "SAP EXTRACT: PAY SLIP\nName: SOMEBODY\nGPF Balance: 99999\n",
                self.facts)
        self.assertIn("no personnel number", str(caught.exception))

    def test_a_file_with_neither_section_is_refused(self):
        with self.assertRaises(SapExtractRejected):
            self.connector.accept_upload("x.txt", "just some text", self.facts)

    def test_the_check_names_both_halves_separately(self):
        parsed = parse_sap_text(
            "SAP EXTRACT: PAY SLIP\nPersonnel No: 9999\n"
            "SAP EXTRACT: GPF FINAL RE-CALCULATION REPORT\nPersonnel No: 8888\n")
        issues = check_against_case(parsed, self.facts)
        self.assertEqual(len(issues), 2)
        self.assertIn("pay slip", issues[0])
        self.assertIn("re-calculation report", issues[1])

    def test_the_rules_also_refuse_a_foreign_extract_that_came_in_the_bundle(self):
        """An extract that arrived in the scan never passed the upload gate, so SAP-IDENTITY
        is the second half of the same guard."""
        foreign = self.facts.with_changes(
            lambda data: data["sap"]["payslip"].update({"persNo": "90000374"}))
        statuses = {r.id: r.status for r in evaluate(foreign)}
        self.assertEqual(statuses["SAP-IDENTITY"], "hard")


class TheConnectorInterfaceIsHonest(unittest.TestCase):
    """§6.2: build the MVP behind the interface the connector will implement."""

    def test_the_manual_route_satisfies_the_protocol(self):
        self.assertIsInstance(ManualUploadConnector(), SapConnector)

    def test_health_says_which_mode_is_in_force(self):
        status = ManualUploadConnector().health()
        self.assertEqual(status.mode, "manual-upload")
        self.assertTrue(status.reachable)
        self.assertIn("phase 2", status.detail.lower())

    def test_the_fetch_half_refuses_rather_than_returning_nothing(self):
        """§14 rule 9 and §6.1: a check waiting on SAP must WAIT. An empty pay slip that read
        as "no balance" would pass a limit test on nothing."""
        connector = ManualUploadConnector()
        for call in (lambda: connector.get_payslip("1"),
                     lambda: connector.get_gpf_recalc_report("1"),
                     lambda: connector.get_advance_history("1"),
                     lambda: connector.get_org_assignment("1")):
            with self.subTest(call=call):
                with self.assertRaises(SapConnectorUnavailable):
                    call()


class TheBalanceTimingTrap(unittest.TestCase):
    """§6.5. An extract pulled after an advance is posted shows the balance AFTER it.

    Applying the limit to the pay slip figure would have failed both corpus advances wrongly,
    and §14 rule 8 states the prohibition: never test an advance limit against a balance that
    already includes the advance.
    """

    def test_the_balance_before_the_advance_is_used(self):
        for slug, payslip_balance, before in (("refundable", 19194, 79899),
                                              ("non-refundable", 260522, 743677)):
            with self.subTest(case=slug):
                facts = load_corpus_case(slug)
                self.assertEqual(facts.sap_payslip["gpfBalance"], payslip_balance)
                basis = balance_before(facts)
                self.assertEqual(basis["value"], before)
                self.assertTrue(basis["posted"])
                self.assertIn("already posted", basis["explanation"])

    def test_both_advances_are_within_the_limit_on_that_basis(self):
        for slug in ("refundable", "non-refundable"):
            with self.subTest(case=slug):
                result = next(r for r in evaluate(load_corpus_case(slug))
                              if r.id == "ADV-LIMIT")
                self.assertIn(result.status, ("ok", "adv"),
                              "a sound advance was failed on the wrong balance")

    def test_the_pay_slip_alone_never_decides_the_limit(self):
        """§11.2 and §14 rule 8. The sharpest form of the trap.

        With the report removed, the only balance available is the pay slip's Rs 19,194 --
        which is AFTER the Rs 58,000 advance was posted. Measured against that, the sanction
        looks Rs 42,645 over an Rs 15,355 ceiling. It is not over anything: the basis is
        wrong. The check must return a verification task, not a hard stop.
        """
        facts = load_corpus_case("refundable").with_changes(
            lambda data: data["sap"].update({"recalc": None}))
        result = next(r for r in evaluate(facts) if r.id == "ADV-LIMIT")
        self.assertEqual(result.status, "conf",
                         "a provisional balance was allowed to fail a sound sanction")
        self.assertIn("may already exclude this advance", result.finding)
        self.assertIn("cannot be confirmed", result.finding)

    def test_the_ceiling_is_still_shown_on_a_provisional_basis(self):
        """Withholding the conclusion is not withholding the working: the officer sees what
        the figure would be once the basis is settled."""
        facts = load_corpus_case("refundable").with_changes(
            lambda data: data["sap"].update({"recalc": None}))
        result = next(r for r in evaluate(facts) if r.id == "ADV-LIMIT")
        self.assertEqual(result.calc["balance"], 19194)
        self.assertEqual(result.calc["ruleLimit"], 15355)
        self.assertEqual(result.cure, {"kind": "sap"})

    def test_the_rules_limit_is_applied_and_the_office_figure_is_shown(self):
        """§11.1/§11.2 and open item GPF-O15: the Rules govern, the office's 80% is flagged."""
        result = next(r for r in evaluate(load_corpus_case("non-refundable"))
                      if r.id == "ADV-LIMIT")
        self.assertEqual(result.calc["ruleLimit"], 743677)          # Rule 1.16, 100%
        self.assertEqual(result.calc["office"], 594941)             # the office's 80%
        # Rs 490,955 sits inside BOTH ceilings, so §11.2's "within both" row applies: ok,
        # with a flag line wherever the two figures differ. They differ by Rs 148,736 here,
        # which is the whole of open item GPF-O15 in one case.
        self.assertEqual(result.status, "ok")
        self.assertIn("80%", result.finding)
        self.assertIn("Flag:", result.finding)

    def test_an_advance_inside_the_rules_but_over_the_office_figure_is_flagged(self):
        """§11.2's "within the Rules, above the office's 80%" row: an observation, so the
        office can settle which applies (GPF-O15) without stopping a lawful sanction.

        The BALANCE is moved rather than the amount. Moving the amount would stop it matching
        the posting in the report, and ``balance_before`` would then fall through to the last
        closing balance -- so the test would be measuring a different thing than it says.
        """
        def lower_the_opening(data):
            for row in data["sap"]["recalc"]["rows"]:
                if row.get("permanentAdvance") == 490955:
                    row["opening"] = 600_000
        facts = load_corpus_case("non-refundable").with_changes(lower_the_opening)
        result = next(r for r in evaluate(facts) if r.id == "ADV-LIMIT")
        self.assertEqual(result.calc["ruleLimit"], 600_000)      # Rule 1.16: 100%
        self.assertEqual(result.calc["office"], 480_000)         # the office's 80%
        self.assertEqual(result.status, "adv")
        self.assertIn("above the office", result.finding)

    def test_the_refundable_limit_is_the_lesser_of_the_two_caps(self):
        """Rule 1.14(1)(d)(i): the lesser of 80% of the balance and 24 months' pay."""
        result = next(r for r in evaluate(load_corpus_case("refundable"))
                      if r.id == "ADV-LIMIT")
        self.assertEqual(result.calc["byPct"], 63919)               # 80% of 79,899
        self.assertEqual(result.calc["byPay"], 549360)              # 24 x 22,890
        self.assertEqual(result.calc["ruleLimit"], 63919)
        self.assertEqual(result.status, "ok")

    def test_an_advance_over_the_limit_is_a_hard_stop_with_the_arithmetic(self):
        """B1-i, and the excess stated so the department knows what to reduce it to.

        Again the balance moves, not the amount: Rs 58,000 against an opening of Rs 60,000
        exceeds the Rule 1.14(1)(d)(i) ceiling of Rs 48,000 by Rs 10,000.
        """
        def lower_the_opening(data):
            for row in data["sap"]["recalc"]["rows"]:
                if row.get("tempAdvance") == 58000:
                    row["opening"] = 60_000
        facts = load_corpus_case("refundable").with_changes(lower_the_opening)
        result = next(r for r in evaluate(facts) if r.id == "ADV-LIMIT")
        self.assertEqual(result.status, "hard")
        self.assertEqual(result.code, "B1-i")
        self.assertEqual(result.calc["ruleLimit"], 48_000)
        self.assertIn("Excess Rs 10,000", result.finding)
        self.assertIn("Reduce the sanction to Rs 48,000 or less", result.remedy)


if __name__ == "__main__":
    unittest.main()
