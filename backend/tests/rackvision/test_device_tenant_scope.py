"""Regression tests for session-owned tenant assignment on device writes."""

from __future__ import annotations

import asyncio
import uuid

import httpx

from api import users
from database import get_db_connection
from main import app


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_device_create_and_import_use_default_org_label_and_require_auth(
    isolated_db,
    make_user,
    monkeypatch,
):
    tenant_id = _id("device-tenant")
    site_id = _id("device-site")
    user = make_user("device-owner", role="Operator")
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET tenant_id = ? WHERE id = ?",
            (tenant_id, user["user_id"]),
        )
        conn.execute(
            "INSERT INTO tenants (id, name, description) VALUES (?, ?, ?)",
            (tenant_id, tenant_id, "Device tenant scope test"),
        )
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
               VALUES (?, ?, ?, 'active', ?)""",
            (site_id, site_id.upper(), "Device tenant test site", tenant_id),
        )
        conn.commit()
    finally:
        conn.close()

    # The endpoint must not retain the old anonymous write behavior.
    unauthenticated = _request(
        "POST",
        "/api/devices",
        json={"hostname": "unauthenticated", "ip_address": "192.0.2.10"},
    )
    assert unauthenticated.status_code == 401, unauthenticated.text

    user_payload = {
        "user_id": user["user_id"],
        "id": user["user_id"],
        "username": "device-owner",
        "role": "Operator",
        "tenant_id": tenant_id,
    }
    monkeypatch.setattr(users, "validate_session_token", lambda token: user_payload)
    headers = {"Authorization": "Bearer device-owner-token"}

    created_id = _id("created-device")
    created = _request(
        "POST",
        "/api/devices",
        headers=headers,
        json={
            "id": created_id,
            "hostname": "created-device",
            "ip_address": "192.0.2.11",
            "platform": "ruijie_rgos",
            "vendor": "Ruijie",
            "tenant_id": "attacker-controlled-tenant",
        },
    )
    assert created.status_code == 200, created.text

    imported_id = _id("imported-device")
    imported = _request(
        "POST",
        "/api/devices/import",
        headers=headers,
        json={
            "devices": [
                {
                    "id": imported_id,
                    "hostname": "imported-device",
                    "ip_address": "192.0.2.12",
                    "platform": "ruijie_rgos",
                    "tenant_id": "attacker-controlled-tenant",
                }
            ],
        },
    )
    assert imported.status_code == 200, imported.text

    asset_created = _request(
        "POST",
        "/api/assets",
        headers=headers,
        json={
            "asset_type": "network_device",
            "hostname": "asset-created-device",
            "management_ip": "192.0.2.14",
            "vendor": "Ruijie",
            "platform": "ruijie_rgos",
            "site_id": site_id,
            "tenant_id": "attacker-controlled-tenant",
        },
    )
    assert asset_created.status_code == 200, asset_created.text
    asset_created_device_id = asset_created.json()["device_id"]

    asset_imported = _request(
        "POST",
        "/api/assets/import",
        headers=headers,
        json=[
            {
                "asset_type": "network_device",
                "hostname": "asset-imported-device",
                "management_ip": "192.0.2.15",
                "vendor": "Ruijie",
                "platform": "ruijie_rgos",
                "site_id": site_id,
                "tenant_id": "attacker-controlled-tenant",
            }
        ],
    )
    assert asset_imported.status_code == 200, asset_imported.text

    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, tenant_id FROM devices WHERE id IN (?, ?) ORDER BY id",
            (created_id, imported_id),
        ).fetchall()
        assert [dict(row) for row in rows] == [
            {"id": created_id, "tenant_id": "tenant-default"},
            {"id": imported_id, "tenant_id": "tenant-default"},
        ]
        asset_rows = conn.execute(
            "SELECT id, hostname, tenant_id FROM devices "
            "WHERE id = ? OR hostname IN (?, ?) ORDER BY hostname",
            (asset_created_device_id, "asset-created-device", "asset-imported-device"),
        ).fetchall()
        assert [dict(row)["tenant_id"] for row in asset_rows] == ["tenant-default", "tenant-default"]
    finally:
        conn.close()


def test_device_write_accepts_authenticated_user_without_tenant(isolated_db, monkeypatch):
    user_payload = {
        "user_id": _id("tenantless-user"),
        "id": _id("tenantless-user-id"),
        "username": "tenantless-operator",
        "role": "Operator",
        "tenant_id": "",
    }
    monkeypatch.setattr(users, "validate_session_token", lambda token: user_payload)

    hostname = _id("tenantless-device")
    response = _request(
        "POST",
        "/api/devices/import",
        headers={"Authorization": "Bearer tenantless-token"},
        json={"devices": [{"hostname": hostname, "ip_address": "192.0.2.13"}]},
    )
    assert response.status_code == 200, response.text
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT tenant_id FROM devices WHERE hostname = ?", (hostname,)).fetchone()
        assert row is not None
        assert row["tenant_id"] == "tenant-default"
    finally:
        conn.close()
