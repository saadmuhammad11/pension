"""/api/health checks the database, the disk, the models and GP Fund (audit 6 Oct 2026, later report item 11).

    python3 -m unittest tests.test_health_checks_something -v

The route reported the run count only, so monitoring showed green through a real outage. It now
fails (503) only when the database cannot be read; a short disk, the model servers and GP Fund
are reported as degraded, probed in the background at most every 30 seconds (review C3, 9 Oct 2026).
"""
from __future__ import annotations

import unittest
from unittest import mock

from api import health
from tests import test_api_v2 as _v2


class Health(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown

    def test_a_healthy_api_answers_200_with_every_part_named(self) -> None:
        health.forget()
        with mock.patch.object(health, "probe", lambda url, timeout=2.0: True), \
                mock.patch.object(health.gpf_bridge if hasattr(health, "gpf_bridge") else __import__("api.gpf_bridge", fromlist=["health"]),
                                  "health", lambda: {"ok": True}):
            r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["runs"], 0)
        self.assertTrue(body["database"]["ok"])
        self.assertTrue(body["disk"]["ok"])
        self.assertIsInstance(body["disk"]["free_gb"], float)
        self.assertEqual(body["models"], {"vision": True, "ocr": True, "embedding": True})
        self.assertTrue(body["gpf"]["ok"])
        self.assertEqual(body["degraded"], [])

    def test_models_down_is_degraded_not_failed(self) -> None:
        health.forget()
        from api import gpf_bridge
        with mock.patch.object(health, "probe", lambda url, timeout=2.0: False), \
                mock.patch.object(gpf_bridge, "health", lambda: None):
            r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(sorted(r.json()["degraded"]), ["embedding", "gpf", "ocr", "vision"])

    def test_probes_are_remembered_so_a_poller_is_cheap(self) -> None:
        health.forget()
        from api import gpf_bridge
        calls = []
        with mock.patch.object(health, "probe", lambda url, timeout=2.0: calls.append(url) or True), \
                mock.patch.object(gpf_bridge, "health", lambda: {"ok": True}):
            for _ in range(5):
                self.client.get("/api/health")
        self.assertEqual(len(calls), 3)                              # one probe per model, then remembered

    def test_a_database_that_cannot_be_read_fails_the_check(self) -> None:
        health.forget()
        from api import gpf_bridge
        with mock.patch.object(health, "_database", lambda: (False, "OperationalError: unable to open database file")), \
                mock.patch.object(health, "probe", lambda url, timeout=2.0: True), \
                mock.patch.object(gpf_bridge, "health", lambda: {"ok": True}):
            r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 503, r.text)
        self.assertFalse(r.json()["ok"])
        self.assertIn("unable to open", r.json()["database"]["problem"])

    def test_a_short_disk_is_degraded_not_failed(self) -> None:
        # A 503 here showed every user the portal's outage screen while the API still served
        # cases (review C3, 9 Oct 2026); uploads are refused on their own with the reason (R8).
        health.forget()
        from api import gpf_bridge
        with mock.patch.object(health, "_disk", lambda: (False, {"free_gb": 1.2, "problem": "the server has 1.2 GB free"})), \
                mock.patch.object(health, "probe", lambda url, timeout=2.0: True), \
                mock.patch.object(gpf_bridge, "health", lambda: {"ok": True}):
            r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])
        self.assertFalse(r.json()["disk"]["ok"])
        self.assertIn("disk", r.json()["degraded"])
        self.assertIn("1.2 GB free", r.json()["disk"]["problem"])

    def test_a_stale_probe_is_answered_from_memory_and_refreshed_behind(self) -> None:
        health.forget()
        from api import gpf_bridge
        slow = []

        def probe(url, timeout=2.0):
            slow.append(url); return True
        with mock.patch.object(health, "probe", probe), mock.patch.object(gpf_bridge, "health", lambda: {"ok": True}):
            self.client.get("/api/health")                              # first answers probe synchronously
            with mock.patch.object(health, "PROBE_TTL_S", 0.0):          # everything is stale at once
                import time
                t0 = time.monotonic()
                r = self.client.get("/api/health")                      # answered from memory, refresh in the background
                self.assertLess(time.monotonic() - t0, 1.0)
                self.assertEqual(r.json()["models"], {"vision": True, "ocr": True, "embedding": True})
            for t in [t for t in __import__("threading").enumerate() if t.name.startswith("health-")]:
                t.join(2)
        self.assertGreaterEqual(len(slow), 3)

    def test_in_production_the_database_error_text_stays_in_the_log(self) -> None:
        health.forget()
        from api import gpf_bridge
        with mock.patch.dict("os.environ", {"PENSION_ENV": "production"}), \
                mock.patch.object(health, "probe", lambda url, timeout=2.0: True), \
                mock.patch.object(gpf_bridge, "health", lambda: {"ok": True}), \
                mock.patch("api.db.connect", side_effect=RuntimeError("password authentication failed for user pension")):
            r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 503, r.text)
        self.assertEqual(r.json()["database"]["problem"], "the database is unavailable")
        self.assertNotIn("password", r.text)

    def test_the_health_url_sits_beside_the_endpoint(self) -> None:
        self.assertEqual(health.health_url("http://127.0.0.1:8011/v1/chat/completions"), "http://127.0.0.1:8011/health")
        self.assertEqual(health.health_url("https://models.example:8443/v1/embeddings"), "https://models.example:8443/health")


if __name__ == "__main__":
    unittest.main()
