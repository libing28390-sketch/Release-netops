from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api import assets
from core.crypto import encrypt_credential
from database import get_db_connection
from schemas.web import WebAccessProfileInput


@pytest.fixture(autouse=True)
def isolate_identity_tests_from_optional_chassis_network_io(monkeypatch):
    # These existing cases exercise hostname/model/credential handling. The
    # separate chassis integration module verifies the new SN stage end to end.
    # Do not let old identity fixtures start additional unmocked UDP requests.
    from services import snmp_import_identification_service

    async def retain_identity_result(_item, identity_result, *_limits):
        return identity_result

    monkeypatch.setattr(snmp_import_identification_service, '_sync_import_chassis_serials', retain_identity_result)


def test_batch_import_without_management_ip_reports_missing_ip_without_network_enrichment(isolated_db):
    result = assets.import_assets([
        assets.AssetCreate(
            asset_type="network_device",
            hostname="imported-without-management-ip",
            vendor="Cisco",
            model="C9300",
            platform="cisco_ios",
        )
    ])

    assert result["created"] == 1
    assert result["hostname_sync"]["total"] == 1
    assert result["hostname_sync"]["succeeded"] == 0
    assert result["hostname_sync"]["failed"] == 1
    assert result["hostname_sync"]["failed_items"][0]["error"] == "缺少管理 IP"
    assert result["librenms_enrollment"]["total"] == 0
    assert result["snmp_identification"]["total"] == 0


def test_batch_import_allows_server_without_hostname_when_management_ip_is_valid(isolated_db):
    management_ip = "192.0.2.221"
    result = assets.import_assets([
        assets.AssetCreate(
            asset_type="server",
            asset_tag="SERVER-EMPTY-HOSTNAME-IMPORT",
            hostname="",
            management_ip=management_ip,
        )
    ])

    assert result["created"] == 1
    with get_db_connection() as conn:
        row = conn.execute(
            """SELECT pa.hostname AS asset_hostname, d.hostname AS device_hostname
                 FROM physical_assets pa
                 JOIN devices d ON d.asset_id = pa.id
                WHERE pa.asset_tag = ?""",
            ("SERVER-EMPTY-HOSTNAME-IMPORT",),
        ).fetchone()
    assert row["asset_hostname"] == management_ip
    assert row["device_hostname"] == management_ip

    missing_ip_result = assets.import_assets([
        assets.AssetCreate(
            asset_type="server",
            asset_tag="SERVER-EMPTY-HOSTNAME-NO-IP",
            hostname="",
            management_ip="",
        )
    ], detailed=True)
    assert missing_ip_result["created"] == 0
    assert missing_ip_result["failed"] == 1
    failure = missing_ip_result["failed_items"][0]
    assert failure["code"] == "ASSET_HOSTNAME_REQUIRED"
    assert failure["message"] == "请填写主机名或有效管理IP"

    with pytest.raises(ValidationError, match="不是有效的 IPv4 或 IPv6 地址"):
        assets.AssetCreate(
            asset_type="server",
            hostname="",
            management_ip="not-an-ip",
        )


def test_batch_import_persists_web_only_management_method_and_sanitizes_password(isolated_db):
    result = assets.import_assets([
        assets.AssetCreate(
            asset_type="network_device",
            asset_tag="WEB-ONLY-IMPORT-1",
            hostname="web-only-import-1",
            management_ip="192.0.2.81",
            vendor="H3C",
            model="SecPath",
            platform="h3c_comware",
            connection_method="web",
            management_port=0,
            web_profiles=[WebAccessProfileInput(
                profile_name="HTTPS management",
                scheme="https",
                port=443,
                path="/login",
                credential_mode="independent",
                normal_username="web-user",
                normal_password="web-secret",
            )],
        )
    ])

    assert result["created"] == 1
    assert result["snmp_identification"]["items"][0]["status"] == "missing_credentials"
    assert result["snmp_identification"]["items"][0]["platform_binding_status"] == "skipped"
    listed = assets.list_assets(q="WEB-ONLY-IMPORT-1", page=1, page_size=10)
    item = listed["items"][0]
    assert item["connection_method"] == "web"
    assert item["management_port"] == 0
    assert len(item["web_profiles"]) == 1
    profile = item["web_profiles"][0]
    assert profile["credential_mode"] == "independent"
    assert profile["normal_username"] == "web-user"
    assert profile["normal_password"] == ""
    assert profile["normal_password_set"] is True

    with get_db_connection() as conn:
        stored = conn.execute(
            "SELECT normal_password FROM asset_web_access_profiles WHERE asset_id = ?",
            (item["id"],),
        ).fetchone()
    assert stored["normal_password"]
    assert stored["normal_password"] != "web-secret"


