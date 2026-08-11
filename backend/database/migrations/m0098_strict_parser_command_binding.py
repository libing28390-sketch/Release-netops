"""Make parser command identity explicit and repair the H3C BGP binding.

The registry previously treated a template filename as an optional hint and
the H3C BGP compatibility migration deliberately bound ``ipv4 unicast`` to a
template without the suffix.  This migration stores the command identity on
each imported SYSTEM template and points the H3C action at the exact grammar.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


VERSION = 98
NAME = "strict_parser_command_binding"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]).lower() for row in rows}
    return {str(row[1]).lower() for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(cursor, table: str, column: str, definition: str, use_pg: bool) -> None:
    if column not in _columns(cursor, table, use_pg):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _derive_template_command(platform_code: str, source_filename: str) -> str:
    """Use the shared canonical filename map only for migration backfill."""
    from services.platform_registry_service import derive_template_command

    return derive_template_command(platform_code, source_filename)


def _ensure_h3c_unicast_template(cursor, now: str) -> str | None:
    path = Path(__file__).resolve().parents[3] / "data" / "textfsm_templates" / "h3c_comware_display_bgp_peer_ipv4_unicast.textfsm"
    if not path.exists():
        return None
    profile = cursor.execute(
        "SELECT id FROM platform_profiles WHERE source = 'SYSTEM' AND parser_platform = 'h3c_comware' ORDER BY id LIMIT 1"
    ).fetchone()
    if not profile:
        return None

    filename = path.name
    template_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template:{filename}"))
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template-version:{filename}:1"))
    content = path.read_text(encoding="utf-8")
    checksum = _checksum(content)
    cursor.execute(
        """INSERT INTO parser_templates
           (id, tenant_id, platform_profile_id, platform_code, template_code,
            source_filename, command, name, source, status, created_by,
            created_at, updated_at, lock_version)
           VALUES (?, NULL, ?, 'h3c_comware', ?, ?, ?, ?, 'SYSTEM', 'ACTIVE',
                   'system', ?, ?, 1)
           ON CONFLICT(id) DO UPDATE SET
             platform_profile_id=excluded.platform_profile_id,
             platform_code=excluded.platform_code,
             source_filename=excluded.source_filename,
             command=excluded.command,
             name=excluded.name,
             updated_at=excluded.updated_at""",
        (
            template_id,
            profile[0],
            "H3C_COMWARE_DISPLAY_BGP_PEER_IPV4_UNICAST",
            filename,
            "display bgp peer ipv4 unicast",
            path.stem,
            now,
            now,
        ),
    )
    cursor.execute(
        """INSERT INTO parser_template_versions
           (id, template_id, version_number, status, content, checksum,
            field_contract_json, test_summary_json, created_by, created_at, updated_at)
           VALUES (?, ?, 1, 'PUBLISHED', ?, ?, '{}', '{"imported":true}',
                   'system', ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             content=excluded.content, checksum=excluded.checksum,
             updated_at=excluded.updated_at""",
        (version_id, template_id, content, checksum, now, now),
    )
    return version_id


def _refresh_release_checksum(cursor, release_id: str, now: str) -> None:
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


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_column(cursor, "parser_templates", "command", "TEXT NOT NULL DEFAULT ''", use_pg)
    now = _now()

    # Backfill only immutable SYSTEM imports.  Tenant templates must declare
    # their command explicitly when they are bound to a release.
    rows = cursor.execute(
        "SELECT id, platform_code, source_filename FROM parser_templates WHERE source = 'SYSTEM'"
    ).fetchall()
    for row in rows:
        command = _derive_template_command(row[1], row[2])
        if command:
            cursor.execute(
                "UPDATE parser_templates SET command = ?, updated_at = ? WHERE id = ?",
                (command, now, row[0]),
            )

    unicast_version_id = _ensure_h3c_unicast_template(cursor, now)
    if not unicast_version_id:
        return

    releases = cursor.execute(
        """SELECT r.id
           FROM platform_releases r
           JOIN platform_profiles p ON p.id = r.profile_id
           WHERE p.source = 'SYSTEM' AND p.parser_platform = 'h3c_comware'"""
    ).fetchall()
    for release_row in releases:
        release_id = release_row[0]
        cursor.execute(
            """UPDATE platform_release_actions
               SET parser_template_version_id = ?, updated_at = ?
               WHERE release_id = ?
                 AND action_code = 'get_bgp_neighbors'
                 AND lower(trim(command)) = 'display bgp peer ipv4 unicast'""",
            (unicast_version_id, now, release_id),
        )
        _refresh_release_checksum(cursor, release_id, now)
