from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _request() -> Request:
    return Request({
        "type": "http",
        "headers": [],
        "client": ("127.0.0.1", 8080),
    })


def test_refresh_wan_device_interfaces_uses_scoped_options_and_returns_fresh_ports(monkeypatch) -> None:
    from api import monitoring
    from services import interface_collection_service, wan_circuit_service

    scope = SimpleNamespace(tenant_id="tenant-a", site_ids=("site-a",))
    user = {"role": "Operator", "tenant_id": "tenant-a", "username": "operator-a"}
    device = {"id": "device-a", "site_id": "site-a", "hostname": "edge-a"}
    interfaces = [{"id": "interface-a", "device_id": "device-a", "interface_name": "GigabitEthernet0/0", "if_index": 19}]
    option_calls = []
    audit_calls = []

    monkeypatch.setattr(monitoring, "_wan_effective_scope", lambda _user, action: (option_calls.append(("scope", action)) or scope))
    monkeypatch.setattr(
        wan_circuit_service,
        "list_wan_link_options_scoped",
        lambda **kwargs: option_calls.append(("options", kwargs)) or {"devices": [device], "interfaces": interfaces},
    )
    monkeypatch.setattr(
        interface_collection_service,
        "refresh_snmp_interface_inventory",
        lambda device_id: {"device_id": device_id, "interface_count": 1, "updated_count": 1},
    )
    monkeypatch.setattr(monitoring, "_outbound_audit", lambda *args, **kwargs: audit_calls.append((args, kwargs)))

    result = monitoring.refresh_monitoring_wan_device_interfaces(
        "device-a", _request(), action="create", user=user,
    )

    assert result == {"success": True, "device_id": "device-a", "interfaces": interfaces, "total": 1}
    assert option_calls[0] == ("scope", "create")
    assert all(call[1]["tenant_id"] == "tenant-a" and call[1]["site_ids"] == ("site-a",) for call in option_calls[1:])
    assert audit_calls[0][1]["details"] == {"interface_count": 1, "updated_count": 1}


def test_refresh_wan_device_interfaces_hides_devices_outside_effective_scope(monkeypatch) -> None:
    from api import monitoring
    from services import interface_collection_service, wan_circuit_service

    scope = SimpleNamespace(tenant_id="tenant-a", site_ids=("site-a",))
    monkeypatch.setattr(monitoring, "_wan_effective_scope", lambda *_args: scope)
    monkeypatch.setattr(wan_circuit_service, "list_wan_link_options_scoped", lambda **_kwargs: {"devices": [], "interfaces": []})
    monkeypatch.setattr(interface_collection_service, "refresh_snmp_interface_inventory", lambda _device_id: pytest.fail("out-of-scope device must not be polled"))

    with pytest.raises(HTTPException) as error:
        monitoring.refresh_monitoring_wan_device_interfaces(
            "device-outside-scope", _request(), action="create", user={"role": "Operator"},
        )

    assert error.value.status_code == 404


def test_refresh_wan_device_interfaces_returns_safe_snmp_error(monkeypatch) -> None:
    from api import monitoring
    from services import interface_collection_service, wan_circuit_service

    scope = SimpleNamespace(tenant_id="tenant-a", site_ids=("site-a",))
    device = {"id": "device-a", "site_id": "site-a", "hostname": "edge-a"}
    monkeypatch.setattr(monitoring, "_wan_effective_scope", lambda *_args: scope)
    monkeypatch.setattr(wan_circuit_service, "list_wan_link_options_scoped", lambda **_kwargs: {"devices": [device], "interfaces": []})

    def fail_snmp(_device_id):
        raise interface_collection_service.InterfaceInventorySyncError(
            "snmp_interface_read_failed",
            "读取设备端口失败，请检查 SNMP 连通性和只读权限。",
        )

    monkeypatch.setattr(interface_collection_service, "refresh_snmp_interface_inventory", fail_snmp)

    with pytest.raises(HTTPException) as error:
        monitoring.refresh_monitoring_wan_device_interfaces(
            "device-a", _request(), action="create", user={"role": "Operator"},
        )

    assert error.value.status_code == 502
    assert error.value.detail == "读取设备端口失败，请检查 SNMP 连通性和只读权限。"
