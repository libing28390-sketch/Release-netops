"""Seed the first reviewed domestic-platform identification keywords."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


VERSION = 88
NAME = "seed_domestic_platform_identification_rules"


RULES: dict[str, tuple[str, ...]] = {
    "zte_5900_v6": ("ZXR10 5960", "5900 V6.", "5960X_"),
    "zte_zsrv2_v3": ("ZXR10 1800-2S", "ZSRV2 V3."),
    "ruijie_s6k_rgos12": ("S6231-48XS8CQ", "S6K-A_RGOS 12."),
    "ruijie_eg_rgos11": ("EG3000UE", "EG_RGOS 11."),
    "dptech_fw_s211": ("FW1000-TS-C", "Software Release S211"),
    "maipu_s3330_v9": ("MyPower S3330", "Software Version 9.7."),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upgrade(cursor, use_pg: bool) -> None:
    now = _now()
    for platform_code, patterns in RULES.items():
        profile = cursor.execute(
            "SELECT id FROM platform_profiles WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_code = ?",
            (platform_code,),
        ).fetchone()
        if not profile:
            continue
        profile_id = profile[0]
        for index, pattern in enumerate(patterns, start=1):
            rule_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:identification:{platform_code}:{pattern}"))
            cursor.execute(
                """INSERT INTO platform_identification_rules
                   (id, platform_profile_id, command, match_type, pattern,
                    logic_group, rule_order, confidence, negate, enabled, created_at)
                   VALUES (?, ?, 'show version', 'contains', ?, 'ANY', ?, 0.95, 0, 1, ?)
                   ON CONFLICT(id) DO UPDATE SET pattern = excluded.pattern,
                     logic_group = excluded.logic_group, rule_order = excluded.rule_order,
                     confidence = excluded.confidence, enabled = excluded.enabled""",
                (rule_id, profile_id, pattern, index, now),
            )
