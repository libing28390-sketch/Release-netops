"""Repair the H3C Comware V7 BGP VRF route action command.

Release 655x defines IPv4 unicast VRF routes as
``display bgp routing-table ipv4 [unicast] [vpn-instance <name>]``.  Earlier
system V7 releases used the older VPNv4 command order, which is not the
documented syntax for the active S6850/S9850 family.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


VERSION = 339
NAME = "h3c_v7_bgp_vrf_route_command"

OLD_COMMAND = "display bgp vpnv4 vpn-instance {{vrf}} routing-table"
NEW_COMMAND = "display bgp routing-table ipv4 unicast vpn-instance {{vrf}}"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


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


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    try:
        cursor.execute("SELECT 1 FROM platform_profiles LIMIT 1")
        cursor.execute("SELECT 1 FROM platform_releases LIMIT 1")
        cursor.execute("SELECT 1 FROM platform_release_actions LIMIT 1")
    except Exception:
        return

    profiles = cursor.execute(
        """SELECT id FROM platform_profiles
           WHERE platform_code = 'h3c_comware_v7'
             AND source = 'SYSTEM' AND tenant_id IS NULL"""
    ).fetchall()
    if not profiles:
        return

    now = _now()
    for profile in profiles:
        profile_id = str(profile[0])
        releases = cursor.execute(
            """SELECT id FROM platform_releases
               WHERE profile_id = ? AND status = 'PUBLISHED'""",
            (profile_id,),
        ).fetchall()
        for release in releases:
            release_id = str(release[0])
            action = cursor.execute(
                """SELECT id, command FROM platform_release_actions
                   WHERE release_id = ? AND action_code = 'get_bgp_routes_vrf'""",
                (release_id,),
            ).fetchone()
            if not action or _normalize(action[1]) != _normalize(OLD_COMMAND):
                continue

            cursor.execute(
                """UPDATE platform_release_actions
                   SET command = ?, command_checksum = ?, updated_at = ?
                   WHERE id = ?""",
                (NEW_COMMAND, _checksum(NEW_COMMAND), now, str(action[0])),
            )
            _refresh_release_checksum(cursor, release_id, now)


def downgrade(cursor, use_pg: bool) -> None:
    # Published command history is not rewritten during downgrade.
    del cursor, use_pg
    return None
