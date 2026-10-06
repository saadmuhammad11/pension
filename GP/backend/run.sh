#!/usr/bin/env bash
#
# Start, stop and inspect the GP Fund AI pre-audit module.
#
#   ./run.sh            start the app, then print the URLs
#   ./run.sh stop       stop it (only ours -- see the note in ours())
#   ./run.sh status     what is up, including the model services it calls
#   ./run.sh restart
#
# There is no project-local virtualenv, deliberately. This runs on /home/tmc/vllm_env, the
# same interpreter the AG Punjab pension portal next door uses: FastAPI, uvicorn and
# python-multipart already live there alongside the CUDA stack, so nothing is duplicated into
# the project. Nothing is ever installed into that env from here -- it is used read-only, and
# it belongs to the wider machine.
#
# One process serves everything: gpf.api mounts /api, the prototype assets, and the web/ UI
# on a single port. There is no separate front-end dev server.
#
# Port 8201, not 8200: this is the ~/Desktop/pension copy of the module, and the original in
# ~/Desktop/Pension-AG holds 8200 on this machine. The two are routinely up at the same time,
# and the AG pension portal's API holds 8110 next door. Override with PORT=... if you need to.
#
# FOUR deployments share this machine and only two are ours:
#     :8110 / :5184   AG Punjab pension portal    ~/Desktop/pension            (ours)
#     :8201           GP Fund module              ~/Desktop/pension/GP         (ours, this)
#     :8200           GP Fund module, the original ~/Desktop/Pension-AG/gp-fund (NOT ours)
#     :8100 / :5174   a colleague's pension copy  ~/Desktop/Pension-AG         (NOT ours)
# ours() below keys on the working directory, so stopping this never touches :8200.
#
# Model services (roles are auto-discovered from /v1/models at each endpoint):
#   Spark-2 (this host, 192.168.1.1):   vision qwen3-vl-30b :8011, OCR paddleocr-vl :8012,
#                                      embedding qwen3-embedding-4b :8093
#   Spark-1 ($SPARK1):                 reasoning qwen3.8-27b-fp8 :8001
# These were 10.170.1.143 / 10.170.0.240 until 1 Oct 2026. Off that network every discovery call
# waited out a TCP timeout before uvicorn would bind, so the module looked dead. This host's own
# models are reached on this host's LAN address 192.168.1.1, and Spark-1 over the direct cable
# (192.168.101.10).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY=/home/tmc/vllm_env/bin/python3
PORT="${PORT:-8201}"
# Listen address: loopback only, trial and production alike (5 Oct 2026). GP Fund has no sign-in of
# its own; the pension portal reaches it on 127.0.0.1 through its signed-in /api/v2 bridge, and
# nothing else should reach it at all (docs/DEPLOYMENT.md F9, F10). GPF_BIND=0.0.0.0 reopens it
# to the network -- for a demo on a closed network only.
GPF_BIND="${GPF_BIND:-127.0.0.1}"
LOGS="$ROOT/logs"
APP_LOG="$LOGS/gpf.log"

# This host's own models, on loopback since 5 Oct 2026 (the box lost 192.168.1.1 that day).
LOCAL="${GPF_LOCAL_HOST:-127.0.0.1}"
SPARK1="${GPF_SPARK1_HOST:-192.168.101.10}"
export GPF_VLLM_URLS="${GPF_VLLM_URLS:-http://$LOCAL:8011,http://$LOCAL:8012,http://$LOCAL:8093,http://$SPARK1:8001}"
export GPF_VLLM_TIMEOUT="${GPF_VLLM_TIMEOUT:-180}"
export GPF_DATA_DIR="${GPF_DATA_DIR:-$ROOT/data}"

C_OK=$'\e[32m'; C_BAD=$'\e[31m'; C_WARN=$'\e[33m'; C_OFF=$'\e[0m'
ok()   { printf "  ${C_OK}%-7s${C_OFF} %s\n" "OK" "$1"; }
bad()  { printf "  ${C_BAD}%-7s${C_OFF} %s\n" "DOWN" "$1"; }
warn() { printf "  ${C_WARN}%-7s${C_OFF} %s\n" "WARN" "$1"; }

up() { curl -sf -m 3 "$1" >/dev/null 2>&1; }

# Only ever touches processes whose working directory is inside this project. `pkill -f uvicorn`
# would take down the AG pension portal's API on :8100 along with ours.
ours() {
  local pid=$1 cwd
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null)" || return 1
  [[ "$cwd" == "$ROOT"* ]]
}

find_ours() {                      # find_ours <pattern>
  local pid
  for pid in $(pgrep -f "$1" 2>/dev/null); do
    ours "$pid" && echo "$pid"
  done
}

