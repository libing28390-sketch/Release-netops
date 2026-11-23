"""Regression tests for asset management remediation items."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from api import assets, users
from core.platform_utils import normalize_device_platform
from main import app


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_multivendor_platform_normalization_preserves_valid_subplatforms():
    # Valid vendor sub-platforms must not be silently overwritten to vendor defaults
    assert assets._normalize_asset_platform("Cisco", "cisco_iosxr") == "cisco_iosxr"
    assert assets._normalize_asset_platform("Cisco", "cisco_asa") == "cisco_asa"
    assert assets._normalize_asset_platform("Huawei", "huawei_smartax") == "huawei_smartax"
    assert assets._normalize_asset_platform("Huawei", "huawei_usg") == "huawei_usg"
    assert assets._normalize_asset_platform("Juniper", "juniper_srx") == "juniper_srx"
    assert assets._normalize_asset_platform("H3C", "h3c_comware") == "h3c_comware"

    # Incompatible platforms must normalize to the selected vendor's default (never silent Cisco)
    assert assets._normalize_asset_platform("Huawei", "cisco_ios") == "huawei_vrp"
    assert assets._normalize_asset_platform("H3C", "cisco_ios") == "h3c_comware"
    assert assets._normalize_asset_platform("Juniper", "cisco_ios") == "juniper_junos"
    assert assets._platform_from_vendor("Cisco") == "cisco_ios"

    # Device-level normalization stays consistent with asset-level rules
    assert normalize_device_platform("Cisco", "cisco_iosxr") == "cisco_iosxr"
    assert normalize_device_platform("Cisco", "cisco_asa") == "cisco_asa"
    assert normalize_device_platform("Huawei", "huawei_smartax") == "huawei_smartax"
    assert normalize_device_platform("Huawei", "huawei_usg") == "huawei_usg"
    assert normalize_device_platform("Juniper", "juniper_srx") == "juniper_srx"
    assert normalize_device_platform("H3C", "cisco_ios") == "h3c_comware"


def test_cmdb_assets_enforce_scope_and_sanitize_secrets_and_asset_tree_returns_role(
    isolated_db, make_user, monkeypatch
):
    conn = isolated_db["module"].get_db_connection()
    tenant_id = _id("tenant-cmdb")
    site_a = _id("site-cmdb-a")
    site_b = _id("site-cmdb-b")
    try:
        conn.execute(
            "INSERT INTO tenants (id, name, description) VALUES (?, ?, ?)",
            (tenant_id, tenant_id, "CMDB scope test"),
        )
        for site_id in (site_a, site_b):
            conn.execute(
                """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
                   VALUES (?, ?, ?, 'active', ?)""",
                (site_id, site_id.upper(), site_id, tenant_id),
            )
        conn.commit()
    finally:
        conn.close()

    soon = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    visible_srv = assets.create_asset(
        assets.AssetCreate(
            asset_type="server",
            asset_tag=_id("SRV-A"),
            hostname="cmdb-srv-visible",
            site_id=site_a,
            management_ip="192.0.2.201",
            device_role="application_server",
            status="active",
            warranty_expiry=soon,
            snmp_community="super-secret-community",
        )
    )
    hidden_srv = assets.create_asset(
        assets.AssetCreate(
            asset_type="server",
            asset_tag=_id("SRV-B"),
            hostname="cmdb-srv-hidden",
            site_id=site_b,
            management_ip="192.0.2.202",
            device_role="database_server",
            status="maintenance",
            snmp_community="hidden-secret",
        )
    )

    viewer = make_user("cmdb-scope-viewer", role="Viewer")
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET tenant_id = ? WHERE id = ?",
            (tenant_id, viewer["user_id"]),
        )
        conn.execute(
            """INSERT INTO user_resource_scopes (
                   id, user_id, resource_type, scope_type, scope_id,
                   actions_json, created_at
               ) VALUES (?, ?, 'asset', 'site', ?, ?, CURRENT_TIMESTAMP)""",
            (_id("scope"), viewer["user_id"], site_a, json.dumps(["view"])),
        )
        conn.commit()
    finally:
        conn.close()

    viewer_payload = {
        "user_id": viewer["user_id"],
        "id": viewer["user_id"],
        "username": "cmdb-scope-viewer",
        "role": "Viewer",
        "tenant_id": tenant_id,
    }
    monkeypatch.setattr(users, "validate_session_token", lambda token: viewer_payload)
    headers = {"Authorization": "Bearer cmdb-scope-token"}

    # 1. CMDB assets list enforces site scope & sanitizes snmp_community
    resp_list = _request("GET", "/api/cmdb/assets", headers=headers)
    assert resp_list.status_code == 200
    items = resp_list.json()["data"]["items"]
    ids = {item["id"] for item in items}
    assert visible_srv["id"] in ids
    assert hidden_srv["id"] not in ids
    visible_row = next(item for item in items if item["id"] == visible_srv["id"])
    assert visible_row["snmp_community"] == ""
    assert visible_row["snmp_community_set"] is True

    # 2. CMDB asset tree enforces site scope
    resp_cmdb_tree = _request("GET", "/api/cmdb/assets/tree", headers=headers)
    assert resp_cmdb_tree.status_code == 200
    cmdb_site_ids = {row["site_id"] for row in resp_cmdb_tree.json()["data"]["items"]}
    assert site_a in cmdb_site_ids
    assert site_b not in cmdb_site_ids

    # 3. /api/assets/tree includes device_role column
    resp_asset_tree = _request("GET", "/api/assets/tree", headers=headers)
    assert resp_asset_tree.status_code == 200
    tree_items = resp_asset_tree.json()["items"]
    assert any(row.get("device_role") == "application_server" for row in tree_items)

    # 4. /api/assets/summary single-pass aggregation matches scoped data
    resp_summary = _request("GET", "/api/assets/summary", headers=headers)
    assert resp_summary.status_code == 200
    summary = resp_summary.json()
    assert summary["total"] == 1
    assert summary["by_type"]["server"] == 1
    assert summary["by_type"]["network_device"] == 0
    assert summary["warranty_expiring_soon"] == 1

    # 5. /api/assets?asset_type=server&include_status_counts=true returns server status_counts
    resp_srv = _request(
        "GET",
        "/api/assets?asset_type=server&include_status_counts=true",
        headers=headers,
    )
    assert resp_srv.status_code == 200
    srv_data = resp_srv.json()
    assert srv_data["total"] == 1
    assert srv_data["status_counts"]["active"] == 1


def test_devices_server_side_lifecycle_tag_and_quick_filters(isolated_db, make_user, monkeypatch):
    admin = make_user("devices-filter-admin", role="Administrator")
    admin_payload = {
        "user_id": admin["user_id"],
        "id": admin["user_id"],
        "username": "devices-filter-admin",
        "role": "Administrator",
    }
    monkeypatch.setattr(users, "validate_session_token", lambda token: admin_payload)
    headers = {"Authorization": "Bearer devices-filter-token"}

    conn = isolated_db["module"].get_db_connection()
    tag_id = _id("tag")
    dev_prod_online = _id("dev-prod-on")
    dev_staging_offline = _id("dev-stg-off")
    try:
        conn.execute(
            """INSERT INTO tag_categories (code, label, label_zh)
               VALUES ('custom_test', 'Custom Test', '自定义测试')
               ON CONFLICT (code) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO tag_definitions (id, category, code, label, label_zh, color, is_active)
               VALUES (?, 'custom_test', ?, 'CoreTag', '核心标签', '#3b82f6', 1)""",
            (tag_id, _id("core-tag")),
        )
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, platform, status, lifecycle_status, vendor)
               VALUES (?, 'sw-prod-on', '192.0.2.11', 'h3c_comware', 'online', 'production', 'H3C')""",
            (dev_prod_online,),
        )
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, platform, status, lifecycle_status, vendor)
               VALUES (?, 'sw-stg-off', '192.0.2.12', 'huawei_vrp', 'offline', 'staging', 'Huawei')""",
            (dev_staging_offline,),
        )
        conn.execute(
            """INSERT INTO tag_assignments (resource_type, resource_id, tag_id)
               VALUES ('device', ?, ?)""",
            (dev_prod_online, tag_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Lifecycle filter
    r_life = _request(
        "GET",
        "/api/devices?asset_type=network_device&lifecycle_status=production&page=1&page_size=10",
        headers=headers,
    )
    assert r_life.status_code == 200
    body_life = r_life.json()
    assert body_life["total"] == 1
    assert [d["id"] for d in body_life["items"]] == [dev_prod_online]

    # Tag filter
    r_tag = _request(
        "GET",
        f"/api/devices?asset_type=network_device&tag_ids={tag_id}&page=1&page_size=10",
        headers=headers,
    )
    assert r_tag.status_code == 200
    body_tag = r_tag.json()
    assert body_tag["total"] == 1
    assert [d["id"] for d in body_tag["items"]] == [dev_prod_online]

    # Quick filter: offline (items filtered, but status_counts still retains full set)
    r_off = _request(
        "GET",
        "/api/devices?asset_type=network_device&quick_filter=offline&page=1&page_size=10",
        headers=headers,
    )
    assert r_off.status_code == 200
    body_off = r_off.json()
    assert body_off["total"] == 1
    assert [d["id"] for d in body_off["items"]] == [dev_staging_offline]
    assert body_off["status_counts"].get("online") == 1
    assert body_off["status_counts"].get("offline") == 1
