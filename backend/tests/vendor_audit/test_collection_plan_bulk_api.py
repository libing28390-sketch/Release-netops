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
            collection_policy_json TEXT DEFAULT '{}'
        );
        CREATE TABLE sites (
            id TEXT PRIMARY KEY,
            site_code TEXT NOT NULL,
            site_name TEXT NOT NULL
        );
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
    monkeypatch.setattr(database, "get_db_connection", lambda: connection)
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
    policy: str = "{}",
) -> None:
    connection.execute(
        "INSERT INTO devices "
        "(id, hostname, ip_address, role, site, site_id, platform, status, device_category, tenant_id, collection_policy_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        "site-a": 3,
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
        "Switch": 1,
    }

    preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={
            "operation": "apply",
            "template_id": "basic",
            "filters": {"site": "site-a", "category": "Switch"},
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["matched_count"] == 1
    assert preview.json()["data"]["overridden_count"] == 1
    assert [row["device_id"] for row in preview.json()["data"]["sample"]] == ["sw-1"]

    # Category matching is case-sensitive exact matching; fallback labels are
    # based on legacy role, with a blank category treated as missing.
    lowercase = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={
            "operation": "reset",
            "filters": {"site": "site-a", "category": "switch"},
        },
    )
    assert lowercase.status_code == 200, lowercase.text
    assert lowercase.json()["data"]["matched_count"] == 0
    legacy = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "reset", "filters": {"category": "Server"}},
    )
    assert legacy.status_code == 200, legacy.text
    assert [row["device_id"] for row in legacy.json()["data"]["sample"]] == ["legacy-server"]


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

    preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "reset", "filters": {"site": "cmdb-site-uuid"}},
    )
    assert preview.status_code == 200, preview.text
    assert [row["device_id"] for row in preview.json()["data"]["sample"]] == [
        "legacy-site-id-device"
    ]


def test_bulk_requires_a_filter_and_operator_to_preview(bulk_api_context):
    client, _connection, user = bulk_api_context
    missing_filter = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "reset", "filters": {}},
    )
    assert missing_filter.status_code == 400

    user["role"] = "Viewer"
    denied_preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "reset", "filters": {"site": "site-a"}},
    )
    assert denied_preview.status_code == 403
    assert client.get("/api/collection-plans/bulk-options", headers=_headers()).status_code == 200


def test_bulk_options_and_preview_are_limited_to_authenticated_tenant(bulk_api_context):
    client, connection, _user = bulk_api_context
    _seed(connection, "tenant-a-device", tenant_id="tenant-default", site="WH")
    _seed(connection, "tenant-b-device", tenant_id="tenant-other", site="WH")

    options = client.get("/api/collection-plans/bulk-options", headers=_headers())
    assert options.status_code == 200, options.text
    assert {item["value"] for item in options.json()["data"]["sites"]} == {"WH"}
    preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "apply", "template_id": "basic", "filters": {"site": "WH"}},
    )
    assert preview.status_code == 200, preview.text
    assert [row["device_id"] for row in preview.json()["data"]["sample"]] == ["tenant-a-device"]


def test_tenantless_administrator_retains_global_bulk_access(bulk_api_context):
    client, connection, user = bulk_api_context
    user["role"] = "Administrator"
    user["tenant_id"] = ""
    _seed(connection, "tenant-a-device", tenant_id="tenant-default", site="WH")
    _seed(connection, "tenant-b-device", tenant_id="tenant-other", site="WH")

    preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "apply", "template_id": "basic", "filters": {"site": "WH"}},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["matched_count"] == 2


def test_non_admin_without_tenant_is_denied(bulk_api_context):
    client, _connection, user = bulk_api_context
    user["tenant_id"] = ""
    preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "reset", "filters": {"site": "site-a"}},
    )
    assert preview.status_code == 403
    assert preview.json()["detail"] == "Authenticated user is not assigned to a tenant"


def test_site_scoped_operator_cannot_preview_outside_granted_sites(bulk_api_context):
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

    blocked = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "apply", "template_id": "basic", "filters": {"site": "HQ"}},
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["data"]["matched_count"] == 0
    assert blocked.json()["data"]["sample"] == []


