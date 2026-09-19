"""Align Cisco BGP neighbor actions with the operational query contract."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


VERSION = 84
NAME = "repair_cisco_bgp_neighbor_commands"


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def upgrade(cursor, use_pg: bool) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    replacements = {
        "get_bgp_neighbors": "show ip bgp summary",
        "get_bgp_neighbors_vrf": "show ip bgp vrf {{vrf}} summary",
    }
    for action_code, command in replacements.items():
        cursor.execute(
            """UPDATE platform_release_actions
               SET command = ?, command_checksum = ?, updated_at = ?
               WHERE action_code = ?
                 AND release_id IN (
                     SELECT r.id FROM platform_releases r
                     JOIN platform_profiles p ON p.id = r.profile_id
                     WHERE p.source = 'SYSTEM' AND p.parser_platform = 'cisco_ios'
                 )""",
            (command, _checksum(command), now, action_code),
        )
    rows = cursor.execute(
        """SELECT r.id FROM platform_releases r
           JOIN platform_profiles p ON p.id = r.profile_id
           WHERE p.source = 'SYSTEM' AND p.parser_platform = 'cisco_ios'"""
    ).fetchall()
    for row in rows:
        release_id = row[0]
        actions = [
            dict(item) for item in cursor.execute(
                """SELECT action_code, command, parser_template_version_id, field_contract_json
                   FROM platform_release_actions WHERE release_id = ? ORDER BY action_code""",
                (release_id,),
            ).fetchall()
        ]
        encoded = json.dumps(actions, ensure_ascii=False, sort_keys=True)
        cursor.execute("UPDATE platform_releases SET checksum = ?, updated_at = ? WHERE id = ?", (_checksum(encoded), now, release_id))
