# AG Punjab Pension Portal on Huawei Cloud Ascend (Sky47): Deployment Plan

| | |
|---|---|
| **Status** | Plan, 7 Oct 2026. Nothing deployed. Speeds are **estimates** until the benchmark in §6 runs. |
| **Quota** | 4 logical Ascend NPUs (ModelArts), 1 ARM instance, 2 TB OBS |
| **Companion** | `docs/DEPLOYMENT.md` (the general guide: security, nginx, systemd, backups, go-live checks). This file covers only what changes on Ascend. |
| **Not used** | The `Qwen3.5-27B-…-Reasoning-Distilled` model prepared in `/opt/modelarts-qwen`. The pension pipeline has no use for a text reasoning model. That project's tooling (OBS upload, image rebuild for UID 1000, IAM auth proxy) is reused below. |

---

## 1. What runs where

```
 Officers (AG office, 86 departments)
        │ HTTPS 443  (internet or VPN: this is now Option B, "public", in DEPLOYMENT.md)
        ▼
 ┌──────────────── ARM instance (Huawei Cloud, same region as ModelArts) ────────────────┐
 │ nginx → portal server :5184 → pension API :8110 ─┬─ SQLite, case files, scans       │
 │                                  GP Fund :8201 ───┤                                   │
 │                                                   └─ auth proxy (IAM token rotation) │
 └───────────────────────────────────────────┬──────────────────────────────────────────┘
                                             │ HTTPS, inside the region
                ┌────────────────────────────┼─────────────────────────────┐
                ▼                            ▼                             ▼
   ModelArts service: VISION     ModelArts service: OCR      ModelArts service: EMBEDDING
   Qwen3-VL-30B-A3B, BF16        PaddleOCR-VL 1.6            Qwen3-Embedding-4B
   2 NPUs, TP2 + expert par.     1 NPU                       (+ reranker, optional), 1 NPU
```

**Why the app runs in the cloud too:** one case sends about 150 page images (2–3 MB each) to the models,
300–450 MB per case. From Lahore over an office uplink that alone takes minutes per case. With the app in the
same region, only the uploaded PDF (typically 10–40 MB) crosses the internet.

**Consequence:** the portal becomes reachable over the internet or a VPN, so **every Option B requirement in
`DEPLOYMENT.md` applies**: written hosting approval, a public certificate, rate limits, penetration test.

## 2. Models on Ascend: what is confirmed and what is not

| Model | Pipeline role | vLLM-Ascend status (support matrix, 7 Oct 2026) | Plan |
|---|---|---|---|
| **Qwen3-VL-30B-A3B** | Classify pages, read fields, signatures | ✅ supported on A2/A3; BF16 ✅, W8A8 ✅, TP ✅. Official recipe: **TP2 + `--enable-expert-parallel`** on 64 GB cards | BF16 on 2 NPUs |
| **PaddleOCR-VL 1.6** | OCR (form check, pay pages, CNIC, attestation) | **PaddleOCR's own Ascend guide uses PaddleOCR-VL-1.6-0.9B (our version) and says it was "verified for accuracy and speed on the Huawei Ascend 910B"**, through the client + VLM-service path we use. Image `paddleocr-genai-vllm-server:latest-huawei-npu`; vLLM-Ascend also has an A2 recipe (`vllm-ascend:v0.23.0`, `--trust-remote-code`, `--enforce-eager` on CANN < 9). The support-matrix row ("300I DUO, BF16 ❌") was out of date. | Likely fine; still the first thing tested (§6), since "910B" may not cover every SKU |
| **Qwen3-Embedding-4B** | Rules search for citations | 🔵 experimental (A2/A3) | 1 NPU |
| **Qwen3-Reranker-4B** | Re-ranks citations | 🔵 experimental. **Optional:** `rag/store.py:312` falls back to embedding order when it is unreachable | Same NPU as embedding, or leave out |
| **qwen3.8-27b-fp8** (Spark-1 today; GP Fund only) | Rewords a GP Fund finding into one sentence | FP8, and not in the vLLM-Ascend support matrix. **Optional:** `GP/backend/gpf/clients/model_client.py:320-339` falls back to the rule's own wording on any error | Leave out, or point `GPF_VLLM_REASONING_MODEL` at the vision service |

