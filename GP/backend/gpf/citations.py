"""Rule-citation retrieval (spec §2, §3 stage 11).

A small searchable corpus of the governing texts — the circular's checklists
(A.1-A.4) and rejection reasons (B1/B2), the office clarifications (R1-R15), and
the advance-limit clauses — so the module can cite the exact clause behind an
observation. Retrieval uses the embedding model (`qwen3-embedding-4b`) with
cosine similarity; when no embedding endpoint is available it falls back to a
deterministic keyword search, so the feature works offline too.

(The spec pairs the embedder with a reranker; only the embedder is deployed, so
cosine ranking is used. A reranker would refine the top-k — a drop-in later.)
"""
from __future__ import annotations

import math
import re
from typing import Optional

from .reference import R_RULES
from .rules_family import ADV_LIMITS

# ── the citable corpus ────────────────────────────────────────────────────────
_CIRCULAR = [
    # A.1 Advances
    ("A1-i", "Checklist A.1 (advances)", "Original sanction of authority as per GP Fund Rules."),
    ("A1-ii", "Checklist A.1 (advances)", "Attested copy of CNIC of the subscriber."),
    ("A1-iii", "Checklist A.1 (advances)", "Change Form-05 for refundable advance / Change Form-06 for non-refundable advance, duly signed by DDO and the subscriber."),
    # A.2 Final payment
    ("A2-i", "Checklist A.2 (final payment)", "Covering / forwarding letter by the head of the department."),
    ("A2-ii", "Checklist A.2 (final payment)", "Properly filled G.P.F. Form 10 signed by the DDO / competent authority and by the subscriber."),
    ("A2-iii", "Checklist A.2 (final payment)", "Attested copy of retirement / resignation / dismissal / removal from service or obituary notification."),
    ("A2-iv", "Checklist A.2 (final payment)", "Attested copy of CNIC of the subscriber; in a death case attested copies of all legal heirs."),
    ("A2-v", "Checklist A.2 (final payment)", "Change Form-06 duly signed by the DDO and the subscriber."),
    ("A2-vi", "Checklist A.2 (final payment)", "In a death case, original affidavit for lawful widow and attested succession certificate for more than one widow or legal heirs other than family."),
    ("A2-vii", "Checklist A.2 (final payment)", "Original Service Book for a non-gazetted subscriber."),
    # A.3 Balance transfer
    ("A3-i", "Checklist A.3 (balance transfer)", "Completely filled proforma for transfer of GP Fund balances with name, father name, designation, old GP Fund account no., GP Fund account no. in DAO, personnel no. and period of posting."),
    ("A3-ii", "Checklist A.3 (balance transfer)", "Forwarding letter by the head of department of the subscriber and from the respective DAO."),
    # A.4 Missing credits
    ("A4-i", "Checklist A.4 (missing credits)", "Covering / forwarding letter by the authority."),
    ("A4-ii", "Checklist A.4 (missing credits)", "Period of the missing months."),
    ("A4-iii", "Checklist A.4 (missing credits)", "Manual deduction certificate issued by the DDO with attested copies of manual bills and acquaintance roll, for the non-gazetted period."),
    ("A4-iv", "Checklist A.4 (missing credits)", "Manual deduction certificate issued by the A.G. Office, for the gazetted period."),
    ("A4-v", "Checklist A.4 (missing credits)", "Challan forms duly verified from the Treasury Office with the covering letter issued by the department."),
    # B.1 rejection reasons (refundable)
    ("B1-i", "Rejection reason B.1 (refundable)", "Insufficient balance in the GP Fund account."),
    ("B1-ii", "Rejection reason B.1 (refundable)", "Original sanction not found attached and/or not signed by the competent authority as per delegation of power."),
    ("B1-iii", "Rejection reason B.1 (refundable)", "QR-coded sanction not verified by the department (for Health, Education and Police departments)."),
    ("B1-iv", "Rejection reason B.1 (refundable)", "Respective rule and relevant reason for advance not mentioned on the sanction."),
    ("B1-v", "Rejection reason B.1 (refundable)", "Change Form-05 not found attached with the GP Fund case."),
    ("B1-vi", "Rejection reason B.1 (refundable)", "Signature of the sanctioning authority does not match the specimen signature provided."),
    ("B1-vii", "Rejection reason B.1 (refundable)", "Change form not signed by the respective Drawing and Disbursing Officer (DDO) and the subscriber."),
    # B.2 rejection reasons (non-refundable & final payment)
    ("B2-i", "Rejection reason B.2 (non-refundable / final)", "Incomplete GP Fund Form-10: missing signature and old and new GP Fund account no. / personnel number and date of retirement."),
    ("B2-ii", "Rejection reason B.2 (non-refundable / final)", "Mismatch in the subscription period with the service mentioned in the Service Book and service statement (for final payment)."),
    ("B2-iii", "Rejection reason B.2 (non-refundable / final)", "Change Form-06 for final payment and non-refundable advance not attached."),
    ("B2-iv", "Rejection reason B.2 (non-refundable / final)", "Signature of the sanctioning authority does not match the specimen provided."),
    ("B2-v", "Rejection reason B.2 (non-refundable / final)", "Change form not signed by the respective Drawing and Disbursing Officer (DDO) and the subscriber."),
    ("B2-vi", "Rejection reason B.2 (non-refundable / final)", "Missing credits and adjustments found in the re-calculation sheet of the applicant."),
    ("B2-vii", "Rejection reason B.2 (non-refundable / final)", "Old GP Fund A/c No. / manual not mentioned in the change form."),
    ("B2-viii", "Rejection reason B.2 (non-refundable / final)", "Requisite entries not found in the Service Book (date of retirement, order of retirement and leave account)."),
    ("B2-ix", "Rejection reason B.2 (non-refundable / final)", "Respective rule not quoted on the sanction (for non-refundable advance)."),
    # Directions
    ("C-i", "Direction C(i)", "Maintain a GP Fund Payment Register instead of noting pay orders on GP Fund ledger cards, with immediate effect."),
    ("para-2", "Circular para 2 (single instance)", "All relevant observations must be pointed out in a single instance in the claim rejection form signed by the Accounts Officer."),
    ("para-3", "Circular para 3 (second return)", "If a case is to be returned a second time, the Deputy Accountant General (Funds) / DAO I reviews and signs it."),
]


