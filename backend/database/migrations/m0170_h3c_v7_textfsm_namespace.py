"""Make the current H3C Comware template scope explicitly V7.

The public parser family remains ``h3c_comware`` and the transport driver
remains ``hp_comware``.  The system V7 Profile is the concrete owner of the
current 22 grammars, so their registry filenames must say V7 instead of
looking like an unversioned family fallback.  This migration also repairs
the command spellings that previously prevented CPU, route, and BGP action
bindings from being matched.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


VERSION = 170
NAME = "h3c_v7_textfsm_namespace"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _canonical_command(command: str) -> str:
    aliases = {
        "display cpu usage": "display cpu-usage",
        "display bgp routing table ipv4": "display bgp routing-table ipv4",
        "display ip routing table": "display ip routing-table",
        "display ip routing table statistics": "display ip routing-table statistics",
        "display ntp service status": "display ntp-service status",
        "display link aggregation verbose": "display link-aggregation verbose",
        "display mac address": "display mac-address",
        "display lldp neighbor information list": "display lldp neighbor-information list",
    }
    normalized = _normalize(command)
    return aliases.get(normalized, normalized)


def _command_from_v7_filename(filename: str) -> str:
    stem = Path(str(filename or "")).stem.lower()
    prefix = "h3c_comware_v7_"
    if stem.startswith(prefix):
        return _canonical_command(stem[len(prefix):].replace("_", " "))
    return ""


def _v7_filename(source_filename: str) -> str | None:
    filename = Path(str(source_filename or "")).name
    lowered = filename.lower()
    marker = "h3c_comware_display_"
    marker_index = lowered.find(marker)
    if marker_index < 0 or lowered.startswith("h3c_comware_v5_") or lowered.startswith("h3c_comware_v9_"):
        return None
    suffix = filename[marker_index + len(marker):]
    return f"h3c_comware_v7_display_{suffix}"


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


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    profile = cursor.execute(
        """SELECT id FROM platform_profiles
           WHERE platform_code = 'h3c_comware'
             AND source = 'SYSTEM' AND tenant_id IS NULL
           LIMIT 1"""
    ).fetchone()
    if not profile:
        return
    profile_id = str(profile[0])
    now = _now()

    template_rows = cursor.execute(
        """SELECT id, platform_profile_id, platform_code, source_filename, command
           FROM parser_templates
           WHERE tenant_id IS NULL AND source = 'SYSTEM'""",
    ).fetchall()
    for row in template_rows:
        source_filename = str(row[3] or "")
        lowered_filename = source_filename.lower()
        belongs_to_v7 = str(row[1] or "") == profile_id or (
            str(row[2] or "").lower() == "h3c_comware"
            and (
                lowered_filename.startswith("h3c_comware_v7_")
                or "h3c_comware_display_" in lowered_filename
            )
        )
        if not belongs_to_v7:
            continue
        target_filename = (
            source_filename
            if lowered_filename.startswith("h3c_comware_v7_")
            else _v7_filename(source_filename)
        )
        if not target_filename:
            continue
        target_code = _template_code(target_filename)
        target_name = Path(target_filename).stem
        target_command = _command_from_v7_filename(target_filename) or _canonical_command(str(row[4] or ""))
        collision = cursor.execute(
            """SELECT id FROM parser_templates
               WHERE tenant_id IS NULL AND source = 'SYSTEM'
                 AND platform_profile_id = ? AND id <> ?
                 AND (source_filename = ? OR template_code = ?)""",
            (profile_id, str(row[0]), target_filename, target_code),
        ).fetchone()
        if collision:
            # A partially applied deployment already has the target row. Keep
            # it authoritative and avoid violating the profile-scoped unique
            # index on a retry.
            continue
        cursor.execute(
            """UPDATE parser_templates
               SET platform_profile_id = ?, source_filename = ?, template_code = ?, name = ?,
                   command = ?, updated_at = ?
               WHERE id = ?""",
            (profile_id, target_filename, target_code, target_name, target_command, now, row[0]),
        )

    # V7's registered BGP grammar represents the command without the optional
    # ``unicast`` suffix. Repair every system V7 Release snapshot so the
    # action and its parser use one exact, auditable command string.
    cursor.execute(
        """UPDATE platform_release_actions
           SET command = ?, updated_at = ?
           WHERE release_id IN (
             SELECT r.id FROM platform_releases r
             WHERE r.profile_id = ?
           ) AND action_code = 'get_bgp_routes'""",
        ("display bgp routing-table ipv4", now, profile_id),
    )

    published_templates = cursor.execute(
        """SELECT v.id, t.command
           FROM parser_template_versions v
           JOIN parser_templates t ON t.id = v.template_id
           WHERE v.status = 'PUBLISHED'
             AND t.source = 'SYSTEM' AND t.tenant_id IS NULL
             AND t.platform_profile_id = ?""",
        (profile_id,),
    ).fetchall()
    template_by_command = {
        _normalize(row[1]): str(row[0])
        for row in published_templates
        if _normalize(row[1])
    }

    release_rows = cursor.execute(
        """SELECT r.id FROM platform_releases r
           WHERE r.profile_id = ?
             AND r.status IN ('PUBLISHED', 'DRAFT', 'IN_REVIEW', 'APPROVED')""",
        (profile_id,),
    ).fetchall()
    for release in release_rows:
        release_id = str(release[0])
        action_rows = cursor.execute(
            """SELECT action_code, command, parser_template_version_id
               FROM platform_release_actions WHERE release_id = ?""",
            (release_id,),
        ).fetchall()
        changed = False
        for action in action_rows:
            version_id = template_by_command.get(_normalize(action[1]))
            if str(action[2] or "") != str(version_id or ""):
                cursor.execute(
                    """UPDATE platform_release_actions
                       SET parser_template_version_id = ?, updated_at = ?
                       WHERE release_id = ? AND action_code = ?""",
                    (version_id, now, release_id, action[0]),
                )
                changed = True
        if changed:
            _refresh_release_checksum(cursor, release_id, now)


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
