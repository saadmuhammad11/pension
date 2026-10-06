"""The pipeline stages, hermetically. BUILD §5, §12.3.

    python3 -m unittest tests.test_pipeline_stages -v

Why this file exists
--------------------
``test_golden_case`` covers the deterministic layer and covers it well. It does not touch the
pipeline, and on 2026-09-11 that gap cost the project every determination it has ever run:
``stage_determine`` referenced ``case.date_of_death`` seven lines before ``case`` was
assigned, so the function raised ``UnboundLocalError`` on every single call. The API caught it
as a routing outcome and emitted "routed to human", the report shipped with
``determination: null``, and 133 tests stayed green throughout.

One line of straight-line code, unreachable by the entire suite. So this file exercises the
stages themselves, against the artefacts in ``artifacts/golden``, with the two model calls
stubbed at their own seams -- the vision and OCR services are shared infrastructure and
BUILD §12.3 requires the deterministic tests to run without a GPU.

What is stubbed and what is not
-------------------------------
Only ``extraction.ocr.ocr_page`` is replaced, with a page of text a real scan would produce.
``pay_scale_from_ocr`` -- the regex that turns that text into a grade, and which exists
because the vision model read BS-19 as 12 twice at confidence 1.00 -- runs for real. Nothing
else is mocked: the pack is loaded off disk, the engine computes, and the assertions are
against ``artifacts/golden/determination.json``, which was produced before the regression and
is the only figure set in the project verified by hand (BRAIN §13).

Each test runs in a temporary copy of the run directory. ``stage_determine`` writes
``determination.json``, and a test that overwrote the golden artefact would destroy the very
thing it checks against.
"""

from __future__ import annotations

import sys
from pathlib import Path

# So the file runs directly as well as under `-m unittest` from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
import shutil
import tempfile
import re
import unittest
from datetime import date, datetime
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "artifacts" / "golden"


def _ocr_text_with(scale: str = "BS-19"):
    """A stand-in for one OCR'd page. Only the pay-scale token is load-bearing."""
    from extraction.ocr import PageText

    def fake(image, page, **kwargs):
        return PageText(
            page=page,
            text=f"GOVERNMENT OF THE PUNJAB\nForm D-I\nPrincipal ({scale})\nTotal Pay 192030",
            model="stub",
        )

    return fake


class PipelineStageTest(unittest.TestCase):
    """Base: a scratch copy of the golden run directory, torn down after each test."""

    @classmethod
    def setUpClass(cls) -> None:
        if not (GOLDEN / "manifest.json").exists():
            raise unittest.SkipTest(f"no golden artefacts at {GOLDEN}")

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="agpb-test-")
        self.run = Path(self._tmp) / "golden"
        shutil.copytree(GOLDEN, self.run)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# ==============================================================================================
# stage 7 -- the determination
# ==============================================================================================

