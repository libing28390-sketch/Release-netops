from __future__ import annotations

import pytest

from services import background_monitor_service as monitor
from services import snmp_hardware_inventory_service as inventory
from services.snmp_discovery_service import HARDWARE_DISCOVERY_VERSION


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("capabilities", "expected_stale"),
    [
        ([], True),
        ([{"discovery_version": "nexora.hardware.discovery.v1"}], True),
        ([{"discovery_version": "older.hardware.discovery"}], True),
        ([{"discovery_version": HARDWARE_DISCOVERY_VERSION}], False),
    ],
)
def test_hardware_discovery_refreshes_missing_or_outdated_capabilities(
    monkeypatch,
    capabilities: list[dict[str, str]],
    expected_stale: bool,
) -> None:
    connection = _Connection()
    monkeypatch.setattr(monitor, "get_db_connection", lambda: connection)
    monkeypatch.setattr(
        inventory,
        "list_hardware_capabilities",
        lambda _connection, device_id: capabilities if device_id == "device-1" else [],
    )

    assert monitor._hardware_inventory_discovery_is_stale("device-1") is expected_stale
    assert connection.closed is True
