"""A cached page reading is served only while the reader that made it is unchanged.

24 Oct 2026. Reuse makes a resubmission cheap -- a claim sent back for one certificate comes
back with every other page byte-identical, and re-reading them is two vision calls a page for
nothing. What it cost was the reason the office switched it off across both products on
23 Oct 2026: a page carried over keeps the reading it was given the FIRST time, right or
wrong, so a fix to the reader reaches an old page only on a run that re-reads it. PC-2026-
000070's ledger was mended today only because reuse was off.

The cache always had a version for this -- "bumped whenever what a page reading contains
changes" -- and a second hand-kept one beside it for pay slips. Both depend on somebody
remembering, and a forgotten bump does not fail loudly: it serves a stale reading for as long
as the case lives. The version is now a hash of the code that produces a page reading, so it
answers for itself, and reuse can be switched back on.

    python3 -m pytest tests/test_page_cache_follows_the_reader.py -q
"""
from __future__ import annotations

import json
import pathlib

import pytest

from gpf.reading import page_cache
from gpf.reading.page_cache import VERSION, PageCache, _reader_fingerprint

READER_DIR = pathlib.Path(page_cache.__file__).resolve().parent


@pytest.fixture
def cache(tmp_path):
    return PageCache(tmp_path, "portal-case-1")


def _put(c, key="k:1", artefact="SAP_GPF_RECALC_REPORT"):
    c.put(key, artefact=artefact, confidence=0.9, fields={}, codes=[])


class TestTheVersionIsTheReader:

    def test_it_is_a_hash_and_not_a_number_someone_keeps(self) -> None:
        assert isinstance(VERSION, str) and len(VERSION) == 16
        assert VERSION == _reader_fingerprint(), "it must not drift between calls"

    def test_it_is_taken_over_the_files_that_decide_a_reading(self) -> None:
        """If a file that reads a page is not in the hash, a change to it is invisible here
        and that is precisely the failure this replaces."""
        src = (READER_DIR / "page_cache.py").read_text(encoding="utf-8")
        for name in ("pipeline.py", "payslip_text.py", "recalc_text.py", "model_client.py"):
            assert name in src, name

    def test_a_change_to_any_of_them_changes_it(self, tmp_path, monkeypatch) -> None:
        before = _reader_fingerprint()
        target = READER_DIR / "recalc_text.py"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"\n# a reader change\n")
            assert _reader_fingerprint() != before
        finally:
            target.write_bytes(original)
        assert _reader_fingerprint() == before, "and the file is put back"


class TestWhatIsServedAndWhatIsNot:

    def test_a_reading_from_this_reader_is_served(self, cache) -> None:
        _put(cache)
        assert cache.get("k:1") is not None

    def test_a_reading_from_any_other_reader_is_not(self, cache, monkeypatch) -> None:
        _put(cache)
        monkeypatch.setattr(page_cache, "VERSION", "0000000000000000")
        assert cache.get("k:1") is None, "a page read by an older reader must be read again"

    def test_the_entry_records_which_reader_made_it(self, cache, tmp_path) -> None:
        _put(cache)
        entry = json.loads(next(pathlib.Path(cache.dir).glob("*.json")).read_text())
        assert entry["version"] == VERSION

    def test_the_hand_kept_payslip_stamp_is_gone(self, cache) -> None:
        """Two mechanisms for one question is how the second one is forgotten. payslip_text.py
        is in the hash, so a pay slip read before its LOAN/FUND block has a different version
        by construction."""
        _put(cache, artefact="SAP_PAYSLIP")
        entry = json.loads(next(pathlib.Path(cache.dir).glob("*.json")).read_text())
        assert "payslip_v" not in entry
        assert cache.get("k:1") is not None

    def test_a_page_nothing_has_read_is_a_miss(self, cache) -> None:
        assert cache.get("never-seen") is None

    def test_a_corrupt_entry_is_a_miss_and_not_a_crash(self, cache) -> None:
        _put(cache)
        next(pathlib.Path(cache.dir).glob("*.json")).write_text("{ not json")
        assert cache.get("k:1") is None


class TestNothingIsSharedBetweenCases:

    def test_two_cases_do_not_see_each_others_pages(self, tmp_path) -> None:
        a, b = PageCache(tmp_path, "portal-case-a"), PageCache(tmp_path, "portal-case-b")
        _put(a)
        assert a.get("k:1") is not None and b.get("k:1") is None
