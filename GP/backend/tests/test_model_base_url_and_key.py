"""The model base URL may be given with or without /v1, and the key is never dropped.

20 October 2026. Clicking "Examine with AI" on a GP Fund case failed with
"Reading the claim... unauthorized". Nothing was unauthorised. Two faults in series:

1. GPF_VLLM_URL on the live box was http://host:8000/v1 -- which is what an
   OpenAI-compatible "base URL" normally means, and what every other model setting in
   /etc/pension/pension.env looks like. But this client appends its own "/v1/..." to every
   request, so discovery asked for /v1/v1/models and got a 404.

2. The `except` around discovery then built the fallback client WITHOUT the api_key, so the
   key defaulted to "EMPTY" and every later call to the model server came back 401. A 404 in
   discovery was reported to the officer as "Unauthorized".

The second is the one that cost the time: a fallback that quietly drops a credential does not
degrade, it lies about why it failed.
"""
import importlib
import os
from unittest import mock

import pytest

from gpf.clients.model_client import VllmModelClient, _server_root


class TestTheBaseUrlIsAccepptedEitherWay:
    @pytest.mark.parametrize("given", [
        "http://model-host.internal:8000",
        "http://model-host.internal:8000/",
        "http://model-host.internal:8000/v1",
        "http://model-host.internal:8000/v1/",
    ])
    def test_every_spelling_resolves_to_the_server_root(self, given):
        assert _server_root(given) == "http://model-host.internal:8000"

    def test_the_client_holds_the_root_whatever_it_was_given(self):
        c = VllmModelClient("http://h:8000/v1", api_key="k")
        assert c.vision_url == "http://h:8000"
        assert c.reasoning_url == "http://h:8000"
        assert c.ocr_url == "http://h:8000"

    def test_a_path_that_is_not_v1_is_left_alone(self):
        """Only a trailing /v1 is the OpenAI prefix. A real path must survive."""
        assert _server_root("http://h:8000/models/vision") == "http://h:8000/models/vision"

    def test_empty_stays_empty(self):
        assert _server_root("") == ""
        assert _server_root(None) == ""


class TestDiscoveryAsksForTheRightPath:
    def test_it_does_not_double_the_prefix(self):
        seen = {}

        class _Resp:
            def read(self): return b'{"data":[{"id":"qwen3-vl-30b-a3b-fp8"}]}'
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["auth"] = req.headers.get("Authorization")
            return _Resp()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            ids = VllmModelClient._list_models("http://h:8000/v1", "the-key", 5.0)

        assert seen["url"] == "http://h:8000/v1/models", "the /v1 was doubled"
        assert seen["auth"] == "Bearer the-key", "discovery must carry the key"
        assert ids == ["qwen3-vl-30b-a3b-fp8"]


class TestTheFallbackKeepsTheKey:
    def test_a_client_built_after_failed_discovery_still_authenticates(self):
        """Point the module at an address nothing answers on, so discovery fails, and check
        the client it falls back to still carries the key."""
        env = {"GPF_VLLM_URL": "http://127.0.0.1:1/v1",      # nothing listens on port 1
               "PENSION_MODEL_API_KEY": "the-key",
               "GPF_VLLM_URLS": "", "GPF_VLLM_API_KEY": ""}
        import gpf.api as gpf_api
        with mock.patch.dict(os.environ, env):
            reloaded = importlib.reload(gpf_api)
            try:
                client = reloaded.model_client
                assert isinstance(client, VllmModelClient), type(client)
                assert client.api_key == "the-key", "the fallback dropped the credential"
            finally:
                importlib.reload(gpf_api)

    def test_the_key_comes_from_the_pipelines_own_setting(self):
        import gpf.api as gpf_api
        with mock.patch.dict(os.environ, {"PENSION_MODEL_API_KEY": "from-pension",
                                          "GPF_VLLM_API_KEY": ""}):
            assert gpf_api._model_api_key() == "from-pension"
        with mock.patch.dict(os.environ, {"PENSION_MODEL_API_KEY": "from-pension",
                                          "GPF_VLLM_API_KEY": "override"}):
            assert gpf_api._model_api_key() == "override"
