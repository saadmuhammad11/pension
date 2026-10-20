"""Ingest renders its pages at once, and gets exactly the pages the serial loop got.

Rendering is the whole cost of ingest and it is local CPU: each page of a departmental scan
carries a ~6 Mpx JPEG that poppler decodes and rescales single-threaded. Measured 19 Oct 2026 at
5.3s a page -- 121.8s of one 25-page run -- with 31 of this box's 32 cores idle. On that real
case file the stage went 146.8s -> 35.6s with eight workers, and every page came out with the
same sha256.

What could break is not the speed but the pages: the loop checkpoints in page order on its own
thread, and a resumed run must re-render nothing. Both are held here.

    python3 -m unittest tests.test_render_concurrency -v
"""
from __future__ import annotations

import hashlib
import importlib
import io
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from pipeline import ingest as ing


def _pdf(pages: int) -> bytes:
    """A minimal valid PDF of blank A4 pages -- fast to render, so the test stays quick."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [" + " ".join(f"{3 + i} 0 R" for i in range(pages))
            + f"] /Count {pages} >>"]
    objs += ["<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>"] * pages
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{body}\nendobj\n".encode())
    start = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return out.getvalue()


class RenderConcurrency(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pdf = Path(self.tmp.name) / "case.pdf"
        self.pdf.write_bytes(_pdf(6))
        self.addCleanup(lambda: importlib.reload(ing))

    def _ingest_at(self, conc: int):
        import os
        with unittest.mock.patch.dict(os.environ, {"PENSION_RENDER_CONCURRENCY": str(conc)}):
            mod = importlib.reload(ing)
            self.assertEqual(mod.RENDER_CONCURRENCY, conc)
            out = Path(tempfile.mkdtemp(dir=self.tmp.name))
            manifest = mod.ingest(self.pdf, out)
            pages = [(p["page"], p["image_path"],
                      hashlib.sha256((out / p["image_path"]).read_bytes()).hexdigest())
                     for p in manifest["pages"]]
            return manifest, pages

    def test_parallel_render_matches_the_serial_one(self) -> None:
        serial_manifest, serial_pages = self._ingest_at(1)
        self.assertEqual(len(serial_pages), 6)
        for conc in (2, 8):
            with self.subTest(concurrency=conc):
                manifest, pages = self._ingest_at(conc)
                self.assertEqual([p[0] for p in pages], [p[0] for p in serial_pages],
                                 "page order must survive the pool")
                self.assertEqual(pages, serial_pages, "every page byte-identical")
                self.assertEqual(manifest["source_sha256"], serial_manifest["source_sha256"])
                self.assertEqual(manifest["source_pages"], serial_manifest["source_pages"])

    def test_a_resumed_run_renders_nothing_again(self) -> None:
        import os
        with unittest.mock.patch.dict(os.environ, {"PENSION_RENDER_CONCURRENCY": "4"}):
            mod = importlib.reload(ing)
            out = Path(tempfile.mkdtemp(dir=self.tmp.name))
            mod.ingest(self.pdf, out)
            rendered: list[int] = []
            real = mod._render_one
            mod._render_one = lambda *a, **k: (rendered.append(a[-1]), real(*a, **k))[1]
            try:
                mod.ingest(self.pdf, out)
            finally:
                mod._render_one = real
            self.assertEqual(rendered, [], "a second pass must re-render nothing")

    def test_the_pool_is_configurable_and_never_below_one(self) -> None:
        import os
        # "" and unset mean this box's core count (the pool is a CPU budget, so the right
        # default is how many cores there are). An explicit 0 still clamps to 1: it turns the
        # pool off, and must not silently become every core.
        cores = __import__("os").cpu_count() or 8
        for given, expect in (("16", 16), ("1", 1), ("0", 1), ("", cores), ("nonsense", cores)):
            with unittest.mock.patch.dict(os.environ, {"PENSION_RENDER_CONCURRENCY": given}):
                self.assertEqual(importlib.reload(ing).RENDER_CONCURRENCY, expect, f"for {given!r}")


if __name__ == "__main__":
    unittest.main()
