"""The three-tier AG workflow per pension wing (scope change C3, 9 Oct 2026; defaults Q1-Q5).

    /home/tmc/vllm_env/bin/python3 -m unittest tests.test_wing_tiers -v

A department's case lands with the Senior Auditor of its wing, who verifies and either returns it
to the department or forwards it to the Assistant AO, who forwards it to the AO, who decides.
Returns go one tier down at a time. A tier officer sees and acts on their own wing only; the moves
between tiers are internal and never reach the DDO; one account acts at one tier on a case.
"""
from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest import mock

from api import db, workflow
from tests import test_api_v2 as _v2


class Tiers(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify
    sa = _v2.V2Test.sa
    aao = _v2.V2Test.aao
    ao = _v2.V2Test.ao
    escalate = _v2.V2Test.escalate

    def _case(self, dept: str = "punjab-police") -> tuple[str, dict]:
        ddo = self.login(dept, dept)
        return self.create(ddo)["case"]["id"], ddo

    def _status(self, case_id: str, headers: dict) -> dict:
        r = self.client.get(f"/api/v2/cases/{case_id}", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # -- the happy path ---------------------------------------------------------------------------
    def test_the_full_chain_from_filing_to_the_ao_s_approval(self) -> None:
        case_id, ddo = self._case()
        sa, aao, ao = self.sa(), self.aao(), self.ao()
        c = self._status(case_id, sa)
        self.assertEqual((c["status"], c["holder_tier"], c["holder_label"]), ("FORWARDED", "SENIOR_AUDITOR", "With Senior Auditor, Pension-V"))
        self.assertIn("RUN_CHECK", c["allowed_actions"])
        # The AAO does not even see the case until the SA forwards it (12 Oct 2026), so cannot verify it.
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=aao).status_code, 403)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/check", headers=aao).status_code, 403)
        self.verify(sa, case_id)
        c = self._status(case_id, sa)
        self.assertEqual(c["status"], "UNDER_REVIEW")
        self.assertEqual(sorted(c["allowed_actions"]), ["FORWARD_TIER", "REQUEST_DOCS", "RETURN", "RUN_CHECK"])
        self.assertNotIn("APPROVE", c["allowed_actions"])                            # the SA decides nothing
        # The AO cannot act while the SA holds it: the case has not reached the AO's desk at all.
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=ao, json={"remark": "x" * 20})
        self.assertEqual(r.status_code, 403, r.text)
        self.assertIn("not been sent to your desk", r.json()["detail"])
        # SA -> AAO
        r = self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa, json={"remark": "Papers complete; no finding."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["case"]["allowed_actions"], [])                        # the answer is complete: the SA no longer holds it
        self.assertEqual((r.json()["case"]["status"], r.json()["case"]["holder_tier"]), ("UNDER_REVIEW", "ASSISTANT_AO"))
        import json as _json
        self.assertEqual(_json.loads(r.json()["event"]["payload_json"]), {"from_tier": "SENIOR_AUDITOR", "to_tier": "ASSISTANT_AO"})
        c = self._status(case_id, aao)
        self.assertEqual(sorted(c["allowed_actions"]), ["FORWARD_TIER", "RETURN_TIER"])
        self.assertEqual(c["holder_label"], "With Assistant Accounts Officer, Pension-V")
        # AAO -> AO
        r = self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=aao, json={})
        self.assertEqual(r.status_code, 200, r.text)
        c = self._status(case_id, ao)
        self.assertEqual(sorted(c["allowed_actions"]), ["APPROVE", "REJECT", "RETURN_TIER"])
        self.assertEqual(c["holder_label"], "With Accounts Officer, Pension-V")
        # The AO decides.
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=ao, json={"remark": "Approved; every paper in order."})
        self.assertEqual(r.status_code, 200, r.text)
        c = self._status(case_id, ao)
        self.assertEqual((c["status"], c["holder_tier"], c["holder_label"]), ("APPROVED", None, None))
        self.assertEqual([e["action"] for e in c["events"]],
                         ["CREATE", "FORWARD", "RUN_CHECK", "CHECK_DONE", "FORWARD_TIER", "FORWARD_TIER", "APPROVE"])
        self.assertEqual(c["events"][-1]["actor_role"], "AG_AO")

    # -- a case is shown to a tier only once it has been sent there (12 Oct 2026) ----------------
    def _visible(self, case_id: str, headers: dict) -> dict:
        """Whether every view agrees the case is (or is not) on this officer's screens."""
        one = self.client.get(f"/api/v2/cases/{case_id}", headers=headers).status_code == 200
        listed = case_id in {c["id"] for c in self.client.get("/api/v2/cases", headers=headers).json()}
        inv = self.client.get("/api/v2/inventory?product=PENSION", headers=headers).json()
        in_inventory = case_id in {r["id"] for r in inv["rows"]}
        total = self.client.get("/api/v2/stats?product=PENSION", headers=headers).json()["total"]
        return {"case": one, "list": listed, "inventory": in_inventory, "counted": total > 0}

    def test_each_tier_sees_the_case_only_once_the_tier_below_sends_it(self) -> None:
        case_id, ddo = self._case()
        sa, aao, ao = self.sa(), self.aao(), self.ao()
        yes = {"case": True, "list": True, "inventory": True, "counted": True}
        no = {"case": False, "list": False, "inventory": False, "counted": False}
        # Filed: with the Senior Auditor alone.
        self.assertEqual(self._visible(case_id, sa), yes)
        self.assertEqual(self._visible(case_id, aao), no)
        self.assertEqual(self._visible(case_id, ao), no)
        r = self.client.get(f"/api/v2/cases/{case_id}", headers=aao)
        self.assertIn("not been sent to your desk", r.json()["detail"])
        self.verify(sa, case_id)
        self.assertEqual(self._visible(case_id, aao), no)                          # verified is not forwarded
        # SA -> AAO: now the AAO sees it; the AO still does not.
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa, json={}).status_code, 200)
        self.assertEqual(self._visible(case_id, aao), yes)
        self.assertEqual(self._visible(case_id, ao), no)
        self.assertEqual(self._visible(case_id, sa), yes)                          # the SA keeps sight of what they sent
        # AAO -> AO.
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=aao, json={}).status_code, 200)
        self.assertEqual(self._visible(case_id, ao), yes)
        # A return down the chain does not hide it from the AO who returned it.
        r = self.client.post(f"/api/v2/cases/{case_id}/return-tier", headers=ao, json={"remark": "Check the FRC date again."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._visible(case_id, ao)["case"], True)
        self.assertEqual(self._visible(case_id, aao)["case"], True)

    def test_a_fresh_filing_after_a_return_starts_the_climb_again(self) -> None:
        case_id, ddo = self._case()
        sa, aao = self.sa(), self.aao()
        self.verify(sa, case_id)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa, json={}).status_code, 200)
        self.assertTrue(self._visible(case_id, aao)["case"])
        r = self.client.post(f"/api/v2/cases/{case_id}/return-tier", headers=aao, json={"remark": "Please re-examine the FRC."})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post(f"/api/v2/cases/{case_id}/return", headers=sa,
                             json={"remark": "FRC illegible; attach a legible copy.", "items": [{"label": "Legible FRC copy"}]})
        self.assertEqual(r.status_code, 200, r.text)
        # The department files again: the case is the Senior Auditor's alone until forwarded again.
        r = self.client.post(f"/api/v2/cases/{case_id}/forward", headers=ddo, json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self._visible(case_id, sa)["case"])
        self.assertEqual(self._visible(case_id, aao), {"case": False, "list": False, "inventory": False, "counted": False})

    def test_the_migration_backfills_how_far_each_case_has_climbed(self) -> None:
        held_by_aao, _ = self._case()
        decided, _ = self._case()
        filed, _ = self._case()
        sa = self.sa()
        for c in (held_by_aao, decided):
            self.verify(sa, c)
        self.assertEqual(self.client.post(f"/api/v2/cases/{held_by_aao}/forward-tier", headers=sa, json={}).status_code, 200)
        ao = self.escalate(decided)
        self.assertEqual(self.client.post(f"/api/v2/cases/{decided}/approve", headers=ao,
                                          json={"remark": "Approved; every paper in order."}).status_code, 200)
        # Forget what the moves recorded and re-run the migration's own SQL over the history.
        sql = (Path(__file__).resolve().parents[1] / "api" / "migrations" / "0016_reached_tier.sql").read_text()
        backfill = sql.split("ALTER TABLE cases ADD COLUMN reached_tier TEXT;", 1)[1]
        conn = db.connect()
        try:
            conn.execute("UPDATE cases SET reached_tier = NULL")
            for stmt in (s.strip() for s in backfill.split(";")):
                if stmt and not all(l.lstrip().startswith("--") for l in stmt.splitlines() if l.strip()):
                    conn.execute(stmt)
            conn.commit()
            got = {r["id"]: r["reached_tier"] for r in conn.execute("SELECT id, reached_tier FROM cases")}
        finally:
            conn.close()
        self.assertEqual(got[held_by_aao], "ASSISTANT_AO")
        self.assertEqual(got[decided], "AO")
        self.assertIn(got[filed], (None, "SENIOR_AUDITOR"))

    # -- each return step -------------------------------------------------------------------------
    def test_returns_go_one_tier_down_at_a_time_and_need_a_remark(self) -> None:
        case_id, ddo = self._case()
        sa, aao, ao = self.sa(), self.aao(), self.ao()
        self.verify(sa, case_id)
        self.escalate(case_id)
        # AO -> AAO (remark required)
        r = self.client.post(f"/api/v2/cases/{case_id}/return-tier", headers=ao, json={"remark": ""})
        self.assertEqual(r.status_code, 422, r.text)
        r = self.client.post(f"/api/v2/cases/{case_id}/return-tier", headers=ao, json={"remark": "Check the FRC date again."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["case"]["holder_tier"], "ASSISTANT_AO")
        # The AO cannot reach the SA directly: the case is now the AAO's.
        r = self.client.post(f"/api/v2/cases/{case_id}/return-tier", headers=ao, json={"remark": "and again"})
        self.assertEqual(r.status_code, 409, r.text)
        # AAO -> SA
        r = self.client.post(f"/api/v2/cases/{case_id}/return-tier", headers=aao, json={"remark": "Please re-examine the FRC."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["case"]["holder_tier"], "SENIOR_AUDITOR")
        # The SA has no lower tier: a return from here goes to the department.
        self.assertNotIn("RETURN_TIER", self._status(case_id, sa)["allowed_actions"])
        r = self.client.post(f"/api/v2/cases/{case_id}/return", headers=sa,
                             json={"remark": "FRC illegible; attach a legible copy.", "items": [{"label": "Legible FRC copy"}]})
        self.assertEqual(r.status_code, 200, r.text)
        c = self._status(case_id, ddo)
        self.assertEqual((c["status"], c["holder_tier"]), ("RETURNED", None))
        self.assertIn("ADD_DOCS", c["allowed_actions"])
        # The AAO and the AO cannot return a case to the department.
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/return", headers=aao, json={"remark": "x" * 20}).status_code, 403)

    def test_the_round_records_follow_only_the_department_return(self) -> None:
        case_id, ddo = self._case()
        sa, aao = self.sa(), self.aao()
        self.verify(sa, case_id)
        self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa, json={})
        self.client.post(f"/api/v2/cases/{case_id}/return-tier", headers=aao, json={"remark": "Look at page 3 again."})
        rounds = self.client.get(f"/api/v2/cases/{case_id}/rounds", headers=sa).json()["rounds"]
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0]["requests"], [])                               # an internal return opens no department round
        self.assertIsNone(rounds[0]["closed_action"])

    # -- the forward gate -------------------------------------------------------------------------
    def test_forward_is_refused_with_a_missing_line_and_allowed_after_a_waiver(self) -> None:
        self.report_to_write = {**_v2.FLAGGED_REPORT, "checklist": {"result": "INCOMPLETE", "missing": 1, "required": 1, "present": 0,
                                "items": [{"id": "AG-06", "requirement": "NADRA FRC", "status": "MISSING", "required": True}]}}   # AG-06 missing
        case_id, ddo = self._case()
        sa = self.sa()
        run_id = self.verify(sa, case_id)["run_id"]
        r = self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa, json={})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("AG-06", r.json()["detail"])
        r = self.client.post(f"/api/v2/cases/{case_id}/runs/{run_id}/checklist-actions", headers=sa,
                             json={"action": "WAIVE", "item_id": "AG-06", "ground": "FRC not required: the widow is the sole heir named on the PPO."})
        self.assertEqual(r.status_code, 201, r.text)
        r = self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa, json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["case"]["holder_tier"], "ASSISTANT_AO")

    # -- wing isolation ---------------------------------------------------------------------------
    def test_a_pension_ii_officer_can_neither_see_nor_act_on_a_pension_v_case(self) -> None:
        case_id, ddo = self._case("punjab-police")                               # Pension-V
        from api.departments import PENSION_SECTION_ORDER
        other_wing_sa = self.login(f"sa.p{PENSION_SECTION_ORDER.index('Pension-II') + 1}", "ag")
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=other_wing_sa).status_code, 403)
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/check", headers=other_wing_sa).status_code, 403)
        self.assertEqual(len(self.client.get("/api/v2/cases", headers=other_wing_sa).json()), 0)
        inv = self.client.get("/api/v2/inventory?product=PENSION", headers=other_wing_sa).json()
        self.assertEqual(inv["rows"], [])
        self.assertEqual(self.client.get("/api/v2/stats?product=PENSION", headers=other_wing_sa).json()["total"], 0)
        # Their own wing's cases they do see.
        own = self._status(case_id, self.sa())
        self.assertEqual(own["pension_wing"], "Pension-V")
        self.assertEqual(len(self.client.get("/api/v2/cases", headers=self.sa()).json()), 1)
        # The Deputy AG and the administrator see every wing.
        for h in (self.login("fatima.hameed", "ag"), self.login("admin", "ag")):
            self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=h).status_code, 200)

    def test_a_wing_officer_is_shown_only_their_wing_s_departments(self) -> None:
        """The lists behind the sidebar, the filters and the counts name the officer's own
        departments only; the AG's desk and the administrator see all 86 (9 Oct 2026)."""
        from api.departments import DEPARTMENTS, PENSION_SECTION_OF
        self._case("agriculture")                                                 # Pension-I
        self._case("punjab-police")                                               # Pension-V
        sa1 = self.sa("agriculture")
        mine = {d.code for d in DEPARTMENTS if PENSION_SECTION_OF.get(d.code) == "Pension-I"}
        listed = self.client.get("/api/v2/departments", headers=sa1).json()
        self.assertEqual({d["code"] for d in listed}, mine)
        counts = self.client.get("/api/v2/departments/counts?product=PENSION", headers=sa1).json()
        self.assertEqual({d["code"] for d in counts}, mine)
        self.assertEqual(sum(d["total"] for d in counts), 1)
        side = self.client.get("/api/v2/inventory?product=PENSION", headers=sa1).json()["sidebar"]
        self.assertEqual({d["code"] for d in side["by_department"]}, mine)
        self.assertEqual(side["by_section"], {"Pension-I": 1})
        for h in (self.login("ag.reviewer", "ag"), self.login("admin", "ag")):
            self.assertEqual(len(self.client.get("/api/v2/departments", headers=h).json()), len(DEPARTMENTS))
            self.assertEqual(self.client.get("/api/v2/inventory?product=PENSION", headers=h).json()["sidebar"]["by_section"], {"Pension-I": 1, "Pension-V": 1})

    # -- internal remarks -------------------------------------------------------------------------
    def test_internal_remarks_never_reach_the_ddo(self) -> None:
        case_id, ddo = self._case()
        sa, aao = self.sa(), self.aao()
        self.verify(sa, case_id)
        self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa, json={"remark": "SECRET-SA-NOTE"})
        self.client.post(f"/api/v2/cases/{case_id}/return-tier", headers=aao, json={"remark": "SECRET-AAO-NOTE"})
        self.client.post(f"/api/v2/cases/{case_id}/return", headers=sa, json={"remark": "Attach the attested PPO copy."})
        seen = self._status(case_id, ddo)
        self.assertNotIn("SECRET", str(seen))
        self.assertNotIn("FORWARD_TIER", [e["action"] for e in seen["events"]])
        self.assertNotIn("RETURN_TIER", [e["action"] for e in seen["events"]])
        self.assertEqual(seen["events"][-1]["action"], "RETURN")
        self.assertEqual(seen["events"][-1]["remark"], "Attach the attested PPO copy.")
        self.assertEqual(seen["holder_tier"], None)
        # The AG side keeps the whole history.
        full = self._status(case_id, sa)
        self.assertIn("SECRET-AAO-NOTE", str(full["events"]))
        self.assertEqual(self._status(case_id, self.login("admin", "ag"))["holder_label"], None)   # returned: nobody at the AG holds it

    def test_the_ddo_sees_only_that_the_ag_holds_the_case(self) -> None:
        case_id, ddo = self._case()
        self.verify(self.sa(), case_id)
        self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=self.sa(), json={})
        seen = self._status(case_id, ddo)
        self.assertEqual((seen["holder_tier"], seen["holder_label"]), (None, "With the Accountant General"))
        rows = self.client.get("/api/v2/cases", headers=ddo).json()
        self.assertEqual(rows[0]["holder_label"], "With the Accountant General")

    # -- maker-checker across tiers ---------------------------------------------------------------
    def test_one_account_acts_at_one_tier_on_a_case(self) -> None:
        case_id, ddo = self._case()
        sa = self.sa()
        self.verify(sa, case_id)
        self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa, json={})
        # The administrator moves the Senior Auditor up to Assistant AO of the same wing.
        admin = self.login("admin", "ag")
        users = self.client.get("/api/v2/admin/users", headers=admin).json()
        sa_row = next(u for u in users if u["username"] == _v2.tier_username("AG_SENIOR_AUDITOR", "punjab-police"))
        r = self.client.post(f"/api/v2/admin/users/{sa_row['id']}/role", headers=admin,
                             json={"role": "AG_ASSISTANT_AO", "pension_wing": "Pension-V", "reason": "Promoted to Assistant AO."})
        self.assertEqual(r.status_code, 200, r.text)
        promoted = self.login(sa_row["username"], "ag")
        r = self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=promoted, json={})
        self.assertEqual(r.status_code, 403, r.text)
        self.assertIn("one account acts at one tier", r.json()["detail"])
        # The filer can never approve, whatever the chain.
        self.assertNotIn("APPROVE", self._status(case_id, ddo)["allowed_actions"])

    # -- the Deputy AG ----------------------------------------------------------------------------
    def test_the_deputy_ag_overrides_from_anywhere_and_the_case_lands_with_the_senior_auditor(self) -> None:
        case_id, ddo = self._case()
        dag = self.login("fatima.hameed", "ag")
        self.verify(self.sa(), case_id)
        self.escalate(case_id)
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=dag,
                             json={"to_status": "FORWARDED", "reason": "Sent back to the start of the chain on the AG's direction."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["case"]["holder_tier"], "SENIOR_AUDITOR")           # an AG-held status: the Senior Auditor's queue
        r = self.client.post(f"/api/v2/cases/{case_id}/override", headers=dag,
                             json={"to_status": "RETURNED", "reason": "Filed under the wrong department; returned to it."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["case"]["holder_tier"])

    # -- the Accountant General's desk ------------------------------------------------------------
    def test_the_ag_desk_acts_at_every_tier_in_every_wing(self) -> None:
        """ag.reviewer (decision of 9 Oct 2026, afternoon): the office's senior officers share one
        login that is bound to no wing and no tier, runs the verification, climbs the chain itself,
        decides, and overrides like the Deputy AG."""
        desk = self.login("ag.reviewer", "ag")
        me = self.client.get("/api/v2/auth/me", headers=desk).json()
        self.assertTrue(me["capabilities"]["run_check"] and me["capabilities"]["decide"] and me["capabilities"]["override"])
        self.assertIsNone(me["capabilities"]["tier"])
        police_case, _ = self._case("punjab-police")                               # Pension-V
        agri_case, _ = self._case("agriculture")                                   # Pension-I
        self.assertEqual(len(self.client.get("/api/v2/cases", headers=desk).json()), 2)   # every wing
        self.assertIn("RUN_CHECK", self._status(police_case, desk)["allowed_actions"])
        self.verify(desk, police_case)
        # Bound to no tier: while the Senior Auditor holds the case the desk may already decide, forward,
        # return or override; only a return one tier down has nowhere to go from the first tier.
        c = self._status(police_case, desk)
        self.assertEqual(sorted(c["allowed_actions"]), ["APPROVE", "FORWARD_TIER", "OVERRIDE", "REJECT", "REQUEST_DOCS", "RETURN", "RUN_CHECK"])
        self.assertEqual(self.client.post(f"/api/v2/cases/{police_case}/forward-tier", headers=desk, json={}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/v2/cases/{police_case}/forward-tier", headers=desk, json={}).status_code, 200)
        self.assertEqual(self._status(police_case, desk)["holder_tier"], "AO")
        self.assertIn("RETURN_TIER", self._status(police_case, desk)["allowed_actions"])
        r = self.client.post(f"/api/v2/cases/{police_case}/approve", headers=desk, json={"remark": "Approved at the AG's desk."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["event"]["actor_role"], "AG_REVIEWER")
        # The other wing's case, straight to a decision after its verification.
        self.verify(desk, agri_case)
        self.escalate(agri_case, "agriculture")
        r = self.client.post(f"/api/v2/cases/{agri_case}/override", headers=desk,
                             json={"to_status": "RETURNED", "reason": "Returned on the Accountant General's direction."})
        self.assertEqual(r.status_code, 200, r.text)
        from api import gpf_bridge
        self.assertEqual(gpf_bridge.OFFICER_FOR_ROLE["AG_REVIEWER"], "dag")

    def test_the_trial_tier_accounts_are_seeded_once(self) -> None:
        made = db.seed_wing_tiers()
        self.assertEqual(len(made), 15)
        self.assertEqual(made[:3], ["sa.pension1", "aao.pension1", "ao.pension1"])
        self.assertEqual(db.seed_wing_tiers(), [])                                 # idempotent
        r = self.client.post("/api/v2/auth/login", json={"username": "ao.pension5", "password": db.SEED_PASSWORD}, headers={"X-Portal": "ag"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["user"]["role"], r.json()["user"]["pension_wing"], r.json()["user"]["display_name"]),
                         ("AG_AO", "Pension-V", "Accounts Officer, Pension-V"))

    # -- GP Fund cases follow the same holders (Q3) ----------------------------------------------
    def test_a_gp_fund_case_maps_the_tiers_to_the_module_s_levels(self) -> None:
        from api import gpf_bridge
        self.assertEqual((gpf_bridge.OFFICER_FOR_ROLE["AG_SENIOR_AUDITOR"], gpf_bridge.OFFICER_FOR_ROLE["AG_ASSISTANT_AO"],
                          gpf_bridge.OFFICER_FOR_ROLE["AG_AO"], gpf_bridge.OFFICER_FOR_ROLE["AG_DAG"]), ("da", "ao", "ao", "dag"))


class MigrationOfExistingCases(unittest.TestCase):
    def test_a_case_under_review_before_0014_lands_in_the_senior_auditor_s_queue(self) -> None:
        """Apply the migrations up to 0013 on a fresh database, file a case the old way, then 0014."""
        with tempfile_dir() as root:
            conn = db.connect(Path(root) / "p.sqlite3")
            try:
                with mock.patch.object(db, "MIGRATIONS", db.MIGRATIONS), \
                        mock.patch("api.db.sorted", lambda paths, **k: [p for p in sorted(paths) if p.stem < "0014"], create=True):
                    db.migrate(conn)
                cols = {r[1] for r in conn.execute("PRAGMA table_info(cases)")}
                self.assertNotIn("holder_tier", cols)
                conn.execute("INSERT INTO departments(code, name) VALUES ('HEALTH', 'Health')")
                conn.execute("INSERT INTO users(id, username, display_name, password_hash, role, department_code, created_at, updated_at) "
                             "VALUES ('u', 'ddo', 'DDO', 'h', 'DEPT_OFFICER', 'HEALTH', 't', 't')")
                for cid, status in (("c1", "UNDER_REVIEW"), ("c2", "FORWARDED"), ("c3", "RETURNED"), ("c4", "APPROVED")):
                    conn.execute("INSERT INTO cases(id, case_no, department_code, created_via, created_by, status, created_at, updated_at) "
                                 "VALUES (?, ?, 'HEALTH', 'DEPARTMENT', 'u', ?, 't', 't')", (cid, f"PC-{cid}", status))
                db.migrate(conn)                                                   # 0014 and anything after
                got = {r["id"]: r["holder_tier"] for r in conn.execute("SELECT id, holder_tier FROM cases")}
                self.assertEqual(got, {"c1": "SENIOR_AUDITOR", "c2": "SENIOR_AUDITOR", "c3": None, "c4": None})
                self.assertIn("pension_wing", {r[1] for r in conn.execute("PRAGMA table_info(users)")})
            finally:
                conn.close()


def tempfile_dir():
    import tempfile
    return tempfile.TemporaryDirectory(prefix="agpb-0014-")


if __name__ == "__main__":
    unittest.main()
