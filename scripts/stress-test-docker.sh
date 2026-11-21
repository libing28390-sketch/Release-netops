#!/usr/bin/env bash
set -Eeuo pipefail

# Host orchestration uses only Python's standard library. Protocol clients run
# in the deployment's existing netops image; no pip install or image pull occurs.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == --probe ]]; then
    shift
    exec bash "$SCRIPT_DIR/stress-test-docker-probe.sh" "$@"
fi
command -v python3 >/dev/null 2>&1 || {
    printf '[ERROR] Python 3.10+ is required on the Docker host.\n' >&2
    exit 2
}
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 2)' || {
    printf '[ERROR] Python 3.10+ is required on the Docker host.\n' >&2
    exit 2
}
exec python3 "$SCRIPT_DIR/docker_capacity/main.py" "$@"
