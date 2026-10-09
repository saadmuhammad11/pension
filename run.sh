#!/usr/bin/env bash
#
# Start, stop and inspect the AI Pension Portal.
#
#   ./run.sh            start the API and the portal, then print the URLs
#   ./run.sh stop       stop them (only ours -- see the note on port 5173)
#   ./run.sh status     what is up, including the model services
#   ./run.sh restart
#
# There is no project-local virtualenv, deliberately. FastAPI, uvicorn and Pillow already live
# in /home/tmc/vllm_env alongside the CUDA stack, so the API runs on that interpreter directly
# rather than duplicating ~200 MB of wheels into the project. Nothing is ever installed into
# that env from here -- it is used read-only, and it belongs to the wider machine.
#
# The rules engine and its tests need none of it: they are standard-library only and run on the
# system python (`python3 -m unittest discover -s tests -t .`).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY=/home/tmc/vllm_env/bin/python3
API_PORT=8110
# The database (9 Oct 2026): PostgreSQL, named by PENSION_DATABASE_URL. deploy/postgres.env holds the
# URL for the container deploy/docker-compose.postgres.yml runs on this box; without the file (or the
# variable) the API falls back to the SQLite file, artifacts/portal.sqlite3. The test database URL
# is deliberately not exported to a server: tools/run-tests.sh sets it for the suites alone.
if [[ -z "${PENSION_DATABASE_URL:-}" && -r "$ROOT/deploy/postgres.env" ]]; then
  PENSION_DATABASE_URL="$(sed -n 's/^PENSION_DATABASE_URL=//p' "$ROOT/deploy/postgres.env" | tail -1)"
fi
export PENSION_DATABASE_URL="${PENSION_DATABASE_URL:-}"
unset PENSION_TEST_DATABASE_URL
# Trial period (25 Sep 2026): every account, including ones seeded later, uses this password.
export PENSION_SEED_PASSWORD="${PENSION_SEED_PASSWORD:-1234}"
UI_PORT=5184
# The models run on this machine, so the API reaches them on loopback (5 Oct 2026): the box lost
# its 192.168.1.1 address that day and every verification would have failed at stage 2. Loopback
# does not depend on which network the box is on. Override any of these for another GPU box.
export PENSION_VISION_URL="${PENSION_VISION_URL:-http://127.0.0.1:8011/v1/chat/completions}"
export PENSION_OCR_URL="${PENSION_OCR_URL:-http://127.0.0.1:8012/v1/chat/completions}"
export PENSION_EMBED_URL="${PENSION_EMBED_URL:-http://127.0.0.1:8093/v1/embeddings}"
# The model servers' key (audit 6 Oct 2026, item 7): once the keyed units are installed every /v1
# request needs it. Read from the same file the units load (root:tmc 640) unless already set.
if [[ -z "${PENSION_MODEL_API_KEY:-}" && -r /etc/pension/models.env ]]; then
  PENSION_MODEL_API_KEY="$(sed -n 's/^VLLM_API_KEY=//p' /etc/pension/models.env | tail -1)"
fi
export PENSION_MODEL_API_KEY="${PENSION_MODEL_API_KEY:-}"
MODEL_HOST=127.0.0.1
LOGS="$ROOT/artifacts/logs"
API_LOG="$LOGS/api.log"
UI_LOG="$LOGS/portal.log"

C_OK=$'\e[32m'; C_BAD=$'\e[31m'; C_WARN=$'\e[33m'; C_OFF=$'\e[0m'
ok()   { printf "  ${C_OK}%-7s${C_OFF} %s\n" "OK" "$1"; }
bad()  { printf "  ${C_BAD}%-7s${C_OFF} %s\n" "DOWN" "$1"; }
warn() { printf "  ${C_WARN}%-7s${C_OFF} %s\n" "WARN" "$1"; }

up() { curl -sf -m 3 "$1" >/dev/null 2>&1; }

# Only ever touches processes whose working directory is inside this project. Port 5173 on this
# machine belongs to a colleague's portal, and an earlier `pkill -f vite` would have taken it
# down along with ours.
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
start_api() {
  if up "http://127.0.0.1:$API_PORT/api/health"; then
    ok "API already serving on :$API_PORT"; return
  fi
  [[ -x "$VENV_PY" ]] || { bad "$VENV_PY not found — the API needs FastAPI from vllm_env"; return 1; }
  mkdir -p "$LOGS"
  ( cd "$ROOT" && setsid nohup "$VENV_PY" -m api.server "$API_PORT" >"$API_LOG" 2>&1 </dev/null & )
  for _ in $(seq 1 30); do
    up "http://127.0.0.1:$API_PORT/api/health" && { ok "API on :$API_PORT   (log: ${API_LOG#$ROOT/})"; return; }
    sleep 1
  done
  bad "API did not come up — last lines:"; tail -5 "$API_LOG" | sed 's/^/         /'
  return 1
}

start_ui() {
  if up "http://127.0.0.1:$UI_PORT/__portals"; then
    ok "portals already serving (AG portal on :$UI_PORT)"; return
  fi
  [[ -d "$ROOT/portals/node_modules" ]] || { bad "portals/node_modules missing — run: cd portals && npm ci"; return 1; }
  mkdir -p "$LOGS"
  # One process serves the built frontend on every portal's port (api/portal_server.py): the AG
  # portal on :5184 and one port per department. Rebuild the bundle when the source is newer.
  if [[ ! -f "$ROOT/portals/dist/index.html" ]] || [[ -n "$(find "$ROOT/portals/src" "$ROOT/portals/index.html" -newer "$ROOT/portals/dist/index.html" -print -quit 2>/dev/null)" ]]; then
    echo "  building the portal bundle…"
    ( cd "$ROOT/portals" && npx tsc --noEmit -p . && npx vite build ) > "$LOGS/portal-build.log" 2>&1 \
      || { bad "portal build failed (see $LOGS/portal-build.log)"; return 1; }
  fi
  ( cd "$ROOT" && setsid nohup "$VENV_PY" -m api.portal_server > "$LOGS/portals.log" 2>&1 < /dev/null & )
  for _ in $(seq 1 30); do up "http://127.0.0.1:$UI_PORT/__portals" && break; sleep 1; done
  if up "http://127.0.0.1:$UI_PORT/__portals"; then
    local n; n=$(curl -sf -m 3 "http://127.0.0.1:$UI_PORT/__portals" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['bound']))" 2>/dev/null)
    ok "portals  $n port(s) bound · AG portal http://localhost:$UI_PORT/ · list: :$UI_PORT/__portals"
    grep -h "could not bind" "$LOGS/portals.log" | sed 's/^/  /' | head -5
  else
    bad "portal server did not come up (see $LOGS/portals.log)"
  fi
}

start_dev_ui() {
  # A developer's live-reload server on :5300; use ?portal=<slug> to act as a department.
  ( cd "$ROOT/portals" && setsid nohup npx vite --host 0.0.0.0 --port 5300 --strictPort > "$LOGS/portal-dev.log" 2>&1 < /dev/null & )
  for _ in $(seq 1 30); do up "http://127.0.0.1:5300/" && break; sleep 1; done
  up "http://127.0.0.1:5300/" && ok "dev portal http://localhost:5300/?portal=agriculture" || bad "dev server :5300 did not come up"
}

stop_all() {
  local pids
  pids=$(find_ours "api.server")
  [[ -n "$pids" ]] && { kill $pids 2>/dev/null; ok "stopped API ($pids)"; } || warn "API was not running"
  pids=$(find_ours "api.portal_server|vite.*--port 5300")
  [[ -n "$pids" ]] && { kill $pids 2>/dev/null; ok "stopped portal ($pids)"; } || warn "portal was not running"
  echo "  (anything on :5173 is a different project and was left alone)"
}

model_services() {
  local name port
  # Only what the pipeline actually calls is reported as required. A status board that
  # lists an unused service teaches the operator to read red as normal, and then a real
  # outage looks like the usual noise. qwen3guard on :8095 was listed here and is called
  # by nothing; it is reported below the line, as provisioned rather than needed.
  echo "  model services this project calls:"
  for entry in "vision:8011" "ocr:8012" "embedding:8093"; do
    name=${entry%%:*}; port=${entry##*:}
    if up "http://$MODEL_HOST:$port/health"; then ok "$name :$port"; else bad "$name :$port"; fi
  done
  if up "http://192.168.101.10:8094/health"; then ok "reranker 192.168.101.10:8094"; else bad "reranker 192.168.101.10:8094"; fi
  echo "  provisioned on the estate, called by nothing in this pipeline:"
  if up "http://$MODEL_HOST:8095/health"; then
    warn "guard :8095 up (unused — it holds GPU memory the pipeline needs)"
  else
    echo "      guard :8095 down (unused, so this is not a fault)"
  fi
  if up "http://192.168.101.10:8001/health"; then ok "reasoning 192.168.101.10:8001 (unused)"; else echo "      reasoning :8001 down (unused, so this is not a fault)"; fi
}

status() {
  echo "AI Pension Portal — $ROOT"
  echo
  up "http://127.0.0.1:$API_PORT/api/health" && ok "API    http://localhost:$API_PORT/api/health" || bad "API    :$API_PORT"
  if up "http://127.0.0.1:$UI_PORT/__portals"; then
    local n; n=$(curl -sf -m 3 "http://127.0.0.1:$UI_PORT/__portals" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['bound']))" 2>/dev/null)
    ok "portals $n port(s) · AG portal http://localhost:$UI_PORT/ · departments :5180-5267 (portals/README.md)"
  else
    bad "portals :$UI_PORT"
  fi
  echo
  model_services
  echo
  # A run needs the vision model; the portal will start without it and then fail at stage 3.
  up "http://$MODEL_HOST:8011/health" || warn "vision :8011 is down — document classification and field extraction cannot run"
  echo
  up "http://127.0.0.1:$API_PORT/api/v2/departments" && ok "case system http://localhost:$API_PORT/api/v2/ · sign in at http://localhost:$UI_PORT/ (portals/README.md)" || bad "case system :$API_PORT/api/v2"
  up "http://127.0.0.1:8201/api/health" && ok "GP Fund module http://localhost:8201/ · in the portal at http://localhost:$UI_PORT/gpf/" || bad "GP Fund module :8201 (./GP/run.sh)"
}

# The GP Fund module (GP/backend on :8201) is the second product behind the same portal since
# 28 Sep 2026; GP/run.sh owns it and only ever touches its own process.
start_gpf() { "$ROOT/GP/run.sh" start 2>&1 | grep -E "OK|DOWN|WARN" | sed 's/^/  /' | head -3; }
stop_gpf()  { "$ROOT/GP/run.sh" stop 2>&1 | grep -E "OK|WARN" | sed 's/^/  /' | head -2; }

case "${1:-start}" in
  start)   start_api; start_ui; start_gpf; echo; status ;;
  stop)    stop_all; stop_gpf ;;
  restart) stop_all; stop_gpf; sleep 2; start_api; start_ui; start_gpf; echo; status ;;
  status)  status ;;
  dev)     start_dev_ui ;;
  build)   ( cd "$ROOT/portals" && npx tsc --noEmit -p . && npx vite build ) && ok "built portals/dist" ;;
  *) echo "usage: $0 [start|stop|restart|status|dev|build]" >&2; exit 2 ;;
esac