def test_batch_import_binds_snmp_credential_name_to_asset_and_device(isolated_db, monkeypatch):
    async def fake_snmp_get(*_args, **_kwargs):
        return "imported-snmp-by-name.CCIE"

    import services.snmp_service as snmp_service
    monkeypatch.setattr(snmp_service, "_snmp_get", fake_snmp_get)

    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO credentials (
                   id, credential_name, credential_type, account_role,
                   snmp_community, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "cred-import-snmp",
                "import-snmp-monitor",
                "snmpv2",
                "normal",
                encrypt_credential("community-import-only"),
                "2026-07-21T00:00:00+00:00",
            ),
        )
        conn.commit()

    result = assets.import_assets([
        assets.AssetCreate(
            asset_type="network_device",
            hostname="imported-placeholder-name",
            management_ip="192.0.2.82",
            vendor="Cisco",
            model="C9300",
            platform="cisco_ios",
            lifecycle_status="staging",
            asset_origin="new",
            snmp_credential_name="import-snmp-monitor",
        )
    ])

    assert result["created"] == 1
    assert result["hostname_sync"] == {
        "total": 1,
        "succeeded": 1,
        "failed": 0,
        "failed_items": [],
    }
    with get_db_connection() as conn:
        asset = conn.execute(
            "SELECT id, snmp_credential_id, snmp_community, hostname FROM physical_assets WHERE management_ip = ?",
            ("192.0.2.82",),
        ).fetchone()
        device = conn.execute(
            "SELECT snmp_credential_id, snmp_community, hostname FROM devices WHERE asset_id = ?",
            (asset["id"],),
        ).fetchone()
    assert asset["snmp_credential_id"] == "cred-import-snmp"
    assert device["snmp_credential_id"] == "cred-import-snmp"
    assert asset["hostname"] == "imported-snmp-by-name"
    assert device["hostname"] == "imported-snmp-by-name"
    from core.crypto import decrypt_credential
    assert decrypt_credential(asset["snmp_community"]) == "community-import-only"
    assert decrypt_credential(device["snmp_community"]) == "community-import-only"

    listed = assets.list_assets(q="imported-snmp-by-name", page=1, page_size=10)
    assert listed["items"][0]["snmp_credential_name"] == "import-snmp-monitor"
    assert listed["items"][0]["snmp_community_set"] is True


