"""Seed the Raisecom ROS platform profile and its reviewed read-only actions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


VERSION = 151
NAME = "raisecom_ros_platform"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upgrade(cursor, use_pg: bool) -> None:
    # Reuse the idempotent profile/template repair path so existing installs
    # receive the new SYSTEM profile just like fresh installs do.
    from database.migrations.m0101_split_platform_profiles import upgrade as refresh_profiles

    refresh_profiles(cursor, use_pg)

    profile = cursor.execute(
        "SELECT id FROM platform_profiles WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_code = ?",
        ("raisecom_ros",),
    ).fetchone()
    if not profile:
        return

    now = _now()
    profile_id = str(profile[0])
    patterns = (
        "Raisecom Operating System Software",
        "Product Name: ISCOM S5600-28C-EI",
        "ROS Version: ROS_5.2.1_20200428",
    )
    for rule_order, pattern in enumerate(patterns, start=1):
        rule_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:identification:raisecom_ros:{pattern}"))
        cursor.execute(
            """INSERT INTO platform_identification_rules
               (id, platform_profile_id, command, match_type, pattern,
                logic_group, rule_order, confidence, negate, enabled, created_at)
               VALUES (?, ?, 'show version', 'contains', ?, 'ANY', ?, 0.95, 0, 1, ?)
               ON CONFLICT(id) DO UPDATE SET
                 platform_profile_id = excluded.platform_profile_id,
                 command = excluded.command,
                 pattern = excluded.pattern,
                 logic_group = excluded.logic_group,
                 rule_order = excluded.rule_order,
                 confidence = excluded.confidence,
                 enabled = excluded.enabled""",
            (rule_id, profile_id, pattern, rule_order, now),
        )
