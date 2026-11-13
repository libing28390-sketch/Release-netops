#!/bin/sh

# Runs VictoriaMetrics as a child process and applies an updated disk threshold
# from the shared runtime volume without granting the web application Docker
# socket access. On a settings change, it gracefully stops VictoriaMetrics and
# exits so Docker's existing restart policy restarts the whole container.

set -u
umask 0002

RUNTIME_DIR="${MONITORING_VM_RUNTIME_DIR:-/var/lib/nexora-vm-runtime}"
REQUEST_FILE="$RUNTIME_DIR/min-free-disk-space-bytes"
ACTIVE_FILE="$RUNTIME_DIR/active-min-free-disk-space-bytes"
ACTIVE_GENERATION_FILE="$RUNTIME_DIR/active-generation"
STATE_FILE="$RUNTIME_DIR/runtime-state"
ERROR_FILE="$RUNTIME_DIR/runtime-error-code"
RESTARTED_FILE="$RUNTIME_DIR/last-restart-at"
DEFAULT_VALUE="${VM_MIN_FREE_DISK_SPACE_BYTES:-10737418240}"
MIN_FREE_BYTES=536870912
MAX_FREE_BYTES=17592186044416
VM_PID=""
ACTIVE_VALUE=""
ACTIVE_GENERATION=""
FAILED_GENERATION=""

write_file() {
  wf_target="$1"
  wf_value="$2"
  wf_temporary="$wf_target.tmp.$$"
  printf '%s\n' "$wf_value" > "$wf_temporary" || return 1
  mv -f "$wf_temporary" "$wf_target" || return 1
  chmod 664 "$wf_target" 2>/dev/null || true
}

write_state() {
  state="$1"
  error_code="${2:-}"
  write_file "$STATE_FILE" "$state"
  write_file "$ERROR_FILE" "$error_code"
}

is_allowed_value() {
  value="$1"
  case "$value" in
    ''|*[!0-9]*) return 1 ;;
  esac
  [ "$value" -ge "$MIN_FREE_BYTES" ] 2>/dev/null && [ "$value" -le "$MAX_FREE_BYTES" ] 2>/dev/null
}

if ! is_allowed_value "$DEFAULT_VALUE"; then
  DEFAULT_VALUE=10737418240
fi

read_requested_config() {
  REQUESTED_VALUE="$DEFAULT_VALUE"
  REQUESTED_GENERATION="default:$DEFAULT_VALUE"
  if [ -f "$REQUEST_FILE" ]; then
    file_value="$(sed -n '1p' "$REQUEST_FILE" 2>/dev/null || true)"
    file_generation="$(sed -n '2p' "$REQUEST_FILE" 2>/dev/null || true)"
    if is_allowed_value "$file_value"; then
      REQUESTED_VALUE="$file_value"
      REQUESTED_GENERATION="${file_generation:-config:$file_value}"
    fi
  fi
  case "$REQUESTED_GENERATION" in
    *[!A-Za-z0-9._:-]*) REQUESTED_GENERATION="config:$REQUESTED_VALUE" ;;
  esac
}

stop_vm() {
  [ -n "$VM_PID" ] || return 0
  if kill -0 "$VM_PID" 2>/dev/null; then
    kill -TERM "$VM_PID" 2>/dev/null || true
    attempts=0
    while kill -0 "$VM_PID" 2>/dev/null && [ "$attempts" -lt 90 ]; do
      sleep 1
      attempts=$((attempts + 1))
    done
    if kill -0 "$VM_PID" 2>/dev/null; then
      kill -KILL "$VM_PID" 2>/dev/null || true
    fi
  fi
  wait "$VM_PID" 2>/dev/null || true
  VM_PID=""
}

shutdown() {
  trap - TERM INT
  write_state STOPPING
  stop_vm
  exit 0
}

launch_vm() {
  launch_threshold="$1"
  launch_generation="$2"
  shift 2
  write_state STARTING
  /victoria-metrics-prod "$@" "-storage.minFreeDiskSpaceBytes=$launch_threshold" &
  VM_PID=$!
  sleep 1
  if kill -0 "$VM_PID" 2>/dev/null; then
    ACTIVE_VALUE="$launch_threshold"
    ACTIVE_GENERATION="$launch_generation"
    write_file "$ACTIVE_FILE" "$ACTIVE_VALUE"
    write_file "$ACTIVE_GENERATION_FILE" "$ACTIVE_GENERATION"
    write_file "$RESTARTED_FILE" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    write_state RUNNING
    FAILED_GENERATION=""
    return 0
  fi
  wait "$VM_PID" 2>/dev/null || true
  VM_PID=""
  ACTIVE_VALUE=""
  ACTIVE_GENERATION=""
  write_file "$ACTIVE_FILE" ""
  write_file "$ACTIVE_GENERATION_FILE" ""
  FAILED_GENERATION="$launch_generation"
  write_state FAILED PROCESS_START_FAILED
  return 1
}

trap shutdown TERM INT

while :; do
  read_requested_config

  if [ -n "$VM_PID" ] && ! kill -0 "$VM_PID" 2>/dev/null; then
    wait "$VM_PID" 2>/dev/null || true
    VM_PID=""
    ACTIVE_VALUE=""
    ACTIVE_GENERATION=""
    write_file "$ACTIVE_FILE" ""
    write_file "$ACTIVE_GENERATION_FILE" ""
    write_state FAILED PROCESS_EXITED
    FAILED_GENERATION=""
    sleep 5
    continue
  fi

  if [ "$REQUESTED_GENERATION" != "$ACTIVE_GENERATION" ] && [ "$REQUESTED_GENERATION" != "$FAILED_GENERATION" ]; then
    if [ -n "$VM_PID" ]; then
      write_state RESTARTING
      stop_vm
      ACTIVE_VALUE=""
      ACTIVE_GENERATION=""
      write_file "$ACTIVE_FILE" ""
      write_file "$ACTIVE_GENERATION_FILE" ""
      write_state RESTARTING
      # The Compose service uses restart: unless-stopped. Exiting PID 1 asks
      # Docker to recreate this container with the persisted runtime setting.
      exit 75
    fi
    launch_vm "$REQUESTED_VALUE" "$REQUESTED_GENERATION" "$@" || true
  fi

  sleep 1
done
