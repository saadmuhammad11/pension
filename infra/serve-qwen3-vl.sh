#!/usr/bin/env bash
#
# AG Punjab AI Pension Portal — document-vision service.
#
# Serves Qwen3-VL-30B-A3B (FP8) as an OpenAI-compatible endpoint. This is pipeline stage 2/3/4
# (OCR & layout parsing, document classification, field extraction) per AGPB-BUILD §5.
#
# WHERE IT RUNS: spark-3369 (192.168.100.11). The reasoning model (qwen3.6-35b-a3b-fp8) stays on
# spark-46ef (192.168.100.10:8001) — AGPB-BUILD §3.1 topology: Spark-1 reasoning, Spark-2 vision.
#
# WHY THE CONSERVATIVE FOOTPRINT: this box co-hosts the voice services (~0.55 of unified memory
# reserved across omnivoice/qwen3-asr/whisper-urdu). The 2026-07-15 unified-memory OOM freeze is
# the reason gpu-memory-utilization and max-num-seqs are kept small here rather than tuned for
# throughput. Raise them only after measuring, and only while watching free memory.
#
# WHY --enforce-eager BY DEFAULT: FP8 MoE + the per-image-shape mrope Triton JIT is the exact
# combination behind the previous vision bring-up problems. Single-node means the JIT is a latency
# spike, not a hang, but graph capture over FP8-MoE remains the riskier path. Prove the service
# first, then try EAGER=0 and measure the decode gain.
#
#   Usage:  ./serve-qwen3-vl.sh              # foreground
#           ./serve-qwen3-vl.sh --detach     # background, logs to $LOG_FILE
#           VERIFY_WEIGHTS=1 ./serve-qwen3-vl.sh   # full shard sha256 before serving (slow)
#           EAGER=0 GPU_MEM_UTIL=0.40 ./serve-qwen3-vl.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "$0")"
LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/qwen3-vl-vllm.log}"

# --- Detached mode ----------------------------------------------------------------------------
if [[ "${1:-}" == "--detach" ]]; then
    echo "Starting detached vision server..."
    nohup "$SCRIPT_DIR/$SCRIPT_NAME" > "$LOG_FILE" 2>&1 &
    echo "PID:  $!"
    echo "Logs: $LOG_FILE"
    exit 0
fi

# --- Config -----------------------------------------------------------------------------------
VENV="${VENV:-/home/tmc/vllm_env}"
MODEL_PATH="${MODEL_PATH:-/models/qwen3-vl-30b-a3b-fp8}"
SERVED_NAME="${SERVED_NAME:-qwen3-vl-30b-a3b-fp8}"
# Loopback only: the pipeline and the GP Fund module call it from this box. On 0.0.0.0 with no key
# anyone on the LAN could use the GPU and read the prompts (audit 6 Oct 2026, item 7).
HOST="${HOST:-127.0.0.1}"
# vLLM reads VLLM_API_KEY from the environment and then refuses any /v1 request without
# "Authorization: Bearer <key>" (/health stays open for the start-up probes). It comes from
# /etc/pension/models.env (systemd EnvironmentFile), never the command line, where `ps` shows it.
VLLM_API_KEY="${VLLM_API_KEY:-}"
PORT="${PORT:-8011}"                       # 8010 is reserved by serve-vision-fp8-node2.sh
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.45}"       # ~42GB of 121GB: ~31GB FP8 weights + ~11GB KV
MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"
# CUDA GRAPHS ON, measured 23 September 2026. Revert with EAGER=1 if this ever misbehaves.
#
# The header above says to prove the service first and then try EAGER=0 and measure the decode
# gain. Measured on an idle box at max-num-seqs 16 / gpu-mem 0.45, same pages both times:
#
#                            --enforce-eager      CUDA graphs
#     extract_page              33.1s                28.7s
#     extract_page_confirmed    64.2s                51.3s      -20%
#     decode rate               38.8 tok/s           47.3 tok/s +22%
#     identify, conc 1/2/4/8    2.8/2.0/1.4/1.2      2.4/1.8/1.5/1.2   (unchanged)
#
# The win is on the LONG calls, which is where the time is: stage 6 is the dominant cost of a
# run and is entirely confirming double reads of ~1,300 output tokens each. Graph capture cost
# 0.15 GiB and took KV cache from 22.01 to 21.77 GiB, which is nothing.
#
# ONE REAL COST, and it is the one this header predicted: "the JIT is a latency spike". The
# FIRST benchmark after the restart read 3.6/3.0/2.4/2.4 -- every level worse -- and the
# identical benchmark immediately after read 2.4/1.8/1.5/1.2. That gap is per-image-shape
# compilation, paid once per shape after every start. Restart=always means an unattended
# restart makes the first case of the day slower; warmup-vision.sh covers some of it, and
# widening the shapes it warms is the obvious next refinement.
EAGER="${EAGER:-0}"

