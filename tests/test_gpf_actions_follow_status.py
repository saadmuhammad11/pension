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
        ag = self.login("syed.haider", "ag")
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
        r = self.client.post("/api/v2/auth/gpf-session", headers=self.login("syed.haider", "ag"))
        self.assertEqual(r.status_code, 200, r.text)
        return r.cookies.get("pension_gpf")

    def _check(self, token: str | None, path: str):
        headers = {"X-GPF-Path": path}
        if token:
            headers["X-GPF-Session"] = token
        return self.client.get("/api/v2/auth/gpf-act-check", headers=headers)

    def test_the_proxy_question_follows_the_case_status(self) -> None:
        token = self._frame_token()
        case_id = self._gpf_case("RETURNED")
        r = self._check(token, f"/api/cases/{GPF_ID}/dispose")
        self.assertEqual(r.status_code, 409, r.text)
        self._set_status(case_id, "UNDER_REVIEW")
        self.assertEqual(self._check(token, f"/api/cases/{GPF_ID}/dispose").status_code, 200)
        # A module case the portal never filed (a template) is not the portal's to judge.
        self.assertEqual(self._check(token, "/api/cases/refundable-template/dispose").status_code, 200)
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
                    # Reading is not acting: no question asked, passed straight on.
                    r = c.get(f"/gpf/api/cases/{GPF_ID}")
                    self.assertEqual(r.status_code, 200)
                    self.assertEqual(len(asked), 1)
                    self.assertEqual(len(forwarded), 1)


if __name__ == "__main__":
    unittest.main()
