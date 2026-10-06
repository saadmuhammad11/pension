"""A fresh clone carries the data files the code and its tests read (audit 6 Oct 2026, N12).

    python3 -m unittest tests.test_clone_has_what_the_code_needs -v

.gitignore is a whitelist of code extensions, so config/case_types.json (which the rules and the
portal both read), the GP Fund module's fixtures and the test data were on the trial box only: a
clone could not start the API or run the GP suites. They are tracked now; this keeps them so.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEEDED = (
    "config/case_types.json",
    "GP/backend/gpf/fixtures/cases.json",
    "GP/backend/gpf/fixtures/gen_sap.json",
    "GP/backend/tests/ground_truth.json",
    "GP/agofficegpfund/prototype/sap-samples/SAP_EXTRACT_90000227.txt",
    "GP/prototype",
)


class CloneContents(unittest.TestCase):
    def test_the_data_files_are_tracked(self) -> None:
        if not (ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        tracked = set(subprocess.run(["git", "ls-files", "--", *NEEDED], cwd=ROOT, capture_output=True,
                                     text=True, check=True).stdout.split())
        missing = [p for p in NEEDED if p not in tracked]
        self.assertEqual(missing, [], f"git does not track: {missing}")

    def test_the_files_the_code_reads_exist(self) -> None:
        for p in NEEDED:
            self.assertTrue((ROOT / p).exists(), p)


if __name__ == "__main__":
    unittest.main()
