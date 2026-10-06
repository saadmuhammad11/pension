#!/usr/bin/env bash
#
# Build a production release tarball from this tree: code and the built portal only.
#
#   deploy/build-release.sh 1.0.0        -> dist-release/pension-1.0.0.tgz
#
# Runs the tests and the portal build first and stops on any failure. What goes in is a list,
# not "everything minus some": the trial tree holds case PDFs, the plaintext sign-in sheet,
# database backups and a helpdesk dump, and none of it may reach a server by accident
# (docs/DEPLOYMENT.md F7). After packing, the tarball is searched for those and refused if
# any is found.
set -euo pipefail

VERSION="${1:?usage: deploy/build-release.sh <version>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PENSION_PYTHON:-/home/tmc/vllm_env/bin/python3}"
OUT="$ROOT/dist-release"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
REL="$STAGE/pension-$VERSION"

echo "== tests"
( cd "$ROOT" && "$PY" -m unittest discover -s tests -t . >"$STAGE/tests.log" 2>&1 ) \
  || { tail -30 "$STAGE/tests.log"; echo "tests failed; no release built" >&2; exit 1; }
( cd "$ROOT/GP" && python3 -m unittest discover -s gpfund/tests -t . >"$STAGE/gp-tests.log" 2>&1 ) \
  || { tail -30 "$STAGE/gp-tests.log"; echo "GP engine tests failed" >&2; exit 1; }
( cd "$ROOT/GP/backend" && ./run.sh test -q >"$STAGE/gp-backend.log" 2>&1 ) \
  || { tail -30 "$STAGE/gp-backend.log"; echo "GP backend tests failed" >&2; exit 1; }

echo "== portal bundle"
( cd "$ROOT/portals" && npx tsc --noEmit -p . && npx vite build ) >"$STAGE/build.log" 2>&1 \
  || { tail -30 "$STAGE/build.log"; echo "portal build failed" >&2; exit 1; }

echo "== staging"
mkdir -p "$REL/portals" "$REL/GP/backend" "$REL/docs" "$REL/artifacts/rag"
copy() { rsync -a --exclude '__pycache__' --exclude '*.pyc' "$@"; }
copy "$ROOT/api" "$ROOT/rules" "$ROOT/pipeline" "$ROOT/extraction" "$ROOT/rag" "$ROOT/config" "$REL/"
copy "$ROOT/portals/dist" "$REL/portals/"
copy "$ROOT/GP/backend/gpf" "$ROOT/GP/backend/web" "$ROOT/GP/backend/pyproject.toml" \
     "$ROOT/GP/backend/requirements.txt" "$REL/GP/backend/"
copy "$ROOT/deploy" "$REL/"
cp "$ROOT/docs/DEPLOYMENT.md" "$REL/docs/"
cp "$ROOT/deploy/requirements.txt" "$REL/requirements.txt"
# The rules search index the pipeline cites from (rag/store.py); seeded into the data folder.
[[ -f "$ROOT/artifacts/rag/index.json" ]] && cp "$ROOT/artifacts/rag/index.json" "$REL/artifacts/rag/"
rm -rf "$REL/deploy/dist-release"
echo "$VERSION" > "$REL/VERSION"

echo "== checking for trial files"
bad=$(cd "$REL" && find . \( -iname 'credentials*' -o -name '*.sqlite3*' -o -name '.jwt_secret' -o -iname '*.pdf' \
        -o -name '*.rar' -o -name '*.zip' -o \( -name '*.sql' -not -path './api/migrations/*' \) -o -name '.env' \
        -o -name 'node_modules' \) -print)
if [[ -n "$bad" ]]; then
  echo "refusing: the release would carry trial files:" >&2; echo "$bad" >&2; exit 1
fi

mkdir -p "$OUT"
tar czf "$OUT/pension-$VERSION.tgz" -C "$STAGE" "pension-$VERSION"
( cd "$OUT" && sha256sum "pension-$VERSION.tgz" > "pension-$VERSION.tgz.sha256" )
echo "built $OUT/pension-$VERSION.tgz ($(du -h "$OUT/pension-$VERSION.tgz" | cut -f1))"