def test_batch_import_auto_identifies_device_and_binds_matching_platform_profile(isolated_db, make_user, monkeypatch):
    import asyncio

    actor = make_user("asset_import_platform_binding", role="Operator", tenant_id="tenant-default")
    from services import rack_service

    with get_db_connection() as conn:
        rack = rack_service.create_rack(
            conn,
            name="snmp-model-sync-rack",
            site_id="site-default",
            total_u=20,
            rack_code="snmp-model-sync-rack",
        )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO credentials (
                   id, credential_name, credential_type, snmp_community, created_at
               ) VALUES (?, ?, 'snmpv2', ?, ?)""",
            (
                "cred-import-auto-profile",
                "import-auto-profile",
                encrypt_credential("identity-probe-secret"),
                "2026-10-08T00:00:00+00:00",
            ),
        )
        conn.commit()

    identity_values_by_ip = {
        f"192.0.2.{91 + index}": {
            "1.3.6.1.2.1.1.2.0": ".1.3.6.1.4.1.25506.11.1.1",
            "1.3.6.1.2.1.1.1.0": "H3C Comware Version 7.1.070",
            "1.3.6.1.2.1.1.5.0": f"AP_{12 + index}",
        }
        for index in range(6)
    }
    identity_reads = []

    async def fake_snmp_get(ip, _community, oid, _port, **_kwargs):
        identity_reads.append((ip, oid))
        return identity_values_by_ip.get(ip, {}).get(oid)

    import services.snmp_service as snmp_service
    monkeypatch.setattr(snmp_service, "_snmp_get", fake_snmp_get)

    from services import librenms_enrollment_service, snmp_entity_model_service

    async def fake_enrollment(device_id, *, actor=None):
        return {"status": "local_snmp", "device_id": device_id}

    active_model_probes = 0
    max_active_model_probes = 0

    async def fake_chassis_model(_ip, _settings):
        nonlocal active_model_probes, max_active_model_probes
        active_model_probes += 1
        max_active_model_probes = max(max_active_model_probes, active_model_probes)
        await asyncio.sleep(0.03)
        # Optional ENTITY-MIB discovery must not hold up the established
        # sysName writeback path.
        with get_db_connection() as conn:
            current = conn.execute(
                'SELECT hostname FROM devices WHERE ip_address = ?', (_ip,)
            ).fetchone()
        assert current['hostname'] == identity_values_by_ip[_ip]["1.3.6.1.2.1.1.5.0"]
        active_model_probes -= 1
        return "S5130-28S-HI"

    monkeypatch.setattr(librenms_enrollment_service, "enroll_imported_network_device", fake_enrollment)
    monkeypatch.setattr(snmp_entity_model_service, "read_chassis_model", fake_chassis_model)

    from services import snmp_import_identification_service as identification_service
    monkeypatch.setattr(identification_service, "ensure_rules_available", lambda: {"status": "cached"})
    monkeypatch.setattr(identification_service, "resolve_rule", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        identification_service,
        "resolve_snmp_vendor_identity",
        lambda *_args, **_kwargs: {
            "status": "identified",
            "vendor": "H3C",
            "platform": "h3c_comware",
            "model": "WA6320-HCL",
            "software_version": "7.1.070",
            "source": "librenms",
        },
    )
    result = assets.import_assets([
        assets.AssetCreate(
            asset_type="network_device",
            asset_tag=f"AUTO-SNMP-IDENTITY-{index + 1}",
            hostname=f"ap-import-placeholder-{index + 1}",
            management_ip=f"192.0.2.{91 + index}",
            vendor="H3C",
            model="",
            platform="",
            rack_id=rack["id"],
            planned_start_u=3 + index,
            rack_model_key="generic_switch_1u_24p",
            snmp_credential_name="import-auto-profile",
        )
        for index in range(6)
    ], _user=actor)

    assert result["created"] == 6
    identified = result["snmp_identification"]
    assert identified["identified"] == 6
    assert identified["unresolved"] == 0
    item = identified["items"][0]
    assert item["status"] == "identified"
    assert item["detected_vendor"] == "H3C"
    assert item["detected_platform"] == "h3c_comware"
    assert item["detected_model"] == "S5130-28S-HI"
    assert item["synced_model"] == "S5130-28S-HI"
    assert item["model_source"] == "entity_mib"
    assert item["rack_sync"]["status"] == "synced"
    assert item["platform_binding_status"] == "auto_bound"
    assert item["platform_profile_id"]
    assert item["platform_profile_name"]
    assert item["platform_binding_message"]
    assert len(identity_reads) == 6 * len(identification_service.IDENTITY_OIDS)
    assert len(set(identity_reads)) == len(identity_reads)
    assert max_active_model_probes == 1
    assert all(
        result_item["synced_model"] == "S5130-28S-HI"
        for result_item in identified["items"]
    )
    assert "profile_bound" not in identified
    assert "profile_id" not in item
    assert "identity-probe-secret" not in str(result)

    with get_db_connection() as conn:
        asset = conn.execute(
            "SELECT vendor, platform, model, rack_id, rack_position, rack_mount_kind "
            "FROM physical_assets WHERE asset_tag = ?",
            ("AUTO-SNMP-IDENTITY-1",),
        ).fetchone()
        device = conn.execute(
            """SELECT vendor, platform, model, version, snmp_metric_profile_id,
                      platform_profile_id, platform_source, platform_locked
                 FROM devices WHERE asset_id = (
                     SELECT id FROM physical_assets WHERE asset_tag = ?
                 )""",
            ("AUTO-SNMP-IDENTITY-1",),
        ).fetchone()
    assert (asset["vendor"], asset["platform"], asset["model"], asset["rack_id"]) == (
        "H3C", "h3c_comware", "S5130-28S-HI", rack["id"]
    )
    assert device["snmp_metric_profile_id"] == ""
    assert device["version"] == "7.1.070"
    assert device["platform_profile_id"] == item["platform_profile_id"]
    assert device["platform_source"] == "SNMP_AUTO"
    assert device["platform_locked"] == 1

    with get_db_connection() as conn:
        audit = conn.execute(
            """SELECT event_type, after_json FROM audit_events
                 WHERE event_type = 'platform.binding.snmp_auto' AND device_id = (
                     SELECT id FROM devices WHERE asset_id = (
                         SELECT id FROM physical_assets WHERE asset_tag = ?
                     )
                 )""",
            ("AUTO-SNMP-IDENTITY-1",),
        ).fetchone()
    assert audit is not None
    assert audit["event_type"] == "platform.binding.snmp_auto"
    assert "SNMP_AUTO" in audit["after_json"]

    with get_db_connection() as conn:
        placement = conn.execute(
            """SELECT rd.model_key, dt.vendor, dt.model, rd.start_u
                 FROM rack_devices rd
                 JOIN device_types dt ON dt.id = rd.device_type_id
                WHERE rd.asset_id = (SELECT id FROM physical_assets WHERE asset_tag = ?)""",
            ("AUTO-SNMP-IDENTITY-1",),
        ).fetchone()
    assert (placement["model_key"], placement["vendor"], placement["model"], placement["start_u"]) == (
        "H3C:S5130-28S-HI", "H3C", "S5130-28S-HI", 3
    )


def test_import_platform_binding_refreshes_existing_version_from_snmp_observation(isolated_db, make_user, monkeypatch):
    import asyncio

    actor = make_user("asset_import_stale_version", role="Operator", tenant_id="tenant-default")
    async def no_initial_snmp_response(*_args, **_kwargs):
        return None

    import services.snmp_service as snmp_service
    monkeypatch.setattr(snmp_service, "_snmp_get", no_initial_snmp_response)
    from services import librenms_enrollment_service

    async def fake_enrollment(device_id, *, actor=None):
        return {"status": "local_snmp", "device_id": device_id}

    monkeypatch.setattr(librenms_enrollment_service, "enroll_imported_network_device", fake_enrollment)
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO credentials (
                   id, credential_name, credential_type, snmp_community, created_at
               ) VALUES (?, ?, 'snmpv2', ?, ?)""",
            (
                "cred-import-stale-version",
                "import-stale-version",
                encrypt_credential("identity-probe-secret"),
                "2026-10-28T00:00:00+00:00",
            ),
        )
        conn.commit()

    result = assets.import_assets([
        assets.AssetCreate(
            asset_type="network_device",
            asset_tag="AUTO-SNMP-STALE-VERSION",
            hostname="stale-version-import",
            management_ip="192.0.2.199",
            vendor="H3C",
            model="S5130-28S-HI",
            platform="h3c_comware",
            snmp_credential_name="import-stale-version",
        )
    ], detailed=True, _user=actor)
    device_id = result["results"][0]["device_id"]
    with get_db_connection() as conn:
        conn.execute("UPDATE devices SET version = '5.20' WHERE id = ?", (device_id,))
        conn.commit()

    async def fake_snmp_get(_ip, _community, oid, _port, **_kwargs):
        return {
            "1.3.6.1.2.1.1.2.0": ".1.3.6.1.4.1.25506",
            "1.3.6.1.2.1.1.1.0": (
                "H3C Comware Software. Software Version 7.1.064, Alpha 7164\n"
                "H3C SecPath F1090..."
            ),
            "1.3.6.1.2.1.1.5.0": "stale-version-import",
        }.get(oid)

    monkeypatch.setattr(snmp_service, "_snmp_get", fake_snmp_get)
    from services import snmp_import_identification_service as identification_service
    monkeypatch.setattr(identification_service, "ensure_rules_available", lambda: {"status": "cached"})
    monkeypatch.setattr(identification_service, "resolve_rule", lambda *_args, **_kwargs: None)
    from services import snmp_discovery_service
    monkeypatch.setattr(snmp_discovery_service, "ensure_rules_available", lambda: {"status": "cached"})
    monkeypatch.setattr(snmp_discovery_service, "_resolve_optional_identity_rule", lambda *_args, **_kwargs: None)

    identity = asyncio.run(identification_service.identify_imported_device(
        {
            "device_id": device_id,
            "row": 1,
            "asset_tag": "AUTO-SNMP-STALE-VERSION",
            "hostname": "stale-version-import",
            "ip": "192.0.2.199",
            "snmp_configured": True,
            "declared_vendor": "H3C",
            "declared_platform": "h3c_comware",
            "declared_model": "S5130-28S-HI",
        },
        asyncio.Semaphore(1),
        asyncio.Semaphore(1),
        user=actor,
        auto_bind_platform=True,
    ))

    assert identity["status"] == "identified"
    assert identity["platform_binding_status"] == "auto_bound"
    assert identity["platform_profile_id"]
    assert identity["platform_profile_name"]
    assert identity["identity_source"] == "sysDescr"
    with get_db_connection() as conn:
        stored = conn.execute(
            """SELECT d.version, d.platform_profile_id, d.platform_source, p.platform_code
               FROM devices d
               LEFT JOIN platform_profiles p ON p.id = d.platform_profile_id
               WHERE d.id = ?""",
            (device_id,),
        ).fetchone()
    assert stored["version"] == "7.1.064"
    assert stored["platform_profile_id"] == identity["platform_profile_id"]
    assert stored["platform_source"] == "SNMP_AUTO"
    assert stored["platform_code"] == "h3c_comware_v7"


