from __future__ import annotations

from database import get_db_connection
from api.health import _load_host_alert_rules


def test_host_alert_rules_load_all_default_tenant_tiers(isolated_db) -> None:
    connection = get_db_connection()
    try:
        connection.execute(
            """
            UPDATE alert_rules
               SET enabled = 1, severity = 'major', threshold = 75,
                   updated_at = '2026-09-26T00:00:00+00:00'
             WHERE id = 'builtin-host-cpu'
            """
        )
        connection.execute(
            """
            INSERT INTO alert_rules
                (id, tenant_id, name, metric_type, severity, threshold, enabled, created_at, updated_at)
            VALUES
                ('host-cpu-warning-old', 'tenant-default', 'Older CPU warning', 'host_cpu', 'warning', 70, 1, '2026-09-26', '2026-09-27T10:00:00+00:00'),
                ('host-cpu-warning-new', 'tenant-default', 'Latest CPU warning', 'host_cpu', 'warning', 68, 1, '2026-09-27', '2026-09-27T13:00:00+00:00'),
                ('host-cpu-critical-new', 'tenant-default', 'Latest CPU critical', 'host_cpu', 'critical', 91, 1, '2026-09-27', '2026-09-27T12:00:00+00:00'),
                ('host-cpu-disabled-new', 'tenant-default', 'Disabled CPU rule', 'host_cpu', 'critical', 1, 0, '2026-09-28', '2026-09-28T13:00:00+00:00'),
                ('host-cpu-other-tenant', 'tenant-other', 'Other tenant CPU rule', 'host_cpu', 'critical', 1, 1, '2026-09-29', '2026-09-29T13:00:00+00:00')
            """
        )
        connection.commit()
    finally:
        connection.close()

    cpu_rule = _load_host_alert_rules()['cpu_percent']

    assert cpu_rule['enabled'] is True
    assert cpu_rule['warn'] == 68.0
    assert cpu_rule['critical'] == 91.0
