from __future__ import annotations

import pytest
from fastapi import HTTPException

from api import assets
from core.crypto import encrypt_credential
from database import get_db_connection
from schemas.web import WebAccessProfileInput


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


def test_import_commits_asset_then_enrolls_with_bound_snmpv3_profile(isolated_db, monkeypatch):
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
    assert result["hostname_sync"]["total"] == 0
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
