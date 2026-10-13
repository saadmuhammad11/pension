# Ascend (Huawei NPU) deployment readiness — pension model serving

**Status: DRAFT, 13 Oct 2026. Nothing here has run on real Ascend hardware yet.** These are the
scripts and the plan to stand the three model servers up on the "Sky 47" Ascend NPU servers the
moment they arrive. Treat every command as *to be confirmed on the box* — the three smoke tests in
§5 are what tell you it actually works, not the install finishing.

This mirrors the CUDA serving in `infra/` (same served-model-names, same ports, same structured
output) so **the pension app and GP Fund need no code change** — they talk to the same URLs and
model names (`extraction/client.py`, `extraction/ocr.py`, `PENSION_EMBED_URL`).

---

## 1. What we serve, and the one hard blocker

| Role | Served name (keep identical) | Port | CUDA now | Ascend weights to use |
|---|---|---:|---|---|
| Vision | `qwen3-vl-30b-a3b-fp8` | 8011 | NVIDIA FP8 | **BF16** `Qwen/Qwen3-VL-30B-A3B-Instruct`, or `…-w8a8-mxfp8` (950DT only) |
| OCR | `paddleocr-vl-1.6` | 8012 | BF16 | `PaddleOCR-VL` (BF16) |
| Embedding | `qwen3-embedding-4b` | 8093 | BF16 | `Qwen3-Embedding-4B` (BF16) |

> **The blocker:** our NVIDIA-FP8 vision checkpoint (`/models/qwen3-vl-30b-a3b-fp8`) **cannot load
> on Ascend.** Ascend has no NVIDIA FP8. Use BF16, or re-quantize to Ascend's own W8A8 (MXFP8) with
> ModelSlim. Keep the FP8 weights, but they are not used here.

The **served name stays `qwen3-vl-30b-a3b-fp8`** even though the weights are BF16 — it is only a
label, and keeping it means `DEFAULT_MODEL` in `extraction/client.py:28` and the app are untouched.

---

## 2. Decide the path from the chip (ask the vendor)

Get from whoever supplies the servers:
1. Ascend chip — **910B / Atlas 800 A2 / A3**, or **950DT**, or older?
2. **HBM per card** (64G or 96G) and **cards per server**.
3. Is **CANN** + `torch-npu` pre-installed, and which CANN version?
4. How many of the 47 are inference nodes?

| Chip / HBM | Vision path | TP | `--quantization` |
|---|---|---:|---|
| 64G — 910B / Atlas 800 A2/A3 | **BF16** (safest, most-tested) | 2 | none |
| 96G — Ascend 950DT | W8A8-**MXFP8** (more throughput) or BF16 | 8 (mxfp8) / 2 (bf16) | `ascend` for mxfp8 |
| older 910 / 310 | **confirm Qwen3-VL support with vendor first** | ? | ? |

Set the chosen values in `/etc/pension/models.env` (see §4); the scripts default to the BF16 / 64G
path.

---

## 3. Install order (on the Ascend box, once)

Do **not** reuse `/home/tmc/vllm_env` — that is a CUDA venv. Build a fresh NPU env.

```bash
# 0. Confirm the NPU stack the vendor left: driver + firmware + CANN
npu-smi info                      # cards visible, HBM, health
cat /usr/local/Ascend/version.info 2>/dev/null   # CANN version

# 1. Fresh venv on the matching Python (CANN/torch-npu dictate it)
python3 -m venv /home/tmc/vllm_ascend_env && source /home/tmc/vllm_ascend_env/bin/activate

# 2. torch + torch-npu + vllm-ascend, versions matched to the CANN the vendor installed.
#    Follow the vllm-ascend v0.23.0 installation page for the exact wheels/container for THIS CANN.
#    Prefer the vendor's NGC-equivalent Ascend container if one is provided.
#    https://docs.vllm.ai/projects/ascend/en/v0.23.0/installation.html

# 3. Verify the engine imports and sees the NPUs before touching models
python3 -c "import torch, torch_npu; print(torch_npu.npu.is_available(), torch_npu.npu.device_count())"
```

Air-gapped: build the env and pull the wheels/container on a connected machine first, then copy —
same discipline as the model weights (`HF_HUB_OFFLINE=1` is already set in the scripts).

---

## 4. Stage the weights and env (can be done NOW, before hardware)

On a connected box, download and copy to the Ascend box under `/models/`:

```
/models/qwen3-vl-30b-a3b-bf16/            <- Qwen/Qwen3-VL-30B-A3B-Instruct   (BF16)
/models/qwen3-vl-30b-a3b-w8a8-mxfp8/      <- only if 950DT (Eco-Tech/…-w8a8-mxfp8)
/models/paddleocr-vl-1.6/                 <- PaddleOCR-VL
/models/qwen3-embedding-4b/               <- Qwen3-Embedding-4B
```

`/etc/pension/models.env` (copy from `deploy/ascend/models.env.example`):

```
VLLM_API_KEY=<openssl rand -base64 48>
ASCEND_TP=2                 # 2 for BF16/64G, 8 for 950DT mxfp8
ASCEND_DEVICES=0,1          # which NPUs (comma list); must match ASCEND_TP count
VISION_QUANT=bf16           # bf16 | w8a8
```

---

## 5. Smoke tests — THE PART THAT PROVES IT (run each the minute its server is up)

These three are the real risks on Ascend, not the install:

1. **Vision, two images per prompt** (a prescribed form spans 2 pages — D-I is 19–20). The Ascend
   tutorials ship `--limit-mm-per-prompt image=1`; our scripts set **2**. If the server rejects it
   or a 2-page request fails, that is a blocker — raise it before running any case.
   ```bash
   curl -s http://127.0.0.1:8011/v1/chat/completions -H "Authorization: Bearer $VLLM_API_KEY" \
     -H 'content-type: application/json' -d @deploy/ascend/smoke/vision-2images.json | head
   ```
2. **Structured output** on a real schema. vllm-ascend supports the `xgrammar` backend on the v1
   engine, but it is **not documented as confirmed with quantized weights** — so test it against an
   actual identify/extract schema, not a toy one.
   ```bash
   python3 -m tools.smoke_structured_output --base http://127.0.0.1:8011/v1   # (write against extraction/schemas.py)
   ```
3. **Embedding returns vectors** of the expected dimension from `/v1/embeddings` on :8093.

Only after all three pass is the stack trustworthy. Then run `tools/bench.py` and compare findings
with `tools/bench_compare.py` against the CUDA baseline — numbers may differ by model randomness
(see memory `perf-pipeline-branch`), so compare **findings**, not just wall time.

---

## 6. Go-live checklist

- [ ] Vendor spec known; path chosen in `models.env` (§2).
- [ ] NPU env built, `torch_npu.npu.is_available()` true, device count = cards (§3).
- [ ] BF16 (not FP8) weights staged under `/models/` (§4).
- [ ] Three servers up on 8011 / 8012 / 8093 with the **same served-model-names** as CUDA.
- [ ] Three smoke tests pass (§5) — especially **image=2** and **structured output**.
- [ ] `./run.sh` health shows vision/ocr/embedding reachable; one real pension case + one GP Fund
      case run end to end and match a known-good CUDA run.
- [ ] systemd units installed (mirror `infra/*.service`, swap `ExecStart` to the `deploy/ascend/`
      scripts, drop CUDA env, add `ASCEND_RT_VISIBLE_DEVICES`).
- [ ] **Never restart a model mid-run** (memory `detach-long-jobs-on-this-box`,
      `pension-runsh-already-serving`).

---

## 7. What is NOT handled here (open items)

- **PaddleOCR-VL on Ascend** is listed as supported but is newer/less-tested — confirm it serves
  and reads a page before trusting OCR facts (facts need vision+OCR agreement — memory
  `c2-qualifying-service-proforma`).
- **ModelSlim W8A8 conversion** (if you want INT8 on 64G rather than BF16) is a separate step not
  scripted here; only Qwen/DeepSeek families are well-tested for it.
- **Multi-NPU topology** (`--enable-expert-parallel`, `--distributed-executor-backend mp`,
  `--data-parallel-size`) — defaults are set for a single node; tune per the tutorial once the card
  count is known.
- Qwen3Guard (safety, :8095) if still used — it is a Qwen3 dense model, also on the Ascend list;
  add a fourth script if you re-enable it.

Sources: [models index](https://docs.vllm.ai/projects/ascend/en/v0.23.0/tutorials/models) ·
[Qwen3-VL-30B-A3B tutorial](https://docs.vllm.ai/projects/ascend/en/v0.23.0/tutorials/models/Qwen3-VL-30B-A3B-Instruct.html) ·
[quantization](https://docs.vllm.ai/projects/ascend/en/v0.23.0/user_guide/feature_guide/quantization.html) ·
[structured output](https://docs.vllm.ai/projects/ascend/en/v0.9.1/user_guide/feature_guide/structured_output.html) ·
[installation](https://docs.vllm.ai/projects/ascend/en/v0.23.0/installation.html)