def test_bulk_apply_and_reset_clear_device_overrides(bulk_api_context, monkeypatch):
    client, connection, _role = bulk_api_context
    audit_events: list[dict] = []
    monkeypatch.setattr(collection_plans_api, "log_audit_event", lambda **event: audit_events.append(event))
    _seed(
        connection,
        "online-device",
        policy='{"template":"firewall","collectors":{"lldp":false,"future":true}}',
    )
    _seed(
        connection,
        "offline-device",
        status="offline",
        policy='{"collectors":{"mac_table":true}}',
    )
    filters = {"site": "site-a"}
    preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "apply", "template_id": "basic", "filters": filters},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["matched_count"] == 2
    assert preview.json()["data"]["overridden_count"] == 2
    assert len(preview.json()["data"]["sample"]) == 2

    applied = client.post(
        "/api/collection-plans/bulk-apply",
        headers=_headers(),
        json={
            "operation": "apply",
            "template_id": "basic",
            "filters": filters,
            "snapshot_token": preview.json()["data"]["snapshot_token"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["data"]["affected_count"] == 2
    assert audit_events[0]["event_type"] == "COLLECTION_PLAN_BULK_UPDATED"
    assert audit_events[0]["actor_username"] == "bulk-test"
    assert audit_events[0]["details"]["affected_count"] == 2
    assert "snapshot_token" not in audit_events[0]["details"]
    policies = connection.execute(
        "SELECT id, collection_policy_json FROM devices ORDER BY id"
    ).fetchall()
    assert {row["id"]: json.loads(row["collection_policy_json"]) for row in policies} == {
        "offline-device": {"template": "basic", "collectors": {}},
        "online-device": {"template": "basic", "collectors": {}},
    }

    connection.execute(
        "UPDATE devices SET collection_policy_json = ? WHERE id = ?",
        ('{"template":"wireless","collectors":{"lldp":false}}', "online-device"),
    )
    reset_preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "reset", "filters": {"site": "site-a"}},
    )
    assert reset_preview.status_code == 200, reset_preview.text
    reset = client.post(
        "/api/collection-plans/bulk-apply",
        headers=_headers(),
        json={
            "operation": "reset",
            "filters": {"site": "site-a"},
            "snapshot_token": reset_preview.json()["data"]["snapshot_token"],
        },
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["data"]["affected_count"] == 2
    assert len(audit_events) == 2
    assert audit_events[1]["details"]["template_id"] == "role_default"
    assert all(
        json.loads(row["collection_policy_json"]) == {"template": "role_default", "collectors": {}}
        for row in connection.execute("SELECT collection_policy_json FROM devices").fetchall()
    )


def test_bulk_zero_match_and_invalid_template_do_not_write(bulk_api_context):
    client, connection, _role = bulk_api_context
    _seed(connection, "kept", policy='{"collectors":{"lldp":false}}')
    before = connection.execute(
        "SELECT collection_policy_json FROM devices WHERE id = ?", ("kept",)
    ).fetchone()[0]

    zero_preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "apply", "template_id": "basic", "filters": {"site": "absent"}},
    )
    assert zero_preview.status_code == 200, zero_preview.text
    assert zero_preview.json()["data"]["matched_count"] == 0
    zero_apply = client.post(
        "/api/collection-plans/bulk-apply",
        headers=_headers(),
        json={
            "operation": "apply",
            "template_id": "basic",
            "filters": {"site": "absent"},
            "snapshot_token": zero_preview.json()["data"]["snapshot_token"],
        },
    )
    assert zero_apply.status_code == 200, zero_apply.text
    assert zero_apply.json()["data"]["affected_count"] == 0

    invalid = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "apply", "template_id": "custom", "filters": {"site": "site-a"}},
    )
    assert invalid.status_code == 400
    after = connection.execute(
        "SELECT collection_policy_json FROM devices WHERE id = ?", ("kept",)
    ).fetchone()[0]
    assert after == before


def test_bulk_apply_rejects_stale_snapshot_without_writing(bulk_api_context):
    client, connection, _role = bulk_api_context
    _seed(connection, "stale-target", policy='{"collectors":{"lldp":false}}')
    preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "apply", "template_id": "basic", "filters": {"site": "site-a"}},
    )
    assert preview.status_code == 200, preview.text
    connection.execute(
        "UPDATE devices SET collection_policy_json = ? WHERE id = ?",
        ('{"collectors":{"lldp":true}}', "stale-target"),
    )
    connection.commit()
    stale = client.post(
        "/api/collection-plans/bulk-apply",
        headers=_headers(),
        json={
            "operation": "apply",
            "template_id": "basic",
            "filters": {"site": "site-a"},
            "snapshot_token": preview.json()["data"]["snapshot_token"],
        },
    )
    assert stale.status_code == 409
    current = connection.execute(
        "SELECT collection_policy_json FROM devices WHERE id = ?", ("stale-target",)
    ).fetchone()[0]
    assert current == '{"collectors":{"lldp":true}}'


