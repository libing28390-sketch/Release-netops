"""Import the verified H3C Comware V9 clock and STP parsers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from .m0100_register_builtin_textfsm_templates import _checksum, _refresh_release_checksum

VERSION = 343
NAME = "h3c_v9_clock_stp_samples"

PROFILE_CODE = "h3c_comware_v9"
PARSER_PLATFORM = "h3c_comware"
TEMPLATES = {
    "h3c_comware_v9_display_clock.textfsm": ("display clock", "get_clock"),
    "h3c_comware_v9_display_stp_brief.textfsm": ("display stp brief", "get_stp"),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _template_code(filename: str) -> str:
    stem = Path(filename).stem
    return "".join(char if char.isalnum() or char == "_" else "_" for char in stem.upper())[:64]


def _profile_id(cursor) -> str | None:
    row = cursor.execute(
        """SELECT id FROM platform_profiles
           WHERE platform_code = ? AND source = 'SYSTEM'
             AND tenant_id IS NULL AND status = 'ACTIVE'
           LIMIT 1""",
        (PROFILE_CODE,),
    ).fetchone()
    return str(row[0]) if row else None


def _register_templates(cursor, profile_id: str, root: Path, now: str) -> dict[str, str]:
    from core.textfsm import _canonical_template_command

    versions: dict[str, str] = {}
    for filename, (command, _action_code) in TEMPLATES.items():
        path = root / filename
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        template_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template:{PROFILE_CODE}:{filename}")
        )
        version_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"nexora:system-template-version:{PROFILE_CODE}:{filename}:1",
            )
        )
        existing = cursor.execute(
            """SELECT id FROM parser_templates
               WHERE tenant_id IS NULL AND source = 'SYSTEM'
                 AND platform_profile_id = ? AND source_filename = ?
               LIMIT 1""",
            (profile_id, filename),
        ).fetchone()
        if existing:
            template_id = str(existing[0])
            cursor.execute(
                """UPDATE parser_templates
                   SET platform_code = ?, template_code = ?, command = ?,
                       name = ?, status = 'ACTIVE', updated_at = ?
                   WHERE id = ?""",
                (
                    PARSER_PLATFORM,
                    _template_code(filename),
                    _canonical_template_command(PARSER_PLATFORM, command),
                    path.stem,
                    now,
                    template_id,
                ),
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
                    PARSER_PLATFORM,
                    _template_code(filename),
                    filename,
                    _canonical_template_command(PARSER_PLATFORM, command),
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
                   ) VALUES (?, ?, 1, 'PUBLISHED', ?, ?, '{}', '{"imported":true}',
                             'system', ?, ?)""",
                (version_id, template_id, content, _checksum(content), now, now),
            )
        versions[command] = version_id
    return versions


def _bind_current_actions(cursor, profile_id: str, versions: dict[str, str], now: str) -> None:
    for command, version_id in versions.items():
        _action_code = next(
            action_code for _filename, (expected_command, action_code) in TEMPLATES.items()
            if expected_command == command
        )
        rows = cursor.execute(
            """SELECT a.id, a.release_id, a.parser_template_version_id,
                      old_t.source, old_t.tenant_id, old_t.source_filename
               FROM platform_profiles p
               JOIN platform_releases r ON r.id = p.current_release_id
               JOIN platform_release_actions a ON a.release_id = r.id
               LEFT JOIN parser_template_versions old_v
                 ON old_v.id = a.parser_template_version_id
               LEFT JOIN parser_templates old_t ON old_t.id = old_v.template_id
               WHERE p.id = ? AND p.source = 'SYSTEM' AND p.tenant_id IS NULL
                 AND p.status = 'ACTIVE' AND r.status = 'PUBLISHED'
                 AND a.action_code = ? AND a.command = ?""",
            (profile_id, _action_code, command),
        ).fetchall()
        for action in rows:
            current_version_id = str(action[2] or "")
            current_is_system = (
                str(action[3] or "") == "SYSTEM"
                and action[4] in (None, "")
            )
            if current_version_id == version_id:
                continue
            if current_version_id and not current_is_system:
                continue
            cursor.execute(
                """UPDATE platform_release_actions
                   SET parser_template_version_id = ?, updated_at = ?
                   WHERE id = ? AND command = ?""",
                (version_id, now, action[0], command),
            )
            if cursor.rowcount:
                _refresh_release_checksum(cursor, str(action[1]), now)


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    try:
        cursor.execute("SELECT 1 FROM parser_templates LIMIT 1")
        cursor.execute("SELECT 1 FROM parser_template_versions LIMIT 1")
        cursor.execute("SELECT 1 FROM platform_profiles LIMIT 1")
        cursor.execute("SELECT 1 FROM platform_releases LIMIT 1")
        cursor.execute("SELECT 1 FROM platform_release_actions LIMIT 1")
    except Exception:
        return

    profile_id = _profile_id(cursor)
    if not profile_id:
        return
    root = Path(__file__).resolve().parents[3] / "data" / "textfsm_templates"
    now = _now()
    versions = _register_templates(cursor, profile_id, root, now)
    _bind_current_actions(cursor, profile_id, versions, now)


def downgrade(cursor, use_pg: bool) -> None:
    # Published parser bindings must remain usable if a release is rolled back.
    del cursor, use_pg
    return None
