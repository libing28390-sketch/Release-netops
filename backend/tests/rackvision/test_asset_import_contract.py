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
