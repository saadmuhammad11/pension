"""Every setting the code reads is in deploy/pension.env.example (audit 6 Oct 2026, N8).

    python3 -m unittest tests.test_env_example_is_complete -v

New settings were added to the code (bundle page cap, concurrent runs, tool timeouts, the GP Fund
job deadline...) without a line in the example the administrator copies, so a deployment could
not know they existed. This test reads every PENSION_* and GPF_* name the code asks the
environment for and expects each in the example, set or named in a comment.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ("api", "pipeline", "extraction", "rag", "rules", "GP/backend/gpf")
EXAMPLE = ROOT / "deploy" / "pension.env.example"
#: Read by the launch scripts and tests only, never by a deployment.
NOT_FOR_DEPLOYMENT = {"PENSION_PYTHON"}


def settings_read_by_the_code() -> set[str]:
    names: set[str] = set()
    pattern = re.compile(r"""(?:environ(?:\.get)?\s*[\[(]\s*|getenv\s*\(\s*)["']((?:PENSION|GPF)_[A-Z0-9_]+)["']""")
    for folder in CODE:
        for path in (ROOT / folder).rglob("*.py"):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            names.update(pattern.findall(path.read_text(encoding="utf-8", errors="replace")))
    return names - NOT_FOR_DEPLOYMENT


class EnvExample(unittest.TestCase):
    def test_every_setting_the_code_reads_is_in_the_example(self) -> None:
        text = EXAMPLE.read_text(encoding="utf-8")
        documented = set(re.findall(r"\b((?:PENSION|GPF)_[A-Z0-9_]+)\b", text))
        missing = sorted(settings_read_by_the_code() - documented)
        self.assertEqual(missing, [], f"add these to {EXAMPLE.relative_to(ROOT)}: {missing}")

    def test_the_example_names_no_setting_the_code_has_forgotten(self) -> None:
        text = EXAMPLE.read_text(encoding="utf-8")
        documented = set(re.findall(r"^\s*#?\s*((?:PENSION|GPF)_[A-Z0-9_]+)=", text, re.M))
        stale = sorted(documented - settings_read_by_the_code())
        self.assertEqual(stale, [], f"these settings are no longer read by any code: {stale}")


if __name__ == "__main__":
    unittest.main()
