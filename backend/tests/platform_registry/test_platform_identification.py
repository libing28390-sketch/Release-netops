from __future__ import annotations

import uuid

import pytest

from services.platform_identification_service import (
    _binding_compatibility,
    bind_device,
    identify_device,
    identify_device_live,
    identify_platforms,
    list_identification_conflicts,
)
from services.platform_registry_service import PlatformRegistryError, create_profile


def _user(tenant: str, role: str = "Operator"):
    return {"id": f"user-{tenant}", "username": f"{tenant}-user", "role": role, "tenant_id": tenant}


def _insert_device(conn, tenant: str, *, device_id: str | None = None, site: str = "site-a") -> str:
    device_id = device_id or str(uuid.uuid4())
    conn.execute(
        """INSERT INTO devices
           (id, hostname, ip_address, platform, status, tenant_id, site,
            device_group_id, platform_source, platform_locked)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (device_id, device_id, "192.0.2.10", "unknown", "active", tenant, site, "group-a", "LEGACY", 0),
    )
    conn.commit()
    return device_id


def _insert_rule(conn, profile_id: str, *, pattern: str, confidence: float = 0.9, match_type: str = "contains"):
    conn.execute(
        """INSERT INTO platform_identification_rules
           (id, platform_profile_id, command, match_type, pattern,
            logic_group, rule_order, confidence, negate, enabled, created_at)
           VALUES (?, ?, ?, ?, ?, 'ALL', 10, ?, 0, 1, ?)""",
        (str(uuid.uuid4()), profile_id, "show version", match_type, pattern, confidence, "now"),
    )
    conn.commit()


def test_binding_compatibility_blocks_high_risk_execution_for_unverified_platform():
    result = _binding_compatibility(
        {"vendor": "Acme", "device_type": "router"},
        {"vendor": "Other", "adaptation_status": "UNVERIFIED", "sample_status": "MISSING"},
    )
    assert result["status"] == "WARNING"
    assert result["high_risk_execution_blocked"] is True
    assert {item["code"] for item in result["warnings"]} == {
        "VENDOR_PLATFORM_MISMATCH", "PLATFORM_ADAPTATION_UNVERIFIED",
    }


def test_platform_identification_is_declarative_and_binding_is_locked(isolated_db, monkeypatch):
    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    user = _user("tenant-1")
    cisco = create_profile(
        {"platform_code": "custom_cisco", "connection_driver": "cisco_ios", "parser_platform": "cisco_ios"},
        user,
    )
    huawei = create_profile(
        {"platform_code": "custom_huawei", "connection_driver": "huawei_vrp", "parser_platform": "huawei_vrp"},
        user,
    )
    conn = isolated_db["module"].get_db_connection()
    try:
        device_id = _insert_device(conn, "tenant-1")
        _insert_rule(conn, cisco["id"], pattern="CUSTOM-CISCO", confidence=0.9)
        _insert_rule(conn, huawei["id"], pattern="CUSTOM-HUAWEI", confidence=0.9)
    finally:
        conn.close()

    result = identify_device(device_id, {"show version": "CUSTOM-CISCO software"}, user)
    assert result["status"] == "MATCHED"
    assert result["selected"]["platform_profile_id"] == cisco["id"]
    assert result["selected"]["matched_rule_count"] == 1

    import services.connectivity_service as connectivity_service

    monkeypatch.setattr(connectivity_service, "_load_device", lambda _device_id: {"device_type": "cisco_ios"})
    monkeypatch.setattr(connectivity_service, "_build_device_info", lambda device: device)

    class FakeAutomation:
        def execute_commands(self, _device, commands, is_config=False):
            assert is_config is False
            return [{"success": True, "output": "CUSTOM-CISCO software"} for _ in commands]

    import services.automation_service as automation_service
    monkeypatch.setattr(automation_service, "AutomationService", FakeAutomation)
    live = identify_device_live(device_id, user)
    assert live["status"] == "MATCHED"
    assert live["connection_driver"] == "cisco_ios"
    assert live["commands"] == ["show version"]
    assert "observations" not in live

    bound = bind_device(device_id, cisco["id"], user, lock=True)
    assert bound["platform_profile_id"] == cisco["id"]
    assert bound["platform_locked"] == 1
    with pytest.raises(PlatformRegistryError) as locked:
        bind_device(device_id, huawei["id"], user)
    assert locked.value.code == "PLATFORM_BINDING_LOCKED"


def test_binding_rejects_an_explicit_device_platform_from_another_profile(isolated_db):
    user = _user("tenant-1")
    conn = isolated_db["module"].get_db_connection()
    try:
        device_id = _insert_device(conn, "tenant-1", device_id="explicit-platform-device")
        conn.execute("UPDATE devices SET platform = ? WHERE id = ?", ("cisco_ios", device_id))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(PlatformRegistryError) as error:
        bind_device(device_id, "system-profile-hp_comware", user)
    assert error.value.code == "PLATFORM_PROFILE_MISMATCH"


def test_platform_identification_returns_conflict_and_rejects_cross_tenant(isolated_db):
    user = _user("tenant-1")
    other = _user("tenant-2")
    first = create_profile(
        {"platform_code": "match_first", "connection_driver": "cisco_ios", "parser_platform": "cisco_ios"}, user,
    )
    second = create_profile(
        {"platform_code": "match_second", "connection_driver": "cisco_ios", "parser_platform": "cisco_ios"}, user,
    )
    conn = isolated_db["module"].get_db_connection()
    try:
        _insert_rule(conn, first["id"], pattern="SAME", confidence=0.8)
        _insert_rule(conn, second["id"], pattern="SAME", confidence=0.8)
        device_id = _insert_device(conn, "tenant-1")
        other_device = _insert_device(conn, "tenant-2")
    finally:
        conn.close()

    conflict = identify_device(device_id, {"show version": "SAME"}, user)
    assert conflict["status"] == "IDENTIFICATION_CONFLICT"
    assert conflict["selected"] is None
    queue = list_identification_conflicts(user)
    assert len(queue) == 1
    assert queue[0]["device_id"] == device_id
    assert queue[0]["observation_commands"] == ["show version"]
    assert {item["platform_code"] for item in queue[0]["platform_candidates"]} == {"match_first", "match_second"}
    bind_device(device_id, first["id"], user)
    assert list_identification_conflicts(user) == []
    with pytest.raises(PlatformRegistryError) as denied:
        identify_device(other_device, {"show version": "SAME"}, user)
    assert denied.value.code == "DEVICE_SCOPE_DENIED"
    with pytest.raises(PlatformRegistryError) as bind_denied:
        bind_device(device_id, first["id"], other)
    assert bind_denied.value.code in {"DEVICE_SCOPE_DENIED", "PLATFORM_SCOPE_DENIED"}


def test_live_identification_uses_bound_profile_connection_driver(isolated_db, monkeypatch):
    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    user = _user("tenant-1")
    profile = create_profile(
        {"platform_code": "zte_5900_v6", "connection_driver": "zte_zxros", "parser_platform": "zte_zxros"},
        user,
    )
    device_id = "live-driver-device"
    conn = isolated_db["module"].get_db_connection()
    try:
        _insert_device(conn, "tenant-1", device_id=device_id)
        conn.execute(
            "UPDATE devices SET platform = ?, platform_profile_id = ? WHERE id = ?",
            ("zte_5900_v6", profile["id"], device_id),
        )
        conn.commit()
    finally:
        conn.close()

    import services.connectivity_service as connectivity_service
    monkeypatch.setattr(connectivity_service, "_load_device", lambda _device_id: {
        "id": device_id,
        "device_type": "zte_5900_v6",
        "platform": "zte_5900_v6",
        "platform_profile_id": profile["id"],
    })
    monkeypatch.setattr(connectivity_service, "_build_device_info", lambda device: device)

    import services.automation_service as automation_service
    observed = []

    class FakeAutomation:
        def execute_commands(self, device, commands, is_config=False):
            observed.append((device["platform"], commands, is_config))
            return [{"success": True, "output": "ZXR10 Software, Version: 5900 V6.00"}]

    monkeypatch.setattr(automation_service, "AutomationService", FakeAutomation)
    live = identify_device_live(device_id, user)
    assert live["connection_driver"] == "zte_zxros"
    assert live["commands"] == ["show version"]
    assert observed == [("zte_zxros", ["show version"], False)]


@pytest.mark.parametrize(
    ("raw_platform", "expected_driver", "expected_command"),
    [
        ("cisco_ios", "cisco_ios", "show version"),
        ("huawei_vrp", "huawei_vrp", "display version"),
        ("h3c_comware", "hp_comware", "display version"),
    ],
)
def test_live_identification_command_families_match_driver_contract(
    isolated_db, monkeypatch, raw_platform, expected_driver, expected_command,
):
    user = _user("tenant-1")
    device_id = f"live-{expected_driver}"
    conn = isolated_db["module"].get_db_connection()
    try:
        _insert_device(conn, "tenant-1", device_id=device_id)
    finally:
        conn.close()

    import services.connectivity_service as connectivity_service
    monkeypatch.setattr(connectivity_service, "_load_device", lambda _device_id: {
        "id": device_id,
        "device_type": raw_platform,
        "platform": raw_platform,
    })
    monkeypatch.setattr(connectivity_service, "_build_device_info", lambda device: device)

    import services.automation_service as automation_service
    observed = []

    class FakeAutomation:
        def execute_commands(self, device, commands, is_config=False):
            observed.append((device["platform"], commands, is_config))
            return [{"success": True, "output": "vendor version"}]

    monkeypatch.setattr(automation_service, "AutomationService", FakeAutomation)
    live = identify_device_live(device_id, user)
    assert live["connection_driver"] == expected_driver
    assert live["commands"] == [expected_command]
    assert observed == [(expected_driver, [expected_command], False)]


@pytest.mark.parametrize(
    ("platform_code", "output"),
    [
        ("zte_5900_v6", "ZTE ZXR10 Software, Version: 5900 V6.00.04.20P01"),
        ("zte_zsrv2_v3", "ZXR10 1800-2S ZSRV2 V3.1"),
        ("ruijie_s6k_rgos12", "S6231-48XS8CQ S6K-A_RGOS 12.5"),
        ("ruijie_eg_rgos11", "EG3000UE EG_RGOS 11.2"),
        ("dptech_fw_s211", "FW1000-TS-C Software Release S211C011"),
        ("maipu_s3330_v9", "MyPower S3330 Software Version 9.7.1"),
    ],
)
def test_seeded_domestic_identification_keywords(isolated_db, platform_code, output):
    user = _user("tenant-1")
    result = identify_platforms({"show version": output}, user, platform_code=platform_code)
    assert result["status"] == "MATCHED"
    assert result["selected"]["platform_code"] == platform_code


@pytest.mark.parametrize(
    ("platform_code", "command", "output"),
    [
        ("cisco_ios", "show version", "Cisco IOS XE Software, Version 17.9.4"),
        ("arista_eos", "show version", "Arista DCS-7050SX3-48YC8\nSoftware image version: 4.29.2F"),
        ("h3c_comware", "display version", "H3C Comware Software, Version 7.1.064"),
        ("huawei_vrp", "display version", "Huawei Versatile Routing Platform Software\nVRP (R) software, Version 8.24"),
        ("juniper_junos", "show version", "JUNOS Software Release [21.4R3-S5.4]"),
    ],
)
def test_seeded_core_identification_keywords_use_driver_command(
    isolated_db, platform_code, command, output,
):
    user = _user("tenant-1")
    result = identify_platforms({command: output}, user, platform_code=platform_code)
    assert result["status"] == "MATCHED"
    assert result["selected"]["platform_code"] == platform_code
