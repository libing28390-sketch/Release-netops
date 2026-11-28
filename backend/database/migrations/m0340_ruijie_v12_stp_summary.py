"""Select the port-level STP command for current system RGOS V12 profiles."""

from datetime import datetime, timezone

from .m0100_register_builtin_textfsm_templates import _checksum, _refresh_release_checksum

VERSION = 340
NAME = "ruijie_v12_stp_summary"

OLD_COMMAND = "show spanning-tree"
NEW_COMMAND = "show spanning-tree summary"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    actions = cursor.execute(
        """SELECT a.id, a.release_id
           FROM platform_profiles p
           JOIN platform_releases r ON r.id = p.current_release_id
           JOIN platform_release_actions a ON a.release_id = r.id
           WHERE p.platform_code = 'ruijie_rgos_v12'
             AND p.source = 'SYSTEM' AND p.tenant_id IS NULL AND p.status = 'ACTIVE'
             AND r.status = 'PUBLISHED'
             AND a.action_code = 'get_stp' AND a.command = ?
             AND a.parser_template_version_id IS NULL""",
        (OLD_COMMAND,),
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    for action_id, release_id in actions:
        cursor.execute(
            """UPDATE platform_release_actions
               SET command = ?, command_checksum = ?, updated_at = ?
               WHERE id = ? AND command = ? AND parser_template_version_id IS NULL""",
            (NEW_COMMAND, _checksum(NEW_COMMAND), now, action_id, OLD_COMMAND),
        )
        if cursor.rowcount:
            _refresh_release_checksum(cursor, release_id, now)


def downgrade(cursor, use_pg: bool) -> None:
    # Do not rewrite the command on downgrade after it may have been reviewed.
    del cursor, use_pg
