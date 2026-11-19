"""Add a Huawei CE6800 V200R005C10 Telemetry profile and starter draft."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid


VERSION = 325
NAME = "huawei_ce6800_v200r005c10_telemetry"

PROFILE_ID = "70000000-0000-4000-8000-000000000006"
PROFILE_KEY = "huawei_ce6800_v200r005c10_grpc_json"
TEMPLATE_KEY = "huawei_ce6800_v200r005c10_basic"

OFFICIAL_SOURCES = [
    "https://e.huawei.com/cn/products/switches/data-center-switches/ce6800",
    "https://info.support.huawei.com/info-finder/encyclopedia/zh/Telemetry.html",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _starter_mappings() -> list[dict]:
    # Source paths are copied from the device configuration supplied by the
    # user. The JSON fields are candidates only; a real payload must confirm
    # the shape before this template can be published.
    evidence = [
        "候选字段映射；尚未收到 CE6800 V200R005C10 JSON 样本，核实后再标记支持并发布。"
    ]
    return [
        {
            "metric_key": "huawei_ce6800_cpu_usage",
            "source_path": "huawei-devm:devm/cpuInfos/cpuInfo",
            "source_field": "cpuInfos.cpuInfo[*].systemCpuUsage",
            "value_type": "gauge",
            "unit": "percent",
            "primary_key_mapping": {"cpu_position": "position"},
            "source_timestamp_semantics": "unknown",
            "support_status": "UNKNOWN",
            "evidence": evidence,
        },
        {
            "metric_key": "huawei_ce6800_interface_speed",
            "source_path": "huawei-ifm:ifm/interfaces/interface",
            "source_field": "interfaces.interface[*].ifSpeed",
            "value_type": "gauge",
            "unit": "bits_per_second",
            "primary_key_mapping": {"interface_name": "ifName"},
            "source_timestamp_semantics": "unknown",
            "support_status": "UNKNOWN",
            "evidence": evidence,
        },
    ]


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Huawei CE6800 Telemetry templates require PostgreSQL")

    now = _now()
    cursor.execute(
        """
        INSERT INTO telemetry_protocol_profiles (
            id, profile_key, vendor, platform, model_scope, version_scope,
            adapter_key, encoding, auth_mode, required_proto_version,
            min_interval_seconds, official_sources, support_status,
            is_system, created_at, updated_at
        ) VALUES (?, ?, 'huawei', 'switch', 'CE6800', 'V200R005C10',
                  'huawei_grpc_dialout_json', 'json', 'device_configured', '',
                  10, ?, 'DOCUMENTED', TRUE, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (PROFILE_ID, PROFILE_KEY, json.dumps(OFFICIAL_SOURCES, ensure_ascii=False), now, now),
    )
    cursor.execute("SELECT id FROM telemetry_protocol_profiles WHERE profile_key = ?", (PROFILE_KEY,))
    profile_row = cursor.fetchone()
    if not profile_row:
        raise RuntimeError("Huawei CE6800 Telemetry profile was not inserted")
    profile_id = str(profile_row[0])

    mappings_json = json.dumps(_starter_mappings(), ensure_ascii=False)
    cursor.execute("SELECT id FROM tenants ORDER BY id")
    for tenant_row in cursor.fetchall():
        tenant_id = str(tenant_row[0])
        template_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"nexora:telemetry:{tenant_id}:{TEMPLATE_KEY}:1",
        ))
        cursor.execute(
            """
            INSERT INTO telemetry_subscription_templates (
                id, tenant_id, profile_id, template_key, version,
                metric_mappings, estimated_series, default_interval_seconds,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?, 100, 10, 'DRAFT', ?, ?)
            ON CONFLICT (tenant_id, template_key, version) DO NOTHING
            """,
            (template_id, tenant_id, profile_id, TEMPLATE_KEY, mappings_json, now, now),
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep protocol/template history intact when rolling back application code.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
