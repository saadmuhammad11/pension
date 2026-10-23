"""The kinds of GP Fund claim a DDO files under, each with the papers the office checks it for.

23 Oct 2026. A pension case shows the documents its type requires the moment the type is
chosen; the GP Fund filing screen could only say "attach every page of the claim", so the
department learnt what was missing when the claim came back.

The two sides own different halves and this endpoint joins them. The module owns the papers,
read off its own checks (gpf.intake) rather than copied, so a check added there is asked for
here without anyone remembering to. This side owns what a kind is CALLED and which kinds a
department may file at all -- the module knows a residual claim, which the office raises on a
final payment and no department ever files.

    python3 -m unittest tests.test_gpf_claim_kinds -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import gpf_bridge, v2  # noqa: E402

#: What the module answers, trimmed to what these tests turn on.
MODULE = {
    "final": [{"id": "COVER", "item": "A2-i", "requirement": "Covering / forwarding letter", "always": True}],
    "death": [
        {"id": "COVER", "item": "A2-i", "requirement": "Covering / forwarding letter", "always": True},
        {"id": "DEATH-AFFIDAVIT", "item": "A2-vi", "requirement": "Original affidavit for lawful widow", "always": False},
    ],
    # The module knows this kind; no department files one.
    "residual": [{"id": "X", "item": "A2-i", "requirement": "Something", "always": True}],
}


def _ask(gazetted: str = "unknown", answer=None, raises=None):
    target = mock.patch.object(gpf_bridge, "intake_checklists",
                               side_effect=raises) if raises else mock.patch.object(
        gpf_bridge, "intake_checklists", return_value={"kinds": MODULE if answer is None else answer})
    with target as called:
        out = v2.gpf_claim_kinds(gazetted=gazetted, user=mock.Mock(role="DEPT_OFFICER"))
    return out, called


class TheTwoSidesAreJoined(unittest.TestCase):

    def test_every_kind_a_department_may_file_is_offered(self) -> None:
        out, _ = _ask()
        self.assertEqual([k["id"] for k in out["kinds"]], list(gpf_bridge.KINDS))

    def test_a_kind_the_module_knows_but_no_department_files_is_not_offered(self) -> None:
        """A residual claim is raised by the office on a final payment."""
        out, _ = _ask()
        self.assertNotIn("residual", [k["id"] for k in out["kinds"]])
        self.assertNotIn("residual", gpf_bridge.KINDS)

    def test_the_labels_are_this_sides_and_the_papers_are_the_modules(self) -> None:
        out, _ = _ask()
        death = next(k for k in out["kinds"] if k["id"] == "death")
        self.assertEqual(death["label"], gpf_bridge.KINDS["death"])
        self.assertEqual(death["label"], "Final payment — death")
        self.assertEqual([d["id"] for d in death["documents"]], ["COVER", "DEATH-AFFIDAVIT"])

    def test_a_paper_wanted_only_sometimes_keeps_that_mark(self) -> None:
        """The screen lists it apart; it must not arrive looking like the rest."""
        out, _ = _ask()
        death = next(k for k in out["kinds"] if k["id"] == "death")
        self.assertEqual([d["always"] for d in death["documents"]], [True, False])

    def test_a_kind_the_module_lists_nothing_for_is_still_offered_with_an_empty_list(self) -> None:
        """Offering six kinds because the seventh has no papers would be the wrong failure."""
        out, _ = _ask(answer={"final": []})
        self.assertEqual([k["id"] for k in out["kinds"]], list(gpf_bridge.KINDS))
        self.assertEqual(next(k for k in out["kinds"] if k["id"] == "death")["documents"], [])


class TheSubscriberIsCarriedThrough(unittest.TestCase):

    def test_what_the_department_said_reaches_the_module(self) -> None:
        """It narrows the list: the DDO's deduction certificate for a non-gazetted period,
        the AG office's for a gazetted one, and the service book on a non-gazetted final."""
        out, called = _ask("non-gazetted")
        called.assert_called_once_with("non-gazetted")
        self.assertEqual(out["gazetted"], "non-gazetted")


class TheModuleNotAnswering(unittest.TestCase):

    def test_it_says_so_rather_than_showing_no_requirements(self) -> None:
        """Silence would read as "this claim needs nothing", which the department would act on.
        The filing screen has a Retry for this (F12)."""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            _ask(raises=gpf_bridge.GpfError(503, "connection refused"))
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("connection refused", caught.exception.detail)
        self.assertIn("each kind of claim needs", caught.exception.detail)

    def test_an_odd_status_from_the_module_is_reported_as_a_bad_gateway(self) -> None:
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            _ask(raises=gpf_bridge.GpfError(418, "a teapot"))
        self.assertEqual(caught.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
