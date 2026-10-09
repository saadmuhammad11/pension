"""Every view of the case inventory shows the same numbers, after every status change. 30 Sep 2026.

    python3 -m unittest tests.test_inventory_consistency -v

Files pension and GP Fund cases in three departments (one with no Pension section of its own),
moves them through every status change the workflow has, and after each change compares every
endpoint a screen counts from (api.check_inventory.compare) for the AG reviewer, the
administrator and each department. A new case must appear at once in the department's list, AG
Review's "All departments", its department and its section, and the Admin register.
"""
from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from tests import test_resubmission_rounds as _rounds

FRC_ON_FILE = _rounds.FRC_ON_FILE


class InventoryIsOneSourceOfTruth(_rounds.RoundsOverTheApi):
    """Reuses the rounds suite's TestClient set-up (stubbed pipeline); adds no tests of its own there."""

    def _check(self, where: str) -> None:
        from api.check_inventory import compare
        for user, role in (("syed.haider", "AG_REVIEWER"), ("admin", "ADMIN"),
                           ("school-education", "DEPT_OFFICER"), ("agriculture", "DEPT_OFFICER")):
            h = self.login(user)

            def get(path, h=h):
                r = self.client.get(path, headers=h)
                self.assertEqual(r.status_code, 200, f"{path}: {r.text}")
                return r.json()
            problems = compare(get, f"{role}:{user}")
            self.assertEqual(problems, [], f"after {where}")

    def _file(self, dept_user: str, product: str = "PENSION") -> str:
        h = self.login(dept_user)
        data = {"case_type": "DEATH_IN_SERVICE"} if product == "PENSION" else {"product": "GPF", "gpf_kind": "final"}
        r = self.client.post("/api/v2/cases", headers=h, data=data,
                             files=[("files", ("case.pdf", io.BytesIO(b"%PDF-1.4\n%" + dept_user.encode() + product.encode()), "application/pdf"))])
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["case"]["id"]

    def _visible_everywhere(self, case_id: str, dept_user: str, dept_code: str, product: str, section: str) -> None:
        ids = lambda rows: {r["id"] for r in rows}
        dept = self.login(dept_user)
        self.assertIn(case_id, ids(self.client.get(f"/api/v2/inventory?product={product}", headers=dept).json()["rows"]))
        for user in ("syed.haider", "admin"):
            h = self.login(user)
            for q in ("", f"&department={dept_code}", f"&pension_section={section}"):
                self.assertIn(case_id, ids(self.client.get(f"/api/v2/inventory?product={product}{q}", headers=h).json()["rows"]), (user, q))
                self.assertIn(case_id, ids(self.client.get(f"/api/v2/cases?product={product}{q}", headers=h).json()), (user, q))
        other = "PENSION" if product == "GPF" else "GPF"
        self.assertNotIn(case_id, ids(self.client.get(f"/api/v2/inventory?product={other}", headers=self.login("admin")).json()["rows"]))

    def test_every_view_agrees_through_every_status_change(self) -> None:
        from api import db
        ag, admin = self.sa("school-education"), self.login("fatima.hameed")   # the Deputy AG overrides (G6)
        ag_b = self.sa("agriculture")                                          # Pension-I: the other case's wing (C3)
        self._check("start")

        # A new case in each of two departments, and one of a department with no section (HEALTH, a
        # retired code): each at once in every view, with every count moved.
        a = self._file("school-education"); self._visible_everywhere(a, "school-education", "SCHOOL_EDUCATION", "PENSION", "Pension-III")
        b = self._file("agriculture"); self._visible_everywhere(b, "agriculture", "AGRICULTURE", "PENSION", "Pension-I")
        conn = db.connect()
        conn.execute("UPDATE cases SET department_code = 'HEALTH' WHERE id = ?", (b,)); conn.close()
        self._check("a case of a department with no Pension section")
        ids = {r["id"] for r in self.client.get("/api/v2/cases?product=PENSION&pension_section=LEGACY", headers=admin).json()}
        self.assertIn(b, ids)                                       # the Legacy section holds it (no wing: the Deputy AG sees it, a tier officer does not)
        self.assertEqual(self.client.get(f"/api/v2/cases/{b}", headers=ag).status_code, 403)
        conn = db.connect()
        conn.execute("UPDATE cases SET department_code = 'AGRICULTURE' WHERE id = ?", (b,)); conn.close()
        self._check("new cases")

        # Verified (returned by itself for the missing FRC), resubmitted, verified clean (approved).
        self.verify(ag, a); self._check("automatic return")
        self.client.post(f"/api/v2/cases/{a}/documents", headers=self.login("school-education"),
                         files=[("files", ("frc.pdf", io.BytesIO(b"%PDF-1.4\n%frc"), "application/pdf"))])
        self._check("documents added")
        self.client.post(f"/api/v2/cases/{a}/forward", headers=self.login("school-education"), json={"remark": "FRC"})
        self._check("forwarded")
        self.report = FRC_ON_FILE
        self.verify(ag, a); self._check("automatic approval")

        # Under review, then each decision by hand, and an admin override.
        self.report = {**FRC_ON_FILE, "flags": [{"id": "F-1", "severity": "HIGH", "class": "RULE-UNDECLARED",
                                                 "title": "Unrecorded recovery", "blocks_ppo": True}],
                       "recommendation": {"verdict": "HOLD", "blocking_flags": ["F-1"]}}
        self.verify(ag_b, b); self._check("under review")
        r = self.client.post(f"/api/v2/cases/{b}/request-docs", headers=ag_b, json={"remark": "Send the LPC."})
        self.assertEqual(r.status_code, 200, r.text); self._check("documents requested")
        self.client.post(f"/api/v2/cases/{b}/forward", headers=self.login("agriculture"), json={"remark": "again"})
        self.verify(ag_b, b)
        r = self.client.post(f"/api/v2/cases/{b}/reject", headers=self.escalate(b, "agriculture"), json={"remark": "Not entitled on these papers."})
        self.assertEqual(r.status_code, 200, r.text); self._check("rejected")
        r = self.client.post(f"/api/v2/cases/{b}/override", headers=admin,
                             json={"to_status": "UNDER_REVIEW", "reason": "Reopened on the department's appeal."})
        self.assertEqual(r.status_code, 200, r.text); self._check("admin override")
        r = self.client.post(f"/api/v2/cases/{b}/return", headers=ag_b, json={"remark": "Correct Annex-A."})
        self.assertEqual(r.status_code, 200, r.text); self._check("returned by hand")

        # GP Fund: its own inventory, as consistent, never mixed with pension.
        with mock.patch("api.gpf_bridge.start_examination", return_value={"jobId": "job-1", "state": "queued"}):
            g = self._file("agriculture", "GPF")
            self._visible_everywhere(g, "agriculture", "AGRICULTURE", "GPF", "Pension-I")
            self._check("a GP Fund case")

    def test_the_version_token_moves_on_every_change(self) -> None:
        ag = self.sa("school-education")
        v0 = self.client.get("/api/v2/inventory/version", headers=ag).json()["version"]
        a = self._file("school-education")
        v1 = self.client.get("/api/v2/inventory/version", headers=ag).json()["version"]
        self.assertNotEqual(v0, v1)
        self.client.post(f"/api/v2/cases/{a}/check", headers=ag)
        self.client.get(f"/api/v2/cases/{a}", headers=ag)
        v2 = self.client.get("/api/v2/inventory/version", headers=ag).json()["version"]
        self.assertNotEqual(v1, v2)


# The rounds suite's own tests are not re-run through this subclass.
for _name in [n for n in dir(_rounds.RoundsOverTheApi) if n.startswith("test_")]:
    setattr(InventoryIsOneSourceOfTruth, _name, None)
