"""A zip of mixed documents becomes one case file.

    python3 -m unittest tests.test_bundle_intake -v

**``pipeline.bundle``** turns a zipped case -- PDFs, phone photographs, a Word LPC -- into the
single PDF the pipeline reads, in the order the files were given, and says in its manifest
what became of every one of them. The failure this prevents is a bundle arriving one document
short in silence.

LibreOffice is only exercised where it is installed; the image and PDF paths need nothing
beyond Pillow and poppler, which ingest already depends on.
"""

from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import bundle as bundle_mod


def _png(width: int = 600, height: int = 400) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, "PNG")
    return buf.getvalue()


def _pdf(pages: int = 1) -> bytes:
    """A real PDF, built by the same library the image path uses, so poppler can read it."""
    from PIL import Image
    buf = io.BytesIO()
    sheets = [Image.new("RGB", (595, 842), "white") for _ in range(pages)]
    sheets[0].save(buf, "PDF", resolution=72.0, save_all=True, append_images=sheets[1:])
    return buf.getvalue()


def _tiff(frames: int, size: tuple[int, int] = (300, 400)) -> bytes:
    """A multi-page TIFF, the way a scanner set to multi-page writes one."""
    from PIL import Image
    buf = io.BytesIO()
    sheets = [Image.new("RGB", size, (255, 255 - n, 255)) for n in range(frames)]
    sheets[0].save(buf, "TIFF", save_all=True, append_images=sheets[1:])
    return buf.getvalue()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


