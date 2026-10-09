"""Image bombs are measured from their headers and refused before decoding (audit 6 Oct 2026, item 5).

    python3 -m unittest tests.test_image_limits -v

A department could upload a ~1 MB group-4 TIFF of 200 frames at 9000 x 9000 (its magic bytes
pass the upload check), and converting it to PDF held every page in memory: ~25 GB, on a box
with 6 GB free, inside the API process. Now each frame's size is read from its header, a frame
or a file past the limits is refused by name at upload and skipped by name in a zip, and the
pages of an acceptable file are written one at a time.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from pipeline import bundle

ROOT = Path(__file__).resolve().parents[1]


def _tiff(path: Path, size: tuple[int, int], frames: int) -> Path:
    """A blank bilevel multi-page TIFF: group-4 compresses each frame to almost nothing."""
    page = Image.new("1", size, 1)
    page.save(path, "TIFF", compression="group4", save_all=True, append_images=[page] * (frames - 1))
    page.close()
    return path


class ImageLimits(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        d = Path(cls._tmp.name)
        # The audit's bomb: 200 frames of 81 Mpx each.
        cls.bomb = _tiff(d / "bomb.tif", (9000, 9000), 200)
        # Every frame under the per-page limit, the file over the total.
        cls.many = _tiff(d / "many.tif", (6000, 6000), 12)
        # A counter scanner's three-page TIFF at 150 dpi A4.
        cls.normal = _tiff(d / "normal.tif", (1240, 1754), 3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_the_bomb_files_are_small_on_disk(self) -> None:
        # The point of the attack: the upload caps never see it.
        self.assertLess(self.bomb.stat().st_size, 2_000_000)

    def test_headers_decide(self) -> None:
        self.assertIn("9000 x 9000 pixels", bundle.image_problem(self.bomb))
        self.assertIn("million pixels by page", bundle.image_problem(self.many))
        self.assertIsNone(bundle.image_problem(self.normal))

    def test_conversion_refuses_by_name_and_keeps_good_files(self) -> None:
        with tempfile.TemporaryDirectory() as out:
            for bad in (self.bomb, self.many):
                with self.assertRaises(bundle.BundleError) as caught:
                    bundle._image_to_pdf(bad, Path(out) / "x.pdf")
                self.assertIn(bad.name, str(caught.exception))
            dst = Path(out) / "normal.pdf"
            self.assertEqual(bundle._image_to_pdf(self.normal, dst), "")
            self.assertEqual(bundle._pdf_pages(dst), 3)

    def test_a_zipped_bomb_is_skipped_with_its_reason_in_bounded_memory(self) -> None:
        # In a fresh process, so its peak memory is this conversion's alone.
        with tempfile.TemporaryDirectory() as d:
            z = Path(d) / "case.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.write(self.bomb, "bomb.tif")
                zf.write(self.normal, "form.tif")
            script = (
                "import json, resource, sys\n"
                "from pathlib import Path\n"
                "from pipeline import bundle\n"
                "b = bundle.normalise(Path(sys.argv[1]).read_bytes(), 'case.zip', Path(sys.argv[2]))\n"
                "print(json.dumps({'pages': b.pages, 'skipped': {p.name: p.skipped for p in b.skipped},\n"
                "                  'peak_mb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024}))\n")
            work = Path(d) / "work"
            work.mkdir()
            proc = subprocess.run([sys.executable, "-c", script, str(z), str(work)], cwd=ROOT,
                                  capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
            out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(out["pages"], 3)
        self.assertIn("9000 x 9000 pixels", out["skipped"]["bomb.tif"])
        self.assertLess(out["peak_mb"], 500, out)
        print(f"\n    zipped bomb: skipped ({out['skipped']['bomb.tif']}); peak memory {out['peak_mb']} MB")

    def test_the_upload_is_refused_at_the_counter(self) -> None:
        from api.v2 import _document_problem
        body = self.bomb.read_bytes()
        self.assertIn("9000 x 9000 pixels", _document_problem("service-book.tif", body))
        self.assertIsNone(_document_problem("form.tif", self.normal.read_bytes()))


class UploadRefusedOverHttp(unittest.TestCase):
    """The same refusal through POST /api/v2/cases, on the case-system fixture."""
    from tests import test_api_v2 as _v2
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide

    def test_a_bomb_tiff_gets_422_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            body = _tiff(Path(d) / "b.tif", (9000, 9000), 3).read_bytes()
        police = self.login("punjab-police", "punjab-police")
        r = self.client.post("/api/v2/cases", headers=police, data={"case_type": "FRESH_SELF"},
                             files=[("files", ("service-book.tif", io.BytesIO(body), "image/tiff"))])
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("service-book.tif", r.json()["detail"])
        self.assertIn("pixels", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
