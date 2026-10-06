"""Model servers: loopback only, a key on every request, run from this release (audit 6 Oct 2026, item 7).

    python3 -m unittest tests.test_model_endpoints -v

Found live on 6 Oct 2026: the vision (:8011), OCR (:8012) and embedding (:8093) servers listened
on 0.0.0.0 with no key, and the vision unit ran its launcher and warmup from another developer's
checkout. These tests read the unit files and launchers as shipped, run the launchers' key
check, and send each pipeline client at a local server that refuses a request without the key.
Nothing here starts a model or touches the running services.
"""
from __future__ import annotations

import http.server
import json
import os
import re
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
UNITS = {"vllm-qwen3-vl.service": 8011, "paddleocr-vl.service": 8012, "qwen3-embedding.service": 8093}
LAUNCHERS = ("serve-qwen3-vl.sh", "serve-paddleocr-vl.sh")
GOOD_KEY = "m" * 16 + "Kq8sV3xN1bT6wY2zR9pL4cH7"   # 40 characters, not a placeholder


class UnitsAndLaunchers(unittest.TestCase):
    def test_no_unit_or_script_runs_from_a_developer_folder(self) -> None:
        for name in (*UNITS, *LAUNCHERS, "warmup-vision.sh"):
            # What runs, not the history in the comments.
            text = "\n".join(l for l in (INFRA / name).read_text().splitlines() if not l.lstrip().startswith("#"))
            self.assertNotIn("Pension-AG", text, name)
            self.assertNotIn("/home/tmc/serve-", text, name)

    def test_units_load_the_key_and_run_released_files(self) -> None:
        for name in UNITS:
            text = (INFRA / name).read_text()
            self.assertIn("EnvironmentFile=/etc/pension/models.env", text, name)
            for line in re.findall(r"^Exec\w+=(?:-)?(/opt/pension/\S+)", text, re.M):
                self.assertTrue((INFRA / Path(line).name).is_file(), f"{name}: {line} is not in infra/")

    def test_everything_binds_loopback(self) -> None:
        emb = (INFRA / "qwen3-embedding.service").read_text()
        self.assertIn("--host 127.0.0.1", emb)
        self.assertNotIn("0.0.0.0", emb)
        for name in LAUNCHERS:
            self.assertIn('HOST="${HOST:-127.0.0.1}"', (INFRA / name).read_text(), name)

    def _launch(self, name: str, key: str | None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "VLLM_API_KEY"}
        if key is not None:
            env["VLLM_API_KEY"] = key
        # A model path that does not exist: if the key check passed, the launcher would stop at
        # its next check ("model path not found") instead -- either way no model is loaded.
        env["MODEL_PATH"] = "/nonexistent/model"
        return subprocess.run(["bash", str(INFRA / name)], env=env, capture_output=True, text=True, timeout=60)

    def test_launchers_refuse_to_start_without_a_proper_key(self) -> None:
        for name in LAUNCHERS:
            for key in (None, "", "CHANGE_ME", "short-key"):
                proc = self._launch(name, key)
                self.assertEqual(proc.returncode, 1, f"{name} key={key!r}: {proc.stderr[-300:]}")
                self.assertIn("VLLM_API_KEY", proc.stderr, f"{name} key={key!r}")
            # With a good key the key check passes and the launcher stops at the next check.
            proc = self._launch(name, GOOD_KEY)
            self.assertNotIn("VLLM_API_KEY", proc.stderr, name)
            self.assertIn("model path not found", proc.stderr, name)

    def test_the_embedding_unit_refuses_to_start_without_a_proper_key(self) -> None:
        text = (INFRA / "qwen3-embedding.service").read_text()
        [line] = [l for l in text.splitlines() if l.startswith("ExecStartPre=") and "VLLM_API_KEY" in l]
        # As systemd runs it: "$$" is its escape for a literal "$".
        command = line.split("=", 1)[1].replace("$$", "$")
        self.assertNotIn("$VLLM", line.replace("$$", ""), "an unescaped $ would be expanded by systemd")
        for key, expected in ((None, 1), ("CHANGE_ME" * 5, 1), ("short", 1), (GOOD_KEY, 0)):
            env = {k: v for k, v in os.environ.items() if k != "VLLM_API_KEY"}
            if key is not None:
                env["VLLM_API_KEY"] = key
            proc = subprocess.run(["/bin/bash", "-c", command.split(" -c ", 1)[1].strip("'")],
                                  env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, expected, f"key={key!r}: {proc.stderr}")


class _KeyedServer:
    """Answers 200 only to Authorization: Bearer <key>, like vLLM with VLLM_API_KEY set."""
    def __init__(self, key: str) -> None:
        seen = self.seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                auth = self.headers.get("Authorization")
                seen.append((self.path, auth))
                ok = auth == f"Bearer {key}"
                body = (json.dumps({"choices": [{"message": {"content": "UPRIGHT"}, "finish_reason": "stop"}],
                                    "data": [{"embedding": [0.0, 1.0]}], "usage": {}})
                        if ok else json.dumps({"error": "Unauthorized"})).encode()
                self.send_response(200 if ok else 401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class ClientsSendTheKey(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _KeyedServer(GOOD_KEY)
        self.addCleanup(self.server.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        from PIL import Image
        self.page = Path(tmp.name) / "page.png"
        Image.new("RGB", (60, 80), "white").save(self.page)

    def _call_every_client(self) -> None:
        from extraction import client, ocr, upright
        from rag import store
        base = self.server.base
        calls = {
            "vision": lambda: client.extract_page(self.page, endpoint=f"{base}/vision", _retry_on_suspect=False),
            "ocr": lambda: ocr.ocr_page(self.page, 1, endpoint=f"{base}/ocr"),
            "upright": lambda: upright.vision_judge(endpoint=f"{base}/upright")(self.page),
            "embedding": lambda: store.embed(["basic pay"], endpoint=f"{base}/embed"),
        }
        for name, call in calls.items():
            try:
                call()
            except Exception:                                    # noqa: BLE001 - only the headers matter
                pass

    def test_every_pipeline_client_presents_the_key(self) -> None:
        with mock.patch.dict(os.environ, {"PENSION_MODEL_API_KEY": GOOD_KEY}):
            self._call_every_client()
        paths = {path for path, _ in self.server.seen}
        self.assertEqual(paths, {"/vision", "/ocr", "/upright", "/embed"})
        self.assertEqual({auth for _, auth in self.server.seen}, {f"Bearer {GOOD_KEY}"})

    def test_without_the_key_the_server_refuses_them(self) -> None:
        with mock.patch.dict(os.environ, {"PENSION_MODEL_API_KEY": ""}):
            self._call_every_client()
        self.assertTrue(self.server.seen)
        self.assertEqual({auth for _, auth in self.server.seen}, {None})


if __name__ == "__main__":
    unittest.main()
