"""The audit of 12 Oct 2026, items 9, 10 and 13: decisions rest on the current run; clearances,
the case type and GP Fund actions are the holding tier's; the scrubbed determination carries no
length of service; an engine refusal becomes the finding it deserves; the conditional checklist
lines AG-14, AG-17 and AG-21 do not read MISSING on a bundle that never needed them.

    /home/tmc/vllm_env/bin/python3 -m unittest tests.test_audit_fixes_12oct -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests import test_api_v2 as _v2  # noqa: E402

from api import db  # noqa: E402


class DecisionsRestOnTheCurrentRun(unittest.TestCase):
    """Item 9: a decision needs a completed verification on the case's CURRENT run, so after a
    failed re-verification nobody returns or approves on the earlier run's findings."""
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    sa, aao, ao, escalate = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate
    create = _v2.V2Test.create
    verify = _v2.V2Test.verify

    def _under_review(self) -> tuple[str, dict, dict]:
        police = self.login("punjab-police", "punjab-police")
        case_id = self.create(police)["case"]["id"]                      # filed: with the Senior Auditor
        sa = self.sa()
        run_id = self.verify(sa, case_id)["run_id"]
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=sa).json()["status"], "UNDER_REVIEW")
        return case_id, sa, {"run_id": run_id, "police": police}

    def test_a_failed_re_verification_blocks_the_decision_until_verified_again(self) -> None:
        case_id, sa, ctx = self._under_review()
        # The re-verification failed: the current run is the failed one, the earlier run is done.
        conn = db.connect()
        try:
            row = conn.execute("SELECT submission_no, created_by FROM cases WHERE id = ?", (case_id,)).fetchone()
            conn.execute("INSERT INTO case_runs (id, case_id, run_id, submission_no, started_by, started_at, state) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", (db.new_id(), case_id, "failed-again", row["submission_no"],
                                                           row["created_by"], "2026-10-12T10:00:00", "failed"))
            conn.execute("UPDATE cases SET status = 'AI_FAILED', current_run_id = 'failed-again' WHERE id = ?", (case_id,))
            conn.commit()
        finally:
            conn.close()
        r = self.client.post(f"/api/v2/cases/{case_id}/return", headers=sa, json={"remark": "x" * 40})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("examine the case with AI first", r.json()["detail"])

    def test_a_completed_current_run_still_lets_the_case_move(self) -> None:
        case_id, sa, ctx = self._under_review()
        r = self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa, json={})
        self.assertEqual(r.status_code, 200, r.text)


class ClearancesAreTheHoldingTiers(DecisionsRestOnTheCurrentRun):
    """Item 10: findings and checklist lines are cleared, and the case type corrected, by the
    tier that holds the case, on its current run; the AG's desk is bound by neither."""

    def test_an_officer_whose_tier_no_longer_holds_the_case_cannot_clear_a_finding(self) -> None:
        case_id, sa, ctx = self._under_review()
        run_id = ctx["run_id"]
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa, json={}).status_code, 200)
        body = {"flag_id": "F-1", "action": "WAIVE", "ground": "the paper is on file at p.3, seen by me"}
        r = self.client.post(f"/api/v2/cases/{case_id}/runs/{run_id}/dispositions", headers=sa, json=body)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("Assistant", r.json()["detail"])
        r = self.client.post(f"/api/v2/cases/{case_id}/runs/{run_id}/checklist-actions", headers=sa,
                             json={"item_id": "AG-05", "action": "WAIVE", "ground": "x" * 30})
        self.assertEqual(r.status_code, 409, r.text)
        # The holder may; the AG's desk may; a run that is not the current one may not be acted on.
        aao = self.aao()
        r = self.client.post(f"/api/v2/cases/{case_id}/runs/{run_id}/dispositions", headers=aao, json=body)
        self.assertNotIn(r.status_code, (403, 409), r.text)
        desk = self.login("ag.reviewer", "ag")
        r = self.client.post(f"/api/v2/cases/{case_id}/runs/{run_id}/dispositions", headers=desk, json=body)
        self.assertNotIn(r.status_code, (403, 409), r.text)
        r = self.client.post(f"/api/v2/cases/{case_id}/runs/not-the-current-one/dispositions", headers=aao, json=body)
        self.assertIn(r.status_code, (404, 409), r.text)

    def test_the_case_type_is_corrected_by_the_holding_tier_only(self) -> None:
        case_id, sa, ctx = self._under_review()
        self.assertEqual(self.client.post(f"/api/v2/cases/{case_id}/forward-tier", headers=sa, json={}).status_code, 200)
        body = {"case_type": "WIDOW", "remark": "declared wrongly; the claimant is the widow"}
        r = self.client.post(f"/api/v2/cases/{case_id}/case-type", headers=sa, json=body)
        self.assertEqual(r.status_code, 409, r.text)
        r = self.client.post(f"/api/v2/cases/{case_id}/case-type", headers=self.aao(), json=body)
        self.assertEqual(r.status_code, 200, r.text)


