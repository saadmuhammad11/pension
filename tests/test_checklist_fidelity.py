"""Does the encoded checklist still say what the officer's sheet says?

    python3 -m unittest tests.test_checklist_fidelity -v

The requirement table in ``rules.checklist`` was transcribed from "Document Checklist.pdf",
the operational sheet in use at the AG office. A transcription is a thing that drifts: a line
edited by hand, a variant added to the wrong set, a tick read from the wrong column. Any of
those changes which documents a family is asked for, and none of them would fail a test that
only exercises the engine.

So this reads the tick matrix out of the PDF again, from the glyph positions, and compares it
cell by cell against what the code holds -- 25 documents against 11 columns, 275 cells. It is
the check that answers "is the system using the right checklist", as distinct from "is the
system applying its checklist correctly", which the engine tests cover.

Skips, rather than fails, where the sheet or poppler is unavailable: a missing source document
is not a broken checklist, and a test that cannot see its evidence must say so.
"""

from __future__ import annotations

import sys
from pathlib import Path

# So the file runs directly as well as under `-m unittest` from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import re
import subprocess
import unittest

SHEET = Path(__file__).resolve().parent.parent / "Document Checklist.pdf"

#: Tick-column x-positions, and the variant each belongs to, left to right across the sheet.
COLUMN_X = (501, 560, 617, 674, 733, 796, 858, 915, 978, 1039, 1102)
COLUMN_VARIANT = (
    "FRESH_SELF", "FRESH_INVALID", "REVISED", "DEATH_IN_SERVICE", "WIDOW",
    "UNMARRIED_CHILD", "WD_DAUGHTER", "DIVORCED_DAUGHTER", "DISABLED_CHILD_SIBLING",
    "PARENT", "SISTER",
)

#: Ticks the office decided after the sheet was printed (docs/pension-rules-decisions.md),
#: item number -> the columns added. The sheet itself is unchanged, so they are added to what
#: is read off it rather than silently expected of the glyphs.
#: S14 (user, 12 Oct 2026): the NADRA FRC is required on a self pension too, found or not found.
DECIDED_AFTER_THE_SHEET: dict[int, set[str]] = {
    6: {"FRESH_SELF", "FRESH_INVALID", "REVISED"},
}

_WORD = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>'
)


def _sheet_matrix() -> dict[int, set[str]]:
    """Item number -> the variants it is ticked for, read from the PDF's glyph positions."""
    xml = subprocess.run(
        ["pdftotext", "-bbox-layout", str(SHEET), "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    words = [
        (float(a), float(b), float(c), float(d), e) for a, b, c, d, e in _WORD.findall(xml)
    ]
    rows = sorted(
        (y0, int(t.rstrip(".")))
        for x0, y0, _x1, _y1, t in words
        if re.fullmatch(r"([1-9]|1[0-9]|2[0-5])\.", t) and x0 < 120
    )
    bands = [
        (n, y - 6, rows[i + 1][0] - 6 if i + 1 < len(rows) else float("inf"))
        for i, (y, n) in enumerate(rows)
    ]
    matrix: dict[int, set[str]] = {n: set() for n, _, _ in bands}
    for x0, y0, _x1, _y1, token in words:
        if token.strip() != "✓":
            continue
        col = min(range(len(COLUMN_X)), key=lambda i: abs(COLUMN_X[i] - x0))
        for n, lo, hi in bands:
            if lo <= y0 < hi:
                matrix[n].add(COLUMN_VARIANT[col])
                break
    return matrix


class ChecklistMatchesTheOfficersSheet(unittest.TestCase):
    """275 cells of the office sheet, against 275 cells of the requirement table."""

    @classmethod
    def setUpClass(cls):
        if not SHEET.exists():
            raise unittest.SkipTest(f"the officer's checklist is not at {SHEET}")
        try:
            cls.matrix = _sheet_matrix()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise unittest.SkipTest(f"cannot read the sheet: {exc}") from None
        # Item 22, the Nikah Nama, is a MEDIUM finding rather than a checklist line (office
        # decision, 24 Sep 2026). Its ticks are checked against the finding's scope below; the
        # rest of the sheet is still matched cell by cell.
        cls.item_22 = cls.matrix.pop(22, set())
        for item, columns in DECIDED_AFTER_THE_SHEET.items():
            cls.matrix[item] = cls.matrix.get(item, set()) | columns

    def test_item_22_lives_on_as_a_finding_on_the_same_columns(self):
        from rules.flags import NIKAH_NAMA_VARIANTS
        self.assertNotIn(22, self._encoded())
        self.assertEqual(set(NIKAH_NAMA_VARIANTS), self.item_22)

    def _encoded(self) -> dict[int, set[str]]:
        from rules.checklist import AG_OFFICE_2026
        return {int(r.id.split("-")[1]): set(r.applies_to) for r in AG_OFFICE_2026}

    def test_every_item_on_the_sheet_is_encoded(self):
        self.assertEqual(sorted(self._encoded()), sorted(self.matrix),
                         "the encoded item numbers differ from the sheet's")

    def test_every_cell_matches(self):
        """Cell by cell. A tick in the code that is not on the sheet asks for a document the
        office does not require; a tick on the sheet that is not in the code lets a case pass
        without one."""
        encoded = self._encoded()
        wrong: list[str] = []
        for item in sorted(self.matrix):
            on_sheet, in_code = self.matrix[item], encoded.get(item, set())
            for extra in sorted(in_code - on_sheet):
                wrong.append(f"AG-{item:02d} {extra}: in the code, NOT on the sheet")
            for missed in sorted(on_sheet - in_code):
                wrong.append(f"AG-{item:02d} {missed}: on the sheet, NOT in the code")
        self.assertEqual(wrong, [], "checklist has drifted from the sheet:\n  "
                                    + "\n  ".join(wrong))

    def test_the_tick_count_is_the_same(self):
        """A blunt total, so a mistake that cancels out across two cells still shows."""
        self.assertEqual(
            sum(len(v) for v in self.matrix.values()),
            sum(len(v) for v in self._encoded().values()),
        )

    def test_every_requirement_can_be_satisfied_by_a_real_document_type(self):
        """A line whose document type is not in the classifier's enum can never be met.

        This is how eight of these lines behaved before the enum was extended: the checklist
        asked for an affidavit, and the model had no token to name one with, so the case was
        returned for a document that was sitting in the bundle.
        """
        from extraction.schemas import DOCUMENT_TYPES
        from rules.checklist import AG_OFFICE_2026
        known = set(DOCUMENT_TYPES) | {"CNIC_DECEASED", "CNIC_CLAIMANT", "DEATH_CERTIFICATE",
                                       "OBITUARY"}
        unmeetable = [
            f"{r.id} -> {d}"
            for r in AG_OFFICE_2026
            for d in set(r.satisfied_by).union(
                *(r.satisfied_by_for or {}).values()) if d not in known
        ]
        self.assertEqual(unmeetable, [], "checklist lines no classifier output can satisfy")


if __name__ == "__main__":
    unittest.main(verbosity=2)
