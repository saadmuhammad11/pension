"""Every third-party package the services import is pinned in deploy/requirements.txt (audit 6 Oct 2026, D3).

    python3 -m unittest tests.test_requirements_cover_imports -v

numpy, OpenCV and zxing-cpp were installed on the trial box by hand and never listed, so a fresh
server could not straighten a rotated page or read a QR code, and said nothing. This test maps the
imports in the code the release ships to distribution names and expects each to be pinned.
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: What deploy/build-release.sh ships.
SHIPPED = ("api", "rules", "pipeline", "extraction", "rag", "GP/backend/gpf")
REQUIREMENTS = ROOT / "deploy" / "requirements.txt"
#: Import name -> distribution name, where they differ.
DISTRIBUTION = {"PIL": "pillow", "cv2": "opencv-python-headless", "zxingcpp": "zxing-cpp", "jwt": "PyJWT",
                "multipart": "python-multipart", "sse_starlette": "sse-starlette", "yaml": "PyYAML"}
#: Our own top-level packages, importable because the release root is on sys.path.
OURS = {"api", "rules", "pipeline", "extraction", "rag", "gpf", "config", "tests"}


def third_party_imports() -> set[str]:
    found: set[str] = set()
    for folder in SHIPPED:
        for path in (ROOT / folder).rglob("*.py"):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    found.add(node.module.split(".")[0])
    return {m for m in found if m not in sys.stdlib_module_names and m not in OURS and not m.startswith("_")}


class Requirements(unittest.TestCase):
    def test_every_import_has_a_pin(self) -> None:
        pinned = {re.split(r"[\[=<>!~ ]", line.strip(), 1)[0].lower()
                  for line in REQUIREMENTS.read_text().splitlines() if line.strip() and not line.startswith("#")}
        needed = {DISTRIBUTION.get(m, m).lower() for m in third_party_imports()}
        missing = sorted(needed - pinned)
        self.assertEqual(missing, [], f"pin these in deploy/requirements.txt: {missing}")

    def test_the_pins_are_exact(self) -> None:
        for line in REQUIREMENTS.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                self.assertRegex(line.strip(), r"^[A-Za-z0-9_.\-]+(\[[a-z,]+\])?==\d", line)


if __name__ == "__main__":
    unittest.main()
