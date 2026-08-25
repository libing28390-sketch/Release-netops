"""Complete H3C operational action bindings from verified Comware output.

The V7 device already had several parser files, but the published release did
not expose the corresponding actions to the operational collector.  This
migration adds the missing action definitions, imports the two V7 grammars
whose command names must be exact, and binds every available H3C V5/V7/V9
parser by concrete Profile + command.  Unsupported combinations remain
explicitly unbound and therefore fail closed at execution time.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


VERSION = 171
NAME = "h3c_operational_action_bindings"

H3C_PROFILE_CODES = ("hp_comware", "h3c_comware", "h3c_comware9")
NEW_ACTION_CODES = (
    "get_link_aggregation",
    "get_temperature",
    "get_bfd_sessions",
    "get_ntp_status",
    "get_logbuffer",
    "get_interface_description",
    "get_irf",
    "get_uptime",
)
NEW_TEMPLATE_FILENAMES = {
    "h3c_comware_v7_display_link_aggregation_verbose.textfsm",
    "h3c_comware_v7_display_interface_brief_description.textfsm",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _checksum(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _template_code(filename: str) -> str:
    stem = Path(filename).stem
    return "".join(char if char.isalnum() or char == "_" else "_" for char in stem.upper())[:64]


def _refresh_release_checksum(cursor, release_id: str, now: str) -> None:
    actions = [
        dict(row)
        for row in cursor.execute(
            """SELECT action_code, command, parser_template_version_id,
                      field_contract_json
               FROM platform_release_actions
               WHERE release_id = ? ORDER BY action_code""",
            (release_id,),
        ).fetchall()
    ]
    cursor.execute(
        "UPDATE platform_releases SET checksum = ?, updated_at = ? WHERE id = ?",
        (_checksum(actions), now, release_id),
    )


def _ensure_action_definitions(cursor, now: str) -> None:
    from services.platform_registry_service import iter_action_definitions

    wanted = set(NEW_ACTION_CODES)
    for definition in iter_action_definitions():
        if definition.get("action_code") not in wanted:
            continue
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
                 device_types_json = excluded.device_types_json,
                 required_fields_json = excluded.required_fields_json,
                 optional_fields_json = excluded.optional_fields_json,
                 field_types_json = excluded.field_types_json,
                 max_records = excluded.max_records,
                 timeout_seconds = excluded.timeout_seconds,
                 sensitive_level = excluded.sensitive_level,
                 consumers_json = excluded.consumers_json""",
            (
                definition["action_code"],
                definition.get("name_zh", ""),
                definition.get("name_en", ""),
                definition.get("purpose", ""),
                definition.get("risk", "low"),
                _json(definition.get("device_types") or []),
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


def _register_new_templates(cursor, now: str) -> dict[str, str]:
    profile_row = cursor.execute(
        """SELECT id FROM platform_profiles
           WHERE platform_code = 'h3c_comware'
             AND source = 'SYSTEM' AND tenant_id IS NULL
           LIMIT 1"""
    ).fetchone()
    if not profile_row:
        return {}
    profile_id = str(profile_row[0])
    root = Path(__file__).resolve().parents[3] / "data" / "textfsm_templates"
    if not root.exists():
        return {}
    from core.textfsm import _canonical_template_command

    versions: dict[str, str] = {}
    for path in sorted(root.glob("*.textfsm"), key=lambda item: item.name.lower()):
        if path.name not in NEW_TEMPLATE_FILENAMES:
            continue
        parser_platform = "h3c_comware"
        suffix = path.stem.removeprefix("h3c_comware_v7_").replace("_", " ")
        command = _canonical_template_command(parser_platform, suffix)
        template_code = _template_code(path.name)
        content = path.read_text(encoding="utf-8")
        template_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template:{path.name}"))
        version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template-version:{path.name}:1"))
        existing = cursor.execute(
            """SELECT id FROM parser_templates
               WHERE tenant_id IS NULL AND source = 'SYSTEM'
                 AND platform_profile_id = ? AND source_filename = ?
               LIMIT 1""",
            (profile_id, path.name),
        ).fetchone()
        if existing:
            template_id = str(existing[0])
            cursor.execute(
                """UPDATE parser_templates
                   SET platform_code = ?, template_code = ?, command = ?,
                       name = ?, updated_at = ?
                   WHERE id = ?""",
                (parser_platform, template_code, command, path.stem, now, template_id),
            )
        else:
            cursor.execute(
                """INSERT INTO parser_templates (
                     id, tenant_id, platform_profile_id, platform_code, template_code,
                     source_filename, command, name, source, status, created_by,
                     created_at, updated_at, lock_version
                   ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'SYSTEM', 'ACTIVE',
                             'system', ?, ?, 1)""",
                (
                    template_id,
                    profile_id,
                    parser_platform,
                    template_code,
                    path.name,
                    command,
                    path.stem,
                    now,
                    now,
                ),
            )
        existing_version = cursor.execute(
            """SELECT id FROM parser_template_versions
               WHERE template_id = ? AND version_number = 1""",
            (template_id,),
        ).fetchone()
        if existing_version:
            version_id = str(existing_version[0])
            cursor.execute(
                """UPDATE parser_template_versions
                   SET content = ?, checksum = ?, status = 'PUBLISHED', updated_at = ?
                   WHERE id = ?""",
                (content, _checksum(content), now, version_id),
            )
        else:
            cursor.execute(
                """INSERT INTO parser_template_versions (
                     id, template_id, version_number, status, content, checksum,
                     field_contract_json, test_summary_json, created_by, created_at, updated_at
                   ) VALUES (?, ?, 1, 'PUBLISHED', ?, ?, '{}', '{\"imported\":true}',
                             'system', ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     template_id = excluded.template_id,
                     content = excluded.content,
                     checksum = excluded.checksum,
                     status = 'PUBLISHED',
                     updated_at = excluded.updated_at""",
                (version_id, template_id, content, _checksum(content), now, now),
            )
        versions[_normalize(command)] = version_id
    return versions


def _parser_version_id(cursor, profile_id: str, command: str) -> str | None:
    rows = cursor.execute(
        """SELECT v.id, t.command
           FROM parser_template_versions v
           JOIN parser_templates t ON t.id = v.template_id
           WHERE v.status = 'PUBLISHED'
             AND t.source = 'SYSTEM' AND t.tenant_id IS NULL
             AND t.platform_profile_id = ?
           ORDER BY v.version_number DESC, v.id""",
        (profile_id,),
    ).fetchall()
    expected = _normalize(command)
    for row in rows:
        if _normalize(row[1]) == expected:
            return str(row[0])
    return None


def _fresh_action_id(cursor, release_id: str, action_code: str) -> str:
    candidate = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:{release_id}:{action_code}"))
    while cursor.execute("SELECT 1 FROM platform_release_actions WHERE id = ?", (candidate,)).fetchone():
        candidate = str(uuid.uuid4())
    return candidate


def _ensure_release_actions(cursor, now: str) -> None:
    from services.platform_registry_service import SYSTEM_PROFILES, get_profile_action_commands

    profile_defs = {
        str(item["platform_code"]): item
        for item in SYSTEM_PROFILES
        if str(item["platform_code"]) in H3C_PROFILE_CODES
    }
    for profile_code, profile in profile_defs.items():
        release = cursor.execute(
            """SELECT p.id, p.parser_platform, r.id, r.status
               FROM platform_profiles p
               JOIN platform_releases r ON r.id = p.current_release_id
               WHERE p.platform_code = ? AND p.source = 'SYSTEM'
                 AND p.tenant_id IS NULL""",
            (profile_code,),
        ).fetchone()
        if not release or str(release[3] or "") != "PUBLISHED":
            continue
        profile_id, _parser_platform, release_id = str(release[0]), str(release[1] or ""), str(release[2])
        commands = get_profile_action_commands(profile)
        changed = False
        for action_code in NEW_ACTION_CODES:
            command = commands.get(action_code)
            if not command:
                continue
            parser_version_id = _parser_version_id(cursor, profile_id, command)
            existing = cursor.execute(
                """SELECT id, parser_template_version_id
                   FROM platform_release_actions
                   WHERE release_id = ? AND action_code = ?""",
                (release_id, action_code),
            ).fetchone()
            if existing:
                selected_parser = parser_version_id or existing[1]
                cursor.execute(
                    """UPDATE platform_release_actions
                       SET command = ?, parser_template_version_id = ?,
                           command_checksum = ?, updated_at = ?
                       WHERE id = ?""",
                    (command, selected_parser, _checksum(command), now, existing[0]),
                )
            else:
                cursor.execute(
                    """INSERT INTO platform_release_actions (
                         id, release_id, action_code, command, parser_template_version_id,
                         field_contract_json, command_checksum, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?)""",
                    (
                        _fresh_action_id(cursor, release_id, action_code),
                        release_id,
                        action_code,
                        command,
                        parser_version_id,
                        _checksum(command),
                        now,
                        now,
                    ),
                )
            changed = True
        if changed:
            _refresh_release_checksum(cursor, release_id, now)


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    try:
        cursor.execute("SELECT 1 FROM platform_profiles LIMIT 1")
        cursor.execute("SELECT 1 FROM platform_releases LIMIT 1")
        cursor.execute("SELECT 1 FROM platform_release_actions LIMIT 1")
        cursor.execute("SELECT 1 FROM action_definitions LIMIT 1")
    except Exception:
        return

    now = _now()
    _ensure_action_definitions(cursor, now)
    _register_new_templates(cursor, now)
    _ensure_release_actions(cursor, now)


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
