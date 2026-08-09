#!/usr/bin/env bash
# ============================================================
#  Install a daily PostgreSQL backup cron job for NetOps.
#
#  Run as root (or via sudo) on the production server. Reads the
#  DATABASE_URL from /opt/nexora-automation/.env automatically.
#
#  Backups land in /var/backups/netops/, kept for 30 days.
# ============================================================

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/nexora-automation}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/netops}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root (or via sudo)." >&2
    exit 1
fi

if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "Cannot find $PROJECT_DIR/.env — set PROJECT_DIR=<path> if the install is elsewhere." >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
chmod 750 "$BACKUP_DIR"

# Extract DATABASE_URL into a clean form. We don't write it into the cron
# script (which lives in /etc); we write a small wrapper that re-reads
# the .env at runtime so password rotations are picked up automatically.
cat > /etc/cron.daily/netops-backup <<EOF
#!/usr/bin/env bash
# NetOps Automation — daily PG dump (installed by install-daily-backup.sh)
set -euo pipefail

PROJECT_DIR="$PROJECT_DIR"
BACKUP_DIR="$BACKUP_DIR"
RETENTION_DAYS=$RETENTION_DAYS

if [ ! -f "\$PROJECT_DIR/.env" ]; then
    echo "[netops-backup] missing \$PROJECT_DIR/.env, aborting." >&2
    exit 1
fi

# shellcheck disable=SC1090
set -a; source "\$PROJECT_DIR/.env"; set +a

mkdir -p "\$BACKUP_DIR"
TS=\$(date +%F-%H%M)
OUT="\$BACKUP_DIR/netops-\$TS.sql.gz"

if pg_dump "\$DATABASE_URL" 2>/dev/null | gzip -9 > "\$OUT"; then
    echo "[netops-backup] wrote \$OUT (\$(du -h "\$OUT" | cut -f1))"
else
    echo "[netops-backup] pg_dump failed" >&2
    rm -f "\$OUT"
    exit 1
fi

# Export a deterministic, redacted Knowledge Engine source manifest beside the
# dump.  It contains hashes/counts only; the source content and credentials
# never enter the manifest.  A missing runtime is a hard failure so a backup
# without its restore-verification companion cannot be mistaken for complete.
MANIFEST_OUT="\$BACKUP_DIR/netops-\$TS.source-manifest.json"
if [ -x "\$PROJECT_DIR/.venv/bin/python" ] && PYTHONPATH="\$PROJECT_DIR/backend" "\$PROJECT_DIR/.venv/bin/python" -m database.backup manifest --output "\$MANIFEST_OUT"; then
    echo "[netops-backup] wrote \$MANIFEST_OUT"
else
    echo "[netops-backup] source manifest export failed" >&2
    rm -f "\$OUT" "\$MANIFEST_OUT"
    exit 1
fi

# Retain only the last RETENTION_DAYS days.
find "\$BACKUP_DIR" -maxdepth 1 -type f -name 'netops-*.sql.gz' -mtime +\$RETENTION_DAYS -delete
find "\$BACKUP_DIR" -maxdepth 1 -type f -name 'netops-*.source-manifest.json' -mtime +\$RETENTION_DAYS -delete
EOF

chmod 755 /etc/cron.daily/netops-backup

echo "Installed /etc/cron.daily/netops-backup"
echo "Backups will land in: $BACKUP_DIR (keeping last $RETENTION_DAYS days)"
echo
echo "To run a backup right now (verify everything works):"
echo "    sudo /etc/cron.daily/netops-backup"
