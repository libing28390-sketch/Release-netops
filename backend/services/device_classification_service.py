"""Shared asset classification used at cross-domain read boundaries."""

from __future__ import annotations

from typing import Any


_SERVER_PLATFORMS = {
    "linux", "ubuntu", "centos", "debian", "redhat", "windows",
    "vmware", "esxi", "windows_server", "linux_server",
}
_SERVER_ROLES = {"server", "host", "vm", "virtual-machine", "hypervisor", "storage"}
_SERVER_LABELS = ("server", "服务器", "虚拟机", "主机", "hypervisor", "esxi", "vmware")


def is_server_device(device: dict[str, Any]) -> bool:
    """Classify an inventory device as a server/host rather than a network node."""
    platform = str(device.get("platform") or "").strip().casefold().replace("-", "_")
    role = str(device.get("role") or device.get("role_identity") or "").strip().casefold().replace("_", "-")
    if platform in _SERVER_PLATFORMS or role in _SERVER_ROLES:
        return True
    return any(
        marker in str(device.get(field) or "").strip().casefold()
        for field in ("device_category", "platform")
        for marker in _SERVER_LABELS
    )


def server_device_sql(alias: str = "d") -> str:
    """Return a SQL predicate matching :func:`is_server_device` for DB rows.

    ``alias`` is an internal SQL identifier selected by the caller, never user
    input.  Keep it in sync with the Python classifier above.
    """
    columns = ("device_category", "platform")
    text_match = " OR ".join(
        f"LOWER(COALESCE({alias}.{column}, '')) LIKE ?" for column in columns for _ in _SERVER_LABELS
    )
    platform_values = ", ".join(f"'{value}'" for value in sorted(_SERVER_PLATFORMS))
    return (
        f"({alias}.platform IS NOT NULL AND LOWER(REPLACE({alias}.platform, '-', '_')) IN ({platform_values}) "
        f"OR LOWER(REPLACE(COALESCE({alias}.role, ''), '_', '-')) IN ({', '.join(repr(value) for value in sorted(_SERVER_ROLES))}) "
        f"OR {text_match})"
    )


def server_device_sql_params() -> tuple[str, ...]:
    return tuple(f"%{marker}%" for _field in ("device_category", "platform") for marker in _SERVER_LABELS)
