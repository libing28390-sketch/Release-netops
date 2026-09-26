from __future__ import annotations

import pytest

from services.platform_registry_service import (
    ACTION_DEFINITIONS,
    PLATFORM_ACTION_COMMANDS,
    PROFILE_ACTION_COMMANDS,
    PlatformRegistryError,
    execute_platform_action,
    get_profile_action_commands,
    platform_vendors_match,
    preview_platform_action,
)


def test_optical_action_has_no_cli_default_in_any_builtin_catalog():
    assert all("get_transceivers" not in actions for actions in PLATFORM_ACTION_COMMANDS.values())
    assert all("get_transceivers" not in actions for actions in PROFILE_ACTION_COMMANDS.values())
    assert "get_transceivers" not in get_profile_action_commands({"parser_platform": "huawei_vrpv8"})
    action = next(item for item in ACTION_DEFINITIONS if item["action_code"] == "get_transceivers")
    assert action["field_types"]["ifIndex"] == "integer"
    assert action["field_types"]["rx_power_dbm"] == "number"
    assert action["max_records"] == 2000


def test_platform_profile_action_rejects_explicit_vendor_mismatch(isolated_db, monkeypatch):
    assert platform_vendors_match("华为", "Huawei")
    assert not platform_vendors_match("H3C", "Cisco")

    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO devices
               (id, hostname, ip_address, vendor, platform, status, username, password,
                connection_method, platform_profile_id, platform_source, tenant_id)
               VALUES ('device-vendor-mismatch', 'wrong-vendor', '192.0.2.19', 'H3C', 'cisco_ios', 'active', 'u', 'p',
                       'mock', 'system-profile-cisco_ios', 'SYSTEM', 'tenant-1')"""
        )
        conn.commit()
    finally:
        conn.close()

    user = {"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"}
    with pytest.raises(PlatformRegistryError) as execute_error:
        execute_platform_action("device-vendor-mismatch", "get_version", user=user)
    with pytest.raises(PlatformRegistryError) as preview_error:
        preview_platform_action("device-vendor-mismatch", "get_version", user=user)

    assert execute_error.value.code == "PLATFORM_VENDOR_MISMATCH"
    assert preview_error.value.code == "PLATFORM_VENDOR_MISMATCH"


def test_registry_transceiver_action_uses_snmp_and_never_dispatches_driver(isolated_db, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO devices
               (id, hostname, ip_address, platform, status, username, password,
                connection_method, platform_profile_id, platform_source, tenant_id)
               VALUES ('device-optical-action', 'edge-optical', '192.0.2.17',
                       'cisco_ios', 'active', 'u', 'p', 'mock',
                       'system-profile-cisco_ios', 'SYSTEM', 'tenant-1')"""
        )
        conn.commit()
    finally:
        conn.close()

    collected_devices = []

    def collect(device):
        collected_devices.append(device)
        return {
            "success": True,
            "source": "snmp",
            "adapter": {"vendor": "H3C", "supported": True},
            "records": [
                {"interface": f"Ten-GigabitEthernet1/0/{index}", "tx_power_dbm": 0.1}
                for index in range(2005)
            ],
            "count": 2005,
        }

    monkeypatch.setattr("services.snmp_optical_service.collect_optical_snmp", collect)

    def reject_cli(*_args, **_kwargs):
        raise AssertionError("transceiver action must not create a CLI driver")

    user = {"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"}
    result = execute_platform_action(
        "device-optical-action",
        "get_transceivers",
        user=user,
        driver_factory=reject_cli,
    )
    preview = preview_platform_action("device-optical-action", "get_transceivers", user=user)

    assert result["success"] is True
    assert result["source"] == "snmp"
    assert result["parser"] == "snmp-optical"
    assert result["command"] is None
    assert result["records"][0]["tx_power_dbm"] == 0.1
    assert result["count"] == 2000
    assert len(result["records"]) == 2000
    assert preview["execution_mode"] == "snmp"
    assert preview["command"] is None
    assert len(collected_devices) == 1


def test_registry_transceiver_action_works_without_platform_profile_or_release(isolated_db, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO devices
               (id, hostname, ip_address, vendor, platform, status,
                connection_method, platform_source, tenant_id)
               VALUES ('device-optical-unbound', 'edge-optical-unbound', '192.0.2.18',
                       'H3C', 'h3c_comware_v7', 'active', 'mock', 'SYSTEM', 'tenant-1')"""
        )
        conn.commit()
    finally:
        conn.close()

    def collect(device):
        assert device["vendor"] == "H3C"
        return {
            "success": True,
            "source": "snmp",
            "adapter": {"vendor": "H3C", "supported": True},
            "records": [{"interface": "GigabitEthernet1/0/1", "rx_power_dbm": -18.5}],
            "count": 1,
        }

    monkeypatch.setattr("services.snmp_optical_service.collect_optical_snmp", collect)
    user = {"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"}

    def reject_cli(*_args, **_kwargs):
        raise AssertionError("SNMP-only action must not require a CLI driver")

    result = execute_platform_action(
        "device-optical-unbound",
        "get_transceivers",
        user=user,
        driver_factory=reject_cli,
    )
    preview = preview_platform_action("device-optical-unbound", "get_transceivers", user=user)

    assert result["success"] is True
    assert result["source"] == "snmp"
    assert result["command"] is None
    assert result["records"][0]["rx_power_dbm"] == -18.5
    assert preview["execution_mode"] == "snmp"
    assert preview["command"] is None

    conn = isolated_db["module"].get_db_connection()
    try:
        run = conn.execute(
            "SELECT status, platform_profile_id, platform_release_id FROM platform_action_runs WHERE device_id = ? ORDER BY created_at DESC LIMIT 1",
            ("device-optical-unbound",),
        ).fetchone()
    finally:
        conn.close()
    assert run["status"] == "SUCCESS"
    assert run["platform_profile_id"] is None
    assert run["platform_release_id"] is None
