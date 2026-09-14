"""Repair SYSTEM action seeds after the P0 parser-platform boundary fix."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone


VERSION = 73
NAME = "repair_platform_registry_command_seeds"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _template_version_id(cursor, parser_platform: str, command: str, profile_code: str = "") -> str | None:
    expected_names = {
        f"{parser_platform}_{command.replace(' ', '_')}.textfsm".lower(),
    }
    if profile_code:
        expected_names.add(f"{profile_code}_{command.replace(' ', '_')}.textfsm".lower())
    rows = cursor.execute(
        """SELECT v.id, t.source_filename
           FROM parser_template_versions v
           JOIN parser_templates t ON t.id = v.template_id
           WHERE t.platform_code = ? AND t.source = 'SYSTEM'
           ORDER BY v.version_number DESC""",
        (parser_platform,),
    ).fetchall()
    for row in rows:
        if str(row[1] or "").lower() in expected_names:
            return str(row[0])
    return None


def upgrade(cursor, use_pg: bool) -> None:
    from services.platform_registry_service import get_profile_action_commands, iter_action_definitions

    now = _now()
    for item in iter_action_definitions():
        dump = lambda value: json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)
        cursor.execute(
            """INSERT INTO action_definitions
               (action_code, name_zh, name_en, purpose, risk_level, device_types_json,
                required_fields_json, optional_fields_json, field_types_json,
                max_output_bytes, max_records, timeout_seconds, sensitive_level,
                consumers_json, read_only, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(action_code) DO UPDATE SET
                 device_types_json=excluded.device_types_json,
                 required_fields_json=excluded.required_fields_json,
                 optional_fields_json=excluded.optional_fields_json,
                 field_types_json=excluded.field_types_json,
                 max_records=excluded.max_records,
                 timeout_seconds=excluded.timeout_seconds,
                 consumers_json=excluded.consumers_json""",
            (item["action_code"], item["name_zh"], item["name_en"], item["purpose"], item["risk"],
             dump(item.get("device_types")), dump(item.get("fields")), dump(item.get("optional_fields")),
             dump(item.get("field_types")), 2_000_000, int(item.get("max_records") or 1000),
             int(item.get("timeout_seconds") or 30), "sensitive" if item["risk"] == "sensitive" else "normal",
             dump(item.get("consumers")), now),
        )
    releases = cursor.execute(
        """SELECT r.id, p.platform_code, p.parser_platform
           FROM platform_releases r
           JOIN platform_profiles p ON p.id = r.profile_id
           WHERE p.source = 'SYSTEM' AND r.status IN ('PUBLISHED', 'DEPRECATED')"""
    ).fetchall()

    for release_id, profile_code, parser_platform in releases:
        commands = get_profile_action_commands({"platform_code": profile_code, "parser_platform": parser_platform})
        for action_code, command in commands.items():
            existing = cursor.execute(
                "SELECT id, parser_template_version_id FROM platform_release_actions WHERE release_id = ? AND action_code = ?",
                (release_id, action_code),
            ).fetchone()
            template_version_id = _template_version_id(cursor, str(parser_platform), command, str(profile_code))
            if existing:
                bound_template_id = template_version_id or existing[1]
                cursor.execute(
                    """UPDATE platform_release_actions
                       SET command = ?, parser_template_version_id = ?, command_checksum = ?, updated_at = ?
                       WHERE id = ?""",
                    (command, bound_template_id, _checksum(command), now, existing[0]),
                )
            else:
                action_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:{release_id}:{action_code}"))
                cursor.execute(
                    """INSERT INTO platform_release_actions
                       (id, release_id, action_code, command, parser_template_version_id,
                        field_contract_json, command_checksum, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?)""",
                    (action_id, release_id, action_code, command, template_version_id, _checksum(command), now, now),
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
            (_checksum(actions), now, release_id),
        )
