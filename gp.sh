#!/usr/bin/env bash
#
# The GP Fund pre-audit module, reached from the pension project root.
#
#   ./gp.sh                 serve the prototype and print the link for your laptop
#   ./gp.sh stop            stop it
#   ./gp.sh status          what is up
#   ./gp.sh test            the rule-engine tests
#   ./gp.sh check fp-death  one case in full
#   ./gp.sh guide           the links plus the office's walk-through
#
# Every argument and every GP_* variable is passed straight through to GP/run.sh, which is
# the module's own launcher and holds the implementation -- including the process-safety
# checks that keep this from touching the two deployments on this box that are not ours.
# There used to be a second copy of that logic here; one copy is better than two that drift.
#
# Not to be confused with ./run.sh beside this file, which serves the AG Punjab PENSION
# portal (API :8110, portal :5184). This is the GP FUND module on :8099.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$ROOT/GP/run.sh"

if [[ ! -x "$TARGET" ]]; then
  if [[ -f "$TARGET" ]]; then
    printf '  \e[31mNO\e[0m      %s is not executable -- run: chmod +x %s\n' \
      "${TARGET#$ROOT/}" "${TARGET#$ROOT/}" >&2
  else
    printf '  \e[31mNO\e[0m      %s not found.\n' "${TARGET#$ROOT/}" >&2
    printf '          The GP Fund module lives in GP/. Extract agofficegpfund*.zip into GP/\n' >&2
    printf '          if that directory is missing.\n' >&2
  fi
  exit 1
fi

# So the delegate's hints name the script the operator actually typed.
export GP_INVOKED_AS="gp.sh"

exec "$TARGET" "$@"