def _build_corpus() -> list[dict]:
    items = [{"id": cid, "source": src, "text": txt} for cid, src, txt in _CIRCULAR]
    for code, text in R_RULES:
        items.append({"id": code, "source": "Office clarification (15-09-2026)", "text": text})
    for clause, L in ADV_LIMITS.items():
        months = f", {L['months']} months' pay" if L.get("months") else ""
        combine = f" ({L['combine']})" if L.get("combine") else ""
        items.append({"id": clause, "source": "GP Fund Rules — advance limit",
                      "text": f"{L['src']}: {L['label']} — limit {L['pct']}% of balance{months}{combine}."})
    return items


CITATIONS: list[dict] = _build_corpus()


# ── retrieval ─────────────────────────────────────────────────────────────────
def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


_STOP = {"the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "by", "is", "not",
         "with", "as", "be", "no", "per", "its", "this", "that", "from"}


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP and len(w) > 1}


def keyword_search(query: str, k: int = 5) -> list[dict]:
    q = _tokens(query)
    scored = []
    for it in CITATIONS:
        overlap = q & _tokens(it["text"] + " " + it["id"])
        if overlap:
            scored.append((len(overlap) / max(len(q), 1), it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{**it, "score": round(s, 3)} for s, it in scored[:k]]


class CitationIndex:
    """Embeds the citable corpus once, then answers cosine-similarity queries."""

    def __init__(self):
        self._vectors: Optional[list[list[float]]] = None

    def build(self, embed_fn) -> None:
        self._vectors = embed_fn([it["text"] for it in CITATIONS])

    @property
    def ready(self) -> bool:
        return self._vectors is not None

    def search(self, query: str, embed_fn, k: int = 5) -> list[dict]:
        if self._vectors is None:
            self.build(embed_fn)
        qv = embed_fn([query])[0]
        scored = sorted(
            ((_cosine(qv, v), it) for v, it in zip(self._vectors, CITATIONS)),
            key=lambda x: x[0], reverse=True)
        return [{**it, "score": round(s, 4)} for s, it in scored[:k]]


_INDEX = CitationIndex()


def search(query: str, k: int, model_client) -> dict:
    """Cite the clauses most relevant to a query, via embeddings or keyword fallback."""
    embed_fn = getattr(model_client, "embed", None)
    can_embed = callable(embed_fn) and getattr(model_client, "embed_url", "")
    if can_embed:
        try:
            return {"method": "embedding", "results": _INDEX.search(query, embed_fn, k)}
        except Exception as e:  # fall back rather than fail
            return {"method": "keyword", "note": f"embedding unavailable ({e})",
                    "results": keyword_search(query, k)}
    return {"method": "keyword", "results": keyword_search(query, k)}
