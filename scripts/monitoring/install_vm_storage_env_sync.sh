#!/usr/bin/env bash
set -Eeuo pipefail

die() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

project_dir="${1:-${NETOPS_DIR:-$PWD}}"
project_dir="$(cd "$project_dir" && pwd -P)"
env_file="$project_dir/.env"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
helper_source="$script_dir/sync_vm_storage_env.py"
runtime_volume="${NEXORA_VM_RUNTIME_VOLUME:-nexora-vm-runtime}"
unit_name="nexora-vm-storage-env-sync"
helper_install_path="/usr/local/libexec/nexora-vm-storage-env-sync.py"
settings_path="/etc/nexora-vm-storage-env-sync.json"
service_path="/etc/systemd/system/${unit_name}.service"
path_unit_path="/etc/systemd/system/${unit_name}.path"

[[ "$(id -u)" -eq 0 ]] || die "Run this installer as root so it can update the deployment .env safely."
[[ -d /run/systemd/system ]] || die "systemd is not active; host .env synchronization cannot be installed."
command -v docker >/dev/null 2>&1 || die "Docker CLI is required to locate the runtime volume."
command -v systemctl >/dev/null 2>&1 || die "systemctl is required."
command -v python3 >/dev/null 2>&1 || die "Python 3 is required for the restricted .env updater."
[[ -f "$env_file" && ! -L "$env_file" ]] || die "The deployment .env must exist as a regular file."
[[ -f "$helper_source" ]] || die "The .env sync helper is missing from the deployment source."

runtime_dir="$(docker volume inspect --format '{{.Mountpoint}}' "$runtime_volume" 2>/dev/null || true)"
[[ "$runtime_dir" == /* && -d "$runtime_dir" ]] || die "The VictoriaMetrics runtime volume is unavailable."
combined_paths="$project_dir$runtime_dir"
for unsafe_character in ' ' $'\t' $'\n' '"' "'" '%' '$' '\\'; do
  [[ "$combined_paths" != *"$unsafe_character"* ]] || die "Project and Docker volume paths cannot contain whitespace, quotes, percent signs, dollar signs, or backslashes."
done

# Create the stable file before enabling its path watcher. The API updates this
# inode in place so systemd.path sees each completed request reliably.
trigger_path="$runtime_dir/env-sync-trigger"
if [[ ! -e "$trigger_path" ]]; then
  install -o 1000 -g 1000 -m 0664 /dev/null "$trigger_path"
else
  [[ -f "$trigger_path" && ! -L "$trigger_path" ]] || die "The host sync trigger is not a regular file."
  chown 1000:1000 "$trigger_path"
  chmod 0664 "$trigger_path"
fi

install -d -m 0755 /usr/local/libexec
install -m 0755 "$helper_source" "$helper_install_path"

python3 - "$settings_path" "$env_file" "$runtime_dir" <<'PY'
import json
import os
import sys

path, env_file, runtime_dir = sys.argv[1:]
temporary = f"{path}.tmp.{os.getpid()}"
with open(temporary, "w", encoding="utf-8") as output:
    json.dump({"env_file": env_file, "runtime_dir": runtime_dir}, output, separators=(",", ":"))
    output.write("\n")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
PY

cat > "$service_path" <<EOF
[Unit]
Description=Synchronize VictoriaMetrics disk threshold to deployment .env
After=local-fs.target

[Service]
Type=oneshot
User=root
Group=root
Environment=NEXORA_VM_ENV_SYNC_SETTINGS=$settings_path
ExecStart=/usr/bin/python3 $helper_install_path
UMask=0077
PrivateNetwork=yes
PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
RestrictSUIDSGID=yes
LockPersonality=yes
ReadWritePaths=$project_dir $runtime_dir
EOF

cat > "$path_unit_path" <<EOF
[Unit]
Description=Watch VictoriaMetrics threshold sync requests

[Path]
PathChanged=$runtime_dir/env-sync-trigger
Unit=${unit_name}.service

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "${unit_name}.path"
systemctl restart "${unit_name}.path"

# Reconcile the current persistent value before marking the sync service ready.
# This updates a stale .env on first install while leaving the running value
# and container untouched when both files already agree.
if [[ -f "$runtime_dir/min-free-disk-space-bytes" ]]; then
  NEXORA_VM_ENV_SYNC_SETTINGS="$settings_path" python3 "$helper_install_path" --reconcile \
    || die "Could not synchronize the current VictoriaMetrics threshold to .env."
fi

ready_tmp="$runtime_dir/.env-sync-ready.tmp.$$"
printf 'READY\n' > "$ready_tmp"
chown 1000:1000 "$ready_tmp"
chmod 0664 "$ready_tmp"
mv -f "$ready_tmp" "$runtime_dir/env-sync-ready"
printf '[NetOps] Host .env threshold synchronization is ready.\n'
