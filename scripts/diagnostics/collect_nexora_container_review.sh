#!/usr/bin/env bash
# Run on the Linux Docker host. Read-only; do not install/reset extensions.
set -uo pipefail

DURATION_SECONDS="${DURATION_SECONDS:-60}"
SAMPLE_SECONDS="${SAMPLE_SECONDS:-10}"
if ! [[ "$DURATION_SECONDS" =~ ^[0-9]+$ && "$SAMPLE_SECONDS" =~ ^[0-9]+$ ]] ||
   (( DURATION_SECONDS < 1 || SAMPLE_SECONDS < 1 )); then
    echo "Duration and sample interval must be positive integer seconds" >&2
    exit 2
fi
command -v docker >/dev/null || { echo "Run this on the Linux Docker host" >&2; exit 2; }
OUTPUT_FILE="${1:-/tmp/nexora-container-review-$(date '+%Y%m%d_%H%M%S').log}"
umask 077
# A new file is required, including when the requested path is a symlink.
(set -o noclobber; : > "$OUTPUT_FILE") || exit 1
exec > >(tee -a "$OUTPUT_FILE") 2>&1

pg_read() {
    docker exec -i nexora-db sh -lc \
      'PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000" psql -X -P pager=off -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-netops}" "$@"' nexora-db-review "$@"
}

db_snapshot() {
    pg_read <<'SQL'
SELECT clock_timestamp() AS sampled_at, pg_postmaster_start_time() AS db_started_at;
SELECT stats_reset, numbackends, xact_commit, xact_rollback, blks_read, blks_hit,
       tup_returned, tup_fetched, deadlocks, temp_files, temp_bytes
FROM pg_stat_database WHERE datname = current_database();
SELECT relname, seq_scan, seq_tup_read, idx_scan, idx_tup_fetch,
       n_live_tup, n_dead_tup, last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables
WHERE relname IN ('interface_telemetry_raw', 'interface_telemetry_1m', 'snmp_mib_nodes');
SELECT relname, indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
WHERE relname IN ('interface_telemetry_raw', 'interface_telemetry_1m', 'snmp_mib_nodes')
ORDER BY relname, indexrelname;
SQL
}

sql_cost_snapshot() {
    # Presence and preload are reported separately; an absent/unusable view
    # is recorded as unavailable and never triggers a configuration change.
    local available
    available="$(pg_read -A -t <<'SQL'
SELECT CASE WHEN to_regclass('pg_stat_statements') IS NOT NULL THEN 1 ELSE 0 END;
SQL
    )"
    if ! [[ "$available" =~ (^|[[:space:]])1([[:space:]]|$) ]]; then
        echo "pg_stat_statements view unavailable; SQL cost attribution remains pending"
        return
    fi
    pg_read <<'SQL'
SELECT to_regclass('pg_stat_statements_info') IS NOT NULL AS has_statement_info \gset
\if :has_statement_info
SELECT stats_reset AS statement_stats_reset, dealloc FROM pg_stat_statements_info;
\endif
SELECT queryid, calls, total_exec_time, mean_exec_time, max_exec_time, rows,
       shared_blks_hit, shared_blks_read, temp_blks_written
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC LIMIT 20;
SQL
}

echo "Started: $(date -Is); duration=${DURATION_SECONDS}s; output=$OUTPUT_FILE"
echo "No SQL text, credentials, complete environment, or container logs are collected."
docker inspect --format '{{.Name}} image_id={{.Image}} started={{.State.StartedAt}} oom={{.State.OOMKilled}} restarts={{.RestartCount}} memory={{.HostConfig.Memory}} nano_cpus={{.HostConfig.NanoCpus}} cpu_quota={{.HostConfig.CpuQuota}} cpu_period={{.HostConfig.CpuPeriod}}' \
    nexora-netops nexora-db nexora-nginx nexora-redis nexora-victoriametrics nexora-grafana nexora-seaweedfs
