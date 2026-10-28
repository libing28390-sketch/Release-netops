"""Scope alert rules and their history to tenants.

The pre-0257 alert rule table was global even though devices, users, and SMTP
profiles already carried tenant boundaries. This migration keeps the existing
rows in tenant-default and materializes equivalent supported network rules for
every other existing tenant. Host resource rules describe the platform itself,
and unsupported server rules have no runtime evaluator; both remain only in
tenant-default.
"""

from __future__ import annotations

import json
import uuid


VERSION = 257
NAME = "tenant_scoped_alert_rules"


def _value(row, key, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _snapshot_with_scope(raw, *, rule_id: str | None, tenant_id: str, groups=None, host_system: bool = False) -> str:
    try:
        snapshot = json.loads(raw or "{}")
    except (TypeError, ValueError):
        snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    if rule_id:
        snapshot["id"] = rule_id
        snapshot["rule_id"] = rule_id
    snapshot["tenant_id"] = tenant_id
    if groups is not None:
        snapshot.setdefault("notification_group_names", groups)
    if host_system:
        snapshot.update({
            "scope_type": "global",
            "scope_match_mode": "exact",
            "scope_value": "",
            "notification_channels": ["workspace"],
            "notification_group_names": [],
        })
    return json.dumps(snapshot, ensure_ascii=False)


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute(
        """
        ALTER TABLE alert_rules
        ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'tenant-default'
        """
    )
    cursor.execute(
        """
        ALTER TABLE alert_rules
        ADD COLUMN IF NOT EXISTS notification_group_names_json JSONB
        NOT NULL DEFAULT '[]'::jsonb
        """
    )
    cursor.execute(
        """
        UPDATE alert_rules
           SET tenant_id = 'tenant-default'
         WHERE tenant_id IS NULL OR tenant_id = ''
        """
    )
    cursor.execute(
        """
        UPDATE alert_rules
           SET notification_group_names_json = '[]'::jsonb
         WHERE notification_group_names_json IS NULL
            OR jsonb_typeof(notification_group_names_json) <> 'array'
        """
    )
    cursor.execute(
        """
        UPDATE alert_rules
           SET tenant_id = 'tenant-default',
               scope_type = 'global',
               scope_match_mode = 'exact',
               scope_value = '',
               notification_channels_json = '[\"workspace\"]'::jsonb,
               notification_group_names_json = '[]'::jsonb
         WHERE metric_type LIKE 'host_%'
        """
    )
    cursor.execute(
        """
        ALTER TABLE alert_rule_history
        ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'tenant-default'
        """
    )
    cursor.execute(
        """
        UPDATE alert_rule_history h
           SET tenant_id = COALESCE(r.tenant_id, 'tenant-default')
          FROM alert_rules r
         WHERE h.rule_id = r.id
           AND (h.tenant_id IS NULL OR h.tenant_id = '')
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_rules_tenant_metric "
        "ON alert_rules(tenant_id, metric_type, enabled)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_rule_history_tenant_created "
        "ON alert_rule_history(tenant_id, created_at DESC)"
    )

    cursor.execute(
        "SELECT id FROM tenants WHERE id IS NOT NULL AND id <> '' ORDER BY id"
    )
    tenant_rows = cursor.fetchall()
    tenant_ids = [str(_value(row, "id", "")).strip() for row in tenant_rows]
    tenant_ids = [tenant_id for tenant_id in tenant_ids if tenant_id]
    if "tenant-default" not in tenant_ids:
        tenant_ids.insert(0, "tenant-default")

    cursor.execute(
        """
        SELECT * FROM alert_rules
         WHERE tenant_id = 'tenant-default'
           AND metric_type NOT LIKE 'host_%'
           AND metric_type NOT LIKE 'srv_%'
        ORDER BY id
        """
    )
    source_rules = [dict(row) for row in cursor.fetchall()]
    rule_columns = (
        "id, tenant_id, name, metric_type, scope_type, scope_match_mode, scope_value, severity, threshold, enabled, "
        "aggregation_mode, notification_repeat_window_seconds, for_duration_seconds, notification_channels_json, "
        "notification_group_names_json, notify_on_active, notify_on_recovery, notify_on_reopen_after_maintenance, "
        "created_by, created_at, updated_by, updated_at"
    )
    for tenant_id in tenant_ids:
        if tenant_id == "tenant-default":
            continue
        for source in source_rules:
            source_id = str(source["id"])
            copied_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:alert-rule:{tenant_id}:{source_id}"))
            cursor.execute(
                f"""
                INSERT INTO alert_rules ({rule_columns})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    copied_id,
                    tenant_id,
                    source["name"],
                    source["metric_type"],
                    source["scope_type"],
                    source["scope_match_mode"],
                    source.get("scope_value") or "",
                    source["severity"],
                    source.get("threshold"),
                    source.get("enabled", 1),
                    source.get("aggregation_mode") or "dedupe_key",
                    source.get("notification_repeat_window_seconds") or 120,
                    source.get("for_duration_seconds") or 0,
                    json.dumps(source.get("notification_channels_json") or ["workspace"], ensure_ascii=False),
                    json.dumps(source.get("notification_group_names_json") or [], ensure_ascii=False),
                    source.get("notify_on_active", 1),
                    source.get("notify_on_recovery", 1),
                    source.get("notify_on_reopen_after_maintenance", 1),
                    source.get("created_by") or "system",
                    source["created_at"],
                    source.get("updated_by") or "system",
                    source["updated_at"],
                ),
            )
            cursor.execute(
                """
                SELECT id, snapshot_json, changed_by, created_at
                  FROM alert_rule_history
                 WHERE rule_id = ? AND tenant_id = 'tenant-default'
                 ORDER BY created_at, id
                """,
                (source_id,),
            )
            for history in cursor.fetchall():
                history_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"nexora:alert-rule-history:{tenant_id}:{history['id']}",
                ))
                groups = source.get("notification_group_names_json") or []
                if isinstance(groups, str):
                    try:
                        groups = json.loads(groups)
                    except (TypeError, ValueError):
                        groups = []
                cursor.execute(
                    """
                    INSERT INTO alert_rule_history
                        (id, settings_id, rule_id, tenant_id, snapshot_json, changed_by, created_at)
                    VALUES (?, 'default', ?, ?, ?, ?, ?)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        history_id,
                        copied_id,
                        tenant_id,
                        _snapshot_with_scope(
                            history["snapshot_json"],
                            rule_id=copied_id,
                            tenant_id=tenant_id,
                            groups=groups,
                        ),
                        history.get("changed_by") or "system",
                        history["created_at"],
                    ),
                )

    cursor.execute(
        "SELECT id, rule_id, tenant_id, snapshot_json FROM alert_rule_history ORDER BY id"
    )
    for history in cursor.fetchall():
        rule_id = _value(history, "rule_id")
        tenant_id = str(_value(history, "tenant_id", "tenant-default") or "tenant-default")
        rule = None
        if rule_id:
            cursor.execute(
                "SELECT notification_group_names_json, metric_type FROM alert_rules WHERE id = ?",
                (rule_id,),
            )
            rule = cursor.fetchone()
        groups = _value(rule, "notification_group_names_json", []) if rule else []
        if isinstance(groups, str):
            try:
                groups = json.loads(groups)
            except (TypeError, ValueError):
                groups = []
        cursor.execute(
            "UPDATE alert_rule_history SET tenant_id = ?, snapshot_json = ? WHERE id = ?",
            (
                tenant_id,
                _snapshot_with_scope(
                    history["snapshot_json"],
                    rule_id=str(rule_id),
                    tenant_id=tenant_id,
                    groups=groups,
                    host_system=str(_value(rule, "metric_type", "") or "").startswith("host_"),
                ),
                history["id"],
            ),
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Tenant and group data are additive and must survive rollback/retry.
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
