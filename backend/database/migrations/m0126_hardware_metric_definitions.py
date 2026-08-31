"""Add the model-scoped hardware metric definition map.

The previous profile shape had dedicated CPU and memory JSON columns.  Keep
those columns as a compatibility projection and add one additive map for
temperature, fan, PSU, storage, voltage, and future hardware metrics.
"""

from __future__ import annotations

import json


VERSION = 126
NAME = "hardware_metric_definitions"


def _columns(cursor, use_pg: bool) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'snmp_metric_profiles'"
    )
    return {str(row[0]) for row in cursor.fetchall()}



def _decode(value) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def upgrade(cursor, use_pg: bool) -> None:
    if "metric_definitions_json" not in _columns(cursor, use_pg):
        cursor.execute(
            "ALTER TABLE snmp_metric_profiles "
            "ADD COLUMN IF NOT EXISTS metric_definitions_json TEXT NOT NULL DEFAULT '{}'"
        )

    rows = cursor.execute(
        "SELECT id, metric_definitions_json, cpu_config_json, memory_config_json, cpu_oid, memory_oid "
        "FROM snmp_metric_profiles"
    ).fetchall()
    for row in rows:
        existing = _decode(row[1])
        if existing:
            continue
        definitions = {}
        for metric, config_value, legacy_oid in (
            ("cpu", row[2], row[4]),
            ("memory", row[3], row[5]),
        ):
            config = _decode(config_value)
            if not config and legacy_oid:
                config = {"mode": "direct_percent", "oid": str(legacy_oid)}
            if config:
                definitions[metric] = config
        if definitions:
            cursor.execute(
                "UPDATE snmp_metric_profiles SET metric_definitions_json = ? WHERE id = ?",
                (json.dumps(definitions, ensure_ascii=False, separators=(",", ":")), row[0]),
            )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Preserve the additive map during rollback; older readers ignore it.
    return None