docker exec -i nexora-netops python - <<'PY'
import hashlib, json, os
from pathlib import Path
keys = ('WORKERS', 'DB_POOL_SIZE', 'DB_POOL_MIN_SIZE', 'DB_POOL_OVERFLOW_MAX', 'STORAGE_BACKEND')
print('Runtime settings:', json.dumps({key: os.environ.get(key) for key in keys}))
for name in ('engine/orchestrator.py', 'database/core.py', 'main.py', 'services/background_monitor_service.py'):
    path = Path('/app/backend') / name
    if path.is_file():
        content = path.read_bytes().replace(b'\r\n', b'\n')
        print('Source SHA256 (LF normalized):', name, hashlib.sha256(content).hexdigest())
PY
pg_read <<'SQL'
SHOW server_version;
SHOW shared_preload_libraries;
SHOW compute_query_id;
SHOW track_activities;
SHOW track_counts;
SHOW track_io_timing;
SHOW work_mem;
SHOW shared_buffers;
SHOW max_connections;
SELECT name, default_version, installed_version
FROM pg_available_extensions WHERE name = 'pg_stat_statements';
SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_stat_statements';
SQL

echo "Initial database counters and SQL costs"
db_snapshot
sql_cost_snapshot
END_EPOCH=$(( $(date +%s) + DURATION_SECONDS ))
while (( $(date +%s) < END_EPOCH )); do
    echo "Sample: $(date -Is)"
    docker stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}} pids={{.PIDs}} net={{.NetIO}} block={{.BlockIO}}' \
      nexora-netops nexora-db nexora-nginx nexora-redis nexora-victoriametrics nexora-grafana nexora-seaweedfs
    pg_read <<'SQL'
SELECT clock_timestamp() AS sampled_at, pid, state, wait_event_type, wait_event,
       round(extract(epoch FROM clock_timestamp() - xact_start)::numeric, 2) AS transaction_age_s,
       round(extract(epoch FROM clock_timestamp() - query_start)::numeric, 2) AS query_age_s,
       pg_blocking_pids(pid) AS blocking_pids, substr(md5(query), 1, 12) AS query_hash
FROM pg_stat_activity
WHERE datname = current_database() AND pid != pg_backend_pid()
  AND state IN ('active', 'idle in transaction', 'idle in transaction (aborted)')
ORDER BY xact_start NULLS LAST LIMIT 25;
SELECT state, COUNT(*) AS connections FROM pg_stat_activity
WHERE datname = current_database() AND pid != pg_backend_pid() GROUP BY state;
SQL
    docker exec -i nexora-netops python - <<'PY'
import time, urllib.request
from pathlib import Path
for name in ('/sys/fs/cgroup/cpu.stat', '/sys/fs/cgroup/cpu/cpu.stat', '/sys/fs/cgroup/cpu,cpuacct/cpu.stat', '/sys/fs/cgroup/memory.events'):
    path = Path(name)
    if path.is_file():
        print('netops cgroup:', name, path.read_text().strip().replace('\n', '; '))
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for label, url in (
    ('netops_direct_live', 'http://127.0.0.1:8003/api/health/live'),
    ('victoriametrics_health', 'http://victoriametrics:8428/health'),
    ('grafana_health', 'http://grafana:3000/api/health'),
):
    started = time.perf_counter()
    try:
        with opener.open(url, timeout=5) as response:
            response.read()
            outcome = f'http={response.status}'
    except Exception as exc:
        outcome = f'error_type={type(exc).__name__}'
    print(label, outcome, f'elapsed_ms={(time.perf_counter()-started)*1000:.1f}')
PY
    if command -v curl >/dev/null; then
        curl --noproxy '*' -k -sS -o /dev/null --connect-timeout 2 --max-time 6 \
          -w 'nginx_live http=%{http_code} connect_s=%{time_connect} first_byte_s=%{time_starttransfer} total_s=%{time_total}\n' \
          https://127.0.0.1/api/health/live || true
    fi
    remaining=$(( END_EPOCH - $(date +%s) ))
    (( remaining > 0 )) || break
    (( remaining < SAMPLE_SECONDS )) && sleep "$remaining" || sleep "$SAMPLE_SECONDS"
done
echo "Final database counters and SQL costs"
db_snapshot
sql_cost_snapshot
echo "Finished: $(date -Is); send this log: $OUTPUT_FILE"
