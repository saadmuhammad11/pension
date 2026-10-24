"""The production fixes of 5 Oct 2026 (docs/DEPLOYMENT.md §3.0, F1-F9), end to end where they can be.

    python3 -m unittest tests.test_production_hardening -v

Each class is one fix. The API ones run over FastAPI's TestClient on the V2Test fixture (a
temporary database, the pipeline stubbed); production is switched on per test with
PENSION_ENV=production, which is read on every call (api.settings).
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from api import auth, db, settings
from api.desks import DeskNotAuthorised, desk_for_account
from tests import test_api_v2 as _v2

PROD = {"PENSION_ENV": "production"}


class _Fixture(unittest.TestCase):
    """The case-system fixture of tests.test_api_v2 -- its set-up and helpers, not its tests."""
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide


class F1PasswordRules(unittest.TestCase):
    def test_the_trial_password_and_its_cousins_are_refused(self) -> None:
        for weak in ("1234", "12345678", "password", "Pension2026!", "punjab123"):
            self.assertIsNotNone(auth.password_problem(weak, "agriculture"), weak)

    def test_the_username_may_not_be_in_the_password(self) -> None:
        self.assertIn("username", auth.password_problem("agriculture-2026", "agriculture"))

    def test_a_generated_password_passes_and_production_asks_for_ten(self) -> None:
        self.assertIsNone(auth.password_problem("Copper-Harbour-Falcon-Marsh-47", "agriculture"))
        self.assertIsNone(auth.password_problem("Kx7#mQ2v", "admin"))             # 8: enough for the trial
        with mock.patch.dict(os.environ, PROD):
            self.assertIn("10", auth.password_problem("Kx7#mQ2v", "admin"))


class F1ForcedChange(_Fixture):
    def _force(self, username: str) -> None:
        conn = db.connect()
        conn.execute("UPDATE users SET must_change_password = 1 WHERE username = ?", (username,))
        conn.close()

    def test_an_account_that_must_change_may_do_nothing_else_until_it_has(self) -> None:
        from tests.test_api_v2 import tier_username
        self._force(tier_username("AG_SENIOR_AUDITOR", "punjab-police"))
        h = self.sa()
        me = self.client.get("/api/v2/auth/me", headers=h).json()
        self.assertTrue(me["user"]["must_change_password"])
        r = self.client.get("/api/v2/cases", headers=h)
        self.assertEqual(r.status_code, 403)
        self.assertIn("change your password", r.json()["detail"])
        self.assertEqual(self.client.get("/api/runs", headers=h).status_code, 403)   # the old routes too
        bad = self.client.post("/api/v2/auth/change-password", headers=h, json={"current": db.SEED_PASSWORD, "new": "1234"})
        self.assertEqual(bad.status_code, 422)
        ok = self.client.post("/api/v2/auth/change-password", headers=h,
                              json={"current": db.SEED_PASSWORD, "new": "Copper-Harbour-Falcon-47"})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertFalse(ok.json()["user"]["must_change_password"])
        fresh = {"Authorization": f"Bearer {ok.json()['token']}"}
        self.assertEqual(self.client.get("/api/v2/cases", headers=fresh).status_code, 200)
        self.assertEqual(self.client.get("/api/v2/cases", headers=h).status_code, 401)  # the old token ended

    def test_in_production_a_password_the_administrator_sets_must_be_replaced(self) -> None:
        admin = self.login("admin", "ag")
        with mock.patch.dict(os.environ, PROD):
            r = self.client.post("/api/v2/admin/users", headers=admin, json={
                "username": "nadia.rauf", "role": "AG_DAG", "password": "Copper-Harbour-Falcon-47"})
            self.assertEqual(r.status_code, 201, r.text)
            self.assertTrue(r.json()["must_change_password"])
            weak = self.client.post("/api/v2/admin/users", headers=admin, json={
                "username": "hina.saeed", "role": "AG_DAG", "password": "12345678"})
            self.assertEqual(weak.status_code, 422)

    def test_production_seed_ignores_the_shared_password_and_flags_every_account(self) -> None:
        with mock.patch.dict(os.environ, PROD):
            conn = db.connect()
            conn.execute("DELETE FROM users WHERE username = 'agriculture'")
            conn.close()
            db.seed(quiet=True)
            conn = db.connect()
            row = conn.execute("SELECT * FROM users WHERE username = 'agriculture'").fetchone()
            conn.close()
        self.assertEqual(row["must_change_password"], 1)
        self.assertFalse(auth.verify_password(db.SEED_PASSWORD, row["password_hash"]))

    def test_production_start_up_flags_accounts_still_on_1234(self) -> None:
        conn = db.connect()
        conn.execute("UPDATE users SET password_hash = ? WHERE username = 'agriculture'", (auth.hash_password("1234"),))
        flagged = auth.flag_weak_passwords(conn)
        row = conn.execute("SELECT must_change_password FROM users WHERE username = 'agriculture'").fetchone()
        conn.close()
        self.assertEqual(flagged, ["agriculture"])
        self.assertEqual(row[0], 1)

    def test_set_all_passwords_is_refused_in_production(self) -> None:
        with mock.patch.dict(os.environ, PROD), self.assertRaises(PermissionError):
            db.set_all_passwords("1234")


class F2DeskFromTheAccount(_Fixture):
    def test_the_account_role_decides_which_desks_it_may_claim(self) -> None:
        self.assertEqual(desk_for_account("recompute", "ADMIN", None), "SYSTEM_ADMIN")
        self.assertEqual(desk_for_account("confirm_rule", "ADMIN", None), "REFERENCE_ADMIN")
        self.assertEqual(desk_for_account("decide", "AG_REVIEWER", "DAG_PENSION"), "DAG_PENSION")
        with self.assertRaises(DeskNotAuthorised):
            desk_for_account("decide", "ADMIN", "AG_REVIEWER")             # not a desk the admin holds
        with self.assertRaises(DeskNotAuthorised):
            desk_for_account("decide", "DEPT_OFFICER", None)               # a DDO holds no deciding desk

    def test_the_administrator_cannot_decide_as_the_pension_wing_on_the_old_routes(self) -> None:
        admin = self.login("admin", "ag")
        r = self.client.post("/api/runs/abc123/decision", headers={**admin, "X-Desk": "AG_REVIEWER"},
                             json={"action": "FORWARD", "officer": "Someone Else"})
        self.assertEqual(r.status_code, 403)
        # Since G6 the administrator takes no case action at all, so the refusal comes from the
        # role gate before the desk is even asked.
        self.assertIn("read-only for your role", r.json()["detail"])


class F3NoApiDescriptionInProduction(unittest.TestCase):
    def test_docs_are_off_in_production_unless_forced(self) -> None:
        self.assertTrue(settings.api_docs())
        with mock.patch.dict(os.environ, PROD):
            self.assertFalse(settings.api_docs())
        with mock.patch.dict(os.environ, {**PROD, "PENSION_API_DOCS": "1"}):
            self.assertTrue(settings.api_docs())


class F11SigningKeyInProduction(unittest.TestCase):
    """Audit 6 Oct 2026 item 2: production refuses a missing, placeholder or short JWT secret."""
    GOOD = "k" * 20 + "Q7vX2pL9mR4tW8yB3nD6"           # 40 characters, not a placeholder
    BAD = {"missing": None, "placeholder": "CHANGE_ME", "short": "only-twenty-chars-xx"}

    def _env(self, secret):
        env = {k: v for k, v in os.environ.items() if k != "PENSION_JWT_SECRET"}
        env["PENSION_ENV"] = "production"
        if secret is not None:
            env["PENSION_JWT_SECRET"] = secret
        return env

    def test_the_rule(self) -> None:
        for name, secret in self.BAD.items():
            with mock.patch.dict(os.environ, self._env(secret), clear=True):
                self.assertIsNotNone(auth.production_secret_problem(), name)
        with mock.patch.dict(os.environ, self._env(self.GOOD), clear=True):
            self.assertIsNone(auth.production_secret_problem())

    def test_no_token_is_signed_with_a_refused_key_in_production(self) -> None:
        with mock.patch.dict(os.environ, self._env("CHANGE_ME"), clear=True):
            with self.assertRaises(auth.InsecureSecret):
                auth._secret()
        with mock.patch.dict(os.environ, {**self._env(self.GOOD)}, clear=True):
            self.assertEqual(auth._secret(), self.GOOD)
        # The trial keeps working on its short key.
        with mock.patch.dict(os.environ, {"PENSION_ENV": "", "PENSION_JWT_SECRET": "CHANGE_ME"}):
            self.assertEqual(auth._secret(), "CHANGE_ME")

    def test_the_server_process_refuses_to_start(self) -> None:
        import subprocess
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for name, secret in self.BAD.items():
            proc = subprocess.run([sys.executable, "-m", "api.server", "0"], cwd=root, env=self._env(secret),
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 1, f"{name}: {proc.stderr[-500:]}")
            self.assertIn("refusing to start", proc.stderr, name)

    def test_a_start_up_that_skips_the_entry_point_is_refused_too(self) -> None:
        import tempfile
        from pathlib import Path
        from fastapi.testclient import TestClient
        from api import case_runs
        from api.server import app
        # A scratch database, so a regression here could never migrate the live one.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.dict(os.environ, self._env("CHANGE_ME"), clear=True), \
                mock.patch.object(db, "DB_PATH", Path(tmp.name) / "portal.sqlite3"), \
                mock.patch.object(case_runs, "start_reconciler", lambda *a, **k: None):
            with self.assertRaises(auth.InsecureSecret):
                with TestClient(app):
                    pass


class F4ModelAddressesFromTheEnvironment(unittest.TestCase):
    def test_each_endpoint_reads_its_variable(self) -> None:
        import importlib

        import extraction.client
        import extraction.ocr
        import rag.store
        env = {"PENSION_VISION_URL": "http://gpu:1/v", "PENSION_OCR_URL": "http://gpu:2/o",
               "PENSION_EMBED_URL": "http://gpu:3/e", "PENSION_RERANK_URL": "http://gpu:4/r"}
        try:
            with mock.patch.dict(os.environ, env):
                for m in (extraction.client, extraction.ocr, rag.store):
                    importlib.reload(m)
                self.assertEqual(extraction.client.DEFAULT_ENDPOINT, "http://gpu:1/v")
                self.assertEqual(extraction.ocr.OCR_ENDPOINT, "http://gpu:2/o")
                self.assertEqual(rag.store.EMBED_ENDPOINT, "http://gpu:3/e")
                self.assertEqual(rag.store.RERANK_ENDPOINT, "http://gpu:4/r")
        finally:
            for m in (extraction.client, extraction.ocr, rag.store):
                importlib.reload(m)


class F5AndF6Logins(_Fixture):
    def _fail(self, username: str, ip: str):
        return self.client.post("/api/v2/auth/login", json={"username": username, "password": "wrong-password"},
                                headers={"X-Portal": "ag", "X-Forwarded-For": ip})

    def test_one_address_cannot_spray_a_password_across_every_account(self) -> None:
        from api.departments import DEPARTMENTS
        names = [d.slug for d in DEPARTMENTS]
        for i in range(auth.ADDRESS_MAX_FAILURES):
            self.assertEqual(self._fail(names[i % len(names)], "203.0.113.9").status_code, 401)
        self.assertEqual(self._fail(names[0], "203.0.113.9").status_code, 429)
        self.assertEqual(self._fail(names[0], "203.0.113.10").status_code, 401)      # another address is not locked

    def test_sign_ins_and_refusals_are_on_the_audit_trail(self) -> None:
        self._fail("agriculture", "203.0.113.1")
        self.login("admin", "ag")
        conn = db.connect()
        rows = conn.execute("SELECT action, entity_id, ip FROM audit_log WHERE action LIKE 'LOGIN%' ORDER BY at").fetchall()
        conn.close()
        actions = {(r["action"], r["entity_id"] if r["action"] != "LOGIN" else "") for r in rows}
        self.assertIn(("LOGIN_FAILED", "agriculture"), actions)
        self.assertIn(("LOGIN", ""), actions)
        self.assertIn("203.0.113.1", {r["ip"] for r in rows})


class F7SheetNotServedInProduction(_Fixture):
    def test_the_credentials_route_is_closed_in_production(self) -> None:
        admin = self.login("admin", "ag")
        with mock.patch.dict(os.environ, PROD):
            self.assertEqual(self.client.get("/api/v2/admin/credentials", headers=admin).status_code, 404)

    def test_forget_credentials_removes_the_sheet(self) -> None:
        db.CREDENTIALS_CSV.write_text("u,p\n")
        db.forget_credentials()
        self.assertFalse(db.CREDENTIALS_CSV.exists())


class F10GpfFrameSignIn(_Fixture):
    def test_only_the_ag_side_gets_a_frame_cookie_and_it_opens_nothing_else(self) -> None:
        reviewer = self.sa()
        r = self.client.post("/api/v2/auth/gpf-session", headers=reviewer)
        self.assertEqual(r.status_code, 200, r.text)
        cookie = r.cookies.get("pension_gpf")
        self.assertTrue(cookie)
        set_cookie = r.headers["set-cookie"].lower()
        for part in ("path=/gpf", "httponly", "samesite=strict"):
            self.assertIn(part, set_cookie)
        check = self.client.get("/api/v2/auth/gpf-check", headers={"X-GPF-Session": cookie})
        self.assertEqual(check.status_code, 200)
        from api.gpf_bridge import OFFICER_FOR_ROLE
        self.assertEqual(check.json()["officer"], OFFICER_FOR_ROLE["AG_SENIOR_AUDITOR"])
        # The frame's token is not a session: it opens no other route.
        self.assertEqual(self.client.get("/api/v2/cases", headers={"Authorization": f"Bearer {cookie}"}).status_code, 401)
        self.assertEqual(self.client.get("/api/runs", headers={"Authorization": f"Bearer {cookie}"}).status_code, 401)
        # And a session token is not a frame token.
        session = reviewer["Authorization"].split()[1]
        self.assertEqual(self.client.get("/api/v2/auth/gpf-check", headers={"X-GPF-Session": session}).status_code, 401)
        ddo = self.login("agriculture", "agriculture")
        self.assertEqual(self.client.post("/api/v2/auth/gpf-session", headers=ddo).status_code, 403)


class F8UploadChecks(unittest.TestCase):
    def test_lookalike_signatures_and_binary_text_are_refused(self) -> None:
        from api.v2 import _document_problem
        self.assertIsNone(_document_problem("scan.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 "))
        self.assertIsNotNone(_document_problem("song.webp", b"RIFF\x00\x00\x00\x00WAVEfmt "))
        self.assertIsNone(_document_problem("scan.bmp", b"BM\x00\x00"))
        self.assertIsNotNone(_document_problem("notes.pdf", b"BM\x00\x00"))
        self.assertIsNone(_document_problem("notes.txt", "Pension case — notes".encode()))
        self.assertIsNotNone(_document_problem("notes.txt", b"\x7fELF\x02\x01\x01\x00\x00"))

    def test_a_pdf_past_the_page_limit_is_refused(self) -> None:
        from api import v2
        with mock.patch.object(v2, "pdf_page_count", return_value=9000):
            self.assertIn("pages", v2._document_problem("big.pdf", b"%PDF-1.4\n"))
        with mock.patch.object(v2, "pdf_page_count", return_value=None):          # pdfinfo could not tell
            self.assertIsNone(v2._document_problem("odd.pdf", b"%PDF-1.4\n"))


class F7AndF9PortalServer(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        from starlette.testclient import TestClient

        from api import portal_server
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-portals-prod-")
        dist = Path(self._tmp.name)
        (dist / "index.html").write_text("<!doctype html><html><head></head><body></body></html>")
        self.portal_server = portal_server
        self.app = portal_server.PortalApp(dist=dist, api="http://127.0.0.1:1", trust_port_header=False)
        self.client = TestClient(self.app.app)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_production_hides_the_sheet_and_the_port_list(self) -> None:
        with mock.patch.dict(os.environ, PROD):
            for path in ("/start.html", "/__portals"):
                self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_gpf_needs_the_frame_sign_in_in_the_trial_and_in_production(self) -> None:
        for env in ({"PENSION_ENV": ""}, PROD):
            with mock.patch.dict(os.environ, env):
                os.environ.pop("PENSION_GPF_PROXY", None)
                for path in ("/gpf/", "/gpf/api/cases", "/gpf"):
                    r = self.client.get(path, follow_redirects=False)
                    self.assertEqual(r.status_code, 401, (env, path))
                # A cookie the API does not confirm is refused as well (the API here is unreachable).
                self.client.cookies.set("pension_gpf", "forged")
                self.assertEqual(self.client.get("/gpf/api/cases").status_code, 401)
                self.client.cookies.clear()

    def test_a_confirmed_frame_reaches_the_module_as_its_own_officer_only(self) -> None:
        async def yes(_request):
            return "ao"                                              # the officer the API confirmed
        seen = {}

        class FakeUpstream:
            status = 200
            headers = {"content-type": "application/json"}
            async def read(self):
                return b"[]"
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False

        def fake_request(method, url, headers=None, **kw):
            seen.update(url=url, headers=headers)
            return FakeUpstream()
        async def may_read(_request, _sub):
            return None                                              # the API said yes (its own tests cover the no)
        with mock.patch.object(self.app, "gpf_signed_in", yes), mock.patch.object(self.app, "gpf_read_refused", may_read):
            with self.client as c:                                   # lifespan: the client session exists
                with mock.patch.object(self.app.session, "request", fake_request):
                    c.cookies.set("pension_gpf", "t")
                    # The browser claims to be the DAG; the portal says who it is.
                    r = c.get("/gpf/api/cases", headers={"Authorization": "Bearer x", "X-GPF-Officer": "dag"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(seen["url"].endswith("/api/cases"))
        sent = {k.lower(): v for k, v in seen["headers"].items()}
        self.assertNotIn("cookie", sent)
        self.assertNotIn("authorization", sent)
        self.assertEqual(sent["x-gpf-officer"], "ao")

    def test_gp_fund_listens_on_loopback_by_default(self) -> None:
        from pathlib import Path
        script = (Path(__file__).resolve().parents[1] / "GP" / "backend" / "run.sh").read_text()
        self.assertIn('GPF_BIND="${GPF_BIND:-127.0.0.1}"', script)
        self.assertIn('--host "$GPF_BIND"', script)

    def test_production_listens_on_loopback_unless_told_otherwise(self) -> None:
        self.assertEqual(self.portal_server.bind_host(), os.environ.get("PENSION_PORTAL_BIND") or "0.0.0.0")
        with mock.patch.dict(os.environ, PROD):
            os.environ.pop("PENSION_PORTAL_BIND", None)
            self.assertEqual(self.portal_server.bind_host(), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
