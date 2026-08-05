"""Bind the exact Comware BGP ``ipv4 unicast`` parser to the registry action."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


VERSION = 97
NAME = "bind_h3c_bgp_textfsm_alias"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upgrade(cursor, use_pg: bool) -> None:
    now = _now()
    releases = cursor.execute(
        """SELECT r.id
           FROM platform_releases r
           JOIN platform_profiles p ON p.id = r.profile_id
           WHERE p.source = 'SYSTEM'
             AND p.parser_platform = 'hp_comware'
             AND r.status IN ('PUBLISHED', 'DEPRECATED')"""
    ).fetchall()
    parser_version = cursor.execute(
        """SELECT v.id
           FROM parser_template_versions v
           JOIN parser_templates t ON t.id = v.template_id
           WHERE t.source = 'SYSTEM'
             AND t.platform_code = 'hp_comware'
             AND lower(t.source_filename) = 'hp_comware_display_bgp_peer_ipv4_unicast.textfsm'
             AND v.status = 'PUBLISHED'
           ORDER BY v.version_number DESC, v.id
           LIMIT 1"""
    ).fetchone()
    if not parser_version:
        return

    for release_row in releases:
        release_id = release_row[0]
        cursor.execute(
            """UPDATE platform_release_actions
               SET parser_template_version_id = ?, updated_at = ?
               WHERE release_id = ?
                 AND action_code = 'get_bgp_neighbors'
                 AND parser_template_version_id IS NULL""",
            (parser_version[0], now, release_id),
        )
        actions = [
            dict(row)
            for row in cursor.execute(
                """SELECT action_code, command, parser_template_version_id, field_contract_json
                   FROM platform_release_actions
                   WHERE release_id = ?
                   ORDER BY action_code""",
                (release_id,),
            ).fetchall()
        ]
        cursor.execute(
            "UPDATE platform_releases SET checksum = ?, updated_at = ? WHERE id = ?",
            (_checksum(actions), now, release_id),
        )
