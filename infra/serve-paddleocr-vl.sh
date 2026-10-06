#!/usr/bin/env bash
# PaddleOCR-VL-1.6 document-OCR service, port 8012.
# CO-LOCATED with qwen3guard-gen-4b (8095) and
# qwen3-embedding-4b (8093) on this GB10 unified-memory node. qwen3-vl (8011) was stopped
# to make room, leaving 73 GB free. Weights are
# only 1.8 GB BF16; gpu-memory-utilization 0.25 (~30 GB of 121) gives a deep KV cache
# while still leaving ~43 GB headroom on the node.
# --enforce-eager for a safe bring-up (skips graph capture / compile risk), matching the
# convention in serve-vision-fp8-node2.sh. Drop it later if throughput needs it.
#
# Brought into the repository on 6 Oct 2026 from /home/tmc/serve-paddleocr-vl.sh, so the unit runs
# a reviewed, released copy rather than a loose file in a home directory (audit item 7).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "$0")"
LOG_FILE="${LOG_FILE:-/home/tmc/paddleocr-vl.log}"

if [[ "${1:-}" == "--detach" ]]; then
    echo "Starting detached vLLM server..."
    nohup "$SCRIPT_DIR/$SCRIPT_NAME" > "$LOG_FILE" 2>&1 &
    echo "PID: $!"
    echo "Logs: $LOG_FILE"
    exit 0
fi

# Loopback only, and a key on every /v1 request (vLLM reads VLLM_API_KEY from the environment;
# /health stays open). The key comes from /etc/pension/models.env, never the command line.
HOST="${HOST:-127.0.0.1}"
VLLM_API_KEY="${VLLM_API_KEY:-}"
if [[ ${#VLLM_API_KEY} -lt 32 || "$VLLM_API_KEY" == *CHANGE_ME* ]]; then
    echo "ERROR: VLLM_API_KEY is missing, the placeholder, or under 32 characters. Set it in" \
         "/etc/pension/models.env (openssl rand -base64 48)." >&2
    exit 1
fi
export VLLM_API_KEY

VENV="${VENV:-/home/tmc/vllm_env}"
source "$VENV/bin/activate"
export TRITON_PTXAS_PATH="${TRITON_PTXAS_PATH:-/usr/local/cuda/bin/ptxas}"

MODEL_PATH="${MODEL_PATH:-/models/paddleocr-vl-1.6}"
SERVED_NAME="${SERVED_NAME:-paddleocr-vl-1.6}"
PORT="${PORT:-8012}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"   # page-at-a-time OCR; model supports 131072
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.25}"      # ~30 GB of 121; 73 GB was free after qwen3-vl stopped
MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"

if [[ ! -d "$MODEL_PATH" ]]; then
    echo "ERROR: model path not found: $MODEL_PATH" >&2
    exit 1
fi

# WHY --structured-outputs-config IS NOT OPTIONAL (added 2026-09-04)
#
# Without it this server cannot serve the OCR_FIRST_PASS role at all. Measured against the
# synthetic bundle's page 1 with the ocr-page prompt and _OCR_SCHEMA: 8192 completion tokens,
# finish_reason=length, unparseable. The content was valid JSON for ~8k characters and then an
# unbroken run of newlines.
#
# xgrammar's default configuration permits unlimited whitespace between JSON tokens, so a 0.9B
# model that loses the thread can emit "\n" forever and the grammar keeps accepting it until
# max_tokens runs out. disable_any_whitespace removes that escape hatch.
#
# serve-qwen3-vl.sh has always carried this flag, which is why :8011 answered the identical
# request in 728 tokens with valid JSON while :8012 burned 8192 and failed. This is a serving
# configuration defect, not a limit of PaddleOCR-VL.
#
echo "Starting vLLM server"
echo "Model: $MODEL_PATH"
echo "Port : $PORT"

exec vllm serve "$MODEL_PATH" \
    --served-model-name "$SERVED_NAME" \
    --max-model-len "$MAX_MODEL_LEN" \
    --max-num-seqs "$MAX_NUM_SEQS" \
    --gpu-memory-utilization "$GPU_MEM_UTIL" \
    --limit-mm-per-prompt '{"image":2}' \
    --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}' \
    --enforce-eager \
    --host "$HOST" \
    --port "$PORT"
