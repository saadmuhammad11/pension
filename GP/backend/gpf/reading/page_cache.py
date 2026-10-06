"""Per-case page cache: a resubmitted claim reads only its new pages. 30 Sep 2026.

A GP Fund claim the Accountant General sends back comes back with the missing paper added and
every other page exactly as it was. Stages 3-4 are two vision-model calls per page, and each
page is read on its own (stage 5b is the only step that looks across pages), so a page's
reading is a function of the page alone. This cache keeps that reading, per case, keyed by
where the page came from -- the sha256 of the document it is in and its position there --
which the portal supplies (``api.gpf_bridge``). On the next round the same key is the same
page: its reading is taken from here, and only pages with a new key reach the model.
Assembly (stage 5b) and every rule run over the whole case, every round.

Scoped per case (``scope``, the portal's case id): the first submission of a case has an empty
scope and is read in full, exactly as before; nothing is ever shared between two cases.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from ..clients.model_client import ExtractedField
from .barcodes import DecodedCode

#: Bumped whenever what a page reading contains changes, so an old entry is read afresh.
VERSION = 1
_SAFE = re.compile(r"[^A-Za-z0-9_.:-]")


class PageCache:
    def __init__(self, root: Path, scope: str) -> None:
        self.dir = Path(root) / _SAFE.sub("_", scope)[:120]
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / (_SAFE.sub("_", key)[:200] + ".json")

    def get(self, key: str) -> Optional[dict]:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
        except ValueError:
            return None
        if data.get("version") != VERSION:
            return None
        # A pay slip read before its LOAN/FUND block was read (30 Sep 2026) is read again.
        if data.get("artefact") == "SAP_PAYSLIP" and data.get("payslip_v", 0) < 2:
            return None
        return data

    def put(self, key: str, *, artefact: str, confidence: float, fields: dict, codes: list) -> None:
        entry = {"version": VERSION, "payslip_v": 2, "artefact": artefact, "classify_confidence": confidence,
                 "fields": {k: asdict(v) for k, v in fields.items()},
                 "codes": [asdict(c) for c in codes]}
        tmp = self._path(key).with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False, default=str))
        tmp.replace(self._path(key))


def fields_from(entry: dict, page: int) -> dict[str, ExtractedField]:
    """The cached fields, under the page number they have in this round's upload."""
    return {k: ExtractedField(**{**v, "page": page if v.get("page") is not None else None})
            for k, v in (entry.get("fields") or {}).items()}


def codes_from(entry: dict, page: int) -> list[DecodedCode]:
    return [DecodedCode(**{**c, "page": page}) for c in entry.get("codes") or []]
