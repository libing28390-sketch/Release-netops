"""Store reusable topology icons and their role and device assignments."""

from __future__ import annotations


VERSION = 326
NAME = "topology_device_icons"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Topology icon assignments require PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS topology_device_icons (
            id TEXT PRIMARY KEY,
            device_type TEXT NOT NULL CHECK (device_type IN (
                'switch', 'firewall', 'router', 'load_balancer', 'waf',
                'vpn_gateway', 'server', 'wireless_ap',
                'wireless_controller', 'wireless', 'generic'
            )),
            name TEXT NOT NULL CHECK (BTRIM(name) <> '' AND LENGTH(name) <= 80),
            content_type TEXT NOT NULL CHECK (content_type IN ('image/svg+xml', 'image/png')),
            storage_backend TEXT NOT NULL CHECK (storage_backend IN ('local', 's3')),
            storage_config_id TEXT,
            storage_bucket TEXT NOT NULL DEFAULT '',
            object_key TEXT NOT NULL UNIQUE,
            object_size INTEGER NOT NULL CHECK (object_size > 0 AND object_size <= 4194304),
            object_sha256 TEXT NOT NULL CHECK (LENGTH(object_sha256) = 64),
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (storage_config_id)
                REFERENCES storage_provider_configs(id) ON DELETE RESTRICT
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_topology_device_icons_type_name
        ON topology_device_icons(device_type, name, created_at, id)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS topology_device_icon_defaults (
            device_type TEXT PRIMARY KEY CHECK (device_type IN (
                'switch', 'firewall', 'router', 'load_balancer', 'waf',
                'vpn_gateway', 'server', 'wireless_ap',
                'wireless_controller', 'wireless', 'generic'
            )),
            icon_id TEXT NOT NULL,
            updated_by TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            FOREIGN KEY (icon_id)
                REFERENCES topology_device_icons(id) ON DELETE RESTRICT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS topology_device_icon_overrides (
            device_id TEXT PRIMARY KEY,
            device_type TEXT NOT NULL CHECK (device_type IN (
                'switch', 'firewall', 'router', 'load_balancer', 'waf',
                'vpn_gateway', 'server', 'wireless_ap',
                'wireless_controller', 'wireless', 'generic'
            )),
            icon_id TEXT NOT NULL,
            updated_by TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
            FOREIGN KEY (icon_id)
                REFERENCES topology_device_icons(id) ON DELETE RESTRICT
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_topology_device_icon_overrides_type
        ON topology_device_icon_overrides(device_type, device_id)
        """
    )


def downgrade(cursor, use_pg: bool) -> None:
    # Keep user-managed icon files and assignments available during rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
