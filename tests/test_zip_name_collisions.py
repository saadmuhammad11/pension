"""Two zip members that land on one name both survive extraction (audit 6 Oct 2026, L6).

    python3 -m unittest tests.test_zip_name_collisions -v

Member names are rooted inside the extraction folder, so "a.pdf", "./a.pdf" and "../a.pdf" all
became a.pdf, and a zip may hold one name twice. The later member overwrote the earlier and a
page of the case went missing without a word. Each now gets its own file.
"""
from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from pipeline import bundle as bundle_mod


def _zip(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members:
            z.writestr(name, data)
    return buf.getvalue()


class Collisions(unittest.TestCase):
    def test_every_member_keeps_its_bytes(self) -> None:
        data = _zip([("a.pdf", b"first"), ("sub/../a.pdf", b"second"), ("./a.pdf", b"third"),
                     ("twice.pdf", b"one"), ("twice.pdf", b"two"), ("other.pdf", b"alone")])
        with tempfile.TemporaryDirectory() as d:
            out = bundle_mod._safe_extract(data, Path(d))
            written = {str(p.relative_to(Path(d).resolve())): p.read_bytes() for _, p in out}
        self.assertEqual(len(out), 6)
        self.assertEqual(set(written.values()), {b"first", b"second", b"third", b"one", b"two", b"alone"})
        # ".." is dropped from a member's path, so "sub/../a.pdf" lands in sub/; the two that land
        # on a.pdf itself are told apart by a counter, as are the two "twice.pdf".
        self.assertEqual(sorted(written), ["a (2).pdf", "a.pdf", "other.pdf", "sub/a.pdf", "twice (2).pdf", "twice.pdf"])
        # The manifest still carries the name the member had in the archive.
        self.assertEqual(sorted(name for name, _ in out),
                         ["./a.pdf", "a.pdf", "other.pdf", "sub/../a.pdf", "twice.pdf", "twice.pdf"])

    def test_a_folder_already_holding_the_name_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.pdf").write_bytes(b"already here")
            out = bundle_mod._safe_extract(_zip([("a.pdf", b"new")]), Path(d))
            self.assertEqual((Path(d) / "a.pdf").read_bytes(), b"already here")
            self.assertEqual(out[0][1].name, "a (2).pdf")


if __name__ == "__main__":
    unittest.main()