**FP8 does not run on Ascend.** Today's vision model is the FP8 checkpoint (`qwen3-vl-30b-a3b-fp8`). On Ascend
use the original BF16 weights (`Qwen/Qwen3-VL-30B-A3B-Instruct`, ~62 GB). On 2 × 64 GB that leaves roughly
50 GB for KV cache, which is plenty for parallel page reads. W8A8 (msModelSlim) would fit one card, but the
only published W8A8 recipe for this model targets 950DT hardware. Treat it as later work, with its own accuracy
check. **Changing FP8 → BF16 changes the model's arithmetic. Re-run the golden cases before trusting
determinations (§6).**

**If PaddleOCR-VL does not run on 910B.** The OCR must stay a *different* model from the vision model:
`extraction/ocr.py` exists because "a model cannot be its own witness". Stage 3's page classification, which
selects the pension formula, is checked against independent OCR text. In order of preference:
1. Both official routes for PaddleOCR-VL-1.6: PaddleOCR's NPU image, then the vLLM-Ascend recipe (FP16 or
   `--enforce-eager` if that is the only blocker).
2. **DeepSeek-OCR-2** (has a vLLM-Ascend tutorial): a different maker and model, the same chat API. Change the
   model name, instruction and output clean-up (`_strip_layout_tokens`).
3. **PP-OCRv5** (classic detection + recognition, not a VLM): a completely different method; runs on Ascend via
   paddle-custom-npu **or on the ARM instance's CPU**, so it cannot fail for NPU reasons. Needs a small wrapper
   exposing the chat API. Weaker on stamps and handwriting, strong on printed form titles.
4. A small Qwen3-VL (2B/4B/8B) on its own card: supported, but the same family as the vision model, so only
   partly independent.
5. **Last resort:** the vision model itself. This loses the independent check and adds 10–25 long reads per case
   to the vision cards.

Any change of OCR model means re-validating the ~20 places that read OCR text (form titles, attestation marks,
CNIC cards, pay pages, recoveries, signatures) against the golden cases.

## 3. NPU layout

**Confirm the card type first:** `npu-smi info` on a ModelArts notebook or the service's logs. "4 logical
NPUs" may mean whole 910B cards (64 GB) or partitions. The layout below assumes 64 GB.

| NPUs | Service | Notes |
|---|---|---|
| 0–1 | **Vision**, TP2 + expert parallel | The official recipe. Not TP4: this model uses ~3B parameters per token, so splitting across 4 cards mostly adds communication, and it would leave no card for OCR or embedding. |
| 2 | **OCR** | PaddleOCR-VL is small; one card is generous |
| 3 | **Embedding** (+ reranker in the same container if wanted) | ModelArts allocates whole cards per service. Two vLLM processes in one custom image, or skip the reranker. |

**If the cards turn out to be 32 GB:** vision BF16 does not fit on 2. Either vision on all 4 at TP4, with OCR
and embedding on the vision model and CPU (the slowest option), or a W8A8 vision model on 2. Decide after the
benchmark.

**Vision launch** (from the vLLM-Ascend recipe, adapted). Image `quay.io/ascend/vllm-ascend:v0.23.0` (A2),
rebuilt for ModelArts' UID 1000 / GID 100 and `/home/mind/model` as script 30 already does:

```bash
export HCCL_BUFFSIZE=1024 HCCL_OP_EXPANSION_MODE=AIV PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
vllm serve /home/mind/model \
  --served-model-name qwen3-vl-30b-a3b \
  --host 0.0.0.0 --port 8080 \
  --tensor-parallel-size 2 --enable-expert-parallel \
  --max-model-len 16384 --max-num-seqs 16 --max-num-batched-tokens 16384 \
  --gpu-memory-utilization 0.9 \
  --limit-mm-per-prompt '{"image":2,"video":0}' \
  --mm-processor-kwargs '{"max_pixels":2408448,"min_pixels":3136}' \
  --enable-prefix-caching
```