class StageDetermineTest(PipelineStageTest):

    def _determine(self, scale: str = "BS-19"):
        from pipeline.extract import stage_determine

        with mock.patch("extraction.ocr.ocr_page", _ocr_text_with(scale)):
            return stage_determine(self.run)

    def test_stage_determine_runs_at_all(self):
        """The regression. Before the fix this raised UnboundLocalError on every call.

        Asserted as its own test, separately from the figures, because the failure mode was
        not a wrong number -- it was the function never completing, on any input.
        """
        payload = self._determine()
        self.assertIn("determination", payload)
        self.assertIn("emoluments", payload)

    def test_reproduces_the_verified_determination(self):
        """Byte-identical to the artefact verified by hand in BRAIN §13."""
        committed = json.loads((GOLDEN / "determination.json").read_text())
        self.assertEqual(self._determine(), committed)

    def test_emoluments_reconcile_against_the_forms_own_total(self):
        """§8.4's highest-value check, end to end: 178,440 + 13,590 = the printed 192,030."""
        emol = self._determine()["emoluments"]
        self.assertEqual(emol["reckonable_total"], 192_030)
        self.assertEqual(emol["printed_total"], 192_030)
        self.assertTrue(emol["reconciled"])
        self.assertEqual(emol["excluded_total"], 161_765)

    def test_rule_pack_is_selected_by_the_date_of_death(self):
        """BLOCKING-21: the rules in force when the entitlement AROSE.

        The regression was introduced in the line that does this, so the behaviour it was
        reaching for is pinned rather than left implied by the byte comparison above.
        """
        from rules import select_pack

        det = self._determine()["determination"]
        death = date.fromisoformat(det["inputs"]["date_of_death"])
        self.assertEqual(det["rule_pack_id"], select_pack(effective_date=death).id)

    def test_determination_is_provisional_and_names_its_open_items(self):
        """BRAIN §14.1: an engaged BLOCKING item shows on the determination's face."""
        det = self._determine()["determination"]
        self.assertTrue(det["provisional"])
        self.assertTrue(det["unverified_rules_engaged"])

    def test_gratuity_is_carried_as_two_readings_never_one(self):
        """BLOCKING-06, the 148.5x spread. The engine must not pick a side."""
        det = self._determine()["determination"]
        gratuity = next(a for a in det["ambiguities"] if a["rule_id"] == "FAM-IS-04")
        self.assertEqual(len(gratuity["readings"]), 2)
        self.assertEqual(
            {r["label"] for r in gratuity["readings"]}, {"literal", "capitalised"}
        )

    def test_computed_at_is_injected_not_read_from_the_clock(self):
        """BUILD §6.2: the same inputs reproduce the same output, forever."""
        from pipeline.extract import stage_determine

        when = datetime(2031, 1, 1, 9, 30, 0)
        with mock.patch("extraction.ocr.ocr_page", _ocr_text_with()):
            det = stage_determine(self.run, computed_at=when)["determination"]
        self.assertEqual(det["computed_at"], when.isoformat())

    def test_the_pack_is_never_chosen_by_the_clock(self):
        """BUILD §6.2 and SOP §8.5.1, the other half.

        The flag battery needs a pack even where no date could be read off the case, and the
        last-resort fallback was ``date.today()`` -- so two auditors reading the same bundle
        on two different days could get different reference values out of the same papers,
        and a rebuild either side of a pack's effective date would change which law applied.
        The fallback is now the newest pack's own effective date, which is fixed by the packs
        on disk, and the report still reports the gap rather than passing it off as a reading.
        """
        source = (ROOT / "pipeline" / "report.py").read_text()
        # Mentioned in the comment that explains the fallback; never called.
        called = re.findall(r"^[^#\n]*\bdate\.today\(\)", source, re.M)
        self.assertEqual(called, [], f"date.today() is called in pipeline/report.py: {called}")

    def test_refuses_when_the_grade_cannot_be_read(self):
        """A page with no scale token routes to a human rather than guessing a band."""
        from pipeline.extract import ExtractionGap, stage_determine
        from extraction.ocr import PageText

        def no_scale(image, page, **kwargs):
            return PageText(page=page, text="GOVERNMENT OF THE PUNJAB", model="stub")

        with mock.patch("extraction.ocr.ocr_page", no_scale):
            with self.assertRaises(ExtractionGap):
                stage_determine(self.run)

    def test_missing_fields_json_is_a_named_gap_not_an_ENOENT(self):
        """Stage 4 found no prescribed form: restated as the bundle defect it is."""
        from pipeline.extract import ExtractionGap, stage_determine

        (self.run / "fields.json").unlink()
        with self.assertRaises(ExtractionGap) as caught:
            stage_determine(self.run)
        self.assertIn("prescribed form", str(caught.exception))

    def test_writes_its_artefact_for_the_next_stage(self):
        self._determine()
        written = json.loads((self.run / "determination.json").read_text())
        self.assertEqual(written["determination"]["inputs"]["bps"], 19)


# ==============================================================================================
# the money regex -- pipeline/report.py
# ==============================================================================================

