"""Use Huawei's full Eth-Trunk command in SYSTEM releases."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


VERSION = 94
NAME = "repair_huawei_eth_trunk_command"

_LEGACY_COMMAND = "dis eth-trunk"
_CANONICAL_COMMAND = "display eth-trunk"


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def upgrade(cursor, use_pg: bool) -> None:
    """Repair existing SYSTEM releases and recompute their release checksums."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    releases = cursor.execute(
        """SELECT r.id
           FROM platform_releases r
           JOIN platform_profiles p ON p.id = r.profile_id
           WHERE p.source = 'SYSTEM'
             AND p.parser_platform IN ('huawei_vrp', 'huawei_vrpv8')
             AND r.status IN ('PUBLISHED', 'DEPRECATED')"""
    ).fetchall()

    for row in releases:
        release_id = row[0]
        cursor.execute(
            """UPDATE platform_release_actions
               SET command = ?, command_checksum = ?, updated_at = ?
               WHERE release_id = ?
                 AND action_code = 'get_link_aggregation'
                 AND command IN (?, ?)""",
            (
                _CANONICAL_COMMAND,
                _checksum(_CANONICAL_COMMAND),
                now,
                release_id,
                _LEGACY_COMMAND,
                _CANONICAL_COMMAND,
            ),
        )
        actions = [
            dict(item)
            for item in cursor.execute(
                """SELECT action_code, command, parser_template_version_id, field_contract_json
                   FROM platform_release_actions
                   WHERE release_id = ?
                   ORDER BY action_code""",
                (release_id,),
            ).fetchall()
        ]
        encoded = json.dumps(actions, ensure_ascii=False, sort_keys=True)
        cursor.execute(
            "UPDATE platform_releases SET checksum = ?, updated_at = ? WHERE id = ?",
            (_checksum(encoded), now, release_id),
        )