**Vision on all 4 NPUs** (only if OCR moves to the vision model, the fallback in §2, and embedding runs on the
ARM instance's CPU). Dimensions on disk: 32 attention heads, 4 KV heads, 128 experts (8 per token), vision
encoder 16 heads, so any split up to 4 is valid.

| Layout | Flags | Per card (64 GB, util 0.9) | Use |
|---|---|---|---|
| A. One copy, TP4 | `--tensor-parallel-size 4 --enable-expert-parallel` | ~15.5 GB weights, ~42 GB KV | Fastest single read, but 96 card-to-card syncs per token (2 per layer × 48), and lower total throughput than B |
| **B. Two copies, DP2 × TP2** (recommended) | `--data-parallel-size 2 --tensor-parallel-size 2 --enable-expert-parallel` | ~31 GB weights, ~26 GB KV (~500k tokens per copy) | ~2× the throughput of one 2-card copy at the same per-read speed. Or two 2-card ModelArts services, with the client spreading calls across both |
| C. Four copies, TP1 | needs W8A8 (~31 GB) | BF16 (62 GB) does not fit | Highest throughput, but W8A8 for this model on 910B is untested. Later, with its own accuracy check |

Benchmark A and B with the golden cases at 1, 4, 8 and 16 concurrent requests before choosing.

`--max-model-len`, `--max-num-seqs`, the image limits and the pixel bounds match today's GB10 service
(`infra/serve-qwen3-vl.sh`), so the pipeline sees the same model behaviour. Keep the **warm-up** step
(`infra/warmup-vision.sh`): the first reads after a restart have returned empty amounts before.

## 4. Changes needed in the application

| # | Change | Why |
|---|---|---|
| A1 | **Model names from settings** (`PENSION_VISION_MODEL`, `PENSION_OCR_MODEL`, `PENSION_EMBED_MODEL`, `PENSION_RERANK_MODEL`, and GP Fund's `GPF_VLLM_*_MODEL`) | Names are constants in code (`extraction/client.py`, `extraction/ocr.py`, `rag/store.py`). The BF16 model should not be served under the name `…-fp8`. |
| A2 | **Point the endpoints at the auth proxy** (`PENSION_VISION_URL` etc. already exist) | ModelArts wants a 24-hour IAM token (`X-Auth-Token`). The proxy in `/opt/modelarts-qwen/webui/proxy.py` mints and rotates it, so the pipeline needs no IAM code. Bind the proxy to 127.0.0.1. |
| A3 | **Check request limits on ModelArts real-time services**: request timeout and body size | A vision double read takes up to ~50 s today, and each request carries a 2–3 MB page image (base64, so larger). If the platform's limits are lower, raise them in the service settings or lower the image size. |
| A4 | **Retries on 429/503** with backoff in the model clients | Managed endpoints throttle and scale; today a failed read can become an "unreadable page" finding (see `docs/STATUS.md`). |
| A5 | **Pipeline concurrency fixes** from the 6 Oct performance review | Stage 6 sends 2 requests where the server takes 16, and stage 4 reads in sequence. Worth more than any hardware change; see §5. |

## 5. Expected processing time (estimates until §6 measures them)

The pipeline's time is spent generating output text (1,300–2,200 tokens per read), so it follows memory
bandwidth: the GB10 has 273 GB/s and measured ~47 tokens/s per stream. A 910B card has roughly 1.6 TB/s, but
kernel overheads, TP communication and expert routing take a share, so expect **2–4× faster decoding per
stream**, not the bandwidth ratio.

| Setup | 43-page case | Cases in parallel |
|---|---|---|
| GB10 today | ~10 min | ~1 |
| GB10 + pipeline fixes (A5) | ~4–5 min | 1–2 |
| **4 Ascend NPUs, pipeline as it is** | **~4–6 min** | several |
| **4 Ascend NPUs + pipeline fixes** | **~1.5–3 min** | several |

Add 1–2 minutes for a large upload over the office connection (a 30 MB PDF at a few Mbit/s), and the first case
after a service restart is slower (warm-up).

## 6. Pilot and benchmark before anything else

1. **Card check:** `npu-smi info`. Record the model, memory and whether the cards are whole or partitioned.
2. **OCR feasibility (the risk):** deploy PaddleOCR-VL on 1 NPU and OCR 20 pages from the golden cases. Compare
   the text with the GB10's `ocr_text.json` for the same pages. Go / no-go, then pick the fallback in §2.
3. **Vision benchmark:** deploy vision TP2 and replay the golden cases' reads. Measure tokens/s per stream at 1,
   4, 8 and 16 concurrent requests, and time per case.
4. **Accuracy gate:** run the full golden set (`tests/test_golden_case.py` plus the trial cases in
   `artifacts/golden`) through the Ascend services. **Every determination, finding and checklist result must match
   the GB10's**, or each difference must be explained and accepted. BF16 vs FP8 and NPU vs GPU arithmetic can
   flip a borderline read.
5. **Write the results here,** replacing the estimates in §5.

**Use synthetic or fully masked cases for the pilot** until the hosting approval (step 7.1) is in writing: the
golden cases contain real claimant data.

## 7. Order of work

| Step | What | Who | Blocks |
|---|---|---|---|
| 7.1 | **Written approval to host pension data on Huawei Cloud**, in the Sky47 region (decision D1). Which region is it? Data-residency rules for CNICs and pension records apply. | AG Punjab / PITB | Everything with real data |
| 7.2 | Console: OBS bucket, AK/SK, SWR organisation (the blocker already listed for the other model) | Cloud admin | 7.4 |
| 7.3 | Download the weights to the ARM instance into `/data/weights`, upload to OBS: Qwen3-VL-30B-A3B-Instruct (BF16), PaddleOCR-VL 1.6, Qwen3-Embedding-4B, optionally Qwen3-Reranker-4B. Verify checksums. Record the model versions. | Team | 7.4 |
| 7.4 | Build one image per service from `vllm-ascend:v0.23.0` (UID 1000, `/home/mind/model`), push to SWR | Team | 7.5 |
| 7.5 | **Pilot (§6)**: OCR first, then vision, then the accuracy gate | Team | 7.6 |
| 7.6 | App changes A1–A5, tested on the GB10 against the Ascend endpoints | Developers | 7.7 |
| 7.7 | Deploy the app on the ARM instance per `DEPLOYMENT.md` (Option B), with the auth proxy on loopback | Team | 7.8 |
| 7.8 | Monitoring: the four services' health and latency, plus the app's `/api/health` (fix its open issues first, `docs/STATUS.md`) | Team | go-live |
| 7.9 | Go-live checklist (`DEPLOYMENT.md` §8) plus: pen test, restore test, golden set green on Ascend | All | — |

## 7a. The ARM instance as provided (7 Oct 2026)

Ubuntu 24.04, Python 3.12 (system, so PEP 668 applies and a venv is required), **4 vCPU / 8 GB RAM / 200 GB
disk, 131 GB free** (52 GB taken by the unused `Qwen3.5-27B` weights in `/data/weights`).

| Resource | Verdict | Action |
|---|---|---|
| aarch64, Ubuntu 24.04, Python 3.12 | ✅ The trial box (GB10) is aarch64 too; the pinned packages have ARM wheels | Use `/opt/pension/venv` as in DEPLOYMENT.md §3.3 |
| 4 vCPU | ⚠️ Fine for one case at a time (page rendering ~15–30 s for 43 pages); contention with several uploads | 8 vCPU for production |
| 8 GB RAM | ⚠️ Enough for the app (~1 GB) plus a LibreOffice conversion, **only with the unused Open WebUI stack stopped**. **Cannot host Qwen3-Embedding-4B on CPU** (~8 GB) | 16–32 GB for production. If vision takes all 4 NPUs, run without citations (the pipeline marks retrieval "unavailable") or switch to a 0.6B embedding model and rebuild `artifacts/rag/index.json` |
| 200 GB disk | ❌ Too small to be both the build host (weights ~80 GB staged, images 15–20 GB each) and the case store (50–100 MB per case) | Delete the unused 52 GB model once confirmed shelved; delete staged weights after the OBS upload; attach a **separate 500 GB–1 TB data disk (EVS)** for `/var/lib/pension`; back up and archive to OBS (2 TB) |

## 8. Questions for the cloud team

1. Are the 4 NPUs whole Ascend 910B cards (64 GB) or partitions? Which Atlas generation (A2 or A3)?
2. Which region is Sky47? Is it approved for government personal data?
3. ModelArts real-time service limits: request timeout, request body size, requests per second, and whether a
   service can hold one card while another holds two.
4. Can the ARM instance reach the ModelArts services privately (VPC endpoint) rather than over the public
   internet?
5. ARM instance size: provided as 4 vCPU / 8 GB / 200 GB (§7a). Can it be raised to 8 vCPU / 16–32 GB, with a
   separate 500 GB–1 TB data disk for the case files? Back up to OBS.
6. Is outbound internet allowed from the ARM instance (certificate renewal, security updates), or only through
   a proxy?
