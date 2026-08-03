import asyncio

import pytest


def test_inspection_uses_registry_for_exact_published_command(monkeypatch):
    from services import inspection_service

    monkeypatch.setattr(
        "services.platform_registry_service.resolve_device_action_code",
        lambda _device_id, _command: "get_clock",
    )
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {"success": True, "raw_output": "12:00:00 UTC\n"},
    )

    output = inspection_service._netmiko_collect(
        {"id": "device-1", "platform_profile_id": "profile-1", "tenant_id": "tenant-1"},
        ["show clock"],
    )
    assert output == {"show clock": "12:00:00 UTC\n"}


def test_topology_uses_registry_lldp_for_bound_device(monkeypatch):
    from services import topology_service

    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "records": [{
                "local_interface": "Gi1/0/1",
                "neighbor": "edge-2",
                "neighbor_interface": "Gi1/0/2",
            }],
        },
    )

    observations, method = asyncio.run(
        topology_service._collect_neighbors_with_netmiko(
            {"id": "device-1", "platform_profile_id": "profile-1", "tenant_id": "tenant-1"},
            [],
        )
    )
    assert method == "platform-registry"
    assert observations[0]["neighbor_name_raw"] == "edge-2"
    assert observations[0]["source_port_raw"] == "Gi1/0/1"


def test_ip_locator_uses_registry_interface_action(monkeypatch):
    from services import ip_locator_service

    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "records": [{"interface": "Vlan100", "ip_address": "192.0.2.10/24"}],
        },
    )

    result = ip_locator_service._check_local_device_ip(
        {
            "id": "device-1",
            "platform": "cisco_ios",
            "platform_profile_id": "profile-1",
            "tenant_id": "tenant-1",
        },
        "192.0.2.10",
    )
    assert result["interface"] == "Vlan100"


def test_scheduler_interface_sync_uses_registry_actions_for_bound_device(monkeypatch):
    from services import scheduler_service

    def fake_execute(_device_id, action_code, **_kwargs):
        records = {
            "get_interfaces": [{
                "interface": "Gi1/0/1",
                "description": "uplink",
                "mac_address": "aabb.ccdd.eeff",
                "speed": "1G",
            }],
            "get_interface_brief": [{
                "interface": "GigabitEthernet1/0/1",
                "admin_status": "up",
                "oper_status": "up",
            }],
            "get_ip_interfaces": [{
                "interface": "Gi1/0/1",
                "ip_address": "192.0.2.1/24",
            }],
        }
        return {"success": True, "records": records[action_code]}

    monkeypatch.setattr("services.platform_registry_service.execute_platform_action", fake_execute)

    result = scheduler_service._collect_registry_interfaces({
        "id": "device-1",
        "hostname": "edge-1",
        "platform_profile_id": "profile-1",
        "tenant_id": "tenant-1",
    })

    assert len(result) == 1
    assert result[0]["name"] == "Gi1/0/1"
    assert result[0]["admin_status"] == "up"
    assert result[0]["ip_address"] == "192.0.2.1/24"
    assert result[0]["switchport_mode"] == "l3"


def test_playbook_action_step_uses_published_action_preview(monkeypatch):
    from api.playbooks import engine

    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    monkeypatch.setattr(
        "services.platform_registry_service.preview_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "command": "show clock",
            "command_checksum": "checksum",
            "platform_release_id": "release-1",
        },
    )

    result = asyncio.run(
        engine._execute_registry_actions(
            "execution-1",
            {"id": "device-1", "tenant_id": "tenant-1"},
            [{"action_code": "get_clock"}],
            dry_run=True,
            actor={"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"},
        )
    )
    assert result["success"] is True
    assert result["actions"][0]["command"] == "show clock"


def test_playbook_action_step_is_closed_with_registry_flag_off(monkeypatch):
    from api.playbooks import engine

    monkeypatch.delenv("PLATFORM_REGISTRY_ENABLED", raising=False)
    result = asyncio.run(
        engine._execute_registry_actions(
            "execution-1",
            {"id": "device-1", "tenant_id": "tenant-1"},
            [{"action_code": "get_clock"}],
            dry_run=True,
            actor={"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"},
        )
    )
    assert result["success"] is False
    assert result["actions"][0]["error_code"] == "PLATFORM_REGISTRY_DISABLED"


def test_controlled_playbook_validator_rejects_raw_commands():
    from api.playbooks.scenarios import validate_controlled_phases

    assert validate_controlled_phases({"pre_check": [{"action_code": "get_clock"}]}) == []
    errors = validate_controlled_phases({"execute": ["show clock"]})
    assert errors == [{"path": "phases.execute[0]", "code": "RAW_COMMAND_DISABLED"}]


def test_connectivity_probe_does_not_bypass_registry_for_bound_device(monkeypatch):
    from services import connectivity_service

    class _ShouldNotExecute:
        def __init__(self, *args, **kwargs):
            raise AssertionError("bound device must not use AutomationService")

    monkeypatch.setattr(connectivity_service, "AutomationService", _ShouldNotExecute, raising=False)
    device = connectivity_service._build_device_info({
        "id": "device-1",
        "hostname": "edge-1",
        "ip_address": "192.0.2.10",
        "platform": "cisco_ios",
        "platform_profile_id": "profile-1",
        "tenant_id": "tenant-1",
    })

    with pytest.raises(ValueError, match="UNSUPPORTED_ACTION"):
        connectivity_service._device_ping(device, "192.0.2.20")
    with pytest.raises(ValueError, match="UNSUPPORTED_ACTION"):
        connectivity_service._device_traceroute(device, "192.0.2.20")
