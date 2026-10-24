"""The repository holds no real case material, not just the release tree.

deploy/check-release-pii.py has refused a release carrying a real-looking CNIC or an
unannounced name since 12 Oct 2026, and it works. It runs on a STAGED release, which holds
no tests and no fixtures -- so on 24 Oct 2026 a real subscriber's CNIC, name, personnel
number and twenty-four years of his fund ledger went into test fixtures and past it. Caught
before the push, by the officer asking whether the commits were safe to send.

Same checker, run over what is tracked, so the gate is at the commit and not at the release.
"""
from __future__ import annotations

import importlib.util
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_release_pii", ROOT / "deploy" / "check-release-pii.py")
pii = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pii)

TEXT = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".sql", ".txt", ".html", ".css", ".yml", ".yaml"}


def _tracked():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, text=True, check=True)
    for rel in out.stdout.split("\0"):
        p = ROOT / rel
        if rel and p.suffix.lower() in TEXT and p.is_file():
            yield rel, p


class NoRealCaseMaterialIsTracked(unittest.TestCase):

    def test_no_tracked_file_carries_a_real_looking_cnic(self) -> None:
        hits = []
        for rel, path in _tracked():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for rx in (pii.DASHED, pii.BARE):
                for m in rx.finditer(text):
                    cnic = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                    if rx is pii.BARE and text[max(0, m.start() - 1):m.start()].isalpha():
                        continue
                    if not pii.synthetic(cnic):
                        # The number itself is not printed: the log must not become the leak.
                        hits.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
        self.assertEqual(hits, [], "a CNIC that does not announce itself as synthetic is tracked")

    def test_the_checker_still_refuses_a_real_one(self) -> None:
        """So this passing means something."""
        self.assertFalse(pii.synthetic("-".join(("42101", "7483921", "5"))))
        self.assertTrue(pii.synthetic("00001-0000001-1"))
