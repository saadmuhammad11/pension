"""Uploads go to disk, not memory, and off the event loop (audit 6 Oct 2026, Medium).

    python3 -m unittest tests.test_upload_streaming -v

The upload handlers were async but did blocking work (the PDF check, writing up to 512 MB,
SQLite's write lock), so one upload stalled every other request; they held each upload whole in
memory (b"".join of every chunk), so a few at once could exhaust the box; and they wrote the
files while holding the database write lock. Now an upload streams to a staging file beside the
case files, the handlers run in the thread pool, and filing a document is a rename.
"""
from __future__ import annotations

import inspect
import io
import tracemalloc
import unittest
from pathlib import Path
from unittest import mock

from api import case_runs, db, v2, workflow
from tests import test_api_v2 as _v2


class _Endless(io.RawIOBase):
    """A file of ``size`` bytes that exists only as it is read: a PDF header, then zeros."""
    def __init__(self, size: int) -> None:
        self.left, self.first = size, True

    def readable(self) -> bool:
        return True

    def readinto(self, buf) -> int:
        n = min(len(buf), self.left)
        if n <= 0:
            return 0
        chunk = (b"%PDF-1.4\n" if self.first else b"") + b"\0" * n
        self.first = False
        buf[:n] = chunk[:n]
        self.left -= n
        return n


class _Upload:
    def __init__(self, name: str, size: int) -> None:
        self.filename, self.file = name, io.BufferedReader(_Endless(size), 1 << 20)


class Streaming(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide
    create = _v2.V2Test.create

    def test_a_200_mb_upload_is_checked_in_a_few_megabytes(self) -> None:
        with mock.patch.object(v2, "pdf_page_count", lambda body: 3):
            tracemalloc.start()
            staged = v2._read_uploads([_Upload("service-book.pdf", 200 * 1024 * 1024)])
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        try:
            self.assertEqual(staged[0].size, 200 * 1024 * 1024)
            self.assertEqual(staged[0].path.stat().st_size, 200 * 1024 * 1024)
            self.assertLess(peak, 16 * 1024 * 1024, f"peak {peak / 1e6:.0f} MB")
            print(f"\n    200 MB upload staged; peak Python memory {peak / 1e6:.1f} MB")
        finally:
            v2._discard_staged(staged)

    def test_the_upload_handlers_run_off_the_event_loop(self) -> None:
        for handler in (v2.create_case, v2.add_documents, v2.replace_document, v2.case_gpf_cure):
            self.assertFalse(inspect.iscoroutinefunction(handler), handler.__name__)

    def test_filing_is_a_rename_and_nothing_is_left_staged(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        staged = v2._read_uploads([_Upload("lpc.pdf", 4096)])
        inode = staged[0].path.stat().st_ino
        conn = db.connect()
        try:
            case = dict(conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone())
            with db.transaction(conn):
                [entry] = v2._write_files(conn, case, staged, mock.Mock(id="u"))
        finally:
            conn.close()
        self.assertEqual(Path(entry["stored_path"]).stat().st_ino, inode, "moved, not copied")
        self.assertEqual(list((case_runs.CASE_FILES / ".incoming").iterdir()), [])

    def test_a_case_whose_filing_fails_leaves_no_files_behind(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        before = {p for p in case_runs.CASE_FILES.rglob("*") if p.is_file()}
        with mock.patch.object(workflow, "record_event", side_effect=RuntimeError("disk error")):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/v2/cases", headers=police, data={"case_type": "FRESH_SELF"},
                                 files=[("files", ("case.pdf", io.BytesIO(_v2.PDF), "application/pdf"))])
        after = {p for p in case_runs.CASE_FILES.rglob("*") if p.is_file()}
        self.assertEqual(after - before, set())


if __name__ == "__main__":
    unittest.main()
