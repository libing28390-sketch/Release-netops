#!/usr/bin/env bash
set -euo pipefail

PORT="${NEXORA_AGENT_PORT:-17890}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_FILE="$SERVICE_DIR/nexora-terminal-agent.service"

if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "python3 is required" >&2
  exit 1
fi

mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Nexora local Terminal Agent
After=network-online.target

[Service]
Type=simple
ExecStart=$PYTHON_BIN $PROJECT_ROOT/scripts/terminal_agent.py --host 127.0.0.1 --port $PORT
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now nexora-terminal-agent.service
echo "Nexora Terminal Agent started on http://127.0.0.1:$PORT"
curl -fsS "http://127.0.0.1:$PORT/health"
