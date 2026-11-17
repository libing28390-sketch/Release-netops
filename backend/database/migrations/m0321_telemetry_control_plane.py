"""Add the PostgreSQL Telemetry control-plane tables."""

from __future__ import annotations

from datetime import datetime, timezone
import json


VERSION = 321
NAME = "telemetry_control_plane"


_UTC_NOW_SQL = "(to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'))"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_protocol_profiles(cursor) -> None:
    """Seed only documentation-scoped protocol records, never device claims."""
    now = _now()
    profiles = (
        (
            "70000000-0000-4000-8000-000000000001",
            "h3c_grpc_dialout_json_v2",
            "h3c",
            "switch",
            "S6812/S6813",
            "R6628Pxx-6W102",
            "h3c_grpc_dialout_json_v2",
            "json",
            "tls_pki",
            "",
            None,
            ["https://www.h3c.com/cn/d_202504/2397915_30005_0.htm"],
        ),
        (
            "70000000-0000-4000-8000-000000000002",
            "h3c_grpc_dialout_json_v3",
            "h3c",
            "switch",
            "S6520X-HI[EI][SI], S6520-SI, S5560X-HI, S5000-EI, MS4600",
            "R68xx-6W102",
            "h3c_grpc_dialout_json_v3",
            "json+telemetry-header",
            "tls_pki",
            "",
            None,
            ["https://www.h3c.com/cn/d_202602/2751840_30005_0.htm"],
        ),
        (
            "70000000-0000-4000-8000-000000000003",
            "huawei_grpc_dialout_json",
            "huawei",
            "switch",
            "CloudEngine S3700/S5700/S6700",
            "V600R024C10",
            "huawei_grpc_dialout_json",
            "json",
            "device_configured",
            "",
            None,
            [
                "https://e.huawei.com/en/documents/products/enterprise-network/16746037ed334a73ab8e8c5dc75b6c08",
                "https://e-file.huawei.com/marketingcloud/pep/asset/20000001/Material/16746037ed334a73ab8e8c5dc75b6c08/M3T1A669N1104567079904432171/CloudEngine%20S3700_%20S5700_%20and%20S6700%20V600R024C10%20Configuration%20Guide%20-%20System%20Monitoring.pdf",
            ],
        ),
    )
    for (
        profile_id,
        profile_key,
        vendor,
        platform,
        model_scope,
        version_scope,
        adapter_key,
        encoding,
        auth_mode,
        required_proto_version,
        min_interval_seconds,
        official_sources,
    ) in profiles:
        cursor.execute(
            """
            INSERT INTO telemetry_protocol_profiles (
                id, profile_key, vendor, platform, model_scope, version_scope,
                adapter_key, encoding, auth_mode, required_proto_version,
                min_interval_seconds, official_sources, support_status,
                is_system, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DOCUMENTED', TRUE, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                profile_id,
                profile_key,
                vendor,
                platform,
                model_scope,
                version_scope,
                adapter_key,
                encoding,
                auth_mode,
                required_proto_version,
                min_interval_seconds,
                json.dumps(official_sources, ensure_ascii=False),
                now,
                now,
            ),
        )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Telemetry control-plane tables require PostgreSQL")

    # The device primary key makes these indexes logically redundant, but
    # PostgreSQL requires an explicitly matching unique key for tenant-aware
    # and device/asset composite foreign keys.
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_id_tenant_id "
        "ON devices(id, tenant_id)"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_id_asset_id "
        "ON devices(id, asset_id)"
    )

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS telemetry_protocol_profiles (
            id TEXT PRIMARY KEY,
            profile_key TEXT NOT NULL UNIQUE,
            vendor TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT '',
            model_scope TEXT NOT NULL DEFAULT '',
            version_scope TEXT NOT NULL DEFAULT '',
            adapter_key TEXT NOT NULL,
            encoding TEXT NOT NULL,
            auth_mode TEXT NOT NULL DEFAULT 'unknown',
            required_proto_version TEXT NOT NULL DEFAULT '',
            min_interval_seconds INTEGER CHECK (min_interval_seconds > 0),
            official_sources JSONB NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(official_sources) = 'array'),
            support_status TEXT NOT NULL DEFAULT 'UNKNOWN'
                CHECK (support_status IN (
                    'DOCUMENTED', 'SAMPLE_VERIFIED', 'DEVICE_VERIFIED',
                    'UNSUPPORTED', 'UNKNOWN'
                )),
            is_system BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            updated_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL}
        )
        """
    )

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS telemetry_subscription_templates (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
            profile_id TEXT NOT NULL
                REFERENCES telemetry_protocol_profiles(id) ON DELETE RESTRICT,
            template_key TEXT NOT NULL,
            version INTEGER NOT NULL CHECK (version > 0),
            metric_mappings JSONB NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(metric_mappings) = 'array'),
            estimated_series INTEGER NOT NULL DEFAULT 0 CHECK (estimated_series >= 0),
            default_interval_seconds INTEGER NOT NULL CHECK (default_interval_seconds > 0),
            status TEXT NOT NULL DEFAULT 'DRAFT'
                CHECK (status IN ('DRAFT', 'PUBLISHED', 'RETIRED')),
            created_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            updated_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            CONSTRAINT uq_telemetry_templates_tenant_key_version
                UNIQUE (tenant_id, template_key, version),
            CONSTRAINT uq_telemetry_templates_id_tenant_version
                UNIQUE (id, tenant_id, version),
            CONSTRAINT uq_telemetry_templates_id_tenant
                UNIQUE (id, tenant_id)
        )
        """
    )

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS telemetry_tls_profiles (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
            name TEXT NOT NULL CHECK (btrim(name) <> ''),
            ca_certificate_ref TEXT NOT NULL DEFAULT '',
            client_certificate_ref TEXT NOT NULL DEFAULT '',
            encrypted_private_key_ref TEXT NOT NULL DEFAULT '',
            fingerprint TEXT NOT NULL DEFAULT '',
            valid_from TEXT,
            valid_until TEXT,
            version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('ACTIVE', 'ROTATION_PENDING', 'EXPIRED', 'REVOKED')),
            created_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            updated_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            CONSTRAINT uq_telemetry_tls_profiles_id_tenant UNIQUE (id, tenant_id)
        )
        """
    )

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS telemetry_device_configs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
            asset_id TEXT NOT NULL REFERENCES physical_assets(id) ON DELETE RESTRICT,
            device_id TEXT NOT NULL,
            device_source_address TEXT,
            collector_id TEXT NOT NULL
                REFERENCES monitoring_collectors(id) ON DELETE RESTRICT,
            profile_id TEXT NOT NULL
                REFERENCES telemetry_protocol_profiles(id) ON DELETE RESTRICT,
            credential_id TEXT REFERENCES credentials(id) ON DELETE RESTRICT,
            tls_profile_id TEXT,
            allowed_sources JSONB NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(allowed_sources) = 'array'),
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            updated_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            CONSTRAINT uq_telemetry_device_configs_tenant_device
                UNIQUE (tenant_id, device_id),
            CONSTRAINT uq_telemetry_device_configs_id_tenant
                UNIQUE (id, tenant_id),
            CONSTRAINT fk_telemetry_device_configs_device_tenant
                FOREIGN KEY (device_id, tenant_id)
                REFERENCES devices(id, tenant_id) ON DELETE RESTRICT,
            CONSTRAINT fk_telemetry_device_configs_device_asset
                FOREIGN KEY (device_id, asset_id)
                REFERENCES devices(id, asset_id) ON DELETE RESTRICT,
            CONSTRAINT fk_telemetry_device_configs_tls_tenant
                FOREIGN KEY (tls_profile_id, tenant_id)
                REFERENCES telemetry_tls_profiles(id, tenant_id) ON DELETE RESTRICT
        )
        """
    )

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS telemetry_subscriptions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
            config_id TEXT NOT NULL,
            name TEXT NOT NULL CHECK (btrim(name) <> ''),
            template_id TEXT NOT NULL,
            template_version INTEGER NOT NULL CHECK (template_version > 0),
            interval_seconds INTEGER NOT NULL CHECK (interval_seconds > 0),
            path_filters JSONB NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(path_filters) = 'array'),
            reserved_series INTEGER NOT NULL DEFAULT 0 CHECK (reserved_series >= 0),
            reserved_sample_rate DOUBLE PRECISION NOT NULL DEFAULT 0
                CHECK (reserved_sample_rate >= 0),
            desired_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            updated_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            CONSTRAINT uq_telemetry_subscriptions_config_name
                UNIQUE (config_id, name),
            CONSTRAINT uq_telemetry_subscriptions_id_tenant
                UNIQUE (id, tenant_id),
            CONSTRAINT fk_telemetry_subscriptions_config_tenant
                FOREIGN KEY (config_id, tenant_id)
                REFERENCES telemetry_device_configs(id, tenant_id) ON DELETE RESTRICT,
            CONSTRAINT fk_telemetry_subscriptions_template_tenant_version
                FOREIGN KEY (template_id, tenant_id, template_version)
                REFERENCES telemetry_subscription_templates(id, tenant_id, version)
                ON DELETE RESTRICT
        )
        """
    )

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS telemetry_subscription_runtime (
            subscription_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
            owner_id TEXT NOT NULL DEFAULT '',
            owner_epoch BIGINT NOT NULL DEFAULT 0 CHECK (owner_epoch >= 0),
            lease_expires_at TEXT,
            applied_version INTEGER,
            connection_state TEXT NOT NULL DEFAULT 'DISABLED'
                CHECK (connection_state IN (
                    'DISABLED', 'AWAITING_DEVICE', 'CONNECTING', 'CONNECTED', 'ERROR'
                )),
            data_state TEXT NOT NULL DEFAULT 'NO_DATA'
                CHECK (data_state IN ('NO_DATA', 'FRESH', 'PARTIAL', 'STALE', 'INVALID')),
            last_received_at TEXT,
            last_valid_at TEXT,
            clock_skew_ms BIGINT,
            active_series BIGINT NOT NULL DEFAULT 0 CHECK (active_series >= 0),
            sample_rate DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (sample_rate >= 0),
            queue_depth BIGINT NOT NULL DEFAULT 0 CHECK (queue_depth >= 0),
            dropped_samples BIGINT NOT NULL DEFAULT 0 CHECK (dropped_samples >= 0),
            reconnect_count BIGINT NOT NULL DEFAULT 0 CHECK (reconnect_count >= 0),
            error_code TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            CONSTRAINT uq_telemetry_subscription_runtime_subscription_tenant
                UNIQUE (subscription_id, tenant_id),
            CONSTRAINT fk_telemetry_subscription_runtime_subscription_tenant
                FOREIGN KEY (subscription_id, tenant_id)
                REFERENCES telemetry_subscriptions(id, tenant_id) ON DELETE RESTRICT
        )
        """
    )

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS telemetry_config_jobs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
            collector_id TEXT NOT NULL
                REFERENCES monitoring_collectors(id) ON DELETE RESTRICT,
            device_config_id TEXT,
            subscription_id TEXT,
            action TEXT NOT NULL
                CHECK (action IN ('PUBLISH', 'ENABLE', 'DISABLE', 'DELETE', 'RETRY', 'ROLLBACK')),
            desired_version INTEGER NOT NULL CHECK (desired_version > 0),
            idempotency_key TEXT NOT NULL CHECK (btrim(idempotency_key) <> ''),
            state TEXT NOT NULL DEFAULT 'QUEUED'
                CHECK (state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
            attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_expires_at TEXT,
            next_retry_at TEXT,
            error_code TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            updated_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            CONSTRAINT uq_telemetry_config_jobs_tenant_idempotency
                UNIQUE (tenant_id, idempotency_key),
            CONSTRAINT fk_telemetry_config_jobs_device_config_tenant
                FOREIGN KEY (device_config_id, tenant_id)
                REFERENCES telemetry_device_configs(id, tenant_id) ON DELETE RESTRICT,
            CONSTRAINT fk_telemetry_config_jobs_subscription_tenant
                FOREIGN KEY (subscription_id, tenant_id)
                REFERENCES telemetry_subscriptions(id, tenant_id) ON DELETE RESTRICT,
            CONSTRAINT ck_telemetry_config_jobs_target
                CHECK (device_config_id IS NOT NULL OR subscription_id IS NOT NULL)
        )
        """
    )

    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_telemetry_tls_profiles_tenant_name "
        "ON telemetry_tls_profiles(tenant_id, lower(btrim(name)))"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_telemetry_device_configs_collector_enabled "
        "ON telemetry_device_configs(collector_id, enabled, tenant_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_telemetry_subscriptions_tenant_enabled "
        "ON telemetry_subscriptions(tenant_id, desired_enabled, config_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_telemetry_config_jobs_queue "
        "ON telemetry_config_jobs(state, next_retry_at, created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_telemetry_config_jobs_tenant_created "
        "ON telemetry_config_jobs(tenant_id, created_at DESC)"
    )

    _seed_protocol_profiles(cursor)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Telemetry configuration and task history are durable control-plane state.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
