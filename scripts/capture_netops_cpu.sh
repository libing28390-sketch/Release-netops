#!/usr/bin/env bash
# Read-only sampling on the Linux Docker host. No installs or container changes.
set -uo pipefail
umask 077
container="${1:-nexora-netops}"
seconds="${2:-60}"
if [[ ! "$seconds" =~ ^[0-9]+$ ]] || (( seconds < 10 || seconds > 300 )); then
  echo 'Duration must be 10..300 seconds.' >&2
  exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
  echo 'Docker is required on the deployment host.' >&2
  exit 1
fi
output="netops-cpu-$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p -- "$output"
docker inspect --format '{{.Name}} PID={{.State.Pid}} Status={{.State.Status}} OOM={{.State.OOMKilled}} Restarts={{.RestartCount}}' "$container" > "$output/container.txt" || exit 1
docker top "$container" -eo pid,ppid,pcpu,comm > "$output/processes.txt" || exit 1
mapfile -t python_pids < <(awk 'NR>1 && ($4 ~ /python/ || $4 ~ /uvicorn/ || $4 ~ /gunicorn/) {print $1}' "$output/processes.txt")
jobs_to_wait=()
for process_id in "${python_pids[@]}"; do
  if [[ ! "$process_id" =~ ^[0-9]+$ ]]; then continue; fi
  if command -v top >/dev/null 2>&1; then
    top -b -H -d 5 -n "$((seconds / 5 + 1))" -p "$process_id" > "$output/threads-$process_id.txt" 2>&1 &
    jobs_to_wait+=("$!")
  fi
  if command -v py-spy >/dev/null 2>&1; then
    # No --locals: do not capture credentials in Python local variables.
    py-spy record --pid "$process_id" --duration "$seconds" --rate 49 --format raw -o "$output/stacks-$process_id.txt" > "$output/profiler-$process_id.txt" 2>&1 &
    jobs_to_wait+=("$!")
  fi
done
if ! command -v py-spy >/dev/null 2>&1; then
  echo 'py-spy is not installed: process/thread samples only; no function profile.' > "$output/profiler-status.txt"
fi
deadline=$((SECONDS + seconds))
while (( SECONDS < deadline )); do
  date -u '+%Y-%m-%dT%H:%M:%SZ' >> "$output/samples.txt"
  docker stats --no-stream --format '{{.Name}} CPU={{.CPUPerc}} MEM={{.MemUsage}} PIDS={{.PIDs}}' "$container" >> "$output/samples.txt" 2>&1
  docker top "$container" -eo pid,ppid,pcpu,comm >> "$output/samples.txt" 2>&1
  sleep 5
done
for sampler_job in "${jobs_to_wait[@]}"; do wait "$sampler_job" || true; done
tar -czf "$output.tar.gz" -- "$output"
echo "Saved $output.tar.gz"
