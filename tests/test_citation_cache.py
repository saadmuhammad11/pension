"""Citations: reproducible, cheap, and free of case facts. ``rag.store``, ``pipeline.report``.

    python3 -m unittest tests.test_citation_cache -v

Hermetic. ``rag.store.search`` is stubbed throughout -- the point is the caching, the
de-duplication and what is allowed onto disk, none of which needs a model. The cache file and
the index fingerprint are redirected into a temporary directory, so no test can write into
``artifacts/rag/`` where the real index lives.

Three things are being pinned.

**Reproducibility.** SOP §8.5.1 requires the same papers and the same rule pack to yield the
same determination whenever recomputed, and §8.5.3 has an auditor recompute one and compare it
against the record. The reranker runs on a GPU and its score is not bit-stable: rebuilding one
case's report moved a citation score from 0.9623 to 0.9627, so a recomputation differed from
the record in a way that was not a difference. At ``top_n=1`` a near-tie could have changed
which passage was cited at all.

**Cost.** Retrieval was the entire cost of a report. Measured on the golden case: 12.40s with
citations against 0.00s without, 17 sequential embed-then-rerank round trips.

**Data handling.** BRAIN §15.4 keeps case facts inside the case record. The first run of this
cache wrote "Family pension for widow daughter of late Muhammad Bashir" and "CNIC copy at p.45
is not referred to anywhere in the case" into a shared file under ``artifacts/rag/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# So the file runs directly as well as under `-m unittest` from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
import tempfile
import unittest
from unittest import mock

from rag import store


class _Fixture(unittest.TestCase):
    """A store whose index, cache file and retrieval are all under the test's control."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.index_path = tmp / "index.json"
        self.index_path.write_text(json.dumps({"model": "test", "dims": 2, "chunks": [],
                                               "vectors": []}))
        self.cache_path = tmp / "citations.json"
        self.calls: list[str] = []

        self._patches = [
            mock.patch.object(store, "INDEX_PATH", self.index_path),
            mock.patch.object(store, "CITATIONS_PATH", self.cache_path),
            mock.patch.object(store, "_FINGERPRINT", None),
            mock.patch.object(store, "_CITATIONS", None),
            mock.patch.object(store, "_INDEX", {"model": "test", "dims": 2,
                                                "chunks": [], "vectors": []}),
            mock.patch.object(store, "search", self._search),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(self.tmp.cleanup)
        for p in self._patches:
            self.addCleanup(p.stop)

    #: Returns a different score every call, exactly as the reranker does.
    def _search(self, query: str, *, top_n: int = 1, **kwargs):
        self.calls.append(query)
        chunk = store.Chunk(id="c1", text=f"passage for {query}", source="s.md",
                            heading="h")
        return [store.Hit(chunk, 0.9 + len(self.calls) / 10_000, "reranker")]

    def entries(self) -> dict:
        return json.loads(self.cache_path.read_text())["entries"]


class TheSecondReadIsTheFirstRead(_Fixture):
    """A cached citation is returned verbatim, so a rebuilt report is byte-identical."""

    def test_a_repeated_query_is_not_retrieved_twice(self):
        first = store.cite_many(["a rule question"], cacheable=["a rule question"])
        second = store.cite_many(["a rule question"], cacheable=["a rule question"])
        self.assertEqual(first, second)
        self.assertEqual(self.calls, ["a rule question"])

    def test_the_score_does_not_drift(self):
        """The defect, directly: without the cache the same query scores differently."""
        uncached_a = store.cite_many(["q"])["q"][0]["score"]
        uncached_b = store.cite_many(["q"])["q"][0]["score"]
        self.assertNotEqual(uncached_a, uncached_b)

        cached_a = store.cite_many(["r"], cacheable=["r"])["r"][0]["score"]
        cached_b = store.cite_many(["r"], cacheable=["r"])["r"][0]["score"]
        self.assertEqual(cached_a, cached_b)

    def test_a_duplicate_query_in_one_batch_is_retrieved_once(self):
        out = store.cite_many(["same", "same", "other"], cacheable=["same", "other"])
        self.assertEqual(sorted(self.calls), ["other", "same"])
        self.assertEqual(sorted(out), ["other", "same"])

    def test_the_caller_gets_a_copy_it_may_mutate(self):
        """A report is a mutable structure; an edit to one step's citation must not appear
        under another's, nor poison the cache."""
        out = store.cite_many(["q"], cacheable=["q"])
        out["q"][0]["citation"] = "edited"
        again = store.cite_many(["q"], cacheable=["q"])
        self.assertNotEqual(again["q"][0]["citation"], "edited")


class TheCacheCannotOutliveItsCorpus(_Fixture):
    """A citation is a function of the corpus. Rebuild the index and the cache falls away."""

    def test_a_rebuilt_index_invalidates_everything(self):
        store.cite_many(["q"], cacheable=["q"])
        self.assertEqual(len(self.entries()), 1)

        self.index_path.write_text(json.dumps({"model": "test", "dims": 2,
                                               "chunks": [{"id": "new"}], "vectors": [[1, 0]]}))
        store._FINGERPRINT = None
        store._CITATIONS = None
        store.cite_many(["q"], cacheable=["q"])
        self.assertEqual(self.calls, ["q", "q"])     # retrieved again against the new corpus

    def test_the_fingerprint_is_recorded_beside_the_entries(self):
        store.cite_many(["q"], cacheable=["q"])
        written = json.loads(self.cache_path.read_text())
        self.assertEqual(written["fingerprint"], store.index_fingerprint())

    def test_a_corrupt_cache_file_is_discarded_not_fatal(self):
        self.cache_path.write_text("{ not json")
        store._CITATIONS = None
        out = store.cite_many(["q"], cacheable=["q"])
        self.assertEqual(out["q"][0]["citation"], "s.md — h")

    def test_a_cache_that_cannot_be_written_does_not_fail_the_report(self):
        """An unwritable artifacts directory is an operations problem, not a case problem."""
        with mock.patch.object(store, "CITATIONS_PATH",
                               Path(self.tmp.name) / "nope" / "x" / "c.json"):
            with mock.patch("pathlib.Path.mkdir", side_effect=OSError("read-only")):
                out = store.cite_many(["q"], cacheable=["q"])
        self.assertEqual(out["q"][0]["scored_by"], "reranker")


class WhatIsNeverWrittenToDisk(_Fixture):
    """Two things: a case fact, and a degraded citation."""

    def test_a_query_not_marked_cacheable_is_never_persisted(self):
        case_query = "Family pension for widow daughter of late Muhammad Bashir"
        store.cite_many([case_query])
        self.assertFalse(self.cache_path.exists() and self.entries())

    def test_an_uncacheable_query_is_still_answered(self):
        out = store.cite_many(["CNIC copy at p.45 is not referred to anywhere in the case"])
        self.assertEqual(len(out), 1)
        self.assertEqual(next(iter(out.values()))[0]["scored_by"], "reranker")

    def test_a_mixed_batch_persists_only_the_rule_questions(self):
        store.cite_many(["a rule question", "a case fact"], cacheable=["a rule question"])
        self.assertEqual(list(self.entries()), ["1|a rule question"])

    def test_a_degraded_citation_is_not_cached(self):
        """One outage must not become the permanent answer."""
        def degraded(query, *, top_n=1, **kw):
            chunk = store.Chunk(id="c", text="t", source="s.md", heading="h")
            return [store.Hit(chunk, 0.5, "embedding (reranker unreachable)")]

        with mock.patch.object(store, "search", degraded):
            out = store.cite_many(["q"], cacheable=["q"])
        self.assertEqual(out["q"][0]["scored_by"], "embedding (reranker unreachable)")
        self.assertFalse(self.cache_path.exists() and self.entries())

    def test_a_failed_retrieval_degrades_visibly_and_is_not_cached(self):
        with mock.patch.object(store, "search",
                               side_effect=store.RagError("cannot reach the reranker")):
            out = store.cite_many(["q"], cacheable=["q"])
        self.assertEqual(out["q"][0]["scored_by"], "none")
        self.assertIn("retrieval unavailable", out["q"][0]["citation"])
        self.assertEqual(out["q"][0]["score"], 0.0)
        self.assertFalse(self.cache_path.exists() and self.entries())

    def test_one_failure_does_not_lose_the_other_citations(self):
        def flaky(query, *, top_n=1, **kw):
            if query == "bad":
                raise store.RagError("down")
            chunk = store.Chunk(id="c", text="t", source="s.md", heading="h")
            return [store.Hit(chunk, 0.9, "reranker")]

        with mock.patch.object(store, "search", flaky):
            out = store.cite_many(["good", "bad"], cacheable=["good", "bad"])
        self.assertEqual(out["good"][0]["scored_by"], "reranker")
        self.assertEqual(out["bad"][0]["scored_by"], "none")
        self.assertEqual(list(self.entries()), ["1|good"])


class EveryRuleAndFlagHasAQuestionOfItsOwn(unittest.TestCase):
    """The guard that keeps case facts out of the retrieval query in the first place.

    ``_cite_all`` falls back to a step's description or a flag's title where the curated maps
    cover neither. On a D-II case those read "Family pension for widow daughter of late
    Muhammad Bashir" and "CNIC copy at p.2 is not referred to anywhere in the case": a poor
    query for a rule, and a case fact in a retrieval call. The death-after-retirement path
    landed after the maps were written and every one of its steps fell through.

    This asserts the maps cover what the code can actually emit, so the next path added goes
    red here rather than quietly citing somebody's name.
    """

    def test_every_rule_id_the_engines_emit_has_a_curated_question(self):
        import re

        from pipeline.report import _RULE_QUERY

        emitted = set()
        for module in ("rules/engine.py", "rules/dii.py"):
            text = (ROOT / module).read_text()
            emitted |= set(re.findall(r'rule_id\s*=\s*"([A-Z][A-Z0-9-]+)"', text))
        uncurated = sorted(r for r in emitted if r not in _RULE_QUERY)
        self.assertEqual(
            uncurated, [],
            f"these rule ids would cite on their own step description, which carries case "
            f"facts: {uncurated}. Add a question about the rule to _RULE_QUERY.",
        )

    def test_every_flag_class_has_a_curated_question(self):
        from pipeline.report import _FLAG_QUERY
        from rules import flags as flag_module

        classes = {
            getattr(flag_module, name)
            for name in dir(flag_module)
            if name.isupper() and isinstance(getattr(flag_module, name), str)
            and "-" in getattr(flag_module, name)
        }
        uncurated = sorted(c for c in classes if c not in _FLAG_QUERY)
        self.assertEqual(
            uncurated, [],
            f"these flag classes would cite on their own title, which carries case facts: "
            f"{uncurated}. Add a question about the rule to _FLAG_QUERY.",
        )


if __name__ == "__main__":
    unittest.main()
