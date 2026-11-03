from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import collection_plans as collection_plans_api
from api import users
import database
from backend.tests.pg_test_utils import postgresql_test_driver
from main import app


@pytest.fixture()
def bulk_api_context(monkeypatch):
    """Use a disposable blank PostgreSQL database, never the configured DB."""
    connection = postgresql_test_driver.connect()
    connection.row_factory = postgresql_test_driver.Row
    connection.executescript(
        """
        CREATE TABLE devices (
            id TEXT PRIMARY KEY,
            hostname TEXT,
            ip_address TEXT,
            role TEXT,
            site TEXT,
            platform TEXT,
            status TEXT,
            device_category TEXT,
            tenant_id TEXT,
            site_id TEXT,
            asset_id TEXT,
            device_group_id TEXT,
            collection_policy_json TEXT DEFAULT '{}'
        );
        CREATE TABLE sites (
            id TEXT PRIMARY KEY,
            site_code TEXT NOT NULL,
            site_name TEXT NOT NULL
        );
        CREATE TABLE physical_assets (id TEXT PRIMARY KEY, site_id TEXT);
        CREATE TABLE users (id TEXT PRIMARY KEY, role_profile TEXT);
        CREATE TABLE user_resource_scopes (
            user_id TEXT,
            resource_type TEXT,
            scope_type TEXT,
            scope_id TEXT,
            actions_json TEXT
        );
        """
    )
    user = {"id": "bulk-user", "username": "bulk-test", "role": "Operator", "tenant_id": "tenant-default"}
    connection.execute("INSERT INTO users (id, role_profile) VALUES (?, ?)", (user["id"], ""))
    connection.commit()
    monkeypatch.setattr(database.core, "get_db_connection", lambda: connection)
    monkeypatch.setattr(collection_plans_api, "get_db_connection", lambda: connection)
    monkeypatch.setattr(
        users,
        "validate_session_token",
        lambda _token: dict(user),
    )
    monkeypatch.setattr(collection_plans_api, "log_audit_event", lambda **_event: None)
    yield TestClient(app), connection, user
    connection.close()


def _seed(
    connection,
    device_id: str,
    *,
    hostname: str | None = None,
    ip_address: str = "192.0.2.1",
    role: str = "Switch",
    site: str = "site-a",
    platform: str = "cisco_ios",
    status: str = "online",
    category: str | None = "Switch",
    tenant_id: str = "tenant-default",
    site_id: str | None = None,
    device_group_id: str | None = None,
    policy: str = "{}",
) -> None:
    connection.execute(
        "INSERT INTO devices "
        "(id, hostname, ip_address, role, site, site_id, platform, status, device_category, tenant_id, device_group_id, collection_policy_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            device_id,
            hostname or device_id,
            ip_address,
            role,
            site,
            site_id or f"site-id-{site}",
            platform,
            status,
            category,
            tenant_id,
            device_group_id,
            policy,
        ),
    )


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer synthetic-bulk-token"}


def test_bulk_options_and_exact_and_category_fallback(bulk_api_context):
    client, connection, _role = bulk_api_context
    _seed(connection, "sw-1", category="Switch", policy='{"collectors":{"lldp":false}}')
    _seed(connection, "rt-1", role="Router", category="Router")
    _seed(connection, "legacy-server", role="Server", category=None, platform="linux")
    _seed(connection, "legacy-network", role="Access", category="", site="site-b")
    _seed(connection, "foreign-tenant", tenant_id="tenant-other", role="Switch", category="Switch")
    connection.execute(
        "INSERT INTO sites (id, site_code, site_name) VALUES (?, ?, ?)",
        ("site-id-site-a", "DC-A", "Datacenter A"),
    )
    connection.execute(
        "INSERT INTO sites (id, site_code, site_name) VALUES (?, ?, ?)",
        ("site-id-site-b", "DC-B", "Datacenter B"),
    )
    connection.commit()

    options = client.get("/api/collection-plans/bulk-options", headers=_headers())
    assert options.status_code == 200, options.text
    option_data = options.json()["data"]
    assert {item["value"]: item["count"] for item in option_data["sites"]} == {
        "site-a": 4,
        "site-b": 1,
    }
    assert {item["value"]: item["label"] for item in option_data["sites"]} == {
        "site-a": "Datacenter A",
        "site-b": "Datacenter B",
    }
    assert {item["value"]: item["count"] for item in option_data["categories"]} == {
        "Network": 1,
        "Router": 1,
        "Server": 1,
        "Switch": 2,
    }


def test_bulk_site_options_fall_back_to_site_id_value_and_resolve_friendly_label(bulk_api_context):
    client, connection, _user = bulk_api_context
    _seed(
        connection,
        "legacy-site-id-device",
        site="",
        site_id="cmdb-site-uuid",
    )
    _seed(
        connection,
        "site-without-cmdb-label",
        site="",
        site_id="550e8400-e29b-41d4-a716-446655440000",
    )
    connection.execute(
        "INSERT INTO sites (id, site_code, site_name) VALUES (?, ?, ?)",
        ("cmdb-site-uuid", "REMOTE-DC", "Remote data center"),
    )
    connection.commit()

    options = client.get("/api/collection-plans/bulk-options", headers=_headers())
    assert options.status_code == 200, options.text
    site_option = next(
        item for item in options.json()["data"]["sites"] if item["value"] == "cmdb-site-uuid"
    )
    assert site_option["label"] == "Remote data center"
    orphan_option = next(
        item
        for item in options.json()["data"]["sites"]
        if item["value"] == "550e8400-e29b-41d4-a716-446655440000"
    )
    assert orphan_option["label"] == "未分配站点"