def test_import_commits_asset_then_enrolls_with_bound_snmpv3_profile(isolated_db, monkeypatch):
    async def no_v3_response(*_args, **_kwargs):
        return None

    import services.snmp_service as snmp_service
    monkeypatch.setattr(snmp_service, "_snmp_get_v3", no_v3_response)

    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO credentials (
                   id, credential_name, credential_type, username, snmp_security_level,
                   snmp_auth_protocol, snmp_auth_password, snmp_priv_protocol,
                   snmp_priv_password, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "cred-import-snmpv3",
                "import-snmpv3-edge",
                "snmpv3",
                "edge-poller",
                "authPriv",
                "SHA",
                encrypt_credential("import-auth-secret"),
                "AES",
                encrypt_credential("import-privacy-secret"),
                "2026-10-07T00:00:00+00:00",
            ),
        )
        conn.commit()

    async def fake_enroll(device_id, *, actor=None):
        # Enrollment is deliberately after commit so a remote API failure can
        # never roll back the CMDB asset.
        with get_db_connection() as conn:
            row = conn.execute(
                """SELECT pa.management_ip, pa.snmp_credential_id, d.ip_address
                     FROM physical_assets pa JOIN devices d ON d.asset_id = pa.id
                    WHERE d.id = ?""",
                (device_id,),
            ).fetchone()
        assert row is not None
        assert row["management_ip"] == "192.0.2.87"
        assert row["ip_address"] == "192.0.2.87"
        assert row["snmp_credential_id"] == "cred-import-snmpv3"
        assert actor is not None
        return {
            "status": "profile_updated_and_bound",
            "message": "profile applied",
            "profile_applied": True,
        }

    from services import librenms_enrollment_service
    monkeypatch.setattr(librenms_enrollment_service, "enroll_imported_network_device", fake_enroll)

    result = assets.import_assets([
        assets.AssetCreate(
            asset_type="network_device",
            hostname="",
            management_ip="192.0.2.87",
            vendor="Huawei",
            model="S6730",
            snmp_credential_name="import-snmpv3-edge",
        )
    ])

    assert result["created"] == 1
    assert result["hostname_sync"]["total"] == 1
    assert result["hostname_sync"]["failed"] == 1
    assert result["snmp_identification"]["items"][0]["status"] == "probe_failed"
    enrollment = result["librenms_enrollment"]
    assert {key: enrollment[key] for key in ("total", "succeeded", "failed", "failed_items")} == {
        "total": 1,
        "succeeded": 1,
        "failed": 0,
        "failed_items": [],
    }
    enrollment_item = enrollment["items"][0]
    assert enrollment_item["row"] == 1
    assert enrollment_item["device_id"]
    assert enrollment_item["hostname"] == enrollment_item["ip"] == "192.0.2.87"
    assert enrollment_item["status"] == "profile_updated_and_bound"
    assert enrollment_item["profile_applied"] is True
    assert "import-auth-secret" not in str(result)
    assert "import-privacy-secret" not in str(result)


