"""One case's PDF is stored once, under as many names as its readers expect (24 Oct 2026).

A case submitted as a single PDF was on the disk four and five times: the department's upload,
the document as filed, and three more inside the run -- bundle/case.pdf, bundle/parts/<name>
and bundle/pdf/<nnn>-<name>, identical to each other and to the original. Measured across the
57 runs on the box: 67 distinct PDFs over a megabyte and 178 redundant copies of them, which
at ~35 MB a case is the larger half of the artefact tree.

Every one of those paths has a reader that expects a file there, so none of them goes. They
become one file with several names, which no reader can tell apart from what it had.

    python3 -m pytest tests/test_artefact_deduplication.py -q
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from api import runs

BIG = b"%PDF-1.4\n" + b"x" * (2 << 20)
OTHER = b"%PDF-1.4\n" + b"y" * (2 << 20)


class Dedupe(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for d in ("cases", "uploads", "run-aaaaaaaaaaaa/bundle/parts", "run-aaaaaaaaaaaa/bundle/pdf"):
            (self.root / d).mkdir(parents=True)
        self.patch = mock.patch.multiple(runs, ARTIFACTS=self.root, UPLOADS=self.root / "uploads")
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def write(self, rel: str, data: bytes = BIG) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        old = (datetime.now() - timedelta(days=1)).timestamp()
        os.utime(p, (old, old))
        return p

    def test_the_same_case_pdf_under_five_names_becomes_one_file(self) -> None:
        paths = [self.write(p) for p in (
            "cases/PC-1/01-case.pdf", "uploads/aaaaaaaaaaaa-case.pdf",
            "run-aaaaaaaaaaaa/bundle/case.pdf",
            "run-aaaaaaaaaaaa/bundle/parts/01-case.pdf",
            "run-aaaaaaaaaaaa/bundle/pdf/001-01-case.pdf")]
        done = runs.link_duplicates()
        self.assertEqual(done["linked"], 4, done)
        inodes = {p.stat().st_ino for p in paths}
        self.assertEqual(len(inodes), 1, "five names, one file")

    def test_every_name_still_opens_and_holds_what_it_held(self) -> None:
        """The point of the exercise: no reader can tell.""" 
        paths = [self.write(p) for p in ("cases/PC-1/a.pdf", "run-aaaaaaaaaaaa/bundle/case.pdf")]
        runs.link_duplicates()
        for p in paths:
            self.assertTrue(p.is_file(), p)
            self.assertEqual(p.read_bytes(), BIG, p)

    def test_files_that_differ_are_left_alone(self) -> None:
        a = self.write("cases/PC-1/a.pdf", BIG)
        b = self.write("cases/PC-2/b.pdf", OTHER)
        runs.link_duplicates()
        self.assertNotEqual(a.stat().st_ino, b.stat().st_ino)

    def test_a_run_still_being_written_is_not_touched(self) -> None:
        """An hour's grace: a bundle being unpacked is a file whose bytes are not final."""
        self.write("cases/PC-1/a.pdf")
        fresh = self.root / "run-aaaaaaaaaaaa/bundle/case.pdf"
        fresh.write_bytes(BIG)                      # mtime now
        self.assertEqual(runs.link_duplicates()["linked"], 0)

    def test_small_files_are_not_worth_an_inode(self) -> None:
        self.write("cases/PC-1/a.json", b"{}" * 10)
        self.write("cases/PC-2/b.json", b"{}" * 10)
        self.assertEqual(runs.link_duplicates()["linked"], 0)

    def test_running_it_twice_changes_nothing_the_second_time(self) -> None:
        self.write("cases/PC-1/a.pdf")
        self.write("run-aaaaaaaaaaaa/bundle/case.pdf")
        self.assertEqual(runs.link_duplicates()["linked"], 1)
        self.assertEqual(runs.link_duplicates()["linked"], 0, "already one file")

    def test_it_reports_the_space_it_reclaimed(self) -> None:
        self.write("cases/PC-1/a.pdf")
        self.write("run-aaaaaaaaaaaa/bundle/case.pdf")
        self.assertEqual(runs.link_duplicates()["bytes"], len(BIG))

    def test_nothing_outside_the_write_once_folders_is_linked(self) -> None:
        """pages/ is rewritten by a resume and by carryover; only bundle, cases and uploads
        are written at creation and read thereafter."""
        self.write("run-aaaaaaaaaaaa/pages/p001.png")
        self.write("run-bbbbbbbbbbbb/pages/p001.png")
        self.assertEqual(runs.link_duplicates()["linked"], 0)


class RefusalIsCountedNotSwallowed(Dedupe):
    """fs.protected_hardlinks (on by default) refuses a link to a file the caller neither owns
    nor may write. The service runs as `pension`; if part of the tree ever drifted out of that
    ownership the pass would do nothing, for ever, in silence. So a refusal is counted and the
    housekeeping line says so.
    """

    def test_a_file_that_cannot_be_linked_is_reported(self) -> None:
        import os
        self.write("cases/PC-1/a.pdf")
        other = self.write("run-aaaaaaaaaaaa/bundle/case.pdf")
        real = os.link

        def refuse(src, dst):
            raise PermissionError(1, "Operation not permitted")

        os.link = refuse
        try:
            done = runs.link_duplicates()
        finally:
            os.link = real
        self.assertEqual(done["linked"], 0)
        self.assertEqual(done["refused"], 1)
        self.assertTrue(other.is_file(), "and the file it could not link is left as it was")
        self.assertFalse(other.with_name(other.name + ".linking").exists(), "no half-made link")

    def test_a_clean_run_reports_no_refusals(self) -> None:
        self.write("cases/PC-1/a.pdf")
        self.write("run-aaaaaaaaaaaa/bundle/case.pdf")
        self.assertEqual(runs.link_duplicates()["refused"], 0)
