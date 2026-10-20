"""One signature-block read per page, however many forms cite that page.

check_form runs once per prescribed form, and the caller de-duplicates on (type, pages). That
does nothing when several forms sit on the SAME sheet -- which is what a departmental bundle
looks like when Form B-I, B-II, B-III and B-IV are printed on one page. On a real 78-page
bundle page 13 was cited by five documents and read four times by the signature reader, each
read identical and three of them discarded (20 Oct 2026).

read_block asks only about the image: same schema, same instruction, same limits, no document
in the question. So the answer cannot differ between callers, and caching it by page is a
saving with no judgement attached.

    python3 -m unittest tests.test_signature_block_cache -v
"""
from __future__ import annotations

import unittest
import unittest.mock
from pathlib import Path

from pipeline import signatory


class SignatureBlockCache(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []

        def fake_extract(image, schema, **kw):
            self.calls.append(str(image))
            return unittest.mock.Mock(data={"signature_present": True, "stamp_present": False,
                                            "seen": str(image)})
        self._p = unittest.mock.patch.object(signatory, "extract_page", fake_extract)
        self._p.start(); self.addCleanup(self._p.stop)

    def test_the_same_page_is_read_once(self) -> None:
        cache: dict = {}
        img = Path("/pages/p013-13.png")
        first = signatory.read_block(img, cache)
        for _ in range(4):
            again = signatory.read_block(img, cache)
            self.assertEqual(again, first, "a cached answer must be the answer")
        self.assertEqual(len(self.calls), 1, "four forms on one page must not read it four times")

    def test_different_pages_are_each_read(self) -> None:
        cache: dict = {}
        signatory.read_block(Path("/pages/p013-13.png"), cache)
        signatory.read_block(Path("/pages/p014-14.png"), cache)
        self.assertEqual(len(self.calls), 2)

    def test_no_cache_means_no_caching(self) -> None:
        """The parameter is optional; without it the old behaviour stands."""
        img = Path("/pages/p013-13.png")
        signatory.read_block(img)
        signatory.read_block(img)
        self.assertEqual(len(self.calls), 2)

    def test_the_cached_value_is_the_blocks_data_not_the_wrapper(self) -> None:
        cache: dict = {}
        out = signatory.read_block(Path("/pages/p013-13.png"), cache)
        self.assertEqual(out["seen"], "/pages/p013-13.png")
        self.assertIs(cache["/pages/p013-13.png"], out)


if __name__ == "__main__":
    unittest.main()
