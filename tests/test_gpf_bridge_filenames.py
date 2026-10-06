"""File names the GP bridge sends to the module cannot break out of their multipart header (audit 6 Oct 2026, L7).

    python3 -m unittest tests.test_gpf_bridge_filenames -v

The bridge wrote an uploaded document's name straight into ``filename="..."``. A name with a
quote, a backslash or a line break ended the header early, and what followed was read by the
module as further headers or as another part.
"""
from __future__ import annotations

import email
import tempfile
import unittest
from email import policy
from pathlib import Path

from api import gpf_bridge


class PartFilenames(unittest.TestCase):
    def test_dangerous_characters_are_replaced_and_paths_reduced_to_a_name(self) -> None:
        self.assertEqual(gpf_bridge.part_filename('lpc.pdf'), 'lpc.pdf')
        self.assertEqual(gpf_bridge.part_filename('a"; name="officer"; x="b.pdf'), 'a_; name=_officer_; x=_b.pdf')
        self.assertEqual(gpf_bridge.part_filename('one\r\nContent-Type: text-html\r\n\r\n<script>'),
                         'one__Content-Type: text-html____<script>')
        self.assertEqual(gpf_bridge.part_filename('../../etc/passwd'), 'passwd')
        self.assertEqual(gpf_bridge.part_filename('back\\slash.pdf'), 'back_slash.pdf')
        self.assertEqual(gpf_bridge.part_filename(''), 'upload')
        self.assertEqual(len(gpf_bridge.part_filename('x' * 500 + '.pdf')), 200)

    def test_the_built_body_parses_as_exactly_the_parts_intended(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            evil = Path(d) / 'p1"; name="officer"; filename="dag.pdf'
            evil.write_bytes(b"%PDF-1.4 page one")
            body, ctype = gpf_bridge._multipart({"kind": "refundable", "officer": "ao"}, [evil])
        msg = email.message_from_bytes(f"Content-Type: {ctype}\r\n\r\n".encode() + body, policy=policy.HTTP)
        parts = list(msg.iter_parts())
        self.assertEqual([p.get_param("name", header="content-disposition") for p in parts],
                         ["kind", "officer", "files"])                 # no fourth part, no second "officer"
        self.assertEqual(parts[1].get_payload(decode=True), b"ao")     # the officer is still ours
        self.assertEqual(parts[2].get_filename(), 'p1_; name=_officer_; filename=_dag.pdf')
        self.assertEqual(parts[2].get_payload(decode=True), b"%PDF-1.4 page one")


if __name__ == "__main__":
    unittest.main()
