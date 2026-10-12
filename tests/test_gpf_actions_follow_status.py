"""GP Fund actions only while the case is under the AG's review (audit 6 Oct 2026, High finding).

    python3 -m unittest tests.test_gpf_actions_follow_status -v

The portal moves a GP Fund case on the module's position only from UNDER_REVIEW. Before this,
an AG could "pass for payment", waive or cure in the module on a case already rejected or
returned -- from the portal's own routes or from the module's screen in the frame -- and the
two systems then disagreed about the same claim. Both paths now ask the case's status first.
"""
from __future__ import annotations

import unittest
from unittest import mock

from api import case_runs, db, gpf_bridge
from tests import test_api_v2 as _v2

GPF_ID = "refundable-scan-0000test"


class _Fixture(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide
    create = _v2.V2Test.create

    def _gpf_case(self, status: str) -> str:
        made = self.create(self.login("punjab-police", "punjab-police"), case_type=None, product="GPF",
                           gpf_kind="refundable")
        case_id = made["case"]["id"]
        conn = db.connect()
        conn.execute("UPDATE cases SET product = 'GPF', gpf_case_id = ?, status = ? WHERE id = ?",
                     (GPF_ID, status, case_id))
        conn.commit()
        conn.close()
        return case_id

    def _set_status(self, case_id: str, status: str) -> None:
        conn = db.connect()
        conn.execute("UPDATE cases SET status = ? WHERE id = ?", (status, case_id))
        conn.commit()
        conn.close()


class PortalRoutes(_Fixture):
    def test_actions_are_refused_unless_under_review(self) -> None:
        ag = self.sa()
        case_id = self._gpf_case("REJECTED")
        acted = []
        with mock.patch.object(gpf_bridge, "act", lambda *a, **k: acted.append(a) or {"ok": True}), \
                mock.patch.object(gpf_bridge, "cure", lambda *a, **k: acted.append(a) or {"ok": True}), \
                mock.patch.object(case_runs, "sync_gpf_case", lambda *a, **k: None):
            for status in ("REJECTED", "RETURNED", "APPROVED", "AI_CHECKING", "FORWARDED"):
                self._set_status(case_id, status)
                r = self.client.post(f"/api/v2/cases/{case_id}/gpf/dispose", headers=ag,
                                     json={"disposal": "pay"})
                self.assertEqual(r.status_code, 409, (status, r.text))
                self.assertIn(status, r.json()["detail"])
                r = self.client.post(f"/api/v2/cases/{case_id}/gpf-cure", headers=ag,
                                     data={"resultId": "ADV-LIMIT", "values": "{}"})
                self.assertEqual(r.status_code, 409, (status, r.text))
            self.assertEqual(acted, [], "nothing reached the module")
            self._set_status(case_id, "UNDER_REVIEW")
            r = self.client.post(f"/api/v2/cases/{case_id}/gpf/dispose", headers=ag, json={"disposal": "pay"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(len(acted), 1)


class FrameCheck(_Fixture):
    def _frame_token(self) -> str:
        r = self.client.post("/api/v2/auth/gpf-session", headers=self.sa())
        self.assertEqual(r.status_code, 200, r.text)
        return r.cookies.get("pension_gpf")

    def _check(self, token: str | None, path: str, method: str = "POST"):
        headers = {"X-GPF-Path": path, "X-GPF-Method": method}
        if token:
            headers["X-GPF-Session"] = token
        return self.client.get("/api/v2/auth/gpf-act-check", headers=headers)

    def test_the_frame_opens_the_portal_s_own_cases_only_and_within_the_wing_and_tier(self) -> None:
        """Audit of 12 Oct 2026: the frame cookie opened the whole module. Now the register and
        the intake are the portal's, the signing register is read-only through the frame, and a
        case is opened on the case system's own visibility and holder rules."""
        token = self._frame_token()                                   # the Senior Auditor of Pension-I
        self.assertEqual(self._check(token, "/api/cases", "GET").status_code, 403)            # the register
        self.assertEqual(self._check(token, "/api/cases", "POST").status_code, 403)           # filing
        self.assertEqual(self._check(token, "/api/cases/from-scans", "POST").status_code, 403)
        self.assertEqual(self._check(token, "/api/cases/from-scans/start", "POST").status_code, 403)
        self.assertEqual(self._check(token, "/api/doa/finalize", "POST").status_code, 403)    # the signing register
        self.assertEqual(self._check(token, "/api/doa/specimens", "POST").status_code, 403)
        self.assertEqual(self._check(token, "/api/doa", "GET").status_code, 200)
        self.assertEqual(self._check(token, "/api/health", "GET").status_code, 200)
        self.assertEqual(self._check(token, "/api/reading/jobs/job-1", "GET").status_code, 200)
        self.assertEqual(self._check(token, "/api/anything-else", "POST").status_code, 403)
        # The wing's own case: read and, while the Senior Auditor holds it, acted on.
        case_id = self._gpf_case("UNDER_REVIEW")
        conn = db.connect()                                              # an examination that completed
        try:
            row = conn.execute("SELECT submission_no, created_by FROM cases WHERE id = ?", (case_id,)).fetchone()
            conn.execute("INSERT INTO case_runs (id, case_id, run_id, submission_no, started_by, started_at, state) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", (db.new_id(), case_id, "gpf-job-done", row["submission_no"],
                                                           row["created_by"], "2026-10-12T10:00:00", "done"))
            conn.execute("UPDATE cases SET current_run_id = 'gpf-job-done' WHERE id = ?", (case_id,))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self._check(token, f"/api/cases/{GPF_ID}", "GET").status_code, 200)
        self.assertEqual(self._check(token, f"/api/cases/{GPF_ID}/pages/3", "GET").status_code, 200)
        self.assertEqual(self._check(token, f"/api/cases/{GPF_ID}/dispose", "POST").status_code, 200)
        # Forwarded to the Assistant AO: the Senior Auditor still reads it, but no longer acts.
        r = self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=self.sa(), json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._check(token, f"/api/cases/{GPF_ID}", "GET").status_code, 200)
        r = self._check(token, f"/api/cases/{GPF_ID}/dispose", "POST")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("Assistant", r.json()["detail"])
        # Another wing's officer: neither reads nor acts.
        other = self.client.post("/api/v2/auth/gpf-session", headers=self.sa("school-education")).cookies.get("pension_gpf")
        self.assertEqual(self._check(other, f"/api/cases/{GPF_ID}", "GET").status_code, 403)
        self.assertEqual(self._check(other, f"/api/cases/{GPF_ID}/dispose", "POST").status_code, 403)
        # The AG's desk reads and acts everywhere.
        desk = self.client.post("/api/v2/auth/gpf-session", headers=self.login("ag.reviewer", "ag")).cookies.get("pension_gpf")
        self.assertEqual(self._check(desk, f"/api/cases/{GPF_ID}", "GET").status_code, 200)
        self.assertEqual(self._check(desk, f"/api/cases/{GPF_ID}/dispose", "POST").status_code, 200)

    def test_the_proxy_question_follows_the_case_status(self) -> None:
        token = self._frame_token()
        case_id = self._gpf_case("RETURNED")
        r = self._check(token, f"/api/cases/{GPF_ID}/dispose")
        self.assertEqual(r.status_code, 409, r.text)
        self._set_status(case_id, "UNDER_REVIEW")
        self.assertEqual(self._check(token, f"/api/cases/{GPF_ID}/dispose").status_code, 200)
        # A module case the portal never filed (a template) is not opened through the frame at
        # all (audit of 12 Oct 2026): the frame is for the portal's own cases.
        self.assertEqual(self._check(token, "/api/cases/refundable-template/dispose").status_code, 403)
        # And the question needs the frame sign-in like every other.
        self.assertEqual(self._check(None, f"/api/cases/{GPF_ID}/dispose").status_code, 401)


class ProxyAsksBeforeWrites(unittest.TestCase):
    """The portal server asks the API before every change it passes from the frame."""
    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        from starlette.testclient import TestClient

        from api import portal_server
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-gpf-act-")
        (Path(self._tmp.name) / "index.html").write_text("<!doctype html><html></html>")
        self.app = portal_server.PortalApp(dist=Path(self._tmp.name), api="http://127.0.0.1:1",
                                           trust_port_header=False)
        self.client = TestClient(self.app.app)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_a_refused_change_never_reaches_the_module(self) -> None:
        async def signed_in(_request):
            return "ao"
        asked, forwarded = [], []

        class Reply:
            def __init__(self, status, body):
                self.status, self._body = status, body
                self.headers = {"content-type": "application/json"}
            async def json(self, content_type=None):
                return self._body
            async def read(self):
                return b"{}"
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False

        def fake_get(url, headers=None, **kw):
            asked.append(headers.get("X-GPF-Path"))
            if headers.get("X-GPF-Method") == "GET":
                return Reply(200, {"ok": True})                      # the officer may see the case
            return Reply(409, {"detail": "case PC-2026-000001 is REJECTED"})

        def fake_request(method, url, **kw):
            forwarded.append((method, url))
            return Reply(200, {})

        with mock.patch.object(self.app, "gpf_signed_in", signed_in):
            with self.client as c:
                with mock.patch.object(self.app.session, "get", fake_get), \
                        mock.patch.object(self.app.session, "request", fake_request):
                    c.cookies.set("pension_gpf", "t")
                    r = c.post(f"/gpf/api/cases/{GPF_ID}/dispose", json={"disposal": "pay"})
                    self.assertEqual(r.status_code, 409)
                    self.assertIn("REJECTED", r.json()["detail"])
                    self.assertEqual(forwarded, [])
                    self.assertEqual(asked, [f"/api/cases/{GPF_ID}/dispose"])
                    # A read of one examination is asked about too (may this officer see the
                    # case?), and passed on when the answer is yes; the yes is remembered, so the
                    # page's many scans cost one question.
                    r = c.get(f"/gpf/api/cases/{GPF_ID}")
                    self.assertEqual(r.status_code, 200)
                    self.assertEqual(len(asked), 2)
                    self.assertEqual(len(forwarded), 1)
                    c.get(f"/gpf/api/cases/{GPF_ID}/pages/1")
                    self.assertEqual(len(asked), 2)
                    self.assertEqual(len(forwarded), 2)


if __name__ == "__main__":
    unittest.main()
