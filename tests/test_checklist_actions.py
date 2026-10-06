"""An officer naming a document the reader missed, or waiving a checklist item (api.checklist_actions)."""

import tempfile
import unittest

from api import checklist_actions as ca
from api.dispositions import calculation_gate

REPORT = {
    "pages": [{"page": n, "document_type": "OTHER" if n == 7 else "FORWARDING_LETTER"} for n in range(1, 21)],
    "pages_unaccounted": [12, 13, 19],
    "flags": [],
    "checklist": {
        "checklist_id": "FAM", "required": 3, "present": 1, "missing": 2, "defective": 0,
        "not_applicable": 0, "satisfied": 1, "result": "INCOMPLETE", "result_line": "x",
        "items": [
            {"id": "AG-02", "requirement": "CNIC of the claimant", "status": "PRESENT", "located": [2]},
            {"id": "AG-15", "requirement": "Non-remarriage certificate", "status": "MISSING"},
            {"id": "AG-19", "requirement": "Reason for late submission", "status": "MISSING"},
        ],
    },
}
OFFICER = dict(officer="Syed Haider", role="ACCOUNTS_OFFICE")


class Actions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def act(self, **kw):
        return ca.record(self.run, run_id="r", report=REPORT, **OFFICER, **kw)

    def test_naming_a_missing_document_makes_it_present_on_its_pages(self):
        self.act(action="IDENTIFY", item_id="AG-15", pages=[12, 13])
        out = ca.apply(REPORT, self.run)
        item = out["checklist"]["items"][1]
        self.assertEqual((item["status"], item["engine_status"]), ("PRESENT", "MISSING"))
        self.assertEqual(item["located"], [12, 13])
        self.assertIn("Syed Haider", item["reason"])
        self.assertEqual(out["pages_unaccounted"], [19])
        self.assertEqual(out["checklist"]["missing"], 1)
        self.assertEqual(out["checklist"]["engine"]["missing"], 2)        # the engine's reading kept
        self.assertEqual(REPORT["checklist"]["items"][1]["status"], "MISSING")  # not rewritten

    def test_a_waiver_needs_a_ground_and_then_clears_the_item(self):
        with self.assertRaises(ca.ChecklistActionError):
            self.act(action="WAIVE", item_id="AG-19", ground="not needed")
        self.act(action="IDENTIFY", item_id="AG-15", pages=[12])
        self.act(action="WAIVE", item_id="AG-19", ground="Case is under three years old; no reason is due.")
        out = ca.apply(REPORT, self.run)
        self.assertEqual(out["checklist"]["items"][2]["status"], "WAIVED")
        self.assertEqual((out["checklist"]["result"], out["checklist"]["satisfied"]), ("COMPLETE", 3))

    def test_the_gate_opens_when_the_officer_has_settled_the_checklist(self):
        self.assertFalse(calculation_gate(ca.apply(REPORT, self.run), self.run)["open"])
        self.act(action="NAME", pages=[12], document_name="Non-remarriage certificate", item_id="AG-15")
        self.act(action="WAIVE", item_id="AG-19", ground="Case is under three years old; no reason is due.")
        self.assertTrue(calculation_gate(ca.apply(REPORT, self.run), self.run)["open"])

    def test_a_page_the_checklist_does_not_list_can_be_named(self):
        e = self.act(action="NAME", pages=[19], document_name="Succession certificate")
        out = ca.apply(REPORT, self.run)
        self.assertEqual([n["name"] for n in out["named_documents"]], ["Succession certificate"])
        self.assertEqual(out["pages_unaccounted"], [12, 13])
        self.act(action="CLEAR", name_id=e["name_id"])
        self.assertEqual(ca.apply(REPORT, self.run)["pages_unaccounted"], [12, 13, 19])

    def test_an_unrecognised_page_named_as_a_checklist_paper_satisfies_it(self):
        e = self.act(action="NAME", pages=[7], document_name="Union Council non-remarriage cert.",
                     item_id="AG-15")
        out = ca.apply(REPORT, self.run)
        item = out["checklist"]["items"][1]
        self.assertEqual((item["status"], item["located"]), ("PRESENT", [7]))
        self.assertIn("Union Council", item["reason"])
        self.assertNotIn(7, out["nameable_pages"])
        self.act(action="CLEAR", name_id=e["name_id"])
        self.assertEqual(ca.apply(REPORT, self.run)["checklist"]["items"][1]["status"], "MISSING")

    def test_only_an_unrecognised_or_unread_page_can_be_named(self):
        self.assertEqual(ca.nameable_pages(REPORT), [7, 12, 13, 19])
        with self.assertRaises(ca.ChecklistActionError):
            self.act(action="NAME", pages=[3], document_name="Forwarding letter")   # identified

    def test_undo_restores_the_engines_reading(self):
        self.act(action="IDENTIFY", item_id="AG-15", pages=[12])
        self.act(action="CLEAR", item_id="AG-15")
        self.assertEqual(ca.apply(REPORT, self.run)["checklist"]["items"][1]["status"], "MISSING")
        self.assertEqual(len(ca.history(self.run)), 2)                    # both kept, in order

    def test_what_is_refused(self):
        for kw in (dict(action="IDENTIFY", item_id="AG-99", pages=[3]),     # no such item
                   dict(action="IDENTIFY", item_id="AG-15", pages=[]),      # no page
                   dict(action="IDENTIFY", item_id="AG-15", pages=[44]),    # beyond the bundle
                   dict(action="NAME", pages=[19], document_name="x")):     # no real name
            with self.assertRaises(ca.ChecklistActionError, msg=str(kw)):
                self.act(**kw)
        with self.assertRaises(ca.ChecklistActionError):
            ca.record(self.run, run_id="r", report=REPORT, officer="Dept", role="ADMIN_DEPARTMENT",
                      action="WAIVE", item_id="AG-19", ground="a long enough ground here")


if __name__ == "__main__":
    unittest.main()
