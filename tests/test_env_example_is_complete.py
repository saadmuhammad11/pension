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
    # A setting name written as a literal anywhere it is passed into a call: os.environ["X"],
    # os.environ.get("X"), getenv("X"), and the project's own resolvers -- envfile.endpoint("X")
    # for the model endpoints, _workers("X") for the pool sizes.
    #
    # Named helpers were matched one by one until 20 Oct 2026, and the moment the endpoints
    # moved behind envfile.endpoint() the four *_URL settings read as STALE while still being
    # read. A detector that goes blind when code is refactored is worse than none: it says
    # "this setting no longer exists" about one that does.
    # The ways this code asks the environment for a setting, named explicitly. A looser rule
    # cannot work: record.document("PENSION_SLIP") is a document type and SOURCES =
    # ("PENSION_REGISTER", ...) a signatory source, and both look exactly like a settings read.
    #
    # The list is the point. Add a resolver and this test fails until it is named here, which
    # is the moment to decide whether the new setting belongs in the example. The four model
    # endpoints moved behind envfile.endpoint() on 20 Oct 2026 and silently read as STALE --
    # the detector said a live setting no longer existed, which is worse than not checking.
    READERS = ("environ", "getenv", "endpoint", "_workers", "_flag")
    pattern = re.compile(
        r"""(?:(?:%s)(?:\.get)?\s*[\[(]\s*)["']((?:PENSION|GPF)_[A-Z0-9_]+)["']"""
        % "|".join(READERS))
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