# ------------------------------------------------------------------------------------------
start_app() {
  if up "http://127.0.0.1:$PORT/api/health"; then
    ok "GP Fund already serving on :$PORT"; return
  fi
  [[ -x "$VENV_PY" ]] || { bad "$VENV_PY not found — the app needs FastAPI from vllm_env"; return 1; }
  mkdir -p "$LOGS" "$GPF_DATA_DIR"
  ( cd "$ROOT" && setsid nohup "$VENV_PY" -m uvicorn gpf.api:app \
      --host "$GPF_BIND" --port "$PORT" >"$APP_LOG" 2>&1 </dev/null & )
  for _ in $(seq 1 30); do
    up "http://127.0.0.1:$PORT/api/health" && { ok "GP Fund on :$PORT   (log: ${APP_LOG#$ROOT/})"; return; }
    sleep 1
  done
  bad "GP Fund did not come up — last lines:"; tail -5 "$APP_LOG" | sed 's/^/         /'
  return 1
}

stop_all() {
  local pids
  pids=$(find_ours "gpf.api")
  [[ -n "$pids" ]] && { kill $pids 2>/dev/null; ok "stopped GP Fund ($pids)"; } || warn "GP Fund was not running"
  echo "  (:8200, :8110/:5184 and :8100/:5174 belong to other deployments and were left alone)"
}

model_services() {
  local name url
  # Only what the reading pipeline actually calls is reported as required. A status board that
  # lists an unused service teaches the operator to read red as normal, and then a real outage
  # looks like the usual noise. Roles are discovered from GPF_VLLM_URLS at startup; if one of
  # these is down, the role it carries is simply absent and the pipeline falls back or 503s.
  echo "  model services this project calls:"
  for entry in "vision:http://$LOCAL:8011" \
               "ocr:http://$LOCAL:8012" \
               "embedding:http://$LOCAL:8093" \
               "reasoning:http://$SPARK1:8001"; do
    name=${entry%%:*}; url=${entry#*:}
    if up "$url/health"; then ok "$name ${url#http://}"; else bad "$name ${url#http://}"; fi
  done
}

status() {
  echo "GP Fund AI Pre-Audit Module — $ROOT"
  echo
  if up "http://127.0.0.1:$PORT/api/health"; then
    ok "app    http://localhost:$PORT/            (UI)"
    ok "       http://localhost:$PORT/api/health  (API)"
  else
    bad "app    :$PORT"
  fi
  echo
  model_services
  echo
  echo "  data dir: $GPF_DATA_DIR"
  # The rules engine is standard-library only and runs with no model at all. Reading scanned
  # documents is the part that needs vision; without it /api/cases/from-scans returns 503.
  up "http://$LOCAL:8011/health" || warn "vision :8011 is down — reading scanned documents cannot run (the rules engine still can)"
}

# The 62-test suite is pytest-based and vllm_env has no pytest, by the read-only rule above.
# So the suite gets its own small venv, built on first use and reused after -- printing the
# recipe and making the operator run it by hand only moved the same three commands onto them.
# Nothing is ever installed into vllm_env: that env belongs to the wider machine.
TEST_VENV="${GPF_TEST_VENV:-${XDG_CACHE_HOME:-$HOME/.cache}/gpf-test-venv}"

tests() {
  # If the shared interpreter happens to have pytest, use it and build nothing.
  if "$VENV_PY" -c "import pytest" 2>/dev/null; then
    ( cd "$ROOT" && exec "$VENV_PY" -m pytest "${@}" )
  fi

  if [[ ! -x "$TEST_VENV/bin/python" ]]; then
    echo "  building the test env at $TEST_VENV (first run only)"
    python3 -m venv "$TEST_VENV" || { bad "could not create $TEST_VENV"; return 1; }
  fi
  # -e so the tests import gpf from this tree, and re-run each time because it is cheap when
  # everything is already satisfied and it keeps the env honest after a dependency change.
  "$TEST_VENV/bin/pip" install -q -e "$ROOT[dev]" || { bad "could not install test deps"; return 1; }
  # GPF_VLLM_URLS is exported at the top of this script for the SERVER. It must not reach the
  # suite: two tests assert what happens when there is no vision model, and with the real
  # endpoints visible they see a working one and fail. The suite configures its own model
  # state per test, so it is run with the server's model settings removed. GPF_DATA_DIR too: it
  # points at the live data folder, and conftest.py only sends the suite to a temporary one
  # when the variable is unset (a scan-read test once left its uploads among real cases).
  ( cd "$ROOT" && exec env -u GPF_VLLM_URLS -u GPF_VLLM_TIMEOUT -u GPF_DATA_DIR \
      "$TEST_VENV/bin/python" -m pytest "${@}" )
}

case "${1:-start}" in
  start)   start_app; echo; status ;;
  stop)    stop_all ;;
  restart) stop_all; sleep 2; start_app; echo; status ;;
  status)  status ;;
  test)    shift; tests "$@" ;;
  *) echo "usage: $0 [start|stop|restart|status|test]" >&2; exit 2 ;;
esac
