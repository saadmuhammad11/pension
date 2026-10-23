"""One switch, both products: every verify reads every page of the bundle again.

Office decision of 23 Oct 2026. It was applied to the pension pipeline the same day
(rounds.carryover_allowed, and base_run_for returning None) and missed on the GP Fund side,
where the reading is not the pipeline's but the module's: api/gpf_bridge.start_examination
sends a ``reuse_scope`` and a ``page_keys`` list, and the module serves any page key it has
read before out of its page cache instead of looking at the page (gpf.api._read_scans).

So a GP Fund re-examination of an unchanged bundle hit the cache on every page and finished
in half a second, having read nothing. Two consequences, both seen on 23 Oct 2026:

  * A fix to the reader never reached a case already read. The rules DO re-run -- they run
    over the cached facts -- so a rule fix landed and a reader fix did not, which is the
    harder of the two to notice.
  * The officer was told the examination takes ten to twenty minutes and then shown no
    progress window at all, because the case left AI_CHECKING in about 300 milliseconds.

    python3 -m unittest tests.test_every_verify_reads_every_page -v
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import case_runs, rounds  # noqa: E402


class TheSwitchItself(unittest.TestCase):

    def test_it_is_off_unless_the_environment_turns_it_on(self) -> None:
        for value in ("", "0", "no", "off", "anything else"):
            with mock.patch.dict(os.environ, {"PENSION_CARRYOVER": value}):
                self.assertFalse(rounds.carryover_allowed(), value)
        for value in ("1", "true", "yes", "on", "ON", " True "):
            with mock.patch.dict(os.environ, {"PENSION_CARRYOVER": value}):
                self.assertTrue(rounds.carryover_allowed(), value)

    def test_it_is_off_where_the_office_left_it(self) -> None:
        """The deployed default. Set PENSION_CARRYOVER=1 to have reuse back, on both sides."""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(rounds.carryover_allowed())


class _Started(Exception):
    """Carries the keyword arguments _start_gpf handed to the module."""

    def __init__(self, kwargs: dict) -> None:
        super().__init__("started")
        self.kwargs = kwargs


def _start_gpf_with(carryover: bool) -> dict:
    """Run _start_gpf far enough to see what it would send, without dialling the module."""
    case = {"id": "case-1", "submission_no": 1, "gpf_case_id": "final-scan-abc", "case_no": "PC-2026-000048"}
    docs = [{"stored_path": "/nonexistent/claim.pdf", "filename": "claim.pdf"}]

    def explode(files, **kwargs):
        raise _Started(kwargs)

    with mock.patch.object(rounds, "carryover_allowed", return_value=carryover), \
            mock.patch.object(case_runs.gpf_bridge, "is_specimen", return_value=False), \
            mock.patch.object(case_runs.gpf_bridge, "scratch_dir", return_value=Path("/tmp/does-not-matter")), \
            mock.patch.object(case_runs.gpf_bridge, "start_examination", side_effect=explode):
        try:
            case_runs._start_gpf(case, docs, {"gpf_kind": "final"}, mock.Mock(role="AG_AO"))
        except _Started as started:
            return started.kwargs
    raise AssertionError("_start_gpf did not reach the module call")


class TheGpFundHalf(unittest.TestCase):

    def test_no_page_is_reused_while_the_switch_is_off(self) -> None:
        """An empty scope is what makes the module read every page: _read_scans builds its
        PageCache only `if reuse_scope and page_keys`."""
        self.assertEqual(_start_gpf_with(carryover=False)["reuse_scope"], "")

    def test_the_scope_comes_back_when_the_switch_is_on(self) -> None:
        """The machinery is untouched, as it is on the pension side -- only not used."""
        self.assertEqual(_start_gpf_with(carryover=True)["reuse_scope"], "portal-case-case-1")

    def test_the_round_is_still_read_into_the_same_module_case(self) -> None:
        """into_case is a different thing and must not follow the switch: a resubmission is a
        second ROUND of one examination, so the officer's dispositions carry across (H-19).
        Reading every page again does not mean starting a new examination."""
        for carryover in (True, False):
            with self.subTest(carryover=carryover):
                self.assertEqual(_start_gpf_with(carryover)["into_case"], "final-scan-abc")


class ThePensionHalf(unittest.TestCase):

    def test_a_pension_round_reuses_nothing_while_the_switch_is_off(self) -> None:
        with mock.patch.object(rounds, "carryover_allowed", return_value=False):
            self.assertIsNone(rounds.base_run_for(mock.Mock(), {"submission_no": 2, "product": "PENSION"}))

    def test_the_module_s_reading_is_not_the_pipelines_to_carry(self) -> None:
        """base_run_for passes a GP Fund case by whatever the switch says -- which is why the
        GP Fund half had to be made in _start_gpf and was missed when the decision was taken."""
        with mock.patch.object(rounds, "carryover_allowed", return_value=True):
            self.assertIsNone(rounds.base_run_for(
                mock.Mock(), {"submission_no": 2, "product": "GPF", "id": "case-1"}))


if __name__ == "__main__":
    unittest.main()
