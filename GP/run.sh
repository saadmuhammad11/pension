#!/usr/bin/env bash
#
# The GP Fund AI pre-audit module -- one front door for the whole system.
#
#   ./run.sh                 start the real system (API + web UI) and print laptop links
#   ./run.sh stop            stop it
#   ./run.sh restart
#   ./run.sh status          what is up, including the model services it calls
#   ./run.sh test            the 62 backend tests
#   ./run.sh logs            follow the app log
#
#   ./run.sh prototype       the OLD static HTML proof-of-concept on :8099 (not the system)
#   ./run.sh engine [args]   the standard-library rules engine, without the web layer
#   ./run.sh engine test     its 181 tests
#
# "The system" is backend/: a FastAPI app that serves the API, the web UI and the case
# assets from ONE process, with the reading pipeline behind gpf/clients/. That is what
# starts by default. The prototype under agofficegpfund/ is the frozen demo the office was
# shown in September and is kept only for reference -- it decides nothing and reads nothing.
#
# ---------------------------------------------------------------------------------------
# FOUR deployments share this machine and only two of them are ours:
#
#     :8110 / :5184   AG Punjab pension portal      ~/Desktop/pension             (ours)
#     :8201           GP Fund module                ~/Desktop/pension/GP          (ours, this)
#     :8200           GP Fund module, the original  ~/Desktop/Pension-AG/gp-fund  (NOT ours)
#     :8100 / :5174   a colleague's pension copy    ~/Desktop/Pension-AG          (NOT ours)
#
# Every process this script touches is first confirmed to be running out of THIS tree, by
# working directory. That is what keeps `stop` here from reaching :8200, which is the same
# application under a different root and would otherwise match every pattern we could grep
# for. It is also why an earlier `pkill -f vite` took down a colleague's portal.
# ---------------------------------------------------------------------------------------
set -uo pipefail

GP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$GP/backend"
SELF="${GP_INVOKED_AS:-$(basename "${BASH_SOURCE[0]}")}"
PY="${GP_PYTHON:-python3}"

# The prototype half, kept whole but no longer the default.
SERVE_DIR="$GP/agofficegpfund/prototype"
PAGE="gp-fund-preaudit-poc.html"
PROTO_PORT="${GP_PORT:-8099}"
PROTO_BIND="${GP_BIND:-0.0.0.0}"
PROTO_LOG="$GP/logs/prototype.log"

C_OK=$'\e[32m'; C_BAD=$'\e[31m'; C_WARN=$'\e[33m'; C_DIM=$'\e[2m'; C_BOLD=$'\e[1m'; C_OFF=$'\e[0m'
ok()     { printf "  ${C_OK}%-7s${C_OFF} %s\n" "OK"   "$1"; }
bad()    { printf "  ${C_BAD}%-7s${C_OFF} %s\n" "DOWN" "$1"; }
warn()   { printf "  ${C_WARN}%-7s${C_OFF} %s\n" "WARN" "$1"; }
refuse() { printf "  ${C_BAD}%-7s${C_OFF} %s\n" "NO"   "$1"; }
note()   { printf "  ${C_DIM}%s${C_OFF}\n" "$1"; }

have_backend() {
  [[ -x "$BACKEND/run.sh" ]] && return 0
  bad "backend/run.sh not found under $GP"
  note "The system lives in GP/backend/. Without it only 'prototype' and 'engine' will work."
  return 1
}

# The app's own launcher owns start/stop/status/test: it knows the interpreter, the port, the
# data dir and the model endpoints. Re-implementing any of that here would be a second copy
# to drift. PORT and the GPF_* variables pass straight through.
app() { have_backend || return 1; "$BACKEND/run.sh" "$@"; }

app_port() { echo "${PORT:-8201}"; }

# ------------------------------------------------------------------------------------------
# The prototype. Unchanged behaviour, now behind an explicit subcommand.

proto_up() { curl -sf -m 3 -o /dev/null "http://127.0.0.1:$PROTO_PORT/$PAGE" 2>/dev/null; }

ours() {
  local pid=$1 cwd
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null)" || return 1
  [[ "$cwd" == "$GP"* ]]
}

# `pgrep -f "http.server 8099"` matches ANY command line containing that text, including a
# shell that merely mentions it -- and this script's own invocation can. So each candidate is
# confirmed from /proc/PID/cmdline to be a Python interpreter actually running http.server on
# THIS port, from inside this tree.
serves_our_port() {
  local pid=$1 argv
  # cmdline is NUL-separated; make it space-separated with a trailing space so the port
  # matches as a whole argument and 8099 cannot match 80990.
  argv="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)" || return 1
  [[ "$argv" == *" http.server "* ]] || return 1
  [[ "$argv" == *" $PROTO_PORT "* ]] || return 1
  [[ "$(basename "$(readlink -f "/proc/$pid/exe" 2>/dev/null)")" == python* ]] || return 1
}

