"""An authorised desk confirms a provisional rule value, and the record shows it. SOP §7.5.

    python3 -m unittest tests.test_rule_confirmations -v

Every test writes to a temporary log. The office's real log in artifacts/rules is evidence and
is never touched from here.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DAG = "Deputy Accountant General (Pension)"
AUTHORITY = "FD-SR-III-4-57/2013 dated 15-05-2013"


class WhoMayConfirm(unittest.TestCase):
    def test_the_two_desks_the_documents_name(self):
        from rules.confirmations import desk_is_authorised
        self.assertTrue(desk_is_authorised(DAG))
        self.assertTrue(desk_is_authorised("DAG_PENSION"))
        self.assertTrue(desk_is_authorised("Reference-data administrator"))
        self.assertTrue(desk_is_authorised("reference_admin"))

    def test_nobody_else(self):
        from rules.confirmations import desk_is_authorised
        for desk in ("Auditor, Pension wing (AG / DAO)", "Pension Sanctioning Authority",
                     "System administrator", "", None):
            self.assertFalse(desk_is_authorised(desk), desk)


class RecordingAConfirmation(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.log = Path(self._dir.name) / "confirmations.jsonl"

    def tearDown(self):
        self._dir.cleanup()

    def _confirm(self, **over):
        from rules.confirmations import record_confirmation
        kw = dict(item="BLOCKING-07", key="share.widow_percent", value="75",
                  officer="A. Officer", role=DAG, authority=AUTHORITY, path=self.log,
                  now=datetime(2026, 9, 16, 12, 0))
        kw.update(over)
        return record_confirmation(**kw)

    def test_it_is_appended_and_in_force(self):
        from rules.confirmations import confirmed_values, load_confirmations
        entry = self._confirm()
        self.assertEqual(entry["value"], "75")
        self.assertEqual(entry["at"], "2026-09-16T12:00:00")
        self.assertEqual(load_confirmations(self.log), [entry])
        self.assertEqual(confirmed_values(self.log)["share.widow_percent"], entry)

    def test_the_latest_entry_wins_and_the_earlier_one_stays(self):
        from rules.confirmations import confirmed_values, load_confirmations
        self._confirm(value="75")
        self._confirm(value="50", now=datetime(2026, 9, 17))
        self.assertEqual(len(load_confirmations(self.log)), 2)
        self.assertEqual(confirmed_values(self.log)["share.widow_percent"]["value"], "50")

    def test_an_unauthorised_desk_is_refused_and_nothing_is_written(self):
        from rules.confirmations import NotAuthorised
        with self.assertRaises(NotAuthorised):
            self._confirm(role="Auditor, Pension wing (AG / DAO)")
        self.assertFalse(self.log.exists())

    def test_no_authority_no_confirmation(self):
        from rules.confirmations import ConfirmationError
        with self.assertRaises(ConfirmationError) as ctx:
            self._confirm(authority="see file")               # eight characters: not a citation
        with self.assertRaises(ConfirmationError):
            self._confirm(authority="")
        self.assertIn("authority", str(ctx.exception))
        self.assertFalse(self.log.exists())

    def test_a_percentage_is_bounded_and_a_choice_is_closed(self):
        from rules.confirmations import ConfirmationError
        with self.assertRaises(ConfirmationError):
            self._confirm(value="175")
        with self.assertRaises(ConfirmationError):
            self._confirm(key="base.definition", value="whatever_the_slip_says")
        self.assertEqual(self._confirm(key="base.definition", value="net_pension")["value"],
                         "net_pension")

    def test_unset_is_not_a_value(self):
        from rules.confirmations import ConfirmationError
        with self.assertRaises(ConfirmationError):
            self._confirm(value="UNSET")

    def test_an_unknown_key_or_item_is_refused(self):
        from rules.confirmations import ConfirmationError
        with self.assertRaises(ConfirmationError):
            self._confirm(key="share.nephew_percent")
        with self.assertRaises(ConfirmationError):
            self._confirm(item="BLOCKING-99")

    def test_the_officer_must_be_named(self):
        from rules.confirmations import ConfirmationError
        with self.assertRaises(ConfirmationError):
            self._confirm(officer="  ")


class TheOpenItemsAsTheScreenSeesThem(unittest.TestCase):
    def test_provisional_and_confirmed_are_told_apart(self):
        from rules.confirmations import open_items, record_confirmation
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "c.jsonl"
            record_confirmation(item="BLOCKING-07", key="share.widow_percent", value="75",
                                officer="A", role=DAG, authority=AUTHORITY, path=log)
            items = open_items(log)
        self.assertEqual([i["item"] for i in items], ["BLOCKING-07"])
        keys = {k["key"]: k for k in items[0]["keys"]}
        self.assertTrue(keys["share.widow_percent"]["confirmed"])
        self.assertEqual(keys["share.widow_percent"]["confirmation"]["authority"], AUTHORITY)
        self.assertFalse(keys["share.regrant_daughter_percent"]["confirmed"])
        self.assertEqual(keys["share.regrant_daughter_percent"]["provisional_value"], "75")
        self.assertIsNone(keys["base.definition"]["provisional_value"])
        self.assertEqual(keys["base.definition"]["choices"], ["pension_in_payment", "net_pension"])
        self.assertIn(DAG, items[0]["authorised_desks"])

    def test_a_torn_line_in_the_log_is_skipped_not_fatal(self):
        from rules.confirmations import load_confirmations
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "c.jsonl"
            log.write_text(json.dumps({"key": "share.widow_percent", "value": "75"}) + "\n"
                           + '{"key": "share.wid', encoding="utf-8")
            self.assertEqual(len(load_confirmations(log)), 1)


if __name__ == "__main__":
    unittest.main()