# Safetensors load strategy. Left unset (vLLM default) the engine memory-maps lazily and
# auto-prefetches only when it recognises a network FS. It never does here: /models appears in
# /proc/mounts twice with the same mount point ("systemd-1 /models autofs" before
# "192.168.100.10:/models /models nfs4"), and vLLM's _get_fs_type keeps the FIRST longest-prefix
# match, so the checkpoint filesystem is reported as AUTOFS and auto-prefetch is skipped even
# though the mount really is nfs4. Set LOAD_STRATEGY=prefetch (page-cache warm before load) or
# =eager (whole shard read upfront, uses more CPU RAM) to override.
LOAD_STRATEGY="${LOAD_STRATEGY:-}"
IMAGES_PER_PROMPT="${IMAGES_PER_PROMPT:-2}"   # a prescribed form commonly spans 2 pages (D-I: 19-20)

# Structured outputs. Stage-4 extraction sends response_format={"type":"json_schema"} on every
# request, so the grammar backend is on the hot path and is pinned rather than left to "auto":
# an auto-selected backend can change with a vLLM upgrade, and provenance requires that the same
# input reproduce the same output years later.
#
# Measured on source page 42 of the golden case (AG salary statement, the densest page in the file):
#   free-form "return JSON" prompt  -> 6000 output tokens, TRUNCATED, invalid JSON
#   response_format json_schema     ->  867 output tokens, valid
# The failure was not cosmetic: an unconstrained schema let a phone number ("03000000001") into an
# integer array, and JSON forbids leading zeros, so a single character invalidated the whole page.
# disable_any_whitespace drops the model's freedom to emit pretty-printing, cutting output further.
SO_BACKEND="${SO_BACKEND:-xgrammar}"
SO_DISABLE_WS="${SO_DISABLE_WS:-true}"
VERIFY_WEIGHTS="${VERIFY_WEIGHTS:-0}"

# Upstream identity, verified against the HF API on 2026-09-02:
#   repo      Qwen/Qwen3-VL-30B-A3B-Instruct-FP8
#   revision  d9748a51ae66354c4dad665aab2c71f26cf2c8cd  (lastModified 2025-11-26)
#   weights   4 shards, 32,251,954,920 bytes total, 1170 tensors
# All 16 local files matched upstream sizes byte-for-byte and every tensor declared in the shard
# index was present. This gate exists because the download log for this artifact records repeated
# stalls and SIGKILLs ("attempt 1 ... STALL ... rc=137"), so a silently truncated re-download is a
# demonstrated failure mode here, not a hypothetical one.
UPSTREAM_REVISION="d9748a51ae66354c4dad665aab2c71f26cf2c8cd"
UPSTREAM_TOTAL_BYTES="${UPSTREAM_TOTAL_BYTES:-32251954920}"
UPSTREAM_TENSOR_COUNT="${UPSTREAM_TENSOR_COUNT:-1170}"
FINGERPRINT_DIR="${FINGERPRINT_DIR:-$SCRIPT_DIR/models}"

# Image token budget. Qwen VL emits roughly pixels/(28*28) tokens per image, so:
#   MAX_IMAGE_TOKENS x 784 = max_pixels
# An uncapped A4 CamScanner page (2480x3508 = 8.7M px) would alone be ~11,100 tokens and blow the
# context. 3072 tokens/page is about a 1300x1850 render.
#
# CALIBRATION OWED: this is the single knob that trades OCR fidelity on dense Urdu print against
# KV footprint, and it cannot be set honestly until real CamScanner pages are measured against the
# hand-labelled golden case. Treat the default as a safe starting point, not a tuned value.
MAX_IMAGE_TOKENS="${MAX_IMAGE_TOKENS:-3072}"
MIN_IMAGE_TOKENS="${MIN_IMAGE_TOKENS:-4}"
MAX_PIXELS=$(( MAX_IMAGE_TOKENS * 784 ))
MIN_PIXELS=$(( MIN_IMAGE_TOKENS * 784 ))

