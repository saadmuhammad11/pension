"""What the claimant is told, and what the officer's decision records. BRAIN §12.2, SOP §6.4.

    python3 -m unittest tests.test_notifications_and_decisions -v

Two layers that face outward and had almost no coverage between them.

The notification tests exist because of a defect that survived every run of the suite: the
claimant's message counted only HIGH department flags while the department's letter counted
those plus the missing and defective documents, so a case returned purely for missing papers
-- the commonest return there is -- told a bereaved family "0 corrections are needed from the
School Education Department". Nothing asserted on the count, so nothing caught it. The golden
case itself produced that message: 10 missing documents, 0 HIGH department flags.

The decision tests cover the other half of §9.7's override rule. ``rules.verdict`` guarantees
no HIGH flag can yield a FORWARD recommendation; ``api.decisions`` is what stops a person
forwarding such a case silently. The UI asks for a justification, and the UI is not what
enforces it -- so the enforcement needs a test that does not go through the UI.

No network, no filesystem outside a temporary directory, no clock dependence beyond the
timestamp the log writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

# So the file runs directly as well as under `-m unittest` from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
import tempfile
import unittest

from rules import CaseRecord
from rules.checklist import (Checklist, ChecklistItem, DEFECTIVE, MISSING,
                             NOT_APPLICABLE, PRESENT)
from rules.flags import CONTRA_IDENTITY, EXTRACT_LOWCONF, Flag, HIGH, LOW, MEDIUM
from rules.notifications import CLAIMANT, DEPARTMENT, notify, notify_claimant
from rules.verdict import FORWARD, HOLD, RETURN_FOR_CORRECTION, Recommendation


def checklist(*statuses: str) -> Checklist:
    return Checklist(
        checklist_id="AG_OFFICE_2026:WIDOW",
        items=tuple(
            ChecklistItem(f"AG-{i:02d}", f"requirement {i}", status)
            for i, status in enumerate(statuses, start=1)
        ),
    )


def flag(owner: str, severity: str = HIGH, flag_class: str = CONTRA_IDENTITY) -> Flag:
    return Flag(id="F-x", severity=severity, flag_class=flag_class,
                title="a finding", finding="the documents disagree",
                required_action="correct it", owner=owner)


FAMILY = CaseRecord(
    case_ref="AG-41759", case_type="FAMILY_PENSION_DEATH_IN_SERVICE",
    case_variant="WIDOW", forwarding_department="the School Education Department",
)
SELF = CaseRecord(
    case_ref="AG-50001", case_type="SUPERANNUATION_PENSION", case_variant="FRESH_SELF",
)

RETURNED = Recommendation(RETURN_FOR_CORRECTION, (), "2 checklist item(s) missing.")
HELD = Recommendation(HOLD, (), "unresolved rule ambiguity.")
FORWARDED = Recommendation(FORWARD, (), "checklist complete; no HIGH flag.")


# ==============================================================================================
# the count
# ==============================================================================================

class ClaimantCountTest(unittest.TestCase):

    def _claimant(self, record, cl, flags, rec):
        return notify(record, cl, flags, rec)[1]

    def test_missing_documents_are_counted(self):
        """The bug. Two missing papers, no HIGH flags: the claimant was told "0"."""
        body = self._claimant(FAMILY, checklist(MISSING, MISSING, PRESENT), (), RETURNED).body_en
        self.assertIn("Two corrections are needed", body)
        self.assertNotIn("0 corrections", body)

    def test_a_single_shortcoming_reads_as_singular(self):
        body = self._claimant(FAMILY, checklist(MISSING, PRESENT), (), RETURNED).body_en
        self.assertIn("One correction is needed", body)

    def test_defective_documents_are_counted_though_the_checklist_is_complete(self):
        """A DEFECTIVE item leaves the checklist COMPLETE by design -- the paper is there."""
        cl = checklist(DEFECTIVE, PRESENT)
        self.assertEqual(cl.missing, 0)
        body = self._claimant(FAMILY, cl, (), RETURNED).body_en
        self.assertIn("One correction is needed", body)

    def test_flags_and_documents_are_counted_together(self):
        body = self._claimant(
            FAMILY, checklist(MISSING, DEFECTIVE), (flag(DEPARTMENT),), RETURNED
        ).body_en
        self.assertIn("Three corrections are needed", body)

    def test_the_two_letters_agree(self):
        """One set of shortcomings, described twice. They must not disagree about its size."""
        for statuses, flags in (
            ((MISSING, MISSING, PRESENT), ()),
            ((MISSING, DEFECTIVE), (flag(DEPARTMENT),)),
            ((PRESENT,), (flag(DEPARTMENT), flag(DEPARTMENT))),
            ((MISSING, MISSING, MISSING, DEFECTIVE), (flag(DEPARTMENT),)),
        ):
            with self.subTest(statuses=statuses, flags=len(flags)):
                dept, claimant = notify(FAMILY, checklist(*statuses), flags, RETURNED)
                expected = sum(1 for s in statuses if s in (MISSING, DEFECTIVE)) + len(flags)
                self.assertIn(f"{expected} shortcoming", dept.subject)
                words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
                self.assertIn(words[expected], claimant.body_en)

    def test_only_department_owned_flags_are_counted_at_the_departments_door(self):
        """An unreadable page is the AG's own finding. No department can correct it."""
        body = self._claimant(
            FAMILY, checklist(MISSING), (flag("AG", HIGH, EXTRACT_LOWCONF),), RETURNED
        ).body_en
        self.assertIn("One correction is needed", body)

    def test_non_blocking_flags_are_not_corrections(self):
        """MEDIUM and LOW do not block a PPO, so they are not things to correct."""
        body = self._claimant(
            FAMILY, checklist(MISSING),
            (flag(DEPARTMENT, MEDIUM), flag(DEPARTMENT, LOW)), RETURNED
        ).body_en
        self.assertIn("One correction is needed", body)

    def test_a_return_with_nothing_for_the_department_says_so_without_a_count(self):
        """Blocked only by an AG-owned finding: "0 corrections" would be absurd."""
        body = self._claimant(
            FAMILY, checklist(PRESENT, PRESENT),
            (flag("AG", HIGH, EXTRACT_LOWCONF),), RETURNED
        ).body_en
        self.assertNotIn("correction", body)
        self.assertIn("with an officer", body)
        self.assertIn("No action is required from you", body)

    def test_no_message_ever_says_zero(self):
        """The whole grid: no combination may produce a count of nought."""
        for statuses in ((PRESENT,), (MISSING,), (DEFECTIVE,), (PRESENT, NOT_APPLICABLE)):
            for flags in ((), (flag(DEPARTMENT),), (flag("AG"),), (flag(CLAIMANT),)):
                for rec in (RETURNED, HELD, FORWARDED):
                    with self.subTest(statuses=statuses, flags=len(flags), v=rec.verdict):
                        body = self._claimant(FAMILY, checklist(*statuses), flags, rec)
                        self.assertNotIn("0 correction", body.body_en)
                        self.assertNotIn(" 0 ", body.body_ur)