class MoneyInTextTest(unittest.TestCase):
    """``_money_in`` decides whether the sanction form DENIES a recovery.

    It read the "19.02" of "w.e.f. 19.02.2026" as Rs. 19, so a form that denied a recovery
    beside a dotted date looked like one that had declared it, and F-3 -- the flag §13.8
    calls "the one that costs money" -- could not fire. Every string below is either from
    the comments in ``pipeline/report.py`` or from the real bundle.
    """

    def _money(self, text):
        from pipeline.report import _money_in
        return _money_in(text)

    def test_dotted_dates_are_not_money(self):
        for text in (
            "w.e.f. 19.02.2026 nothing is recoverable",
            "Recovery: Nil, w.e.f. 01.07.2025",
            "retired 19.02.26 with no demand",
            "dated 2026-03-18, nil",
            "dated 18-02-2026, nil",
            "joinent at 12/1/74 9/3",
        ):
            with self.subTest(text=text):
                self.assertIsNone(self._money(text))

    def test_an_absent_figure_reads_as_absent(self):
        for text in ("", "No", "Nil", "amounting to Rs. ..... ", None):
            with self.subTest(text=text):
                self.assertIsNone(self._money(text))

    def test_real_figures_are_still_read(self):
        cases = {
            "Rs. 126,355 is recoverable": 126_355,
            "w.e.f. 19.02.2026 ... amounting to Rs. 126,355 is recoverable": 126_355,
            "220,941.56": 220_942,          # FMT-01 half-up
            "an overpayment of 1234.50 remains": 1_235,
            "Rs. 11,217,493": 11_217_493,
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self._money(text), want)


class DateParsingTest(unittest.TestCase):
    """``_as_date`` refuses rather than coerces: a misparsed date makes a WRONG SLA flag."""

    def _parse(self, text):
        from pipeline.report import _as_date
        return _as_date(text)

    def test_the_formats_one_real_bundle_produced(self):
        cases = {
            "12-02-2026": date(2026, 2, 12),
            "18/03/2026": date(2026, 3, 18),
            "2026-03-18": date(2026, 3, 18),
            "4th March, 2026": date(2026, 3, 4),
            "6/3/26": date(2026, 3, 6),
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self._parse(text), want)

    def test_unparseable_is_none_never_a_guess(self):
        for text in ("", "2026", "sometime in March", "31-02-2026", None):
            with self.subTest(text=text):
                self.assertIsNone(self._parse(text))

    def test_two_digit_years_are_bounded_not_silently_1926(self):
        """The reason _EARLIEST/_LATEST exist."""
        self.assertEqual(self._parse("6/3/26"), date(2026, 3, 6))


# ==============================================================================================
# the report -- and the recovery flag that depends on the regex above
# ==============================================================================================

