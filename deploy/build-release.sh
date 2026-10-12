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
# The GP module's own working data (cases, page cache, uploads) is real claimant data and stays
# on the box it was made on; the fixtures it ships are synthetic (checked below).
copy --exclude 'data/' --exclude 'page_cache/' --exclude 'uploads/' --exclude '*.jsonl' \
     "$ROOT/GP/backend/gpf" "$ROOT/GP/backend/web" "$ROOT/GP/backend/pyproject.toml" \
     "$ROOT/GP/backend/requirements.txt" "$REL/GP/backend/"
# The deploy folder ships its examples, never a filled-in env file: deploy/postgres.env is the
# live database password (untracked, mode 600) and sat beside them, and an unfiltered copy of the
# folder packed it into the tarball (audit 12 Oct 2026). rsync takes the first matching rule, so
# the include for the examples must come before the exclude.
copy --include '*.env.example' --exclude '*.env' "$ROOT/deploy" "$REL/"
# The model services' launchers and units, so systemd runs them from this release (root-owned
# /opt/pension/current/infra) rather than from anyone's working tree (audit 6 Oct 2026, item 7).
mkdir -p "$REL/infra"
copy "$ROOT/infra/serve-qwen3-vl.sh" "$ROOT/infra/serve-paddleocr-vl.sh" "$ROOT/infra/warmup-vision.sh" \
     "$ROOT/infra/vllm-qwen3-vl.service" "$ROOT/infra/paddleocr-vl.service" \
     "$ROOT/infra/qwen3-embedding.service" "$ROOT/infra/models" "$REL/infra/"
cp "$ROOT/docs/DEPLOYMENT.md" "$REL/docs/"
cp "$ROOT/deploy/requirements.txt" "$REL/requirements.txt"
# The rules search index the pipeline cites from (rag/store.py); seeded into the data folder.
[[ -f "$ROOT/artifacts/rag/index.json" ]] && cp "$ROOT/artifacts/rag/index.json" "$REL/artifacts/rag/"
rm -rf "$REL/deploy/dist-release"
echo "$VERSION" > "$REL/VERSION"

echo "== checking for trial files"
bad=$(cd "$REL" && find . \( -iname 'credentials*' -o -name '*.sqlite3*' -o -name '.jwt_secret' -o -iname '*.pdf' \
        -o -name '*.rar' -o -name '*.zip' -o \( -name '*.sql' -not -path './api/migrations/*' \) \
        -o \( -name '*.env' ! -name '*.env.example' \) -o -name 'node_modules' \) -print)
if [[ -n "$bad" ]]; then
  echo "refusing: the release would carry trial files:" >&2; echo "$bad" >&2; exit 1
fi

echo "== checking for claimant data"
# File names catch the trial files above; this reads the contents. Any CNIC that is not one of
# the synthetic or placeholder numbers stops the build (the hits are printed masked).
"$PY" "$ROOT/deploy/check-release-pii.py" "$REL"

mkdir -p "$OUT"
# Owned by root in the archive: the files were staged as whoever built the release (uid 1000 on
# the trial box), and unpacked by root with their ids kept, /opt/pension/current belonged to a
# login account on the server (audit 6 Oct 2026, D1). The service user only ever needs to read it.
tar czf "$OUT/pension-$VERSION.tgz" --owner=0 --group=0 --numeric-owner -C "$STAGE" "pension-$VERSION"
( cd "$OUT" && sha256sum "pension-$VERSION.tgz" > "pension-$VERSION.tgz.sha256" )
echo "built $OUT/pension-$VERSION.tgz ($(du -h "$OUT/pension-$VERSION.tgz" | cut -f1))"
