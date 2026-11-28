"""Archive the temporary RSR templates that were seeded under generic RGOS V10."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .m0100_register_builtin_textfsm_templates import _refresh_release_checksum


VERSION = 344
NAME = "archive_ruijie_rgos_v10_rsr_templates"

PROFILE_CODE = "ruijie_rgos_v10"
PARSER_PLATFORM = "ruijie_rgos"
TEMPLATE_FILENAMES = (
    "ruijie_rgos_v10_show_memory.textfsm",
    "ruijie_rgos_v10_show_ip_route.textfsm",
    "ruijie_rgos_v10_show_ip_route_vrf.textfsm",
    "ruijie_rgos_v10_show_clock.textfsm",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _template_ids(filename: str) -> tuple[str, str]:
    template_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template:{filename}"))
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template-version:{filename}:1"))
    return template_id, version_id


def upgrade(cursor, use_pg: bool) -> None:
    """Clear only the exact legacy V10 SYSTEM parser rows and their bindings."""
    del use_pg  # Uses the migration cursor adapter and portable '?' placeholders.

    try:
        profile_rows = cursor.execute(
            """SELECT id FROM platform_profiles
               WHERE platform_code = ? AND source = 'SYSTEM' AND tenant_id IS NULL""",
            (PROFILE_CODE,),
        ).fetchall()
    except Exception:
        return
    profile_ids = {str(row[0]) for row in profile_rows}
    if not profile_ids:
        return

    now = _now()
    changed_release_ids: set[str] = set()
    for filename in TEMPLATE_FILENAMES:
        template_id, version_id = _template_ids(filename)
        template = cursor.execute(
            """SELECT id, tenant_id, platform_profile_id, platform_code,
                      source_filename, source, status
               FROM parser_templates WHERE id = ?""",
            (template_id,),
        ).fetchone()
        if not template:
            continue
        if (
            template[1] not in (None, "")
            or str(template[2] or "") not in profile_ids
            or str(template[3] or "") != PARSER_PLATFORM
            or str(template[4] or "") != filename
            or str(template[5] or "") != "SYSTEM"
        ):
            continue

        version = cursor.execute(
            """SELECT id, template_id, status
               FROM parser_template_versions WHERE id = ?""",
            (version_id,),
        ).fetchone()
        action_rows = cursor.execute(
            """SELECT a.id, a.release_id
               FROM platform_release_actions a
               JOIN platform_releases r ON r.id = a.release_id
               JOIN platform_profiles p ON p.id = r.profile_id
               WHERE a.parser_template_version_id = ?
                 AND p.platform_code = ? AND p.source = 'SYSTEM'
                 AND p.tenant_id IS NULL""",
            (version_id, PROFILE_CODE),
        ).fetchall()
        for action in action_rows:
            cursor.execute(
                """UPDATE platform_release_actions
                   SET parser_template_version_id = NULL, updated_at = ?
                   WHERE id = ? AND parser_template_version_id = ?""",
                (now, str(action[0]), version_id),
            )
            if cursor.rowcount:
                changed_release_ids.add(str(action[1]))

        remaining_version_bindings = cursor.execute(
            """SELECT 1 FROM platform_release_actions
               WHERE parser_template_version_id = ? LIMIT 1""",
            (version_id,),
        ).fetchone()
        if (
            version
            and str(version[1]) == template_id
            and not remaining_version_bindings
            and str(version[2] or "") != "ARCHIVED"
        ):
            cursor.execute(
                """UPDATE parser_template_versions
                   SET status = 'ARCHIVED', updated_at = ?
                   WHERE id = ? AND template_id = ?""",
                (now, version_id, template_id),
            )

        remaining_active_versions = cursor.execute(
            """SELECT 1 FROM parser_template_versions
               WHERE template_id = ? AND status <> 'ARCHIVED' LIMIT 1""",
            (template_id,),
        ).fetchone()
        remaining_template_bindings = cursor.execute(
            """SELECT 1 FROM platform_release_actions a
               JOIN parser_template_versions v ON v.id = a.parser_template_version_id
               WHERE v.template_id = ? LIMIT 1""",
            (template_id,),
        ).fetchone()
        if (
            not remaining_active_versions
            and not remaining_template_bindings
            and str(template[6] or "") != "ARCHIVED"
        ):
            cursor.execute(
                """UPDATE parser_templates SET status = 'ARCHIVED', updated_at = ?
                   WHERE id = ? AND platform_profile_id = ? AND platform_code = ?
                     AND source_filename = ? AND source = 'SYSTEM'
                     AND tenant_id IS NULL""",
                (now, template_id, str(template[2]), PARSER_PLATFORM, filename),
            )

    for release_id in changed_release_ids:
        _refresh_release_checksum(cursor, release_id, now)


def downgrade(cursor, use_pg: bool) -> None:
    # RSR output is not safe to restore to the generic V10 Profile.
    del cursor, use_pg