class BundleTest(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-bundle-")
        self.work = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_mixed_bundle_merges_in_order_with_page_ranges(self) -> None:
        """Three documents, six pages, and a manifest that says which pages are whose."""
        data = _zip({
            "01_sanction.pdf": _pdf(3),
            "02_cnic.png": _png(),
            "03_death certificate.jpg": _png(400, 600),
        })
        result = bundle_mod.normalise(data, "AGP-451-2026.zip", self.work)

        self.assertTrue(result.pdf.startswith(b"%PDF"))
        self.assertEqual(result.pages, 5)
        self.assertEqual([p.name for p in result.parts],
                         ["01_sanction.pdf", "02_cnic.png", "03_death certificate.jpg"])
        self.assertEqual([(p.page_from, p.page_to) for p in result.parts],
                         [(1, 3), (4, 4), (5, 5)])
        self.assertEqual([p.converter for p in result.parts], ["", "pillow", "pillow"])
        self.assertEqual(result.skipped, [])
        # The zip stays as it arrived, next to what was made from it.
        self.assertTrue((self.work / "case.pdf").exists())

    def test_natural_order_not_ascii_order(self) -> None:
        """page10 comes after page2: a scanner numbers pages, and ASCII does not agree."""
        data = _zip({f"page{n}.png": _png() for n in (1, 2, 10)})
        result = bundle_mod.normalise(data, "t.zip", self.work)
        self.assertEqual([p.name for p in result.parts], ["page1.png", "page2.png", "page10.png"])

    def test_unreadable_attachment_is_named_not_dropped(self) -> None:
        """A `.msg` the department thought was the LPC leaves a reason, not a gap."""
        data = _zip({"01_form.pdf": _pdf(1), "02_note.msg": b"not a document"})
        result = bundle_mod.normalise(data, "t.zip", self.work)
        self.assertEqual(result.pages, 1)
        self.assertEqual([p.name for p in result.skipped], ["02_note.msg"])
        self.assertIn(".msg", result.skipped[0].skipped)
        self.assertIn("could not be read", bundle_mod.describe(result.parts))

    def test_nothing_readable_is_refused_with_the_reasons(self) -> None:
        data = _zip({"a.msg": b"x", "b.exe": b"y"})
        with self.assertRaises(bundle_mod.BundleError) as caught:
            bundle_mod.normalise(data, "t.zip", self.work)
        self.assertIn("a.msg", str(caught.exception))

    def test_a_lone_pdf_needs_no_zip(self) -> None:
        """The officer's ordinary upload takes the same path and keeps its own pages."""
        result = bundle_mod.normalise(_pdf(2), "case.pdf", self.work)
        self.assertEqual(result.pages, 2)
        self.assertEqual(len(result.parts), 1)
        self.assertEqual(result.parts[0].kind, "pdf")

    def test_a_member_cannot_escape_the_work_directory(self) -> None:
        """Anyone who can attach a file to a helpdesk ticket can name it ``../../x``."""
        data = _zip({"../../escaped.pdf": _pdf(1), "ok.pdf": _pdf(1)})
        result = bundle_mod.normalise(data, "t.zip", self.work)
        written = [p for p in self.work.rglob("*.pdf")]
        for path in written:
            self.assertTrue(str(path.resolve()).startswith(str(self.work.resolve())))
        self.assertGreaterEqual(result.pages, 1)

    def test_too_many_members_is_refused(self) -> None:
        with mock.patch.object(bundle_mod, "MAX_MEMBERS", 2):
            with self.assertRaises(bundle_mod.BundleError):
                bundle_mod.normalise(_zip({f"{n}.pdf": _pdf(1) for n in range(3)}),
                                     "t.zip", self.work)

    def test_inspect_reads_the_index_without_converting(self) -> None:
        """What the counter's click answers with: names, kinds, sizes, and nothing rendered."""
        data = _zip({"01_form.pdf": _pdf(1), "02_note.msg": b"x", "__MACOSX/._junk": b"x"})
        contents = bundle_mod.inspect(data, "t.zip")
        self.assertEqual([c["name"] for c in contents], ["01_form.pdf", "02_note.msg"])
        self.assertEqual([c["readable"] for c in contents], [True, False])

    def test_every_frame_of_a_multi_page_tiff_is_a_page(self) -> None:
        """exif_transpose hands back one frame; the pages must come from the file itself."""
        result = bundle_mod.normalise(_zip({"service book.tif": _tiff(3)}), "t.zip", self.work)
        self.assertEqual(result.pages, 3)
        self.assertEqual(result.parts[0].note, "")

    def test_a_tiff_past_the_frame_limit_is_cut_short_and_says_so(self) -> None:
        with mock.patch.object(bundle_mod, "MAX_FRAMES", 2):
            result = bundle_mod.normalise(_zip({"scan.tif": _tiff(4)}), "t.zip", self.work)
        self.assertEqual(result.pages, 2)
        self.assertIn("2 of 4", result.parts[0].note)
        self.assertIn("2 of 4", result.manifest()["parts"][0]["note"])

    def test_one_attachment_that_blows_up_loses_only_itself(self) -> None:
        """A decompression bomb, a codec Pillow lacks: that document is skipped, named, and why."""
        from PIL import Image
        data = _zip({"01_form.pdf": _pdf(1), "02_bomb.png": _png(), "03_odd.png": _png()})
        real = bundle_mod._image_to_pdf

        def explode(src, dst):
            if "bomb" in src.name:
                raise Image.DecompressionBombError("Image size exceeds limit")
            if "odd" in src.name:
                raise NotImplementedError("unsupported TIFF compression")
            return real(src, dst)

        with mock.patch.object(bundle_mod, "_image_to_pdf", explode):
            result = bundle_mod.normalise(data, "t.zip", self.work)
        self.assertEqual(result.pages, 1)
        reasons = {p.name: p.skipped for p in result.skipped}
        self.assertIn("DecompressionBombError", reasons["02_bomb.png"])
        self.assertIn("NotImplementedError", reasons["03_odd.png"])

    def test_a_member_whose_compressed_bytes_are_damaged_is_named(self) -> None:
        """A broken deflate stream raises zlib.error, which used to take the bundle with it."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("01_form.pdf", _pdf(1))
            z.writestr("02_cnic.png", _png(1200, 800) + b"\0" * 20000)
        raw = bytearray(buf.getvalue())
        info = zipfile.ZipFile(io.BytesIO(bytes(raw))).getinfo("02_cnic.png")
        start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        raw[start:start + 64] = b"\xff" * 64               # block type 3: not deflate at all
        result = bundle_mod.normalise(bytes(raw), "t.zip", self.work)
        self.assertEqual(result.pages, 1)
        [bad] = result.skipped
        self.assertEqual(bad.name, "02_cnic.png")
        self.assertIn("could not be read out of the zip", bad.skipped)

    def test_the_limits_count_every_level_of_nested_zip(self) -> None:
        """Two zips of three files are eight members, whatever each box holds on its own."""
        inner = _zip({f"{n}.pdf": _pdf(1) for n in range(3)})
        data = _zip({"a.zip": inner, "b.zip": inner})
        with mock.patch.object(bundle_mod, "MAX_MEMBERS", 5):
            with self.assertRaises(bundle_mod.BundleError) as caught:
                bundle_mod.normalise(data, "t.zip", self.work / "one")
        self.assertIn("limit is 5", str(caught.exception))
        # And the bytes, the same way.
        # Each level alone fits; the outer zip and both inner ones together do not.
        total = 2 * len(inner) + 6 * len(_pdf(1))
        with mock.patch.object(bundle_mod, "MAX_UNCOMPRESSED", total - 1):
            with self.assertRaises(bundle_mod.BundleError):
                bundle_mod.normalise(data, "t.zip", self.work / "two")
        # Under the limits the same bundle is six pages.
        self.assertEqual(bundle_mod.normalise(data, "t.zip", self.work / "three").pages, 6)

    def test_a_nested_zip_that_will_not_open_is_named_not_fatal(self) -> None:
        data = _zip({"01_form.pdf": _pdf(1), "02_more.zip": b"PK\x03\x04 not really"})
        result = bundle_mod.normalise(data, "t.zip", self.work)
        self.assertEqual(result.pages, 1)
        self.assertIn("could not be opened", result.skipped[0].skipped)

    def test_a_page_budget_stops_converting_once_it_is_met(self) -> None:
        """The counter's quick read wants five pages, not the whole bundle converted."""
        data = _zip({"01.pdf": _pdf(2), "02.pdf": _pdf(1), "03.png": _png()})
        result = bundle_mod.normalise(data, "t.zip", self.work, max_pages=3)
        self.assertEqual(result.pages, 3)
        self.assertEqual([p.name for p in result.skipped], ["03.png"])
        # Without one, everything is converted, as before.
        self.assertEqual(bundle_mod.normalise(data, "t.zip", self.work / "all").pages, 4)

    @unittest.skipUnless(shutil.which("soffice"), "LibreOffice is not installed here")
    def test_an_office_document_becomes_pages(self) -> None:
        data = _zip({"LPC.txt": b"LAST PAY CERTIFICATE\nBasic pay: Rs. 92,470\n"})
        result = bundle_mod.normalise(data, "t.zip", self.work)
        self.assertEqual(result.parts[0].converter, "libreoffice")
        self.assertGreaterEqual(result.pages, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
