"""The orientation reads happen together, and decide exactly what they decided in turn.

Two candidate rotations at JUDGE_READS each is six round trips, and they ran one after
another: a sideways page cost 6.4s against 0.08s for one the layout could place on its own,
on a 78-page bundle where about twenty pages run sideways (20 Oct 2026).

The reads are independent, so only the waiting is shared. What must not move is the rule:
unanimity per candidate, and a read that RAISED is not a verdict -- it cannot vote, and it is
not the reader saying "unsure" either.

    python3 -m unittest tests.test_judge_concurrency -v
"""
from __future__ import annotations

import unittest
import unittest.mock
from pathlib import Path

from extraction import upright as U


def _judge_from(spec: dict):
    """A reader that answers from a per-angle script, so a pool cannot change the answers."""
    calls = {a: 0 for a in spec}

    def judge(image):
        angle = int(Path(image).stem.rsplit("-", 1)[-1])
        s = spec[angle]
        if s == "raise":
            raise RuntimeError("the reader is down")
        v = s[calls[angle] % len(s)]
        calls[angle] += 1
        return v
    return judge


IMAGES = {90: Path("/t/p-90.png"), 270: Path("/t/p-270.png")}


class JudgeConcurrency(unittest.TestCase):
    def _ask(self, spec, conc):
        with unittest.mock.patch.object(U, "JUDGE_CONCURRENCY", conc):
            return U._ask_all(_judge_from(spec), IMAGES)

    def test_pooled_matches_sequential_on_every_shape(self) -> None:
        cases = {
            "90 unstable, 270 steady": {90: [True, False, False], 270: [True, True, True]},
            "both steady true":        {90: [True] * 3,          270: [True] * 3},
            "both steady false":       {90: [False] * 3,         270: [False] * 3},
            "only 90 upright":         {90: [True] * 3,          270: [False] * 3},
            "a read raises":           {90: [True] * 3,          270: "raise"},
        }
        for label, spec in cases.items():
            with self.subTest(case=label):
                self.assertEqual(self._ask(spec, 6), self._ask(spec, 1))

    def test_a_candidate_the_reader_wavers_on_earns_no_vote(self) -> None:
        out = self._ask({90: [True, False, False], 270: [True] * 3}, 6)
        self.assertIsNone(out[90], "unanimity, not majority")
        self.assertIs(out[270], True)

    def test_a_read_that_raised_is_not_a_verdict(self) -> None:
        out = self._ask({90: [True] * 3, 270: "raise"}, 6)
        self.assertIs(out[90], True)
        self.assertIsNone(out[270])

    def test_every_candidate_is_asked_JUDGE_READS_times(self) -> None:
        seen = []

        def judge(image):
            seen.append(int(Path(image).stem.rsplit("-", 1)[-1]))
            return True
        with unittest.mock.patch.object(U, "JUDGE_CONCURRENCY", 6):
            U._ask_all(judge, IMAGES)
        self.assertEqual(seen.count(90), U.JUDGE_READS)
        self.assertEqual(seen.count(270), U.JUDGE_READS)

    def test_one_disables_the_pool(self) -> None:
        import os
        import importlib
        for given, expect in (("1", 1), ("8", 8), ("0", 1), ("", 6)):
            with unittest.mock.patch.dict(os.environ, {"PENSION_JUDGE_CONCURRENCY": given}):
                self.assertEqual(importlib.reload(U).JUDGE_CONCURRENCY, expect, f"for {given!r}")
        importlib.reload(U)


if __name__ == "__main__":
    unittest.main()