class TheScrubbedDeterminationCarriesNoService(unittest.TestCase):
    """Item 13: qualifying service is a figure the engine computes and this release does not show."""

    DET = {
        "rule_pack_id": "PB-DI-2026.09",
        "steps": [
            {"rule_id": "QS-01", "description": "Qualifying service, 1993-12-08 to 2026-02-18", "amount": None,
             "unit": "years", "computation_shown": "x", "note": "P32Y2M10D, exclusive day-counting (QS-16)."},
            {"rule_id": "QS-08", "description": "Qualifying service reckoned for pension", "amount": None,
             "unit": "years", "computation_shown": "min(32, 30) = 30", "note": "2 year(s) earned but not reckonable."},
            {"rule_id": "FAM-IS-03", "description": "Share", "amount": 1, "note": "Widow's share, Rs 12,345 of the gross."},
        ],
        "ambiguities": [], "inputs": {},
        "caveats": ["AI extracted the inputs; this determination was computed by the rules engine (PB) with no model."],
    }

    def test_service_lengths_and_the_computed_caveat_are_withheld(self) -> None:
        from rules.scope import has_computed_amount, scrub_determination
        before = has_computed_amount({"determination": self.DET})
        self.assertTrue(any("service" in p for p in before), before)
        self.assertTrue(any("computed" in p for p in before), before)
        out = scrub_determination(self.DET)
        self.assertEqual(has_computed_amount({"determination": out}), [])
        self.assertEqual(out["steps"][0]["note"], "[service withheld], exclusive day-counting (QS-16).")
        self.assertEqual(out["steps"][1]["note"], "[service withheld] earned but not reckonable.")
        self.assertEqual(out["steps"][2]["note"], "Widow's share, [amount withheld] of the gross.")
        self.assertIn("no figure is computed in this release", out["caveats"][0])
        self.assertNotIn("was computed by the rules engine", out["caveats"][0])

    def test_strip_service_leaves_dates_rule_ids_and_pages_alone(self) -> None:
        from rules.scope import strip_service
        self.assertEqual(strip_service("submitted 2026-07-01, p.7, QS-16, pack PB-DII-2026.09"),
                         "submitted 2026-07-01, p.7, QS-16, pack PB-DII-2026.09")
        self.assertEqual(strip_service("7 reckonable years is short of the 10 (QS-02)"),
                         "[service withheld] is short of the 10 (QS-02)")


class AnEngineRefusalBecomesTheFindingItDeserves(unittest.TestCase):
    """Item 13: only a contradiction in the papers is a HIGH against the department; short
    service is a MEDIUM for the reviewer without the years; anything else is a gap."""

    def test_the_refusal_is_sorted_by_kind(self) -> None:
        from pipeline.report import _self_pension_refusal
        from rules.engine import RetirementDateMismatch, ServiceTooShort
        from rules.loader import UnknownReferenceValue
        error, defect, short = _self_pension_refusal(RetirementDateMismatch("born 1956, retired 2026: ten years past"))
        self.assertEqual(defect, error)
        self.assertIsNone(short)
        error, defect, short = _self_pension_refusal(ServiceTooShort("7 reckonable years is short of the 10 (QS-02); due a service gratuity"))
        self.assertIsNone(defect)
        self.assertEqual(short, error)
        self.assertNotIn("7 reckonable years", short)
        error, defect, short = _self_pension_refusal(UnknownReferenceValue("no VOL-RED-01 row for 2026"))
        self.assertEqual((defect, short), (None, None))
        self.assertIn("VOL-RED-01", error)

    def test_short_service_is_a_medium_finding_for_the_reviewer_without_a_figure(self) -> None:
        from rules import CaseRecord, Document
        from rules.flags import HIGH, MEDIUM, SELF_PENSION_REFUSED, SERVICE_SHORT, run_battery
        from rules.loader import select_pack
        pack = select_pack(effective_date=date(2026, 6, 30))
        rec = CaseRecord(case_ref="T", case_type="SUPERANNUATION_PENSION", case_variant="FRESH_SELF",
                         documents=(Document("FORM_B_I", (3,)),),
                         self_pension_service_short="[service withheld] is short of the 10")
        flags = [f for f in run_battery(rec, pack) if f.flag_class in (SERVICE_SHORT, SELF_PENSION_REFUSED)]
        self.assertEqual([(f.flag_class, f.severity, f.owner) for f in flags], [(SERVICE_SHORT, MEDIUM, "AG")])
        self.assertNotRegex(flags[0].title + flags[0].finding, r"\d+ (?:reckonable )?years?\b(?! the rules)")
        rec = CaseRecord(case_ref="T", case_type="SUPERANNUATION_PENSION", case_variant="FRESH_SELF",
                         documents=(Document("FORM_B_I", (3,)),), self_pension_defect="born 1956, retired 2026")
        flags = [f for f in run_battery(rec, pack) if f.flag_class in (SERVICE_SHORT, SELF_PENSION_REFUSED)]
        self.assertEqual([(f.flag_class, f.severity) for f in flags], [(SELF_PENSION_REFUSED, HIGH)])


