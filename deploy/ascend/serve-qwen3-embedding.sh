#!/usr/bin/env bash
# Embedding server on Ascend NPU — Qwen3-Embedding-4B. DRAFT (13 Oct 2026), untested on hardware.
# Mirrors infra/qwen3-embedding.service (CUDA): pooling/embed runner. Served name + port kept
# identical so PENSION_EMBED_URL (http://127.0.0.1:8093/v1/embeddings) is unchanged.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "$0")"
LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/qwen3-embedding-ascend.log}"
if [[ "${1:-}" == "--detach" ]]; then
    echo "Starting detached embedding server (Ascend)..."
    nohup "$SCRIPT_DIR/$SCRIPT_NAME" > "$LOG_FILE" 2>&1 &
    echo "PID: $!"; echo "Logs: $LOG_FILE"; exit 0
fi

VENV="${VENV:-/home/tmc/vllm_ascend_env}"
source "$VENV/bin/activate"

ASCEND_TP="${EMBED_TP:-1}"
ASCEND_DEVICES="${EMBED_DEVICES:-3}"                  # its own NPU
export ASCEND_RT_VISIBLE_DEVICES="$ASCEND_DEVICES"

MODEL_PATH="${MODEL_PATH:-/models/qwen3-embedding-4b}"
SERVED_NAME="${SERVED_NAME:-qwen3-embedding-4b}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8093}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.30}"

VLLM_API_KEY="${VLLM_API_KEY:-}"
if [[ ${#VLLM_API_KEY} -lt 32 || "$VLLM_API_KEY" == *CHANGE_ME* ]]; then
    echo "ERROR: VLLM_API_KEY missing, placeholder, or under 32 chars. Set it in /etc/pension/models.env" >&2
    exit 1
fi
export VLLM_API_KEY
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 HF_HUB_DISABLE_TELEMETRY=1

if [[ ! -s "$MODEL_PATH/config.json" ]]; then
    echo "ERROR: model config not found: $MODEL_PATH/config.json" >&2; exit 1
fi

echo "Embedding (Ascend): model=$MODEL_PATH served=$SERVED_NAME TP=$ASCEND_TP devices=$ASCEND_DEVICES port=$PORT"

exec vllm serve "$MODEL_PATH" \
    --served-model-name "$SERVED_NAME" \
    --runner pooling \
    --convert embed \
    --tensor-parallel-size "$ASCEND_TP" \
    --trust-remote-code \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_MEM_UTIL" \
    --host "$HOST" \
    --port "$PORT"
