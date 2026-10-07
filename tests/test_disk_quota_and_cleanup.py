"""Case files stop when the disk is nearly full, and what no case needs is swept (audit 6 Oct 2026, R8).

    python3 -m unittest tests.test_disk_quota_and_cleanup -v

A bundle can be 500 MB and a run writes every page as an image; nothing checked the disk, so it
filled mid-run and half-written artefacts were taken for results. Now an upload and a
verification are refused (507) when the artefact disk has less than PENSION_MIN_FREE_GB free,
and the reconciler sweeps orphan run folders and stale upload staging files.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from collections import namedtuple
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from api import runs
from tests import test_api_v2 as _v2

_Usage = namedtuple("usage", "total used free")


class Refusals(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    create = _v2.V2Test.create

    def test_uploads_and_verifications_are_refused_when_the_disk_is_short(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.login("syed.haider", "ag")
        nearly_full = _Usage(total=100 * 1024 ** 3, used=98 * 1024 ** 3, free=2 * 1024 ** 3)
        with mock.patch.object(shutil, "disk_usage", lambda p: nearly_full), \
                mock.patch.dict(os.environ, {"PENSION_MIN_FREE_GB": "5"}):
            r = self.client.post(f"/api/v2/cases/{case_id}/documents", headers=police,
                                 files=[("files", ("more.pdf", _v2.PDF, "application/pdf"))])
            self.assertEqual(r.status_code, 507, r.text)
            self.assertIn("2.0 GB free", r.json()["detail"])
            r = self.client.post(f"/api/v2/cases/{case_id}/check", headers=reviewer)
            self.assertEqual(r.status_code, 507, r.text)
        # The case was not moved into "AI verification in progress" by the refused start.
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()["status"], "FORWARDED")
        # With room, the same requests go through.
        r = self.client.post(f"/api/v2/cases/{case_id}/check", headers=reviewer)
        self.assertEqual(r.status_code, 202, r.text)


class Sweep(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-sweep-")
        self.root = Path(self._tmp.name)
        self._patches = [mock.patch.object(runs, "ARTIFACTS", self.root),
                         mock.patch.object(runs, "UPLOADS", self.root / "uploads")]
        for p in self._patches:
            p.start()
        self._saved = dict(runs.RUNS)
        runs.RUNS.clear()

    def tearDown(self) -> None:
        runs.RUNS.clear()
        runs.RUNS.update(self._saved)
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def _run_dir(self, run_id: str, *, report: bool, age_days: float) -> Path:
        d = self.root / f"run-{run_id}"
        d.mkdir()
        (d / "manifest.json").write_text("{}")
        if report:
            (d / "case_report.json").write_text("{}")
        (self.root / "uploads").mkdir(exist_ok=True)
        (self.root / "uploads" / f"{run_id}-case.pdf").write_bytes(b"%PDF-1.4")
        old = time.time() - age_days * 86400
        for p in [d, *d.iterdir()]:
            os.utime(p, (old, old))
        return d

    def test_only_old_orphans_and_stale_staging_go(self) -> None:
        orphan = self._run_dir("a" * 12, report=False, age_days=10)
        recent_orphan = self._run_dir("b" * 12, report=False, age_days=2)
        finished = self._run_dir("c" * 12, report=True, age_days=400)
        a_cases_run = self._run_dir("d" * 12, report=False, age_days=30)
        live = self._run_dir("e" * 12, report=False, age_days=30)
        runs.RUNS["e" * 12] = runs.Run(run_id="e" * 12, pdf_path=self.root / "e.pdf", run_dir=live, state="running")
        incoming = self.root / "cases" / ".incoming"
        incoming.mkdir(parents=True)
        stale = incoming / "up-stale"
        stale.write_bytes(b"x")
        os.utime(stale, (time.time() - 2 * 86400,) * 2)
        fresh = incoming / "up-fresh"
        fresh.write_bytes(b"x")

        with mock.patch.dict(os.environ, {"PENSION_RUN_ORPHAN_DAYS": "7"}):
            removed = runs.sweep_disk(referenced={"d" * 12})

        self.assertEqual(removed, {"runs": ["a" * 12], "staging": ["up-stale"]})
        self.assertFalse(orphan.exists())
        self.assertFalse((self.root / "uploads" / ("a" * 12 + "-case.pdf")).exists())
        for kept in (recent_orphan, finished, a_cases_run, live, fresh):
            self.assertTrue(kept.exists(), kept)

    def test_a_disk_that_cannot_be_asked_is_not_refused(self) -> None:
        def broken(p):
            raise OSError("no such device")
        with mock.patch.object(shutil, "disk_usage", broken):
            self.assertIsNone(runs.disk_shortfall())


if __name__ == "__main__":
    unittest.main()