class ServiceShortAtTheBoundary(unittest.TestCase):
    """Item 13: entry on 1 July 2011 and death on 30 June 2021 is ten years, not nine."""

    def _record(self, entry: date, death: date):
        from rules import CaseRecord
        return CaseRecord(case_ref="T", case_type="FAMILY_PENSION_DEATH_IN_SERVICE", case_variant="DEATH_IN_SERVICE",
                          form_dates=(("date_of_birth", date(1980, 1, 1), 2, "FORM_D_I"),
                                      ("date_first_entry", entry, 2, "FORM_D_I"),
                                      ("date_of_death", death, 2, "FORM_D_I")))

    def test_ten_whole_years_are_not_short_and_a_day_less_is(self) -> None:
        from rules.flags import SERVICE_SHORT, check_form_d_i_dates
        from rules.loader import select_pack
        pack = select_pack(effective_date=date(2021, 6, 30))
        self.assertEqual([f.flag_class for f in check_form_d_i_dates(self._record(date(2011, 7, 1), date(2021, 6, 30)), pack)], [])
        short = check_form_d_i_dates(self._record(date(2011, 7, 1), date(2021, 6, 29)), pack)
        self.assertEqual([f.flag_class for f in short], [SERVICE_SHORT])
        self.assertNotRegex(short[0].title, r"\(\d+ years?\)")


class TheConditionalLinesAskOnlyWhenCalledFor(unittest.TestCase):
    """Item 13: AG-14, AG-17 and AG-21 on a death in service follow the claimant's relation; a
    relation the form does not state keeps the line."""

    def _items(self, variant: str, relation: str | None, *docs: str) -> dict:
        from rules import CaseRecord, Document
        from rules.checklist import run_checklist
        rec = CaseRecord(case_ref="T", case_type="FAMILY_PENSION_DEATH_IN_SERVICE" if variant == "DEATH_IN_SERVICE" else "SELF_PENSION",
                         case_variant=variant, claimant_relation=relation,
                         documents=tuple(Document(t, (n + 1,)) for n, t in enumerate(docs)))
        return {i.id: i for i in run_checklist(rec, variant=variant).items}

    def test_a_widow_s_death_in_service_bundle_is_not_asked_for_the_three(self) -> None:
        items = self._items("DEATH_IN_SERVICE", "widow", "FORM_D_I")
        for item_id in ("AG-14", "AG-17", "AG-21"):
            self.assertEqual(items[item_id].status, "NOT_APPLICABLE", item_id)
        self.assertIn("spouse", items["AG-17"].reason)

    def test_the_relation_decides_which_line_stays(self) -> None:
        items = self._items("DEATH_IN_SERVICE", "divorced daughter", "FORM_D_I")
        self.assertEqual((items["AG-14"].status, items["AG-17"].status, items["AG-21"].status),
                         ("NOT_APPLICABLE", "MISSING", "MISSING"))
        items = self._items("DEATH_IN_SERVICE", "son, disable", "FORM_D_I")
        self.assertEqual((items["AG-14"].status, items["AG-21"].status), ("MISSING", "NOT_APPLICABLE"))
        items = self._items("DEATH_IN_SERVICE", "son, disable", "FORM_D_I", "MEDICAL_BOARD_CERTIFICATE")
        self.assertEqual(items["AG-14"].status, "PRESENT")

    def test_an_unstated_relation_keeps_every_line(self) -> None:
        items = self._items("DEATH_IN_SERVICE", None, "FORM_D_I")
        for item_id in ("AG-14", "AG-17", "AG-21"):
            self.assertEqual(items[item_id].status, "MISSING", item_id)

    def test_a_compulsory_retirement_needs_no_medical_board(self) -> None:
        items = self._items("FRESH_INVALID", None, "FORM_B_IV", "COMPULSORY_RETIREMENT_ORDER")
        self.assertEqual(items["AG-14"].status, "NOT_APPLICABLE")
        items = self._items("FRESH_INVALID", None, "FORM_B_IV")
        self.assertEqual(items["AG-14"].status, "MISSING")
        items = self._items("DISABLED_CHILD_SIBLING", "son, disable", "FORM_D_II")
        self.assertEqual(items["AG-14"].status, "MISSING")


if __name__ == "__main__":
    unittest.main()
