#!/bin/bash
# Nightly backup of the SERVE PUNJAB database (24 Oct 2026).
#
# Until today the office had none: no cron job, no timer, archive_mode off, and one dump taken
# by hand on 19 Oct sitting in /root. The database is small -- twelve megabytes -- so the cost
# of this is seconds a night and the cost of not having it is the register.
#
# Run by pension-backup.service, nightly, as root. It needs no password: pg_dump runs as the
# postgres system user over the local socket (peer authentication).
#
#   /opt/pension/current/deploy/backup-db.sh          # the nightly run
#   BACKUP_DIR=/tmp/t deploy/backup-db.sh             # somewhere else, to try it
#
# Settings live in /etc/pension/backup.conf, which is optional:
#   BACKUP_OFFSITE        rsync destination, e.g. agbackup@backup-host.internal:/srv/backups/pension/
#                         Unset means local only, and the script says so every night.
#   BACKUP_SSH_KEY        private key for that destination (default /root/.ssh/id_ed25519)
#   BACKUP_INCLUDE_ENV    1 to include /etc/pension/pension.env, which holds the database
#                         password, the JWT secret and the model API key. The database alone
#                         does not rebuild the system; with this it does. Off by default
#                         because it puts those secrets wherever the offsite copy lives.
set -uo pipefail

CONF=${BACKUP_CONF:-/etc/pension/backup.conf}
# shellcheck disable=SC1090
[[ -r $CONF ]] && source "$CONF"

BACKUP_DIR=${BACKUP_DIR:-/var/backups/pension}
DB=${BACKUP_DB:-pension}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-14}         # every night for a fortnight
KEEP_MONTHLY_DAYS=${BACKUP_KEEP_MONTHLY_DAYS:-365}   # and the first of each month for a year
OFFSITE=${BACKUP_OFFSITE:-}
SSH_KEY=${BACKUP_SSH_KEY:-/root/.ssh/id_ed25519}
INCLUDE_ENV=${BACKUP_INCLUDE_ENV:-0}

say() { printf '%s %s\n' "$(date -Is)" "$*"; }
die() { say "FAILED: $*"; exit 1; }

stamp=$(date +%Y%m%d-%H%M%S)
install -d -m 700 -o root -g root "$BACKUP_DIR" || die "cannot make $BACKUP_DIR"

# -Fc: compressed, and pg_restore can list it, which is how the dump is checked below. A dump
# that cannot be listed is not a backup, it is a file.
out="$BACKUP_DIR/$DB-$stamp.dump"
say "dumping $DB to $out"
if ! sudo -n -u postgres pg_dump -Fc --no-owner --no-privileges "$DB" > "$out" 2>"$out.err"; then
    say "$(tail -3 "$out.err" 2>/dev/null)"
    rm -f "$out" "$out.err"
    die "pg_dump"
fi
rm -f "$out.err"
chmod 600 "$out"

# --list only reads the file, so this runs as root: the dump is 600 root:root and the
# postgres user cannot open it.
tables=$(pg_restore --list "$out" 2>/dev/null | grep -c 'TABLE DATA')
[[ ${tables:-0} -gt 0 ]] || die "the dump holds no table data"
say "dump verified: $tables tables, $(du -h "$out" | cut -f1)"

if [[ $INCLUDE_ENV == 1 && -r /etc/pension/pension.env ]]; then
    cp /etc/pension/pension.env "$BACKUP_DIR/pension.env-$stamp"
    chmod 600 "$BACKUP_DIR/pension.env-$stamp"
    say "included pension.env (holds secrets; BACKUP_INCLUDE_ENV=1)"
fi

# Thin out: drop what is older than KEEP_DAYS unless it is that month's first dump, and drop
# those once they are a year old. -mtime is whole days, which is what nightly means here.
pruned=0
while IFS= read -r -d '' f; do
    base=${f##*/}; day=${base//[!0-9]/}; day=${day:6:2}
    if [[ $day == 01 ]]; then continue; fi
    rm -f "$f" && pruned=$((pruned + 1))
done < <(find "$BACKUP_DIR" -maxdepth 1 -type f \( -name "$DB-*.dump" -o -name 'pension.env-*' \) -mtime "+$KEEP_DAYS" -print0)
while IFS= read -r -d '' f; do
    rm -f "$f" && pruned=$((pruned + 1))
done < <(find "$BACKUP_DIR" -maxdepth 1 -type f \( -name "$DB-*.dump" -o -name 'pension.env-*' \) -mtime "+$KEEP_MONTHLY_DAYS" -print0)
held=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "$DB-*.dump" | wc -l)
say "pruned $pruned, holding $held dumps ($(du -sh "$BACKUP_DIR" | cut -f1))"

# A backup on the same disk as the database is not a backup of the disk.
if [[ -z $OFFSITE ]]; then
    say "NO OFFSITE COPY: set BACKUP_OFFSITE in $CONF. This disk is the only copy."
    exit 0
fi
say "copying to $OFFSITE"
if rsync -a --timeout=120 -e "ssh -i $SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
         "$BACKUP_DIR"/ "$OFFSITE" 2>&1; then
    say "offsite copy done"
else
    die "offsite copy to $OFFSITE"
fi
