from __future__ import annotations

import uuid

import pytest

from services.platform_identification_service import (
    _assert_device_profile_platform,
    _assert_version_override_permission,
    _binding_compatibility,
    _extract_version_from_text,
    _inventory_profile_code,
    _prefer_version_evidence,
    bind_device,
    bind_devices_batch,
    identify_device,
    identify_device_from_inventory,
    identify_device_from_snmp,
    identify_device_live,
    identify_platforms,
    list_identification_conflicts,
    unbind_devices_batch,
)
from services.platform_registry_service import PlatformRegistryError, create_profile
from api.platform_registry import PlatformDetectRequest, api_device_platform_detect


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


@pytest.mark.parametrize(
    ("platform", "version", "vendor", "expected_profile", "expected_parser"),
    [
        ("h3c_comware", "3.10", "H3C", "h3c_comware_v3", "h3c_comware_v3"),
        ("h3c_comware", "5.20", "H3C", "h3c_comware_v5", "h3c_comware_v5"),
        ("h3c_comware", "7.1.070", "H3C", "h3c_comware_v7", "h3c_comware_v7"),
        ("h3c_comware", "7.1.070", "新华三", "h3c_comware_v7", "h3c_comware_v7"),
        ("unknown", "9.1", "H3C", "h3c_comware_v9", "h3c_comware_v9"),
        ("h3c_comware", "Comware custom", "H3C", "", "h3c_comware"),
        ("unknown", "7.1.070", "", "", ""),
        ("", "11.9(6)B13P1", "锐捷", "ruijie_rgos_v11", "ruijie_rgos_v11"),
        ("", "S211C011D007P08", "迪普", "dptech_fw_s211", "dptech_conplat"),
        ("", "", "山石", "hillstone_stoneos", "hillstone_stoneos"),
        ("", "9.7.1.25(integrity)", "迈普", "maipu_mypower_v9", "maipu"),
        ("", "5900 V6.00.04.20P01", "中兴", "zte_5900_v6", "zte_zxros"),
        ("ruijie_rgos", "11.9(6)B13P1", "Ruijie", "ruijie_rgos_v11", "ruijie_rgos_v11"),
        ("ruijie_os", "RGOS 12.5(1)", "锐捷", "ruijie_rgos_v12", "ruijie_rgos_v12"),
    ],
)
def test_inventory_resolution_requires_vendor_evidence_and_known_major_version(
    platform, version, vendor, expected_profile, expected_parser,
):
    assert _inventory_profile_code(platform, version, vendor) == (expected_profile, expected_parser)


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


def test_ruijie_system_software_version_extracts_numeric_release():
    output = """show version
System description      : Ruijie EASY GATEWAY(EG3000UE) by Ruijie Networks.
System software version : EG_RGOS 11.9(6)B13P1
System patch number     : NA
"""
    assert _extract_version_from_text(output) == "11.9(6)B13P1"


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("Software Release S211C011D007P08", "S211C011D007P08"),
        ("MyPower S3330 Software Version 9.7.1.25(integrity)", "9.7.1.25(integrity)"),
        ("ZTE ZXR10 Software, Version: 5900 V6.00.04.20P01, Release software", "5900 V6.00.04.20P01"),
        ("ZTE ZXR10 Software, Version: ZSRV2 V3.00.30(1.2.9), Release software", "ZSRV2 V3.00.30(1.2.9)"),
    ],
)
def test_domestic_vendor_version_formats_are_extracted_without_truncation(output, expected):
    assert _extract_version_from_text(output) == expected


@pytest.mark.parametrize(
    ("platform", "version", "vendor", "expected_profile", "expected_parser"),
    [
        ("dptech_ios", "S211C011D007P08", "DPtech", "dptech_fw_s211", "dptech_conplat"),
        ("maipu", "9.7.1.25", "Maipu", "maipu_mypower_v9", "maipu"),
        ("zte_zxros", "5900 V6.00.04.20P01", "ZTE", "zte_5900_v6", "zte_zxros"),
        ("zte_zxros", "ZSRV2 V3.00.30(1.2.9)", "ZTE", "zte_zsrv2_v3", "zte_zxros"),
    ],
)
def test_domestic_vendor_inventory_versions_resolve_concrete_profiles(
    platform, version, vendor, expected_profile, expected_parser,
):
    assert _inventory_profile_code(platform, version, vendor) == (expected_profile, expected_parser)


