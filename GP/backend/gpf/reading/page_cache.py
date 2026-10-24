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

def _reader_fingerprint() -> str:
    """A hash of the code that decides what a page reading contains.

    This was a hand-kept integer "bumped whenever what a page reading contains changes", with
    a second one beside it for pay slips. Both depend on somebody remembering, and a forgotten
    bump does not fail loudly -- it serves an old reading of a page for as long as the case
    lives, so a fix to the reader never reaches the claims that needed it. That is the whole
    reason reuse was switched off across the office on 23 Oct 2026, and with the version
    answering for itself it can be switched back on (24 Oct 2026).

    Err toward re-reading: a comment changed in any of these files costs one more read of the
    pages of one case, and a reading served from before a reader was fixed costs a claim.
    """
    import hashlib
    here = Path(__file__).resolve().parent
    reads_a_page = [here / "pipeline.py", here / "payslip_text.py", here / "recalc_text.py",
                    here / "schemas.py", here / "artefacts.py", here / "barcodes.py",
                    here.parent / "clients" / "model_client.py"]
    h = hashlib.sha256()
    for f in sorted(reads_a_page):
        h.update(f.name.encode())
        h.update(f.read_bytes() if f.is_file() else b"")
    return h.hexdigest()[:16]


#: What read the page. An entry read by any other version of the reader is read again.
VERSION = _reader_fingerprint()
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
        # The hand-kept payslip_v that stood here is subsumed: payslip_text.py is one of the
        # files the fingerprint is taken over, so a pay slip read before its LOAN/FUND block
        # was read has a different version by construction.
        if data.get("version") != VERSION:
            return None
        return data

    def put(self, key: str, *, artefact: str, confidence: float, fields: dict, codes: list) -> None:
        entry = {"version": VERSION, "artefact": artefact, "classify_confidence": confidence,
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
