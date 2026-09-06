"""HTTP contract tests for RackVision asset scope and public projections."""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx

from api import assets, users
from main import app
from database import get_db_connection


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_asset_reads_are_site_scoped_and_secrets_are_not_projected(isolated_db, make_user, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    tenant_a = _id("asset-tenant-a")
    tenant_b = _id("asset-tenant-b")
    site_a = _id("asset-site-a")
    site_a2 = _id("asset-site-a2")
    site_b = _id("asset-site-b")
    try:
        for tenant_id in (tenant_a, tenant_b):
            conn.execute(
                "INSERT INTO tenants (id, name, description) VALUES (?, ?, ?)",
                (tenant_id, tenant_id, "RackVision asset scope test"),
            )
        for site_id, tenant_id in ((site_a, tenant_a), (site_a2, tenant_a), (site_b, tenant_b)):
            conn.execute(
                """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
                   VALUES (?, ?, ?, 'active', ?)""",
                (site_id, site_id.upper(), site_id, tenant_id),
            )
        conn.commit()
    finally:
        conn.close()

    visible = assets.create_asset(
        assets.AssetCreate(
            asset_type="server",
            asset_tag=_id("visible-asset"),
            hostname="asset-visible",
            site_id=site_a,
            management_ip="192.0.2.101",
            username="operator",
            password="secret-value",
            snmp_community="snmp-secret",
        )
    )
    same_tenant_hidden = assets.create_asset(
        assets.AssetCreate(
            asset_type="server",
            asset_tag=_id("same-tenant-asset"),
            hostname="asset-same-tenant-hidden",
            site_id=site_a2,
            management_ip="192.0.2.102",
        )
    )
    other_tenant = assets.create_asset(
        assets.AssetCreate(
            asset_type="server",
            asset_tag=_id("other-tenant-asset"),
            hostname="asset-other-tenant",
            site_id=site_b,
            management_ip="192.0.2.103",
        )
    )

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE physical_assets SET vault_path = ?, password = ?, snmp_community = ? WHERE id = ?",
            ("vault://do-not-disclose", "encrypted-password", "encrypted-snmp", visible["id"]),
        )
        user = make_user("asset-scope-operator", role="Operator")
        conn.execute(
            "UPDATE users SET tenant_id = ? WHERE id = ?",
            (tenant_a, user["user_id"]),
        )
        conn.execute(
            """INSERT INTO user_resource_scopes (
                   id, user_id, resource_type, scope_type, scope_id,
                   actions_json, created_at
               ) VALUES (?, ?, 'asset', 'site', ?, ?, CURRENT_TIMESTAMP)""",
            (
                _id("asset-scope"),
                user["user_id"],
                site_a,
                json.dumps(["view", "create", "update", "delete", "verify"]),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    user_payload = {
        "user_id": user["user_id"],
        "id": user["user_id"],
        "username": "asset-scope-operator",
        "role": "Operator",
        "tenant_id": tenant_a,
    }
    monkeypatch.setattr(users, "validate_session_token", lambda token: user_payload)
    headers = {"Authorization": "Bearer asset-scope-token"}

    listed = _request("GET", "/api/assets", headers=headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert [item["id"] for item in items] == [visible["id"]]
    assert "vault_path" not in items[0]
    assert items[0]["password"] == ""
    assert items[0]["password_set"] is True
    assert items[0]["snmp_community"] == ""
    assert items[0]["snmp_community_set"] is True

    summary = _request("GET", "/api/assets/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    assert summary.json()["total"] == 1

    tree = _request("GET", "/api/assets/tree", headers=headers)
    assert tree.status_code == 200, tree.text
    assert [item["site_id"] for item in tree.json()["items"]] == [site_a]

    detail = _request("GET", f"/api/assets/{visible['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert "vault_path" not in detail.json()
    assert detail.json()["password_set"] is True

    same_tenant_denied = _request("GET", f"/api/assets/{same_tenant_hidden['id']}", headers=headers)
    assert same_tenant_denied.status_code == 403, same_tenant_denied.text
    assert same_tenant_denied.json()["error"]["code"] == "RESOURCE_SCOPE_DENIED"

    other_tenant_denied = _request("GET", f"/api/assets/{other_tenant['id']}", headers=headers)
    assert other_tenant_denied.status_code == 403, other_tenant_denied.text
    assert other_tenant_denied.json()["error"]["code"] == "RESOURCE_SCOPE_DENIED"

    create_other_site = _request(
        "POST",
        "/api/assets",
        headers=headers,
        json={
            "asset_type": "server",
            "hostname": "asset-write-denied",
            "site_id": site_b,
            "management_ip": "192.0.2.104",
        },
    )
    assert create_other_site.status_code == 403, create_other_site.text
    assert create_other_site.json()["error"]["code"] == "RESOURCE_SCOPE_DENIED"

