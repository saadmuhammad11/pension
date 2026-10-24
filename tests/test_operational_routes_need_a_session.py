"""The operational endpoints are not readable by the public internet.

/api/gpu was written when the models ran on this box: it reported this machine's own GPU and
memory to the trial console, and it was put on the open list because a utilisation gauge is
not secret. Both halves of that stopped being true.

The models moved to a separate NPU server on 18 October 2026, and on 20 October the route was
widened to read those servers' own /metrics. It now answers, to anyone who asks:

  * the model servers' addresses on the private network (model-host.internal, three ports),
  * which models and versions are being served,
  * KV-cache occupancy, queue depth, and cumulative prompt/generation token counts.

Meanwhile the portal became reachable from the public internet on a forwarded port. So the
estate's internal topology and its workload were readable without signing in.

Nothing calls it -- not the portal, not run.sh, not tools/bench.py -- so it costs nothing to
close. An operator reads it signed in, as they read every other operational figure.

/api/health stays open deliberately: a health check that needs a credential is not a health
check, and it says whether each dependency is up and no more.

    python3 -m unittest tests.test_operational_routes_need_a_session -v
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api import server


class TheOpenList(unittest.TestCase):
    def test_the_gpu_route_is_not_on_it(self) -> None:
        self.assertNotIn("/api/gpu", server._OPEN_V1)

    def test_health_still_is(self) -> None:
        """Monitoring has to reach it, and it discloses nothing but up/down."""
        self.assertIn("/api/health", server._OPEN_V1)

    def test_nothing_was_added_to_it_by_accident(self) -> None:
        """The list is short on purpose. A new entry is a new unauthenticated route and
        should be a deliberate decision, not a side effect."""
        self.assertEqual(set(server._OPEN_V1), {"/api/health", "/api/variants", "/api/v2/"})


class WhatTheRouteDiscloses(unittest.TestCase):
    def test_it_reports_the_model_servers_which_is_why_it_is_closed(self) -> None:
        """If this ever stops reporting the model estate, the reason for closing it is gone
        and the decision should be revisited rather than silently inherited."""
        import inspect
        from api import runs
        src = inspect.getsource(runs.gpu_utilisation)
        self.assertIn("model_metrics", src)
        self.assertIn("models", src)


class TheRouteIsRefusedWithoutASession(unittest.TestCase):
    def setUp(self) -> None:
        try:
            from starlette.testclient import TestClient
        except Exception as exc:                      # pragma: no cover
            self.skipTest(f"no test client: {exc}")
        # /api/health reports on the database, so give it one of its own rather than the
        # deployment's -- the suite is run with PENSION_DATABASE_URL unset for that reason.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        from api import db
        env = mock.patch.dict("os.environ", {"PENSION_DB": str(Path(tmp.name) / "t.sqlite3")})
        env.start(); self.addCleanup(env.stop)
        patched = mock.patch.object(db, "DB_PATH", Path(tmp.name) / "t.sqlite3")
        patched.start(); self.addCleanup(patched.stop)
        db.migrate()
        self.client = TestClient(server.app)

    def test_an_unauthenticated_read_is_refused(self) -> None:
        r = self.client.get("/api/gpu")
        self.assertIn(r.status_code, (401, 403), r.text)

    def test_health_is_still_answered(self) -> None:
        self.assertEqual(self.client.get("/api/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