def test_ruijie_version_evidence_overrides_a_contradictory_model_rule():
    result = {
        "success": True,
        "status": "MATCHED",
        "suggestions": [{"platform_profile_id": "eg-v11", "platform_code": "ruijie_eg_rgos11"}],
        "selected": {"platform_profile_id": "eg-v11", "platform_code": "ruijie_eg_rgos11"},
    }
    candidate = {
        "platform_profile_id": "generic-v12",
        "platform_code": "ruijie_rgos_v12",
        "score": 1.0,
        "evidence": "software_version",
    }
    corrected = _prefer_version_evidence(result, candidate)
    assert corrected["status"] == "MATCHED"
    assert corrected["selected"]["platform_code"] == "ruijie_rgos_v12"

    matching = {**candidate, "platform_code": "ruijie_rgos_v11"}
    assert _prefer_version_evidence(result, matching)["selected"]["platform_code"] == "ruijie_eg_rgos11"


def test_manual_binding_rejects_known_generation_mismatch():
    with pytest.raises(PlatformRegistryError) as mismatch:
        _assert_device_profile_platform(
            {"vendor": "H3C", "platform": "h3c_comware", "version": "7.1.064"},
            {"vendor": "H3C", "platform_code": "h3c_comware_v5", "parser_platform": "h3c_comware"},
        )
    assert mismatch.value.code == "PLATFORM_VERSION_MISMATCH"

    _assert_device_profile_platform(
        {"vendor": "H3C", "platform": "h3c_comware", "version": "7.1.064"},
        {"vendor": "H3C", "platform_code": "h3c_comware_v7", "parser_platform": "h3c_comware"},
    )
    _assert_device_profile_platform(
        {"vendor": "H3C", "platform": "h3c_comware", "version": "7.1.064"},
        {"vendor": "H3C", "platform_code": "h3c_comware_v5", "parser_platform": "h3c_comware"},
        allow_version_mismatch=True,
    )
    _assert_device_profile_platform(
        {"vendor": "H3C", "platform": "h3c_comware", "version": ""},
        {"vendor": "H3C", "platform_code": "h3c_comware_v5", "parser_platform": "h3c_comware"},
    )


def test_version_override_is_restricted_to_administrators():
    with pytest.raises(PlatformRegistryError) as denied:
        _assert_version_override_permission(True, _user("tenant-1", "Operator"))
    assert denied.value.code == "PLATFORM_VERSION_OVERRIDE_FORBIDDEN"

    _assert_version_override_permission(True, _user("tenant-1", "Administrator"))
    _assert_version_override_permission(False, _user("tenant-1", "Operator"))


def test_manual_binding_rejects_cross_vendor_and_accepts_same_vendor_family():
    with pytest.raises(PlatformRegistryError) as mismatch:
        _assert_device_profile_platform(
            {"vendor": "Huawei", "platform": "unknown"},
            {"vendor": "H3C", "platform_code": "h3c_comware_v7", "parser_platform": "h3c_comware"},
        )
    assert mismatch.value.code == "PLATFORM_VENDOR_MISMATCH"

    _assert_device_profile_platform(
        {"vendor": "Huawei", "platform": "huawei_vrp"},
        {"vendor": "Huawei", "platform_code": "huawei_vrp8", "parser_platform": "huawei_vrpv8"},
    )


def test_concrete_catalog_batch_binding_and_unbinding(isolated_db):
    user = _user("tenant-1", "Administrator")
    conn = isolated_db["module"].get_db_connection()
    try:
        device_ids = [
            _insert_device(conn, "tenant-1", device_id="batch-huawei-1"),
            _insert_device(conn, "tenant-1", device_id="batch-huawei-2"),
        ]
        conn.execute(
            "UPDATE devices SET platform = ? WHERE id IN (?, ?)",
            ("huawei_vrp", *device_ids),
        )
        conn.commit()
    finally:
        conn.close()

    bound = bind_devices_batch(
        device_ids,
        "system-profile-huawei_vrp8",
        user,
        lock=True,
    )
    assert bound["device_count"] == 2
    assert bound["platform_code"] == "huawei_vrp8"

    unbound = unbind_devices_batch(device_ids, user, force=True)
    assert unbound["device_count"] == 2
    conn = isolated_db["module"].get_db_connection()
    try:
        rows = conn.execute(
            "SELECT platform, platform_profile_id, platform_locked FROM devices WHERE id IN (?, ?) ORDER BY id",
            tuple(device_ids),
        ).fetchall()
        assert all(row[0] == "huawei_vrpv8" and row[1] is None and row[2] == 0 for row in rows)
    finally:
        conn.close()


