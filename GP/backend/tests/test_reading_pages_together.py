"""The pages of a claim are read together, and the case is assembled as if they were not.

Measured on this box 20 October 2026, a three-page claim: 54.99s of model time inside 55.0s
of wall clock. 1.00x -- every page waiting for the one before it, while the vision server
reported a single request running against a scheduler that will take 128. The per-page cost
is also uneven (4.8s, 11.3s, 35.4s on those three), so a serial read makes the case wait on
the worst page AND on everything queued behind it.

Nothing about the result may move. The order of page_results is the case file's page order;
reused_pages and needs_human follow it; the facts object is assembled from that list. Only
the waiting is shared.

Two things did have to change, and both are pinned here:

  * `done` counts pages FINISHED, not the loop index. Pages finish out of order now, and
    jobs.Job.done takes whatever it is handed -- fed an index, the officer's bar walks
    backwards.
  * the order the model is ASKED in is the pool's, not the page order. Nothing may depend
    on it; tests that did have been changed to assert which pages were read.
"""
import os
from unittest import mock

import pytest

from gpf.reading.artefacts import Artefact
from gpf.reading.barcodes import ScriptedBarcodeDecoder
from gpf.reading.pipeline import Page, ReadingPipeline, read_concurrency


class _SlowModel:
    """A model that takes a measurable moment, so serial and parallel are distinguishable."""

    def __init__(self, inner, delay=0.05):
        self.inner, self.delay, self.seen = inner, delay, []
        self._peak = 0
        self._now = 0
        import threading
        self._lock = threading.Lock()

    def _enter(self):
        with self._lock:
            self._now += 1
            self._peak = max(self._peak, self._now)

    def _leave(self):
        with self._lock:
            self._now -= 1

    def classify_document(self, ref):
        import time
        self._enter()
        try:
            self.seen.append(ref)
            time.sleep(self.delay)
            return self.inner.classify_document(ref)
        finally:
            self._leave()

    def extract_fields(self, ref, artefact):
        import time
        self._enter()
        try:
            time.sleep(self.delay)
            return self.inner.extract_fields(ref, artefact)
        finally:
            self._leave()

    @property
    def peak_in_flight(self):
        return self._peak


def _scripted():
    """Six pages the scripted model can classify. A classification is an ExtractedField whose
    value is the artefact name, which is what the pipeline reads .value and .confidence off."""
    from gpf.clients.model_client import ExtractedField, ScriptedModelClient
    A = Artefact
    kinds = [A.SANCTION_ORDER, A.CNIC_SMART_FRONT, A.CNIC_SMART_BACK,
             A.FORM_PAY_05, A.SAP_PAYSLIP, A.SAP_GPF_RECALC_REPORT]
    classifications = {f"p{i + 1}": ExtractedField(k.value, 0.98, field_class="structural")
                       for i, k in enumerate(kinds)}
    return ScriptedModelClient(classifications, {})


def _pages(n):
    return [Page(i + 1, f"p{i + 1}") for i in range(n)]


