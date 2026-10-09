#!/usr/bin/env bash
# A consistent dump of the PostgreSQL database, kept 30 deep (9 Oct 2026: the move to PostgreSQL
# left the trial with no scheduled backup; the only copy was the one taken before the import).
#
#   deploy/pg-backup.sh                 # one dump now, into artifacts/backups/pg/
#   deploy/pg-backup.sh install-cron    # nightly at 02:30 in this user's crontab (trial box)
#
# Reads PENSION_DATABASE_URL from the environment or deploy/postgres.env. Dumps with the server's
# own pg_dump when the pension-postgres container is running (no client needed on the box), else
# with pg_dump on PATH. Every dump is read back with pg_restore --list before the old ones go.
# Production: the same script from /etc/pension/pension.env, writing to /var/backups/pension
# (PENSION_BACKUP_DIR); docs/DEPLOYMENT.md §7.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${PENSION_DATABASE_URL:-}" ]]; then
  for f in /etc/pension/pension.env "$ROOT/deploy/postgres.env"; do
    if [[ -r "$f" ]]; then
      PENSION_DATABASE_URL="$(sed -n 's/^PENSION_DATABASE_URL=//p' "$f" | tail -1)"
      [[ -n "$PENSION_DATABASE_URL" ]] && break
    fi
  done
fi
[[ -n "${PENSION_DATABASE_URL:-}" ]] || { echo "pg-backup: PENSION_DATABASE_URL is not set" >&2; exit 2; }
DEST="${PENSION_BACKUP_DIR:-$ROOT/artifacts/backups/pg}"
KEEP="${PENSION_BACKUP_KEEP:-30}"

if [[ "${1:-}" == "install-cron" ]]; then
  line="30 2 * * * $ROOT/deploy/pg-backup.sh >> $ROOT/artifacts/logs/pg-backup.log 2>&1"
  # `grep -v` answers 1 when nothing is left (an empty crontab), which pipefail would turn into a
  # silent exit before the line was written (found 9 Oct 2026); `|| true` keeps the pipe going.
  ( crontab -l 2>/dev/null | grep -v "deploy/pg-backup.sh" || true ; echo "$line" ) | crontab -
  echo "installed: $line"; exit 0
fi

mkdir -p "$DEST" "$ROOT/artifacts/logs"; chmod 700 "$DEST"
stamp="$(date +%F-%H%M%S)"
out="$DEST/portal-$stamp.dump"
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx pension-postgres; then
  # Inside the container: the URL's host is the box, so dump by name through the socket.
  db="${PENSION_DATABASE_URL##*/}"; db="${db%%\?*}"
  user="$(sed -n 's#^[a-z]*://\([^:/@]*\).*#\1#p' <<<"$PENSION_DATABASE_URL")"
  docker exec pension-postgres pg_dump -U "$user" -Fc "$db" > "$out.tmp"
  docker exec -i pension-postgres pg_restore --list < "$out.tmp" > /dev/null
else
  pg_dump -Fc "$PENSION_DATABASE_URL" > "$out.tmp"
  pg_restore --list "$out.tmp" > /dev/null
fi
chmod 600 "$out.tmp"; mv "$out.tmp" "$out"
echo "$(date -Is) wrote $out ($(du -h "$out" | cut -f1))"
# Retention: the newest KEEP dumps stay.
ls -1t "$DEST"/portal-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
