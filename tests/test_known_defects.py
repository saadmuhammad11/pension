"""Defects that are known, reported, and not yet fixed. BRAIN §15.2.

    python3 -m unittest tests.test_known_defects -v

Every test here asserts the behaviour the system OUGHT to have and is marked
``expectedFailure``, so the suite stays green while the backlog becomes something you can
run instead of something you have to remember. When one of these starts passing, unittest
reports an unexpected success and the run goes red -- which is the prompt to delete the
decorator and move the test into the suite proper.

This is not a place to park things that are merely untidy. Each entry below is a defect with
a described consequence, and the docstring says what that consequence is. A file like this
earns its keep only if everything in it is real.

Nothing here touches production code, and no test writes outside a temporary directory.

Six of the seven entries this file opened with were fixed on 18 September 2026 and moved
into the suite proper, as the paragraph above requires:

  * the unrecognised pay line that never reached the engine (``EMOL-08``)
    -> ``tests/test_pay_table_reads.AnUnrecognisedPayLineReachesTheEngine``
  * the month-end borrow in ``span`` and the extraordinary leave that was recorded but never
    deducted (``QS-05``)                       -> ``tests/test_qualifying_service``
  * the truncated pension base in ``inputs`` (``FMT-01``) and the unvalidated
    ``pension_kind``                           -> ``tests/test_engine_input_integrity``

What is left is the one entry that cannot be fixed by writing code, for the reason its own
docstring gives.
"""

from __future__ import annotations

import sys
from pathlib import Path

# So the file runs directly as well as under `-m unittest` from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest


# ==============================================================================================

class UrduPluralTest(unittest.TestCase):
    """The Urdu claimant message uses the plural "تصحیحات" for a count of one.

    The English has a singular special case ("One correction is needed"); the Urdu does not,
    so a single shortcoming reads as "one corrections". Pre-existing, but reachable far more
    often now that the count includes missing and defective documents rather than HIGH flags
    alone.

    Deliberately asserted as "does not use the plural form" rather than against a specific
    singular: ``rules/notifications.py`` states that none of its Urdu has been reviewed by a
    native speaker, and guessing the singular noun and its verb agreement here would be
    composing exactly the unreviewed text that warning is about.
    """

    def _bodies(self):
        from rules.checklist import Checklist, ChecklistItem, MISSING, PRESENT
        from rules.notifications import notify
        from rules.verdict import RETURN_FOR_CORRECTION, Recommendation
        from rules import CaseRecord

        def cl(*s):
            return Checklist("AG_OFFICE_2026:WIDOW", tuple(
                ChecklistItem(f"AG-{i:02d}", "r", st) for i, st in enumerate(s, 1)))

        record = CaseRecord(case_ref="AG-1", case_type="FAMILY_PENSION_DEATH_IN_SERVICE",
                            case_variant="WIDOW")
        rec = Recommendation(RETURN_FOR_CORRECTION, (), "returned")
        one = notify(record, cl(MISSING, PRESENT), (), rec)[1].body_ur
        two = notify(record, cl(MISSING, MISSING), (), rec)[1].body_ur
        return one, two

    def test_the_english_has_a_singular(self):
        """Not a defect: the half that is right."""
        from rules.checklist import Checklist, ChecklistItem, MISSING, PRESENT
        from rules.notifications import notify
        from rules.verdict import RETURN_FOR_CORRECTION, Recommendation
        from rules import CaseRecord

        note = notify(
            CaseRecord(case_ref="AG-1", case_type="F", case_variant="WIDOW"),
            Checklist("c", (ChecklistItem("AG-01", "r", MISSING),
                            ChecklistItem("AG-02", "r", PRESENT))),
            (), Recommendation(RETURN_FOR_CORRECTION, (), "returned"),
        )[1]
        self.assertIn("One correction is", note.body_en)

    @unittest.expectedFailure
    def test_the_urdu_does_not_use_the_plural_for_one(self):
        one, two = self._bodies()
        self.assertIn("تصحیحات", two)          # the plural, correctly, for two
        self.assertNotIn("تصحیحات", one)       # and not for one


if __name__ == "__main__":
    unittest.main()
