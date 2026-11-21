#!/usr/bin/env bash

# Capture a bounded five-minute Docker/API/PostgreSQL performance snapshot.
# Run this on the Linux host that runs the Nexora Compose stack.

set -uo pipefail

DURATION_SECONDS="${DURATION_SECONDS:-300}"
SAMPLE_SECONDS="${SAMPLE_SECONDS:-5}"
DB_SAMPLE_SECONDS="${DB_SAMPLE_SECONDS:-15}"
CONTAINERS=(nexora-netops nexora-db nexora-redis nexora-vmagent nexora-nginx)

STAMP="$(date '+%Y%m%d_%H%M%S')"
OUTPUT_FILE="${1:-/tmp/nexora-perf-${STAMP}.log}"
OUTPUT_DIR="$(dirname "$OUTPUT_FILE")"

if ! [[ "$DURATION_SECONDS" =~ ^[0-9]+$ ]] || (( DURATION_SECONDS < 1 )); then
    echo "DURATION_SECONDS must be a positive integer" >&2
    exit 2
fi
if ! [[ "$SAMPLE_SECONDS" =~ ^[0-9]+$ ]] || (( SAMPLE_SECONDS < 1 )); then
    echo "SAMPLE_SECONDS must be a positive integer" >&2
    exit 2
fi
if ! [[ "$DB_SAMPLE_SECONDS" =~ ^[0-9]+$ ]] || (( DB_SAMPLE_SECONDS < 1 )); then
    echo "DB_SAMPLE_SECONDS must be a positive integer" >&2
    exit 2
fi

mkdir -p "$OUTPUT_DIR" || exit 1
if [[ -e "$OUTPUT_FILE" ]]; then
    echo "Refusing to overwrite existing log: $OUTPUT_FILE" >&2
    exit 1
fi
umask 077
: > "$OUTPUT_FILE" || exit 1
chmod 600 "$OUTPUT_FILE" 2>/dev/null || true
exec > >(tee -a "$OUTPUT_FILE") 2>&1

START_EPOCH="$(date +%s)"
START_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
END_EPOCH=$((START_EPOCH + DURATION_SECONDS))
NEXT_DB_SAMPLE="$START_EPOCH"
NEXT_STATS_SAMPLE="$START_EPOCH"

echo "Nexora performance capture"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S %z')"
echo "Duration: ${DURATION_SECONDS}s; Docker sample: ${SAMPLE_SECONDS}s; PostgreSQL sample: ${DB_SAMPLE_SECONDS}s"
echo "Output: $OUTPUT_FILE"
echo "Sensitive query text is not recorded; PostgreSQL statements are represented by a short MD5 fingerprint."

echo
echo "=== Host and container limits ==="
hostname 2>&1 || true
date '+%Y-%m-%d %H:%M:%S %z' 2>&1 || true
uptime 2>&1 || true
nproc 2>&1 || true
free -h 2>&1 || true
docker inspect --format '{{.Name}} memory_bytes={{.HostConfig.Memory}} nano_cpus={{.HostConfig.NanoCpus}} cpu_quota={{.HostConfig.CpuQuota}} cpu_period={{.HostConfig.CpuPeriod}}' "${CONTAINERS[@]}" 2>&1 || true
docker top nexora-netops -eo pid,ppid,stat,%cpu,%mem,comm,args 2>&1 || true

sample_database_activity() {
    echo
    echo "=== PostgreSQL sessions at $(date '+%Y-%m-%d %H:%M:%S %z') ==="
    echo "sample_time|pid|application|state|xact_age_s|state_age_s|query_age_s|wait_type|wait_event|blocking_pids|query_hash"
    docker exec -i nexora-db sh -lc 'psql -X -A -t -F "|" -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT
    to_char(clock_timestamp(), 'YYYY-MM-DD"T"HH24:MI:SSOF'),
    pid,
    replace(coalesce(application_name, ''), '|', '/'),
    coalesce(state, ''),
    coalesce(round(extract(epoch FROM clock_timestamp() - xact_start)::numeric, 1)::text, ''),
    coalesce(round(extract(epoch FROM clock_timestamp() - state_change)::numeric, 1)::text, ''),
    coalesce(round(extract(epoch FROM clock_timestamp() - query_start)::numeric, 1)::text, ''),
    coalesce(wait_event_type, ''),
    coalesce(wait_event, ''),
    coalesce(array_to_string(pg_blocking_pids(pid), ','), ''),
    substr(md5(coalesce(query, '')), 1, 12)
FROM pg_stat_activity
WHERE datname = current_database()
  AND (state = 'active' OR state = 'idle in transaction')
ORDER BY (state = 'idle in transaction') DESC, xact_start NULLS LAST, query_start NULLS LAST;
SQL
    local result=$?
    if (( result != 0 )); then
        echo "PostgreSQL sample failed (exit=$result)"
    fi
}

echo
echo "=== Repeated resource samples ==="
while (( $(date +%s) < END_EPOCH )); do
    SAMPLE_EPOCH="$(date +%s)"
    echo
    echo "--- Docker stats at $(date '+%Y-%m-%d %H:%M:%S %z') ---"
    docker stats --no-stream --format 'name={{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}} pids={{.PIDs}} net={{.NetIO}} block={{.BlockIO}}' "${CONTAINERS[@]}" 2>&1 || true

    if (( SAMPLE_EPOCH >= NEXT_DB_SAMPLE )); then
        sample_database_activity
        NEXT_DB_SAMPLE=$((SAMPLE_EPOCH + DB_SAMPLE_SECONDS))
    fi

    NEXT_STATS_SAMPLE=$((NEXT_STATS_SAMPLE + SAMPLE_SECONDS))
    NOW_EPOCH="$(date +%s)"
    if (( NOW_EPOCH >= NEXT_STATS_SAMPLE )); then
        NEXT_STATS_SAMPLE=$((NOW_EPOCH + SAMPLE_SECONDS))
    fi
    if (( NEXT_STATS_SAMPLE > END_EPOCH )); then
        NEXT_STATS_SAMPLE="$END_EPOCH"
    fi
    SLEEP_SECONDS=$((NEXT_STATS_SAMPLE - NOW_EPOCH))
    if (( SLEEP_SECONDS > 0 )); then
        sleep "$SLEEP_SECONDS"
    fi
done

END_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo
echo "=== Application slow-request and worker warnings (${START_UTC} to ${END_UTC}) ==="
if docker logs --timestamps --since "$START_UTC" --until "$END_UTC" nexora-netops 2>&1 \
    | grep -E 'Route: |PG pool exhausted|skipped: maximum number of running instances|deadlock detected|lock timeout|locator.*(failed|deferred|timeout)' ; then
    :
else
    echo "No matching application log lines were returned for this interval."
fi

echo
echo "Finished: $(date '+%Y-%m-%d %H:%M:%S %z')"
echo "Log saved to: $OUTPUT_FILE"
