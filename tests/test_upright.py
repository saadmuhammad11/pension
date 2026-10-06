"""A page scanned sideways is turned upright before anything reads it. extraction/upright.py.

    python3 -m unittest tests.test_upright -v

Nothing here touches a model. The reader is stubbed where the tests need one, and the pages
are drawn rather than scanned, so the same assertions hold on a machine with no OCR service.

What is being protected:

*   **Text upright, not paper portrait.** A genuinely landscape document -- a wide pay table --
    must be left alone. Rotating it would put readable text on its side, and page shape cannot
    tell it apart from a portrait page lying down.
*   **A page is never turned on a guess.** Where neither the layout nor the reader can say
    which way round a sideways page goes, it stays as scanned and the manifest says why. A
    page turned the wrong way is worse than one left alone: an officer can read a sideways
    page by tilting their head, and knows to.
*   **Nothing the department sent is thrown away.** The page as rendered is kept beside the
    upright copy.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extraction import upright


def _page(lines: int = 22, ragged: bool = True) -> "object":
    """A sheet of left-aligned typed text: tidy starts, ragged ends, like any form or letter."""
    from PIL import Image, ImageDraw
    img = Image.new("L", (1200, 1600), 255)
    d = ImageDraw.Draw(img)
    for i in range(lines):
        y = 90 + i * 60
        width = 820 - (i * 37) % 300 if ragged else 820
        d.rectangle([120, y, 120 + width, y + 26], fill=30)      # the body of the line
        d.rectangle([120, y - 12, 150, y + 26], fill=30)         # a capital, above the x-height
    return img


class WhichWayTheTextRuns(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="upright-")
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _save(self, img, name: str) -> Path:
        path = self.dir / name
        img.save(path)
        return path

    def test_an_ordinary_page_reads_across(self) -> None:
        axis, across, up = upright.text_axis(self._save(_page(), "upright.png"))
        self.assertEqual(axis, "horizontal")
        self.assertGreater(across, up)

    def test_the_same_page_on_its_side_reads_up(self) -> None:
        axis, across, up = upright.text_axis(
            self._save(_page().rotate(270, expand=True), "sideways.png"))
        self.assertEqual(axis, "vertical")
        self.assertGreater(up, across)

    def test_a_page_with_almost_no_text_is_not_judged(self) -> None:
        """A photograph of a CNIC, a page carrying one stamp: too little to tell."""
        from PIL import Image, ImageDraw
        img = Image.new("L", (1200, 800), 255)
        ImageDraw.Draw(img).rectangle([100, 100, 400, 140], fill=30)
        axis, _across, _up = upright.text_axis(self._save(img, "sparse.png"))
        self.assertEqual(axis, "unclear")

    def test_line_starts_are_tidier_the_right_way_up(self) -> None:
        """The one signal that tells 90° from 270°: left edges agree, right edges are ragged."""
        right_way = upright.tidy_line_starts(self._save(_page(), "a.png"))
        upside_down = upright.tidy_line_starts(
            self._save(_page().rotate(180, expand=True), "b.png"))
        self.assertGreater(right_way, 1.0)
        self.assertLess(upside_down, 1.0)
        self.assertGreater(right_way, upside_down)


class WhatIsDecided(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="upright-")
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _save(self, img, name: str) -> Path:
        path = self.dir / name
        img.save(path)
        return path

    def test_an_upright_page_is_left_alone_without_asking_a_reader(self) -> None:
        def never(_path):                                   # noqa: ANN001
            raise AssertionError("the reader must not be called on an upright page")
        turn = upright.decide(self._save(_page(), "upright.png"), never)
        self.assertEqual(turn.rotation, 0)
        self.assertFalse(turn.rotated)
        self.assertIn("across the page", turn.basis)

    def test_a_sideways_page_is_turned_the_way_the_reader_says_is_upright(self) -> None:
        # The page was turned 270° to make it sideways, so 90° puts it back.
        path = self._save(_page().rotate(270, expand=True), "sideways.png")
        turn = upright.decide(path, lambda candidate: "-90" in candidate.name)
        self.assertEqual(turn.rotation, 90)
        self.assertIn("reads upright", turn.basis)

    def test_a_sideways_page_is_left_alone_when_nothing_can_judge_it(self) -> None:
        path = self._save(_page().rotate(270, expand=True), "sideways.png")
        turn = upright.decide(path, None)
        self.assertEqual(turn.rotation, 0)
        self.assertIn("which way round", turn.basis)

    def test_a_page_both_ways_round_look_wrong_is_not_turned(self) -> None:
        """The bank form that defeated the layout cue: nothing is turned on a coin toss."""
        path = self._save(_page().rotate(270, expand=True), "ruled.png")
        turn = upright.decide(path, lambda _c: False)
        self.assertEqual(turn.rotation, 0)
        self.assertIn("both ways round look upside down", turn.basis)
        turn = upright.decide(path, lambda _c: True)
        self.assertEqual(turn.rotation, 0)
        self.assertIn("both ways round look right", turn.basis)

    def test_a_landscape_table_is_not_forced_upright(self) -> None:
        """Wide and readable is not the same as sideways. This is the one that must not move.

        No judge is given, and none should be needed: a page whose text runs across it is
        never a candidate, whatever shape the paper is.
        """
        from PIL import Image, ImageDraw
        img = Image.new("L", (1600, 1000), 255)
        d = ImageDraw.Draw(img)
        for i in range(12):                                  # wide rows of a pay table
            y = 80 + i * 70
            d.rectangle([80, y, 1500, y + 24], fill=30)
        turn = upright.decide(self._save(img, "table.png"), None)
        self.assertEqual(turn.rotation, 0)

    def test_a_reader_that_cannot_choose_leaves_the_page_as_scanned(self) -> None:
        """Unsure is not a vote. Nothing is guessed."""
        from PIL import Image, ImageDraw
        img = Image.new("L", (1000, 1400), 255)              # centred text: no tidy edge either way
        d = ImageDraw.Draw(img)
        for i in range(20):
            y, half = 80 + i * 64, 300 - (i * 29) % 120
            d.rectangle([500 - half, y, 500 + half, y + 24], fill=30)
        path = self._save(img.rotate(270, expand=True), "centred.png")
        turn = upright.decide(path, lambda _p: None)
        self.assertEqual(turn.rotation, 0)
        self.assertIn("left as scanned", turn.basis)

    def test_a_judge_that_raises_does_not_take_the_page_down_with_it(self) -> None:
        from PIL import Image, ImageDraw
        img = Image.new("L", (1000, 1400), 255)
        d = ImageDraw.Draw(img)
        for i in range(20):
            y, half = 80 + i * 64, 300 - (i * 29) % 120
            d.rectangle([500 - half, y, 500 + half, y + 24], fill=30)
        path = self._save(img.rotate(270, expand=True), "centred.png")

        def breaks(_candidate: Path) -> bool:
            raise RuntimeError("the vision service is down")

        turn = upright.decide(path, breaks)
        self.assertEqual(turn.rotation, 0)

    def test_the_page_as_scanned_is_kept(self) -> None:
        path = self._save(_page().rotate(270, expand=True), "p001.png")
        before = path.read_bytes()
        kept = path.with_name("p001-as-scanned.png")
        upright.apply(path, 90, kept)
        self.assertTrue(kept.exists())
        self.assertEqual(kept.read_bytes(), before)          # byte for byte, as it arrived
        from PIL import Image
        with Image.open(path) as turned:
            self.assertGreater(turned.height, turned.width)  # and the page in place is upright


class InTheBundle(unittest.TestCase):
    """A phone photograph carries its own rotation, and the camera is never wrong about it."""

    def test_a_photograph_taken_sideways_is_uprighted_from_its_exif_tag(self) -> None:
        import io
        from PIL import Image
        from pipeline import bundle

        with tempfile.TemporaryDirectory(prefix="exif-") as tmp:
            work = Path(tmp)
            # 6 = the camera was rotated 90° clockwise; the picture is stored on its side.
            wide = Image.new("RGB", (1200, 800), "white")
            exif = wide.getexif()
            exif[274] = 6
            src = work / "cnic.jpg"
            wide.save(src, exif=exif)

            dst = work / "cnic.pdf"
            bundle._image_to_pdf(src, dst)
            self.assertTrue(dst.exists())
            # Transposed to portrait before it was laid on the page, so the page is portrait.
            import subprocess
            out = subprocess.run(["pdfinfo", str(dst)], capture_output=True, text=True).stdout
            size = [l for l in out.splitlines() if l.startswith("Page size:")][0]
            w, h = (float(size.split()[2]), float(size.split()[4]))
            self.assertGreater(h, w)


if __name__ == "__main__":
    unittest.main(verbosity=2)
