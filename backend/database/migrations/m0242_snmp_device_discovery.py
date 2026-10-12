"""Persist secret-free, per-device SNMP identity and OID discovery results."""

from __future__ import annotations


VERSION = 242
NAME = "snmp_device_discovery"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_device_discoveries (
            device_id TEXT PRIMARY KEY,
            vendor TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            software_version TEXT NOT NULL DEFAULT '',
            sys_object_id TEXT NOT NULL DEFAULT '',
            sys_descr TEXT NOT NULL DEFAULT '',
            sys_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT NOT NULL DEFAULT '',
            rule_version TEXT NOT NULL DEFAULT '',
            identity_json TEXT NOT NULL DEFAULT '{}',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            interface_json TEXT NOT NULL DEFAULT '{}',
            exporter_json TEXT NOT NULL DEFAULT '{}',
            observed_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_device_discoveries_status "
        "ON snmp_device_discoveries(status, updated_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_device_discoveries_identity "
        "ON snmp_device_discoveries(vendor, platform, model)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute("DROP TABLE IF EXISTS snmp_device_discoveries")