find_proto() {
  local pid
  for pid in $(pgrep -f "http\.server" 2>/dev/null); do
    serves_our_port "$pid" && ours "$pid" && echo "$pid"
  done
}

# What the RUNNING server on a port is bound to, read from the kernel rather than from a
# variable: a fresh shell would otherwise describe $GP_BIND instead of the live process.
#   actual_bind <port> [fallback]
actual_bind() {
  local port=$1 fallback=${2:-0.0.0.0} addr
  addr="$(ss -ltn 2>/dev/null | awk -v p=":$port\$" '$4 ~ p {print $4; exit}')"
  [[ -n "$addr" ]] && echo "${addr%:*}" || echo "$fallback"
}

# Every address this box answers on, so the page can be opened from a laptop rather than
# only from here. The box has several and only some of them reach a laptop, so each is
# printed with what it is instead of guessing at one and being wrong.
#   links <port> <path> [restrict-hint]
links() {
  local port=$1 path=${2:-} hint=${3:-} bound
  bound="$(actual_bind "$port")"

  # Bound to loopback, every address below is unreachable. Printing them anyway would hand
  # the operator four links that time out and one that works.
  if [[ "$bound" == "127.0.0.1" || "$bound" == "localhost" || "$bound" == "[::1]" ]]; then
    printf "\n      ${C_BOLD}http://localhost:%s/%s${C_OFF}\n\n" "$port" "$path"
    warn "bound to $bound, so only this machine can open it."
    return
  fi

  printf "\n  ${C_BOLD}Open this on your laptop${C_OFF}\n\n"

  # The interface carrying the default route first: that is the one a laptop on the same
  # network almost always arrives on.
  local main_if main_ip dev ip
  main_if="$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')"
  main_ip="$(ip -4 -o addr show scope global dev "$main_if" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1)"
  [[ -n "${main_ip:-}" ]] && \
    printf "      ${C_BOLD}http://%s:%s/%s${C_OFF}   ${C_DIM}(%s, this network)${C_OFF}\n" \
      "$main_ip" "$port" "$path" "$main_if"

  # Docker and container bridges are skipped: nothing outside this box can route to them,
  # and printing them only wastes a click.
  while read -r dev ip; do
    [[ "$dev" == "$main_if" ]] && continue
    case "$dev" in docker*|br-*|veth*|virbr*) continue ;; esac
    if [[ "$dev" == tailscale* ]]; then
      printf "      http://%s:%s/%s   ${C_DIM}(Tailscale, works from anywhere you are signed in)${C_OFF}\n" \
        "$ip" "$port" "$path"
    else
      printf "      http://%s:%s/%s   ${C_DIM}(%s)${C_OFF}\n" "$ip" "$port" "$path" "$dev"
    fi
  done < <(ip -4 -o addr show scope global | awk '{split($4,a,"/"); print $2, a[1]}')

  printf "      http://%s:%s/%s   ${C_DIM}(hostname, if your laptop resolves it)${C_OFF}\n" \
    "$(hostname)" "$port" "$path"
  printf "\n  ${C_DIM}On this machine: ${C_OFF}http://localhost:%s/%s\n" "$port" "$path"

  # Said once, at the point the choice is made. The case files are real: CNICs, bank
  # accounts, death certificates, family registration records. Neither server has a login,
  # so anything that can route to this box can read them -- which is the trade for opening
  # the page on a laptop.
  printf "\n  ${C_DIM}Serving real case papers (CNICs, bank details, family records) with no${C_OFF}\n"
  printf "  ${C_DIM}login, reachable by anything that can route to this box.${C_OFF}\n"
  [[ -n "$hint" ]] && printf "  ${C_DIM}%s${C_OFF}\n" "$hint"
  return 0
}

proto_links() {
  links "$PROTO_PORT" "$PAGE" "GP_BIND=127.0.0.1 ./$SELF prototype restricts it to this machine."
}

# The app binds 127.0.0.1 in backend/run.sh since 5 Oct 2026 (GPF_BIND to change it); links()
# then prints only the localhost address, because the network ones would not answer.
app_links() {
  links "$(app_port)" "" "PORT=8202 ./$SELF moves it to another port."
}