# ==============================================================================================
# who the message is for
# ==============================================================================================

class ClaimantWordingTest(unittest.TestCase):

    def test_a_self_pension_is_not_a_family_pension(self):
        """The pensioner earned it. Calling it a family pension is wrong in the one line
        they are certain to read."""
        note = notify(SELF, checklist(MISSING, PRESENT), (), RETURNED)[1]
        self.assertIn("Your pension case", note.body_en)
        self.assertNotIn("family pension", note.body_en)
        self.assertIn("پنشن", note.body_ur)
        self.assertNotIn("فیملی", note.body_ur)

    def test_a_family_pension_still_says_so(self):
        note = notify(FAMILY, checklist(MISSING, PRESENT), (), RETURNED)[1]
        self.assertIn("Your family pension case", note.body_en)
        self.assertIn("فیملی پنشن", note.body_ur)

    def test_every_branch_names_the_case_kind_correctly(self):
        """Four branches, two case families: all eight must agree with the variant."""
        for record, wanted, unwanted in ((SELF, "Your pension case", "family pension"),
                                         (FAMILY, "Your family pension case", None)):
            for cl, flags, rec in (
                (checklist(MISSING), (), RETURNED),                   # counted corrections
                (checklist(PRESENT), (flag(CLAIMANT),), RETURNED),    # claimant must act
                (checklist(PRESENT), (), HELD),                       # hold
                (checklist(PRESENT), (), FORWARDED),                  # forward
            ):
                with self.subTest(variant=record.case_variant, verdict=rec.verdict):
                    body = notify(record, cl, flags, rec)[1].body_en
                    self.assertIn(wanted, body)
                    if unwanted:
                        self.assertNotIn(unwanted, body)

    def test_every_message_is_bilingual_and_says_whether_to_act(self):
        """§12.2: the single most valuable sentence is whether the person must do anything."""
        for cl, flags, rec, must_act in (
            (checklist(MISSING), (), RETURNED, False),
            (checklist(PRESENT), (flag(CLAIMANT),), RETURNED, True),
            (checklist(PRESENT), (), HELD, False),
            (checklist(PRESENT), (), FORWARDED, False),
        ):
            with self.subTest(verdict=rec.verdict, must_act=must_act):
                note = notify(FAMILY, cl, flags, rec)[1]
                self.assertTrue(note.bilingual)
                self.assertEqual(note.requires_recipient_action, must_act)
                self.assertEqual(note.recipient_class, CLAIMANT)
                if not must_act:
                    self.assertIn("No action is required from you", note.body_en)

    def test_no_rule_ids_or_rupee_figures_reach_the_claimant(self):
        """§12.2: no flag ids, no form numbers, no provisional amounts."""
        note = notify(FAMILY, checklist(MISSING), (flag(DEPARTMENT),), RETURNED)[1]
        for forbidden in ("F-1", "F-x", "CONTRA", "Rs.", "AG-01", "BLOCKING"):
            self.assertNotIn(forbidden, note.body_en)

    def test_the_diary_number_falls_back_to_the_case_reference(self):
        """A receipt number quoted wrongly is worse than one omitted."""
        note = notify(FAMILY, checklist(PRESENT), (), FORWARDED)[1]
        self.assertIn("AG-41759", note.body_en)

    def test_notify_claimant_without_a_checklist_still_works(self):
        """The optional parameter is optional. It sees fewer shortcomings, not none."""
        note = notify_claimant(FAMILY, (flag(DEPARTMENT),), RETURNED)
        self.assertIn("One correction is needed", note.body_en)


