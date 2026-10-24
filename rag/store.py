"""RAG over the pension rules corpus. BUILD §2, §4.

"Qwen3-Embedding + Qwen3-Reranker: RAG over the rules corpus so every flag and figure carries
a citation."

Two stages, because they answer different questions. The embedder finds passages that are
*about* the query, cheaply, over the whole corpus. The reranker then reads each candidate
against the query as a pair and scores how well it actually answers it -- a cross-encoder,
which is far more accurate and far too slow to run over everything. Retrieve wide, rerank
narrow.

Why the index is local rather than in Qdrant
--------------------------------------------
BUILD §4 names Qdrant or pgvector, and that remains the production target. The Qdrant instance
on this cluster is shared with other projects, and this corpus is ~200 chunks -- brute-force
cosine over that is sub-millisecond and needs no server, no schema migration and no write
access to somebody else's store. The interface here is the part that matters; swapping the
backing store touches ``search`` and nothing else.

What this is *not* for
----------------------
Not for computing anything. A retrieved passage is evidence an officer can read, attached to a
figure the rules engine computed. BUILD §15 rule 1 is unchanged: if a rupee figure has a model
anywhere in its causal chain, the design is wrong. RAG supplies the citation, never the number.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "artifacts" / "rag" / "index.json"

#: Citations already retrieved, keyed by the corpus they came from. See :func:`cite_many`.
CITATIONS_PATH = ROOT / "artifacts" / "rag" / "citations.json"

#: How many retrievals to have in flight at once. The embedding and reranker services are
#: batching servers, so the limit is politeness to shared infrastructure rather than
#: throughput: a report asks for ~20 citations and eight at a time empties that queue in
#: three rounds without monopolising a GPU another project is also using.
CITE_WORKERS = int(os.environ.get("AGPB_CITE_WORKERS", "8"))

#: PENSION_EMBED_URL / PENSION_RERANK_URL point a deployment at its own model boxes (docs/DEPLOYMENT.md F4).
from extraction import envfile as _envfile

EMBED_ENDPOINT = _envfile.endpoint("PENSION_EMBED_URL", "embedding")
EMBED_MODEL = "qwen3-embedding-4b"
#: Spark-1, over the direct cable (was reasoning-host.internal, then reasoning-host.internal, until 1 Oct 2026).
RERANK_ENDPOINT = (_envfile.endpoint("PENSION_RERANK_URL", "rerank")
                   or os.environ.get("AGPB_RERANK_ENDPOINT") or "")
RERANK_MODEL = "qwen3-reranker-4b"

#: Qwen3-Embedding is instruction-aware on the query side, and omitting the instruction costs
#: 1-5% retrieval quality (model card). Documents are embedded verbatim, queries are not.
QUERY_INSTRUCTION = (
    "Instruct: Given a question about Pakistani government pension rules, retrieve the "
    "passage that states the governing rule\nQuery:"
)

#: Headings excluded from the corpus. BRAIN §13 is the golden test -- the EXPECTED output for
#: the one real case, including a table of the seven flags by id. Indexing it made retrieval
#: circular: F-3's citation came back as "§13.5 says F-3 is a flag", which is the answer key
#: citing itself, not the rule that makes the recovery a defect. Observed 2026-09-04, when
#: three of five flags cited §13.5 and only one cited a governing rule.
#:
#: §14 (the BLOCKING register) stays IN: it is authoritative about which rules are unresolved,
#: which is a fact about the rules and not a fact about this case.
#: A line that is nothing but bold text: a sub-heading in this corpus.
_SUBHEADING = re.compile(r"^\*\*([^*]{2,60})\*\*$")

EXCLUDED_HEADINGS = (
    re.compile(r"^13[.\s]"),                     # 13., 13.1 ... the golden test
    re.compile(r"golden test", re.I),
    re.compile(r"regression assertions", re.I),
)

#: The corpus. Only rules and procedure -- not the case file. Retrieving a passage from the
#: very case under review would let a document justify itself.
SOURCES = (
    "01-QWEN-DOMAIN-BRAIN-ag-punjab-pension.md",
    "agofficepension/research/01-pension-calculation-pakistan-research.md",
    "agofficepension/research/02-glossary-business-terms.md",
    "agofficepension/source-document/02-fd-reformed-pension-procedure.md",
    "agofficepension/source-document/03-forms-and-annexures.md",
    "agofficepension/source-document/04-checklists-quick-guide-relief-package.md",
)


class RagError(RuntimeError):
    """Retrieval failed. Never swallowed: a citation that silently vanishes is worse than none."""


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    source: str
    heading: str

    @property
    def citation(self) -> str:
        return f"{self.source} — {self.heading}" if self.heading else self.source


def _post(endpoint: str, payload: dict, timeout_s: int = 120) -> dict:
    """Every call to the embedding and rerank servers goes through here, so this is where they
    are timed. They were the one part of a run that cost model time and reported none of it
    (19 Oct 2026); a citation lookup that has gone slow was invisible beside vision and OCR."""
    import time
    from extraction.model_auth import model_headers
    from pipeline import timing
    role = "rerank" if "rerank" in endpoint else "embedding"
    started = time.time()
    req = urllib.request.Request(endpoint, json.dumps(payload).encode(), model_headers())
    try:
        body = json.loads(urllib.request.urlopen(req, timeout=timeout_s).read())
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode(errors="replace")
        timing.model_call(role, started=started, ended=time.time(), status="error",
                          detail={"http": exc.code})
        raise RagError(f"{endpoint} returned HTTP {exc.code}: {detail}") from exc
    except OSError as exc:
        timing.model_call(role, started=started, ended=time.time(), status="error",
                          detail={"error": str(exc)[:200]})
        raise RagError(f"cannot reach {endpoint} ({exc})") from exc
    timing.model_call(role, started=started, ended=time.time(),
                      detail={"n": len(payload.get("input") or payload.get("documents") or [])})
    return body


# -- corpus ------------------------------------------------------------------------------------

def chunk_markdown(path: Path, max_chars: int = 1100) -> list[Chunk]:
    """Split on markdown headings, keeping each chunk under one heading.

    Heading-bounded rather than fixed-window: a chunk that straddles "§9.4 Commutation" and
    "§9.5 Net pension" cites whichever heading it happened to start under, and a citation that
    points at the wrong rule is worse than a vague one.
    """
    text = path.read_text()
    chunks: list[Chunk] = []
    heading = base_heading = ""
    buf: list[str] = []
    n = 0

    def flush() -> None:
        nonlocal buf, n
        body = "\n".join(buf).strip()
        if len(body) > 40:
            chunks.append(Chunk(
                id=f"{path.name}#{len(chunks)}", text=body,
                source=path.name, heading=heading,
            ))
        buf, n = [], 0

    skipping = False
    for line in text.splitlines():
        if re.match(r"^#{1,4} ", line):
            flush()
            heading = base_heading = line.lstrip("# ").strip()
            skipping = any(pat.search(heading) for pat in EXCLUDED_HEADINGS)
            continue
        if skipping:
            continue
        # A bold-only line is a sub-heading in this corpus -- §8.4 runs "**Identity**",
        # "**Dates and service**", "**Money**", "**Family and entitlement**" under one
        # markdown heading. Splitting only on ## left those in one bucket, so a query about
        # recoveries retrieved the chunk that happened to hold the date checks. Carrying the
        # sub-heading into the citation also makes it say WHICH battery of checks it means.
        if _SUBHEADING.match(line.strip()):
            flush()
            sub = _SUBHEADING.match(line.strip()).group(1).strip()
            heading = f"{base_heading} — {sub}" if base_heading else sub
            continue
        if n + len(line) > max_chars:
            flush()
        buf.append(line)
        n += len(line) + 1
    flush()
    return chunks


#: A markdown table row.
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
#: The |---|---| separator under a table header.
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def build_corpus(root: Path | None = None) -> list[Chunk]:
    base = root or ROOT
    out: list[Chunk] = []
    for rel in SOURCES:
        path = base / rel
        if path.exists():
            # NOT split_table_rows(). Emitting each table row as its own chunk was tried on
            # 2026-09-04 and measurably regressed citation quality: four of five flags moved
            # from the right passage to the wrong one. A lone row like
            # "| Service history, pay fixation | Service book | ... |" carries almost no
            # distinguishing signal once separated from its table, and 368 near-identical
            # fragments crowded the reranker's 20-candidate window with noise, pushing out the
            # whole-section chunks that were answering correctly. The function is kept below,
            # documented, so the experiment is not repeated by someone reading the same
            # intuition. Sharpening §8.3 needs a different approach -- likely per-row chunks
            # that also carry the surrounding prose, or a hybrid that reranks sections first.
            out.extend(chunk_markdown(path))
    if not out:
        raise RagError(f"no corpus documents found under {base}")
    return out


# -- embedding ---------------------------------------------------------------------------------

def embed(texts: list[str], *, endpoint: str = EMBED_ENDPOINT, batch: int = 16) -> list[list[float]]:
    """Embed a list of texts. Returns L2-normalised vectors (the server normalises)."""
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch):
        body = _post(endpoint, {"model": EMBED_MODEL, "input": texts[i:i + batch]})
        vectors.extend(row["embedding"] for row in body["data"])
    return vectors


def build_index(out_path: Path | None = None, *, progress=None) -> dict:
    """Embed the corpus once and write it to disk."""
    path = out_path or INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks = build_corpus()
    if progress:
        progress(f"embedding {len(chunks)} chunks from {len(SOURCES)} documents")
    vectors = embed([c.text for c in chunks])
    payload = {
        "model": EMBED_MODEL,
        "dims": len(vectors[0]) if vectors else 0,
        "chunks": [asdict(c) for c in chunks],
        "vectors": vectors,
    }
    path.write_text(json.dumps(payload))
    if progress:
        progress(f"index written: {len(chunks)} chunks, {payload['dims']} dims -> {path}")
    return payload


_INDEX: dict | None = None


def load_index(path: Path | None = None) -> dict:
    global _INDEX
    if _INDEX is None:
        p = path or INDEX_PATH
        if not p.exists():
            raise RagError(f"no index at {p}; run `python3 -m rag.store build` first")
        _INDEX = json.loads(p.read_text())
    return _INDEX


# -- search ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    stage: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.chunk.citation,
            "source": self.chunk.source,
            "heading": self.chunk.heading,
            "text": self.chunk.text[:600],
            "score": round(self.score, 4),
            "scored_by": self.stage,
        }


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )


def search(
    query: str,
    *,
    top_k: int = 20,
    top_n: int = 3,
    rerank: bool = True,
    index: dict | None = None,
) -> list[Hit]:
    """Retrieve ``top_k`` by embedding, rerank, return the best ``top_n``.

    Falls back to the embedding ranking if the reranker is unreachable, and says so in each
    hit's ``stage``. A silently degraded citation would be indistinguishable from a good one.
    """
    idx = index or load_index()
    chunks = [Chunk(**c) for c in idx["chunks"]]
    qvec = embed([QUERY_INSTRUCTION + query])[0]

    scored = sorted(
        ((_cosine(qvec, v), c) for v, c in zip(idx["vectors"], chunks)),
        key=lambda pair: pair[0], reverse=True,
    )[:top_k]

    if not rerank:
        return [Hit(c, s, "embedding") for s, c in scored[:top_n]]

    try:
        body = _post(RERANK_ENDPOINT, {
            "model": RERANK_MODEL,
            "query": query,
            "documents": [c.text for _, c in scored],
        })
        ranked = sorted(body["results"], key=lambda r: -r["relevance_score"])[:top_n]
        return [
            Hit(scored[r["index"]][1], r["relevance_score"], "reranker")
            for r in ranked
        ]
    except RagError:
        return [Hit(c, s, "embedding (reranker unreachable)") for s, c in scored[:top_n]]


# -- citations: cached against the corpus, retrieved concurrently ------------------------------
#
# Two problems, one mechanism.
#
# REPRODUCIBILITY. SOP §8.5.1 requires that "the same papers and the same rule pack yield the
# same determination whenever recomputed", and §8.5.3 has an auditor recompute a determination
# and compare it against the record. The reranker is a model on a GPU and its score is not bit-
# stable: rebuilding one case's report moved a citation score from 0.9623 to 0.9627, so a
# recomputation differed from the record in a way that was not a difference. Worse, at top_n=1 a
# near-tie between two passages could have changed which passage was cited at all.
#
# COST. Retrieval was the whole cost of building a report. Measured on the golden case:
# 12.40s with citations, 0.00s without -- 17 sequential round trips, each an embedding call
# followed by a rerank of 20 candidates. Nothing else in the report took measurable time.
#
# The corpus is static and versioned (``build_index`` writes it; nothing else does), so a
# citation is a pure function of (corpus, query, top_n). Caching it against the corpus
# fingerprint makes a rebuild return the byte-identical citation -- which is exactly what §8.5
# asks for -- and makes it free. Rebuilding the index changes the fingerprint and the cache
# falls away with it, so a stale citation cannot outlive the corpus it came from.
#
# A DEGRADED citation is never cached. If the reranker is unreachable the report still builds
# and says so in ``scored_by`` (that is the visible-degradation contract in ``search``), but
# writing that to disk would make one outage the permanent answer, and the next reader could
# not tell. Misses are retried every time until they succeed.
#
# NOR IS A QUERY THAT CAME OFF A CASE. Callers must mark a query ``cacheable``, and the
# default is that nothing is written. A report falls back to a step's description or a flag's
# title where no curated question covers the rule, and those carry case facts: the first run
# of this cache wrote "Family pension for widow daughter of late Muhammad Bashir" and
# "CNIC copy at p.45 is not referred to anywhere in the case" into a shared file under
# ``artifacts/rag/``. A deceased man's name does not belong outside the case record
# (BRAIN §15.4, SOP §8.1), and a query naming one page of one bundle would never be reused
# anyway. Such queries are still de-duplicated and retrieved concurrently within the one
# build; they are simply not persisted.

_FINGERPRINT: str | None = None
_CITATIONS: dict[str, Any] | None = None


def index_fingerprint(path: Path | None = None) -> str:
    """A stable identity for the corpus citations were retrieved from.

    The whole index file, hashed: the chunk texts decide what can be cited and the vectors
    decide which candidates the reranker ever sees, so both belong in the identity. ~40 ms
    on the pilot hardware, once per process.
    """
    global _FINGERPRINT
    if _FINGERPRINT is None:
        p = path or INDEX_PATH
        if not p.exists():
            raise RagError(f"no index at {p}; run `python3 -m rag.store build` first")
        _FINGERPRINT = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return _FINGERPRINT


def unavailable(exc: BaseException) -> list[dict]:
    """The citation entry for a retrieval that could not be made.

    Kept here rather than at the call site so that every caller degrades the same way and an
    officer reading a report cannot mistake a failure for a weak match.
    """
    return [{"citation": f"retrieval unavailable ({type(exc).__name__})",
             "text": "", "score": 0.0, "scored_by": "none"}]


def _citation_store() -> dict[str, Any]:
    """The on-disk cache, discarded wholesale if it belongs to another corpus."""
    global _CITATIONS
    if _CITATIONS is None:
        fingerprint = index_fingerprint()
        loaded: dict[str, Any] = {}
        if CITATIONS_PATH.exists():
            try:
                loaded = json.loads(CITATIONS_PATH.read_text())
            except ValueError:
                loaded = {}
        if loaded.get("fingerprint") != fingerprint or not isinstance(
            loaded.get("entries"), dict
        ):
            loaded = {"fingerprint": fingerprint, "entries": {}}
        _CITATIONS = loaded
    return _CITATIONS


def _write_citations() -> None:
    """Best effort. A cache that cannot be written must not fail a report."""
    store = _citation_store()
    try:
        CITATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CITATIONS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(store, indent=1, ensure_ascii=False, sort_keys=True))
        os.replace(tmp, CITATIONS_PATH)
    except OSError:
        pass


def _key(query: str, top_n: int) -> str:
    return f"{top_n}|{query}"


def cite(query: str, top_n: int = 1, *, cacheable: bool = False) -> list[dict]:
    """Citations for a rule or finding, ready to attach to a report entry.

    Raises ``RagError`` when retrieval fails, as it always has -- callers that want to
    degrade visibly instead should use :func:`cite_many`, or wrap this and
    :func:`unavailable`.

    ``cacheable`` says the query is about the RULES and carries nothing from a case, so it
    may be written to the shared cache. It defaults to False; see the note above.
    """
    entries = _citation_store()["entries"]
    key = _key(query, top_n)
    if cacheable and key in entries:
        return copy.deepcopy(entries[key])
    hits = [h.to_dict() for h in search(query, top_n=top_n)]
    if cacheable and all(h["scored_by"] == "reranker" for h in hits):
        entries[key] = copy.deepcopy(hits)     # a copy; the caller mutates reports
        _write_citations()
    return hits


def cite_many(
    queries: list[str],
    top_n: int = 1,
    *,
    cacheable: Any = (),
    workers: int | None = None,
) -> dict[str, list[dict]]:
    """Citations for many queries at once. Cached hits are free; misses go out together.

    Returns one entry per DISTINCT query, so a caller with the same query against several
    steps attaches the same citation to each -- which a report has to do anyway, and which
    sequential retrieval did not guarantee.

    ``cacheable`` is the subset of ``queries`` that is about the rules rather than about a
    case, and so may be persisted. Anything outside it is retrieved and returned but never
    written to disk. Pass ``cacheable=queries`` where every query is rule text.

    A query that cannot be retrieved maps to :func:`unavailable` rather than raising: a
    report with one missing citation is worth building, and BRAIN §15.2 wants the gap
    visible rather than the build lost.
    """
    entries = _citation_store()["entries"]
    may_cache = set(cacheable)
    wanted = list(dict.fromkeys(queries))
    out: dict[str, list[dict]] = {}
    misses: list[str] = []
    for query in wanted:
        key = _key(query, top_n)
        if query in may_cache and key in entries:
            out[query] = copy.deepcopy(entries[key])
        else:
            misses.append(query)

    if misses:
        # Warm the index (and its fingerprint) on this thread. `load_index` memoises into a
        # module global, and having eight threads race to parse an 11 MB file is both slower
        # and a data race nobody needs.
        load_index()

        def one(query: str) -> tuple[str, list[dict], bool]:
            try:
                hits = [h.to_dict() for h in search(query, top_n=top_n)]
            except Exception as exc:                       # noqa: BLE001
                return query, unavailable(exc), False
            keep = query in may_cache and all(h["scored_by"] == "reranker" for h in hits)
            return query, hits, keep

        count = max(1, min(workers or CITE_WORKERS, len(misses)))
        wrote = False
        with ThreadPoolExecutor(max_workers=count) as pool:
            for query, hits, keep in pool.map(one, misses):
                out[query] = hits
                if keep:
                    # A copy into the cache, not the object handed back. A report is mutable
                    # and passes through redaction and the API after this; storing the same
                    # list would let an edit to one step's citation rewrite the cache, and
                    # every later case would inherit it.
                    entries[_key(query, top_n)] = copy.deepcopy(hits)
                    wrote = True
        if wrote:
            _write_citations()

    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_index(progress=lambda m: print(" ", m, flush=True))
    else:
        q = " ".join(sys.argv[1:]) or "How is gross pension calculated?"
        for h in search(q):
            print(f"\n  [{h.score:.4f} · {h.stage}] {h.chunk.citation}")
            print("   ", h.chunk.text[:260].replace("\n", " "))
