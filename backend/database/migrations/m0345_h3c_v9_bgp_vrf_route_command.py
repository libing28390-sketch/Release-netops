"""Repair the default single-VPN BGP route query in current system V9 releases."""

from .m0347_h3c_v7_bgp_vrf_route_command import (
    OLD_COMMAND,
    _checksum,
    _normalize,
    _now,
    _refresh_release_checksum,
)

VERSION = 345
NAME = "h3c_v9_bgp_vrf_route_command"
NEW_COMMAND = "display bgp routing-table ipv4 vpn-instance {{vrf}}"


def upgrade(cursor, use_pg: bool) -> None:
    actions = cursor.execute(
        """SELECT a.id, a.release_id, a.command
           FROM platform_profiles p
           JOIN platform_releases r ON r.id = p.current_release_id
           JOIN platform_release_actions a ON a.release_id = r.id
           WHERE p.platform_code IN ('h3c_comware_v9', 'h3c_comware9')
             AND p.source = 'SYSTEM' AND p.tenant_id IS NULL
             AND r.status = 'PUBLISHED'
             AND a.action_code = 'get_bgp_routes_vrf'
             AND a.parser_template_version_id IS NULL"""
    ).fetchall()
    now = _now()
    for action in actions:
        if _normalize(action[2]) != OLD_COMMAND:
            continue
        cursor.execute(
            """UPDATE platform_release_actions
               SET command = ?, command_checksum = ?, updated_at = ?
               WHERE id = ?""",
            (NEW_COMMAND, _checksum(NEW_COMMAND), now, action[0]),
        )
        _refresh_release_checksum(cursor, action[1], now)


def downgrade(cursor, use_pg: bool) -> None:
    # A subsequent release may already depend on the corrected command.
    pass
