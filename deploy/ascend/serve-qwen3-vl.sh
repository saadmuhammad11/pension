#!/usr/bin/env bash
# Vision server on Ascend NPU — Qwen3-VL-30B-A3B. DRAFT (13 Oct 2026), untested on hardware.
#
# Mirrors infra/serve-qwen3-vl.sh (CUDA) but for Ascend: no NVIDIA FP8, no ptxas, no FP8 weight
# fingerprint. The served name stays "qwen3-vl-30b-a3b-fp8" so the app (extraction/client.py:28)
# is unchanged even though the weights are BF16 (or Ascend W8A8-MXFP8).
#
#   VISION_QUANT=bf16  -> /models/qwen3-vl-30b-a3b-bf16        (no --quantization) TP=2  (64G cards)
#   VISION_QUANT=w8a8  -> /models/qwen3-vl-30b-a3b-w8a8-mxfp8  (--quantization ascend) TP=8 (950DT)
#
# Confirm on the box: CANN/torch-npu import, ASCEND_TP matches ASCEND_DEVICES count, and the
# image=2 + structured-output smoke tests (README §5).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "$0")"
LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/qwen3-vl-ascend.log}"
if [[ "${1:-}" == "--detach" ]]; then
    echo "Starting detached vision server (Ascend)..."
    nohup "$SCRIPT_DIR/$SCRIPT_NAME" > "$LOG_FILE" 2>&1 &
    echo "PID:  $!"; echo "Logs: $LOG_FILE"; exit 0
fi

VENV="${VENV:-/home/tmc/vllm_ascend_env}"
source "$VENV/bin/activate"

VISION_QUANT="${VISION_QUANT:-bf16}"                 # bf16 | w8a8
ASCEND_TP="${ASCEND_TP:-2}"                          # 2 for BF16/64G, 8 for 950DT mxfp8
ASCEND_DEVICES="${ASCEND_DEVICES:-0,1}"             # NPUs to use; count MUST equal ASCEND_TP
export ASCEND_RT_VISIBLE_DEVICES="$ASCEND_DEVICES"

if [[ "$VISION_QUANT" == "w8a8" ]]; then
    MODEL_PATH="${MODEL_PATH:-/models/qwen3-vl-30b-a3b-w8a8-mxfp8}"
    QUANT_FLAGS=(--quantization ascend)
else
    MODEL_PATH="${MODEL_PATH:-/models/qwen3-vl-30b-a3b-bf16}"
    QUANT_FLAGS=()
fi

SERVED_NAME="${SERVED_NAME:-qwen3-vl-30b-a3b-fp8}"   # keep identical to CUDA so the app is unchanged
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8011}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"                 # Ascend tutorial uses 0.9 (per-card HBM)
IMAGES_PER_PROMPT="${IMAGES_PER_PROMPT:-2}"          # a prescribed form spans 2 pages (D-I: 19-20)
SO_BACKEND="${SO_BACKEND:-xgrammar}"
SO_DISABLE_WS="${SO_DISABLE_WS:-true}"
MAX_IMAGE_TOKENS="${MAX_IMAGE_TOKENS:-3072}"
MIN_IMAGE_TOKENS="${MIN_IMAGE_TOKENS:-4}"
MAX_PIXELS=$(( MAX_IMAGE_TOKENS * 784 ))
MIN_PIXELS=$(( MIN_IMAGE_TOKENS * 784 ))

# API key: required, >=32 chars, not the placeholder (mirrors the CUDA scripts).
VLLM_API_KEY="${VLLM_API_KEY:-}"
if [[ ${#VLLM_API_KEY} -lt 32 || "$VLLM_API_KEY" == *CHANGE_ME* ]]; then
    echo "ERROR: VLLM_API_KEY missing, placeholder, or under 32 chars. Set it in /etc/pension/models.env" >&2
    exit 1
fi
export VLLM_API_KEY

export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 HF_HUB_DISABLE_TELEMETRY=1

if [[ ! -d "$MODEL_PATH" ]]; then
    echo "ERROR: model path not found: $MODEL_PATH (VISION_QUANT=$VISION_QUANT)" >&2
    exit 1
fi

echo "Vision (Ascend): model=$MODEL_PATH served=$SERVED_NAME quant=$VISION_QUANT TP=$ASCEND_TP devices=$ASCEND_DEVICES port=$PORT"

exec vllm serve "$MODEL_PATH" \
    --served-model-name "$SERVED_NAME" \
    --tensor-parallel-size "$ASCEND_TP" \
    --enable-expert-parallel \
    --trust-remote-code \
    --max-model-len "$MAX_MODEL_LEN" \
    --max-num-seqs "$MAX_NUM_SEQS" \
    --gpu-memory-utilization "$GPU_MEM_UTIL" \
    --limit-mm-per-prompt "{\"image\":$IMAGES_PER_PROMPT}" \
    --mm-processor-kwargs "{\"max_pixels\":$MAX_PIXELS,\"min_pixels\":$MIN_PIXELS}" \
    --structured-outputs-config "{\"backend\":\"$SO_BACKEND\",\"disable_any_whitespace\":$SO_DISABLE_WS}" \
    "${QUANT_FLAGS[@]}" \
    --host "$HOST" \
    --port "$PORT"
