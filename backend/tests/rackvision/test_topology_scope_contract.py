"""Tenant/site scope checks for the RackVision topology read models."""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx

from api import users
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


def test_topology_read_models_are_scoped_to_authorized_asset_sites(isolated_db, make_user, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    tenant_a = _id("topology-tenant-a")
    tenant_b = _id("topology-tenant-b")
    site_a = _id("topology-site-a")
    site_b = _id("topology-site-b")
    device_a = _id("topology-device-a")
    device_b = _id("topology-device-b")
    try:
        for tenant_id in (tenant_a, tenant_b):
            conn.execute(
                "INSERT INTO tenants (id, name, description) VALUES (?, ?, ?)",
                (tenant_id, tenant_id, "RackVision topology scope test"),
            )
        for site_id, tenant_id in ((site_a, tenant_a), (site_b, tenant_b)):
            conn.execute(
                """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
                   VALUES (?, ?, ?, 'active', ?)""",
                (site_id, site_id.upper(), site_id, tenant_id),
            )
        conn.executemany(
            """INSERT INTO devices (id, hostname, status, site_id, ip_address, platform)
               VALUES (?, ?, 'online', ?, ?, 'cisco_ios')""",
            [
                (device_a, "topology-a", site_a, "192.0.2.121"),
                (device_b, "topology-b", site_b, "192.0.2.122"),
            ],
        )
        user = make_user("topology-scope-viewer", role="Viewer")
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
                _id("topology-scope"),
                user["user_id"],
                site_a,
                json.dumps(["view"]),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    user_payload = {
        "user_id": user["user_id"],
        "id": user["user_id"],
        "username": "topology-scope-viewer",
        "role": "Viewer",
        "tenant_id": tenant_a,
    }
    monkeypatch.setattr(users, "validate_session_token", lambda token: user_payload)
    headers = {"Authorization": "Bearer topology-scope-token"}

    sites = _request("GET", "/api/topology/sites", headers=headers)
    assert sites.status_code == 200, sites.text
    assert [item["site_id"] for item in sites.json()["items"]] == [site_a]
    assert sites.json()["items"][0]["device_count"] == 1

    generation = _request("GET", "/api/topology/generation-status", headers=headers)
    assert generation.status_code == 200, generation.text
    assert generation.json()["inventory"]["managed_devices"] == 1

    links = _request("GET", "/api/topology/links", headers=headers)
    assert links.status_code == 200, links.text
    assert links.json()["links"] == []
    assert links.json()["unmanaged_nodes"] == []

