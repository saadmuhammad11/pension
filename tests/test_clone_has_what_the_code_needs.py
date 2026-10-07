"""A fresh clone carries the data files the code and its tests read (audit 6 Oct 2026, N12).

    python3 -m unittest tests.test_clone_has_what_the_code_needs -v

.gitignore is a whitelist of code extensions, so config/case_types.json (which the rules and the
portal both read), the GP Fund module's fixtures and the test data were on the trial box only: a
clone could not start the API or run the GP suites. Re-verified 7 Oct 2026 on a `git archive`
snapshot: the rule packs (every determination failed with "no rule packs found"), the specimen
register, the GP corpus (the GP engine did not import) and the model fingerprints were missing
too. They are tracked now; this keeps them so -- and keeps whole folders tracked, so a pack or
corpus case added later cannot slip back to the trial box only.
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
    "rules/packs/PB-2024.12.json",
    "rules/packs/PB-2026.02.json",
    "rules/specimens/register.json",
    "GP/gpfund/corpus/order.json",
    "infra/models/qwen3-vl-30b-a3b-fp8.fingerprint",
)
#: Every file in these folders must be tracked (code and caches aside): the loaders read whatever
#: is there, so a new pack, specimen image or corpus case is needed by a clone the moment it lands.
FOLDERS = ("rules/packs", "rules/specimens", "GP/gpfund/corpus", "infra/models")
SKIP_SUFFIXES = (".py", ".pyc")


def _files_in(folder: str) -> list[str]:
    return sorted(str(p.relative_to(ROOT)) for p in (ROOT / folder).rglob("*")
                  if p.is_file() and p.suffix not in SKIP_SUFFIXES and "__pycache__" not in p.parts)


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

    def test_every_file_in_the_data_folders_is_tracked(self) -> None:
        if not (ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        for folder in FOLDERS:
            with self.subTest(folder=folder):
                present = _files_in(folder)
                self.assertTrue(present, f"{folder} is empty")
                tracked = set(subprocess.run(["git", "ls-files", "--", folder], cwd=ROOT,
                                             capture_output=True, text=True, check=True).stdout.split())
                self.assertEqual([p for p in present if p not in tracked], [],
                                 f"files in {folder} that git does not track")

    def test_the_rules_engine_finds_its_packs_from_the_tracked_files(self) -> None:
        """The failure a bare clone showed: ``PackError: no rule packs found``."""
        from rules.loader import load_all
        ids = sorted(p.id for p in load_all(ROOT / "rules" / "packs"))
        self.assertIn("PB-2026.02", ids)


if __name__ == "__main__":
    unittest.main()
