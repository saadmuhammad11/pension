#!/usr/bin/env python3
"""Refuse a release tree that carries a real-looking CNIC.

    python3 deploy/check-release-pii.py <staged release dir>      # exit 1 and list hits

Called by deploy/build-release.sh after staging. Fixtures, tests and code comments use only
synthetic numbers (a district starting with 0, which NADRA never issues) or the handful of
documented placeholders below; anything else in CNIC shape is treated as a claimant's number and stops
the build. Searched: every text file in the tree, dashed (ddddd-ddddddd-d) and bare
(13 digits) forms. The bare form only counts when it stands alone, so the 13-digit
millisecond timestamps in the built bundle do not trip it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

#: Placeholders that are not anyone's number: the printed form's own template, the format
#: examples the prompts quote, and the zero-padded misreads the extraction code guards against.
ALLOWED = {
    "00000-0000000-0", "12345-1234567-1", "35201-1111111-1", "35201-1234567-1",
    "35202-0000000-0", "35203-0000000-0",
}

DASHED = re.compile(r"(?<!\d)(\d{5})-(\d{7})-(\d)(?!\d)")
BARE = re.compile(r"(?<![\d.])([1-7]\d{4})(\d{7})(\d)(?![\d.])")


def synthetic(cnic: str) -> bool:
    digits = cnic.replace("-", "")
    # NADRA never issues a number starting with 0, so a leading zero marks a synthetic one.
    return (cnic in ALLOWED or digits.startswith("0")
            or len(digits) - len(digits.rstrip("0")) >= 6 or len(set(digits)) == 1)


def scan(root: Path) -> list[str]:
    hits = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue                                   # images, fonts: not text
        for rx in (DASHED, BARE):
            for m in rx.finditer(text):
                cnic = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                if rx is BARE and text[max(0, m.start() - 1):m.start()].isalpha():
                    continue                           # part of an identifier, not a number
                if not synthetic(cnic):
                    line = text.count("\n", 0, m.start()) + 1
                    hits.append(f"{path.relative_to(root)}:{line}: {cnic[:5]}-*******-{cnic[-1]}")
    return hits


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    hits = scan(Path(sys.argv[1]))
    if hits:
        print("refusing: the release carries real-looking CNICs:", file=sys.stderr)
        print("\n".join(hits), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
