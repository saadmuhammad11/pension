"""A page is turned upright on reads the judge is consistent about, or not at all.

The reader is not stable on a page whose layout is nearly tied. Measured on page 17 of a real
78-page bundle (line starts 0.93 at 90°, 1.07 at 270°), asked twenty times per candidate: the
270° rotation came back upright 20/20, and the 90° rotation -- the WRONG one -- came back
upright 7 times in 20. Two winners means "both ways round look right", so a page that really
did read upright one way was left as scanned, about a quarter of the time, with a basis
sentence that read like a settled judgement.

What moves is a spurious yes on the wrong candidate, not the right one, so the rule is
unanimity rather than a majority: a candidate the reader is not consistent about has not
earned a vote.

    python3 -m unittest tests.test_upright_agreement -v
"""
from __future__ import annotations

import unittest
import unittest.mock
from pathlib import Path

from extraction import upright


class _Flaky:
    """A reader stable on one rotation and unreliable on the other, as measured."""

    def __init__(self, stable: int, flaky: int, pattern: list[bool]) -> None:
        self.stable, self.flaky, self.pattern = stable, flaky, list(pattern)
        self.calls: list[int] = []
        self._i = 0

    def __call__(self, image: Path) -> bool | None:
        angle = int(Path(image).stem.rsplit("-", 1)[-1])
        self.calls.append(angle)
        if angle == self.stable:
            return True
        answer = self.pattern[self._i % len(self.pattern)]
        self._i += 1
        return answer


class UprightAgreement(unittest.TestCase):
    def setUp(self) -> None:
        # decide() only consults the judge for a page whose text runs up the side.
        self._axis = unittest.mock.patch.object(
            upright, "text_axis", lambda p: ("vertical", 0.93, 1.07))
        self._axis.start(); self.addCleanup(self._axis.stop)
        self._img = unittest.mock.patch("PIL.Image.open")
        m = self._img.start(); self.addCleanup(self._img.stop)
        m.return_value.__enter__.return_value.rotate.return_value.save = lambda *a, **k: None
        # The rotated candidates are never really written, so the layout measure has nothing to
        # read; it is not what this test is about.
        self._tidy = unittest.mock.patch.object(upright, "tidy_line_starts", lambda p: 1.0)
        self._tidy.start(); self.addCleanup(self._tidy.stop)

    def test_a_spurious_yes_on_the_wrong_candidate_does_not_cancel_the_right_one(self) -> None:
        """The failure as measured: 90° says upright now and then; 270° always does."""
        judge = _Flaky(stable=270, flaky=90, pattern=[True, False, False])
        for _ in range(12):
            self.assertEqual(upright.decide("p.png", judge).rotation, 270)

    def test_a_candidate_that_never_wavers_still_wins(self) -> None:
        judge = _Flaky(stable=270, flaky=90, pattern=[False])
        out = upright.decide("p.png", judge)
        self.assertEqual(out.rotation, 270)
        self.assertIn("reads upright", out.basis)

    def test_a_reader_that_agrees_on_both_leaves_the_page_alone(self) -> None:
        judge = _Flaky(stable=270, flaky=90, pattern=[True])
        out = upright.decide("p.png", judge)
        self.assertEqual(out.rotation, 0)
        self.assertIn("both ways round look right", out.basis)

    def test_each_candidate_is_asked_until_it_agrees_with_itself(self) -> None:
        judge = _Flaky(stable=270, flaky=90, pattern=[False])
        upright.decide("p.png", judge)
        self.assertEqual(judge.calls.count(90), upright.JUDGE_READS)
        self.assertEqual(judge.calls.count(270), upright.JUDGE_READS)

    def test_a_judge_that_raises_cannot_vote(self) -> None:
        def angry(image):
            raise RuntimeError("the reader is down")
        out = upright.decide("p.png", angry)
        self.assertEqual(out.rotation, 0)
        self.assertIn("left as scanned", out.basis)


if __name__ == "__main__":
    unittest.main()