def test_duplicate_import_retries_only_the_persisted_snmp_profile(isolated_db, monkeypatch):
    with get_db_connection() as conn:
        conn.executemany(
            """INSERT INTO credentials
               (id, credential_name, credential_type, snmp_community, created_at)
               VALUES (?, ?, 'snmpv2', ?, ?)""",
            [
                ("cred-retry-v2-a", "retry-profile-a", encrypt_credential("community-a"), "2026-10-08T00:00:00+00:00"),
                ("cred-retry-v2-b", "retry-profile-b", encrypt_credential("community-b"), "2026-10-08T00:00:00+00:00"),
            ],
        )
        conn.commit()

    async def fake_snmp_get(*_args, **_kwargs):
        return "retry-device.example"

    import services.snmp_service as snmp_service
    monkeypatch.setattr(snmp_service, "_snmp_get", fake_snmp_get)
    enrollment_calls = []

    async def fake_enroll(device_id, *, actor=None):
        enrollment_calls.append(device_id)
        return {
            "status": "api_failed",
            "message": "LibreNMS test failure",
            "profile_applied": False,
        }

    from services import librenms_enrollment_service
    monkeypatch.setattr(librenms_enrollment_service, "enroll_imported_network_device", fake_enroll)

    initial = assets.AssetCreate(
        asset_type="network_device",
        asset_tag="RETRY-PROFILE-IMPORT",
        hostname="retry-device-placeholder",
        management_ip="192.0.2.90",
        vendor="Cisco",
        snmp_credential_name="retry-profile-a",
    )
    first = assets.import_assets([initial])
    device_id = first["librenms_enrollment"]["items"][0]["device_id"]
    assert first["librenms_enrollment"]["items"][0]["status"] == "api_failed"
    assert enrollment_calls == [device_id]

    changed_profile = assets.import_assets([
        assets.AssetCreate(
            asset_type="network_device",
            asset_tag="RETRY-PROFILE-IMPORT",
            hostname="retry-device-placeholder",
            management_ip="192.0.2.90",
            vendor="Cisco",
            snmp_credential_name="retry-profile-b",
        )
    ])
    changed_item = changed_profile["librenms_enrollment"]["items"][0]
    assert changed_item["status"] == "skipped_duplicate_profile_mismatch"
    assert changed_item["asset_status"] == "skipped"
    assert changed_profile["librenms_enrollment"]["total"] == 0
    assert enrollment_calls == [device_id]

    retry_same_profile = assets.import_assets([initial])
    retry_item = retry_same_profile["librenms_enrollment"]["items"][0]
    assert retry_item["status"] == "api_failed"
    assert retry_same_profile["librenms_enrollment"]["total"] == 1
    assert enrollment_calls == [device_id, device_id]


def test_import_rejects_undecryptable_v2_community_instead_of_sending_ciphertext(isolated_db):
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO credentials
               (id, credential_name, credential_type, snmp_community, created_at)
               VALUES (?, ?, 'snmpv2', ?, ?)""",
            ("cred-broken-v2", "broken-v2-profile", "enc:v2:invalid-ciphertext", "2026-10-08T00:00:00+00:00"),
        )
        conn.commit()

    with pytest.raises(HTTPException, match="SNMPv2 凭据无法解密"):
        assets.import_assets([
            assets.AssetCreate(
                asset_type="network_device",
                asset_tag="BROKEN-V2-IMPORT",
                hostname="broken-v2-import",
                management_ip="192.0.2.88",
                vendor="Cisco",
                snmp_credential_name="broken-v2-profile",
            )
        ])

    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM physical_assets WHERE asset_tag = ?",
            ("BROKEN-V2-IMPORT",),
        ).fetchone()[0] == 0


def test_import_rejects_unknown_librenms_snmpv3_auth_algorithm(isolated_db):
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO credentials (
                   id, credential_name, credential_type, username, snmp_security_level,
                   snmp_auth_protocol, snmp_auth_password, created_at
               ) VALUES (?, ?, 'snmpv3', ?, 'authNoPriv', ?, ?, ?)""",
            (
                "cred-bad-v3-algorithm",
                "bad-v3-algorithm-profile",
                "snmp-user",
                "SHA-1024",
                encrypt_credential("auth-secret"),
                "2026-10-08T00:00:00+00:00",
            ),
        )
        conn.commit()

    with pytest.raises(HTTPException, match="SNMPv3 认证算法不受 LibreNMS 支持"):
        assets.import_assets([
            assets.AssetCreate(
                asset_type="network_device",
                asset_tag="BAD-V3-ALGORITHM-IMPORT",
                hostname="bad-v3-algorithm-import",
                management_ip="192.0.2.89",
                vendor="Cisco",
                snmp_credential_name="bad-v3-algorithm-profile",
            )
        ])

    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM physical_assets WHERE asset_tag = ?",
            ("BAD-V3-ALGORITHM-IMPORT",),
        ).fetchone()[0] == 0


