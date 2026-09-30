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
            hostname="imported-snmp-by-name",
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

    with pytest.raises(HTTPException, match="SNMPv2"):
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
