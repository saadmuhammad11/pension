"""Signing authorities and specimen signatures: one master store for both products (C1, 9 Oct 2026).

    /home/tmc/vllm_env/bin/python3 -m unittest tests.test_signatories -v
"""
from __future__ import annotations

import io
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from api import db, signatories
from rules import specimens
from tests import test_api_v2 as _v2

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class Signatories(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    login = _v2.V2Test.login

    def setUp(self) -> None:
        _v2.V2Test.setUp(self)
        self._store = tempfile.TemporaryDirectory(prefix="agpb-signatories-")
        self._sp = mock.patch.object(signatories, "STORE_DIR", Path(self._store.name) / "store"); self._sp.start()
        self._active = specimens.ACTIVE
        self.added = signatories.start_up()

    def tearDown(self) -> None:
        specimens.ACTIVE = self._active
        self._sp.stop()
        self._store.cleanup()
        _v2.V2Test.tearDown(self)

    def _conn(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        return conn

    # -- import ------------------------------------------------------------------------------------
    def test_the_two_legacy_registers_are_imported_once(self) -> None:
        self.assertEqual(self.added["pension"], 1)
        self.assertGreater(self.added["gpf"], 5)
        conn = self._conn()
        before = conn.execute("SELECT COUNT(*) FROM signing_authorities").fetchone()[0]
        again = signatories.import_all(conn)
        self.assertEqual(again, {"pension": 0, "gpf": 0})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM signing_authorities").fetchone()[0], before)
        sgad = signatories.get_authority(conn, "SGAD-AS-ADMN-2025-09-09")
        self.assertEqual((sgad["post"], sgad["source"], sgad["provisional"], len(sgad["specimens"])),
                         ("Additional Secretary (Admn)", "PENSION_REGISTER", False, 3))
        gpf = [a for a in signatories.list_authorities(conn, product="GPF") if a["source"] == "GPF_PROVISIONAL"]
        self.assertTrue(gpf and all(a["provisional"] for a in gpf))
        # The export the pipeline reads names the same entry with its three images.
        self.assertEqual(specimens.active_register(), signatories.STORE_DIR / signatories.EXPORT_NAME)
        spec, why = specimens.lookup("Govt. of the Punjab / S & G A D", "Addl. Secretary (Admn)", date(2026, 3, 1))
        self.assertEqual((spec.id, why, len(spec.images)), ("SGAD-AS-ADMN-2025-09-09", "on file", 3))
        self.assertTrue(all(p.exists() for p in spec.images))

    # -- lookup ------------------------------------------------------------------------------------
    def test_lookup_by_department_post_and_date_including_a_closed_entry(self) -> None:
        conn = self._conn()
        admin = _v2.V2Test.login(self, "admin", "ag")
        r = self.client.post("/api/v2/signatories", headers=admin, json={
            "department_name": "Health Department", "department_code": "HEALTH", "post": "Secretary Health",
            "post_aliases": ["Secretary (Health)"], "officer_name": "Dr A. Khan", "scope": "PSA for BS-17 and above",
            "effective_from": "2024-01-01", "product_scope": "PENSION", "letter_no": "SO(H)1/2024", "letter_date": "2023-12-20"})
        self.assertEqual(r.status_code, 201, r.text)
        first = r.json()["id"]
        r = self.client.post(f"/api/v2/signatories/{first}/specimens", headers=admin, files=[("file", ("s1.jpg", io.BytesIO(JPEG), "image/jpeg"))])
        self.assertEqual(r.status_code, 201, r.text)
        found = signatories.lookup(conn, "Health Department", "Secretary (Health)", date(2025, 6, 1))
        self.assertEqual((found["authority"]["id"], found["status"], len(found["specimens"])), (first, "on file", 1))
        # Closed on 30 Jun 2025: a signature of July 2025 has no specimen; one of May 2025 still has.
        r = self.client.post(f"/api/v2/signatories/{first}/close", headers=admin,
                             json={"effective_to": "2025-06-30", "reason": "Transferred; letter SO(H)9/2025."})
        self.assertEqual(r.status_code, 200, r.text)
        after = signatories.lookup(conn, "Health Department", "Secretary Health", date(2025, 7, 15))
        self.assertIsNone(after["authority"])
        self.assertEqual(after["status"], "not in force on 2025-07-15")
        self.assertIn("No specimen on file for Health Department", after["message"])
        still = signatories.lookup(conn, "Govt. of the Punjab, Health Department", "Secretary Health", date(2025, 5, 1))
        self.assertEqual(still["authority"]["id"], first)
        # The successor: a new entry, the old one kept.
        r = self.client.post("/api/v2/signatories", headers=admin, json={
            "department_name": "Health Department", "post": "Secretary Health", "officer_name": "Mr B. Ali",
            "effective_from": "2025-07-01", "product_scope": "PENSION"})
        self.assertEqual(r.status_code, 201, r.text)
        later = signatories.lookup(conn, "Health Department", "Secretary Health", date(2025, 7, 15))
        self.assertEqual(later["authority"]["officer_name"], "Mr B. Ali")
        self.assertIn("No specimen on file", later["message"])             # listed, but no image yet
        rows = conn.execute("SELECT COUNT(*) FROM signing_authorities WHERE department_name = 'Health Department'").fetchone()[0]
        self.assertEqual(rows, 2)
        actions = [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE entity_type = 'signing_authority' AND entity_id = ? ORDER BY at", (first,))]
        self.assertEqual(actions, ["SIGNATORY_CREATE", "SPECIMEN_ADD", "SIGNATORY_CLOSE"])
        # Nothing but the department's own post matches.
        self.assertIsNone(signatories.lookup(conn, "Health Department", "Deputy Secretary", date(2025, 5, 1))["authority"])

    def test_a_closed_entry_cannot_be_edited_and_a_reason_is_needed_to_close(self) -> None:
        admin = _v2.V2Test.login(self, "admin", "ag")
        r = self.client.post("/api/v2/signatories/SGAD-AS-ADMN-2025-09-09/close", headers=admin, json={"reason": "x"})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/v2/signatories/SGAD-AS-ADMN-2025-09-09", headers=admin, json={"officer_name": "Someone Else", "reason": "typo"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["officer_name"], "Someone Else")
        r = self.client.post("/api/v2/signatories/SGAD-AS-ADMN-2025-09-09/close", headers=admin, json={"reason": "Post changed hands."})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/v2/signatories/SGAD-AS-ADMN-2025-09-09", headers=admin, json={"officer_name": "Again"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.post("/api/v2/signatories/SGAD-AS-ADMN-2025-09-09/close", headers=admin,
                                          json={"reason": "Post changed hands."}).status_code, 409)

    # -- who sees a specimen -------------------------------------------------------------------------
    def test_a_ddo_is_refused_the_specimen_and_the_ag_is_served_it_uncached_and_audited(self) -> None:
        conn = self._conn()
        name = signatories.get_authority(conn, "SGAD-AS-ADMN-2025-09-09")["specimens"][0]["name"]
        url = f"/api/v2/signatories/SGAD-AS-ADMN-2025-09-09/images/{name}"
        police = _v2.V2Test.login(self, "punjab-police", "punjab-police")
        self.assertEqual(self.client.get(url, headers=police).status_code, 403)
        self.assertEqual(self.client.get("/api/v2/signatories", headers=police).status_code, 403)
        reviewer = _v2.V2Test.login(self, "syed.haider", "ag")
        r = self.client.get(url, headers=reviewer)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(r.headers["content-type"], "image/jpeg")
        # The same through a media token on the address (an <img> cannot send a header).
        token = self.client.get("/api/v2/auth/media-token", headers=reviewer).json()["token"]
        self.assertEqual(self.client.get(f"{url}?token={token}").status_code, 200)
        # A DDO's media token is refused too.
        ddo_token = self.client.get("/api/v2/auth/media-token", headers=police).json()["token"]
        self.assertEqual(self.client.get(f"{url}?token={ddo_token}").status_code, 403)
        views = conn.execute("SELECT actor_id FROM audit_log WHERE action = 'SPECIMEN_VIEWED' AND entity_id = ?",
                             ("SGAD-AS-ADMN-2025-09-09",)).fetchall()
        self.assertEqual(len(views), 2)
        # The old open route is closed to a DDO as well.
        self.assertEqual(self.client.get(f"/api/specimens/SGAD-AS-ADMN-2025-09-09/images/{name}", headers=police).status_code, 403)
        self.assertEqual(self.client.get(f"/api/specimens/SGAD-AS-ADMN-2025-09-09/images/{name}", headers=reviewer).status_code, 200)

    def test_at_most_five_specimens_and_only_images(self) -> None:
        admin = _v2.V2Test.login(self, "admin", "ag")
        aid = "SGAD-AS-ADMN-2025-09-09"
        for i in range(2):
            r = self.client.post(f"/api/v2/signatories/{aid}/specimens", headers=admin, files=[("file", (f"s{i}.png", io.BytesIO(PNG), "image/png"))])
            self.assertEqual(r.status_code, 201, r.text)
        r = self.client.post(f"/api/v2/signatories/{aid}/specimens", headers=admin, files=[("file", ("s9.png", io.BytesIO(PNG), "image/png"))])
        self.assertEqual(r.status_code, 409)
        r = self.client.post(f"/api/v2/signatories/{aid}/letter", headers=admin, files=[("file", ("l.txt", io.BytesIO(b"hello"), "text/plain"))])
        self.assertEqual(r.status_code, 422)
        r = self.client.post(f"/api/v2/signatories/{aid}/letter", headers=admin, files=[("file", ("l.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf"))])
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(r.json()["has_letter"])
        self.assertEqual(self.client.get(f"/api/v2/signatories/{aid}/letter", headers=_v2.V2Test.login(self, "punjab-police", "punjab-police")).status_code, 403)

    # -- GP Fund register --------------------------------------------------------------------------
    def test_marking_the_gpf_register_final_clears_the_provisional_flag_here_and_in_the_module(self) -> None:
        admin = _v2.V2Test.login(self, "admin", "ag")
        conn = self._conn()
        calls = []
        with mock.patch("api.gpf_bridge._request", side_effect=lambda *a, **k: calls.append((a, k)) or {"ok": True, "status": "final"}):
            r = self.client.post("/api/v2/signatories/gpf-register/finalize", headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertGreater(r.json()["rows_made_final"], 5)
        self.assertEqual(calls[0][0][:2], ("POST", "/api/doa/finalize"))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM signing_authorities WHERE provisional = 1").fetchone()[0], 0)
        self.assertTrue(conn.execute("SELECT 1 FROM audit_log WHERE action = 'GPF_REGISTER_FINAL'").fetchone())


if __name__ == "__main__":
    unittest.main()