class DepartmentLetterTest(unittest.TestCase):

    def test_missing_and_defective_are_listed_separately(self):
        """§7.3: one asks for a document, the other for a correction."""
        dept = notify(FAMILY, checklist(MISSING, DEFECTIVE), (), RETURNED)[0]
        self.assertIn("Documents not located in the bundle", dept.body_en)
        self.assertIn("Documents present but defective", dept.body_en)

    def test_the_class_distinguishes_send_from_correct(self):
        send = notify(FAMILY, checklist(MISSING), (), RETURNED)[0]
        correct = notify(FAMILY, checklist(DEFECTIVE), (), RETURNED)[0]
        self.assertEqual(send.notification_class, "ADDITIONAL_DOCUMENTS_REQUIRED")
        self.assertEqual(correct.notification_class, "CASE_RETURNED")

    def test_ag_owned_findings_are_not_put_in_the_departments_letter(self):
        """Asking a department to correct a statutory cap or its own queue time is wrong."""
        dept = notify(FAMILY, checklist(PRESENT), (flag("AG", HIGH, EXTRACT_LOWCONF),),
                      RETURNED)[0]
        self.assertIn("0 shortcoming", dept.subject)
        self.assertEqual(dept.recipient_class, DEPARTMENT)

    def test_the_department_letter_is_english_only(self):
        dept = notify(FAMILY, checklist(MISSING), (), RETURNED)[0]
        self.assertIsNone(dept.body_ur)
        self.assertEqual(dept.channel, "EMAIL")


# ==============================================================================================
# the officer's decision -- api/decisions.py
# ==============================================================================================