def test_batch_import_keeps_imported_hostname_and_reports_snmp_sync_failure(isolated_db, monkeypatch):
    async def fake_snmp_get(*_args, **_kwargs):
        raise TimeoutError('test-only timeout')

    import services.snmp_service as snmp_service
    monkeypatch.setattr(snmp_service, '_snmp_get', fake_snmp_get)
    result = assets.import_assets([
        assets.AssetCreate(
            asset_type='network_device',
            hostname='manual-device-name',
            management_ip='192.0.2.86',
            vendor='H3C',
            platform='h3c_comware',
            lifecycle_status='staging',
            asset_origin='new',
            snmp_community='test-community-only',
        )
    ], detailed=True)

    assert result['created'] == 1
    assert result['hostname_sync']['succeeded'] == 0
    assert result['hostname_sync']['failed'] == 1
    failure = result['hostname_sync']['failed_items'][0]
    assert failure['previous_hostname'] == 'manual-device-name'
    assert failure['status'] == 'failed'
    assert 'TimeoutError' in failure['error']
    assert 'test-community-only' not in str(result)
    with get_db_connection() as conn:
        row = conn.execute(
            '''SELECT pa.hostname AS asset_hostname, d.hostname AS device_hostname
               FROM physical_assets pa JOIN devices d ON d.asset_id = pa.id
               WHERE pa.management_ip = ?''',
            ('192.0.2.86',),
        ).fetchone()
    assert row['asset_hostname'] == row['device_hostname'] == 'manual-device-name'


def test_batch_import_rejects_non_snmp_credential_name(isolated_db):
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO credentials (
                   id, credential_name, credential_type, username,
                   encrypted_password, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "cred-import-ssh",
                "import-ssh-only",
                "ssh_password",
                "ops",
                encrypt_credential("not-a-snmp-secret"),
                "2026-07-21T00:00:00+00:00",
            ),
        )
        conn.commit()

    with pytest.raises(HTTPException, match="SNMP凭据类型不受支持"):
        assets.import_assets([
            assets.AssetCreate(
                asset_type="network_device",
                hostname="imported-snmp-wrong-type",
                management_ip="192.0.2.83",
                vendor="Cisco",
                model="C9300",
                platform="cisco_ios",
                lifecycle_status="staging",
                asset_origin="new",
                snmp_credential_name="import-ssh-only",
            )
        ])

    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS count FROM physical_assets WHERE hostname = ?",
            ("imported-snmp-wrong-type",),
        ).fetchone()["count"] == 0


def test_batch_import_keeps_legacy_snmp_community_without_binding(isolated_db):
    result = assets.import_assets([
        assets.AssetCreate(
            asset_type="network_device",
            hostname="imported-snmp-community-only",
            management_ip="192.0.2.84",
            vendor="Cisco",
            model="C9300",
            platform="cisco_ios",
            lifecycle_status="staging",
            asset_origin="new",
            snmp_community="community-legacy",
            snmp_port=1161,
        )
    ])

    assert result["created"] == 1
    with get_db_connection() as conn:
        asset = conn.execute(
            "SELECT snmp_community, snmp_port, snmp_credential_id FROM physical_assets WHERE hostname = ?",
            ("imported-snmp-community-only",),
        ).fetchone()
        device = conn.execute(
            "SELECT snmp_port, snmp_credential_id FROM devices WHERE hostname = ?",
            ("imported-snmp-community-only",),
        ).fetchone()
    assert assets.decrypt_credential(asset["snmp_community"]) == "community-legacy"
    assert asset["snmp_port"] == 1161
    assert asset["snmp_credential_id"] in (None, "")
    assert device["snmp_port"] == 1161
    assert device["snmp_credential_id"] in (None, "")


def test_batch_import_rejects_missing_snmp_credential_name(isolated_db):
    with pytest.raises(HTTPException, match="SNMP凭据不存在"):
        assets.import_assets([
            assets.AssetCreate(
                asset_type="network_device",
                hostname="imported-snmp-missing",
                management_ip="192.0.2.85",
                vendor="Cisco",
                model="C9300",
                platform="cisco_ios",
                lifecycle_status="staging",
                asset_origin="new",
                snmp_credential_name="missing-snmp-credential",
            )
        ])


def test_detailed_import_explains_missing_snmp_profile_without_echoing_input(isolated_db):
    result = assets.import_assets([
        assets.AssetCreate(
            asset_type='network_device', hostname='missing-profile-feedback',
            management_ip='192.0.2.86', vendor='H3C', platform='h3c_comware',
            snmp_credential_name='missing-profile-do-not-echo',
        )
    ], detailed=True)

    assert result['created'] == 0
    assert result['failed'] == 1
    failure = result['failed_items'][0]
    assert failure['code'] == 'ASSET_SNMP_CREDENTIAL_NOT_FOUND'
    assert '凭据中心' in failure['message']
    assert 'missing-profile-do-not-echo' not in str(result)


def _create_asset_deferred_enrichment(body, actor):
    from unittest.mock import Mock

    # Keep asset creation on the normal API path while preventing its
    # post-commit enrichment task from running before the manual retry test.
    return assets.create_asset(body, background_tasks=Mock(), _user=actor)


