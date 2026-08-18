#!/usr/bin/env bash
# ============================================================
#  Install a daily PostgreSQL backup cron job for NetOps.
#
#  Run as root (or via sudo) on the production server. Reads the
#  DATABASE_URL from /opt/nexora-automation/.env automatically.
#
#  Backups land in /var/backups/netops/, kept for 30 days. The database dump
#  uses PostgreSQL custom format so it can be restored with pg_restore into an
#  explicitly isolated rehearsal database.
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
OUT="\$BACKUP_DIR/netops-\$TS.dump"
PARTIAL_OUT="\$OUT.partial"

if pg_dump --format=custom --no-owner --file "\$PARTIAL_OUT" "\$DATABASE_URL"; then
    if [ ! -s "\$PARTIAL_OUT" ]; then
        echo "[netops-backup] pg_dump produced an empty dump" >&2
        rm -f "\$PARTIAL_OUT"
        exit 1
    fi
    mv -f "\$PARTIAL_OUT" "\$OUT"
    echo "[netops-backup] wrote \$OUT (\$(du -h "\$OUT" | cut -f1))"
else
    echo "[netops-backup] pg_dump failed" >&2
    rm -f "\$PARTIAL_OUT" "\$OUT"
    exit 1
fi

# Export a deterministic, redacted Knowledge Engine source manifest beside the
# dump.  It contains hashes/counts only; the source content and credentials
# never enter the manifest.  A missing runtime is a hard failure so a backup
# without its restore-verification companion cannot be mistaken for complete.
MANIFEST_OUT="\$BACKUP_DIR/netops-\$TS.source-manifest.json"
if [ -x "\$PROJECT_DIR/.venv/bin/python" ] && PYTHONPATH="\$PROJECT_DIR/backend" "\$PROJECT_DIR/.venv/bin/python" -m database.backup manifest --output "\$MANIFEST_OUT"; then
    if [ ! -s "\$MANIFEST_OUT" ]; then
        echo "[netops-backup] source manifest is empty" >&2
        rm -f "\$OUT" "\$MANIFEST_OUT"
        exit 1
    fi
    echo "[netops-backup] wrote \$MANIFEST_OUT"
else
    echo "[netops-backup] source manifest export failed" >&2
    rm -f "\$OUT" "\$MANIFEST_OUT"
    exit 1
fi

# Preserve the deployment configuration needed for a rollback. The archive is
# private (it may contain the encrypted runtime .env) and is never printed or
# included in the redacted Source Manifest. Optional paths are included only
# when present so a minimal server installation remains valid.
CONFIG_OUT="\$BACKUP_DIR/netops-\$TS.config.tar.gz"
CONFIG_PARTIAL="\$CONFIG_OUT.partial"
CONFIG_ENTRIES=(.env)
[ -f "\$PROJECT_DIR/.env.example" ] && CONFIG_ENTRIES+=(.env.example)
[ -d "\$PROJECT_DIR/nginx/ssl" ] && CONFIG_ENTRIES+=(nginx/ssl)
[ -f "\$PROJECT_DIR/desktop/desktop_settings.ini" ] && CONFIG_ENTRIES+=(desktop/desktop_settings.ini)
if tar -czf "\$CONFIG_PARTIAL" -C "\$PROJECT_DIR" "\${CONFIG_ENTRIES[@]}"; then
    if [ ! -s "\$CONFIG_PARTIAL" ]; then
        echo "[netops-backup] configuration archive is empty" >&2
        rm -f "\$OUT" "\$MANIFEST_OUT" "\$CONFIG_PARTIAL"
        exit 1
    fi
    chmod 600 "\$CONFIG_PARTIAL"
    mv -f "\$CONFIG_PARTIAL" "\$CONFIG_OUT"
    echo "[netops-backup] wrote \$CONFIG_OUT"
else
    echo "[netops-backup] configuration archive failed" >&2
    rm -f "\$OUT" "\$MANIFEST_OUT" "\$CONFIG_PARTIAL" "\$CONFIG_OUT"
    exit 1
fi

# Retain only the last RETENTION_DAYS days.
find "\$BACKUP_DIR" -maxdepth 1 -type f -name 'netops-*.dump' -mtime +\$RETENTION_DAYS -delete
find "\$BACKUP_DIR" -maxdepth 1 -type f -name 'netops-*.source-manifest.json' -mtime +\$RETENTION_DAYS -delete
find "\$BACKUP_DIR" -maxdepth 1 -type f -name 'netops-*.config.tar.gz' -mtime +\$RETENTION_DAYS -delete
EOF

chmod 755 /etc/cron.daily/netops-backup

echo "Installed /etc/cron.daily/netops-backup"
echo "Backups will land in: $BACKUP_DIR (keeping last $RETENTION_DAYS days)"
echo
echo "To run a backup right now (verify everything works):"
echo "    sudo /etc/cron.daily/netops-backup"
