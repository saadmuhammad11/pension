"""The run registry, without a web server or a GPU. BUILD §4, §5.1.

    python3 -m unittest tests.test_api_runs -v

``api.runs`` is deliberately separable from the HTTP layer so the pipeline can be driven from
a test without FastAPI in the way, and this is the test that takes it up on the offer. It
matters because two of its properties are load-bearing and neither is obvious from reading
it:

*   **The run id is the content hash**, so re-posting a file resumes from its artefacts
    instead of repeating nine minutes of vision inference (§5.1).
*   **A finished run outlives the process**, because the registry is in memory and the
    artefacts are not. A restart used to hide every case the office had processed.

``execute`` is patched out throughout. Calling ``start_run`` for real would launch the whole
pipeline on a background thread -- vision model, OCR, the lot -- which is exactly what a unit
test must not do. ``ARTIFACTS`` and ``UPLOADS`` are redirected into a temporary directory so
no test can write into ``artifacts/``, where the golden run lives.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# So the file runs directly as well as under `-m unittest` from the project root. Without
# it the module-level `import api.runs` fails and the `unittest.main()` guard at the foot
# of the file can never fire.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import api.runs as runs

PDF = b"%PDF-1.4\nnot really a pdf, but it hashes\n"
OTHER_PDF = b"%PDF-1.4\na different file entirely\n"


class RunRegistryTest(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-runs-")
        root = Path(self._tmp.name)
        self.artifacts = root / "artifacts"
        self.uploads = self.artifacts / "uploads"
        self.artifacts.mkdir()
        self._patches = [
            mock.patch.object(runs, "ARTIFACTS", self.artifacts),
            mock.patch.object(runs, "UPLOADS", self.uploads),
            mock.patch.object(runs, "execute", lambda run: None),
        ]
        for p in self._patches:
            p.start()
        self._saved_runs = dict(runs.RUNS)
        runs.RUNS.clear()

    def tearDown(self) -> None:
        runs.RUNS.clear()
        runs.RUNS.update(self._saved_runs)
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def _finished_run(self, run_id: str, report: dict | None = None) -> Path:
        """A run directory as it looks after the pipeline has written its report."""
        d = self.artifacts / f"run-{run_id}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "case_report.json").write_text(json.dumps(report or {"case_ref": run_id}))
        return d

    # -- the content hash ------------------------------------------------------------------

    def test_the_run_id_is_the_content_hash(self):
        import hashlib

        started = runs.start_run(PDF, "case.pdf")
        self.assertEqual(started["run_id"], hashlib.sha256(PDF).hexdigest()[:12])
        self.assertEqual(started["sha256"], hashlib.sha256(PDF).hexdigest())

    def test_the_same_file_maps_to_the_same_run_whatever_it_is_called(self):
        first = runs.start_run(PDF, "case.pdf")
        runs.RUNS[first["run_id"]].state = "done"
        self.assertEqual(runs.start_run(PDF, "renamed.pdf")["run_id"], first["run_id"])

    def test_a_first_upload_has_nothing_to_resume(self):
        self.assertFalse(runs.start_run(PDF, "case.pdf")["resumed"])

    def test_re_posting_a_file_whose_artefacts_exist_reports_a_resume(self):
        """§5.1: the point of the content hash is not repeating nine minutes of inference."""
        run_id = runs.start_run(PDF, "case.pdf")["run_id"]
        runs.RUNS[run_id].state = "done"
        (self.artifacts / f"run-{run_id}").mkdir(parents=True)
        self.assertTrue(runs.start_run(PDF, "case.pdf")["resumed"])

    def test_joining_a_run_still_in_flight_also_reports_a_resume(self):
        """Pinned as observed, not as designed: ``resumed`` carries two meanings. On this
        branch it means "a run is already going", and on the branch above it means "there
        are artefacts on disk". Nothing consumes the field today -- the portal's Intake
        discards it -- so this records the ambiguity rather than asserting it is right."""
        runs.start_run(PDF, "case.pdf")          # left queued: execute is patched out
        again = runs.start_run(PDF, "case.pdf")
        self.assertTrue(again["resumed"])
        self.assertEqual(again["state"], "queued")

    def test_different_files_are_different_runs(self):
        self.assertNotEqual(
            runs.start_run(PDF, "a.pdf")["run_id"],
            runs.start_run(OTHER_PDF, "b.pdf")["run_id"],
        )

    def test_a_run_already_in_flight_is_not_started_twice(self):
        """Two officers posting the same bundle must not race two pipelines over one
        directory."""
        first = runs.start_run(PDF, "case.pdf")
        second = runs.start_run(PDF, "case.pdf")
        self.assertEqual(second["state"], first["state"])
        self.assertTrue(second["resumed"])
        self.assertEqual(len(runs.RUNS), 1)

    def test_the_upload_is_kept_under_its_run_id(self):
        run_id = runs.start_run(PDF, "Saima Rasheed case.pdf")["run_id"]
        saved = list(self.uploads.iterdir())
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].name.startswith(run_id))

    def test_a_path_in_the_filename_cannot_escape_the_upload_directory(self):
        runs.start_run(PDF, "../../etc/passwd")
        for path in self.uploads.iterdir():
            self.assertEqual(path.parent, self.uploads)

    def test_the_officers_intake_choices_are_carried_onto_the_run(self):
        pay = {"2023": "58000", "2024": "60500", "2025": "62550"}
        started = runs.start_run(PDF, "case.pdf", variant="WIDOW", annual_pay=pay)
        run = runs.RUNS[started["run_id"]]
        self.assertEqual(run.variant, "WIDOW")
        self.assertEqual(run.annual_pay, pay)

    # -- surviving a restart ----------------------------------------------------------------

    def test_a_finished_run_is_recovered_from_disk(self):
        self._finished_run("abc123def456")
        run = runs.adopt_from_disk("abc123def456")
        self.assertIsNotNone(run)
        self.assertEqual(run.state, "done")

    def test_an_adopted_run_closes_its_event_stream_at_once(self):
        """It carries one synthetic end event: the pipeline will never speak again."""
        self._finished_run("abc123def456")
        run = runs.adopt_from_disk("abc123def456")
        self.assertEqual(len(run.events), 1)
        self.assertEqual(run.events[0]["stage"], "end")
        self.assertTrue(run.events[0]["replayed"])

    def test_an_unfinished_run_directory_is_not_adopted(self):
        """It did not finish. Presenting it as a case would invent a history."""
        (self.artifacts / "run-halfdone1234").mkdir(parents=True)
        self.assertIsNone(runs.adopt_from_disk("halfdone1234"))

    def test_adopting_never_replaces_a_live_run(self):
        started = runs.start_run(PDF, "case.pdf")
        run_id = started["run_id"]
        live = runs.RUNS[run_id]
        live.state = "running"
        self._finished_run(run_id)
        self.assertIs(runs.adopt_from_disk(run_id), live)
        self.assertEqual(live.state, "running")

    def test_completed_run_ids_lists_only_runs_with_a_report(self):
        self._finished_run("aaaaaaaaaaaa")
        self._finished_run("bbbbbbbbbbbb")
        (self.artifacts / "run-cccccccccccc").mkdir()
        self.assertEqual(set(runs.completed_run_ids()), {"aaaaaaaaaaaa", "bbbbbbbbbbbb"})

    def test_completed_run_ids_is_empty_rather_than_raising(self):
        self.assertEqual(runs.completed_run_ids(), [])

    # -- the path guard ----------------------------------------------------------------------

    def test_a_traversing_run_id_is_refused(self):
        """``run_id`` arrives from the URL. It names a directory."""
        for run_id in ("../secrets", "..", ".", "", "a/b", "a\\b", ".hidden"):
            with self.subTest(run_id=run_id):
                self.assertIsNone(runs.adopt_from_disk(run_id))

    def test_an_unknown_run_is_none_not_an_exception(self):
        self.assertIsNone(runs.adopt_from_disk("ffffffffffff"))


class RunEventTest(unittest.TestCase):
    """Events are the audit-visible account of what the pipeline did."""

    def setUp(self) -> None:
        # emit() also logs to stdout, which is right in a server and noise in a test run.
        self._quiet = mock.patch("builtins.print")
        self._quiet.start()
        self.addCleanup(self._quiet.stop)
        self.run = runs.Run(run_id="abc", pdf_path=Path("/tmp/x.pdf"),
                            run_dir=Path("/tmp/run-abc"))

    def test_events_are_sequenced_for_replay(self):
        self.run.emit("ingest", "reading")
        self.run.emit("identify", "classifying")
        self.assertEqual([e["seq"] for e in self.run.events], [0, 1])

    def test_extra_fields_are_carried(self):
        self.run.emit("ingest", "done", pages=43)
        self.assertEqual(self.run.events[0]["pages"], 43)

    def test_a_level_marks_a_degraded_stage(self):
        self.run.emit("determine", "routed to human", level="warn")
        self.assertEqual(self.run.events[0]["level"], "warn")


class GpuReportingTest(unittest.TestCase):
    """§ "an invented percentage on a demo screen is what makes a real one untrustworthy"."""

    def test_unavailable_figures_are_null_never_plausible(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("no nvidia-smi")):
            out = runs.gpu_utilisation()
        self.assertIsNone(out["gpu_util_pct"])
        self.assertIsNone(out["gpu_name"])

    def test_it_never_raises(self):
        with mock.patch("subprocess.run", side_effect=OSError("boom")), \
             mock.patch.object(Path, "read_text", side_effect=OSError("boom")):
            out = runs.gpu_utilisation()
        self.assertIn("at", out)


class IntakeChoicesSurviveARestart(unittest.TestCase):
    """The officer's intake choices are written beside the artefacts and read back on adoption."""

    def test_adopt_from_disk_restores_variant_pay_commutation_and_retirement(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock
        import api.runs as runs
        with tempfile.TemporaryDirectory(prefix="agpb-intake-") as tmp:
            root = Path(tmp)
            with mock.patch.object(runs, "ARTIFACTS", root / "artifacts"), \
                 mock.patch.object(runs, "UPLOADS", root / "uploads"), \
                 mock.patch.dict(runs.RUNS, {}, clear=True):
                run_dir = root / "artifacts" / "run-abc123def456"
                run_dir.mkdir(parents=True)
                run = runs.Run(run_id="abc123def456", pdf_path=root / "x.pdf", run_dir=run_dir,
                               variant="REVISED", annual_pay={"2023": "1", "2024": "2", "2025": "3"},
                               commutation_percent="25", retirement_date="2026-06-01")
                runs.persist_intake(run)
                (run_dir / "manifest.json").write_text("{}")
                (run_dir / "case_report.json").write_text(json.dumps({"case_ref": "run-abc123def456"}))
                adopted = runs.adopt_from_disk("abc123def456")
        self.assertIsNotNone(adopted)
        self.assertEqual(adopted.variant, "REVISED")
        self.assertEqual(adopted.annual_pay, {"2023": "1", "2024": "2", "2025": "3"})
        self.assertEqual(adopted.commutation_percent, "25")
        self.assertEqual(adopted.retirement_date, "2026-06-01")


if __name__ == "__main__":
    unittest.main()