def test_batch_manual_snmp_sync_updates_hostname_model_and_rack(isolated_db, make_user, monkeypatch):
    from services import rack_service, snmp_entity_model_service, snmp_import_identification_service, snmp_service

    actor = make_user("manual-snmp-sync-admin", role="Administrator", tenant_id="tenant-default")
    with get_db_connection() as conn:
        rack = rack_service.create_rack(
            conn,
            name="manual-snmp-sync-rack",
            site_id="site-default",
            total_u=20,
            rack_code="manual-snmp-sync-rack",
        )

    asset = _create_asset_deferred_enrichment(
        assets.AssetCreate(
            asset_type="network_device",
            asset_tag="MANUAL-SNMP-SYNC-1",
            hostname="retry-placeholder",
            management_ip="192.0.2.241",
            vendor="H3C",
            platform="h3c_comware",
            snmp_community="manual-retry-community",
            rack_id=rack["id"],
            planned_start_u=7,
            rack_model_key="generic_switch_1u_24p",
        ),
        actor,
    )

    identity_values = {
        "1.3.6.1.2.1.1.2.0": ".1.3.6.1.4.1.25506.11.1.1",
        "1.3.6.1.2.1.1.1.0": "H3C Comware Platform Software, Software Version 7.1.070\r\nH3C S6850",
        "1.3.6.1.2.1.1.5.0": "manual-retry-switch",
    }
    observed_gets = []

    async def fake_snmp_get(_ip, _community, oid, _port, **_kwargs):
        observed_gets.append(oid)
        return identity_values.get(oid)

    async def fake_chassis_model(_ip, _settings):
        return "H3C S6850"

    monkeypatch.setattr(snmp_service, "_snmp_get", fake_snmp_get)
    monkeypatch.setattr(snmp_entity_model_service, "read_chassis_model", fake_chassis_model)
    monkeypatch.setattr(snmp_import_identification_service, "ensure_rules_available", lambda: {"status": "cached"})
    monkeypatch.setattr(snmp_import_identification_service, "resolve_rule", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        snmp_import_identification_service,
        "resolve_snmp_vendor_identity",
        lambda *_args, **_kwargs: {
            "status": "identified",
            "vendor": "H3C",
            "platform": "h3c_comware",
            "model": "H3C S6850",
            "software_version": "7.1.070",
            "source": "sysDescr",
        },
    )

    result = assets.batch_snmp_sync_assets(
        assets.BatchAssetSnmpSyncRequest(asset_ids=[asset["id"]]),
        _user=actor,
    )

    assert result["requested"] == 1
    assert result["synced"] == 1
    assert result["partial"] == result["failed"] == result["skipped"] == 0
    item = result["results"][0]
    assert item["status"] == "synced"
    assert item["hostname"] == "manual-retry-switch"
    assert item["detected_model"] == item["synced_model"] == "S6850"
    assert item["model_source"] == "entity_mib"
    assert item["rack_sync"]["status"] == "synced"
    assert set(observed_gets) == set(identity_values)
    assert "manual-retry-community" not in str(result)

    with get_db_connection() as conn:
        stored_asset = conn.execute(
            "SELECT hostname, model, rack_id FROM physical_assets WHERE id = ?", (asset["id"],)
        ).fetchone()
        stored_device = conn.execute(
            "SELECT hostname, model FROM devices WHERE id = ?", (asset["device_id"],)
        ).fetchone()
        placement = conn.execute(
            """SELECT rd.model_key, dt.vendor, dt.model, rd.start_u
                 FROM rack_devices rd JOIN device_types dt ON dt.id = rd.device_type_id
                WHERE rd.asset_id = ?""",
            (asset["id"],),
        ).fetchone()
        audit_count = conn.execute(
            "SELECT COUNT(*) AS count FROM audit_events WHERE event_type = ? AND target_id = ?",
            ("asset.snmp_identity_sync", asset["id"]),
        ).fetchone()["count"]
    assert (stored_asset["hostname"], stored_asset["model"], stored_asset["rack_id"]) == (
        "manual-retry-switch", "S6850", rack["id"]
    )
    assert (stored_device["hostname"], stored_device["model"]) == ("manual-retry-switch", "S6850")
    assert (placement["model_key"], placement["vendor"], placement["model"], placement["start_u"]) == (
        "H3C:S6850", "H3C", "S6850", 7
    )
    assert audit_count == 1


def test_batch_manual_snmp_sync_marks_retained_model_partial_when_no_new_model_is_read(
    isolated_db,
    make_user,
    monkeypatch,
):
    from services import snmp_entity_model_service, snmp_import_identification_service, snmp_service

    actor = make_user("manual-snmp-sync-retained-model", role="Administrator", tenant_id="tenant-default")
    asset = _create_asset_deferred_enrichment(
        assets.AssetCreate(
            asset_type="network_device",
            asset_tag="MANUAL-SNMP-RETAINED-MODEL",
            hostname="retained-model-placeholder",
            management_ip="192.0.2.245",
            vendor="H3C",
            platform="h3c_comware",
            model="H3C S6850",
            snmp_community="manual-retained-model-community",
        ),
        actor,
    )
    identity_values = {
        "1.3.6.1.2.1.1.2.0": ".1.3.6.1.4.1.25506.11.1.1",
        "1.3.6.1.2.1.1.1.0": "H3C Comware Platform Software, Software Version 7.1.070",
        "1.3.6.1.2.1.1.5.0": "retained-model-switch",
    }

    async def fake_snmp_get(_ip, _community, oid, _port, **_kwargs):
        return identity_values.get(oid)

    async def no_chassis_model(_ip, _settings):
        return ""

    monkeypatch.setattr(snmp_service, "_snmp_get", fake_snmp_get)
    monkeypatch.setattr(snmp_entity_model_service, "read_chassis_model", no_chassis_model)
    monkeypatch.setattr(snmp_import_identification_service, "ensure_rules_available", lambda: {"status": "cached"})
    monkeypatch.setattr(snmp_import_identification_service, "resolve_rule", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        snmp_import_identification_service,
        "resolve_snmp_vendor_identity",
        lambda *_args, **_kwargs: {
            "status": "identified",
            "vendor": "H3C",
            "platform": "h3c_comware",
            "model": "",
            "software_version": "7.1.070",
            "source": "sysObjectID",
        },
    )

    result = assets.batch_snmp_sync_assets(
        assets.BatchAssetSnmpSyncRequest(asset_ids=[asset["id"]]),
        _user=actor,
    )

    assert result["synced"] == 0
    assert result["partial"] == 1
    item = result["results"][0]
    assert item["status"] == "partial"
    assert item["hostname"] == "retained-model-switch"
    assert item["synced_model"] == "S6850"
    assert item["model_source"] == "existing"
    assert "本次未获取到新型号" in item["message"]
    assert "当前型号已保留" in item["message"]


