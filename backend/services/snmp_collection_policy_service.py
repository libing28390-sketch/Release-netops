"""Shared device-level policy for automatic SNMP collection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_FALSE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})


def is_snmp_collection_enabled(device: Any) -> bool:
    """Return whether automatic SNMP collection is enabled for a device.

    Missing or null values are treated as enabled so old records, cached
    payloads, and test fixtures retain the pre-switch behavior.
    """
    if isinstance(device, Mapping):
        value = device.get("snmp_collection_enabled", True)
    else:
        value = getattr(device, "snmp_collection_enabled", True)
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().casefold() not in _FALSE_VALUES