class BuildReportTest(PipelineStageTest):

    def _report(self, **kwargs):
        from pipeline.report import build_report
        return build_report(self.run, with_citations=False, **kwargs)

    def test_builds_from_the_golden_artefacts(self):
        report = self._report()
        self.assertEqual(report["source"]["source_pages"], len(report["pages"]))
        self.assertTrue(report["documents"])
        self.assertIsNotNone(report["recommendation"])

    def test_citations_are_off_by_request_so_the_suite_needs_no_network(self):
        report = self._report()
        for flag in report["flags"]:
            self.assertNotIn("corpus_citation", flag)

    # -- why there is no determination. BRAIN §15.2: say so, precisely ---------------------

    def _refused(self, **kwargs):
        """The golden run with its determination removed and the pipeline's refusal kept.

        Which is the state a B-I or D-II bundle actually reaches today: stage 4 reads only
        Form D-I, so every other prescribed form ends here.
        """
        (self.run / "determination.json").unlink(missing_ok=True)
        (self.run / "determination_gap.json").write_text(json.dumps({
            "extract": "no Form D-I among the identified documents; stage 4 has nothing "
                       "authoritative to read the determination inputs from",
            "determine": "stage 4 produced no determination inputs: the bundle has no "
                         "prescribed form for the extraction to read.",
        }))
        return self._report(**kwargs)

    def test_a_refusal_reaches_the_officer_instead_of_dying_in_the_log(self):
        """The stage said precisely why it stopped. The report must carry that sentence.

        It used to reach `api.log` and go no further: the screen said "Not computed." and
        left the officer to guess, which is the invisible gap §15.2 argues against.
        """
        report = self._refused()
        self.assertIsNone(report["determination"])
        gap = report["determination_gap"]
        self.assertIn("no Form D-I", gap["extract"])
        self.assertIn("no determination inputs", gap["determine"])

    def test_a_determination_that_succeeded_carries_no_gap(self):
        """A stale refusal from an earlier attempt must not shadow a determination."""
        (self.run / "determination_gap.json").write_text('{"determine": "an older refusal"}')
        report = self._report()
        self.assertIsNotNone(report["determination"])
        self.assertIsNone(report["determination_gap"])

    def test_the_pay_figures_are_asked_for_only_where_they_would_work(self):
        """`_self_pension` builds a SelfPensionCase, so on a family column it reaches nothing.

        The screen used to tell every undetermined case to supply three years of pay. On a
        widow's case that is an errand to the service book with no result at the end of it.
        The golden bundle is a family case; the self-pension column here is asserted against
        the flag, not against the bundle.
        """
        self.assertFalse(self._refused(variant="WIDOW")["awaiting_pay_figures"])
        self.assertTrue(self._refused(variant="FRESH_SELF")["awaiting_pay_figures"])

    def test_figures_already_supplied_are_not_asked_for_again(self):
        """Once they are in, the engine's own refusal is the thing to read, not a prompt."""
        report = self._refused(variant="FRESH_SELF",
                               annual_pay={"2022": "58000", "2023": "60500", "2024": "62550"})
        self.assertFalse(report["awaiting_pay_figures"])
        self.assertIsNotNone(report["self_pension_error"])

    def _with_recovery(self, declared_text: str):
        """An LPC recording a recovery, against a sanction form stating ``declared_text``."""
        (self.run / "assertions.json").write_text(json.dumps({
            "recoveries": [{
                "amount": 126355, "amount_exact": "126355",
                "reason": "pay drawn in excess", "page": 29, "document": "LPC",
            }],
            "form_recovery_declared": {"text": declared_text, "page": 41},
        }))
        return [f for f in self._report()["flags"] if f["class"] == "RULE-UNDECLARED"]

    def test_f3_fires_when_the_form_denies_a_recovery_beside_a_dotted_date(self):
        """The bug, at the level an officer would have seen it: no flag at all."""
        flags = self._with_recovery("No demand or recovery is due w.e.f. 19.02.2026")
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["severity"], "HIGH")
        self.assertTrue(flags[0]["blocks_ppo"])
        self.assertIn("126,355", flags[0]["title"])

    def test_f3_fires_on_a_bare_denial(self):
        self.assertEqual(len(self._with_recovery("No")), 1)

    def test_f3_does_not_fire_when_the_form_declares_the_recovery(self):
        """The other direction. A false accusation costs a family a round trip."""
        self.assertEqual(
            self._with_recovery("Recovery of Rs. 126,355 is due w.e.f. 19.02.2026"), []
        )

    def test_recoveries_are_taken_from_the_lpc_only(self):
        """§8.3: the LPC governs recoveries. Prose elsewhere produced 11-million artefacts."""
        (self.run / "assertions.json").write_text(json.dumps({
            "recoveries": [{
                "amount": 999999, "amount_exact": "999999", "reason": "prose artefact",
                "page": 12, "document": "SALARY_STATEMENT",
            }],
            "form_recovery_declared": {"text": "No", "page": 41},
        }))
        self.assertEqual(
            [f for f in self._report()["flags"] if f["class"] == "RULE-UNDECLARED"], []
        )

    def test_personnel_numbers_outside_6_to_10_digits_are_discarded(self):
        """A stripped CNIC is not a third personnel number. It reached F-1's title once."""
        (self.run / "assertions.json").write_text(json.dumps({
            "assertions": [
                {"field": "personnel_no", "value": "0000100001083", "page": 8,
                 "document": "BANK_OPTION_FORM"},
                {"field": "personnel_no", "value": "90000857", "page": 2,
                 "document": "FILE_COVER"},
            ],
        }))
        titles = " ".join(f["title"] for f in self._report()["flags"])
        self.assertNotIn("0000100001083", titles)

    def test_pages_unaccounted_is_reported_so_a_MISSING_line_can_be_trusted(self):
        report = self._report()
        self.assertIn("pages_unaccounted", report)
        self.assertIsInstance(report["pages_unaccounted"], list)


