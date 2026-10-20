"""The three-year-average refusal applies while a figure is published, and not otherwise.

rule 4.4(4) as substituted on 2 December 2024 makes the base the average basic pay over the
last three years. The engine sums ONE pay record, which on a rising scale is always larger, so
computing anyway would overstate a pension for life. It refused.

But this release publishes no computed figure at all -- rules.scope.CALCULATIONS_IN_SCOPE is
False (business decision of 7 Oct 2026) and scrub_report strips every amount from the report,
the API and the screens. An overstated base cannot reach anyone, while refusing cost the
officer the checks that DO reach them. Every self-pension bundle hit it: 21 runs out of 21 on
20 Oct 2026.

So the refusal follows the flag. Turn calculations back on and it returns -- which is the whole
point of having the decision in one place.

    python3 -m unittest tests.test_base_guard_follows_scope -v
"""
from __future__ import annotations

import unittest
import unittest.mock

from rules import engine, scope


class BaseGuardFollowsScope(unittest.TestCase):
    def test_this_release_publishes_no_computed_figure(self) -> None:
        """The premise. If this ever becomes True the guard below must fire again."""
        self.assertFalse(scope.CALCULATIONS_IN_SCOPE)

    def test_the_refusal_is_conditional_on_the_flag(self) -> None:
        """Both determination paths read the flag rather than refusing unconditionally."""
        import inspect
        for fn in (engine.determine_self_pension,
                   engine.determine_family_pension_death_in_service):
            src = inspect.getsource(fn)
            with self.subTest(fn=fn.__name__):
                self.assertIn("scope.CALCULATIONS_IN_SCOPE", src)
                self.assertIn("base_is_not_the_required_average", src)

    def test_a_case_without_the_three_figures_is_still_marked_blocking(self) -> None:
        """Not refusing is not the same as not saying. BLOCKING-23 is what makes the
        determination provisional and puts the case in the exceptional lane."""
        import inspect
        for fn in (engine.determine_self_pension,
                   engine.determine_family_pension_death_in_service):
            with self.subTest(fn=fn.__name__):
                self.assertIn('engaged.append("BLOCKING-23")', inspect.getsource(fn))

    def test_the_officer_is_told_why_in_the_caveats(self) -> None:
        src = inspect.getsource(engine.determine_self_pension) if (inspect := __import__("inspect")) else ""
        self.assertIn("No PPO may issue", src)
        self.assertIn("have not been supplied at intake", src)


if __name__ == "__main__":
    unittest.main()
