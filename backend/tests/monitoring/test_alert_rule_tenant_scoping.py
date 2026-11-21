from __future__ import annotations

import json
import uuid

import pytest

from database import get_db_connection
from database.migrations.m0257_tenant_scoped_alert_rules import upgrade as upgrade_tenant_rules
from services import alert_rule_service


def _payload(name: str, **overrides) -> dict:
    payload = {
        "name": name,
        "metric_type": "interface_down",
        "scope_type": "global",
        "notification_channels": ["email"],
        "notification_group_names": ["noc"],
        "skip_approval_verification": True,
    }
    payload.update(overrides)
    return payload


def _insert_active_user(connection, tenant_id: str, group_name: str) -> None:
    connection.execute(
        """
        INSERT INTO users (id, username, password, role, status, created_at, group_name, tenant_id)
        VALUES (?, ?, 'x', 'Operator', 'active', CURRENT_TIMESTAMP, ?, ?)
        """,
        (str(uuid.uuid4()), f"user-{uuid.uuid4().hex[:8]}", group_name, tenant_id),
    )


def test_alert_rule_service_supports_partitions_but_api_is_organization_wide(isolated_db):
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-a', 'Tenant A') ON CONFLICT DO NOTHING")
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-b', 'Tenant B') ON CONFLICT DO NOTHING")
        _insert_active_user(conn, "tenant-a", "noc")
        _insert_active_user(conn, "tenant-b", "noc")
        conn.commit()
    finally:
        conn.close()

    tenant_a_rule = alert_rule_service.create_rule(_payload("A rule"), tenant_id="tenant-a")
    tenant_b_rule = alert_rule_service.create_rule(_payload("B rule"), tenant_id="tenant-b")

    assert {row["id"] for row in alert_rule_service.list_rules("tenant-a")} == {tenant_a_rule["id"]}
    assert {row["id"] for row in alert_rule_service.list_rules("tenant-b")} == {tenant_b_rule["id"]}
    assert alert_rule_service.get_rule(tenant_b_rule["id"], "tenant-a") is None
    assert alert_rule_service.list_notification_groups("tenant-a") == [{"name": "noc", "member_count": 1}]
    from api.alerts import read_alert_rule_notification_groups, read_alert_rules

    api_rules = read_alert_rules(
        search='', enabled='all', metric_type='all', category='all',
        page=1, page_size=20, user={"tenant_id": "tenant-a"},
    )
    api_groups = read_alert_rule_notification_groups(user={"tenant_id": "tenant-a"})
    from api.alerts import read_alert_rule_scope_catalog
    api_scope_catalog = read_alert_rule_scope_catalog(user={"tenant_id": "tenant-a"})
    assert {tenant_a_rule["id"], tenant_b_rule["id"]} <= {row["id"] for row in api_rules["items"]}
    assert {row["name"]: row["member_count"] for row in api_groups["items"]}["noc"] == 2
    assert api_scope_catalog == {
        'sites': [], 'roles': [], 'categories': [], 'platforms': [],
        'devices': [], 'device_total': 0, 'missing_device_ids': [],
    }
    tenant_a_supported = alert_rule_service.list_rules_paginated(tenant_id="tenant-a")["supported_metric_types"]
    default_supported = alert_rule_service.list_rules_paginated(tenant_id="tenant-default")["supported_metric_types"]
    assert not any(metric.startswith("host_") for metric in tenant_a_supported)
    assert "host_cpu" in default_supported
    history = alert_rule_service.list_rule_history(tenant_id="tenant-a")
    assert history and history[0]["tenant_id"] == "tenant-a"
    assert history[0]["snapshot"]["tenant_id"] == "tenant-a"


def test_server_metric_is_rejected_with_supported_metric_types(isolated_db):
    with pytest.raises(alert_rule_service.UnsupportedMetricTypeError) as exc_info:
        alert_rule_service.create_rule(
            _payload("Unsupported", metric_type="srv_cpu_util", notification_group_names=[]),
            tenant_id="tenant-default",
        )
    assert "srv_cpu_util" not in exc_info.value.supported_metric_types
    assert "interface_down" in exc_info.value.supported_metric_types


