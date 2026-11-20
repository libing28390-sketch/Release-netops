from __future__ import annotations

import json

from database import get_db_connection
from database.migrations.m0259_normalize_alert_rule_notifications import upgrade
from services import alert_rule_service


def test_legacy_network_channels_are_normalized_and_host_channel_is_preserved(isolated_db):
    connection = get_db_connection()
    try:
        rules = [
            ("legacy-workspace", "interface_down", ["workspace"]),
            ("legacy-dingtalk", "cpu", ["dingtalk"]),
            ("mixed-email-dingtalk", "memory", ["email", "dingtalk"]),
            ("current-methods", "interface_util", ["feishu", "email"]),
            ("host-workspace", "host_cpu", ["workspace"]),
        ]
        for rule_id, metric_type, channels in rules:
            connection.execute(
                """
                INSERT INTO alert_rules
                    (id, tenant_id, name, metric_type, notification_channels_json, created_at, updated_at)
                VALUES (?, 'tenant-default', ?, ?, ?::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (rule_id, rule_id, metric_type, json.dumps(channels)),
            )
        connection.execute(
            """
            INSERT INTO alert_rule_history
                (id, settings_id, rule_id, tenant_id, snapshot_json, changed_by, created_at)
            VALUES ('legacy-workspace-history', 'default', 'legacy-workspace', 'tenant-default', ?, 'admin', CURRENT_TIMESTAMP),
                   ('host-workspace-history', 'default', 'host-workspace', 'tenant-default', ?, 'admin', CURRENT_TIMESTAMP)
            """,
            (
                json.dumps({'metric_type': 'interface_down', 'notification_channels': ['workspace']}),
                json.dumps({'metric_type': 'host_cpu', 'notification_channels': ['workspace']}),
            ),
        )
        connection.commit()

        upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        stored = {
            row['id']: row['notification_channels_json']
            for row in connection.execute(
                "SELECT id, notification_channels_json FROM alert_rules WHERE id LIKE 'legacy-%' OR id LIKE 'mixed-%' OR id IN ('current-methods', 'host-workspace')"
            ).fetchall()
        }
        assert stored['legacy-workspace'] == ['feishu', 'email']
        assert stored['legacy-dingtalk'] == ['feishu', 'email']
        assert stored['mixed-email-dingtalk'] == ['email']
        assert stored['current-methods'] == ['feishu', 'email']
        assert stored['host-workspace'] == ['workspace']

        snapshots = {
            row['id']: json.loads(row['snapshot_json'])
            for row in connection.execute(
                "SELECT id, snapshot_json FROM alert_rule_history WHERE id IN ('legacy-workspace-history', 'host-workspace-history')"
            ).fetchall()
        }
        assert snapshots['legacy-workspace-history']['notification_channels'] == ['feishu', 'email']
        assert snapshots['host-workspace-history']['notification_channels'] == ['workspace']

        normalized = alert_rule_service.get_rule('legacy-workspace', tenant_id='tenant-default')
        assert normalized['notification_channels'] == ['feishu', 'email']

        upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        assert connection.execute(
            "SELECT notification_channels_json FROM alert_rules WHERE id = 'legacy-workspace'"
        ).fetchone()['notification_channels_json'] == ['feishu', 'email']
    finally:
        connection.close()
