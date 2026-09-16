"""Repair persisted Huawei VRP5 and DPtech SYSTEM action commands.

The platform registry is authoritative once it is seeded, so changing the
fallback command catalog alone does not repair upgraded deployments.  This
migration aligns existing SYSTEM releases with the vendor commands backed by
the shipped TextFSM templates while preserving tenant-owned profiles.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


VERSION = 186
NAME = "repair_vendor_action_catalogs"


DPTECH_COMMANDS = {
    "get_version": "show version",
    "get_lldp_neighbors": "show lldp neighbors",
    "get_interface_brief": "show interface status",
    "get_ip_interfaces": "show ip interface brief",
    "get_arp_table": "show arp all",
    "get_mac_table": "show mac-address-table",
    "get_vlan_table": "show vlan",
    "get_route_table": "show ip route",
    "get_stp": "show spanning-tree",
    "get_cpu": "show cpu-usage",
    "get_memory": "show memory",
    "get_temperature": "show environment",
    "get_ntp_status": "show ntp status",
    "get_bfd_sessions": "show bfd session",
    "get_logbuffer": "show logging operlog recent",
    "get_interface_description": "show ip interface brief",
    "get_clock": "show clock",
    "get_uptime": "show version",
}


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _repair_release(cursor, release_id: str, commands: dict[str, str], now: str) -> None:
    for action_code, command in commands.items():
        cursor.execute(
            """UPDATE platform_release_actions
               SET command = ?, command_checksum = ?, updated_at = ?
               WHERE release_id = ? AND action_code = ? AND command <> ?""",
            (command, _checksum(command), now, release_id, action_code, command),
        )

    actions = [
        dict(row)
        for row in cursor.execute(
            """SELECT action_code, command, parser_template_version_id, field_contract_json
               FROM platform_release_actions
               WHERE release_id = ? ORDER BY action_code""",
            (release_id,),
        ).fetchall()
    ]
    cursor.execute(
        "UPDATE platform_releases SET checksum = ?, updated_at = ? WHERE id = ?",
        (_checksum(_json(actions)), now, release_id),
    )


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg  # The database adapter translates portable '?' placeholders.
    try:
        cursor.execute("SELECT 1 FROM platform_release_actions LIMIT 1")
    except Exception:
        return

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = cursor.execute(
        """SELECT p.platform_code, p.parser_platform, r.id
           FROM platform_profiles p
           JOIN platform_releases r ON r.id = p.current_release_id
           WHERE p.tenant_id IS NULL AND p.source = 'SYSTEM'
             AND r.status IN ('PUBLISHED', 'DEPRECATED')"""
    ).fetchall()

    for platform_code, parser_platform, release_id in rows:
        code = str(platform_code or "").strip().lower()
        parser = str(parser_platform or "").strip().lower()
        if code in {"huawei_vrp", "huawei_vrp5"}:
            _repair_release(cursor, str(release_id), {"get_fans": "dis fan"}, now)
        elif parser == "dptech_ios":
            _repair_release(cursor, str(release_id), DPTECH_COMMANDS, now)


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
