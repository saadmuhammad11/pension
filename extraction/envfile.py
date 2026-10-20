"""The deployment's own settings, for code not started by systemd.

The services get ``/etc/pension/pension.env`` from their unit files. A shell does not, and the
model endpoints used to fall back to the DGX Spark's address -- ``192.168.1.1`` -- which stopped
existing when the models moved to the Ascend NPU server. Nothing said so: the fallback is a host
on a private range, so a call to it sits in SYN-SENT until the connect times out, and
``vision_judge`` allows 120s per call. An equivalence run spent eighteen minutes against that
address before anyone looked (20 Oct 2026).

Worse than the delay, it fails QUIETLY in the one place it matters: an unreachable orientation
judge reads as "unsure", so pages are left as scanned and the manifest records a reason that
looks like a considered decision.

So the file is read here, into the environment, for anything that was not started with it --
``tools/bench.py``, a pipeline module run by hand, a test harness. Values already set win: the
environment is the override, this is only the default.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

#: Where the deployment keeps its settings (deploy/pension.env.example).
ENV_FILE = Path(os.environ.get("PENSION_ENV_FILE") or "/etc/pension/pension.env")

_loaded = False
_lock = threading.Lock()


def load(path: Path | None = None) -> int:
    """Put any PENSION_*/GPF_* setting not already in the environment there. Returns how many.

    Silent on a missing or unreadable file: a developer box with no deployment is not an error,
    and the caller's own default still applies.
    """
    global _loaded
    with _lock:
        if _loaded and path is None:
            return 0
        target = path or ENV_FILE
        added = 0
        try:
            text = target.read_text()
        except OSError:
            if path is None:
                _loaded = True
            return 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not key.startswith(("PENSION_", "GPF_")) or key in os.environ:
                continue
            os.environ[key] = value
            added += 1
        if path is None:
            _loaded = True
        return added


def endpoint(variable: str, what: str) -> str:
    """The endpoint ``variable`` names, or "" where the deployment has not set one.

    No default address. The previous one outlived the machine it pointed at, and a wrong
    address that hangs is harder to diagnose than no address at all -- the callers below say
    plainly which setting is missing.
    """
    load()
    return os.environ.get(variable) or ""


def require(value: str, variable: str, what: str) -> str:
    """``value`` if set, else an error naming the setting and what it is for."""
    if value:
        return value
    raise RuntimeError(
        f"no {what} endpoint: set {variable} in {ENV_FILE} (or the environment). "
        f"There is deliberately no default -- the old one pointed at a machine that no longer exists."
    )
