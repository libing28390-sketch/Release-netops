"""Normalize network alert rules to the supported Webhook and email methods."""

from __future__ import annotations

import json


VERSION = 259
NAME = "normalize_alert_rule_notifications"
SUPPORTED_CHANNELS = ("feishu", "email")


def _decode_channels(value) -> list[str]:
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(raw, (list, tuple, set)):
        return []
    return list(dict.fromkeys(str(item or "").strip().lower() for item in raw if str(item or "").strip()))


def _current_channels(value) -> list[str]:
    raw = _decode_channels(value)
    supported = [channel for channel in raw if channel in SUPPORTED_CHANNELS]
    if "workspace" in raw or not supported:
        return list(SUPPORTED_CHANNELS)
    return supported


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute("SELECT id, metric_type FROM alert_rules")
    metric_by_rule_id = {str(row["id"]): str(row["metric_type"] or "") for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT id, notification_channels_json
          FROM alert_rules
         WHERE metric_type NOT LIKE 'host_%'
         ORDER BY id
        """
    )
    for row in cursor.fetchall():
        channels = _current_channels(row["notification_channels_json"])
        previous = _decode_channels(row["notification_channels_json"])
        if channels != previous:
            cursor.execute(
                "UPDATE alert_rules SET notification_channels_json = ?::jsonb WHERE id = ?",
                (json.dumps(channels), row["id"]),
            )

    cursor.execute("SELECT id, rule_id, snapshot_json FROM alert_rule_history ORDER BY id")
    for row in cursor.fetchall():
        try:
            snapshot = json.loads(row["snapshot_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(snapshot, dict):
            continue
        metric_type = str(snapshot.get("metric_type") or metric_by_rule_id.get(str(row["rule_id"] or ""), ""))
        if metric_type.startswith("host_"):
            continue
        previous = _decode_channels(snapshot.get("notification_channels"))
        channels = _current_channels(previous)
        if channels == previous:
            continue
        snapshot["notification_channels"] = channels
        cursor.execute(
            "UPDATE alert_rule_history SET snapshot_json = ?::jsonb WHERE id = ?",
            (json.dumps(snapshot, ensure_ascii=False), row["id"]),
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # The legacy workspace preference fan-out cannot be reconstructed from the
    # normalized rule alone; restoring it requires a pre-migration DB backup.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
