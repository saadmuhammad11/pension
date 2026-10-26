"""The concurrent vision read must stay in the job log (26 Oct 2026).

Making the two ledger reads start together took PC-2026-000055's six pages from 107.1s to
72.3s. The job log for that run showed model time falling 189.8s -> 157.6s and the `recalc`
call gone from it altogether -- not because the call stopped happening, but because it had
moved into a pool worker, and the job id is a threading.local that a worker does not inherit.
record() found no job and dropped the row.

The wall-clock win was real; the model-time figure was not. A speed change that quietly
switches off the thing measuring it is the one change that must not be trusted on its own
evidence, so the binding is pinned here.
"""
from __future__ import annotations

from unittest import mock

from gpf.clients.model_client import VllmModelClient
from gpf.reading import timing


def _client() -> VllmModelClient:
    c = VllmModelClient.__new__(VllmModelClient)
    c.vision_url, c.vision_model = "http://vision.invalid", "test-vision"
    c.ocr_url, c.ocr_model = "http://ocr.invalid", "test-ocr"
    c.reasoning_url, c.reasoning_model = "http://reason.invalid", "test-reason"
    c.api_key, c.timeout = "test", 5
    return c


def test_the_vision_read_runs_bound_to_the_job_that_asked_for_it() -> None:
    seen: list[str | None] = []

    def spy(self, image_ref):
        seen.append(timing.current())
        return [], 0.0

    # An OCR read that returns nothing, so the page cannot finish on the fast path and the
    # vision read is genuinely waited for.
    with mock.patch.object(VllmModelClient, "_recalc_rows_from_vision", spy), \
            mock.patch.object(VllmModelClient, "ocr_table_text", return_value=("", False)):
        with timing.bind("job-under-test"):
            _client()._extract_recalc_rows("p6.png")

    assert seen == ["job-under-test"], (
        f"the vision read saw job {seen!r}; unbound, every recalc call it makes is dropped "
        "from the job log and the run under-reports its own model time")


def test_the_binding_does_not_leak_back_into_the_calling_thread() -> None:
    with mock.patch.object(VllmModelClient, "_recalc_rows_from_vision", return_value=([], 0.0)), \
            mock.patch.object(VllmModelClient, "ocr_table_text", return_value=("", False)):
        with timing.bind("job-outer"):
            _client()._extract_recalc_rows("p6.png")
            assert timing.current() == "job-outer"
    assert timing.current() is None
