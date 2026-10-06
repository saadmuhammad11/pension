"""Every model unit either listens on loopback or refuses to start without the key (audit 6 Oct 2026, N7).

    python3 -m unittest tests.test_model_units_gated -v

Item 7 of the audit closed the vision, OCR and embedding units; the reranker and guard units
still listened on every address with no key. The guard is unused and now on loopback. The
reranker serves this box from Spark-1 over the LAN, so it cannot be loopback: it carries the same
key gate as the others and vLLM refuses requests without the key.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

INFRA = Path(__file__).resolve().parents[1] / "infra"


def _host(text: str) -> str | None:
    """The address the unit's server binds: from the unit, or from the launcher script it runs."""
    m = re.search(r"--host\s+(\S+)", text)
    if m:
        return m.group(1).strip('"')
    launcher = re.search(r"^ExecStart=\S*/infra/(serve-[\w.-]+\.sh)", text, re.M)
    if launcher:
        script = (INFRA / launcher.group(1)).read_text()
        default = re.search(r'^HOST="\$\{HOST:-([^}]+)\}"', script, re.M)
        return default.group(1) if default else None
    return None


class ModelUnits(unittest.TestCase):
    def test_every_unit_is_loopback_or_key_gated(self) -> None:
        units = sorted(INFRA.glob("*.service"))
        self.assertGreaterEqual(len(units), 5)
        for unit in units:
            text = unit.read_text()
            host = _host(text)
            if host == "127.0.0.1":
                continue
            # Not loopback: the key must be loaded and checked before the server starts.
            self.assertIn("EnvironmentFile=/etc/pension/models.env", text, unit.name)
            gates = [l for l in text.splitlines() if l.startswith("ExecStartPre=") and "VLLM_API_KEY" in l]
            self.assertTrue(gates, f"{unit.name} listens on {host} with no key gate")
            self.assertIn("CHANGE_ME", gates[0], unit.name)       # the placeholder is refused too

    def test_the_guard_is_on_loopback_and_the_reranker_is_gated(self) -> None:
        self.assertEqual(_host((INFRA / "qwen3guard.service").read_text()), "127.0.0.1")
        reranker = (INFRA / "qwen3-reranker.service").read_text()
        self.assertNotEqual(_host(reranker), "127.0.0.1")                # called from this box over the LAN
        self.assertIn("VLLM_API_KEY", reranker)


if __name__ == "__main__":
    unittest.main()
