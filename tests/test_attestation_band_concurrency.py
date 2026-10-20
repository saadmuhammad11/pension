"""The attestation bands are read at once, and say exactly what reading them in turn said.

attestation_on splits a page into a top band and a foot band and only the FOOT's designations
count -- a letterhead naming the issuing office is not an attestation. The two reads were done
one after the other: 56s of serial OCR on the slowest page of a run (19 Oct 2026), on the
critical path of stage 6.

So band ORDER is not cosmetic here: bands[0] and bands[-1] mean the top and the foot, and a pool
that returned them in completion order would read a letterhead as an attesting officer. That,
the foot_read flag, and the refusal and degenerate paths are what this holds.

    python3 -m unittest tests.test_attestation_band_concurrency -v
"""
from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from extraction import ocr as O


def _page(path: Path, w: int, h: int) -> None:
    """Second half solid black, first half white, so a stub reader can tell the bands apart by
    what is IN the crop rather than by the order it was called in.

    Solid, not sparse: the bands overlap by _BAND_OVERLAP, so the top band legitimately
    contains a tenth of the foot. A faint signal put both bands over the same threshold and
    the test then passed with the two bands deliberately swapped. With a solid half the top
    band is ~17% dark and the foot ~83%, which a 50% threshold separates with room to spare."""
    from PIL import Image
    im = Image.new("RGB", (w, h), (255, 255, 255))
    half = (w // 2, 0, w, h) if w > h else (0, h // 2, w, h)
    im.paste((0, 0, 0), half)
    im.save(path)


class AttestationBands(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, conc: int, *, w: int, h: int, fail: str | None = None,
             degenerate: bool = False):
        from PIL import Image
        img = Path(self.tmp.name) / f"p{w}x{h}.png"
        if not img.exists():
            _page(img, w, h)

        def stub(path, page, **kw):
            with Image.open(path) as c:
                px = list(c.convert("L").getdata())
                dark = sum(1 for v in px if v < 128) / max(1, len(px))
            which = "foot" if dark > 0.5 else "top"
            if fail == which:
                raise O.OcrError(f"refused the {which} band")
            if degenerate and which == "foot":
                return O.PageText(page=page, text="X" * 400, model=O.OCR_MODEL)
            body = ("ATTESTED Dy. Superintendent of Police" if which == "foot"
                    else "OFFICE OF THE SENIOR HEADMISTRESS")
            return O.PageText(page=page, text=body, model=O.OCR_MODEL)

        with unittest.mock.patch.object(O, "ATTESTATION_BAND_CONCURRENCY", conc), \
             unittest.mock.patch.object(O, "ocr_page", stub):
            a = O.attestation_on(img, page=18)
            return tuple(a.marks), a.read_the_foot

    def test_only_the_foot_designation_counts(self) -> None:
        """The property the bands exist for, pinned to a value rather than to each other.

        Comparing concurrency 1 against concurrency 2 cannot catch a fault in the code BOTH
        run -- the bands were deliberately swapped during review and the comparison still
        passed, because it reversed them on both sides. So this asserts what the docstring
        promises: the FOOT's designation is an attestation, the top's letterhead is not.
        """
        for conc in (1, 2):
            with self.subTest(concurrency=conc):
                marks, foot_read = self._run(conc, w=800, h=1200)
                self.assertIn("SUPERINTENDENT OF POLICE", marks,
                              "the foot band's designation must be counted")
                self.assertNotIn("HEADMISTRESS", marks,
                                 "the top band is a letterhead and must NOT count as attesting")
                self.assertNotIn("SENIOR HEADMISTRESS", marks)
                self.assertTrue(foot_read)

    def test_portrait_page_matches(self) -> None:
        want = self._run(1, w=800, h=1200)
        self.assertEqual(self._run(2, w=800, h=1200), want)
        self.assertTrue(want[0], "the fixture must find at least one mark")

    def test_landscape_page_matches(self) -> None:
        want = self._run(1, w=1200, h=600)
        self.assertEqual(self._run(2, w=1200, h=600), want)

    def test_a_refused_band_matches(self) -> None:
        for fail in ("top", "foot"):
            with self.subTest(refused=fail):
                want = self._run(1, w=800, h=1200, fail=fail)
                self.assertEqual(self._run(2, w=800, h=1200, fail=fail), want)

    def test_a_degenerate_foot_matches(self) -> None:
        want = self._run(1, w=800, h=1200, degenerate=True)
        self.assertEqual(self._run(2, w=800, h=1200, degenerate=True), want)

    def test_the_pool_is_configurable_and_never_below_one(self) -> None:
        import importlib
        import os
        for given, expect in (("4", 4), ("1", 1), ("0", 1), ("", 2)):
            with unittest.mock.patch.dict(os.environ, {"PENSION_ATTESTATION_BAND_CONCURRENCY": given}):
                self.assertEqual(importlib.reload(O).ATTESTATION_BAND_CONCURRENCY, expect, f"for {given!r}")
        importlib.reload(O)


if __name__ == "__main__":
    unittest.main()
