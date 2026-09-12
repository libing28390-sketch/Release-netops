#!/usr/bin/env bash
# ============================================================
#  NetOps Automation — production preflight check
#
#  Runs a battery of read-only checks against the current host /
#  database and prints a colored "PASS / WARN / FAIL" report. Exits
#  non-zero if any FAIL items are found, so this script is safe to
#  wire into CI or a release pipeline.
#
#  Usage:
#    cd /opt/nexora-automation
#    bash scripts/preflight-check.sh
# ============================================================

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

PASS_COUNT=0; WARN_COUNT=0; FAIL_COUNT=0

pass() { echo -e " ${GREEN}✓${NC}  $*"; PASS_COUNT=$((PASS_COUNT + 1)); }
warn() { echo -e " ${YELLOW}⚠${NC}  $*"; WARN_COUNT=$((WARN_COUNT + 1)); }
fail() { echo -e " ${RED}✗${NC}  $*"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
hdr()  { echo -e "\n${CYAN}── $* ──${NC}"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

ENV_FILE="$PROJECT_DIR/.env"

echo "============================================================"
echo "  NetOps Automation — Preflight Check"
echo "  Project: $PROJECT_DIR"
echo "  Time:    $(date)"
echo "============================================================"

# ─────────────────────────────────────────────────────────
# 1. .env file presence
# ─────────────────────────────────────────────────────────
hdr "Environment file"

if [ ! -f "$ENV_FILE" ]; then
    fail ".env not found at $ENV_FILE"
    fail "Run deploy-ubuntu.sh or copy .env.example → .env and fill in real secrets."
    echo
    echo "Cannot continue without .env."
    exit 1
fi
pass ".env exists at $ENV_FILE"

# Source it so we can inspect specific keys without exposing them.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# ─────────────────────────────────────────────────────────
# 2. Secrets — must not be placeholders
# ─────────────────────────────────────────────────────────
hdr "Secret values"

is_placeholder() {
    local v="${1-}"
    [ -z "$v" ] && return 0
    case "$v" in
        *__CHANGE_ME__*|*replace-with-*|*change-me-to-*|*your-secret-key-here*|*supersecret*) return 0 ;;
    esac
    return 1
}

if is_placeholder "${CREDENTIAL_ENCRYPTION_KEY-}"; then
    fail "CREDENTIAL_ENCRYPTION_KEY is a placeholder — generate with: openssl rand -hex 32"
elif [ "${#CREDENTIAL_ENCRYPTION_KEY}" -lt 24 ]; then
    fail "CREDENTIAL_ENCRYPTION_KEY is shorter than 24 chars (weak)."
else
    pass "CREDENTIAL_ENCRYPTION_KEY looks non-default (length=${#CREDENTIAL_ENCRYPTION_KEY})"
fi

if is_placeholder "${SECRET_KEY-}"; then
    warn "SECRET_KEY is a placeholder — generate with: openssl rand -hex 32"
elif [ "${#SECRET_KEY}" -lt 24 ]; then
    warn "SECRET_KEY is shorter than 24 chars."
else
    pass "SECRET_KEY looks non-default (length=${#SECRET_KEY})"
fi

if [ -n "${DATABASE_URL-}" ] && echo "$DATABASE_URL" | grep -q "__CHANGE_ME__\|YOUR_PASSWORD\|postgres:postgres@"; then
    fail "DATABASE_URL contains a placeholder or default 'postgres:postgres' credentials."
else
    pass "DATABASE_URL appears to use a non-default credential."
fi

# ─────────────────────────────────────────────────────────
# 3. PostgreSQL — connectivity and key migrations
# ─────────────────────────────────────────────────────────
hdr "PostgreSQL"

if ! command -v psql > /dev/null 2>&1; then
    warn "psql client not found — cannot verify database state."
else
    if [ -n "${DATABASE_URL-}" ]; then
        if PGPASSWORD="" psql "$DATABASE_URL" -c '\q' > /dev/null 2>&1; then
            pass "Connected to database via DATABASE_URL"
            DB_OK=1
        else
            fail "Cannot connect to database via DATABASE_URL"
            DB_OK=0
        fi
    else
        warn "DATABASE_URL is empty — skipping DB checks."
        DB_OK=0
    fi

    if [ "${DB_OK:-0}" = "1" ]; then
        # Performance indexes
        IDX_COUNT=$(psql "$DATABASE_URL" -tAc "
            SELECT COUNT(*) FROM pg_indexes
            WHERE indexname IN (
                'idx_jobs_created_at','idx_jobs_device_id','idx_jobs_status',
                'idx_config_snapshots_device_ts','idx_config_snapshots_timestamp',
                'idx_playbook_executions_created_at','idx_playbook_executions_status',
                'idx_playbook_executions_scenario',
                'idx_devices_status','idx_devices_asset_id','idx_devices_site',
                'idx_scripts_updated_at','idx_scripts_status',
                'idx_alert_events_device_id'
            );" 2>/dev/null | tr -d ' ')
        if [ "${IDX_COUNT:-0}" = "14" ]; then
            pass "All 14 performance indexes present"
        elif [ "${IDX_COUNT:-0}" -gt 0 ] 2>/dev/null; then
            warn "Only ${IDX_COUNT}/14 performance indexes present — restart backend to run init_db() migration."
        else
            fail "Performance indexes missing — backend hasn't migrated yet. Restart the netops service."
        fi

        # PAM soft-delete FK
        FK_OK=$(psql "$DATABASE_URL" -tAc "
            SELECT COUNT(*) FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            WHERE t.relname IN ('pam_sessions','pam_access_requests')
              AND c.contype = 'f'
              AND pg_get_constraintdef(c.oid) ILIKE '%asset_id%physical_assets%SET NULL%';" 2>/dev/null | tr -d ' ')
        if [ "${FK_OK:-0}" -ge 2 ] 2>/dev/null; then
            pass "PAM soft-delete FK migrated (ON DELETE SET NULL)"
        elif [ "${FK_OK:-0}" -ge 1 ] 2>/dev/null; then
            warn "PAM soft-delete partially migrated (${FK_OK}/2 tables)."
        else
            warn "PAM soft-delete FK not migrated yet — first restart will apply it."
        fi
    fi
fi

# ─────────────────────────────────────────────────────────
# 4. Backend service health
# ─────────────────────────────────────────────────────────
hdr "Backend service"

PORT="${PORT:-8003}"
if curl -sf "http://127.0.0.1:${PORT}/api/health" > /dev/null 2>&1; then
    pass "Backend responds on http://127.0.0.1:${PORT}/api/health"
else
    warn "Backend not responding on port ${PORT} — service may be down or the port differs."
fi

# ─────────────────────────────────────────────────────────
# 5. Default admin password
# ─────────────────────────────────────────────────────────
hdr "Default admin password"

if curl -sf -X POST "http://127.0.0.1:${PORT}/api/login" \
        -H 'Content-Type: application/json' \
        -d '{"username":"admin","password":"admin"}' \
        -o /dev/null 2>/dev/null; then
    fail "admin / admin still works — change the admin password immediately via the UI."
else
    pass "Default admin password rejected (or backend unreachable — see above)."
fi

# ─────────────────────────────────────────────────────────
# 6. HTTPS / Nginx
# ─────────────────────────────────────────────────────────
hdr "HTTPS"

if command -v nginx > /dev/null 2>&1; then
    if grep -rq "ssl_certificate" /etc/nginx/sites-enabled/ 2>/dev/null; then
        pass "Nginx is configured with TLS (ssl_certificate found)"
    else
        warn "No ssl_certificate directive in /etc/nginx/sites-enabled — service is HTTP-only."
        warn "Run: sudo certbot --nginx -d <your-domain>  to enable HTTPS."
    fi
else
    warn "Nginx not detected — TLS termination is your responsibility (e.g. Caddy / cloud LB)."
fi

# ─────────────────────────────────────────────────────────
# 7. Backup configuration
# ─────────────────────────────────────────────────────────
hdr "Backups"

if [ -f /etc/cron.daily/netops-backup ]; then
    pass "Daily PG backup cron job present"
else
    warn "No /etc/cron.daily/netops-backup — set up automated PG dumps."
fi

# ─────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────
echo
echo "============================================================"
echo "  Summary:  ${GREEN}${PASS_COUNT} pass${NC}   ${YELLOW}${WARN_COUNT} warn${NC}   ${RED}${FAIL_COUNT} fail${NC}"
echo "============================================================"

if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0
