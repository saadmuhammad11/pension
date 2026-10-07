"""The sign-in sheet can be brought back in step with the accounts without touching them (6 Oct 2026).

    python3 -m unittest tests.test_refresh_credentials_sheet -v

After the trial's accounts were put on one password by hand, the sheet still showed the generated
passwords and sent its first reader to a locked account. ``refresh-credentials <password>`` records
a sheet row for every active account that is on that password and changes nothing else.
"""
from __future__ import annotations

import csv
import unittest

from api import db
from tests import test_api_v2 as _v2


class RefreshSheet(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login

    def _rows(self) -> dict[str, str]:
        with open(db.CREDENTIALS_CSV, newline="", encoding="utf-8") as fh:
            latest = {}
            for r in csv.DictReader(fh):
                latest[r["username"]] = r["password"]
        return latest

    def test_rows_are_recorded_for_the_accounts_on_that_password_only(self) -> None:
        conn = db.connect()
        try:
            from api.auth import hash_password
            conn.execute("UPDATE users SET password_hash = ? WHERE username IN ('agriculture', 'syed.haider')",
                         (hash_password("Trial-1234"),))
            conn.commit()
            before = {u["username"]: (u["password_hash"], u["token_version"]) for u in conn.execute("SELECT * FROM users")}
        finally:
            conn.close()
        names = db.refresh_credentials("Trial-1234")
        self.assertEqual(sorted(names), ["agriculture", "syed.haider"])
        rows = self._rows()
        self.assertEqual((rows["agriculture"], rows["syed.haider"]), ("Trial-1234", "Trial-1234"))
        self.assertEqual(rows["admin"], db.SEED_PASSWORD)              # untouched accounts keep their row
        self.assertIn("Trial-1234", db.CREDENTIALS_HTML.read_text())
        conn = db.connect()
        try:
            after = {u["username"]: (u["password_hash"], u["token_version"]) for u in conn.execute("SELECT * FROM users")}
        finally:
            conn.close()
        self.assertEqual(before, after)                                  # nothing changed, no session ended
        self.login("admin", "ag")                                        # and everyone still signs in

    def test_a_password_nobody_has_records_nothing(self) -> None:
        rows_before = self._rows()
        self.assertEqual(db.refresh_credentials("Nobody-Has-This-9"), [])
        self.assertEqual(self._rows(), rows_before)


if __name__ == "__main__":
    unittest.main()
