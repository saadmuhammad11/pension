#!/usr/bin/env bash
# Put the PostgreSQL driver where both interpreters find it (9 Oct 2026).
#
# The API runs on /home/tmc/vllm_env/bin/python3 (read-only, nothing is installed into it) and the
# tests on the system python3; neither has psycopg, and the box has no libpq. So psycopg 3 with its
# bundled libpq (psycopg[binary]) is installed into <root>/vendor, which api/dbcore.py appends to
# sys.path when the interpreter has no psycopg of its own. vendor/ is not tracked; run this once per
# checkout (and again after a Python minor-version change: the binary wheel is per version).
#
#   deploy/vendor-psycopg.sh            # install / refresh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
rm -rf "$ROOT/vendor"
"$PY" -m pip install --quiet --target "$ROOT/vendor" -r "$ROOT/deploy/requirements-db.txt"
PYTHONPATH="$ROOT/vendor" "$PY" -c "import psycopg; print('psycopg', psycopg.__version__, psycopg.pq.__impl__, 'libpq', psycopg.pq.version())"
