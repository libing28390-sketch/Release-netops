from __future__ import annotations

import pytest
from fastapi import BackgroundTasks, HTTPException

from api import assets
from database import get_db_connection


def _asset(hostname: str) -> assets.AssetCreate:
    return assets.AssetCreate(
        asset_type="server",
        hostname=hostname,
        asset_tag=f"tag-{hostname}",
        management_ip=f"192.0.2.{81 if hostname == 'bad-row' else 80}",
    )


def test_asset_import_detailed_row_failure_and_atomic_rollback(isolated_db, monkeypatch):
    prior_row_visible = []

    def fail_bad_row(_conn, asset_id, body, _user=None):
        if body.hostname == "bad-row":
            with get_db_connection() as verify_conn:
                if verify_conn.execute(
                    "SELECT 1 FROM physical_assets WHERE hostname = ?", ("partial-good-row",)
                ).fetchone():
                    prior_row_visible.append(True)
            raise ValueError("placement conflict")

    monkeypatch.setattr(assets, "_sync_rack_device_from_asset", fail_bad_row)

    detailed = assets.import_assets([_asset("bad-row")], detailed=True)
    assert detailed["created"] == 0
    assert detailed["failed"] == 1
    assert detailed["results"][0]["code"] == "ASSET_IMPORT_VALIDATION_FAILED"

    conn = get_db_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM physical_assets WHERE hostname = ?", ("bad-row",)
        ).fetchone()[0] == 0
    finally:
        conn.close()

    with pytest.raises(HTTPException) as exc_info:
        assets.import_assets([_asset("good-row"), _asset("bad-row")], atomic=True)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "ASSET_IMPORT_ATOMIC_FAILED"

    conn = get_db_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM physical_assets WHERE hostname IN (?, ?)",
            ("good-row", "bad-row"),
        ).fetchone()[0] == 0
    finally:
        conn.close()

    partial = assets.import_assets([_asset("partial-good-row"), _asset("bad-row")], detailed=True)
    assert partial["created"] == 1
    assert partial["failed"] == 1
    assert partial["results"][0]["status"] == "created"
    assert partial["results"][1]["status"] == "failed"
    assert prior_row_visible
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM physical_assets WHERE hostname = ?", ("partial-good-row",)
        ).fetchone()[0] == 1


def test_asset_import_queues_snmp_enrichment_after_committing_asset(isolated_db):
    background_tasks = BackgroundTasks()
    result = assets.import_assets(
        [assets.AssetCreate(
            asset_type="network_device",
            hostname="edge-import-pending",
            asset_tag="tag-edge-import-pending",
            management_ip="192.0.2.90",
            vendor="Huawei",
            model="S6730",
            platform="huawei_vrp",
        )],
        detailed=True,
        background_tasks=background_tasks,
    )

    assert result["created"] == 1
    assert result["enrichment_pending"] is True
    assert result["snmp_identification"]["pending"] == 1
    assert len(background_tasks.tasks) == 1
    assert result["results"][0]["snmp_identification"]["status"] == "pending"
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM physical_assets WHERE hostname = ?",
            ("edge-import-pending",),
        ).fetchone()[0] == 1


def test_asset_import_reserved_site_error_is_actionable(isolated_db):
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT 1 FROM sites WHERE id = ?", ("site-default",)).fetchone():
            conn.execute(
                """
                INSERT INTO sites (id, site_code, site_name, status, tenant_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("site-default", "DEFAULT_SITE", "Default Site", "active", "tenant-default"),
            )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(HTTPException) as exc_info:
        assets.import_assets([
            assets.AssetCreate(
                asset_type="server",
                hostname="edge-03",
                asset_tag="tag-edge-03",
                site_id="DEFAULT_SITE",
                management_ip="192.0.2.83",
            )
        ])

    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert detail["code"] == "ASSET_SITE_INVALID"
    assert detail["reason"] == "reserved_system_site"
    assert detail["row"] == 1
    assert detail["asset_label"] == "edge-03"
    assert detail["site_label"] == "系统默认站点"
    assert "系统保留站点" in detail["message"]
    assert "site-default" not in detail["message"]


def test_batch_asset_delete_uses_one_monitor_sync_and_reports_item_failures(isolated_db, monkeypatch):
    user = {
        "id": "batch-delete-admin",
        "user_id": "batch-delete-admin",
        "username": "batch-delete-admin",
        "role": "Administrator",
        "tenant_id": "tenant-default",
    }
    created = assets.create_asset(
        assets.AssetCreate(
            asset_type="server",
            hostname="batch-delete-server",
            asset_tag="batch-delete-server",
            management_ip="192.0.2.201",
        ),
        _user=user,
    )
    sync_calls = []
    monkeypatch.setattr(assets, "_trigger_asset_monitoring_sync", lambda: sync_calls.append(True))

    result = assets.batch_delete_assets(
        assets.BatchAssetDeleteRequest(asset_ids=[created["id"], "missing-asset"]),
        _user=user,
    )

    assert result["deleted"] == 1
    assert result["deleted_ids"] == [created["id"]]
    assert result["failed"] == 1
    assert result["failed_items"] == [{"asset_id": "missing-asset", "message": "Asset not found"}]
    assert sync_calls == [True]
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM physical_assets WHERE id = ?", (created["id"],)
        ).fetchone()[0] == 0


def test_batch_asset_delete_preserves_assets_denied_by_scope(isolated_db, monkeypatch):
    user = {
        "id": "batch-delete-scoped-admin",
        "user_id": "batch-delete-scoped-admin",
        "username": "batch-delete-scoped-admin",
        "role": "Administrator",
        "tenant_id": "tenant-default",
    }
    created = assets.create_asset(
        assets.AssetCreate(
            asset_type="server",
            hostname="batch-delete-denied-server",
            asset_tag="batch-delete-denied-server",
            management_ip="192.0.2.202",
        ),
        _user=user,
    )

    def deny_delete(_user, _row, action):
        assert action == "delete"
        raise HTTPException(status_code=403, detail="Asset is outside the user's scope")

    monkeypatch.setattr(assets, "_enforce_asset_row_scope", deny_delete)
    result = assets.batch_delete_assets(
        assets.BatchAssetDeleteRequest(asset_ids=[created["id"]]),
        _user=user,
    )

    assert result["deleted"] == 0
    assert result["failed"] == 1
    assert result["failed_items"] == [{
        "asset_id": created["id"],
        "message": "Asset is outside the user's scope",
    }]
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM physical_assets WHERE id = ?", (created["id"],)
        ).fetchone()[0] == 1
