"""Align the published H3C Comware V5 actions with the V5 CLI.

Comware V5 keeps the ``hp_comware`` transport but does not use the V7/V9
BGP command suffixes.  This migration repairs existing system releases; the
static profile catalog covers fresh installations.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone


VERSION = 184
NAME = "h3c_v5_command_bindings"

V5_PROFILE_CODES = ("hp_comware", "h3c_comware_v5")
V5_COMMANDS = {
    "get_arp_table": "display arp all",
    "get_bgp_neighbors": "display bgp peer",
    "get_bgp_routes": "display bgp routing-table",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def _new_action_id(release_id: str, action_code: str) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"nexora:m0184:{release_id}:{action_code}",
    ))


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    try:
        cursor.execute("SELECT 1 FROM platform_profiles LIMIT 1")
        cursor.execute("SELECT 1 FROM platform_releases LIMIT 1")
        cursor.execute("SELECT 1 FROM platform_release_actions LIMIT 1")
    except Exception:
        return

    now = _now()
    for profile_code in V5_PROFILE_CODES:
        releases = cursor.execute(
            """SELECT p.id, r.id
               FROM platform_profiles p
               JOIN platform_releases r ON r.id = p.current_release_id
               WHERE p.platform_code = ? AND p.source = 'SYSTEM'
                 AND p.tenant_id IS NULL AND r.status = 'PUBLISHED'""",
            (profile_code,),
        ).fetchall()
        for profile_id, release_id in releases:
            del profile_id
            release_id = str(release_id)
            for action_code, command in V5_COMMANDS.items():
                existing = cursor.execute(
                    """SELECT id FROM platform_release_actions
                       WHERE release_id = ? AND action_code = ?""",
                    (release_id, action_code),
                ).fetchone()
                if existing:
                    cursor.execute(
                        """UPDATE platform_release_actions
                           SET command = ?, parser_template_version_id = NULL,
                               command_checksum = ?, updated_at = ?
                           WHERE id = ?""",
                        (command, _checksum(command), now, existing[0]),
                    )
                else:
                    cursor.execute(
                        """INSERT INTO platform_release_actions (
                             id, release_id, action_code, command,
                             parser_template_version_id, field_contract_json,
                             command_checksum, created_at, updated_at
                           ) VALUES (?, ?, ?, ?, NULL, '{}', ?, ?, ?)""",
                        (
                            _new_action_id(release_id, action_code),
                            release_id,
                            action_code,
                            command,
                            _checksum(command),
                            now,
                            now,
                        ),
                    )
            _refresh_release_checksum(cursor, release_id, now)


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
