"""PDF pages are measured before rendering, poppler cannot hang a run, and a zip cannot carry a
case past the page limit (audit 6 Oct 2026, Medium).

    python3 -m unittest tests.test_pdf_limits -v
"""
from __future__ import annotations

import io
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from pipeline import ingest


def _pdf(sizes: list[tuple[int, int]]) -> bytes:
    """A minimal valid PDF whose pages have these MediaBox sizes in points (blank pages)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [" + " ".join(f"{3 + i} 0 R" for i in range(len(sizes)))
            + f"] /Count {len(sizes)} >>"]
    objs += [f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] >>" for w, h in sizes]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{body}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


class PagesMeasuredFirst(unittest.TestCase):
    def test_a_giant_second_page_is_refused_before_anything_renders(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / "case.pdf"
            pdf.write_bytes(_pdf([(595, 842), (9500, 9500)]))         # the audit's 428-byte file
            self.assertLess(pdf.stat().st_size, 1000)
            dpi = ingest._render_dpi(pdf)
            self.assertEqual([n for n, _ in ingest._oversized_pages(pdf, 2, dpi)], [2])
            pages_dir = Path(d) / "pages"
            pages_dir.mkdir()
            with self.assertRaises(ingest.IngestError) as caught:
                ingest._ingest_raw_scan(pdf, Path(d), pages_dir)
            self.assertIn("p.2", str(caught.exception))
            self.assertEqual(list(pages_dir.iterdir()), [], "nothing was rendered")

    def test_ordinary_pages_are_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / "case.pdf"
            pdf.write_bytes(_pdf([(595, 842), (842, 595), (612, 1008)]))  # A4, A4 landscape, legal
            self.assertEqual(ingest._oversized_pages(pdf, 3, ingest._render_dpi(pdf)), [])


class ToolsCannotHang(unittest.TestCase):
    def test_a_poppler_call_that_does_not_finish_is_stopped(self) -> None:
        with mock.patch.object(ingest, "TOOL_TIMEOUT", 1):
            started = time.monotonic()
            with self.assertRaises(ingest.IngestError) as caught:
                ingest._run(["sleep", "30"])
            self.assertLess(time.monotonic() - started, 10)
            self.assertIn("did not finish", str(caught.exception))


class ZippedCaseIsCapped(unittest.TestCase):
    def test_the_merged_case_file_is_held_to_the_limit(self) -> None:
        from api import runs
        from pipeline.bundle import BundleError
        with tempfile.TemporaryDirectory() as d:
            z = Path(d) / "case.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("part1.pdf", _pdf([(595, 842)] * 2))
                zf.writestr("part2.pdf", _pdf([(595, 842)] * 2))
            run_dir = Path(d) / "run-x"
            run_dir.mkdir()
            run = runs.Run(run_id="x", pdf_path=Path(d) / "case.pdf", run_dir=run_dir, bundle_path=z)
            with mock.patch.dict(os.environ, {"PENSION_MAX_BUNDLE_PAGES": "3"}):
                with self.assertRaises(BundleError) as caught:
                    runs.unpack(run)
            self.assertIn("4 pages", str(caught.exception))
            self.assertFalse(run.pdf_path.exists(), "no case file was made")
            with mock.patch.dict(os.environ, {"PENSION_MAX_BUNDLE_PAGES": "4"}):
                runs.unpack(run)
            self.assertTrue(run.pdf_path.exists())


if __name__ == "__main__":
    unittest.main()
