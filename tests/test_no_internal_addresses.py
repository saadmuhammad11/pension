"""The repository names no real host on the office network (24 Oct 2026).

github.com/saadmuhammad11/pension is a PUBLIC repository. It carried the addresses of the
three model servers, two GPU boxes by name, the private subnets behind them, and -- in
docs/AUDIT-13OCT-2026.md -- a curl against a named host and port that once returned every
account and its password. The addresses are deliberately not written here: the first version
of this file listed them, in the docstring and again in its own self-check, and so published
on the public tip the very thing it exists to keep off it.

None of those addresses is routable from the internet and the route in that document is long
closed (it answers 404, and no account accepts the old password: both checked 24 Oct 2026).
What the disclosure gives away is the map: anyone who reaches the office network knows where
the model servers are, what speaks on each port, and what the boxes are called. A public
repository is not the place for it, and nothing in the code needs it -- every address the
running system uses comes from /etc/pension/pension.env, which is not in the tree.

    python3 -m pytest tests/test_no_internal_addresses.py -q
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".sql", ".txt", ".html", ".css",
        ".yml", ".yaml", ".sh", ".service", ".timer", ".conf", ".example"}

#: RFC 1918 and the link-local block: anything here is a real machine on somebody's network.
PRIVATE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|169\.254\.\d{1,3}\.\d{1,3})\b")

#: What may be written down. Loopback and the unspecified address name no machine; the
#: documentation ranges (RFC 5737) route nowhere by design and are what a test or an example
#: should use; 172.16.0.0/12 is the Docker default network, named as a CIDR in a firewall
#: rule rather than as a host. Nothing else: an address that is not one of these is somebody's.
ALLOWED = {"127.0.0.1", "0.0.0.0", "172.16.0.0"}
ALLOWED_PREFIXES = ("192.0.2.", "198.51.100.", "203.0.113.", "127.")

#: The office's own machines, by name -- assembled rather than written, for the reason above.
HOSTNAMES = ("spark-" + "46ef", "spark-" + "3369")


def tracked():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                         capture_output=True, text=True, check=True)
    for rel in out.stdout.split("\0"):
        p = ROOT / rel
        if rel and p.suffix.lower() in TEXT and p.is_file():
            yield rel, p


def allowed(addr: str) -> bool:
    return addr in ALLOWED or addr.startswith(ALLOWED_PREFIXES)


class TheTreeNamesNoRealHost(unittest.TestCase):

    def test_no_tracked_file_holds_a_private_address(self) -> None:
        hits = []
        for rel, path in tracked():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for m in PRIVATE.finditer(text):
                if not allowed(m.group(0)):
                    line = text.count("\n", 0, m.start()) + 1
                    hits.append(f"{rel}:{line}")           # the address itself is not printed
        self.assertEqual(hits, [], "a real internal address is tracked; use a .internal placeholder")

    def test_no_tracked_file_names_one_of_the_boxes(self) -> None:
        hits = [rel for rel, p in tracked()
                if any(h in p.read_text(encoding="utf-8", errors="ignore") for h in HOSTNAMES)]
        self.assertEqual(hits, [])

    def test_the_check_would_catch_one(self) -> None:
        """So this passing means something. The address is built at run time and is nobody's:
        written out, it would be the one thing this file forbids, and the check above -- which
        reads this file like any other -- would catch it."""
        addr = ".".join(("10", "28", "8", "143"))
        self.assertTrue(PRIVATE.search(f"http://{addr}:8000/v1"))
        self.assertFalse(allowed(addr))
        self.assertTrue(allowed("127.0.0.1"))
        self.assertTrue(allowed("203.0.113.20"))


if __name__ == "__main__":
    unittest.main()
