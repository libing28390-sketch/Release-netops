"""Detach legacy TextFSM version IDs from active platform mappings.

TextFSM templates are now file-backed, saved-as-active assets.  The old
registry tables remain in place for historical compatibility, but no current
platform action may depend on a registered or published parser version.
"""

from __future__ import annotations


VERSION = 180
NAME = "detach_legacy_textfsm_versions"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    for table in ("platform_release_actions", "platform_action_runs"):
        try:
            cursor.execute(f"UPDATE {table} SET parser_template_version_id = NULL")
        except Exception:
            # Keep fresh/partial installations compatible with the migration
            # runner; the owning schema migration will create the column when
            # that feature is present.
            continue


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
