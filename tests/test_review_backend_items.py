"""The backend items of the 7 Oct review, fixed on 9 Oct 2026: idempotent uploads (F8), media
tokens (F10), the password rule in /auth/me (F14), the old register read-only in production
(N23), a reason for every admin reset and the mark on the next sign-in (N25), no plaintext
unknown username in the audit log (N27), an override bookkept by where it lands (N28), the
engine's reading hidden from a DDO (N29), and the officer's name header surviving non-ASCII (N30).

    /home/tmc/vllm_env/bin/python3 -m unittest tests.test_review_backend_items -v
"""
from __future__ import annotations

import io
import os
import unittest
import uuid
from unittest import mock

from api import db, gpf_bridge, settings
from tests import test_api_v2 as _v2


class Backend(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    # -- F8 --------------------------------------------------------------------------------------
    def test_a_repeated_filing_with_one_idempotency_key_creates_one_case(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        key = str(uuid.uuid4())
        first = self.create({**police, "Idempotency-Key": key})
        again = self.client.post("/api/v2/cases", headers={**police, "Idempotency-Key": key},
                                 data={"case_type": "WIDOW"},
                                 files=[("files", ("case.pdf", io.BytesIO(_v2.PDF), "application/pdf"))])
        self.assertEqual(again.status_code, 201, again.text)
        self.assertEqual(again.headers.get("Idempotent-Replayed"), "true")
        self.assertEqual(again.json()["case"]["id"], first["case"]["id"])
        conn = db.connect()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0], 1)
        finally:
            conn.close()
        # Another officer's identical key is their own.
        edu = self.login("school-education", "school-education")
        other = self.create({**edu, "Idempotency-Key": key})
        self.assertNotEqual(other["case"]["id"], first["case"]["id"])

    def test_repeated_document_uploads_with_one_key_add_the_papers_once(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        self.verify(reviewer, case_id)
        self.client.post(f"/api/v2/cases/{case_id}/return", headers=reviewer, json={"remark": "FRC missing; attach it."})
        key = str(uuid.uuid4())
        for _ in range(2):
            r = self.client.post(f"/api/v2/cases/{case_id}/documents", headers={**police, "Idempotency-Key": key},
                                 files=[("files", ("frc.pdf", io.BytesIO(_v2.PDF2), "application/pdf"))])
            self.assertEqual(r.status_code, 201, r.text)
        docs = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()["documents"]
        self.assertEqual(len([d for d in docs if d["filename"] == "frc.pdf"]), 1)

    # -- F10 -------------------------------------------------------------------------------------
    def test_a_media_token_opens_images_only(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer = self.sa()
        run_id = self.verify(reviewer, case_id)["run_id"]
        r = self.client.get("/api/v2/auth/media-token", headers=reviewer)
        self.assertEqual(r.status_code, 200, r.text)
        token, ttl = r.json()["token"], r.json()["expires_in"]
        self.assertEqual(ttl, 900)
        # Refused on a JSON route, on a write, and in the Authorization header of either.
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}?token={token}").status_code, 401)
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers={"Authorization": f"Bearer {token}"}).status_code, 401)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/return?token={token}", json={"remark": "x" * 20}).status_code, 401)
        # Accepted where an <img> or a download link needs it (the fixture writes no page image: 404
        # is past the token check; 401 would be the refusal).
        r = self.client.get(f"/api/v2/cases/{case_id}/runs/{run_id}/pages/1?token={token}")
        self.assertEqual(r.status_code, 404, r.text)
        docs = self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()["documents"]
        r = self.client.get(f"/api/v2/cases/{case_id}/documents/{docs[0]['id']}?token={token}")
        self.assertEqual(r.status_code, 200, r.text)
        # A session token still works on those URLs until every screen asks for media tokens.
        session = reviewer["Authorization"].split()[1]
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}/documents/{docs[0]['id']}?token={session}").status_code, 200)

    def test_the_gp_fund_page_image_is_never_cached(self) -> None:
        """The GP Fund page route takes the token on the URL (the scan viewer's <img> cannot send a
        header); a cached copy of the answer is a token on disk, so it is served no-store (F10)."""
        import json, tempfile
        from pathlib import Path
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police, product="GPF", gpf_kind="final")["case"]["id"]
        with tempfile.TemporaryDirectory(prefix="agpb-gpf-pages-") as tmp:
            png = Path(tmp) / "p001.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
            (Path(tmp) / "pages.json").write_text(json.dumps([str(png)]))
            with mock.patch.object(gpf_bridge, "scratch_dir", lambda case_id, submission_no: Path(tmp)):
                token = self.sa()["Authorization"].split(" ", 1)[1]
                r = self.client.get(f"/api/v2/cases/{case_id}/gpf/pages/1?token={token}")
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.headers.get("Cache-Control"), "no-store")
                self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}/gpf/pages/1", headers=police).status_code, 403)

    # -- F14 -------------------------------------------------------------------------------------
    def test_the_password_rule_comes_from_the_server(self) -> None:
        reviewer = self.sa()
        me = self.client.get("/api/v2/auth/me", headers=reviewer).json()
        self.assertEqual(me["password_min_length"], settings.min_password_length())
        r = self.client.post("/api/v2/auth/login", json={"username": "syed.haider", "password": "Pension@2026"}, headers={"X-Portal": "ag"})
        self.assertEqual(r.json()["password_min_length"], settings.min_password_length())

    # -- N23 -------------------------------------------------------------------------------------
    def test_the_old_register_is_read_only_in_production(self) -> None:
        reviewer = self.login("syed.haider", "ag")                   # signed in before production refuses the trial password
        with mock.patch.dict(os.environ, {"PENSION_ENV": "production"}):
            self.assertFalse(settings.legacy_register_writes())
            r = self.client.post("/api/runs", files=[("file", ("x.pdf", io.BytesIO(_v2.PDF), "application/pdf"))], headers=reviewer)
            self.assertEqual(r.status_code, 403, r.text)
            self.assertIn("read-only", r.json()["detail"])
            r = self.client.post("/api/runs/abc123/decision", json={"action": "FORWARD"}, headers=reviewer)
            self.assertEqual(r.status_code, 403, r.text)
        with mock.patch.dict(os.environ, {"PENSION_ENV": "production", "PENSION_LEGACY_REGISTER_WRITES": "1"}):
            self.assertTrue(settings.legacy_register_writes())
        with mock.patch.dict(os.environ, {"PENSION_ENV": "", "PENSION_LEGACY_REGISTER_WRITES": "0"}):
            self.assertFalse(settings.legacy_register_writes())

    # -- N25 -------------------------------------------------------------------------------------
    def test_an_admin_reset_needs_a_reason_and_marks_the_next_sign_in(self) -> None:
        admin = self.login("admin", "ag")
        users = self.client.get("/api/v2/admin/users", headers=admin).json()
        target = next(u for u in users if u["username"] == "school-education")
        r = self.client.post(f"/api/v2/admin/users/{target['id']}/reset-password", headers=admin,
                             json={"password": "Fresh-Password-2026!"})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("reason", r.json()["detail"])
        r = self.client.post(f"/api/v2/admin/users/{target['id']}/reset-password", headers=admin,
                             json={"password": "Fresh-Password-2026!", "reason": "Officer locked out; identity confirmed by phone."})
        self.assertEqual(r.status_code, 200, r.text)
        from api.departments import SINGLE_PORTAL
        r = self.client.post("/api/v2/auth/login", json={"username": "school-education", "password": "Fresh-Password-2026!"},
                             headers={"X-Portal": "ag" if SINGLE_PORTAL else "school-education"})
        self.assertEqual(r.status_code, 200, r.text)
        log = self.client.get("/api/v2/admin/audit-log?limit=100", headers=admin).json()
        login_rows = [e for e in log if e["action"] == "LOGIN" and e["entity_id"] == target["id"]]
        self.assertTrue(login_rows, log[:5])
        self.assertTrue(login_rows[0]["after"].get("after_admin_reset"), login_rows[0])
        # The next sign-in is an ordinary one again.
        r = self.client.post("/api/v2/auth/login", json={"username": "school-education", "password": "Fresh-Password-2026!"},
                             headers={"X-Portal": "ag" if SINGLE_PORTAL else "school-education"})
        self.assertEqual(r.status_code, 200, r.text)
        log = self.client.get("/api/v2/admin/audit-log?limit=100", headers=admin).json()
        newest = [e for e in log if e["action"] == "LOGIN" and e["entity_id"] == target["id"]][0]
        self.assertNotIn("after_admin_reset", newest["after"])

    # -- N27 -------------------------------------------------------------------------------------
    def test_a_failed_sign_in_with_an_unknown_name_stores_a_hash_not_the_text(self) -> None:
        secret_typed_in_the_wrong_box = "Hunter2-Pension!"
        r = self.client.post("/api/v2/auth/login", json={"username": secret_typed_in_the_wrong_box, "password": "x"},
                             headers={"X-Portal": "ag"})
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/v2/auth/login", json={"username": "syed.haider", "password": "wrong-wrong"}, headers={"X-Portal": "ag"})
        self.assertEqual(r.status_code, 401)
        admin = self.login("admin", "ag")
        log = self.client.get("/api/v2/admin/audit-log?limit=50", headers=admin).json()
        failed = [e for e in log if e["action"] in ("LOGIN_FAILED", "LOGIN_REFUSED")]
        self.assertNotIn(secret_typed_in_the_wrong_box, str(log))
        self.assertTrue(any(e["entity_id"].startswith("(unknown) sha256:") for e in failed), failed)
        self.assertTrue(any(e["entity_id"] == "syed.haider" for e in failed), failed)

    # -- N28 -------------------------------------------------------------------------------------
    def test_an_override_to_returned_opens_a_round_request(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        dag = self.login("fatima.hameed", "ag")
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=dag,
                             json={"to_status": "RETURNED", "reason": "Filed under the wrong department; returned."})
        self.assertEqual(r.status_code, 200, r.text)
        rounds = self.client.get(f"/api/v2/cases/{case_id}/rounds", headers=dag).json()["rounds"]
        self.assertEqual(rounds[0]["closed_action"], "OVERRIDE")
        self.client.post(f"/api/v2/cases/{case_id}/documents", headers=police,
                         files=[("files", ("more.pdf", io.BytesIO(_v2.PDF2), "application/pdf"))])
        rounds = self.client.get(f"/api/v2/cases/{case_id}/rounds", headers=dag).json()["rounds"]
        self.assertEqual(len(rounds), 2)
        req = rounds[1]["requests"][0]
        self.assertEqual(req["action"], "OVERRIDE")
        self.assertIn("wrong department", req["remark"])
        self.assertIn("Fatima Hameed", req["by"])

    # -- N29 -------------------------------------------------------------------------------------
    def test_a_ddo_does_not_learn_that_the_type_was_the_engines_reading(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        conn = db.connect()
        try:
            conn.execute("UPDATE cases SET case_type_source = 'DETECTED', detected_case_type = 'FAMILY_PENSION' WHERE id = ?", (case_id,))
        finally:
            conn.close()
        seen = self.client.get(f"/api/v2/cases/{case_id}", headers=police).json()
        self.assertIsNone(seen["case_type_source"])
        self.assertIsNone(seen["detected_case_type"])
        ag = self.client.get(f"/api/v2/cases/{case_id}", headers=self.login("syed.haider", "ag")).json()
        self.assertEqual(ag["case_type_source"], "DETECTED")

    # -- N30 -------------------------------------------------------------------------------------
    def test_the_officer_name_header_survives_non_ascii(self) -> None:
        from urllib.parse import unquote
        encoded = gpf_bridge.header_name("Zoë  Qureshi\nX")
        self.assertTrue(encoded.isascii())
        self.assertEqual(unquote(encoded), "Zoë Qureshi X")
        self.assertEqual(gpf_bridge.header_name("Syed Haider"), "Syed%20Haider")


if __name__ == "__main__":
    unittest.main()