def test_api_batch_toggle_cannot_reenable_unsupported_legacy_rule(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO alert_rules (id, tenant_id, name, metric_type, enabled, created_at, updated_at)
            VALUES ('legacy-srv-rule', 'tenant-default', 'Legacy server rule', 'srv_cpu_util', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        conn.commit()
    finally:
        conn.close()

    from fastapi import HTTPException
    from api import alerts

    monkeypatch.setattr(alerts, '_verify_alert_rule_approval', lambda *_args, **_kwargs: None)
    with pytest.raises(HTTPException) as exc_info:
        alerts.batch_toggle_alert_rules(
            {'rule_ids': ['legacy-srv-rule'], 'enabled': True},
            user={'tenant_id': 'tenant-default', 'username': 'admin', 'role': 'Operator'},
        )
    assert exc_info.value.status_code == 400

    conn = get_db_connection()
    try:
        enabled = conn.execute("SELECT enabled FROM alert_rules WHERE id = 'legacy-srv-rule'").fetchone()['enabled']
        assert not bool(enabled)
    finally:
        conn.close()


def test_host_rule_is_global_workspace_only(isolated_db):
    with pytest.raises(ValueError, match="global scope"):
        alert_rule_service.create_rule(
            _payload("Host", metric_type="host_cpu", scope_type="device", notification_group_names=[]),
            tenant_id="tenant-default",
        )


def test_network_rule_requires_explicit_webhook_or_email(isolated_db):
    with pytest.raises(ValueError, match="reserved for system host alerts"):
        alert_rule_service.create_rule(
            _payload("Personal preference network rule", notification_channels=["workspace"], notification_group_names=[]),
            tenant_id="tenant-default",
        )


def test_rule_service_accepts_scheduled_job_asset_scope_shapes(isolated_db):
    tag_value = json.dumps({
        'version': 2,
        'expression': {'operator': 'and', 'negated': False, 'tag_ids': ['tag-network'], 'groups': []},
    })
    rules = [
        alert_rule_service.create_rule(
            _payload('Composite scope', scope_type='composite', scope_value=json.dumps({'site': 'HQ', 'role': 'core'}), scope_match_mode='contains', notification_group_names=[]),
            tenant_id='tenant-default',
        ),
        alert_rule_service.create_rule(
            _payload('IP scope', scope_type='ip', scope_value='192.0.2.1, 192.0.2.2', notification_group_names=[]),
            tenant_id='tenant-default',
        ),
        alert_rule_service.create_rule(
            _payload('Tag scope', scope_type='tag', scope_value=tag_value, notification_group_names=[]),
            tenant_id='tenant-default',
        ),
    ]
    assert [rule['scope_type'] for rule in rules] == ['composite', 'ip', 'tag']


@pytest.mark.parametrize(
    ('scope_type', 'scope_value'),
    [('composite', '{}'), ('tag', '{"expression":{"operator":"and","tag_ids":[],"groups":[]}}')],
)
def test_rule_service_rejects_empty_structured_asset_scope(isolated_db, scope_type, scope_value):
    with pytest.raises(ValueError, match='scope'):
        alert_rule_service.create_rule(
            _payload(f'Empty {scope_type} scope', scope_type=scope_type, scope_value=scope_value, notification_group_names=[]),
            tenant_id='tenant-default',
        )


def test_scope_catalog_service_selector_and_api_are_organization_wide(isolated_db):
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-scope-a', 'Scope A') ON CONFLICT DO NOTHING")
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-scope-b', 'Scope B') ON CONFLICT DO NOTHING")
        conn.execute(
            '''
            INSERT INTO devices (id, hostname, ip_address, platform, role, site, device_category, tenant_id)
            VALUES ('scope-device-a', 'edge-a', '192.0.2.10', 'cisco_ios', 'core', 'HQ', 'Network', 'tenant-scope-a'),
                   ('scope-device-b', 'edge-b', '192.0.2.11', 'huawei_vrp', 'access', 'Branch', 'Network', 'tenant-scope-b')
            '''
        )
        conn.commit()
    finally:
        conn.close()

    catalog = alert_rule_service.get_scope_catalog('tenant-scope-a')
    assert catalog['sites'] == [{'value': 'HQ', 'count': 1}]
    assert catalog['roles'] == [{'value': 'core', 'count': 1}]
    assert catalog['categories'] == [{'value': 'Network', 'count': 1}]
    assert catalog['platforms'] == [{'value': 'cisco_ios', 'count': 1}]
    search_result = alert_rule_service.get_scope_catalog('tenant-scope-a', search='192.0.2.10')
    assert search_result['device_total'] == 1
    assert [device['id'] for device in search_result['devices']] == ['scope-device-a']
    assert alert_rule_service.get_scope_catalog('tenant-scope-a', search='edge-b')['devices'] == []
    selected_result = alert_rule_service.get_scope_catalog(
        'tenant-scope-a', device_ids=['scope-device-a', 'scope-device-b', 'missing-device'],
    )
    assert [device['id'] for device in selected_result['devices']] == ['scope-device-a']
    assert selected_result['missing_device_ids'] == ['scope-device-b', 'missing-device']
    from api.alerts import read_alert_rule_scope_catalog
    api_search = read_alert_rule_scope_catalog(
        search='edge-a', user={'id': 'scope-catalog-viewer', 'role': 'Viewer', 'tenant_id': 'tenant-scope-a'},
    )
    assert [device['id'] for device in api_search['devices']] == ['scope-device-a']
    api_cross_tenant_search = read_alert_rule_scope_catalog(
        search='edge-b', user={'id': 'scope-catalog-viewer', 'role': 'Viewer', 'tenant_id': 'tenant-scope-a'},
    )
    assert [device['id'] for device in api_cross_tenant_search['devices']] == ['scope-device-b']
    with pytest.raises(ValueError, match="workspace"):
        alert_rule_service.create_rule(
            _payload("Host", metric_type="host_cpu", notification_channels=["email"], notification_group_names=[]),
            tenant_id="tenant-default",
        )


def test_selected_execution_machines_are_exact_and_tenant_scoped(isolated_db):
    connection = get_db_connection()
    try:
        connection.execute("INSERT INTO tenants (id, name) VALUES ('tenant-machine-a', 'Machine A') ON CONFLICT DO NOTHING")
        connection.execute("INSERT INTO tenants (id, name) VALUES ('tenant-machine-b', 'Machine B') ON CONFLICT DO NOTHING")
        connection.execute(
            """
            INSERT INTO devices (id, hostname, ip_address, tenant_id)
            VALUES ('machine-a', 'edge-a', '192.0.2.20', 'tenant-machine-a'),
                   ('machine-b', 'edge-b', '192.0.2.21', 'tenant-machine-b')
            """
        )
        connection.commit()
    finally:
        connection.close()

    created = alert_rule_service.create_rule(
        _payload('Selected machine', scope_type='devices', scope_value='["machine-a"]', scope_match_mode='exact', notification_group_names=[]),
        tenant_id='tenant-machine-a',
    )
    assert created['scope_value'] == '["machine-a"]'
    with pytest.raises(ValueError, match='current tenant CMDB'):
        alert_rule_service.create_rule(
            _payload('Foreign machine', scope_type='devices', scope_value='["machine-b"]', notification_group_names=[]),
            tenant_id='tenant-machine-a',
        )
    with pytest.raises(ValueError, match='exact matching'):
        alert_rule_service.create_rule(
            _payload('Fuzzy machine IDs', scope_type='devices', scope_value='["machine-a"]', scope_match_mode='contains', notification_group_names=[]),
            tenant_id='tenant-machine-a',
        )


def test_tenant_rule_migration_copies_network_rules_only(isolated_db):
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-copy', 'Copy Tenant') ON CONFLICT DO NOTHING")
        conn.execute(
            """
            INSERT INTO alert_rules (id, tenant_id, name, metric_type, created_at, updated_at)
            VALUES ('legacy-srv-rule', 'tenant-default', 'Legacy server rule', 'srv_cpu_util', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        conn.execute(
            """
            UPDATE alert_rules
            SET scope_type = 'site', scope_match_mode = 'contains', scope_value = 'legacy-site',
                notification_channels_json = '[\"email\"]'::jsonb,
                notification_group_names_json = '[\"legacy-group\"]'::jsonb
            WHERE id = 'builtin-host-cpu'
            """
        )
        conn.execute(
            """
            INSERT INTO alert_rule_history (id, settings_id, rule_id, tenant_id, snapshot_json, changed_by, created_at)
            VALUES ('legacy-host-history', 'default', 'builtin-host-cpu', 'tenant-default', ?, 'admin', CURRENT_TIMESTAMP)
            """,
            (json.dumps({
                'id': 'builtin-host-cpu',
                'tenant_id': 'tenant-default',
                'metric_type': 'host_cpu',
                'scope_type': 'site',
                'scope_match_mode': 'contains',
                'scope_value': 'legacy-site',
                'notification_channels': ['email'],
                'notification_group_names': ['legacy-group'],
            }),),
        )
        conn.commit()
        alert_rule_service.create_rule(_payload("Migration source", notification_group_names=[]), tenant_id="tenant-default")
        upgrade_tenant_rules(conn.cursor(), use_pg=True)
        conn.commit()
        network_default = conn.execute(
            "SELECT COUNT(*) AS c FROM alert_rules WHERE tenant_id = 'tenant-default' AND metric_type NOT LIKE 'host_%' AND metric_type NOT LIKE 'srv_%'"
        ).fetchone()["c"]
        network_copy = conn.execute(
            "SELECT COUNT(*) AS c FROM alert_rules WHERE tenant_id = 'tenant-copy' AND metric_type NOT LIKE 'host_%' AND metric_type NOT LIKE 'srv_%'"
        ).fetchone()["c"]
        host_copy = conn.execute(
            "SELECT COUNT(*) AS c FROM alert_rules WHERE tenant_id = 'tenant-copy' AND metric_type LIKE 'host_%'"
        ).fetchone()["c"]
        assert network_copy == network_default
        assert host_copy == 0
        srv_counts = conn.execute(
            "SELECT tenant_id, COUNT(*) AS c FROM alert_rules WHERE metric_type LIKE 'srv_%' GROUP BY tenant_id"
        ).fetchall()
        assert {row["tenant_id"]: row["c"] for row in srv_counts} == {"tenant-default": 1}
        normalized_host = alert_rule_service.get_rule('builtin-host-cpu', tenant_id='tenant-default')
        assert normalized_host['scope_type'] == 'global'
        assert normalized_host['scope_match_mode'] == 'exact'
        assert normalized_host['scope_value'] == ''
        assert normalized_host['notification_channels'] == ['workspace']
        assert normalized_host['notification_group_names'] == []
        normalized_host_history = alert_rule_service.list_rule_history(
            rule_id='builtin-host-cpu', tenant_id='tenant-default',
        )
        snapshot = normalized_host_history[0]['snapshot']
        assert snapshot['scope_type'] == 'global'
        assert snapshot['scope_match_mode'] == 'exact'
        assert snapshot['scope_value'] == ''
        assert snapshot['notification_channels'] == ['workspace']
        assert snapshot['notification_group_names'] == []
        copied_history = conn.execute(
            "SELECT COUNT(*) AS c FROM alert_rule_history WHERE tenant_id = 'tenant-copy'"
        ).fetchone()["c"]
        assert copied_history > 0
        upgrade_tenant_rules(conn.cursor(), use_pg=True)
        conn.commit()
        repeated = conn.execute(
            "SELECT COUNT(*) AS c FROM alert_rules WHERE tenant_id = 'tenant-copy'"
        ).fetchone()["c"]
        assert repeated == network_copy
    finally:
        conn.close()
