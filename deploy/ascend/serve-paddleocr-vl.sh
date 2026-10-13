#!/usr/bin/env bash
# OCR server on Ascend NPU — PaddleOCR-VL. DRAFT (13 Oct 2026), untested on hardware.
# Mirrors infra/serve-paddleocr-vl.sh (CUDA). Served name and port kept identical to the app.
# PaddleOCR-VL is listed as supported on vllm-ascend but is newer/less-tested: confirm it reads a
# page before trusting OCR facts (README §7).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "$0")"
LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/paddleocr-vl-ascend.log}"
if [[ "${1:-}" == "--detach" ]]; then
    echo "Starting detached OCR server (Ascend)..."
    nohup "$SCRIPT_DIR/$SCRIPT_NAME" > "$LOG_FILE" 2>&1 &
    echo "PID: $!"; echo "Logs: $LOG_FILE"; exit 0
fi

VENV="${VENV:-/home/tmc/vllm_ascend_env}"
source "$VENV/bin/activate"

ASCEND_TP="${OCR_TP:-1}"                              # OCR is small; TP=1 is usually enough
ASCEND_DEVICES="${OCR_DEVICES:-2}"                    # a separate NPU from the vision server
export ASCEND_RT_VISIBLE_DEVICES="$ASCEND_DEVICES"

MODEL_PATH="${MODEL_PATH:-/models/paddleocr-vl-1.6}"
SERVED_NAME="${SERVED_NAME:-paddleocr-vl-1.6}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8012}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"               # page-at-a-time; model supports 131072
MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"

VLLM_API_KEY="${VLLM_API_KEY:-}"
if [[ ${#VLLM_API_KEY} -lt 32 || "$VLLM_API_KEY" == *CHANGE_ME* ]]; then
    echo "ERROR: VLLM_API_KEY missing, placeholder, or under 32 chars. Set it in /etc/pension/models.env" >&2
    exit 1
fi
export VLLM_API_KEY
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 HF_HUB_DISABLE_TELEMETRY=1

if [[ ! -d "$MODEL_PATH" ]]; then
    echo "ERROR: model path not found: $MODEL_PATH" >&2; exit 1
fi

echo "OCR (Ascend): model=$MODEL_PATH served=$SERVED_NAME TP=$ASCEND_TP devices=$ASCEND_DEVICES port=$PORT"

exec vllm serve "$MODEL_PATH" \
    --served-model-name "$SERVED_NAME" \
    --tensor-parallel-size "$ASCEND_TP" \
    --trust-remote-code \
    --max-model-len "$MAX_MODEL_LEN" \
    --max-num-seqs "$MAX_NUM_SEQS" \
    --gpu-memory-utilization "$GPU_MEM_UTIL" \
    --limit-mm-per-prompt '{"image":2}' \
    --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}' \
    --enforce-eager \
    --host "$HOST" \
    --port "$PORT"
