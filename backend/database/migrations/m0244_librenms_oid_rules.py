"""Store parsed LibreNMS OS detection/discovery rules as the trusted source."""

from __future__ import annotations


VERSION = 244
NAME = "librenms_oid_rules"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_librenms_rules (
            id TEXT PRIMARY KEY,
            os_key TEXT NOT NULL,
            vendor TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT '',
            display_name TEXT NOT NULL DEFAULT '',
            detection_json TEXT NOT NULL DEFAULT '{}',
            oid_candidates_json TEXT NOT NULL DEFAULT '[]',
            source_path TEXT NOT NULL DEFAULT '',
            source_commit TEXT NOT NULL DEFAULT '',
            rule_status TEXT NOT NULL DEFAULT 'active',
            generated_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (os_key, source_commit)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_librenms_rules_vendor_platform "
        "ON snmp_librenms_rules(vendor, platform, rule_status)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute("DROP TABLE IF EXISTS snmp_librenms_rules")
