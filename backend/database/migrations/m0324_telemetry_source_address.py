"""Add the explicit Telemetry device source address and S6850 profile."""

from __future__ import annotations

from datetime import datetime, timezone
import json


VERSION = 324
NAME = "telemetry_source_address"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Telemetry source addresses require PostgreSQL")

    cursor.execute(
        "ALTER TABLE telemetry_device_configs "
        "ADD COLUMN IF NOT EXISTS device_source_address TEXT"
    )

    # These are documentation-scoped capability profiles, not device test
    # results. Both are restricted to the S6850 and the documented 6717 release.
    now = _now()
    profile_rows = (
        (
            "70000000-0000-4000-8000-000000000004",
            "h3c_grpc_dialout_json_v2_s6850_r6717",
            "h3c_grpc_dialout_json_v2",
            "json",
        ),
        (
            "70000000-0000-4000-8000-000000000005",
            "h3c_grpc_dialout_json_v3_s6850_r6717",
            "h3c_grpc_dialout_json_v3",
            "json+telemetry-header",
        ),
    )
    official_sources = json.dumps(
        ["https://wwwsg.h3c.com/cn/d_202606/2861049_30005_0.htm"],
        ensure_ascii=False,
    )
    for profile_id, profile_key, adapter_key, encoding in profile_rows:
        cursor.execute(
            """
            INSERT INTO telemetry_protocol_profiles (
                id, profile_key, vendor, platform, model_scope, version_scope,
                adapter_key, encoding, auth_mode, required_proto_version,
                min_interval_seconds, official_sources, support_status,
                is_system, created_at, updated_at
            ) VALUES (?, ?, 'h3c', 'switch', 'S6850', 'R6717Pxx-6W101',
                      ?, ?, 'tls_pki', '', NULL, ?, 'DOCUMENTED', TRUE, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (profile_id, profile_key, adapter_key, encoding, official_sources, now, now),
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Device source metadata and documentation-backed profile are retained.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