# --- Sovereignty: offline is enforced, not assumed ---------------------------------------------
# A startup that reaches the network is a sovereignty defect, not a warning (AGPB-BUILD §3.3).
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 HF_HUB_DISABLE_TELEMETRY=1

# --- Engine environment -------------------------------------------------------------------------
export VLLM_HOST_IP="$(hostname -I | tr ' ' '\n' | grep -m1 '^192\.168\.100\.' || echo 127.0.0.1)"
export VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS="${VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS:-1800}"
export VLLM_ENGINE_ITERATION_TIMEOUT_S="${VLLM_ENGINE_ITERATION_TIMEOUT_S:-1800}"
export VLLM_ENGINE_READY_TIMEOUT_S="${VLLM_ENGINE_READY_TIMEOUT_S:-3600}"
export TRITON_PTXAS_PATH="${TRITON_PTXAS_PATH:-/usr/local/cuda/bin/ptxas}"
export PATH="/usr/local/cuda/bin:$PATH"

# --- Preflight ----------------------------------------------------------------------------------
die() { echo "ERROR: $*" >&2; exit 1; }

[[ ${#VLLM_API_KEY} -ge 32 && "$VLLM_API_KEY" != *CHANGE_ME* ]] || die "VLLM_API_KEY is missing, \
the placeholder, or under 32 characters. Set it in /etc/pension/models.env (openssl rand -base64 48)."
export VLLM_API_KEY

[[ -d "$MODEL_PATH" ]] || die "model path not found: $MODEL_PATH
Weights are never downloaded. If this artifact is absent, that is a blocking operational
finding — do not substitute a different model or fall back to a smaller variant."

[[ -f "$MODEL_PATH/config.json" ]] || die "no config.json under $MODEL_PATH"
[[ -f "$VENV/bin/vllm" ]]         || die "vllm not found at $VENV/bin/vllm"

if (ss -tln 2>/dev/null || netstat -tln 2>/dev/null) | grep -qE "[:.]${PORT}[[:space:]]"; then
    die "port $PORT is already in use. Set PORT=<free port>."
fi

ARCH=$("$VENV/bin/python" -c "import json;print(json.load(open('$MODEL_PATH/config.json'))['architectures'][0])")
[[ "$ARCH" == "Qwen3VLMoeForConditionalGeneration" ]] \
    || die "unexpected architecture '$ARCH' — refusing to serve a model this script was not written for"

DECLARED_TENSORS=$("$VENV/bin/python" -c \
    "import json;print(len(json.load(open('$MODEL_PATH/model.safetensors.index.json'))['weight_map']))")
[[ "$DECLARED_TENSORS" == "$UPSTREAM_TENSOR_COUNT" ]] \
    || die "shard index declares $DECLARED_TENSORS tensors, expected $UPSTREAM_TENSOR_COUNT
The weights do not match the verified upstream revision $UPSTREAM_REVISION."

# --- Weights provenance -------------------------------------------------------------------------
# provenance.weights_version must be reproducible (AGPB-BRAIN §6 provenance block). The cheap
# fingerprint hashes config.json + the shard index and totals the shard bytes: it pins the
# architecture, quantisation and shard layout without reading 31GB over NFS on every restart.
# VERIFY_WEIGHTS=1 additionally hashes every shard, which is the real integrity check.
mkdir -p "$FINGERPRINT_DIR"
FP_FILE="$FINGERPRINT_DIR/${SERVED_NAME}.fingerprint"

SHARD_BYTES=$(find "$MODEL_PATH" -maxdepth 1 -name '*.safetensors' -printf '%s\n' \
               | awk '{t+=$1} END{printf "%d", t}')
SHARD_COUNT=$(find "$MODEL_PATH" -maxdepth 1 -name '*.safetensors' | wc -l)
CHEAP_SHA=$(cat "$MODEL_PATH/config.json" "$MODEL_PATH/model.safetensors.index.json" 2>/dev/null \
            | sha256sum | cut -d' ' -f1)

[[ "$SHARD_BYTES" == "$UPSTREAM_TOTAL_BYTES" ]] || die "shard bytes $SHARD_BYTES, expected $UPSTREAM_TOTAL_BYTES
The weights are truncated or divergent from upstream revision $UPSTREAM_REVISION. Do not serve
them: a partially-downloaded shard set loads without error and produces silently wrong output.
Re-download and re-run, or delete $FP_FILE if this change is deliberate."

if [[ "$VERIFY_WEIGHTS" == "1" ]]; then
    echo "Hashing $SHARD_COUNT shards ($SHARD_BYTES bytes) — this reads the full model over NFS..."
    SHARD_SHA=$(find "$MODEL_PATH" -maxdepth 1 -name '*.safetensors' | sort \
                | xargs sha256sum | sha256sum | cut -d' ' -f1)
else
    SHARD_SHA="not-verified"
fi

FP_NOW="arch=$ARCH shards=$SHARD_COUNT bytes=$SHARD_BYTES cheap_sha256=$CHEAP_SHA"

if [[ -f "$FP_FILE" ]]; then
    FP_WAS=$(grep -m1 '^arch=' "$FP_FILE" || true)
    if [[ "$FP_WAS" != "$FP_NOW" ]]; then
        die "weights fingerprint mismatch — refusing to serve.
  recorded: $FP_WAS
  on disk:  $FP_NOW
If this change is intended, delete $FP_FILE and re-run to re-record it."
    fi
    echo "Weights fingerprint matches $FP_FILE"
else
    { echo "$FP_NOW"; echo "recorded_at=$(date -Is)"; echo "model_path=$MODEL_PATH"; \
      echo "shard_sha256=$SHARD_SHA"; } > "$FP_FILE"
    echo "Weights fingerprint recorded (first run): $FP_FILE"
fi

# --- Report -------------------------------------------------------------------------------------
cat <<EOF

  AG Punjab Pension Portal — document vision
  ------------------------------------------------------------------
  model            $MODEL_PATH
  served as        $SERVED_NAME
  endpoint         http://$HOST:$PORT/v1
  host ip          $VLLM_HOST_IP
  context          $MAX_MODEL_LEN tokens
  images/prompt    $IMAGES_PER_PROMPT  (<= $MAX_IMAGE_TOKENS tokens each, max_pixels=$MAX_PIXELS)
  gpu mem util     $GPU_MEM_UTIL   max-num-seqs $MAX_NUM_SEQS   eager=$EAGER
  load strategy    ${LOAD_STRATEGY:-<vllm default: lazy mmap, auto-prefetch on NFS>}
  structured out   backend=$SO_BACKEND  disable_any_whitespace=$SO_DISABLE_WS
  offline          HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 (telemetry off)
  reasoning model  http://192.168.100.10:8001/v1  (separate box, untouched)
  ------------------------------------------------------------------

EOF

free -g | sed -n '1,2p'
echo

# --- Serve --------------------------------------------------------------------------------------
source "$VENV/bin/activate"

EXTRA=()
[[ "$EAGER" == "1" ]] && EXTRA+=(--enforce-eager)
[[ -n "$LOAD_STRATEGY" ]] && EXTRA+=(--safetensors-load-strategy "$LOAD_STRATEGY")

exec vllm serve "$MODEL_PATH" \
    --served-model-name "$SERVED_NAME" \
    --max-model-len "$MAX_MODEL_LEN" \
    --max-num-seqs "$MAX_NUM_SEQS" \
    --gpu-memory-utilization "$GPU_MEM_UTIL" \
    --limit-mm-per-prompt "{\"image\":$IMAGES_PER_PROMPT}" \
    --mm-processor-kwargs "{\"max_pixels\":$MAX_PIXELS,\"min_pixels\":$MIN_PIXELS}" \
    --enable-prefix-caching \
    --structured-outputs-config "{\"backend\":\"$SO_BACKEND\",\"disable_any_whitespace\":$SO_DISABLE_WS}" \
    "${EXTRA[@]}" \
    --host "$HOST" \
    --port "$PORT"