# ==============================================================================================
# the three-year average base -- EMOL-BASE, rule 4.4(4)
# ==============================================================================================

class AverageBaseWindowTest(unittest.TestCase):
    """Which three years, not merely how many.

    Intake derived them from ``new Date().getFullYear()`` -- the clock on the officer's desk,
    not a fact about the case -- so a servant who retired in June 2025 whose case is processed
    in 2026 was offered 2023/24/25 and needed 2022/23/24. Three figures for the wrong three
    years average silently into a pension for life.
    """

    def _pack(self):
        from rules import select_pack
        return select_pack(effective_date=date(2026, 2, 18))

    def _pay(self, *years):
        from decimal import Decimal
        from rules.emoluments import AnnualPay
        return [AnnualPay(y, Decimal("100000")) for y in years]

    def test_the_window_is_taken_from_the_retirement_date(self):
        from rules.emoluments import average_years_for

        cases = {
            date(2026, 2, 18): [2023, 2024, 2025],   # before 1 July
            date(2026, 6, 30): [2023, 2024, 2025],   # the day before
            date(2026, 7, 1): [2024, 2025, 2026],    # the boundary itself
            date(2026, 9, 30): [2024, 2025, 2026],   # after
            date(2025, 6, 30): [2022, 2023, 2024],
        }
        for retirement, want in cases.items():
            with self.subTest(retirement=retirement):
                self.assertEqual(average_years_for(retirement, 3), want)

    def test_the_right_window_is_accepted(self):
        from rules.emoluments import reckon_average

        emol = reckon_average(self._pay(2023, 2024, 2025), self._pack(),
                              retirement=date(2026, 2, 18))
        self.assertEqual(int(emol.reckonable_total), 100_000)

    def test_the_wrong_window_is_refused(self):
        """The clock-derived years, against a servant who retired in June 2025."""
        from rules.emoluments import EmolumentsError, reckon_average

        with self.assertRaises(EmolumentsError) as caught:
            reckon_average(self._pay(2023, 2024, 2025), self._pack(),
                           retirement=date(2025, 6, 30))
        message = str(caught.exception)
        self.assertIn("2022, 2023, 2024", message)   # what was required
        self.assertIn("2023, 2024, 2025", message)   # what was supplied

    def test_short_list_still_refused(self):
        """Pre-existing guard, kept: the missing year is the earliest and so the lowest."""
        from rules.emoluments import EmolumentsError, reckon_average

        with self.assertRaises(EmolumentsError):
            reckon_average(self._pay(2024, 2025), self._pack())

    def test_omitting_the_retirement_date_checks_only_the_count(self):
        """Backward compatible: the window check is opt-in, because without a date there
        is nothing to check against and inventing one from the clock is the bug itself."""
        from rules.emoluments import reckon_average

        emol = reckon_average(self._pay(1999, 2000, 2001), self._pack())
        self.assertEqual(int(emol.reckonable_total), 100_000)

    def test_the_base_is_not_pre_rounded(self):
        """FMT-03: the average is carried unrounded into the gross-pension step."""
        from decimal import Decimal
        from rules.emoluments import AnnualPay, reckon_average

        years = [AnnualPay(y, Decimal(a)) for y, a in
                 ((2023, "100000"), (2024, "100001"), (2025, "100001"))]
        emol = reckon_average(years, self._pack(), retirement=date(2026, 2, 18))
        self.assertNotEqual(emol.reckonable_total, int(emol.reckonable_total))


if __name__ == "__main__":
    unittest.main()
