"""The key the model servers ask for (audit 6 Oct 2026, item 7).

The vision (:8011), OCR (:8012) and embedding (:8093) servers listen on 127.0.0.1 and refuse a
request without ``Authorization: Bearer <key>`` (vLLM ``--api-key``, set from VLLM_API_KEY in
/etc/pension/models.env). Every pipeline request carries PENSION_MODEL_API_KEY, the same value.
Read on each call, so a changed environment takes effect without an import-time snapshot.
"""
from __future__ import annotations

import os


def model_headers() -> dict[str, str]:
    """JSON content type, plus the bearer key when one is configured."""
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("PENSION_MODEL_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers
