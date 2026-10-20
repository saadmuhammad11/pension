#!/usr/bin/env bash
#
# Start, stop and inspect the AI Pension Portal.
#
#   ./run.sh            start the API and the portal, then print the URLs
#   ./run.sh stop       stop them (only ours -- see the note on port 5173)
#   ./run.sh status     what is up, including the model services
#   ./run.sh restart
#   ./run.sh stop|restart --force   even while verification runs are in flight (they are lost)
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
# The API's own description pages. Closed here rather than by PENSION_ENV=production, because
# the office keeps the trial's shared passwords and its sign-in sheet for now and production
# mode refuses both (13 Oct 2026). Set either to 1 to open them again.
export PENSION_API_DOCS="${PENSION_API_DOCS:-0}"
export GPF_API_DOCS="${GPF_API_DOCS:-0}"
UI_PORT=5184
# WHERE THE MODELS ARE. They ran on this machine until 18 Oct 2026 (DGX Spark), reached on
# loopback. They now run on a separate Ascend NPU server, so there is no defensible default
# here: /etc/pension/pension.env names the real endpoints and these are only a fallback for a
# developer box that serves its own models. The status board below reads whatever is set rather
# than assuming a port, because a board that checks the wrong address reports a healthy server
# down and teaches the operator to ignore it.
if [[ -z "${PENSION_VISION_URL:-}" && -r /etc/pension/pension.env ]]; then
  for _v in PENSION_VISION_URL PENSION_OCR_URL PENSION_EMBED_URL PENSION_RERANK_URL; do
    _val="$(sed -n "s/^$_v=//p" /etc/pension/pension.env | tail -1)"
    [[ -n "$_val" ]] && export "$_v=$_val"
  done
  unset _v _val
fi
export PENSION_VISION_URL="${PENSION_VISION_URL:-http://127.0.0.1:8011/v1/chat/completions}"
export PENSION_OCR_URL="${PENSION_OCR_URL:-http://127.0.0.1:8012/v1/chat/completions}"
export PENSION_EMBED_URL="${PENSION_EMBED_URL:-http://127.0.0.1:8093/v1/embeddings}"
# The model servers' key (audit 6 Oct 2026, item 7): once the keyed units are installed every /v1
# request needs it. Read from the same file the units load (root:tmc 640) unless already set.
if [[ -z "${PENSION_MODEL_API_KEY:-}" && -r /etc/pension/models.env ]]; then
  PENSION_MODEL_API_KEY="$(sed -n 's/^VLLM_API_KEY=//p' /etc/pension/models.env | tail -1)"
fi
export PENSION_MODEL_API_KEY="${PENSION_MODEL_API_KEY:-}"
#: scheme://host:port of a configured model endpoint -- the base the /health probe hangs off.
base_of() { printf '%s' "$1" | sed -E 's#^([a-zA-Z]+://[^/]+).*#\1#'; }
LOGS="$ROOT/artifacts/logs"
API_LOG="$LOGS/api.log"
UI_LOG="$LOGS/portal.log"

C_OK=$'\e[32m'; C_BAD=$'\e[31m'; C_WARN=$'\e[33m'; C_OFF=$'\e[0m'
ok()   { printf "  ${C_OK}%-7s${C_OFF} %s\n" "OK" "$1"; }
bad()  { printf "  ${C_BAD}%-7s${C_OFF} %s\n" "DOWN" "$1"; }
warn() { printf "  ${C_WARN}%-7s${C_OFF} %s\n" "WARN" "$1"; }

up() { curl -sf -m 3 "$1" >/dev/null 2>&1; }
# Answered at all, whatever the status. A route behind sign-in returns 401 to an unauthenticated
# probe, which is the service working: `up` reads that as down and reported a healthy case
# system dead on every production box (19 Oct 2026).
answers() { local c; c=$(curl -s -o /dev/null -m 3 -w '%{http_code}' "$1" 2>/dev/null); [[ -n "$c" && "$c" != 000 ]]; }

# Only ever touches processes whose working directory is inside this project. Port 5173 on this
# machine belongs to a colleague's portal, and an earlier `pkill -f vite` would have taken it
# down along with ours. The directory is compared whole: "$ROOT"* would also accept a sibling
# tree whose name merely starts with ours.
ours() {
  local pid=$1 cwd
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null)" || return 1
  [[ "$cwd" == "$ROOT" || "$cwd" == "$ROOT/"* ]]
}

# `pgrep -f api.server` matches ANY command line containing that text, including a shell that
# merely mentions it: a `bash -c '... api.server ...'` run from inside this tree was killed
# twice on 12 Oct 2026 (exit 144), the caller along with the server. So pgrep only nominates
# candidates, and each one is confirmed from /proc to be the process start_api or start_ui
# launched: argv[0] must be an interpreter of the right kind, and the arguments after it must
# be exactly the module and arguments we launch with. A wrapper shell has argv[0] = bash and
# fails the first check; a python running something else fails the second.
#   argv_after_exe <pid>   prints argv[1..] one per line (empty when the process is gone)
argv_after_exe() {
  local -a argv
  mapfile -d '' -t argv < "/proc/$1/cmdline" 2>/dev/null || return 1
  [[ ${#argv[@]} -gt 1 ]] || return 0
  printf '%s\n' "${argv[@]:1}"
}
exe_is() {                         # exe_is <pid> <python|node>
  [[ "$(basename "$(readlink -f "/proc/$1/exe" 2>/dev/null)")" == "$2"* ]]
}
#   is_python_running <pid> <arg>...   true when PID is a python whose argv[1..] is exactly <arg>...
is_python_running() {
  local pid=$1; shift
  exe_is "$pid" python || return 1
  [[ "$(argv_after_exe "$pid")" == "$(printf '%s\n' "$@")" ]]
}
#   is_vite_dev_server <pid>   true when PID is node running vite with `--port 5300` among its
#   arguments (npx resolves to `node .../node_modules/.bin/vite --host ... --port 5300 ...`).
is_vite_dev_server() {
  local pid=$1 i
  local -a argv
  exe_is "$pid" node || return 1
  mapfile -t argv < <(argv_after_exe "$pid")
  [[ ${#argv[@]} -ge 3 && "$(basename "${argv[0]}")" == vite* ]] || return 1
  for ((i = 1; i < ${#argv[@]} - 1; i++)); do
    [[ "${argv[i]}" == "--port" && "${argv[i+1]}" == "5300" ]] && return 0
  done
  return 1
}

# The pids of our servers, confirmed as above and inside this tree. pgrep narrows the field
# cheaply; it never decides.
find_api()    { local pid; for pid in $(pgrep -f "api\.server" 2>/dev/null); do
                  ours "$pid" && is_python_running "$pid" -m api.server "$API_PORT" && echo "$pid"; done; }
find_portal() { local pid; for pid in $(pgrep -f "api\.portal_server|vite" 2>/dev/null); do
                  ours "$pid" || continue
                  { is_python_running "$pid" -m api.portal_server || is_vite_dev_server "$pid"; } && echo "$pid"; done; }

# Sending SIGTERM and moving on left a window (12 Oct 2026): start_api ran while the old server
# was still shutting down, saw it answer /api/health, printed "already serving", and then the old
# process exited and nothing was listening. So a stop waits for the pids to be gone, up to 15 s,
# and only then SIGKILLs whatever is left.
#   wait_gone <pid>...
wait_gone() {
  local deadline=$((SECONDS + 15)) pid alive
  while :; do
    alive=""
    for pid in "$@"; do kill -0 "$pid" 2>/dev/null && alive="$alive $pid"; done
    [[ -z "$alive" ]] && return 0
    (( SECONDS >= deadline )) && break
    sleep 0.5
  done
  warn "still running after 15 s, killing:$alive"
  kill -9 $alive 2>/dev/null
  for _ in 1 2 3 4 5 6; do
    alive=""
    for pid in "$@"; do kill -0 "$pid" 2>/dev/null && alive="$alive $pid"; done
    [[ -z "$alive" ]] && return 0
    sleep 0.5
  done
  bad "could not stop:$alive"; return 1
}

# A verification run is a daemon thread inside the API: stopping the process mid-run loses the
# run and the officer's intake with it (12 Oct 2026, restarted twice during live runs). /api/health
# reports `runs`, the queued-or-running count, so a stop refuses while it is above zero unless
# `--force` is given. No answer from health means nothing to lose, and the stop proceeds.
#   active_runs   prints the count, or nothing when health does not answer
active_runs() {
  curl -sf -m 3 "http://127.0.0.1:$API_PORT/api/health" 2>/dev/null \
    | python3 -c "import json,sys; print(int(json.load(sys.stdin).get('runs') or 0))" 2>/dev/null
}
#   refuse_if_busy [--force]   returns 1 (after explaining) when runs are in flight and no --force
refuse_if_busy() {
  local n; n="$(active_runs)"
  [[ -z "$n" || "$n" == 0 ]] && return 0
  if [[ "${1:-}" == "--force" ]]; then
    warn "$n verification run(s) in flight on :$API_PORT; stopping anyway (--force)"; return 0
  fi
  bad "$n verification run(s) in flight on :$API_PORT; not stopping the API"
  echo "         wait for them to finish (./run.sh status, or /api/health \"runs\"), or: $0 ${ACTION:-stop} --force"
  return 1
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

#   stop_all [--force]   returns 1 without touching anything when runs are in flight and no --force
stop_all() {
  local pids
  refuse_if_busy "${1:-}" || return 1
  pids=$(find_api | xargs)
  if [[ -n "$pids" ]]; then kill $pids 2>/dev/null; wait_gone $pids && ok "stopped API ($pids)"; else warn "API was not running"; fi
  pids=$(find_portal | xargs)
  if [[ -n "$pids" ]]; then kill $pids 2>/dev/null; wait_gone $pids && ok "stopped portal ($pids)"; else warn "portal was not running"; fi
  echo "  (anything on :5173 is a different project and was left alone)"
}

model_services() {
  local name port
  # Only what the pipeline actually calls is reported as required. A status board that
  # lists an unused service teaches the operator to read red as normal, and then a real
  # outage looks like the usual noise. qwen3guard on :8095 was listed here and is called
  # by nothing; it is reported below the line, as provisioned rather than needed.
  local base
  echo "  model services this project calls:"
  for entry in "vision:$PENSION_VISION_URL" "ocr:$PENSION_OCR_URL" "embedding:$PENSION_EMBED_URL"; do
    name=${entry%%:*}; base=$(base_of "${entry#*:}")
    if [[ -z "$base" ]]; then warn "$name has no endpoint configured"; continue; fi
    if up "$base/health"; then ok "$name $base"; else bad "$name $base"; fi
  done
  # The reranker is optional: rag/store.py falls back to embedding-only ranking and says so in
  # each hit's stage. It is reported against the address actually configured, so an unset or a
  # stale PENSION_RERANK_URL is visible rather than hidden behind a hard-coded one.
  if [[ -n "${PENSION_RERANK_URL:-}" ]]; then
    base=$(base_of "$PENSION_RERANK_URL")
    if up "$base/health"; then ok "reranker $base"
    else warn "reranker $base unreachable — citations rank on embeddings alone"; fi
  else
    echo "      no reranker configured (citations rank on embeddings alone)"
  fi
}

status() {
  echo "AI Pension Portal — $ROOT"
  echo
  up "http://127.0.0.1:$API_PORT/api/health" && ok "API    http://localhost:$API_PORT/api/health" || bad "API    :$API_PORT"
  if up "http://127.0.0.1:$UI_PORT/__portals"; then
    local n; n=$(curl -sf -m 3 "http://127.0.0.1:$UI_PORT/__portals" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['bound']))" 2>/dev/null)
    ok "portals $n port(s) · AG portal http://localhost:$UI_PORT/ · departments :5180-5267 (portals/README.md)"
  elif up "http://127.0.0.1:$UI_PORT/"; then
    # /__portals is not served in production (api/portal_server.py), so its absence there is
    # the setting working, not the portal being down.
    ok "portal   http://localhost:$UI_PORT/ (production: /__portals not served)"
  else
    bad "portals :$UI_PORT"
  fi
  echo
  model_services
  echo
  # A run needs the vision model; the portal will start without it and then fail at stage 3.
  up "$(base_of "$PENSION_VISION_URL")/health" || warn "the vision model is down — document classification and field extraction cannot run"
  echo
  answers "http://127.0.0.1:$API_PORT/api/v2/departments" && ok "case system http://localhost:$API_PORT/api/v2/ · sign in at http://localhost:$UI_PORT/ (portals/README.md)" || bad "case system :$API_PORT/api/v2"
  up "http://127.0.0.1:8201/api/health" && ok "GP Fund module http://localhost:8201/ · in the portal at http://localhost:$UI_PORT/gpf/" || bad "GP Fund module :8201 (./GP/run.sh)"
}

# The GP Fund module (GP/backend on :8201) is the second product behind the same portal since
# 28 Sep 2026; GP/run.sh owns it and only ever touches its own process.
start_gpf() { "$ROOT/GP/run.sh" start 2>&1 | grep -E "OK|DOWN|WARN" | sed 's/^/  /' | head -3; }
stop_gpf()  { "$ROOT/GP/run.sh" stop 2>&1 | grep -E "OK|WARN" | sed 's/^/  /' | head -2; }

ACTION="${1:-start}"
# `stop --force` and `restart --force` stop the API even while verification runs are in flight.
FORCE=""
[[ "${2:-}" == "--force" ]] && FORCE="--force"
case "$ACTION" in
  start)   start_api; start_ui; start_gpf; echo; status ;;
  stop)    stop_all "$FORCE" && stop_gpf ;;
  # stop_all already waited for the old pids to exit, so start_api cannot see the old server.
  restart) stop_all "$FORCE" && { stop_gpf; start_api; start_ui; start_gpf; echo; status; } ;;
  status)  status ;;
  dev)     start_dev_ui ;;
  build)   ( cd "$ROOT/portals" && npx tsc --noEmit -p . && npx vite build ) && ok "built portals/dist" ;;
  *) echo "usage: $0 [start|stop|restart|status|dev|build] [--force]" >&2; exit 2 ;;
esac
