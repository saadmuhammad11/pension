"""A ledger the model could not finish reading must not fail the examination.

PC-2026-000050, 23 Oct 2026. The GPF Final Re-calculation Report is one row a year with ten
numeric columns, asked for as JSON in a single call. A long service history overran the
4,000-token ceiling, the reply came back cut mid-number, and `json.loads` raised straight out
of the read:

    JSONDecodeError: Expecting ',' delimiter: line 1 column 7681 (char 7680)
    JSONDecodeError: Expecting value: line 1 column 7740 (char 7739)

Two generations stopping 59 characters apart is a ceiling, not a coincidence. The case went to
AI_FAILED twice, and the officer was shown a Python exception.
"""
from __future__ import annotations

import json
from unittest import mock

from gpf.clients.model_client import VllmModelClient


def _client() -> VllmModelClient:
    """A client without its __init__: the endpoints are mocked, nothing is dialled."""
    c = VllmModelClient.__new__(VllmModelClient)
    c.vision_url, c.vision_model = "http://vision.invalid", "test-vision"
    c.ocr_url, c.ocr_model = "http://ocr.invalid", "test-ocr"
    c.reasoning_url, c.reasoning_model = "http://reason.invalid", "test-reason"
    c.api_key, c.timeout = "test", 5
    return c


def _reply(content: str, finish: str = "stop") -> dict:
    return {"choices": [{"finish_reason": finish, "message": {"content": content}}]}


def test_a_truncated_ledger_reads_as_no_rows_rather_than_raising() -> None:
    cut = '{"rows": [{"start": "01.07.2001", "end": "30.06.2002", "opening": 1234'
    with mock.patch.object(VllmModelClient, "_chat", return_value=_reply(cut, "length")), \
            mock.patch.object(VllmModelClient, "_image_url", return_value="data:,"):
        rows, conf = _client()._extract_recalc_rows("p1.png")
    assert rows == [] and conf == 0.0


def test_a_reply_that_is_not_json_reads_as_no_rows_too() -> None:
    with mock.patch.object(VllmModelClient, "_chat", return_value=_reply("I could not read it.")), \
            mock.patch.object(VllmModelClient, "_image_url", return_value="data:,"):
        rows, conf = _client()._extract_recalc_rows("p1.png")
    assert rows == [] and conf == 0.0


def test_a_whole_ledger_is_still_read() -> None:
    whole = json.dumps({"rows": [{"start": "01.07.2001", "closing": 5000}], "confidence": 0.91})
    with mock.patch.object(VllmModelClient, "_chat", return_value=_reply(whole)), \
            mock.patch.object(VllmModelClient, "_image_url", return_value="data:,"):
        rows, conf = _client()._extract_recalc_rows("p1.png")
    assert len(rows) == 1 and conf == 0.91


def test_the_ceiling_is_high_enough_for_a_long_service_history() -> None:
    """Forty years at ten columns a row does not fit in four thousand tokens."""
    seen: dict = {}

    def capture(self, url, model, messages, **kw):
        seen.update(kw)
        return _reply(json.dumps({"rows": [], "confidence": 0.5}))

    with mock.patch.object(VllmModelClient, "_chat", capture), \
            mock.patch.object(VllmModelClient, "_image_url", return_value="data:,"):
        _client()._extract_recalc_rows("p1.png")
    assert seen["max_tokens"] >= 12000