def test_bulk_options_ignore_legacy_tenant_ids_in_single_org(bulk_api_context):
    client, connection, _user = bulk_api_context
    _seed(connection, "tenant-a-device", tenant_id="tenant-default", site="WH")
    _seed(connection, "tenant-b-device", tenant_id="tenant-other", site="WH")

    options = client.get("/api/collection-plans/bulk-options", headers=_headers())
    assert options.status_code == 200, options.text
    assert {item["value"] for item in options.json()["data"]["sites"]} == {"WH"}


def test_tenantless_administrator_retains_global_bulk_access(bulk_api_context):
    client, connection, user = bulk_api_context
    user["role"] = "Administrator"
    user["tenant_id"] = ""
    _seed(connection, "tenant-a-device", tenant_id="tenant-default", site="WH")
    _seed(connection, "tenant-b-device", tenant_id="tenant-other", site="WH")
    options = client.get("/api/collection-plans/bulk-options", headers=_headers())
    assert options.status_code == 200, options.text


def test_non_admin_without_tenant_keeps_legacy_role_access_in_single_org(bulk_api_context):
    client, connection, user = bulk_api_context
    user["tenant_id"] = ""
    _seed(connection, "tenantless-device", tenant_id="tenant-other", site="site-a")
    options = client.get("/api/collection-plans/bulk-options", headers=_headers())
    assert options.status_code == 200, options.text


def test_site_scoped_operator_options_hide_ungranted_sites(bulk_api_context):
    client, connection, user = bulk_api_context
    _seed(connection, "allowed-site-device", site="WH-DC-02")
    _seed(connection, "blocked-site-device", site="HQ")
    connection.execute(
        "INSERT INTO user_resource_scopes (user_id, resource_type, scope_type, scope_id, actions_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (user["id"], "asset", "site", "site-id-WH-DC-02", '["view", "update"]'),
    )
    connection.commit()

    options = client.get("/api/collection-plans/bulk-options", headers=_headers())
    assert options.status_code == 200, options.text
    assert {item["value"] for item in options.json()["data"]["sites"]} == {"WH-DC-02"}


def test_device_group_only_scope_filters_collection_plan_options(bulk_api_context):
    client, connection, user = bulk_api_context
    user["scope_mode"] = "restricted"
    _seed(connection, "group-a-device", site="East", tenant_id="tenant-other", device_group_id="group-a")
    _seed(connection, "group-b-device", site="West", device_group_id="group-b")
    connection.execute(
        "INSERT INTO user_resource_scopes (user_id, resource_type, scope_type, scope_id, actions_json) "
        "VALUES (?, 'asset', 'device_group', 'group-a', ?)",
        (user["id"], '["view", "update"]'),
    )
    connection.commit()

    options = client.get("/api/collection-plans/bulk-options", headers=_headers())
    assert options.status_code == 200, options.text
    assert {item["value"] for item in options.json()["data"]["sites"]} == {"East"}


def test_site_and_device_group_grants_form_a_union(bulk_api_context):
    client, connection, user = bulk_api_context
    user["scope_mode"] = "restricted"
    _seed(connection, "group-a-device", site="East", device_group_id="group-a")
    _seed(connection, "site-only-device", site="West", device_group_id="group-b")
    _seed(connection, "outside-device", site="South", device_group_id="group-c")
    connection.executemany(
        "INSERT INTO user_resource_scopes (user_id, resource_type, scope_type, scope_id, actions_json) "
        "VALUES (?, 'asset', ?, ?, ?)",
        [
            (user["id"], "site", "site-id-West", '["view", "update"]'),
            (user["id"], "device_group", "group-a", '["view", "update"]'),
        ],
    )
    connection.commit()

    options = client.get("/api/collection-plans/bulk-options", headers=_headers())
    assert options.status_code == 200, options.text
    assert {item["value"] for item in options.json()["data"]["sites"]} == {"East", "West"}


def test_restricted_collection_scope_without_grants_fails_closed(bulk_api_context):
    client, connection, user = bulk_api_context
    user["scope_mode"] = "restricted"
    _seed(connection, "invisible-device", site="East", device_group_id="group-a")

    options = client.get("/api/collection-plans/bulk-options", headers=_headers())
    assert options.status_code == 403


@pytest.mark.parametrize("method,path", [
    ("GET", "/catalog"),
    ("GET", "/templates"), ("POST", "/templates"),
    ("PUT", "/templates/basic"), ("DELETE", "/templates/basic"),
    ("GET", "/operation-catalog"),
    ("POST", "/bulk-preview"), ("POST", "/bulk-apply"),
    ("GET", "/devices"), ("GET", "/devices/by-ip?ip=192.0.2.1"),
    ("GET", "/devices/retired-policy-device"),
    ("PUT", "/devices/retired-policy-device"),
    ("DELETE", "/devices/retired-policy-device"),
])
def test_retired_nsot_policy_routes_are_unavailable_and_preserve_device_policy(
    bulk_api_context, method, path,
):
    client, connection, _user = bulk_api_context
    policy = '{"collectors":{"arp":true}}'
    _seed(connection, "retired-policy-device", policy=policy)
    connection.commit()
    response = client.request(
        method, "/api/collection-plans" + path,
        headers=_headers(), json={"operation": "reset", "filters": {"site": "site-a"}},
    )
    # An unregistered API is 404; the optional root static-file mount rejects
    # non-GET methods with 405 before its file lookup. Neither may dispatch
    # the retired policy handlers, regardless of frontend build presence.
    assert [route.path for route in collection_plans_api.router.routes] == [
        "/collection-plans/bulk-options",
    ]
    assert response.status_code in {404, 405}, response.text
    stored = connection.execute(
        "SELECT collection_policy_json FROM devices WHERE id = ?", ("retired-policy-device",),
    ).fetchone()
    assert stored[0] == policy
