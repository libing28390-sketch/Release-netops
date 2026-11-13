#!/usr/bin/env bash
# Read-only Docker diagnostics. Usage: bash collect_container_errors.sh [2h] [20000|all]
set -u
set -o pipefail
umask 077

since="${1:-2h}"
tail_lines="${2:-20000}"
if [[ "$tail_lines" != all && ! "$tail_lines" =~ ^[1-9][0-9]*$ ]]; then
  printf 'The second argument must be a positive row count or all.\n' >&2
  exit 2
fi
if ! docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
  printf 'Docker daemon is unavailable or access is denied.\n' >&2
  exit 1
fi

until_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
report_dir="docker-diagnostics-$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$report_dir"
printf 'Since=%s Until=%s TailPerContainer=%s\n' "$since" "$until_time" "$tail_lines" > "$report_dir/scope.txt"
docker ps -a --format '{{.ID}} {{.Names}}' > "$report_dir/containers.txt"
: > "$report_dir/status.txt"
: > "$report_dir/error-summary.txt"
pattern='error|exception|traceback|fatal|panic|out of memory|oom|killed process'

while read -r container_id container_name; do
  [[ -n "$container_id" ]] || continue
  docker inspect --format '{{.Name}} Status={{.State.Status}} OOM={{.State.OOMKilled}} Exit={{.State.ExitCode}} Restarts={{.RestartCount}} MemoryLimitBytes={{.HostConfig.Memory}} NanoCPUs={{.HostConfig.NanoCpus}} CPUQuota={{.HostConfig.CpuQuota}} CPUPeriod={{.HostConfig.CpuPeriod}} LogDriver={{.HostConfig.LogConfig.Type}} LogMaxSize={{index .HostConfig.LogConfig.Config "max-size"}} LogMaxFile={{index .HostConfig.LogConfig.Config "max-file"}} Started={{.State.StartedAt}} Finished={{.State.FinishedAt}}' \
    "$container_id" >> "$report_dir/status.txt" 2>&1
  log_file="$report_dir/$container_name.log"
  if ! docker logs --since "$since" --until "$until_time" --tail "$tail_lines" --timestamps "$container_id" > "$log_file" 2>&1; then
    printf '%s: docker logs failed; see its log file.\n' "$container_name" >> "$report_dir/error-summary.txt"
  fi
  error_count="$(grep -Eic "$pattern" "$log_file" || true)"
  printf '%s MatchingLines=%s\n' "$container_name" "$error_count" >> "$report_dir/error-summary.txt"
  grep -Ein -B 2 -A 4 "$pattern" "$log_file" > "$report_dir/$container_name.errors.txt" || true
done < "$report_dir/containers.txt"

docker stats --no-stream > "$report_dir/stats.txt" 2>&1
docker events --since "$since" --until "$until_time" \
  --filter type=container --filter event=oom --filter event=die --filter event=restart \
  --format '{{json .}}' > "$report_dir/events.jsonl" 2>&1
cat "$report_dir/status.txt" "$report_dir/error-summary.txt" "$report_dir/stats.txt"
printf '\nSaved to %s\n' "$report_dir"
printf 'Docker retains only the latest 256 events. Keyword matches are log lines, not distinct failures.\n'
printf 'The default tail cap is 20000 lines per container; use the second argument all to remove that cap.\n'
