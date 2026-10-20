"""AG-10 is no longer asked for, and a service book that IS filed is still cited.

The office removed the requirement on 20 Oct 2026 -- "Original service book with photocopies
attested by the DDO, or the proforma for qualifying service (non-gazetted)". It is treated the
way AG-09 was on 12 Oct: NOT_REQUIRED_ANYWHERE rather than deleted, so a bundle that does carry
the book has it acknowledged (FOUND_NOT_REQUIRED) instead of the paper going unmentioned, and
the line can never make a checklist INCOMPLETE again.

    python3 -m unittest tests.test_ag10_not_required -v
"""
from __future__ import annotations

import unittest

from rules.checklist import (FOUND_NOT_REQUIRED, MISSING, NOT_REQUIRED,
                             NOT_REQUIRED_ANYWHERE, not_required)


class Ag10NotRequired(unittest.TestCase):
    def test_ag10_is_not_required_in_any_case_type(self) -> None:
        for variant in ("FRESH_SELF", "FRESH_INVALID", "REVISED", "DEATH_IN_SERVICE",
                        "WIDOW", "UNMARRIED_CHILD", None):
            with self.subTest(variant=variant):
                self.assertTrue(not_required("AG-10", variant))

    def test_it_sits_with_the_other_removed_lines(self) -> None:
        self.assertIn("AG-10", NOT_REQUIRED_ANYWHERE)
        self.assertIn("AG-09", NOT_REQUIRED_ANYWHERE, "AG-09 is the precedent this follows")

    def test_lines_that_are_still_required_are_untouched(self) -> None:
        """The removal must not leak into its neighbours."""
        for item in ("AG-01", "AG-02", "AG-04", "AG-05", "AG-11", "AG-13"):
            with self.subTest(item=item):
                self.assertFalse(not_required(item, "FRESH_SELF"))

    def test_a_not_required_line_is_never_missing(self) -> None:
        """NOT_REQUIRED and FOUND_NOT_REQUIRED are the two outcomes; neither is a deficiency."""
        self.assertNotEqual(NOT_REQUIRED, MISSING)
        self.assertNotEqual(FOUND_NOT_REQUIRED, MISSING)


if __name__ == "__main__":
    unittest.main()
