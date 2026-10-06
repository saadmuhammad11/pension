"""The three services run confined (audit 6 Oct 2026, L10).

    python3 -m unittest tests.test_systemd_hardening -v

The units had the basics (own user, NoNewPrivileges, ProtectSystem=strict, ProtectHome,
PrivateTmp) and nothing else. They now also lose every capability, see no kernel tunables,
modules, logs or control groups, cannot change the clock or hostname, cannot create namespaces,
see only their own processes, speak only IP and Unix sockets, and run under the system-service
system-call set with the privileged and resource calls removed. Devices stay visible for
nvidia-smi, and W^X is not enforced because numpy and OpenCV load code pages at run time.
"""
from __future__ import annotations

import unittest
from pathlib import Path

UNITS = sorted((Path(__file__).resolve().parents[1] / "deploy" / "systemd").glob("pension-*.service"))

REQUIRED = {
    "User": "pension", "NoNewPrivileges": "true", "ProtectSystem": "strict", "ProtectHome": "true",
    "PrivateTmp": "true", "ProtectKernelTunables": "true", "ProtectKernelModules": "true",
    "ProtectKernelLogs": "true", "ProtectControlGroups": "true", "ProtectClock": "true",
    "ProtectHostname": "true", "ProtectProc": "invisible", "RestrictNamespaces": "true",
    "RestrictRealtime": "true", "RestrictSUIDSGID": "true", "LockPersonality": "true",
    "RestrictAddressFamilies": "AF_INET AF_INET6 AF_UNIX", "SystemCallArchitectures": "native",
    "CapabilityBoundingSet": "", "AmbientCapabilities": "", "UMask": "0077", "Restart": "always",
}


def _settings(unit: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in unit.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith(("#", "[")):
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), []).append(v.strip())
    return out


class Units(unittest.TestCase):
    def test_every_unit_carries_the_hardening(self) -> None:
        self.assertEqual(len(UNITS), 3)
        for unit in UNITS:
            settings = _settings(unit)
            for key, value in REQUIRED.items():
                self.assertIn(key, settings, f"{unit.name}: {key}")
                self.assertEqual(settings[key][-1], value, f"{unit.name}: {key}")
            filters = settings.get("SystemCallFilter", [])
            self.assertIn("@system-service", " ".join(filters), unit.name)
            self.assertTrue(any(v.startswith("~") for v in filters), unit.name)
            self.assertTrue(settings.get("ReadWritePaths") or settings.get("ReadOnlyPaths"), unit.name)


if __name__ == "__main__":
    unittest.main()
