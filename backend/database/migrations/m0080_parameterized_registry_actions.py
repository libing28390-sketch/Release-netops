"""Seed explicit VRF action variants into existing SYSTEM releases."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone


VERSION = 80
NAME = "parameterized_registry_actions"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _dump(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _checksum(value) -> str:
    raw = value if isinstance(value, str) else _dump(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upgrade(cursor, use_pg: bool) -> None:
    from services.platform_registry_service import PLATFORM_ACTION_COMMANDS, iter_action_definitions

    now = _now()
    for item in iter_action_definitions():
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
             _dump(item.get("device_types")), _dump(item.get("fields")), _dump(item.get("optional_fields")),
             _dump(item.get("field_types")), 2_000_000, int(item.get("max_records") or 1000),
             int(item.get("timeout_seconds") or 30), "sensitive" if item["risk"] == "sensitive" else "normal",
             _dump(item.get("consumers")), now),
        )

    releases = cursor.execute(
        """SELECT r.id, p.parser_platform
           FROM platform_releases r
           JOIN platform_profiles p ON p.id = r.profile_id
           WHERE p.source = 'SYSTEM' AND r.status IN ('PUBLISHED', 'DEPRECATED')"""
    ).fetchall()
    for release_id, parser_platform in releases:
        for action_code, command in PLATFORM_ACTION_COMMANDS.get(str(parser_platform), {}).items():
            exists = cursor.execute(
                "SELECT id FROM platform_release_actions WHERE release_id = ? AND action_code = ?",
                (release_id, action_code),
            ).fetchone()
            if exists:
                continue
            cursor.execute(
                """INSERT INTO platform_release_actions
                   (id, release_id, action_code, command, field_contract_json,
                    command_checksum, created_at, updated_at)
                   VALUES (?, ?, ?, ?, '{}', ?, ?, ?)""",
                (str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:{release_id}:{action_code}")), release_id,
                 action_code, command, _checksum(command), now, now),
            )
        actions = [
            dict(row) for row in cursor.execute(
                """SELECT action_code, command, parser_template_version_id, field_contract_json
                   FROM platform_release_actions WHERE release_id = ? ORDER BY action_code""",
                (release_id,),
            ).fetchall()
        ]
        cursor.execute(
            "UPDATE platform_releases SET checksum = ?, updated_at = ? WHERE id = ?",
            (_checksum(actions), now, release_id),
        )
