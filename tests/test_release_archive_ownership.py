"""A release archive carries root-owned files, not the builder's uid (audit 6 Oct 2026, D1).

    python3 -m unittest tests.test_release_archive_ownership -v

The tarball was written with the staging files' own owner, uid 1000 on the trial box. Unpacked by
root with ids kept, /opt/pension/current belonged to whatever login account had that uid on the
server. The archive is now written with every entry owned by root (0:0); the service user reads it.
"""
from __future__ import annotations

import os
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "build-release.sh"


class ArchiveOwnership(unittest.TestCase):
    def _tar_line(self) -> str:
        lines = [l for l in SCRIPT.read_text().splitlines() if re.match(r"\s*tar czf ", l)]
        self.assertEqual(len(lines), 1, "one tar command packs the release")
        return lines[0]

    def test_the_script_asks_for_root_ownership(self) -> None:
        line = self._tar_line()
        for flag in ("--owner=0", "--group=0", "--numeric-owner"):
            self.assertIn(flag, line)

    def test_the_tar_flags_the_script_uses_produce_root_owned_entries(self) -> None:
        """Run the script's own tar invocation on a stand-in stage and read the result back."""
        line = self._tar_line()
        flags = re.findall(r"--\S+", line)
        with tempfile.TemporaryDirectory() as d:
            stage = Path(d) / "stage"
            (stage / "pension-0.0.0" / "api").mkdir(parents=True)
            (stage / "pension-0.0.0" / "api" / "server.py").write_text("print('x')\n")
            out = Path(d) / "pension-0.0.0.tgz"
            subprocess.run(["tar", "czf", str(out), *flags, "-C", str(stage), "pension-0.0.0"], check=True)
            with tarfile.open(out) as tf:
                members = tf.getmembers()
        self.assertTrue(members)
        for m in members:
            self.assertEqual((m.uid, m.gid, m.uname, m.gname), (0, 0, "", ""), m.name)
        self.assertNotEqual(os.getuid(), 0, "this check means something only when not run as root")


if __name__ == "__main__":
    unittest.main()
