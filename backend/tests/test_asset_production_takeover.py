import pytest
from fastapi import HTTPException


def _create_legacy_asset(assets):
    result = assets.create_asset(
        assets.AssetCreate(
            asset_type="network_device",
            hostname="legacy-switch",
            management_ip="192.0.2.10",
            vendor="H3C",
            model="S5130",
            lifecycle_status="staging",
            asset_origin="legacy",
        )
    )
    return result["id"], result["device_id"]


def test_production_transition_requires_linked_device(isolated_db):
    from api import assets
    from database import get_db_connection

    asset_id, device_id = _create_legacy_asset(assets)
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(HTTPException) as exc_info:
        assets.update_asset(asset_id, assets.AssetUpdate(lifecycle_status="production"))

    assert exc_info.value.status_code == 422
    assert "缺少关联设备记录" in exc_info.value.detail


def test_asset_stays_staging_until_takeover_succeeds(isolated_db, monkeypatch):
    from api import assets
    from database import get_db_connection
    from services import vault_service

    asset_id, device_id = _create_legacy_asset(assets)
    conn = get_db_connection()
    try:
        conn.execute("UPDATE devices SET onboarding_status = 'verified' WHERE id = ?", (device_id,))
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        vault_service,
        "resolve_device_credentials",
        lambda _device: {"username": "admin", "password": "initial-password"},
    )
    started_threads = []

    class DeferredThread:
        def __init__(self, target, args=(), daemon=None):
            self.target = target
            self.args = args
            started_threads.append(self)

        def start(self):
            return None

    monkeypatch.setattr(assets.threading, "Thread", DeferredThread)

    result = assets.update_asset(asset_id, assets.AssetUpdate(lifecycle_status="production"))

    assert result["rotation_pending"] is True
    assert len(started_threads) == 1
    conn = get_db_connection()
    try:
        asset = conn.execute(
            "SELECT lifecycle_status FROM physical_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        device = conn.execute(
            "SELECT lifecycle_status, rotation_status FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
    finally:
        conn.close()
    assert asset["lifecycle_status"] == "staging"
    assert device["lifecycle_status"] == "staging"
    assert device["rotation_status"] == "rotating"


def test_takeover_success_commits_production_status(isolated_db, monkeypatch):
    from api import assets
    from database import get_db_connection
    from services import password_rotation_service, vault_service

    asset_id, device_id = _create_legacy_asset(assets)
    conn = get_db_connection()
    try:
        conn.execute("UPDATE devices SET onboarding_status = 'verified' WHERE id = ?", (device_id,))
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        vault_service,
        "resolve_device_credentials",
        lambda _device: {"username": "admin", "password": "initial-password"},
    )
    monkeypatch.setattr(
        password_rotation_service,
        "rotate_password",
        lambda _device_id, role="admin": {"success": True},
    )
    started_threads = []

    class CapturedThread:
        def __init__(self, target, args=(), daemon=None):
            self.target = target
            self.args = args
            started_threads.append(self)

        def start(self):
            return None

    monkeypatch.setattr(assets.threading, "Thread", CapturedThread)

    assets.update_asset(asset_id, assets.AssetUpdate(lifecycle_status="production"))
    started_threads[0].target(*started_threads[0].args)

    conn = get_db_connection()
    try:
        asset = conn.execute(
            "SELECT lifecycle_status, is_managed FROM physical_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        device = conn.execute(
            "SELECT lifecycle_status, rotation_status, is_managed FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
    finally:
        conn.close()
    assert asset["lifecycle_status"] == "production"
    assert asset["is_managed"] == 1
    assert device["lifecycle_status"] == "production"
    assert device["rotation_status"] == "completed"
    assert device["is_managed"] == 1


def test_legacy_device_can_enter_production_without_password_rotation(isolated_db, monkeypatch):
    from api import assets
    from database import get_db_connection
    from services import vault_service

    asset_id, device_id = _create_legacy_asset(assets)
    conn = get_db_connection()
    try:
        conn.execute("UPDATE devices SET onboarding_status = 'verified' WHERE id = ?", (device_id,))
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        vault_service,
        "resolve_device_credentials",
        lambda _device: {"normal_username": "operator", "normal_password": "existing-password"},
    )
    monkeypatch.setattr(
        assets.threading,
        "Thread",
        lambda *args, **kwargs: pytest.fail("legacy exemption must not start password rotation"),
    )

    result = assets.update_asset(
        asset_id,
        assets.AssetUpdate(
            lifecycle_status="production",
            production_mode="legacy_exempt",
            takeover_exempt_reason="存量设备保持现有普通账号",
        ),
    )

    assert result["legacy_exempt"] is True
    conn = get_db_connection()
    try:
        asset = conn.execute(
            "SELECT lifecycle_status, is_managed, credential_governance_mode, takeover_exempt_reason "
            "FROM physical_assets WHERE id = ?",
            (asset_id,),
        ).fetchone()
        device = conn.execute(
            "SELECT lifecycle_status, rotation_status, is_managed FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
    finally:
        conn.close()
    assert asset["lifecycle_status"] == "production"
    assert asset["is_managed"] == 0
    assert asset["credential_governance_mode"] == "legacy_exempt"
    assert asset["takeover_exempt_reason"] == "存量设备保持现有普通账号"
    assert device["lifecycle_status"] == "production"
    assert device["rotation_status"] == "exempt"
    assert device["is_managed"] == 0


def test_legacy_exemption_requires_reason(isolated_db, monkeypatch):
    from api import assets
    from database import get_db_connection
    from services import vault_service

    asset_id, device_id = _create_legacy_asset(assets)
    conn = get_db_connection()
    try:
        conn.execute("UPDATE devices SET onboarding_status = 'verified' WHERE id = ?", (device_id,))
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(
        vault_service,
        "resolve_device_credentials",
        lambda _device: {"normal_username": "operator", "normal_password": "existing-password"},
    )

    with pytest.raises(HTTPException) as exc_info:
        assets.update_asset(
            asset_id,
            assets.AssetUpdate(
                lifecycle_status="production",
                production_mode="legacy_exempt",
                takeover_exempt_reason="短",
            ),
        )

    assert exc_info.value.status_code == 422
    assert "豁免原因" in exc_info.value.detail


def test_new_asset_cannot_be_created_directly_in_production(isolated_db):
    from api import assets
    from database import get_db_connection

    result = assets.create_asset(
        assets.AssetCreate(
            asset_type="network_device",
            hostname="new-switch",
            management_ip="192.0.2.20",
            lifecycle_status="production",
            asset_origin="new",
        )
    )
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT lifecycle_status, asset_origin FROM physical_assets WHERE id = ?",
            (result["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row["lifecycle_status"] == "staging"
    assert row["asset_origin"] == "new"


def test_legacy_asset_can_be_created_directly_in_production(isolated_db):
    from api import assets
    from database import get_db_connection

    result = assets.create_asset(
        assets.AssetCreate(
            asset_type="network_device",
            hostname="existing-switch",
            management_ip="192.0.2.30",
            lifecycle_status="production",
            asset_origin="legacy",
            takeover_exempt_reason="存量设备暂时沿用普通账号",
            normal_username="operator",
            normal_password="existing-password",
        )
    )
    assert result["legacy_exempt"] is True
    conn = get_db_connection()
    try:
        asset = conn.execute(
            "SELECT lifecycle_status, asset_origin, credential_governance_mode, is_managed "
            "FROM physical_assets WHERE id = ?",
            (result["id"],),
        ).fetchone()
        device = conn.execute(
            "SELECT lifecycle_status, rotation_status, is_managed FROM devices WHERE id = ?",
            (result["device_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert asset["lifecycle_status"] == "production"
    assert asset["asset_origin"] == "legacy"
    assert asset["credential_governance_mode"] == "legacy_exempt"
    assert asset["is_managed"] == 0
    assert device["lifecycle_status"] == "production"
    assert device["rotation_status"] == "exempt"
    assert device["is_managed"] == 0


def test_import_new_asset_is_forced_to_staging(isolated_db):
    from api import assets
    from database import get_db_connection

    result = assets.import_assets([
        assets.AssetCreate(
            asset_type="network_device",
            hostname="imported-new-switch",
            lifecycle_status="production",
            asset_origin="new",
        )
    ])

    assert result == {"created": 1, "skipped": 0}
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT lifecycle_status, asset_origin FROM physical_assets WHERE hostname = ?",
            ("imported-new-switch",),
        ).fetchone()
    finally:
        conn.close()
    assert row["lifecycle_status"] == "staging"
    assert row["asset_origin"] == "new"


def test_import_legacy_production_asset_records_exemption(isolated_db):
    from api import assets
    from database import get_db_connection

    result = assets.import_assets([
        assets.AssetCreate(
            asset_type="network_device",
            hostname="imported-legacy-switch",
            lifecycle_status="production",
            asset_origin="legacy",
            takeover_exempt_reason="Existing production device",
            normal_username="operator",
            normal_password="existing-password",
        )
    ])

    assert result == {"created": 1, "skipped": 0}
    conn = get_db_connection()
    try:
        asset = conn.execute(
            "SELECT id, lifecycle_status, asset_origin, credential_governance_mode, is_managed "
            "FROM physical_assets WHERE hostname = ?",
            ("imported-legacy-switch",),
        ).fetchone()
        device = conn.execute(
            "SELECT lifecycle_status, rotation_status, is_managed FROM devices WHERE asset_id = ?",
            (asset["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert asset["lifecycle_status"] == "production"
    assert asset["asset_origin"] == "legacy"
    assert asset["credential_governance_mode"] == "legacy_exempt"
    assert asset["is_managed"] == 0
    assert device["lifecycle_status"] == "production"
    assert device["rotation_status"] == "exempt"
    assert device["is_managed"] == 0


def test_huawei_vendor_corrects_stale_cisco_platform(isolated_db):
    from api import assets
    from database import get_db_connection

    result = assets.create_asset(
        assets.AssetCreate(
            asset_type="network_device",
            hostname="huawei-switch",
            management_ip="192.0.2.100",
            vendor="Huawei",
            model="S6800",
            platform="cisco_ios",
        )
    )

    conn = get_db_connection()
    try:
        asset = conn.execute(
            "SELECT platform FROM physical_assets WHERE id = ?", (result["id"],)
        ).fetchone()
        device = conn.execute(
            "SELECT platform FROM devices WHERE id = ?", (result["device_id"],)
        ).fetchone()
    finally:
        conn.close()

    assert asset["platform"] == "huawei_vrp"
    assert device["platform"] == "huawei_vrp"


def test_vendor_change_repairs_existing_platform(isolated_db):
    from api import assets
    from database import get_db_connection

    result = assets.create_asset(
        assets.AssetCreate(
            asset_type="network_device",
            hostname="vendor-change-switch",
            management_ip="192.0.2.101",
            vendor="Cisco",
            platform="cisco_ios",
        )
    )

    assets.update_asset(
        result["id"],
        assets.AssetUpdate(vendor="Huawei", platform="cisco_ios"),
    )

    conn = get_db_connection()
    try:
        asset = conn.execute(
            "SELECT vendor, platform FROM physical_assets WHERE id = ?", (result["id"],)
        ).fetchone()
        device = conn.execute(
            "SELECT vendor, platform FROM devices WHERE id = ?", (result["device_id"],)
        ).fetchone()
    finally:
        conn.close()

    assert dict(asset) == {"vendor": "Huawei", "platform": "huawei_vrp"}
    assert dict(device) == {"vendor": "Huawei", "platform": "huawei_vrp"}
