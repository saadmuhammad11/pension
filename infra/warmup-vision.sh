#!/usr/bin/env bash
#
# Warm the vision service with REAL production requests before it is used on a pension case.
#
# Why this exists, and why the obvious version of it did not work
# ---------------------------------------------------------------
# Observed reproducibly across two restarts of this service on 2026-09-02, on the AG pay
# certificate (source page 29 of the golden case):
#
#     request #1 after restart : 14 rows, 0 amounts filled, 1298 output tokens   -- WRONG
#     requests #2-5            : 13 rows, 13 amounts filled, 1329 tokens         -- correct
#
# Every label read correctly; every amount came back null. The first attempt at a fix sent a
# generic warmup request with a small ad-hoc schema. It reported OK and the very next real
# request STILL failed identically -- because a generic request does not make the production
# request "not the first of its kind". Whatever is being initialised on first use (prefix cache,
# multimodal processor cache, first-use grammar compilation for a given schema are all
# candidates; the mechanism is not established) is specific to the request shape.
#
# So this warmup sends the ACTUAL production requests: the real client, the real system prompt
# and instruction, the real per-document-type schemas, on a page at real geometry. One request
# per schema, so no schema's first use lands on a real case.
#
# This is belt-and-braces with extraction.client's all-amounts-null retry guard, which catches
# the symptom regardless of cause. Neither replaces the other: the guard costs a re-read on a
# real case, the warmup means the guard should not have to fire.
#
# Failure here is deliberately non-fatal: it logs loudly but does not flap the service.
set -uo pipefail

PORT="${PORT:-8011}"
URL="http://127.0.0.1:${PORT}"
# The release this script ships in (infra/..), not another checkout: the warmup must exercise the
# client this deployment runs. It once imported a different developer's tree (audit 6 Oct 2026).
PROJECT="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON="${PYTHON:-/home/tmc/vllm_env/bin/python}"
DEADLINE=$(( SECONDS + ${WARMUP_TIMEOUT:-900} ))

# Real page geometry. The vision kernels compile per shape, so a warmup at the wrong size warms
# the wrong path. 910x1287 is the page size of the digitized case corpus; if the scanning
# pipeline changes geometry, change this or the warmup silently stops covering what matters.
WARMUP_W="${WARMUP_W:-910}"
WARMUP_H="${WARMUP_H:-1287}"

echo "warmup: waiting for ${URL}/health"
until curl -sf --max-time 4 "${URL}/health" >/dev/null 2>&1; do
    if (( SECONDS > DEADLINE )); then echo "warmup: TIMED OUT waiting for health"; exit 0; fi
    sleep 5
done

cd "$PROJECT" || { echo "warmup: project dir $PROJECT not found"; exit 0; }

# The server wants its key on /v1 (VLLM_API_KEY, from the same EnvironmentFile); the client sends
# PENSION_MODEL_API_KEY, so hand it the one this server was started with.
PROJECT="$PROJECT" PENSION_VISION_URL="${URL}/v1/chat/completions" \
PENSION_MODEL_API_KEY="${VLLM_API_KEY:-${PENSION_MODEL_API_KEY:-}}" \
"$PYTHON" - "$WARMUP_W" "$WARMUP_H" <<'PY'
import io, os, sys, tempfile, pathlib
sys.path.insert(0, os.environ["PROJECT"])

width, height = int(sys.argv[1]), int(sys.argv[2])

try:
    from PIL import Image, ImageDraw
    from extraction.client import extract_page, ExtractionError
except Exception as exc:                                            # noqa: BLE001
    print(f"warmup: cannot import warmup dependencies ({exc}) — service is up but UNWARMED")
    raise SystemExit(0)

# A synthetic page carrying a small pay table, at production geometry. Content is deliberately
# recognisable as a warmup page so it can never be mistaken for a document in a log.
img = Image.new("RGB", (width, height), (238, 238, 236))
d = ImageDraw.Draw(img)
d.text((40, 50), "WARMUP PAGE - NOT A PENSION DOCUMENT", fill=(120, 120, 120))
rows = [("Basic Pay", "178440"), ("Personal Pay", "13590"),
        ("House Rent Allowance 45%", "13284"), ("Gross Pays and Allowance", "205314")]
y = 160
for label, amount in rows:
    d.text((60, y), label, fill=(20, 20, 20))
    d.text((int(width * 0.68), y), amount, fill=(20, 20, 20))
    d.line((50, y + 28, width - 50, y + 28), fill=(205, 205, 205))
    y += 52

with tempfile.TemporaryDirectory() as tmp:
    page = pathlib.Path(tmp) / "warmup.jpg"
    img.save(page, format="JPEG", quality=72)

    # One request per production schema: no schema's first use should land on a real case.
    failed = []
    for schema in ("AG_PAY_CERTIFICATE", "FORM_D_I", "DESCRIPTIVE_ROLL", "GENERIC_PAGE"):
        try:
            # _retry_on_suspect=False so the warmup REPORTS the first-request defect rather than
            # silently papering over it -- that signal is the whole reason this script exists.
            ext = extract_page(str(page), schema, max_tokens=3000, _retry_on_suspect=False)
            comps = ext.data.get("pay_components") or []
            filled = sum(1 for c in comps if isinstance(c.get("amount_rs"), int))
            state = "amounts read" if (filled or not comps) else "ALL AMOUNTS NULL"
            print(f"warmup: {schema:<20} {ext.latency_s:5.1f}s  {ext.completion_tokens:4d} tok  "
                  f"{len(comps)} rows, {state}")
        except ExtractionError as exc:
            failed.append(schema)
            print(f"warmup: {schema:<20} FAILED — {str(exc)[:150]}")
        except Exception as exc:                                    # noqa: BLE001
            failed.append(schema)
            print(f"warmup: {schema:<20} ERROR — {type(exc).__name__}: {str(exc)[:120]}")

if failed:
    print(f"warmup: PARTIAL — {len(failed)} schema(s) did not warm: {failed}. The service is up, "
          "but the first real case using one of these is still an unwarmed first-of-its-kind "
          "request; the client's all-amounts-null retry guard is the remaining defence.")
else:
    print(f"warmup: OK — {width}x{height} page pushed through every production schema")
PY
echo "warmup: done"