def test_bulk_snapshot_is_bound_to_operation_and_template(bulk_api_context):
    client, connection, _role = bulk_api_context
    _seed(connection, "bound-target", policy='{"collectors":{"lldp":false}}')
    connection.commit()
    preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "apply", "template_id": "basic", "filters": {"site": "site-a"}},
    )
    assert preview.status_code == 200, preview.text
    stale = client.post(
        "/api/collection-plans/bulk-apply",
        headers=_headers(),
        json={
            "operation": "apply",
            "template_id": "firewall",
            "filters": {"site": "site-a"},
            "snapshot_token": preview.json()["data"]["snapshot_token"],
        },
    )
    assert stale.status_code == 409
    current = connection.execute(
        "SELECT collection_policy_json FROM devices WHERE id = ?", ("bound-target",)
    ).fetchone()[0]
    assert current == '{"collectors":{"lldp":false}}'


def test_bulk_apply_rolls_back_all_rows_after_database_failure(bulk_api_context):
    client, connection, _role = bulk_api_context
    _seed(connection, "rollback-a", policy='{"collectors":{"lldp":false}}')
    _seed(connection, "rollback-b", policy='{"collectors":{"mac_table":true}}')
    connection.executescript(
        """
        CREATE FUNCTION reject_second_bulk_update() RETURNS trigger AS $$
        BEGIN
            IF NEW.id = 'rollback-b' THEN
                RAISE EXCEPTION 'synthetic collection policy failure';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER reject_second_bulk_update
        BEFORE UPDATE OF collection_policy_json ON devices
        FOR EACH ROW EXECUTE FUNCTION reject_second_bulk_update();
        """
    )
    preview = client.post(
        "/api/collection-plans/bulk-preview",
        headers=_headers(),
        json={"operation": "apply", "template_id": "basic", "filters": {"site": "site-a"}},
    )
    assert preview.status_code == 200, preview.text
    response = client.post(
        "/api/collection-plans/bulk-apply",
        headers=_headers(),
        json={
            "operation": "apply",
            "template_id": "basic",
            "filters": {"site": "site-a"},
            "snapshot_token": preview.json()["data"]["snapshot_token"],
        },
    )
    assert response.status_code == 500
    policies = {
        row["id"]: row["collection_policy_json"]
        for row in connection.execute(
            "SELECT id, collection_policy_json FROM devices ORDER BY id"
        ).fetchall()
    }
    assert policies == {
        "rollback-a": '{"collectors":{"lldp":false}}',
        "rollback-b": '{"collectors":{"mac_table":true}}',
    }


def test_lookup_collection_plan_by_normalized_ipv4_and_ipv6(bulk_api_context):
    client, connection, _user = bulk_api_context
    _seed(connection, "ipv4-switch", ip_address="192.0.2.10", policy='{"collectors":{"lldp":true}}')
    _seed(connection, "ipv6-switch", ip_address="2001:db8::1", policy='{"template":"firewall"}')
    _seed(connection, "legacy-invalid-ip", ip_address="not an IP")

    ipv4 = client.get(
        "/api/collection-plans/devices/by-ip",
        params={"ip": " 192.0.2.10 "},
        headers=_headers(),
    )
    assert ipv4.status_code == 200, ipv4.text
    assert ipv4.json()["data"]["device"]["id"] == "ipv4-switch"
    assert ipv4.json()["data"]["device"]["category"] == "Switch"
    assert ipv4.json()["data"]["device"]["site"] == "site-a"
    assert ipv4.json()["data"]["device"]["site_id"] == "site-id-site-a"
    assert ipv4.json()["data"]["plan"]["overrides"]["lldp"] is True

    ipv6 = client.get(
        "/api/collection-plans/devices/by-ip",
        params={"ip": "2001:0DB8:0:0:0:0:0:1"},
        headers=_headers(),
    )
    assert ipv6.status_code == 200, ipv6.text
    assert ipv6.json()["data"]["device"]["id"] == "ipv6-switch"
    assert ipv6.json()["data"]["plan"]["template_id"] == "firewall"


