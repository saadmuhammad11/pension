"""pdfinfo's output is not always valid UTF-8, and a case must not fail because of it.

A scan uploaded on 19 Oct 2026 made pdfinfo emit a 0xFE byte in its metadata (position 186 of
its output). ``subprocess.run(..., text=True)`` decodes strictly, so the UnicodeDecodeError
escaped ``pdf_page_count`` -- which catches only OSError and TimeoutExpired -- and came out of
POST /api/v2/cases as a 500. The portal shows any 5xx as "the connection is slow or the server
is busy" (shared/api/client.ts SLOW_OR_BUSY), so the officer retries a file that can never go
through, and nothing in the message says the file is the problem.

Which metadata field produced the byte does not matter and is not worth pinning: pdfinfo's
output is a byte stream this code does not control, and the only line it needs -- ``Pages:`` --
is ASCII. So the test stubs pdfinfo rather than crafting a PDF, and asserts the page count
survives bytes that are not UTF-8 at all.

    python3 -m unittest tests.test_pdf_metadata_encoding -v
"""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from api.v2 import pdf_page_count
from pipeline import bundle, ingest

#: pdfinfo output with a lone 0xFE in the Title -- invalid UTF-8 at any offset -- and a good
#: Pages line after it, written by a stub so the test does not depend on poppler's conversions.
STUB = br'''#!/bin/sh
printf 'Title:          \376\376\376\n'
printf 'Creator:        Scanner\n'
printf 'Pages:          7\n'
printf 'Page size:      595 x 842 pts (A4)\n'
'''


class PdfMetadataEncoding(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        stub = Path(self.dir.name) / "pdfinfo"
        stub.write_bytes(STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{self.dir.name}{os.pathsep}{old}"
        self.addCleanup(os.environ.__setitem__, "PATH", old)

    def test_non_utf8_metadata_does_not_break_the_page_count(self):
        pdf = Path(self.dir.name) / "scan.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        self.assertEqual(pdf_page_count(pdf), 7)

    def test_non_utf8_metadata_does_not_break_the_bytes_path(self):
        self.assertEqual(pdf_page_count(b"%PDF-1.4\n"), 7)

    def test_the_bundle_reads_its_page_count(self):
        """The same byte reached verification through bundle._pdf_pages, and one unreadable
        document failed the whole bundle: "nothing in this bundle could be read as a document"."""
        pdf = Path(self.dir.name) / "01-scan.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        self.assertEqual(bundle._pdf_pages(pdf), 7)

    def test_ingest_reads_the_tool_output(self):
        self.assertIn("Pages:", ingest._run(["pdfinfo", "ignored"]))


if __name__ == "__main__":
    unittest.main()
