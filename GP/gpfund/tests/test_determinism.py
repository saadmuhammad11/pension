"""Determinism and reproducibility. Build specification §0 rules 4 and 5, §7.3, §15, §17.

Three of the specification's standing rules are properties of code, not promises, and this
file is where they are held to:

* **Re-evaluating the same facts must give the same results.** (§0 rule 5)
* **Swapping the model must not change a case outcome given the same facts.** (§0 rule 4)
  Testable because the rules never see the model: the same facts from a different reader are
  the same facts, so this is the same assertion as the first one, made against facts that
  carry different confidences and page regions.
* **Re-evaluating an earlier version must reproduce its results exactly.** (§7.3)
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gpfund.rules                                                        # noqa: F401
from gpfund import CORPUS_ORDER, Facts, evaluate, lists, load_corpus_case
from gpfund.casefile import CaseFile
from gpfund.corpus import corpus_facts


def _signature(results) -> str:
    """Everything a result says, as one comparable string."""
    return json.dumps([r.to_dict() for r in results], sort_keys=True, ensure_ascii=False)


class TheSameFactsGiveTheSameResults(unittest.TestCase):
    """§0 rule 5, and §17 row "Re-evaluation determinism"."""

    def test_evaluating_twice_is_byte_identical(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                facts = load_corpus_case(slug)
                self.assertEqual(_signature(evaluate(facts)), _signature(evaluate(facts)))

    def test_a_separate_load_of_the_same_facts_agrees(self):
        """Not the same object: a fresh load, as an audit recomputation would be."""
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                self.assertEqual(_signature(evaluate(load_corpus_case(slug))),
                                 _signature(evaluate(load_corpus_case(slug))))

    def test_evaluation_does_not_mutate_the_facts(self):
        """A check that could edit the facts it is judging is a check that can disagree with
        itself on the next run."""
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                raw = corpus_facts(slug)
                before = json.dumps(raw, sort_keys=True)
                evaluate(Facts(raw))
                self.assertEqual(json.dumps(raw, sort_keys=True), before)

    def test_key_order_in_the_facts_does_not_change_the_results(self):
        """Facts arriving from a different serialiser are the same facts."""
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                raw = corpus_facts(slug)
                reordered = dict(reversed(list(raw.items())))
                self.assertEqual(_signature(evaluate(Facts(raw))),
                                 _signature(evaluate(Facts(reordered))))


class SwappingTheReaderCannotChangeTheOutcome(unittest.TestCase):
    """§0 rule 4, and §17 row "Model swap invariance".

    The rules read VALUES. Confidence, page region, model name and prompt version are recorded
    for the audit trail (§15) and are not inputs to any decision -- so the same facts read by
    a different model, or by a person, produce the same results. This test simulates the swap
    by rewriting every piece of reading provenance and asserting the results do not move.
    """

    @staticmethod
    def _reread(node):
        """The same values as if a different model had lifted them."""
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if key in ("confidence", "bbox", "crop", "model", "promptVersion"):
                    out[key] = {"confidence": 0.71, "bbox": [1, 2, 3, 4], "crop": "other.png",
                                "model": "some-other-vlm", "promptVersion": "v99"}[key]
                else:
                    out[key] = SwappingTheReaderCannotChangeTheOutcome._reread(value)
            return out
        if isinstance(node, list):
            return [SwappingTheReaderCannotChangeTheOutcome._reread(v) for v in node]
        return node

    def test_a_different_reader_gives_the_same_statuses(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                original = {r.id: r.status for r in evaluate(load_corpus_case(slug))}
                swapped = {r.id: r.status
                           for r in evaluate(Facts(self._reread(corpus_facts(slug))))}
                self.assertEqual(swapped, original)

    def test_the_four_numbers_do_not_move(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                self.assertEqual(
                    lists(evaluate(Facts(self._reread(corpus_facts(slug))))).counts(),
                    lists(evaluate(load_corpus_case(slug))).counts())


class AnEarlierVersionReproducesItself(unittest.TestCase):
    """§7.3: "Re-evaluating an earlier version must reproduce its results exactly."

    This is what lets an auditor recompute a determination against the rule set recorded on
    the case and get the figures on the record rather than today's.
    """

    def _case_with_history(self) -> CaseFile:
        case = CaseFile(load_corpus_case("missing-credits"), by="Harness", desk="AO", at="T0")
        first = _signature(case.results)
        case.upload_against(
            "MC-CHALLANS", file_name="challan-sr4.png", content=b"a scanned challan",
            confirmed={"sr": "4", "amount": "7960", "bankStamp": "yes"},
            by="Sadia Rehman", desk="AO", at="T1")
        case.record_verification("DOA:treasury", ok=True, note="Specimen compared and matched.",
                                 by="Sadia Rehman", desk="AO", at="T2")
        self._first_signature = first
        return case

    def test_three_versions_are_recorded(self):
        case = self._case_with_history()
        self.assertEqual(case.version, 3)
        self.assertEqual([v.number for v in case.versions], [1, 2, 3])

    def test_version_one_recomputes_to_what_it_was(self):
        case = self._case_with_history()
        self.assertEqual(_signature(case.results_at(1)), self._first_signature)

    def test_every_version_recomputes_to_its_recorded_counts(self):
        case = self._case_with_history()
        for version in case.versions:
            with self.subTest(version=version.number):
                self.assertEqual(lists(case.results_at(version.number)).counts(),
                                 dict(version.counts))

    def test_the_hard_stop_was_actually_cured(self):
        """The loop has to do something, or the determinism above is the determinism of a
        module that never changes its mind."""
        case = self._case_with_history()
        self.assertEqual(lists(case.results_at(1)).counts()["hard"], 1)
        self.assertEqual(case.lists.counts()["hard"], 0)

    def test_the_earlier_facts_are_untouched_by_the_later_ones(self):
        case = self._case_with_history()
        challans_v1 = case.versions[0].facts.doc("challans") or {}
        challans_now = case.facts.doc("challans") or {}
        self.assertEqual(len(challans_v1.get("copies") or []), 6)
        self.assertEqual(len(challans_now.get("copies") or []), 7)


class NoClockAndNoRandomness(unittest.TestCase):
    """The property the two above rest on."""

    def test_the_rules_layer_reads_no_clock_and_no_randomness(self):
        """A grep, deliberately: the cheapest way to keep a clock out of a pure layer is to
        assert that nothing in it can reach one."""
        import re

        banned = re.compile(
            r"\b(datetime\.now|date\.today|time\.time|time\.monotonic|random\.|uuid[0-9]?\()")
        package = ROOT / "gpfund"
        pure = ["engine.py", "contracts.py", "params.py", "doa.py", "cures.py",
                "rules_common.py", "rules_advances.py", "rules_final.py",
                "rules_missing_credits.py", "rules_statutory.py", "rules_custom.py",
                "rules.py", "sap.py", "disposal.py"]
        for name in pure:
            with self.subTest(module=name):
                text = (package / name).read_text()
                # Strip comments and docstrings before grepping, so prose about the clock is
                # allowed and a CALL is not.
                code = "\n".join(line.split("#")[0] for line in text.splitlines())
                hits = banned.findall(code)
                self.assertEqual(hits, [], f"gpfund/{name} reaches for a clock or randomness")

    def test_the_case_file_takes_its_timestamps_as_arguments(self):
        """``casefile`` records times, so it must be GIVEN them -- a replay of the same
        actions has to reproduce the same case file."""
        case = CaseFile(load_corpus_case("refundable"), by="Harness", desk="AO", at="T0")
        self.assertEqual(case.versions[0].at, "T0")
        self.assertEqual(case.audit[0].at, "T0")


if __name__ == "__main__":
    unittest.main()
