#!/usr/bin/env bash
set -Eeuo pipefail

# Run bounded, read-only probes against each active Nexora Compose service.
# These probes check reachability and light load, not capacity or suitable limits.
# The default mode only prints the planned probes; pass --run to generate load.

readonly DEFAULT_DURATION=15
readonly DEFAULT_CONCURRENCY=4
readonly DEFAULT_RPS=20
readonly DEFAULT_SAMPLE_INTERVAL=1
readonly LOAD_IMAGE_CONTAINER="nexora-netops"

DURATION="$DEFAULT_DURATION"
CONCURRENCY="$DEFAULT_CONCURRENCY"
RPS="$DEFAULT_RPS"
SAMPLE_INTERVAL="$DEFAULT_SAMPLE_INTERVAL"
OUTPUT_DIR=""
RUN_TESTS=0
CURRENT_RUNNER_NAME=""
SAMPLE_FILE=""

die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage:
  bash scripts/stress-test-docker.sh [options]

The default is a dry run. Pass --run to send probes to the Docker services.

Options:
  --run                    Execute the workloads (otherwise show the plan)
  --dry-run                Show the plan without contacting Docker (default)
  --duration SECONDS       Duration per HTTP/PostgreSQL/Redis service (5..60, default: 15)
  --concurrency N          Concurrent clients per service (1..16, default: 4)
  --rps N                  Total request rate per service (1..100, default: 20)
  --sample-interval SEC    docker stats sampling interval (1..10, default: 1)
  --output-dir PATH        Report directory (default: /tmp/nexora-docker-stress-<UTC time>)
  -h, --help               Show this help

This is a reachability and light-load precheck, not a capacity benchmark.
Successful probes do not establish safe CPU/memory limits or production capacity.
The script probes the configured Nexora services, one at a time.
It uses read-only requests: PostgreSQL SELECT 1, Redis PING, HTTP health/query/
metrics endpoints, and a SeaweedFS S3 root GET. It does not write application
data, poll real SNMP devices, pull images, or change container limits.

HTTP request generation uses the already-installed nexora-netops image in a
temporary container capped at 0.5 CPU and 192 MiB. CPU/memory/network/block-I/O
stats for the target container are sampled into a CSV file during each stage.
The load can still affect service latency while it runs; use a maintenance window
or staging deployment for higher settings.

Examples:
  bash scripts/stress-test-docker.sh
  bash scripts/stress-test-docker.sh --run
  bash scripts/stress-test-docker.sh --run --duration 30 --concurrency 8 --rps 50
EOF
}

is_uint() {
    [[ "$1" =~ ^[0-9]+$ ]]
}

