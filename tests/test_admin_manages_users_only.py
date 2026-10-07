"""The IT administrator manages users only; every action is logged under the real officer (business decision G6, 7 Oct 2026).

    python3 -m unittest tests.test_admin_manages_users_only -v

The administrator could file a case for any department, verify it, dispose of its findings,
approve it, override any case, and act in GP Fund as the DAG -- and the GP Fund module logged
every action under a hard-coded placeholder name for the band. Now the administrator creates,
disables and resets accounts and reads the registers and the audit log, and nothing else; the
override is the Deputy AG's; and the signed-in officer's own name travels into the GP Fund module
with the band, so its records carry the person, not the persona.
"""
from __future__ import annotations

import unittest
import urllib.request
from unittest import mock

from api import gpf_bridge
from tests import test_api_v2 as _v2


class TheAdministrator(unittest.TestCase):
    report_to_write = _v2.FLAGS_ONLY_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def test_capabilities_are_users_and_reading_only(self) -> None:
        r = self.client.post("/api/v2/auth/login", json={"username": "admin", "password": "Pension@2026"}, headers={"X-Portal": "ag"})
        caps = r.json()["capabilities"]
        for key in ("create_case", "add_documents", "run_check", "forward", "pick_department", "intake_choices",
                    "correct_case_type", "review", "dispose", "override"):
            self.assertFalse(caps[key], key)
        for key in ("manage_users", "audit_log", "all_departments"):
            self.assertTrue(caps[key], key)

    def test_no_case_action_is_open_to_the_administrator(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer, admin = self.login("syed.haider", "ag"), self.login("admin", "ag")
        run_id = self.verify(reviewer, case_id)["run_id"]
        refused = {
            "file a case": self.client.post("/api/v2/cases", headers=admin, data={"department_code": "PUNJAB_POLICE"}).status_code,
            "verify": self.client.post(f"/api/v2/cases/{case_id}/check", headers=admin).status_code,
            "approve": self.client.post(f"/api/v2/cases/{case_id}/approve", headers=admin, json={"remark": "x" * 20}).status_code,
            "return": self.client.post(f"/api/v2/cases/{case_id}/return", headers=admin, json={"remark": "x" * 20}).status_code,
            "override": self.client.post(f"/api/v2/cases/{case_id}/override", headers=admin, json={"to_status": "RETURNED", "reason": "x" * 20}).status_code,
            "dispose": self.client.post(f"/api/v2/cases/{case_id}/runs/{run_id}/dispositions", headers=admin,
                                        json={"flag_id": "F-1", "action": "WAIVE", "ground": "x" * 20}).status_code,
            "checklist": self.client.post(f"/api/v2/cases/{case_id}/runs/{run_id}/checklist-actions", headers=admin,
                                          json={"action": "WAIVE", "item_id": "AG-19", "ground": "x" * 20}).status_code,
            "case type": self.client.post(f"/api/v2/cases/{case_id}/case-type", headers=admin, json={"case_type": "WIDOW", "remark": "x" * 20}).status_code,
            "GP Fund frame": self.client.post("/api/v2/auth/gpf-session", headers=admin).status_code,
            "GP Fund action": self.client.post(f"/api/v2/cases/{case_id}/gpf/verify", headers=admin, json={}).status_code,
            "old register write": self.client.post("/api/runs/abc123/recompute", headers=admin).status_code,
        }
        self.assertEqual({k: v for k, v in refused.items() if v != 403}, {}, refused)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=admin).json()
        self.assertEqual(case["allowed_actions"], [])
        # Reading stays: the register, the stats, the audit log, the users.
        for path in ("/api/v2/cases", "/api/v2/stats", "/api/v2/admin/audit-log", "/api/v2/admin/users", "/api/runs"):
            self.assertEqual(self.client.get(path, headers=admin).status_code, 200, path)

    def test_the_deputy_ag_holds_the_override_and_the_dag_band(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]
        reviewer, dag = self.login("syed.haider", "ag"), self.login("fatima.hameed", "ag")
        self.verify(reviewer, case_id)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=dag).json()
        self.assertIn("OVERRIDE", case["allowed_actions"])
        self.assertNotIn("OVERRIDE", self.client.get(f"/api/v2/cases/{case_id}", headers=reviewer).json()["allowed_actions"])
        self.assertEqual(gpf_bridge.OFFICER_FOR_ROLE["AG_DAG"], "dag")
        self.assertNotIn("ADMIN", gpf_bridge.OFFICER_FOR_ROLE)

    def test_the_frame_check_names_the_officer(self) -> None:
        reviewer = self.login("syed.haider", "ag")
        r = self.client.post("/api/v2/auth/gpf-session", headers=reviewer)
        frame = r.cookies.get("pension_gpf")
        answer = self.client.get("/api/v2/auth/gpf-check", headers={"X-Gpf-Session": frame}).json()
        self.assertEqual((answer["officer"], answer["user"]), ("ao", "syed.haider"))
        self.assertEqual(answer["name"], "Syed Haider (AG Punjab, Pension Wing)")


class TheNameTravels(unittest.TestCase):
    def test_the_bridge_sends_the_acting_officer_s_name(self) -> None:
        seen = {}

        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"ok": true}'

        def fake_open(req, timeout=0):
            seen["headers"] = {k.lower(): v for k, v in req.header_items()}
            return _Resp()
        with mock.patch.object(urllib.request, "urlopen", fake_open):
            gpf_bridge.act("gpf-1", "verify", {"officer": "ao"}, acting_name="Ayesha Khan (Auditor)")
        self.assertEqual(seen["headers"].get("x-gpf-user"), "Ayesha Khan (Auditor)")
        with mock.patch.object(urllib.request, "urlopen", fake_open):
            gpf_bridge.act("gpf-1", "verify", {"officer": "ao"})
        self.assertNotIn("x-gpf-user", seen["headers"])

    def test_the_proxy_passes_band_and_name_separately(self) -> None:
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1] / "api/portal_server.py").read_text()
        self.assertIn('headers["X-GPF-Officer"] = band', src)
        self.assertIn('headers["X-GPF-User"] = name', src)
        self.assertIn('"x-gpf-user"', src)                           # a browser's own copy is dropped
        v2 = (Path(__file__).resolve().parents[1] / "api/v2.py").read_text()
        self.assertEqual(v2.count("acting_name=user.display_name"), 2)   # every bridge action carries the name


if __name__ == "__main__":
    unittest.main()
