"""The per-run read cache (extraction.readcache, perf/read-cache).

The pipeline reads the same page with the vision model in stage 4 and again in stage 6; the cache
removes the repeat. These tests pin the three properties the pipeline depends on: a repeat read of
the same (page, schema) does not reach the model; the stored result is isolated from the caller's
mutations (the stages blank disputed fields and stamp the agreement); and a different image or
schema is a different read.
"""

import tempfile
import unittest
from pathlib import Path

from extraction.client import Extraction
from extraction.readcache import ReadCache


def _extraction(rows: int = 2) -> Extraction:
    return Extraction(
        data={"pay_components": [{"amount": 100} for _ in range(rows)], "note": "first"},
        doc_type="FORM_D_I",
        schema_name="FORM_D_I",
        source="test",
        model="test-model",
        prompt_version="v1",
        latency_s=1.0,
        prompt_tokens=10,
        completion_tokens=20,
    )


class CountingReader:
    """Stands in for extract_page_confirmed; records how many real reads happened."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, image, schema_name="GENERIC_PAGE", **kwargs):
        self.calls.append((str(image), schema_name))
        return _extraction(), {"agree": True, "page": None, "document": None}


class ReadCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.page = Path(self.tmp.name) / "p041.png"
        self.page.write_bytes(b"\x89PNG-page-41-bytes")
        self.other = Path(self.tmp.name) / "p042.png"
        self.other.write_bytes(b"\x89PNG-page-42-bytes")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_repeat_same_page_schema_is_not_re_read(self):
        cache = ReadCache()
        reader = CountingReader()
        for _ in range(3):
            cache.confirmed(self.page, "FORM_D_I", reader=reader)
        self.assertEqual(len(reader.calls), 1, "the page was read more than once")
        self.assertEqual(cache.misses, 1)
        self.assertEqual(cache.hits, 2)

    def test_double_read_still_happens_on_the_miss(self):
        # The cache removes the REPEAT, never the first confirming read: the reader (which is the
        # double read in production) is called exactly once for a never-seen page.
        cache = ReadCache()
        reader = CountingReader()
        cache.confirmed(self.page, "FORM_D_I", reader=reader)
        self.assertEqual(len(reader.calls), 1)

    def test_different_schema_is_a_separate_read(self):
        cache = ReadCache()
        reader = CountingReader()
        cache.confirmed(self.page, "FORM_D_I", reader=reader)
        cache.confirmed(self.page, "GENERIC_PAGE", reader=reader)
        self.assertEqual(len(reader.calls), 2)

    def test_different_image_bytes_is_a_separate_read(self):
        # Stage 4's upright-corrected image and stage 6's raw image differ in bytes where the
        # correction changed the pixels; they must not share a cache entry.
        cache = ReadCache()
        reader = CountingReader()
        cache.confirmed(self.page, "FORM_D_I", reader=reader)
        cache.confirmed(self.other, "FORM_D_I", reader=reader)
        self.assertEqual(len(reader.calls), 2)

    def test_hit_is_isolated_from_caller_mutation(self):
        # The stages mutate what they get back (blank disputed figures, stamp the agreement onto
        # it). A later hit must see the pristine read, not the first caller's edits.
        cache = ReadCache()
        reader = CountingReader()
        ext1, agree1 = cache.confirmed(self.page, "FORM_D_I", reader=reader)
        ext1.data["pay_components"] = []          # as H1 blanking would
        ext1.data["note"] = "mutated"
        agree1["page"] = 41

        ext2, agree2 = cache.confirmed(self.page, "FORM_D_I", reader=reader)
        self.assertEqual(len(ext2.data["pay_components"]), 2, "cached read was corrupted")
        self.assertEqual(ext2.data["note"], "first")
        self.assertIsNone(agree2["page"], "cached agreement was corrupted")

    def test_miss_result_is_isolated_too(self):
        # Even the value returned on the MISS must not let the caller reach into the store.
        cache = ReadCache()
        reader = CountingReader()
        ext1, _ = cache.confirmed(self.page, "FORM_D_I", reader=reader)
        ext1.data["note"] = "mutated"
        ext2, _ = cache.confirmed(self.page, "FORM_D_I", reader=reader)
        self.assertEqual(ext2.data["note"], "first")


if __name__ == "__main__":
    unittest.main()