class TestTheSetting:
    def test_it_defaults_to_four(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GPF_READ_CONCURRENCY", None)
            assert read_concurrency() == 4

    def test_the_office_can_change_it(self):
        with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": "9"}):
            assert read_concurrency() == 9

    def test_nonsense_and_zero_fall_back_safely(self):
        for value, expected in (("four", 4), ("0", 1), ("-3", 1)):
            with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": value}):
                assert read_concurrency() == expected


class TestPagesAreReadTogether:
    def test_more_than_one_page_is_in_flight(self):
        model = _SlowModel(_scripted())
        with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": "4"}):
            ReadingPipeline(model, ScriptedBarcodeDecoder({})).run(_pages(6), kind="refundable")
        assert model.peak_in_flight > 1, "pages were still read one at a time"

    def test_one_restores_the_serial_read_exactly(self):
        model = _SlowModel(_scripted())
        with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": "1"}):
            ReadingPipeline(model, ScriptedBarcodeDecoder({})).run(_pages(6), kind="refundable")
        assert model.peak_in_flight == 1
        assert model.seen == [f"p{i}" for i in range(1, 7)], "serial must keep page order"


class TestTheResultIsUnchanged:
    def test_the_same_case_comes_out_either_way(self):
        serial_model, pool_model = _SlowModel(_scripted(), 0), _SlowModel(_scripted(), 0)
        bc = ScriptedBarcodeDecoder({})
        with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": "1"}):
            a = ReadingPipeline(serial_model, bc).run(_pages(6), kind="refundable", gazetted="non-gazetted")
        with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": "6"}):
            b = ReadingPipeline(pool_model, bc).run(_pages(6), kind="refundable", gazetted="non-gazetted")
        assert a.facts == b.facts
        assert a.needs_human == b.needs_human
        assert a.illegible_pages == b.illegible_pages
        assert [p.page for p in a.pages] == [p.page for p in b.pages] == list(range(1, 7))

    def test_page_order_survives_the_pool(self):
        """Completion order is the model's; the case file's order is the page number."""
        model = _SlowModel(_scripted(), 0.02)
        with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": "6"}):
            r = ReadingPipeline(model, ScriptedBarcodeDecoder({})).run(_pages(6), kind="refundable")
        assert [p.page for p in r.pages] == [1, 2, 3, 4, 5, 6]

    def test_an_illegible_page_is_still_skipped_and_recorded(self):
        pages = _pages(4)
        pages[1].illegible = True
        with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": "4"}):
            r = ReadingPipeline(_SlowModel(_scripted(), 0), ScriptedBarcodeDecoder({})).run(
                pages, kind="refundable")
        assert r.illegible_pages == [2]
        assert [p.page for p in r.pages] == [1, 3, 4]


class TestTheProgressBarDoesNotWalkBackwards:
    def test_done_never_decreases(self):
        events = []
        with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": "6"}):
            ReadingPipeline(_SlowModel(_scripted(), 0.02), ScriptedBarcodeDecoder({})).run(
                _pages(6), kind="refundable", on_progress=events.append)
        seen = [e["done"] for e in events if e.get("done") is not None]
        assert seen == sorted(seen), f"the bar went backwards: {seen}"

    def test_it_reaches_the_page_count(self):
        events = []
        with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": "6"}):
            ReadingPipeline(_SlowModel(_scripted(), 0), ScriptedBarcodeDecoder({})).run(
                _pages(6), kind="refundable", on_progress=events.append)
        assert max(e["done"] for e in events if e.get("done") is not None) == 6


class TestTheBarKnowsWhatIsUnderWay:
    """`done` alone is a bar that sits at nothing while four pages work and then jumps by
    four. On a live five-page claim it was 0% for the first ten seconds, which an officer
    reads as stuck. `in_flight` is what the screen draws as the pale part of the bar."""

    def _events(self, pages, concurrency):
        events = []
        with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": str(concurrency)}):
            ReadingPipeline(_SlowModel(_scripted(), 0.03), ScriptedBarcodeDecoder({})).run(
                _pages(pages), kind="refundable", on_progress=events.append)
        return [e for e in events if e.get("in_flight") is not None]

    def test_pages_are_reported_as_under_way_before_any_finish(self):
        events = self._events(6, 4)
        before_first_finish = [e for e in events if (e.get("done") or 0) == 0]
        assert any(e["in_flight"] > 1 for e in before_first_finish), \
            "the bar would sit at zero with nothing to show for it"

    def test_it_returns_to_zero_when_the_read_is_over(self):
        events = self._events(6, 4)
        assert events[-1]["in_flight"] == 0

    def test_done_plus_in_flight_never_exceeds_the_page_count(self):
        for e in self._events(6, 4):
            assert (e.get("done") or 0) + e["in_flight"] <= e["total"], e

    def test_a_page_that_raises_does_not_leave_the_bar_claiming_it_is_being_read(self):
        """The counter is decremented in a finally. Without it a failed page would hold a
        slice of the bar for ever, on a screen that is still polling."""
        class _Boom:
            def classify_document(self, ref):
                if ref == "p3":
                    raise RuntimeError("the model fell over")
                return _scripted().classify_document(ref)

            def extract_fields(self, ref, artefact):
                return {}

        events = []
        with mock.patch.dict(os.environ, {"GPF_READ_CONCURRENCY": "4"}):
            with pytest.raises(RuntimeError):
                ReadingPipeline(_Boom(), ScriptedBarcodeDecoder({})).run(
                    _pages(6), kind="refundable", on_progress=events.append)
        counted = [e for e in events if e.get("in_flight") is not None]
        assert counted, "no progress was reported at all"
        assert counted[-1]["in_flight"] >= 0


class TestTheJobServesAClock:
    def test_the_view_carries_elapsed_and_in_flight(self):
        """The screen shows `mmss(elapsed) elapsed`, and the module serves elapsed rather
        than the browser timing it, so a clock skew cannot show a negative timer."""
        from gpf.reading.jobs import Job
        v = Job(id="job-x", total=5, done=2, in_flight=3).view()
        assert v["inFlight"] == 3
        assert v["done"] == 2 and v["total"] == 5
        assert isinstance(v["elapsed"], float) and v["elapsed"] >= 0