proto_start() {
  [[ -f "$SERVE_DIR/$PAGE" ]] || { bad "$SERVE_DIR/$PAGE not found"; return 1; }
  proto_up && { ok "prototype already serving on :$PROTO_PORT"; proto_links; return; }
  if ss -ltn 2>/dev/null | grep -q ":$PROTO_PORT "; then
    refuse "port $PROTO_PORT is held by another process, and it is not ours"
    note "Run GP_PORT=8098 ./$SELF prototype to use a different port."
    return 1
  fi
  mkdir -p "$GP/logs"
  ( cd "$SERVE_DIR" && setsid nohup "$PY" -m http.server "$PROTO_PORT" --bind "$PROTO_BIND" \
      >"$PROTO_LOG" 2>&1 </dev/null & )
  local _
  for _ in $(seq 1 20); do
    proto_up && { ok "prototype on :$PROTO_PORT"; proto_links; return; }
    sleep 0.5
  done
  bad "the prototype did not come up -- last lines:"
  tail -5 "$PROTO_LOG" 2>/dev/null | sed 's/^/         /'
  return 1
}

proto_stop() {
  local pids; pids=$(find_proto)
  [[ -n "$pids" ]] && { kill $pids 2>/dev/null && ok "stopped the prototype ($pids)"; } \
                   || warn "the prototype was not running"
}

# ------------------------------------------------------------------------------------------
# The rules engine, without the web layer. Standard library only: no GPU, no network, no
# clock, which is what lets the office re-check a case years from now.

engine() {
  if [[ "${1:-}" == "test" || "${1:-}" == "tests" ]]; then
    ( cd "$GP" && "$PY" -m unittest discover -s gpfund/tests -t . )
    return
  fi
  ( cd "$GP" && "$PY" -m gpfund "$@" )
}

overview() {
  echo
  echo "  the rest of this tree:"
  if proto_up; then
    note "prototype  http://localhost:$PROTO_PORT/$PAGE   (the frozen September demo)"
  else
    note "prototype  not running            ./$SELF prototype"
  fi
  local count
  count=$(cd "$GP" && "$PY" - <<'PYEOF' 2>/dev/null
import sys
sys.path.insert(0, ".")
try:
    import gpfund.rules
    from gpfund.engine import CHECKS, CUSTOM_CHECKS
    print(f"{len(CHECKS)} checks + {len(CUSTOM_CHECKS)} case-specific")
except Exception as exc:
    print(f"import failed: {exc}")
PYEOF
)
  note "engine     $count, needs nothing running    ./$SELF engine"
}

case "${1:-start}" in
  start)   app start   && app_links ;;
  stop)    app stop ;;
  restart) app restart && app_links ;;
  status)  app status; app_links; overview ;;
  test)    shift; app test "$@" ;;
  logs)    tail -f "$BACKEND/logs/gpf.log" ;;
  url|open|link|links)
    p="$(app_port)"
    if curl -sf -m 3 -o /dev/null "http://127.0.0.1:$p/api/health"; then
      app_links
    else
      bad "the system is not running on :$p -- ./$SELF start"; exit 1
    fi ;;
  prototype|proto)
    shift
    case "${1:-start}" in
      stop)    proto_stop ;;
      restart) proto_stop; sleep 1; proto_start ;;
      *)       proto_start ;;
    esac ;;
  engine)  shift; engine "$@" ;;
  *)
    cat >&2 <<TXT
usage: ./$SELF [start|stop|restart|status|test|logs|url]
       ./$SELF prototype [start|stop|restart]
       ./$SELF engine [case|--catalogue|test]

  THE SYSTEM (backend/, FastAPI: API + web UI + reading pipeline, one process)
    start      start it and print the URLs                    (default)
    stop       stop it; :8200, :8110/:5184 and :8100/:5174 are left alone
    restart
    status     what is up, including the four model services
    test       the 62 backend tests
    logs       follow backend/logs/gpf.log
    url        print the laptop links again

  REFERENCE
    prototype  the frozen September HTML demo on :8099 -- decides nothing
    engine     the standard-library rules engine with no web layer:
                 ./$SELF engine                  all eight corpus cases
                 ./$SELF engine fp-death         one case, every check
                 ./$SELF engine --catalogue      every registered check
                 ./$SELF engine test             its 181 tests

environment:
  PORT=8202               serve the system on another port (default 8201)
  GP_PORT=8098            the prototype's port (default 8099)
  GP_BIND=127.0.0.1       keep the prototype on this machine only
  GPF_VLLM_URLS=...       the model endpoints the reading pipeline calls
TXT
    exit 2 ;;
esac
