"""Seed the Raisecom ROS platform profile and its reviewed read-only actions."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path


VERSION = 151
NAME = "raisecom_ros_platform"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _ensure_raisecom_show_version_template(
    cursor,
    profile_id: str,
    now: str,
) -> str | None:
    """Reconcile only Raisecom's template by its scoped business key."""

    template_path = (
        Path(__file__).resolve().parents[3]
        / "data"
        / "textfsm_templates"
        / "raisecom_ros_show_version.textfsm"
    )
    if not template_path.exists():
        return None

    content = template_path.read_text(encoding="utf-8")
    template_code = "RAISECOM_ROS_SHOW_VERSION"
    source_filename = template_path.name
    row = cursor.execute(
        """
        SELECT id
        FROM parser_templates
        WHERE tenant_id IS NULL
          AND platform_code = ?
          AND platform_profile_id = ?
          AND template_code = ?
        """,
        ("raisecom_ros", profile_id, template_code),
    ).fetchone()

    if row:
        template_id = str(row[0])
        cursor.execute(
            """
            UPDATE parser_templates
            SET source_filename = ?,
                command = ?,
                name = ?,
                source = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                source_filename,
                "show version",
                "Raisecom ROS show version",
                "SYSTEM",
                "ACTIVE",
                now,
                template_id,
            ),
        )
    else:
        template_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"nexora:system-template:{source_filename}",
            )
        )
        cursor.execute(
            """
            INSERT INTO parser_templates (
                id, tenant_id, platform_profile_id, platform_code,
                template_code, source_filename, command, name, source,
                status, created_by, created_at, updated_at, lock_version
            )
            VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_id,
                profile_id,
                "raisecom_ros",
                template_code,
                source_filename,
                "show version",
                "Raisecom ROS show version",
                "SYSTEM",
                "ACTIVE",
                "system",
                now,
                now,
                1,
            ),
        )

    checksum = _checksum(content)
    version_row = cursor.execute(
        """
        SELECT id
        FROM parser_template_versions
        WHERE template_id = ?
          AND version_number = ?
        """,
        (template_id, 1),
    ).fetchone()

    if version_row:
        version_id = str(version_row[0])
        cursor.execute(
            """
            UPDATE parser_template_versions
            SET status = ?, content = ?, checksum = ?, updated_at = ?
            WHERE id = ?
            """,
            ("PUBLISHED", content, checksum, now, version_id),
        )
    else:
        version_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"nexora:system-template-version:{source_filename}:1",
            )
        )
        cursor.execute(
            """
            INSERT INTO parser_template_versions (
                id, template_id, version_number, status, content, checksum,
                field_contract_json, test_summary_json, created_by, created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                template_id,
                1,
                "PUBLISHED",
                content,
                checksum,
                "{}",
                '{"imported": true}',
                "system",
                now,
                now,
            ),
        )

    return version_id


def upgrade(cursor, use_pg: bool) -> None:
    # Reuse only the profile/release/action seed. Re-running the historical
    # full template refresh can collide with scoped unique indexes on existing
    # templates unrelated to Raisecom.
    del use_pg
    # Migration 151 runs before the startup-config feature migration.  Seed
    # the catalog first so the FK on platform_release_actions is satisfied for
    # databases upgraded from a version that predates get_startup_config.
    from database.migrations.m0072_platform_registry_p0 import (
        _seed_action_definitions,
    )
    from database.migrations.m0101_split_platform_profiles import _ensure_system_profiles

    now = _now()
    _seed_action_definitions(cursor)
    profile_ids = _ensure_system_profiles(cursor, now)
    profile_id = profile_ids.get("raisecom_ros")
    if not profile_id:
        return

    parser_template_version_id = _ensure_raisecom_show_version_template(
        cursor,
        str(profile_id),
        now,
    )
    if parser_template_version_id:
        release_row = cursor.execute(
            "SELECT id FROM platform_releases WHERE profile_id = ? AND release_number = ?",
            (str(profile_id), 1),
        ).fetchone()
        if not release_row:
            raise RuntimeError("Raisecom system release was not materialized")
        cursor.execute(
            """
            UPDATE platform_release_actions
            SET parser_template_version_id = ?, updated_at = ?
            WHERE release_id = ?
              AND action_code = ?
            """,
            (
                parser_template_version_id,
                now,
                str(release_row[0]),
                "get_version",
            ),
        )

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
