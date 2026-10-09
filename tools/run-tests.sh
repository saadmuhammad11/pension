#!/usr/bin/env bash
# Run the suites against PostgreSQL (9 Oct 2026).
#
#   tools/run-tests.sh                 # pension suite + GP Fund suite on the test database
#   tools/run-tests.sh tests.test_api_v2 -v     # arguments go to unittest (pension tree)
#   PENSION_TEST_DATABASE_URL=... tools/run-tests.sh   # another test database
#
# The test database is pension_test on the same server as deploy/postgres.env's URL (the compose
# init script creates it). Each test's temporary DB_PATH becomes a schema there, dropped when the
# process ends; `python3 -m api.db drop-test-schemas` clears what a killed run left behind.
# Without a URL and without deploy/postgres.env the suites run on SQLite, as before.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The pension suite needs FastAPI's TestClient, which lives in the API's interpreter (run.sh);
# the GP Fund rules suite is standard-library only and runs on the system python.
PY="${PENSION_TEST_PYTHON:-/home/tmc/vllm_env/bin/python3}"
[[ -x "$PY" ]] || PY=python3
if [[ -z "${PENSION_TEST_DATABASE_URL:-}" && -r "$ROOT/deploy/postgres.env" ]]; then
  url="$(sed -n 's/^PENSION_DATABASE_URL=//p' "$ROOT/deploy/postgres.env" | tail -1)"
  [[ -n "$url" ]] && PENSION_TEST_DATABASE_URL="${url%/*}/pension_test"
fi
export PENSION_TEST_DATABASE_URL="${PENSION_TEST_DATABASE_URL:-}"
unset PENSION_DATABASE_URL
echo "test database: ${PENSION_TEST_DATABASE_URL:-(none: SQLite)}" | sed 's#://\([^:]*\):[^@]*@#://\1:***@#'
cd "$ROOT"
if [[ $# -gt 0 ]]; then
  exec "$PY" -m unittest "$@"
fi
"$PY" -m unittest discover -s tests -t . ; a=$?
( cd "$ROOT/GP" && python3 -m unittest discover -s gpfund/tests -t . ) ; b=$?
"$ROOT/GP/backend/run.sh" test -q ; c=$?                     # pytest in its own venv; SQLite temp file (conftest)
echo "pension: $a  gp-fund rules: $b  gp-fund backend: $c"
[[ $a -eq 0 && $b -eq 0 && $c -eq 0 ]]
