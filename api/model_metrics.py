"""What the model servers are doing, read from their own ``/metrics``.

Until 18 Oct 2026 the models ran on the same box as the pipeline (``infra/serve-qwen3-vl.sh``:
"WHERE IT RUNS: spark-3369"), so ``nvidia-smi`` on this host measured the thing doing the work.
Since the move to the Ascend NPU server the models are reached over the network, and a device
query here measures the wrong machine -- it reports nothing at all, which is worse than a wrong
number because it looks like an idle GPU rather than a missing one.

vLLM's own counters are reachable, mean the same thing on either vendor, and are what tuning
concurrency actually needs: how many requests are executing, how many are queued for scheduling
capacity, and how full the KV cache is. ``npu-smi``/``nvidia-smi`` would add the device's own
utilisation, but only from the box the device is in.

Read-only and best effort: a server that cannot be reached is reported unreachable, never as
zero. A zero that means "idle" and a zero that means "I could not ask" are different facts.
"""
from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from typing import Any

#: The roles this deployment serves, and the environment variable naming each one's endpoint.
ROLES: tuple[tuple[str, str], ...] = (
    ("vision", "PENSION_VISION_URL"),
    ("ocr", "PENSION_OCR_URL"),
    ("embedding", "PENSION_EMBED_URL"),
    ("rerank", "PENSION_RERANK_URL"),
)

#: gauge name -> key in the returned dict. Counters are cumulative since the server started.
_GAUGES = {
    "vllm:num_requests_running": "running",
    "vllm:num_requests_waiting": "waiting",
    "vllm:kv_cache_usage_perc": "kv_cache_pct",
    "vllm:num_preemptions_total": "preemptions",
    "vllm:prompt_tokens_total": "prompt_tokens",
    "vllm:generation_tokens_total": "generation_tokens",
}

_LINE = re.compile(r"^(?P<name>[a-zA-Z_:][\w:]*)(?P<labels>\{[^}]*\})?\s+(?P<value>[-\d.eE+]+)\s*$")
_REASON = re.compile(r'reason="([^"]*)"')
_MODEL = re.compile(r'model_name="([^"]*)"')


def metrics_url(endpoint: str) -> str:
    """``http://host:port/v1/chat/completions`` -> ``http://host:port/metrics``."""
    scheme, _, rest = endpoint.partition("://")
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}/metrics" if scheme else f"http://{host}/metrics"


def read(endpoint: str, *, timeout_s: float = 5.0) -> dict[str, Any]:
    """One server's counters. ``{"reachable": False, "error": ...}`` if it cannot be asked."""
    from extraction.model_auth import model_headers
    url = metrics_url(endpoint)
    try:
        req = urllib.request.Request(url, headers=model_headers())
        body = urllib.request.urlopen(req, timeout=timeout_s).read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"reachable": False, "url": url, "error": str(exc)[:160]}

    out: dict[str, Any] = {"reachable": True, "url": url, "waiting_capacity": None}
    for line in body.splitlines():
        if line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name, labels, raw = m["name"], m["labels"] or "", m["value"]
        try:
            value = float(raw)
        except ValueError:
            continue
        if name == "vllm:num_requests_waiting_by_reason":
            reason = _REASON.search(labels)
            if reason and reason.group(1) == "capacity":
                out["waiting_capacity"] = value
            continue
        key = _GAUGES.get(name)
        if key is not None and key not in out:
            out[key] = value
            if "model" not in out:
                served = _MODEL.search(labels)
                if served:
                    out["model"] = served.group(1)
    return out


def snapshot(timeout_s: float = 5.0) -> dict[str, dict]:
    """Every configured role, by name. Roles with no endpoint set are left out."""
    out = {}
    for role, var in ROLES:
        endpoint = os.environ.get(var)
        if endpoint:
            out[role] = read(endpoint, timeout_s=timeout_s)
    return out


def pressure(snap: dict[str, dict] | None = None) -> dict[str, Any]:
    """The two numbers that say whether concurrency may be raised, across all roles.

    ``waiting_capacity`` above zero means requests are queued inside vLLM for a scheduler slot:
    raising concurrency past that point buys queueing, not throughput, and with a client timeout
    it buys failures. ``preemptions`` above zero means the KV cache is evicting work already
    started.
    """
    snap = snapshot() if snap is None else snap
    live = [m for m in snap.values() if m.get("reachable")]
    return {
        "running": sum(m.get("running") or 0 for m in live),
        "waiting_capacity": sum(m.get("waiting_capacity") or 0 for m in live),
        "preemptions": sum(m.get("preemptions") or 0 for m in live),
        "kv_cache_pct_max": max((m.get("kv_cache_pct") or 0 for m in live), default=0.0),
        "unreachable": [r for r, m in snap.items() if not m.get("reachable")],
    }
