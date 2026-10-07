"""HTTP save contracts for tenant-scoped physical assets."""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx

import database
from api import users
from main import app
from services import collector_sync_service, password_rotation_service


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def _asset_state(asset_id: str) -> dict:
    connection = database.get_db_connection()
    try:
        row = connection.execute(
            """SELECT pa.id, pa.asset_tag, pa.hostname, pa.vendor AS asset_vendor,
                      pa.model AS asset_model, pa.platform AS asset_platform,
                      pa.management_ip, pa.site_id AS asset_site_id,
                      pa.lifecycle_status, pa.department, pa.notes,
                      d.id AS device_id, d.hostname AS device_hostname,
                      d.vendor AS device_vendor, d.model AS device_model,
                      d.platform AS device_platform, d.ip_address,
                      d.site_id AS device_site_id, d.tenant_id AS device_tenant_id
                 FROM physical_assets pa
                 LEFT JOIN devices d ON d.asset_id = pa.id
                WHERE pa.id = ?""",
            (asset_id,),
        ).fetchone()
        assert row is not None
        return dict(row)
    finally:
        connection.close()


def _create_network_asset(
    headers: dict[str, str],
    *,
    site_id: str,
    prefix: str,
    management_ip: str,
    vendor: str = "Cisco",
) -> dict:
    response = _request(
        "POST",
        "/api/assets",
        headers=headers,
        json={
            "asset_type": "network_device",
            "asset_tag": _id(f"{prefix}-tag"),
            "hostname": _id(f"{prefix}-host"),
            "vendor": vendor,
            "model": _id(f"{prefix}-model"),
            "platform": "cisco_iosxe" if vendor == "Cisco" else "",
            "site_id": site_id,
            "management_ip": management_ip,
            "business_ip": f"198.51.100.{management_ip.rsplit('.', 1)[-1]}",
            "connection_method": "none",
            "username": "",
            "password": "",
            "status": "active",
            "lifecycle_status": "staging",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_tenant_site(connection, tenant_id: str, site_id: str) -> None:
    connection.execute(
        "INSERT INTO tenants (id, name, description) VALUES (?, ?, ?)",
        (tenant_id, tenant_id, "Asset save contract test"),
    )
    connection.execute(
        """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
           VALUES (?, ?, ?, 'active', ?)""",
        (site_id, site_id.upper(), site_id, tenant_id),
    )


def _grant_site_asset_scope(connection, user_id: str, site_id: str) -> None:
    connection.execute(
        """INSERT INTO user_resource_scopes (
               id, user_id, resource_type, scope_type, scope_id,
               actions_json, created_at
           ) VALUES (?, ?, 'asset', 'site', ?, ?, CURRENT_TIMESTAMP)""",
        (_id("asset-save-scope"), user_id, site_id, json.dumps(["view", "create", "update", "delete", "verify"])),
    )


def test_asset_http_put_preserves_sync_scope_and_rollback_contracts(
    isolated_db,
    make_user,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("OUTBOUND_PROBE_ALLOW_PRIVATE_NETWORKS", "false")
    monkeypatch.setenv("AI_EMBEDDING_MODE", "local")
    monkeypatch.setenv("AI_RERANKER_MODE", "legacy")
    monkeypatch.setenv("AI_PARSER_MODE", "legacy")
    monkeypatch.setenv("AI_OBSERVABILITY_MODE", "off")
    monkeypatch.setenv("AI_CONFIG_CLARIFICATION_ENABLED", "0")

    def unexpected_rotation(*_args, **_kwargs):
        raise AssertionError("staging asset saves must not start password rotation")

    monkeypatch.setattr(password_rotation_service, "rotate_password", unexpected_rotation)
    monkeypatch.setattr(collector_sync_service, "trigger_async_monitoring_sync", lambda: None)

    tenant_a, tenant_b = _id("asset-save-tenant-a"), _id("asset-save-tenant-b")
    site_a, site_b = _id("asset-save-site-a"), _id("asset-save-site-b")
    user_a = make_user(_id("asset-save-operator-a"), role="Operator")
    user_b = make_user(_id("asset-save-operator-b"), role="Operator")

    connection = database.get_db_connection()
    try:
        _create_tenant_site(connection, tenant_a, site_a)
        _create_tenant_site(connection, tenant_b, site_b)
        for user, tenant_id, site_id in (
            (user_a, tenant_a, site_a),
            (user_b, tenant_b, site_b),
        ):
            connection.execute(
                "UPDATE users SET tenant_id = ? WHERE id = ?",
                (tenant_id, user["user_id"]),
            )
            _grant_site_asset_scope(connection, user["user_id"], site_id)
        connection.commit()
    finally:
        connection.close()

    session_payloads = {
        "asset-save-token-a": {
            "user_id": user_a["user_id"],
            "id": user_a["user_id"],
            "username": user_a["username"],
            "role": "Operator",
            "tenant_id": tenant_a,
        },
        "asset-save-token-b": {
            "user_id": user_b["user_id"],
            "id": user_b["user_id"],
            "username": user_b["username"],
            "role": "Operator",
            "tenant_id": tenant_b,
        },
    }
    monkeypatch.setattr(users, "validate_session_token", lambda token: session_payloads.get(token))
    headers_a = {"Authorization": "Bearer asset-save-token-a"}
    headers_b = {"Authorization": "Bearer asset-save-token-b"}

    primary = _create_network_asset(
        headers_a,
        site_id=site_a,
        prefix="primary",
        management_ip="192.0.2.81",
    )
    conflict = _create_network_asset(
        headers_a,
        site_id=site_a,
        prefix="conflict",
        management_ip="192.0.2.83",
    )
    cross_tenant = _create_network_asset(
        headers_b,
        site_id=site_b,
        prefix="cross-tenant",
        management_ip="192.0.2.84",
    )

    primary_id = primary["id"]
    normal_hostname = _id("asset-save-updated-host")
    normal_tag = _id("asset-save-updated-tag")
    normal_ip = "192.0.2.82"
    updated = _request(
        "PUT",
        f"/api/assets/{primary_id}?run_bg_rotate=false",
        headers=headers_a,
        json={
            "asset_tag": normal_tag,
            "hostname": normal_hostname,
            "model": "Test switch revised",
            "management_ip": normal_ip,
            "department": "Network Operations",
            "notes": "ordinary staging update",
        },
    )
    assert updated.status_code == 200, updated.text
    state = _asset_state(primary_id)
    assert state["lifecycle_status"] == "staging"
    assert state["asset_tag"] == normal_tag
    assert state["hostname"] == state["device_hostname"] == normal_hostname
    assert state["asset_vendor"] == state["device_vendor"] == "Cisco"
    assert state["asset_model"] == state["device_model"] == "Test switch revised"
    assert state["asset_platform"] == state["device_platform"] == "cisco_iosxe"
    assert state["management_ip"] == state["ip_address"] == normal_ip
    assert state["asset_site_id"] == state["device_site_id"] == site_a
    assert state["device_tenant_id"] == tenant_a
    assert state["department"] == "Network Operations"

    before_conflict = _asset_state(primary_id)
    hostname_conflict = _request(
        "PUT",
        f"/api/assets/{primary_id}?run_bg_rotate=false",
        headers=headers_a,
        json={"hostname": _asset_state(conflict["id"])["hostname"], "notes": "must not persist"},
    )
    assert hostname_conflict.status_code == 409, hostname_conflict.text
    after_conflict = _asset_state(primary_id)
    assert after_conflict == before_conflict

    before_bad_rack = _asset_state(primary_id)
    bad_rack = _request(
        "PUT",
        f"/api/assets/{primary_id}?run_bg_rotate=false",
        headers=headers_a,
        json={
            "hostname": _id("must-rollback"),
            "department": "must rollback",
            "rack_id": _id("missing-rack"),
        },
    )
    assert bad_rack.status_code == 400, bad_rack.text
    assert _asset_state(primary_id) == before_bad_rack
    connection = database.get_db_connection()
    try:
        placement_count = connection.execute(
            "SELECT COUNT(*) AS count FROM rack_devices WHERE asset_id = ?",
            (primary_id,),
        ).fetchone()["count"]
    finally:
        connection.close()
    assert placement_count == 0

    before_cross_tenant = _asset_state(cross_tenant["id"])
    denied = _request(
        "PUT",
        f"/api/assets/{cross_tenant['id']}?run_bg_rotate=false",
        headers=headers_a,
        json={"hostname": _id("cross-tenant-must-not-write")},
    )
    assert denied.status_code == 403, denied.text
    assert _asset_state(cross_tenant["id"]) == before_cross_tenant

    switched_to_huawei = _request(
        "PUT",
        f"/api/assets/{primary_id}?run_bg_rotate=false",
        headers=headers_a,
        json={"vendor": "Huawei", "platform": "cisco_iosxe"},
    )
    assert switched_to_huawei.status_code == 200, switched_to_huawei.text
    huawei_state = _asset_state(primary_id)
    assert huawei_state["asset_vendor"] == huawei_state["device_vendor"] == "Huawei"
    assert huawei_state["asset_platform"] == huawei_state["device_platform"] == "huawei_vrp"

    switched_to_h3c = _request(
        "PUT",
        f"/api/assets/{primary_id}?run_bg_rotate=false",
        headers=headers_a,
        json={"vendor": "H3C", "platform": "huawei_vrp"},
    )
    assert switched_to_h3c.status_code == 200, switched_to_h3c.text
    h3c_state = _asset_state(primary_id)
    assert h3c_state["asset_vendor"] == h3c_state["device_vendor"] == "H3C"
    assert h3c_state["asset_platform"] == h3c_state["device_platform"] == "h3c_comware"