class DecisionLogTest(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-decisions-")
        self.run_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _report(self, verdict="RETURN_FOR_CORRECTION", blocking=("F-1",), missing=1):
        return {
            "recommendation": {"verdict": verdict, "blocking_flags": list(blocking)},
            "checklist": {"result": "INCOMPLETE" if missing else "COMPLETE",
                          "missing": missing, "satisfied": 15, "required": 16},
            "case_variant": "WIDOW",
        }

    def _record(self, **kwargs):
        from api.decisions import record_decision
        params = {"run_id": "abc123", "action": "FORWARD", "officer": "Syed Haider",
                  "justification": "", "report": self._report()}
        params.update(kwargs)
        return record_decision(self.run_dir, **params)

    def test_forwarding_a_blocked_case_requires_a_written_reason(self):
        """§9.7. The UI asks; this is what enforces."""
        from api.decisions import DecisionError

        with self.assertRaises(DecisionError) as caught:
            self._record()
        self.assertIn("justification", str(caught.exception))

    def test_a_one_word_justification_is_not_a_justification(self):
        from api.decisions import DecisionError

        with self.assertRaises(DecisionError):
            self._record(justification="fine")

    def test_a_real_justification_is_accepted_and_marked_an_override(self):
        entry = self._record(justification="Verified against the SAP master by telephone.")
        self.assertTrue(entry["overrides_recommendation"])
        self.assertIn("F-1", entry["override_grounds"])

    def test_forwarding_a_clean_case_needs_no_justification(self):
        entry = self._record(report=self._report("FORWARD", (), 0))
        self.assertFalse(entry["overrides_recommendation"])

    def test_returning_a_blocked_case_is_not_an_override(self):
        """Agreeing with the recommendation is not overriding it."""
        entry = self._record(action="RETURN_FOR_CORRECTION")
        self.assertFalse(entry["overrides_recommendation"])

    def test_a_decision_has_an_author(self):
        from api.decisions import DecisionError

        with self.assertRaises(DecisionError):
            self._record(officer="   ", report=self._report("FORWARD", (), 0))

    def test_unknown_actions_are_refused(self):
        from api.decisions import DecisionError

        with self.assertRaises(DecisionError):
            self._record(action="APPROVE", report=self._report("FORWARD", (), 0))

    def test_a_case_that_reached_no_determination_cannot_be_forwarded_silently(self):
        """Nothing was checked, so nothing can vouch for it."""
        from api.decisions import DecisionError

        with self.assertRaises(DecisionError):
            self._record(report={"checklist": {}, "case_variant": "WIDOW"})

    def test_the_log_is_append_only(self):
        from api.decisions import current_decision, decisions_for

        self._record(action="RETURN_FOR_CORRECTION")
        self._record(action="HOLD")
        self._record(justification="Department confirmed the correction by email today.")
        history = decisions_for(self.run_dir)
        self.assertEqual([d["action"] for d in history],
                         ["RETURN_FOR_CORRECTION", "HOLD", "FORWARD"])
        self.assertEqual(current_decision(self.run_dir)["action"], "FORWARD")

    def test_the_desk_is_recorded_with_the_decision(self):
        """The portal asks who is at the desk; the log keeps the answer.

        Nothing verifies it -- there is no authentication in this build -- so this asserts
        that the claim is stored, not that it is true. An audit asking "was this person
        entitled to sign this" needs the desk in the row, not in a directory that has since
        changed.
        """
        entry = self._record(action="HOLD", role="Deputy Accountant General (Pension)")
        self.assertEqual(entry["role"], "Deputy Accountant General (Pension)")

        from api.decisions import current_decision
        self.assertEqual(
            current_decision(self.run_dir)["role"], "Deputy Accountant General (Pension)")

    def test_a_decision_without_a_desk_is_still_a_decision(self):
        """The name has an author check; the desk deliberately has none.

        A caller with no notion of desks -- a test, a CLI, the API before this field existed
        -- still records a decision, and it records the desk as absent rather than inventing
        one.
        """
        self.assertEqual(self._record(action="HOLD")["role"], "")

    def test_what_the_officer_saw_is_copied_not_referenced(self):
        """The report on disk may be rebuilt against a newer pack before any audit."""
        entry = self._record(action="HOLD")
        self.assertEqual(entry["recommended_verdict"], "RETURN_FOR_CORRECTION")
        self.assertEqual(entry["blocking_flags"], ["F-1"])
        self.assertEqual(entry["checklist_result"], "INCOMPLETE")
        self.assertEqual(entry["case_variant"], "WIDOW")

    def test_a_refused_decision_writes_nothing(self):
        from api.decisions import DecisionError, decisions_for

        with self.assertRaises(DecisionError):
            self._record()
        self.assertEqual(decisions_for(self.run_dir), [])

    def test_an_unreadable_line_is_reported_not_skipped(self):
        """This is an audit log: a reader must see that part of it could not be read."""
        from api.decisions import DECISIONS_LOG, decisions_for

        self._record(action="HOLD")
        with (self.run_dir / DECISIONS_LOG).open("a") as fh:
            fh.write("{corrupt\n")
        history = decisions_for(self.run_dir)
        self.assertEqual(len(history), 2)
        self.assertIn("unreadable", history[1])

    def test_no_decisions_is_not_an_error(self):
        from api.decisions import current_decision, decisions_for

        self.assertEqual(decisions_for(self.run_dir), [])
        self.assertIsNone(current_decision(self.run_dir))

    def test_entries_are_valid_json_lines(self):
        self._record(action="HOLD")
        self._record(action="RETURN_FOR_CORRECTION")
        from api.decisions import DECISIONS_LOG

        for line in (self.run_dir / DECISIONS_LOG).read_text().splitlines():
            json.loads(line)


if __name__ == "__main__":
    unittest.main()
