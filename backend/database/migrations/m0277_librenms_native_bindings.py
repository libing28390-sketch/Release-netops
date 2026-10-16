"""Persist LibreNMS native instances and explicit Nexora device bindings."""

from __future__ import annotations


VERSION = 277
NAME = "librenms_native_bindings"


def upgrade(cursor, use_pg: bool) -> None:
    """Create the PostgreSQL integration registry for native LibreNMS.

    Nexora stores only the ID of the encrypted credential record. LibreNMS
    remains responsible for SNMP collection and its own datastore; these tables
    hold integration identity, synchronization state, and task health only.
    """
    if not use_pg:
        raise RuntimeError("librenms_native_bindings requires PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS librenms_instances (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL CHECK (BTRIM(display_name) <> ''),
            base_url TEXT NOT NULL CHECK (BTRIM(base_url) <> ''),
            token_credential_id TEXT,
            engine_version TEXT NOT NULL DEFAULT '',
            engine_commit TEXT NOT NULL DEFAULT '',
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            health_state TEXT NOT NULL DEFAULT 'unknown'
                CHECK (health_state IN ('unknown', 'healthy', 'unavailable', 'error')),
            health_checked_at TIMESTAMPTZ,
            health_error_code TEXT NOT NULL DEFAULT '',
            health_error_text TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (token_credential_id)
                REFERENCES credentials(id) ON DELETE SET NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_librenms_instances_enabled_health
            ON librenms_instances(enabled, health_state, updated_at DESC)
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS librenms_device_bindings (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL CHECK (BTRIM(tenant_id) <> ''),
            asset_id TEXT NOT NULL CHECK (BTRIM(asset_id) <> ''),
            device_id TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            librenms_device_id TEXT
                CHECK (librenms_device_id IS NULL OR BTRIM(librenms_device_id) <> ''),
            librenms_hostname TEXT NOT NULL DEFAULT '',
            collector_id TEXT NOT NULL DEFAULT '',
            poller_group TEXT NOT NULL DEFAULT '',
            desired_state TEXT NOT NULL DEFAULT 'enabled'
                CHECK (desired_state IN ('enabled', 'disabled')),
            sync_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (sync_status IN ('pending', 'synced', 'failed', 'disabled')),
            last_sync_at TIMESTAMPTZ,
            last_discovery_at TIMESTAMPTZ,
            last_poll_at TIMESTAMPTZ,
            last_error_code TEXT NOT NULL DEFAULT '',
            last_error_text TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_librenms_bindings_device
                UNIQUE (device_id),
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
            FOREIGN KEY (asset_id) REFERENCES physical_assets(id) ON DELETE CASCADE,
            FOREIGN KEY (instance_id)
                REFERENCES librenms_instances(id) ON DELETE RESTRICT
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_librenms_bindings_native_device
            ON librenms_device_bindings(instance_id, librenms_device_id)
            WHERE librenms_device_id IS NOT NULL
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_librenms_bindings_tenant_asset_device
            ON librenms_device_bindings(tenant_id, asset_id, device_id)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_librenms_bindings_device
            ON librenms_device_bindings(device_id)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_librenms_bindings_instance_sync_state
            ON librenms_device_bindings(instance_id, desired_state, sync_status)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_librenms_bindings_poller_group
            ON librenms_device_bindings(instance_id, poller_group, desired_state)
        """
    )


def downgrade(cursor, use_pg: bool) -> None:
    """Drop the binding registry while retaining credentials and device data."""
    if not use_pg:
        raise RuntimeError("librenms_native_bindings requires PostgreSQL")
    cursor.execute("DROP TABLE IF EXISTS librenms_device_bindings")
    cursor.execute("DROP TABLE IF EXISTS librenms_instances")


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
