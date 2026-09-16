from __future__ import annotations

import pytest
from fastapi import HTTPException

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
    def fail_bad_row(_conn, asset_id, body, _user=None):
        if body.hostname == "bad-row":
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