def test_batch_binding_version_mismatch_is_atomic(isolated_db):
    user = _user("tenant-1", "Administrator")
    device_ids = ["batch-version-1", "batch-version-2"]
    conn = isolated_db["module"].get_db_connection()
    try:
        for device_id in device_ids:
            _insert_device(conn, "tenant-1", device_id=device_id)
        conn.execute(
            "UPDATE devices SET platform = ?, version = ? WHERE id IN (?, ?)",
            ("h3c_comware", "7.1.064", *device_ids),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(PlatformRegistryError) as mismatch:
        bind_devices_batch(device_ids, "system-profile-h3c_comware_v5", user, lock=True)
    assert mismatch.value.code == "PLATFORM_VERSION_MISMATCH"

    conn = isolated_db["module"].get_db_connection()
    try:
        rows = conn.execute(
            "SELECT platform_profile_id FROM devices WHERE id IN (?, ?) ORDER BY id",
            tuple(device_ids),
        ).fetchall()
        assert all(row[0] is None for row in rows)
    finally:
        conn.close()

    overridden = bind_devices_batch(
        device_ids,
        "system-profile-h3c_comware_v5",
        user,
        lock=True,
        allow_version_mismatch=True,
    )
    assert overridden["device_count"] == 2
    conn = isolated_db["module"].get_db_connection()
    try:
        rows = conn.execute(
            "SELECT platform_profile_id FROM devices WHERE id IN (?, ?) ORDER BY id",
            tuple(device_ids),
        ).fetchall()
        assert all(row[0] == "system-profile-h3c_comware_v5" for row in rows)
    finally:
        conn.close()


def test_platform_detection_uses_snmp_inventory_version_without_cli_probe(isolated_db, monkeypatch):
    user = _user("tenant-1")
    conn = isolated_db["module"].get_db_connection()
    try:
        columns = {
            str(row[0])
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'devices'",
            ).fetchall()
        }
        if "version" not in columns:
            conn.execute("ALTER TABLE devices ADD COLUMN version TEXT DEFAULT ''")
        device_id = _insert_device(conn, "tenant-1", device_id="snmp-version-device")
        conn.execute(
            "UPDATE devices SET platform = ?, version = ? WHERE id = ?",
            ("h3c_comware", "7.1.070", device_id),
        )
        conn.commit()
    finally:
        conn.close()

    result = identify_device_from_inventory(device_id, user)
    assert result is not None
    assert result["source"] == "snmp_inventory"
    assert result["version"] == "7.1.070"
    assert result["parser_platform"] == "h3c_comware_v7"
    assert result["selected"]["platform_code"] == "h3c_comware_v7"
    assert result["commands"] == []

    import api.platform_registry as platform_registry_api


    def fail_if_cli_is_called(*_args, **_kwargs):
        raise AssertionError("SNMP-backed detection must not call the CLI probe")

    monkeypatch.setattr(platform_registry_api, "identify_device_live", fail_if_cli_is_called)
    response = api_device_platform_detect(device_id, PlatformDetectRequest(), user)
    assert response["success"] is True
    assert response["message"] == "SNMP inventory version used; CLI probe skipped"


def test_platform_detection_probes_live_snmp_before_cli_when_version_is_not_cached(isolated_db, monkeypatch):
    user = _user("tenant-1")
    conn = isolated_db["module"].get_db_connection()
    try:
        columns = {
            str(row[0])
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'devices'",
            ).fetchall()
        }
        if "version" not in columns:
            conn.execute("ALTER TABLE devices ADD COLUMN version TEXT DEFAULT ''")
        device_id = _insert_device(conn, "tenant-1", device_id="live-snmp-version-device")
        conn.execute(
            "UPDATE devices SET platform = ?, version = ? WHERE id = ?",
            ("h3c_comware", "", device_id),
        )
        conn.commit()
    finally:
        conn.close()

    async def fake_collect_device_info(_ip, _community, _port):
        return {
            "sys_name": "S6850-1",
            "sys_descr": "H3C Comware Platform Software, Software Version 7.1.070, Alpha 7170",
        }

    import services.snmp_service as snmp_service
    import services.vault_service as vault_service
    monkeypatch.setattr(snmp_service, "collect_device_info", fake_collect_device_info)
    monkeypatch.setattr(
        vault_service,
        "resolve_collector_credentials",
        lambda _device: {"snmp": {"server": "192.0.2.10", "community": "test", "port": 161}},
    )

    result = identify_device_from_snmp(device_id, user)
    assert result is not None
    assert result["source"] == "snmp_live"
    assert result["source_detail"] == "live"
    assert result["version"] == "7.1.070"
    assert result["parser_platform"] == "h3c_comware_v7"

    conn = isolated_db["module"].get_db_connection()
    try:
        assert conn.execute("SELECT version FROM devices WHERE id = ?", (device_id,)).fetchone()[0] == "7.1.070"
    finally:
        conn.close()

    import api.platform_registry as platform_registry_api

    monkeypatch.setattr(platform_registry_api, "identify_device_from_inventory", lambda *_args: None)
    monkeypatch.setattr(platform_registry_api, "identify_device_from_snmp", lambda *_args: result)

    def fail_if_cli_is_called(*_args, **_kwargs):
        raise AssertionError("Live SNMP detection must not call the CLI fallback")

    monkeypatch.setattr(platform_registry_api, "identify_device_live", fail_if_cli_is_called)
    response = api_device_platform_detect(device_id, PlatformDetectRequest(), user)
    assert response["success"] is True
    assert response["message"] == "Live SNMP identity used; CLI probe skipped"


