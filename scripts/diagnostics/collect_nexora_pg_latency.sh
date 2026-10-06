#!/usr/bin/env bash
# Copy this file and nexora_pg_latency.py together to the Linux Docker host.
set -uo pipefail

DURATION_SECONDS="${DURATION_SECONDS:-90}"
SAMPLE_SECONDS="${SAMPLE_SECONDS:-1}"
COLLECT_PLANS="${COLLECT_PLANS:-0}"
if ! [[ "$DURATION_SECONDS" =~ ^[0-9]{1,3}$ && "$SAMPLE_SECONDS" =~ ^[0-9]{1,2}$ ]] ||
   (( 10#$DURATION_SECONDS < 1 || 10#$DURATION_SECONDS > 600 ||
      10#$SAMPLE_SECONDS < 1 || 10#$SAMPLE_SECONDS > 10 )) ||
   ! [[ "$COLLECT_PLANS" =~ ^[01]$ ]]; then
    echo "Use duration 1..600s, sample interval 1..10s, COLLECT_PLANS=0 or 1" >&2
    exit 2
fi
command -v docker >/dev/null || { echo "Run on the Linux Docker host" >&2; exit 2; }
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 2
HELPER="$SCRIPT_DIR/nexora_pg_latency.py"
[[ -r "$HELPER" ]] || { echo "Copy nexora_pg_latency.py beside this script" >&2; exit 2; }
OUTPUT_FILE="${1:-/tmp/nexora-pg-latency-$(date '+%Y%m%d_%H%M%S').jsonl}"
RESOURCE_FILE="${OUTPUT_FILE%.jsonl}.resources.jsonl"
umask 077
(set -o noclobber; : > "$OUTPUT_FILE") || exit 1
(set -o noclobber; : > "$RESOURCE_FILE") || exit 1
echo "Collecting for ${DURATION_SECONDS}s; reproduce one slow operation; output=$OUTPUT_FILE"
sample_resources() {
    local end=$(( SECONDS + 10#$DURATION_SECONDS )) observed
    while (( SECONDS < end )); do
        observed="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        docker stats --no-stream --format \
          '{"kind":"docker_resources","observed_at":"'"$observed"'","name":"{{.Name}}","cpu":"{{.CPUPerc}}","memory":"{{.MemUsage}}","pids":"{{.PIDs}}","block_io":"{{.BlockIO}}"}' \
          nexora-netops nexora-db nexora-nginx nexora-grafana nexora-victoriametrics \
          nexora-vmagent nexora-snmp-exporter >> "$RESOURCE_FILE" 2>/dev/null || return
        sleep 5
    done
}
sample_resources &
resource_pid=$!
stop_resources() {
    kill "$resource_pid" 2>/dev/null || true
    wait "$resource_pid" 2>/dev/null || true
}
trap stop_resources EXIT
# Credentials stay inside the backend container. stderr is omitted because a
# Docker/runtime failure can include configuration; Python emits safe errors.
docker exec -i nexora-netops python - "$DURATION_SECONDS" "$SAMPLE_SECONDS" "$COLLECT_PLANS" \
    < "$HELPER" > "$OUTPUT_FILE" 2>/dev/null
result=$?
if (( result != 0 )); then
    echo "Collector exited $result. Preserve the partial log: $OUTPUT_FILE" >&2
    exit "$result"
fi
echo "Finished. Send both files: $OUTPUT_FILE and $RESOURCE_FILE"
