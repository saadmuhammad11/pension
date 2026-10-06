"""Model client interface — the seam where the vLLM-served models plug in.

Spec §0: "The language model never decides anything. It reads." So the model
layer produces only schema-constrained extraction (and, at the very end,
observation *wording*). The rules engine never calls a model.

In Phase 1 the case facts are hand-transcribed fixtures, so `StubModelClient`
is all the engine needs. When the DGX Spark is online, `VllmModelClient` calls
the OpenAI-compatible endpoints vLLM exposes for each model in spec §2 — and
because both implement the same `ModelClient` protocol, nothing downstream
changes (the same pattern the spec uses for SAP in §6.2).

Confidence gating (§4.5): any extraction below its field threshold is returned
with `needs_human=True` and must be confirmed by a person; the model never
guesses an account number, CNIC, date or amount.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable

# Confidence thresholds by field class (spec §4.5). Effective-dated config.
THRESHOLDS = {
    "financial": 0.95,   # account numbers, CNIC, amounts, dates
    "identity": 0.85,
    "structural": 0.90,  # signature present, stamp present
    "narrative": 0.70,
    "service_book": 0.98,  # any Service Book field in v1
}


@dataclass
class ExtractedField:
    value: Any
    confidence: float
    page: Optional[int] = None
    bbox: Optional[list] = None
    field_class: str = "narrative"

    @property
    def threshold(self) -> float:
        return THRESHOLDS.get(self.field_class, THRESHOLDS["narrative"])

    @property
    def needs_human(self) -> bool:
        return self.confidence < self.threshold


@runtime_checkable
class ModelClient(Protocol):
    """The four model roles of the reading/wording pipeline (spec §2, §3)."""

    def classify_document(self, image_ref: str) -> ExtractedField:
        """Stage 3: artefact_type per page, enum-constrained, by layout not filename."""

    def extract_fields(self, image_ref: str, artefact_type: str) -> dict[str, ExtractedField]:
        """Stage 4: per-artefact schema; every field carries confidence, page, bbox."""

    def phrase_observation(self, result: dict) -> str:
        """Stage 12: one sentence for a result the RULES already decided. Wording only."""

    def health(self) -> dict:
        ...


class StubModelClient:
    """Deterministic stand-in used in Phase 1 (no models, fixtures supply facts).

    Reading methods raise clearly: in Phase 1 facts come from fixtures, not the
    model. `phrase_observation` just echoes the rule's own finding, so a build
    with no model produces identical observations to a build with one — which is
    exactly the model-swap-invariance the spec makes a test (§0, §17).
    """

    name = "stub"

    def classify_document(self, image_ref: str) -> ExtractedField:  # pragma: no cover
        raise NotImplementedError(
            "Phase 1 uses hand-transcribed fixtures; document classification arrives "
            "with the vision pipeline (build phase 6).")

    def extract_fields(self, image_ref: str, artefact_type: str) -> dict[str, ExtractedField]:  # pragma: no cover
        raise NotImplementedError(
            "Phase 1 uses hand-transcribed fixtures; field extraction arrives with the "
            "vision pipeline (build phase 6).")

    def phrase_observation(self, result: dict) -> str:
        return result.get("finding", "")

    def health(self) -> dict:
        return {"ok": True, "mode": "stub", "note": "No models; fixtures supply facts."}


class VllmModelClient:
    """Talks to vLLM's OpenAI-compatible HTTP API, one endpoint PER ROLE (§1, §2).

    The roles can live on different hosts — in the AG deployment the vision, OCR
    and embedding models run on Spark-2 and the reasoning model on Spark-1. Each
    role therefore carries its own base URL and model id. Constructing this
    object does NOT open a connection, so it is safe to import with no Spark up.
    """

    name = "vllm"

    def __init__(self, base_url: Optional[str] = None, *, api_key: str = "EMPTY",
                 vision_model: str = "Qwen3-VL", ocr_model: str = "PaddleOCR-VL",
                 reasoning_model: str = "Qwen3.5", embed_model: str = "",
                 vision_url: Optional[str] = None, ocr_url: Optional[str] = None,
                 reasoning_url: Optional[str] = None, embed_url: Optional[str] = None,
                 timeout: float = 180.0):
        b = base_url.rstrip("/") if base_url else None
        self.base_url = b
        self.api_key = api_key
        self.timeout = timeout
        self.vision_url = (vision_url or b or "").rstrip("/")
        self.ocr_url = (ocr_url or b or "").rstrip("/")
        self.reasoning_url = (reasoning_url or b or "").rstrip("/")
        self.embed_url = (embed_url or b or "").rstrip("/")
        self.vision_model = vision_model
        self.ocr_model = ocr_model
        self.reasoning_model = reasoning_model
        self.embed_model = embed_model
        self.available_models: dict[str, list[str]] = {}

    # ── discovery ─────────────────────────────────────────────────────────────
    @staticmethod
    def _list_models(base_url: str, api_key: str, timeout: float) -> list[str]:
        import urllib.request
        req = urllib.request.Request(base_url.rstrip("/") + "/v1/models",
                                     headers={"Authorization": "Bearer " + api_key})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return [m["id"] for m in json.loads(r.read().decode("utf-8")).get("data", [])]

    @classmethod
    def from_server(cls, base_url: str, *, api_key: str = "EMPTY", timeout: float = 180.0) -> "VllmModelClient":
        """Single-endpoint: one server that may serve one or more models."""
        return cls.from_discovery([base_url], api_key=api_key, timeout=timeout)

    @classmethod
    def from_discovery(cls, base_urls: list[str], *, api_key: str = "EMPTY",
                       timeout: float = 180.0) -> "VllmModelClient":
        """Probe several endpoints and assign each model to its role by name.

        vision  = a *-vl* / vision / omni model that is not the OCR model;
        ocr     = a paddle/ocr model;
        embed   = an embedding model;
        reason  = a remaining text model. A single multimodal model can fill both
        the vision and reasoning roles when nothing more specific is served.
        """
        catalog: list[tuple[str, str]] = []   # (url, model_id)
        per_url: dict[str, list[str]] = {}
        for url in base_urls:
            try:
                ids = cls._list_models(url, api_key, timeout)
            except Exception:
                ids = []
            per_url[url.rstrip("/")] = ids
            for i in ids:
                catalog.append((url.rstrip("/"), i))
        if not catalog:
            raise RuntimeError(f"No models served by any of: {base_urls}")

        def find(pred):
            for url, mid in catalog:
                if pred(mid.lower()):
                    return url, mid
            return None

        vision = find(lambda s: ("vl" in s or "vision" in s or "omni" in s) and "ocr" not in s and "paddle" not in s)
        ocr = find(lambda s: "paddle" in s or "ocr" in s)
        embed = find(lambda s: "embed" in s)
        used = {x[1] for x in (vision, ocr, embed) if x}
        reason = find(lambda s: True) if not vision else None
        reason = next(((u, m) for (u, m) in catalog if m not in used and "embed" not in m.lower()
                       and "ocr" not in m.lower() and "paddle" not in m.lower()), None)
        # sensible fallbacks so a role is never left unbound
        vision = vision or reason or catalog[0]
        reason = reason or vision
        inst = cls(api_key=api_key, timeout=timeout,
                   vision_url=vision[0], vision_model=vision[1],
                   reasoning_url=reason[0], reasoning_model=reason[1],
                   ocr_url=(ocr[0] if ocr else None), ocr_model=(ocr[1] if ocr else "PaddleOCR-VL"),
                   embed_url=(embed[0] if embed else None), embed_model=(embed[1] if embed else ""))
        inst.available_models = per_url
        return inst

    def _chat(self, url: str, model: str, messages: list, **kw) -> dict:
        """POST /v1/chat/completions to a specific role endpoint. urllib only."""
        import urllib.request
        payload = {"model": model, "messages": messages, **kw}
        req = urllib.request.Request(
            url + "/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key},
            method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    @staticmethod
    def _image_url(image_ref: str) -> str:
        """Inline a local image as a data URL for the OpenAI vision message format."""
        if image_ref.startswith(("http://", "https://", "data:")):
            return image_ref
        import base64
        import mimetypes
        data = open(image_ref, "rb").read()
        mt = mimetypes.guess_type(image_ref)[0] or "image/jpeg"
        return f"data:{mt};base64," + base64.b64encode(data).decode()

    def classify_document(self, image_ref: str) -> ExtractedField:  # pragma: no cover - needs Spark
        from ..reading.artefacts import ALL_TYPES, ARTEFACT_LEGEND
        schema = {"type": "object", "properties": {
            "artefact_type": {"type": "string", "enum": ALL_TYPES},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
            "required": ["artefact_type", "confidence"], "additionalProperties": False}
        legend = "\n".join(f"- {a.value}: {desc}" for a, desc in ARTEFACT_LEGEND.items())
        system = (
            "You classify one scanned page of a Pakistani Government Provident Fund (GP Fund) case "
            "from the Accountant General, Punjab. Choose the ONE artefact type that matches the page's "
            "PRIMARY printed form or content, by layout and content, never by file name.\n"
            "Rules:\n"
            "- Office diary stamps, receipt marks, tokens or handwritten annotations on a department "
            "form do NOT change its type. Classify by the underlying form.\n"
            "- Use SECTION_WORKING only when the page is WHOLLY the AG office's own computation sheet.\n"
            "- If genuinely none fit, use UNKNOWN.\n\n"
            "Artefact types:\n" + legend)
        msg = [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": "Classify this page. Return the artefact_type and your confidence."},
                {"type": "image_url", "image_url": {"url": self._image_url(image_ref)}}]},
        ]
        out = self._chat(self.vision_url, self.vision_model, msg, temperature=0, max_tokens=64,
                         response_format={"type": "json_schema",
                                          "json_schema": {"name": "classify", "schema": schema}})
        data = json.loads(out["choices"][0]["message"]["content"])
        return ExtractedField(value=data["artefact_type"], confidence=float(data.get("confidence", 0)),
                              field_class="structural")

    def extract_fields(self, image_ref: str, artefact_type: str) -> dict[str, ExtractedField]:  # pragma: no cover
        from ..reading.artefacts import Artefact
        from ..reading.schemas import field_map, to_json_schema
        art = Artefact(artefact_type)
        schema = to_json_schema(art)
        fm = field_map(art)
        fielddesc = "\n".join(f"- {s.name}: {s.desc or s.field_class}" for s in fm.values())
        msg = [
            {"role": "system", "content":
             f"You read one scanned '{artefact_type}' page from a GP Fund case (AG Punjab) and extract "
             "the requested fields. For each field return value, confidence (0-1), page and bbox. Read "
             "stamps and handwriting. Never guess an account number, CNIC, date or amount: if unsure, "
             "return the field with a low confidence (the value may be null). Fields:\n" + fielddesc},
            {"role": "user", "content": [
                {"type": "text", "text": f"Extract the fields for this {artefact_type}."},
                {"type": "image_url", "image_url": {"url": self._image_url(image_ref)}}]},
        ]
        out = self._chat(self.vision_url, self.vision_model, msg, temperature=0, max_tokens=1400,
                         response_format={"type": "json_schema",
                                          "json_schema": {"name": "extract", "schema": schema}})
        data = json.loads(out["choices"][0]["message"]["content"])
        res: dict[str, ExtractedField] = {}
        for name, spec in fm.items():
            d = data.get(name)
            if d is None or d.get("value") is None:
                continue
            res[name] = ExtractedField(value=d.get("value"), confidence=float(d.get("confidence", 0)),
                                       page=d.get("page"), bbox=d.get("bbox"), field_class=spec.field_class)
        # The pay slip's LOAN/FUND block is a small printed table the whole-page vision read passes
        # over: on PC-2026-000050 it returned no balance for "GPF#: 255,534.00". OCR reads printed
        # digits exactly, so the block is read from the page's OCR text too, and its figures are
        # preferred where it finds them (30 Sep 2026).
        if art is Artefact.SAP_PAYSLIP:
            from ..reading.payslip_text import fund_block
            try:
                fund = fund_block(self.ocr_text(image_ref))
            except Exception:                              # noqa: BLE001 -- the vision read stands
                fund = {}
            for name in ("gpf_balance", "gpf_loan_balance"):
                if fund.get(name) is not None:
                    res[name] = ExtractedField(value=fund[name], confidence=0.97,
                                               field_class=fm[name].field_class)
        # The re-calculation report is a ledger TABLE — read its rows in a second call.
        if art is Artefact.SAP_GPF_RECALC_REPORT:
            rows, conf = self._extract_recalc_rows(image_ref)
            if rows:
                res["rows"] = ExtractedField(value=rows, confidence=conf, field_class="financial")
        return res

    def ocr_text(self, image_ref: str) -> str:  # pragma: no cover - needs the OCR service
        """The page's printed text, from the OCR model (PaddleOCR-VL): characters, not conclusions."""
        msg = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": self._image_url(image_ref)}},
            {"type": "text", "text": "Transcribe all printed text on this page, in reading order. "
                                     "Output the text only, with no commentary and no description of the layout."}]}]
        out = self._chat(self.ocr_url, self.ocr_model, msg, temperature=0, max_tokens=2048)
        return out["choices"][0]["message"]["content"] or ""

    def _extract_recalc_rows(self, image_ref: str):  # pragma: no cover - needs Spark
        """Read the GPF re-calculation ledger table as rows (spec §4.2, §12)."""
        from ..reading.schemas import recalc_rows_json_schema
        schema = recalc_rows_json_schema()
        msg = [
            {"role": "system", "content":
             "Read the SAP 'GPF Final Re-calculation Report' ledger table. Return EVERY yearly row with "
             "its columns: start, end (as dd.mm.yyyy), opening, subscription, adjustments, tempAdvance, "
             "recTempAdvance, permanentAdvance, interest, closing. Numbers only (no commas, no 'Rs'). A "
             "trailing minus sign means a debit — return it as a negative number. Use 0 for blank cells. "
             "Also return an overall confidence (0-1)."},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract all ledger rows as JSON."},
                {"type": "image_url", "image_url": {"url": self._image_url(image_ref)}}]},
        ]
        out = self._chat(self.vision_url, self.vision_model, msg, temperature=0, max_tokens=4000,
                         response_format={"type": "json_schema",
                                          "json_schema": {"name": "recalc", "schema": schema}})
        data = json.loads(out["choices"][0]["message"]["content"])
        return data.get("rows", []), float(data.get("confidence", 0.8))

    def phrase_observation(self, result: dict) -> str:
        """Reasoning model wording — constrained so it cannot change the decision.

        It may only rephrase; if anything goes wrong we fall back to the rule's
        own finding so the observation set is never altered by the model.
        """
        try:
            msg = [
                {"role": "system",
                 "content": ("Rewrite the audit finding in one clear sentence: what is wrong, which clause, "
                             "what cures it. Do not add, remove, invent, soften or change any fact, code, "
                             "amount or rule reference. Output the sentence only.")},
                {"role": "user", "content": json.dumps({
                    "finding": result.get("finding"), "remedy": result.get("remedy"),
                    "code": result.get("code"), "ref": result.get("ref")})},
            ]
            out = self._chat(self.reasoning_url, self.reasoning_model, msg, temperature=0, max_tokens=160)
            return out["choices"][0]["message"]["content"].strip() or result.get("finding", "")
        except Exception:
            return result.get("finding", "")

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - needs Spark
        """Embed texts via the embedding endpoint (rule-citation retrieval, §2)."""
        if not self.embed_url:
            raise RuntimeError("No embedding endpoint configured.")
        import urllib.request
        payload = {"model": self.embed_model, "input": texts}
        req = urllib.request.Request(
            self.embed_url + "/v1/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key},
            method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [d["embedding"] for d in data["data"]]

    def health(self) -> dict:
        roles = {"vision": (self.vision_url, self.vision_model),
                 "ocr": (self.ocr_url, self.ocr_model),
                 "reasoning": (self.reasoning_url, self.reasoning_model),
                 "embed": (self.embed_url, self.embed_model)}
        reachable = {}
        for url in {u for (u, _) in roles.values() if u}:
            try:
                reachable[url] = self._list_models(url, self.api_key, min(self.timeout, 8))
            except Exception as e:  # pragma: no cover
                reachable[url] = {"error": str(e)}
        return {"ok": True, "mode": "vllm",
                "roles": {r: {"url": u, "model": m} for r, (u, m) in roles.items() if u},
                "reachable": reachable}


class ScriptedModelClient:
    """Deterministic reading model for tests/demo: canned outputs keyed by image_ref.

    Lets the reading pipeline run end-to-end with no Spark, so the whole
    reading -> facts -> rules seam is exercised in CI.
    """

    name = "scripted"

    def __init__(self, classifications: dict[str, ExtractedField],
                 extractions: dict[str, dict[str, ExtractedField]]):
        self._c = classifications
        self._e = extractions

    def classify_document(self, image_ref: str) -> ExtractedField:
        if image_ref not in self._c:
            raise KeyError(f"No scripted classification for {image_ref!r}")
        return self._c[image_ref]

    def extract_fields(self, image_ref: str, artefact_type: str) -> dict[str, ExtractedField]:
        return dict(self._e.get(image_ref, {}))

    def phrase_observation(self, result: dict) -> str:
        return result.get("finding", "")

    def health(self) -> dict:
        return {"ok": True, "mode": "scripted", "pages": len(self._c)}