def test_batch_manual_snmp_sync_skips_disabled_or_non_network_assets(isolated_db, make_user, monkeypatch):
    from unittest.mock import Mock
    from services import snmp_entity_model_service, snmp_service

    actor = make_user("manual-snmp-sync-disabled", role="Administrator", tenant_id="tenant-default")
    network_asset = _create_asset_deferred_enrichment(
        assets.AssetCreate(
            asset_type="network_device",
            asset_tag="MANUAL-SNMP-SYNC-DISABLED",
            hostname="disabled-sync-host",
            management_ip="192.0.2.242",
            vendor="H3C",
            platform="h3c_comware",
            model="Existing Model",
            snmp_community="must-not-probe-community",
        ),
        actor,
    )
    server_asset = assets.create_asset(
        assets.AssetCreate(
            asset_type="server",
            asset_tag="MANUAL-SNMP-SYNC-SERVER",
            hostname="manual-sync-server",
            management_ip="192.0.2.243",
        ),
        background_tasks=Mock(),
        _user=actor,
    )
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE devices SET snmp_collection_enabled = FALSE WHERE id = ?",
            (network_asset["device_id"],),
        )
        conn.commit()

    observed_gets = []
    observed_walks = []

    async def forbidden_snmp_get(*_args, **_kwargs):
        observed_gets.append(True)
        return None

    async def forbidden_chassis_walk(*_args, **_kwargs):
        observed_walks.append(True)
        return ""

    monkeypatch.setattr(snmp_service, "_snmp_get", forbidden_snmp_get)
    monkeypatch.setattr(snmp_entity_model_service, "read_chassis_model", forbidden_chassis_walk)
    result = assets.batch_snmp_sync_assets(
        assets.BatchAssetSnmpSyncRequest(asset_ids=[network_asset["id"], server_asset["id"]]),
        _user=actor,
    )

    assert result["requested"] == 2
    assert result["skipped"] == 2
    assert result["results"][0]["message"] == "该设备已关闭 SNMP 采集，未执行自动识别"
    assert result["results"][1]["message"] == "仅支持同步网络设备"
    assert observed_gets == []
    assert observed_walks == []
    with get_db_connection() as conn:
        unchanged = conn.execute(
            "SELECT hostname, model FROM physical_assets WHERE id = ?", (network_asset["id"],)
        ).fetchone()
    assert (unchanged["hostname"], unchanged["model"]) == ("disabled-sync-host", "Existing Model")


def test_batch_manual_snmp_sync_reports_missing_credentials_and_checks_scope(isolated_db, make_user, monkeypatch):
    actor = make_user("manual-snmp-sync-owner", role="Administrator", tenant_id="tenant-default")
    network_asset = _create_asset_deferred_enrichment(
        assets.AssetCreate(
            asset_type="network_device",
            asset_tag="MANUAL-SNMP-SYNC-NO-CREDENTIAL",
            hostname="no-credential-host",
            management_ip="192.0.2.244",
            vendor="H3C",
            platform="h3c_comware",
        ),
        actor,
    )
    result = assets.batch_snmp_sync_assets(
        assets.BatchAssetSnmpSyncRequest(asset_ids=[network_asset["id"]]),
        _user=actor,
    )
    assert result["failed"] == 1
    assert result["results"][0]["status"] == "failed"
    assert "未配置 SNMP 凭据" in result["results"][0]["message"]

    def deny_update_scope(_user, _row, action):
        assert action == "update"
        raise HTTPException(status_code=403, detail="Asset is outside the user's scope")

    monkeypatch.setattr(assets, "_enforce_asset_row_scope", deny_update_scope)
    with pytest.raises(HTTPException) as exc_info:
        assets.batch_snmp_sync_assets(
            assets.BatchAssetSnmpSyncRequest(asset_ids=[network_asset["id"]]),
            _user=actor,
        )
    assert exc_info.value.status_code == 403


def test_batch_manual_snmp_sync_request_has_no_fixed_device_count_cap():
    request = assets.BatchAssetSnmpSyncRequest(asset_ids=[f"asset-{index}" for index in range(1, 21)])
    assert len(request.asset_ids) == 20
