"""Monitoring V1 control-plane objects and the generic IF-MIB catalog.

The migration is deliberately additive.  The existing native telemetry tables
remain the source used by the ``native`` provider until a collector is
explicitly cut over.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


VERSION = 232
NAME = "monitoring_v1_control_plane"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Extend the credential vault with encrypted SNMPv3 fields.  Existing
    # v2c rows remain untouched and continue using the encrypted community.
    credential_columns = {row[0] for row in cursor.execute("SELECT * FROM credentials LIMIT 0").description}
    for column, definition in (
        ("snmp_security_level", "TEXT NOT NULL DEFAULT 'authPriv'"),
        ("snmp_auth_protocol", "TEXT NOT NULL DEFAULT 'SHA'"),
        ("snmp_auth_password", "TEXT NOT NULL DEFAULT ''"),
        ("snmp_priv_protocol", "TEXT NOT NULL DEFAULT 'AES'"),
        ("snmp_priv_password", "TEXT NOT NULL DEFAULT ''"),
        ("snmp_context_name", "TEXT NOT NULL DEFAULT ''"),
    ):
        if column not in credential_columns:
            cursor.execute(f"ALTER TABLE credentials ADD COLUMN {column} {definition}")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_collectors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            site_id TEXT NOT NULL DEFAULT '',
            collector_type TEXT NOT NULL DEFAULT 'LOCAL',
            status TEXT NOT NULL DEFAULT 'UNKNOWN',
            enabled INTEGER NOT NULL DEFAULT 1,
            management_address TEXT NOT NULL DEFAULT '',
            remote_write_endpoint TEXT NOT NULL DEFAULT '',
            last_heartbeat_at TEXT,
            last_config_version INTEGER,
            last_config_applied_at TEXT,
            last_config_status TEXT NOT NULL DEFAULT '',
            max_concurrency INTEGER NOT NULL DEFAULT 8,
            queue_disk_limit_mb INTEGER NOT NULL DEFAULT 2048,
            software_version TEXT NOT NULL DEFAULT '',
            vmagent_version TEXT NOT NULL DEFAULT '',
            snmp_exporter_version TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_modules (
            id TEXT PRIMARY KEY,
            module_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            vendor TEXT NOT NULL DEFAULT '',
            cli_platform TEXT NOT NULL DEFAULT '',
            feature_domain TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            metric_group TEXT NOT NULL DEFAULT '',
            walk_fingerprint TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            built_in INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_module_variants (
            id TEXT PRIMARY KEY,
            module_id TEXT NOT NULL,
            variant_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            generator_config_version TEXT NOT NULL DEFAULT '',
            generated_config_version TEXT NOT NULL DEFAULT '',
            max_repetitions INTEGER NOT NULL DEFAULT 25,
            retries INTEGER NOT NULL DEFAULT 2,
            request_timeout_ms INTEGER NOT NULL DEFAULT 3000,
            scrape_timeout_ms INTEGER NOT NULL DEFAULT 20000,
            supported_models TEXT NOT NULL DEFAULT '[]',
            supported_version_scope TEXT NOT NULL DEFAULT '[]',
            verified_models TEXT NOT NULL DEFAULT '[]',
            verified_versions TEXT NOT NULL DEFAULT '[]',
            mib_bundle_id TEXT NOT NULL DEFAULT '',
            mib_hash TEXT NOT NULL DEFAULT '',
            generator_version TEXT NOT NULL DEFAULT '',
            generator_config_hash TEXT NOT NULL DEFAULT '',
            generated_output_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'DRAFT',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (module_id) REFERENCES snmp_modules(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_snmp_module_variants_module ON snmp_module_variants(module_id)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_collection_plans (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            cli_platform TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            config_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_collection_assignments (
            id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            collector_id TEXT NOT NULL,
            module_variant_id TEXT NOT NULL,
            credential_id TEXT NOT NULL DEFAULT '',
            auth_alias TEXT NOT NULL DEFAULT '',
            interval_seconds INTEGER NOT NULL,
            scrape_timeout_seconds INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            source_type TEXT NOT NULL DEFAULT 'PLAN',
            source_plan_id TEXT NOT NULL DEFAULT '',
            assignment_hash TEXT NOT NULL,
            last_compiled_at TEXT,
            last_config_version INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (collector_id) REFERENCES monitoring_collectors(id),
            FOREIGN KEY (module_variant_id) REFERENCES snmp_module_variants(id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_assignments_asset ON monitoring_collection_assignments(asset_id, enabled)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_assignments_collector ON monitoring_collection_assignments(collector_id, enabled)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_config_versions (
            id TEXT PRIMARY KEY,
            collector_id TEXT NOT NULL,
            config_version INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'COMPILED',
            artifact_path TEXT NOT NULL DEFAULT '',
            manifest_json TEXT NOT NULL DEFAULT '{}',
            checksum TEXT NOT NULL DEFAULT '',
            error_code TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            applied_at TEXT,
            rolled_back_at TEXT,
            UNIQUE (collector_id, config_version),
            FOREIGN KEY (collector_id) REFERENCES monitoring_collectors(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_target_snapshots (
            id TEXT PRIMARY KEY,
            collector_id TEXT NOT NULL,
            config_version INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL DEFAULT '[]',
            checksum TEXT NOT NULL,
            is_last_known_good INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (collector_id) REFERENCES monitoring_collectors(id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_snapshots_lkg ON monitoring_target_snapshots(collector_id, is_last_known_good)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_metric_definitions (
            id TEXT PRIMARY KEY,
            metric_key TEXT NOT NULL UNIQUE,
            semantic TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            query TEXT NOT NULL DEFAULT '',
            metric_type TEXT NOT NULL DEFAULT 'gauge',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_shadow_comparisons (
            id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            metric_key TEXT NOT NULL,
            native_value REAL,
            vm_value REAL,
            delta REAL,
            tolerance REAL NOT NULL DEFAULT 0.05,
            status TEXT NOT NULL,
            sampled_at TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_shadow_asset_metric ON monitoring_shadow_comparisons(asset_id, metric_key, sampled_at)")

    now = _now()
    cursor.execute(
        """
        INSERT INTO monitoring_collectors
          (id, name, code, collector_type, status, enabled, created_at, updated_at)
        VALUES (?, ?, ?, 'LOCAL', 'UNKNOWN', 1, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        ('collector-local', 'Local collector', 'collector-local', now, now),
    )
    cursor.execute(
        """
        INSERT INTO snmp_modules
          (id, module_key, display_name, vendor, cli_platform, feature_domain,
           description, metric_group, walk_fingerprint, enabled, built_in, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        ('module-generic-if-mib', 'generic_ifmib_interface', 'Generic IF-MIB interface', 'generic',
         'generic', 'interface', 'RFC 2863 interface status, speed and counters', 'interface',
         'if-mib:1.3.6.1.2.1.2|1.3.6.1.2.1.31', now, now),
    )
    cursor.execute(
        """
        INSERT INTO snmp_module_variants
          (id, module_id, variant_key, display_name, max_repetitions, retries,
           request_timeout_ms, scrape_timeout_ms, status, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, 25, 2, 3000, 20000, 'PUBLISHED', 1, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        ('variant-generic-if-mib-std', 'module-generic-if-mib', 'generic_ifmib_interface_std',
         'Generic IF-MIB standard', now, now),
    )
    cursor.execute(
        """
        INSERT INTO snmp_modules
          (id, module_key, display_name, vendor, cli_platform, feature_domain,
           description, metric_group, walk_fingerprint, enabled, built_in, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        ('module-generic-system', 'generic_system', 'Generic system', 'generic', 'generic', 'system',
         'RFC 3418 system uptime and identity', 'system', 'system-mib:1.3.6.1.2.1.1', now, now),
    )
    cursor.execute(
        """
        INSERT INTO snmp_module_variants
          (id, module_id, variant_key, display_name, max_repetitions, retries,
           request_timeout_ms, scrape_timeout_ms, status, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, 10, 2, 3000, 20000, 'PUBLISHED', 1, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        ('variant-generic-system-std', 'module-generic-system', 'generic_system_std',
         'Generic system standard', now, now),
    )
    cursor.execute(
        """
        INSERT INTO monitoring_collection_plans
          (id, name, cli_platform, description, config_json, enabled, created_at, updated_at)
        VALUES (?, ?, '*', ?, ?, 1, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            'plan-generic-ifmib',
            'Generic IF-MIB baseline',
            'Safe baseline for devices without a vendor-specific V1 plan',
            json.dumps({'modules': [
                {'module': 'generic_ifmib_interface', 'variant': 'generic_ifmib_interface_std', 'enabled': True, 'interval': '30s', 'scrape_timeout': '20s'},
                {'module': 'generic_system', 'variant': 'generic_system_std', 'enabled': True, 'interval': '900s', 'scrape_timeout': '30s'},
            ]}, ensure_ascii=False),
            now,
            now,
        ),
    )
    metric_rows = (
        ('device_uptime_seconds', 'Device uptime', 'seconds', 'sysUpTime / 100', 'gauge'),
        ('interface_admin_status', 'Interface administrative status', 'state', 'ifAdminStatus', 'gauge'),
        ('interface_oper_status', 'Interface operational status', 'state', 'ifOperStatus', 'gauge'),
        ('interface_speed_bps', 'Interface speed', 'bps', 'ifHighSpeed * 1000000', 'gauge'),
        ('interface_rx_bps', 'Interface receive bandwidth', 'bps', 'rate(ifHCInOctets[5m]) * 8', 'counter'),
        ('interface_tx_bps', 'Interface transmit bandwidth', 'bps', 'rate(ifHCOutOctets[5m]) * 8', 'counter'),
        ('interface_in_errors_rate', 'Interface receive errors', 'errors/s', 'rate(ifInErrors[5m])', 'counter'),
        ('interface_out_errors_rate', 'Interface transmit errors', 'errors/s', 'rate(ifOutErrors[5m])', 'counter'),
        ('interface_in_discards_rate', 'Interface receive discards', 'discards/s', 'rate(ifInDiscards[5m])', 'counter'),
        ('interface_out_discards_rate', 'Interface transmit discards', 'discards/s', 'rate(ifOutDiscards[5m])', 'counter'),
    )
    for key, semantic, unit, query, metric_type in metric_rows:
        cursor.execute(
            """
            INSERT INTO monitoring_metric_definitions
              (id, metric_key, semantic, unit, query, metric_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
            """,
            (f'metric-{key}', key, semantic, unit, query, metric_type, now, now),
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    for table in (
        'monitoring_shadow_comparisons', 'monitoring_metric_definitions',
        'monitoring_target_snapshots', 'monitoring_config_versions',
        'monitoring_collection_assignments', 'monitoring_collection_plans',
        'snmp_module_variants', 'snmp_modules', 'monitoring_collectors',
    ):
        cursor.execute(f'DROP TABLE IF EXISTS {table}')
