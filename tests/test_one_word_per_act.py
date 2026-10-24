"""The machine examines; the officer verifies (24 Oct 2026).

One word was doing two jobs, and they met on one screen. The pension portal called the AI
reading of a case "Verify case with AI". Inside the GP Fund frame on that same case screen,
"Verify" is the officer's own act -- the button on a finding that records having checked it
against the paper, with a reason, under their name. A Senior Auditor therefore met "Verify"
meaning "run the machine again" and "Verify" meaning "I have checked this myself", a few
centimetres apart.

The two products did not even agree with each other: GP Fund already said "Examine with AI"
for exactly what pension called "Verify case with AI". The words were unified on 24 Oct 2026
onto "verify", which was the wrong direction for the reason above, and then onto "examine",
which is this.

So, the glossary:

    examine   what the AI does to a case -- reads every document and reports findings
    verify    what an OFFICER does to a finding -- checks it against the paper and says so
    approve / return / reject    what an officer does to a CASE

    python3 -m pytest tests/test_one_word_per_act.py -q
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "portals" / "src" / "shared"
MODULE_JS = ROOT / "GP" / "backend" / "web" / "js" / "app.js"

#: Phrases that would mean the machine's act is being called verification again.
MACHINE_AS_VERIFY = (
    "Verify case with AI", "Verify the case again", "verify the case with AI",
    "Verification started", "Verification in progress", "Verification incomplete",
    "is verifying the case", "verified with AI",
)


def ui_strings(path: Path) -> list[str]:
    """Quoted literals, with // and /* */ comments removed: what a person can read."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    return re.findall(r"'([^'\n]{2,200})'|\"([^\"\n]{2,200})\"", text) and [
        a or b for a, b in re.findall(r"'([^'\n]{2,200})'|\"([^\"\n]{2,200})\"", text)]


class ThePortalDoesNotCallTheMachinesActVerification(unittest.TestCase):

    def test_no_screen_says_it(self) -> None:
        offenders = []
        for f in sorted(SRC.rglob("*.ts")) + sorted(SRC.rglob("*.tsx")):
            if "__tests__" in f.parts:
                continue
            for s in ui_strings(f):
                for bad in MACHINE_AS_VERIFY:
                    if bad.lower() in s.lower():
                        offenders.append(f"{f.relative_to(ROOT)}: {s[:70]}")
        self.assertEqual(offenders, [], "the machine examines; see this file's glossary")

    def test_both_products_use_the_same_words_for_it(self) -> None:
        """Pension said "Verify case with AI" where GP Fund said "Examine with AI"."""
        cases = (SRC / "api" / "cases.ts").read_text(encoding="utf-8")
        verbs = re.findall(r"verify: '([^']+)'", cases)
        self.assertTrue(verbs, "no product verb found at all")
        self.assertEqual(len(set(verbs)), 1, f"the products disagree: {verbs}")
        self.assertEqual(verbs[0], "Examine with AI")


class TheOfficersOwnWordIsLeftAlone(unittest.TestCase):

    def test_the_module_still_calls_the_officers_act_verifying(self) -> None:
        js = MODULE_JS.read_text(encoding="utf-8")
        self.assertIn("'Verify'", js)
        self.assertIn("What did you verify, and against what?", js)

    def test_the_portal_keeps_it_where_an_officer_is_the_subject(self) -> None:
        """"Verified by the Senior Auditor" is a person's act and stays a person's word."""
        timeline = (SRC / "components" / "HistoryTimeline.tsx").read_text(encoding="utf-8")
        self.assertIn("Verified by the Senior Auditor", timeline)


if __name__ == "__main__":
    unittest.main()
