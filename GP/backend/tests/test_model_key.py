"""The GP module sends the model servers their key (audit 6 Oct 2026, item 7).

The vision, OCR and embedding servers now refuse a /v1 request without
"Authorization: Bearer <VLLM_API_KEY>". The module takes the pipeline's PENSION_MODEL_API_KEY
(or its own GPF_VLLM_API_KEY) and its client sends it on discovery and on every call.
"""
import http.server
import threading

from gpf import api
from gpf.clients import VllmModelClient

KEY = "g" * 16 + "Kq8sV3xN1bT6wY2zR9pL4cH7"


def test_key_comes_from_the_pipeline_setting_unless_overridden(monkeypatch):
    monkeypatch.delenv("GPF_VLLM_API_KEY", raising=False)
    monkeypatch.delenv("PENSION_MODEL_API_KEY", raising=False)
    assert api._model_api_key() == "EMPTY"
    monkeypatch.setenv("PENSION_MODEL_API_KEY", KEY)
    assert api._model_api_key() == KEY
    monkeypatch.setenv("GPF_VLLM_API_KEY", "override-" + KEY)
    assert api._model_api_key() == "override-" + KEY


def test_discovery_presents_the_key():
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            body = b'{"data": [{"id": "qwen3-vl-30b-a3b-fp8"}]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        ids = VllmModelClient._list_models(f"http://127.0.0.1:{server.server_address[1]}", KEY, 5)
    finally:
        server.shutdown()
        server.server_close()
    assert ids == ["qwen3-vl-30b-a3b-fp8"]
    assert seen == [f"Bearer {KEY}"]