def test_lookup_collection_plan_by_ip_falls_back_for_alternate_ipv6_text(bulk_api_context):
    client, connection, _user = bulk_api_context
    _seed(connection, "alternate-ipv6", ip_address="2001:db8:0:0:1::1")
    _seed(connection, "legacy-invalid-ip", ip_address="invalid legacy address")

    response = client.get(
        "/api/collection-plans/devices/by-ip",
        params={"ip": "2001:db8::1:0:0:1"},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["device"]["id"] == "alternate-ipv6"


def test_lookup_collection_plan_by_ip_validates_input_and_hides_misses(bulk_api_context):
    client, _connection, _user = bulk_api_context
    invalid = client.get(
        "/api/collection-plans/devices/by-ip",
        params={"ip": "not-an-ip"},
        headers=_headers(),
    )
    assert invalid.status_code == 422

    missing = client.get(
        "/api/collection-plans/devices/by-ip",
        params={"ip": "198.51.100.250"},
        headers=_headers(),
    )
    assert missing.status_code == 404


def test_lookup_collection_plan_by_ip_obeys_tenant_and_site_scopes(bulk_api_context):
    client, connection, user = bulk_api_context
    _seed(connection, "own-tenant", ip_address="192.0.2.11", site="allowed", site_id="site-allowed")
    _seed(
        connection,
        "foreign-tenant",
        ip_address="192.0.2.12",
        site="allowed",
        site_id="site-allowed",
        tenant_id="tenant-other",
    )
    _seed(connection, "allowed-site", ip_address="192.0.2.13", site="allowed", site_id="site-allowed")
    _seed(connection, "blocked-site", ip_address="192.0.2.14", site="blocked", site_id="site-blocked")
    connection.execute(
        "INSERT INTO user_resource_scopes (user_id, resource_type, scope_type, scope_id, actions_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (user["id"], "asset", "site", "site-allowed", '["view"]'),
    )
    connection.commit()

    own_tenant = client.get(
        "/api/collection-plans/devices/by-ip",
        params={"ip": "192.0.2.11"},
        headers=_headers(),
    )
    assert own_tenant.status_code == 200, own_tenant.text

    for ip in ("192.0.2.12", "192.0.2.14"):
        denied = client.get(
            "/api/collection-plans/devices/by-ip",
            params={"ip": ip},
            headers=_headers(),
        )
        assert denied.status_code == 404

    allowed_site = client.get(
        "/api/collection-plans/devices/by-ip",
        params={"ip": "192.0.2.13"},
        headers=_headers(),
    )
    assert allowed_site.status_code == 200, allowed_site.text


def test_lookup_collection_plan_by_ip_reports_ambiguous_visible_matches(bulk_api_context):
    client, connection, _user = bulk_api_context
    _seed(connection, "duplicate-a", ip_address="203.0.113.20")
    _seed(connection, "duplicate-b", ip_address="203.0.113.20")

    response = client.get(
        "/api/collection-plans/devices/by-ip",
        params={"ip": "203.0.113.20"},
        headers=_headers(),
    )
    assert response.status_code == 409


def test_lookup_collection_plan_by_ip_reports_equivalent_ipv6_text_as_ambiguous(bulk_api_context):
    client, connection, _user = bulk_api_context
    _seed(connection, "compressed-ipv6", ip_address="2001:db8::1")
    _seed(connection, "expanded-ipv6", ip_address="2001:0db8:0000:0000:0000:0000:0000:0001")

    response = client.get(
        "/api/collection-plans/devices/by-ip",
        params={"ip": "2001:db8::1"},
        headers=_headers(),
    )
    assert response.status_code == 409


def test_device_collection_plan_id_routes_obey_tenant_and_site_scope(bulk_api_context):
    client, connection, user = bulk_api_context
    _seed(connection, "own-site-device", site_id="site-allowed")
    _seed(
        connection,
        "foreign-tenant-same-site",
        site_id="site-allowed",
        tenant_id="tenant-other",
        policy='{"template":"firewall"}',
    )
    _seed(connection, "blocked-site-device", site_id="site-blocked", policy='{"template":"router"}')
    connection.execute(
        "INSERT INTO user_resource_scopes (user_id, resource_type, scope_type, scope_id, actions_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (user["id"], "asset", "site", "site-allowed", '["view", "update"]'),
    )
    connection.commit()

    listed = client.get("/api/collection-plans/devices", headers=_headers())
    assert listed.status_code == 200, listed.text
    assert {item["device"]["id"] for item in listed.json()["data"]} == {"own-site-device"}

    visible = client.get("/api/collection-plans/devices/own-site-device", headers=_headers())
    assert visible.status_code == 200, visible.text
    for device_id in ("foreign-tenant-same-site", "blocked-site-device"):
        assert client.get(
            f"/api/collection-plans/devices/{device_id}", headers=_headers()
        ).status_code == 404
        assert client.put(
            f"/api/collection-plans/devices/{device_id}",
            headers=_headers(),
            json={"template": "firewall"},
        ).status_code == 404
        assert client.delete(
            f"/api/collection-plans/devices/{device_id}", headers=_headers()
        ).status_code == 404

    preserved = {
        row["id"]: row["collection_policy_json"]
        for row in connection.execute(
            "SELECT id, collection_policy_json FROM devices "
            "WHERE id IN (?, ?)",
            ("foreign-tenant-same-site", "blocked-site-device"),
        ).fetchall()
    }
    assert preserved == {
        "foreign-tenant-same-site": '{"template":"firewall"}',
        "blocked-site-device": '{"template":"router"}',
    }