while (($#)); do
    case "$1" in
        --run)
            RUN_TESTS=1
            shift
            ;;
        --dry-run)
            RUN_TESTS=0
            shift
            ;;
        --duration)
            (($# >= 2)) || die "--duration requires a value"
            DURATION="$2"
            shift 2
            ;;
        --concurrency)
            (($# >= 2)) || die "--concurrency requires a value"
            CONCURRENCY="$2"
            shift 2
            ;;
        --rps)
            (($# >= 2)) || die "--rps requires a value"
            RPS="$2"
            shift 2
            ;;
        --sample-interval)
            (($# >= 2)) || die "--sample-interval requires a value"
            SAMPLE_INTERVAL="$2"
            shift 2
            ;;
        --output-dir)
            (($# >= 2)) || die "--output-dir requires a path"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown option: $1 (use --help)"
            ;;
    esac
done

is_uint "$DURATION" && ((DURATION >= 5 && DURATION <= 60)) || die "--duration must be an integer from 5 to 60"
is_uint "$CONCURRENCY" && ((CONCURRENCY >= 1 && CONCURRENCY <= 16)) || die "--concurrency must be an integer from 1 to 16"
is_uint "$RPS" && ((RPS >= 1 && RPS <= 100)) || die "--rps must be an integer from 1 to 100"
is_uint "$SAMPLE_INTERVAL" && ((SAMPLE_INTERVAL >= 1 && SAMPLE_INTERVAL <= 10)) || die "--sample-interval must be an integer from 1 to 10"

cat <<EOF
Nexora Docker per-container reachability and light-load precheck
  Scope:       Probe results cannot determine suitable CPU/memory limits
  Duration:    ${DURATION}s per service
  Concurrency: ${CONCURRENCY} clients
  Rate cap:    ${RPS} requests/second per service
  Execution:   $([[ "$RUN_TESTS" == 1 ]] && printf 'RUN' || printf 'DRY RUN')

  nexora-db                    PostgreSQL read-only SELECT 1
  nexora-netops                GET /api/health/live
  nexora-victoriametrics       GET /api/v1/query?query=up
  nexora-snmp-exporter         GET /metrics (no device polling)
  nexora-vmagent               GET /metrics
  nexora-docker-socket-proxy   GET /_ping
  nexora-cadvisor              GET /metrics
  nexora-grafana               GET /api/health
  nexora-nginx                 GET / (expect 301; do not follow HTTPS redirect)
  nexora-redis                 Redis PING (no key writes)
  nexora-seaweedfs             S3 GET / (no object writes)
EOF

if ((RUN_TESTS == 0)); then
    printf '\nDry run only; pass --run to execute these bounded workloads.\n'
    exit 0
fi

command -v docker >/dev/null 2>&1 || die "Docker CLI is required on the deployment host"
docker info >/dev/null 2>&1 || die "Cannot access the Docker daemon; check the active context and Docker permissions"

OUTPUT_DIR="${OUTPUT_DIR:-/tmp/nexora-docker-stress-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p -- "$OUTPUT_DIR"
SAMPLE_FILE="$OUTPUT_DIR/container-stats.csv"
printf 'timestamp_utc,service,container,phase,cpu_percent,memory_usage,memory_percent,net_io,block_io,pids\n' > "$SAMPLE_FILE"

container_state() {
    docker inspect --format '{{.State.Status}}' "$1" 2>/dev/null || true
}

container_network() {
    docker inspect --format '{{range $name, $network := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$1" 2>/dev/null | head -n 1
}

container_env_value() {
    local container="$1" key="$2"
    docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container" |
        awk -v key="$key" 'index($0, key "=") == 1 { value = substr($0, length(key) + 2); found = 1 } END { if (!found) exit 1; printf "%s", value }'
}

sample_stats() {
    local service="$1" container="$2" phase="$3" stats cpu memory memory_percent net_io block_io pids
    stats="$(docker stats --no-stream --format '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}|{{.PIDs}}' "$container" 2>/dev/null || true)"
    [[ -n "$stats" ]] || return 0
    IFS='|' read -r cpu memory memory_percent net_io block_io pids <<< "$stats"
    printf '"%s","%s","%s","%s","%s","%s","%s","%s","%s","%s"\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$service" "$container" "$phase" \
        "$cpu" "$memory" "$memory_percent" "$net_io" "$block_io" "$pids" >> "$SAMPLE_FILE"
}

cleanup() {
    if [[ -n "$CURRENT_RUNNER_NAME" ]]; then
        docker rm -f "$CURRENT_RUNNER_NAME" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

LOAD_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$LOAD_IMAGE_CONTAINER" 2>/dev/null)" ||
    die "The running $LOAD_IMAGE_CONTAINER container is required as a local Python load-generator image"
docker image inspect "$LOAD_IMAGE" >/dev/null 2>&1 || die "Load-generator image is not available locally: $LOAD_IMAGE"

LOAD_GENERATOR="$(cat <<'PY'
import json
import math
import os
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


# Keep each probe on its intended target; Nginx HTTP intentionally redirects to TLS.
# Docker service aliases must connect directly even if the image has proxy variables.
DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirectHandler())
mode = os.environ["NEXORA_TEST_MODE"]
service = os.environ["NEXORA_TEST_SERVICE"]
duration = int(os.environ["NEXORA_TEST_DURATION"])
concurrency = int(os.environ["NEXORA_TEST_CONCURRENCY"])
rps = int(os.environ["NEXORA_TEST_RPS"])
deadline = time.monotonic() + duration
password = os.environ.get("NEXORA_STRESS_SECRET", "")
allowed_statuses = {int(value) for value in os.environ.get("NEXORA_TEST_ALLOWED_STATUSES", "200").split(",")}
lock = threading.Lock()
schedule_lock = threading.Lock()
next_slot = [time.monotonic()]
latencies = []
statuses = {}
errors = []
attempts = 0


def record(started, status, error=None):
    global attempts
    elapsed_ms = (time.monotonic() - started) * 1000.0
    with lock:
        attempts += 1
        latencies.append(elapsed_ms)
        if status is not None:
            key = str(status)
            statuses[key] = statuses.get(key, 0) + 1
        if error:
            error_text = str(error)
            if password:
                error_text = error_text.replace(password, "[REDACTED]")
            errors.append(error_text[:240])


def reserve_slot():
    with schedule_lock:
        now = time.monotonic()
        slot = max(now, next_slot[0])
        if slot >= deadline:
            return None
        next_slot[0] = slot + 1.0 / rps
        return slot


def open_client():
    if mode == "postgres":
        import psycopg2
        return psycopg2.connect(
            host=os.environ["NEXORA_TEST_HOST"],
            port=int(os.environ["NEXORA_TEST_PORT"]),
            user=os.environ["NEXORA_TEST_USER"],
            password=password or None,
            dbname=os.environ["NEXORA_TEST_DATABASE"],
            application_name="nexora-container-stress",
            connect_timeout=4,
            options="-c default_transaction_read_only=on -c statement_timeout=3000",
        )
    if mode == "redis":
        import redis
        # The nexora Redis ACL allows PING but does not grant CLIENT SETNAME.
        return redis.Redis(
            host=os.environ["NEXORA_TEST_HOST"],
            port=int(os.environ["NEXORA_TEST_PORT"]),
            username="nexora",
            password=password or None,
            socket_connect_timeout=4,
            socket_timeout=4,
            decode_responses=True,
        )
    return None


def perform_http():
    started = time.monotonic()
    url = os.environ["NEXORA_TEST_URL"]
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "nexora-container-stress/1.0", "Connection": "close"})
    try:
        with DIRECT_OPENER.open(request, timeout=4) as response:
            response.read()
            status = response.status
        record(started, status, None if status in allowed_statuses else f"unexpected HTTP {status}")
    except urllib.error.HTTPError as exc:
        exc.read()
        record(started, exc.code, None if exc.code in allowed_statuses else f"HTTP {exc.code}")
    except Exception as exc:
        record(started, None, f"{type(exc).__name__}: {exc}")


def worker(_worker_id):
    try:
        client = open_client()
    except Exception as exc:
        record(time.monotonic(), None, f"connect {type(exc).__name__}: {exc}")
        return
    try:
        while True:
            slot = reserve_slot()
            if slot is None:
                break
            delay = slot - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            if time.monotonic() >= deadline:
                break
            started = time.monotonic()
            try:
                if mode == "http":
                    perform_http()
                    continue
                if mode == "postgres":
                    with client.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        cursor.fetchone()
                elif mode == "redis":
                    client.ping()
                record(started, "ok")
            except Exception as exc:
                record(started, None, f"{type(exc).__name__}: {exc}")
    finally:
        try:
            if mode == "postgres":
                client.close()
            elif mode == "redis":
                client.close()
        except Exception:
            pass


with ThreadPoolExecutor(max_workers=concurrency) as executor:
    futures = [executor.submit(worker, worker_id) for worker_id in range(concurrency)]
    for future in futures:
        future.result()

ordered = sorted(latencies)


def percentile(fraction):
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return round(ordered[index], 2)


summary = {
    "test_scope": "reachability_and_light_load",
    "capacity_validated": False,
    "service": service,
    "mode": mode,
    "target": f"{os.environ['NEXORA_TEST_HOST']}:{os.environ['NEXORA_TEST_PORT']}" + os.environ.get("NEXORA_TEST_PATH", ""),
    "duration_seconds": duration,
    "concurrency": concurrency,
    "rate_limit_rps": rps,
    "requests": attempts,
    "errors": len(errors),
    "status_counts": statuses,
    "latency_ms": {
        "min": round(min(ordered), 2) if ordered else 0.0,
        "mean": round(statistics.mean(ordered), 2) if ordered else 0.0,
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "max": round(max(ordered), 2) if ordered else 0.0,
    },
    "error_samples": errors[:5],
}
print(json.dumps(summary, ensure_ascii=False))
raise SystemExit(1 if errors or attempts == 0 else 0)
PY
)"

run_stage() {
    local service="$1" container="$2" network="$3" mode="$4" host="$5" port="$6" path="$7" allowed_statuses="$8"
    local runner_name stage_log password="" user="" database="" result=0 runner_pid
    runner_name="nexora-stress-$$-${service//[^a-zA-Z0-9]/-}"
    stage_log="$OUTPUT_DIR/${service}.jsonl"

    case "$mode" in
        postgres)
            user="$(container_env_value "$container" POSTGRES_USER)" || die "Cannot read PostgreSQL user from $container"
            database="$(container_env_value "$container" POSTGRES_DB)" || die "Cannot read PostgreSQL database name from $container"
            password="$(container_env_value "$container" POSTGRES_PASSWORD)" || die "Cannot read PostgreSQL password from $container"
            ;;
        redis)
            password="$(container_env_value "$container" REDIS_PASSWORD || true)"
            ;;
    esac

    sample_stats "$service" "$container" before
    printf '\n[RUN] %s via %s network (%ss, concurrency=%s, cap=%s rps)\n' "$service" "$network" "$DURATION" "$CONCURRENCY" "$RPS"
    CURRENT_RUNNER_NAME="$runner_name"

    (
        export NEXORA_STRESS_SECRET="$password"
        docker run --rm --name "$runner_name" --pull=never \
            --network "$network" --cpus 0.5 --memory 192m --pids-limit 32 \
            --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
            --env HTTP_PROXY= --env HTTPS_PROXY= --env ALL_PROXY= \
            --env http_proxy= --env https_proxy= --env all_proxy= \
            --env NO_PROXY=localhost,127.0.0.1,db,netops,victoriametrics,snmp-exporter,vmagent,docker-socket-proxy,cadvisor,grafana,nginx,redis,seaweedfs \
            --env no_proxy=localhost,127.0.0.1,db,netops,victoriametrics,snmp-exporter,vmagent,docker-socket-proxy,cadvisor,grafana,nginx,redis,seaweedfs \
            --env "NEXORA_TEST_MODE=$mode" \
            --env "NEXORA_TEST_SERVICE=$service" \
            --env "NEXORA_TEST_DURATION=$DURATION" \
            --env "NEXORA_TEST_CONCURRENCY=$CONCURRENCY" \
            --env "NEXORA_TEST_RPS=$RPS" \
            --env "NEXORA_TEST_HOST=$host" \
            --env "NEXORA_TEST_PORT=$port" \
            --env "NEXORA_TEST_PATH=$path" \
            --env "NEXORA_TEST_ALLOWED_STATUSES=$allowed_statuses" \
            --env "NEXORA_TEST_USER=$user" \
            --env "NEXORA_TEST_DATABASE=$database" \
            --env "NEXORA_TEST_URL=http://$host:$port$path" \
            --env NEXORA_STRESS_SECRET \
            --env PYTHONDONTWRITEBYTECODE=1 \
            --entrypoint python "$LOAD_IMAGE" -c "$LOAD_GENERATOR"
    ) > "$stage_log" 2>&1 &
    runner_pid=$!

    while kill -0 "$runner_pid" 2>/dev/null; do
        if docker inspect "$runner_name" >/dev/null 2>&1; then
            sample_stats "$service" "$container" during
        fi
        sleep "$SAMPLE_INTERVAL"
    done
    wait "$runner_pid" || result=$?
    CURRENT_RUNNER_NAME=""
    sample_stats "$service" "$container" after
    cat "$stage_log"
    if ((result != 0)); then
        printf '[FAIL] %s load generator exited with status %s\n' "$service" "$result" >&2
        return "$result"
    fi
}

run_service_test() {
    local container="$1" mode="$2" host="$3" port="$4" path="$5" allowed_statuses="$6"
    local state network
    state="$(container_state "$container")"
    if [[ "$state" != running ]]; then
        printf '[SKIP] %s is not running (state=%s)\n' "$container" "${state:-missing}"
        return 0
    fi
    network="$(container_network "$container")"
    [[ -n "$network" ]] || { printf '[SKIP] %s has no Docker network\n' "$container"; return 0; }
    run_stage "${container#nexora-}" "$container" "$network" "$mode" "$host" "$port" "$path" "$allowed_statuses"
}

FAILURES=0
run_checked_test() {
    if run_service_test "$@"; then
        return 0
    else
        local status=$?
    fi
    FAILURES=$((FAILURES + 1))
    printf '[FAIL] service stage exited with status %s\n' "$status" >&2
    return 0
}

run_checked_test nexora-db postgres db 5432 "" 200
run_checked_test nexora-netops http netops 8003 /api/health/live 200
run_checked_test nexora-victoriametrics http victoriametrics 8428 '/api/v1/query?query=up' 200
run_checked_test nexora-snmp-exporter http snmp-exporter 9116 /metrics 200
run_checked_test nexora-vmagent http vmagent 8429 /metrics 200
run_checked_test nexora-docker-socket-proxy http docker-socket-proxy 2375 /_ping 200
run_checked_test nexora-cadvisor http cadvisor 8080 /metrics 200
run_checked_test nexora-grafana http grafana 3000 /api/health 200
run_checked_test nexora-nginx http nginx 80 / 301
run_checked_test nexora-redis redis redis 6379 "" 200
run_checked_test nexora-seaweedfs http seaweedfs 8333 / 200,403

printf '\nCompleted. Stats CSV: %s\nPer-service results: %s\n' "$SAMPLE_FILE" "$OUTPUT_DIR"
if ((FAILURES > 0)); then
    printf '[RESULT] %s service stage(s) failed; inspect the JSONL logs.\n' "$FAILURES" >&2
    exit 1
fi
printf '[RESULT] All started probe stages completed without request errors; capacity and limits remain unvalidated.\n'
