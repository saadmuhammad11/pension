#!/usr/bin/env python3
"""Refuse a release tree that carries a real-looking CNIC, or a fixture that names a real-looking person.

    python3 deploy/check-release-pii.py <staged release dir>      # exit 1 and list hits

Called by deploy/build-release.sh after staging. Fixtures, tests and code comments use only
synthetic numbers (a district starting with 0, which NADRA never issues) or the handful of
documented placeholders below; anything else in CNIC shape is treated as a claimant's number and stops
the build. Searched: every text file in the tree, dashed (ddddd-ddddddd-d) and bare
(13 digits) forms. The bare form only counts when it stands alone, so the 13-digit
millisecond timestamps in the built bundle do not trip it.

Names (audit of 12 Oct 2026): the GP Fund fixtures shipped the subjects' real names after the
CNICs had been replaced. A fixture's quoted ``name`` value that looks like a person's name
must now announce itself as synthetic ("Subscriber A. Test", "Claimant B. Test"); see
``real_name`` for exactly what is and is not seen.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

#: Placeholders that are not anyone's number: the printed form's own template, the format
#: examples the prompts quote, and the zero-padded misreads the extraction code guards against.
ALLOWED = {
    "00000-0000000-0", "12345-1234567-1", "35201-1111111-1", "35201-1234567-1",
    "35202-0000000-0", "35202-1234567-1", "35203-0000000-0",
}

DASHED = re.compile(r"(?<!\d)(\d{5})-(\d{7})-(\d)(?!\d)")
BARE = re.compile(r"(?<![\d.])([1-7]\d{4})(\d{7})(\d)(?![\d.])")


#: A fixture's name must carry one of these (any case) to pass: the pseudonyms the fixtures use
#: are "Subscriber A. Test", "Claimant B. Test", "Father C. Test" and so on. The real names are
#: deliberately not written here; the check refuses whatever does not announce itself.
SYNTHETIC_TOKENS = ("test", "sample", "demo", "specimen", "synthetic", "placeholder")

#: ``"name": "..."`` in JSON and ``name: '...'`` in the JS fixtures, the value on one line.
NAME_VALUE = re.compile(r"""["']?\bname["']?\s*:\s*(["'])([^"'\n]{2,80})\1""")
#: What a person's name looks like to this check: two or more capitalised words, letters only,
#: an honorific allowed in front; or two or more words in capitals as SAP prints them.
PERSON = re.compile(r"^(?:(?:Mr|Mrs|Ms|Mst|Miss|Dr)\.?\s+)?(?:[A-Z][a-z]+(?:\s+|$)){2,}$|^(?:[A-Z]{2,}(?:\s+|$)){2,}$")


def synthetic(cnic: str) -> bool:
    digits = cnic.replace("-", "")
    # NADRA never issues a number starting with 0, so a leading zero marks a synthetic one.
    return (cnic in ALLOWED or digits.startswith("0")
            or len(digits) - len(digits.rstrip("0")) >= 6 or len(set(digits)) == 1)


def fixture_file(path: Path) -> bool:
    """The files the name check reads: anything under a ``fixtures`` or ``corpus`` folder."""
    return any(part in ("fixtures", "corpus") for part in path.parts)


def real_name(value: str) -> bool:
    """A quoted name value that looks like a person and does not say it is synthetic.

    Limits, so nobody mistakes a clean run for a guarantee: only values under a key spelled
    ``name`` are read, so a name in a page title, a subject line, a finding or under another key
    (``father``, ``heirs``) is not seen; only names of two or more words made of letters count, so
    a single given name passes; and a value that carries any token of SYNTHETIC_TOKENS passes
    whatever else it says. The check knows nothing about which names are real; it refuses every
    name that does not announce itself. A document title in Title Case under a ``name`` key would
    be refused too, and should then be renamed, not allow-listed.
    """
    value = value.strip()
    if any(token in value.lower() for token in SYNTHETIC_TOKENS):
        return False
    return bool(PERSON.match(value))


def scan(root: Path) -> list[str]:
    hits = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue                                   # images, fonts: not text
        if fixture_file(path):
            for m in NAME_VALUE.finditer(text):
                if real_name(m.group(2)):
                    line = text.count("\n", 0, m.start()) + 1
                    # The value itself is not printed: the log must not become the leak.
                    hits.append(f"{path.relative_to(root)}:{line}: a name that does not say it is synthetic")
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
        print("refusing: the release carries real-looking CNICs or names:", file=sys.stderr)
        print("\n".join(hits), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
