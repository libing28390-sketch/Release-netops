"""Repair missing published aggregation actions after partial registry upgrades.

Some existing databases completed the platform split with an action row for
``hp_comware`` but no row for the canonical ``h3c_comware`` profile. The
collector then correctly reported ``unsupported_by_platform`` because the
published release had no ``get_link_aggregation`` mapping. This migration is
additive and idempotent: it repairs only SYSTEM releases and preserves any
tenant-owned or user-authored action rows.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone


VERSION = 128
NAME = "repair_h3c_aggregation_actions"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _table_columns(cursor, table_name: str) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table_name,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _parser_version_id(cursor, profile_id: str, parser_platform: str, command: str) -> str | None:
    """Find the latest published SYSTEM parser for the exact command."""
    version_columns = _table_columns(cursor, "parser_template_versions")
    template_columns = _table_columns(cursor, "parser_templates")
    if not {"id", "template_id", "status", "version_number"}.issubset(version_columns) or not {
        "id", "command", "source", "platform_profile_id",
    }.issubset(template_columns):
        return None
    rows = cursor.execute(
        """SELECT v.id, t.command
           FROM parser_template_versions v
           JOIN parser_templates t ON t.id = v.template_id
           WHERE v.status = 'PUBLISHED'
             AND t.source = 'SYSTEM'
             AND t.platform_profile_id = ?
           ORDER BY v.version_number DESC, v.id""",
        (profile_id,),
    ).fetchall()
    expected = " ".join(str(command or "").replace("-", " ").lower().split())
    for row in rows:
        actual = " ".join(str(row[1] or "").replace("-", " ").lower().split())
        if actual == expected:
            return str(row[0])
    return None


def _fresh_action_id(cursor, release_id: str, action_code: str) -> str:
    candidate = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:{release_id}:{action_code}"))
    while cursor.execute("SELECT 1 FROM platform_release_actions WHERE id = ?", (candidate,)).fetchone():
        candidate = str(uuid.uuid4())
    return candidate


def _ensure_action_definition(cursor, definition: dict, now: str) -> None:
    cursor.execute(
        """INSERT INTO action_definitions (
             action_code, name_zh, name_en, purpose, risk_level,
             device_types_json, required_fields_json, optional_fields_json,
             field_types_json, max_output_bytes, max_records, timeout_seconds,
             sensitive_level, consumers_json, read_only, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
           ON CONFLICT(action_code) DO UPDATE SET
             name_zh = excluded.name_zh,
             name_en = excluded.name_en,
             purpose = excluded.purpose,
             risk_level = excluded.risk_level,
             optional_fields_json = excluded.optional_fields_json,
             field_types_json = excluded.field_types_json,
             max_records = excluded.max_records,
             timeout_seconds = excluded.timeout_seconds,
             consumers_json = excluded.consumers_json""",
        (
            definition["action_code"],
            definition.get("name_zh", ""),
            definition.get("name_en", ""),
            definition.get("purpose", ""),
            definition.get("risk", "low"),
            _json(definition.get("device_types") or ["router", "switch", "firewall"]),
            _json(definition.get("fields") or []),
            _json(definition.get("optional_fields") or []),
            _json(definition.get("field_types") or {}),
            2_000_000,
            int(definition.get("max_records") or 1000),
            int(definition.get("timeout_seconds") or 30),
            "sensitive" if definition.get("risk") == "sensitive" else "normal",
            _json(definition.get("consumers") or []),
            now,
        ),
    )


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg  # The migration adapter accepts portable '?' placeholders.
    required_tables = {
        "platform_profiles": {"id", "tenant_id", "source", "platform_code", "parser_platform", "current_release_id"},
        "platform_releases": {"id", "status", "checksum", "updated_at"},
        "platform_release_actions": {"id", "release_id", "action_code"},
        "action_definitions": {"action_code"},
    }
    if any(not columns.issubset(_table_columns(cursor, table)) for table, columns in required_tables.items()):
        return

    from services.platform_registry_service import (
        SYSTEM_PROFILES,
        get_profile_action_commands,
        iter_action_definitions,
    )

    definition = next(
        (item for item in iter_action_definitions() if item.get("action_code") == "get_link_aggregation"),
        None,
    )
    if not definition:
        return
    now = _now()
    _ensure_action_definition(cursor, definition, now)

    for profile in SYSTEM_PROFILES:
        profile_code = str(profile.get("platform_code") or "").strip()
        command = get_profile_action_commands(profile).get("get_link_aggregation")
        if not profile_code or not command:
            continue
        release = cursor.execute(
            """SELECT p.id, p.parser_platform, p.current_release_id, r.id, r.status
               FROM platform_profiles p
               JOIN platform_releases r ON r.id = p.current_release_id
               WHERE p.tenant_id IS NULL AND p.source = 'SYSTEM'
                 AND p.platform_code = ?""",
            (profile_code,),
        ).fetchone()
        if not release or str(release[4] or "") != "PUBLISHED":
            continue
        profile_id, parser_platform, release_id = str(release[0]), str(release[1] or ""), str(release[2])
        parser_version_id = _parser_version_id(cursor, profile_id, parser_platform, command)
        checksum = _checksum(command)
        existing = cursor.execute(
            "SELECT id, parser_template_version_id FROM platform_release_actions WHERE release_id = ? AND action_code = ?",
            (release_id, "get_link_aggregation"),
        ).fetchone()
        if existing:
            cursor.execute(
                """UPDATE platform_release_actions
                   SET command = ?, parser_template_version_id = COALESCE(?, parser_template_version_id),
                       command_checksum = ?, updated_at = ?
                   WHERE id = ?""",
                (command, parser_version_id, checksum, now, existing[0]),
            )
        else:
            cursor.execute(
                """INSERT INTO platform_release_actions (
                     id, release_id, action_code, command, parser_template_version_id,
                     field_contract_json, command_checksum, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?)""",
                (
                    _fresh_action_id(cursor, release_id, "get_link_aggregation"),
                    release_id,
                    "get_link_aggregation",
                    command,
                    parser_version_id,
                    checksum,
                    now,
                    now,
                ),
            )
        actions = [
            dict(row)
            for row in cursor.execute(
                """SELECT action_code, command, parser_template_version_id, field_contract_json
                   FROM platform_release_actions WHERE release_id = ? ORDER BY action_code""",
                (release_id,),
            ).fetchall()
        ]
        cursor.execute(
            "UPDATE platform_releases SET checksum = ?, updated_at = ? WHERE id = ?",
            (_checksum(_json(actions)), now, release_id),
        )


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
