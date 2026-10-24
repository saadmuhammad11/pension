"""The database is backed up nightly, and the backup is one that restores (24 Oct 2026).

Until this week the office had none: no cron job, no systemd timer, ``archive_mode`` off, and
a single dump taken by hand five days earlier sitting in /root. The database is twelve
megabytes; the register it holds is not replaceable.

These are the checks that can be made without root on an arbitrary machine: that the three
pieces agree with each other, and that the script verifies its own output rather than
trusting that a file appeared. Whether the timer is installed is a property of a box, not of
the repository, and is checked by looking at the box.

    python3 -m pytest tests/test_nightly_backup.py -q
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
SCRIPT = DEPLOY / "backup-db.sh"
SERVICE = (DEPLOY / "pension-backup.service").read_text(encoding="utf-8")
TIMER = (DEPLOY / "pension-backup.timer").read_text(encoding="utf-8")


class TheThreePiecesAgree(unittest.TestCase):

    def test_the_unit_runs_the_script_that_is_here(self) -> None:
        exec_start = re.search(r"^ExecStart=(.+)$", SERVICE, re.M).group(1).strip()
        self.assertEqual(exec_start, str(SCRIPT))

    def test_the_script_is_executable(self) -> None:
        self.assertTrue(os.access(SCRIPT, os.X_OK), f"{SCRIPT} is not executable")

    def test_it_is_a_oneshot_so_a_failure_is_a_failed_unit(self) -> None:
        """A backup that fails silently is worse than none: it is believed."""
        self.assertIn("Type=oneshot", SERVICE)

    def test_the_timer_names_the_office_s_own_clock(self) -> None:
        """The host runs America/New_York and the office is in Karachi; "02:30" without a zone
        would back up in the middle of the working day."""
        line = re.search(r"^OnCalendar=(.+)$", TIMER, re.M).group(1).strip()
        self.assertIn("Asia/Karachi", line)

    def test_a_night_the_box_was_off_is_not_simply_skipped(self) -> None:
        self.assertIn("Persistent=true", TIMER)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze is not on this machine")
    def test_systemd_itself_accepts_the_schedule(self) -> None:
        line = re.search(r"^OnCalendar=(.+)$", TIMER, re.M).group(1).strip()
        out = subprocess.run(["systemd-analyze", "calendar", line], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Next elapse", out.stdout)


class TheScriptChecksItsOwnWork(unittest.TestCase):

    TEXT = SCRIPT.read_text(encoding="utf-8")

    def test_the_dump_is_listed_back_before_it_counts_as_a_backup(self) -> None:
        """pg_restore --list on the file just written: a dump that cannot be read is a file."""
        self.assertIn("pg_restore --list", self.TEXT)
        self.assertIn("the dump holds no table data", self.TEXT)

    def test_a_dump_that_failed_is_not_left_lying_about(self) -> None:
        """Half a dump beside the good ones is the one a hurried restore picks."""
        self.assertRegex(self.TEXT, r"rm -f \"\$out\"")

    def test_it_says_so_when_the_only_copy_is_on_this_disk(self) -> None:
        self.assertIn("NO OFFSITE COPY", self.TEXT)

    def test_the_password_is_never_in_the_script(self) -> None:
        """pg_dump runs as the postgres system user over the local socket."""
        self.assertIn("-u postgres pg_dump", self.TEXT)
        self.assertNotIn("PGPASSWORD", self.TEXT)

    @unittest.skipUnless(shutil.which("bash"), "no bash")
    def test_it_parses(self) -> None:
        self.assertEqual(subprocess.run(["bash", "-n", str(SCRIPT)]).returncode, 0)


if __name__ == "__main__":
    unittest.main()
