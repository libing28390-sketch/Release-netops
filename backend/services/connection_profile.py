from __future__ import annotations

from typing import Any, Mapping


def resolve_ssh_port(device_info: Mapping[str, Any] | None, default: int = 22) -> int:
    """Resolve the SSH management port from CMDB/device payloads.

    Canonical field is ``management_port``. ``port``, ``ssh_port`` and
    ``target_port`` are compatibility aliases for older automation payloads,
    driver calls, and PAM session snapshots.
    """
    data = device_info or {}
    raw = (
        data.get("management_port")
        or data.get("port")
        or data.get("ssh_port")
        or data.get("target_port")
        or default
    )
    try:
        port = int(raw)
    except (TypeError, ValueError):
        return default
    return port if 1 <= port <= 65535 else default