def test_platform_detection_falls_back_to_cli_when_snmp_has_no_version(isolated_db, monkeypatch):
    user = _user("tenant-1")
    conn = isolated_db["module"].get_db_connection()
    try:
        device_id = _insert_device(conn, "tenant-1", device_id="cli-fallback-device")
    finally:
        conn.close()

    import api.platform_registry as platform_registry_api

    monkeypatch.setattr(platform_registry_api, "identify_device_from_inventory", lambda *_args: None)
    monkeypatch.setattr(platform_registry_api, "identify_device_from_snmp", lambda *_args: None)
    cli_result = {
        "device_id": device_id,
        "source": "cli",
        "version": "7.1.070",
        "status": "MATCHED",
        "commands": ["display version"],
        "suggestions": [],
        "selected": None,
    }
    monkeypatch.setattr(platform_registry_api, "identify_device_live", lambda *_args: cli_result)

    response = api_device_platform_detect(device_id, PlatformDetectRequest(), user)
    assert response["success"] is True
    assert response["data"] == cli_result
    assert response["message"] == ""


@pytest.mark.parametrize(
    ("sys_object_id", "sys_descr", "expected_vendor", "expected_platform"),
    [
        (
            ".1.3.6.1.4.1.31648.1.1",
            "DPtech ConPlat Software Version S211C011D007P08",
            "DPtech",
            "dptech_fw_s211",
        ),
        (
            ".1.3.6.1.4.1.24681.1.1",
            "Hillstone StoneOS",
            "Hillstone",
            "hillstone_stoneos",
        ),
        (
            ".1.3.6.1.4.1.28557.1.1",
            "Hillstone StoneOS",
            "Hillstone",
            "hillstone_stoneos",
        ),
    ],
)
def test_live_snmp_vendor_identity_suggests_dptech_and_hillstone_without_mutating_asset(
    isolated_db, monkeypatch, sys_object_id, sys_descr, expected_vendor, expected_platform,
):
    user = _user("tenant-1")
    conn = isolated_db["module"].get_db_connection()
    try:
        device_id = _insert_device(conn, "tenant-1", device_id=f"snmp-{expected_vendor.lower()}-device")
        conn.execute(
            "UPDATE devices SET platform = ?, vendor = '' WHERE id = ?",
            ("unknown", device_id),
        )
        conn.commit()
    finally:
        conn.close()

    async def fake_collect_device_info(_ip, _community, _port):
        return {
            "sys_name": "test-device",
            "sys_descr": sys_descr,
            "sys_object_id": sys_object_id,
        }

    import services.snmp_discovery_service as snmp_discovery_service
    import services.snmp_service as snmp_service
    import services.vault_service as vault_service

    monkeypatch.setattr(snmp_service, "collect_device_info", fake_collect_device_info)
    monkeypatch.setattr(vault_service, "resolve_collector_credentials", lambda _device: {
        "snmp": {"server": "192.0.2.10", "community": "test", "port": 161},
    })
    monkeypatch.setattr(snmp_discovery_service, "ensure_rules_available", lambda: None)
    monkeypatch.setattr(snmp_discovery_service, "resolve_rule", lambda *_args, **_kwargs: None)

    result = identify_device_from_snmp(device_id, user)

    assert result is not None
    assert result["status"] == "MATCHED"
    assert result["detected_vendor"] == expected_vendor
    assert result["vendor_source"] == "sysObjectID"
    assert result["selected"]["platform_code"] == expected_platform

    conn = isolated_db["module"].get_db_connection()
    try:
        device = conn.execute(
            "SELECT vendor, platform FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
        assert device[0] == ""
        assert device[1] == "unknown"
    finally:
        conn.close()


def test_live_snmp_vendor_conflict_does_not_suggest_or_mutate_platform(isolated_db, monkeypatch):
    user = _user("tenant-1")
    conn = isolated_db["module"].get_db_connection()
    try:
        device_id = _insert_device(conn, "tenant-1", device_id="snmp-vendor-conflict-device")
        conn.execute(
            "UPDATE devices SET platform = ?, vendor = ? WHERE id = ?",
            ("unknown", "H3C", device_id),
        )
        conn.commit()
    finally:
        conn.close()

    async def fake_collect_device_info(_ip, _community, _port):
        return {
            "sys_name": "test-device",
            "sys_descr": "DPtech ConPlat Software Version S211C011D007P08",
            "sys_object_id": ".1.3.6.1.4.1.31648.1.1",
        }

    import services.snmp_discovery_service as snmp_discovery_service
    import services.snmp_service as snmp_service
    import services.vault_service as vault_service

    monkeypatch.setattr(snmp_service, "collect_device_info", fake_collect_device_info)
    monkeypatch.setattr(vault_service, "resolve_collector_credentials", lambda _device: {
        "snmp": {"server": "192.0.2.10", "community": "test", "port": 161},
    })
    monkeypatch.setattr(snmp_discovery_service, "ensure_rules_available", lambda: None)
    monkeypatch.setattr(snmp_discovery_service, "resolve_rule", lambda *_args, **_kwargs: None)

    result = identify_device_from_snmp(device_id, user)

    assert result is not None
    assert result["status"] == "VENDOR_CONFLICT"
    assert result["detected_vendor"] == "DPtech"
    assert result["suggestions"] == []
    assert result["selected"] is None

    conn = isolated_db["module"].get_db_connection()
    try:
        device = conn.execute(
            "SELECT vendor, platform FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
        assert device[0] == "H3C"
        assert device[1] == "unknown"
    finally:
        conn.close()


def test_platform_detect_uses_live_snmp_before_cached_inventory(monkeypatch):
    import api.platform_registry as platform_registry_api

    live_result = {
        "source": "snmp_live",
        "status": "MATCHED",
        "detected_vendor": "Hillstone",
        "selected": {"platform_profile_id": "system-profile-hillstone_stoneos"},
        "suggestions": [],
    }
    monkeypatch.setattr(platform_registry_api, "identify_device_from_snmp", lambda *_args: live_result)
    monkeypatch.setattr(
        platform_registry_api,
        "identify_device_from_inventory",
        lambda *_args: (_ for _ in ()).throw(AssertionError("cached inventory must follow live SNMP")),
    )
    monkeypatch.setattr(
        platform_registry_api,
        "identify_device_live",
        lambda *_args: (_ for _ in ()).throw(AssertionError("live SNMP must precede the CLI probe")),
    )

    response = api_device_platform_detect("device-id", PlatformDetectRequest(), _user("tenant-1"))

    assert response["data"] is live_result
    assert response["message"] == "Live SNMP identity used; CLI probe skipped"


def test_platform_identification_is_declarative_and_binding_is_locked(isolated_db, monkeypatch):
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


def test_platform_binding_is_immutable_after_first_assignment(isolated_db):
    user = _user("tenant-1")
    first = create_profile(
        {"platform_code": "stable_first", "connection_driver": "cisco_ios", "parser_platform": "cisco_ios"}, user,
    )
    second = create_profile(
        {"platform_code": "stable_second", "connection_driver": "cisco_ios", "parser_platform": "cisco_ios"}, user,
    )
    conn = isolated_db["module"].get_db_connection()
    try:
        device_id = _insert_device(conn, "tenant-1", device_id="immutable-platform-device")
    finally:
        conn.close()

    bound = bind_device(device_id, first["id"], user)
    assert bound["platform_profile_id"] == first["id"]
    assert bound["platform_locked"] == 1

    repeated = bind_device(device_id, first["id"], user, lock=True)
    assert repeated["binding_unchanged"] is True

    with pytest.raises(PlatformRegistryError) as changed:
        bind_device(device_id, second["id"], user)
    assert changed.value.code == "PLATFORM_BINDING_LOCKED"


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
