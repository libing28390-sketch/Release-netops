"""Expose the VLAN description parameter in the legacy Huawei/H3C seeds.

The original application seed rendered ``Created_by_NetOps`` literally, so
the template center could not offer a field for the operator to edit.  This
migration only replaces that exact built-in source and leaves user-authored
templates untouched.  The SQL uses the project's parameterized subset, which
is translated by the database adapter for PostgreSQL deployments.
"""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 59
NAME = "vendor_vlan_description_parameters"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for vendor in ("Huawei", "H3C"):
        old_source = """vlan {{ vlan_id | default(10) }}
 description Created_by_NetOps"""
        new_source = """vlan {{ vlan_id | default(10) }}
 description {{ vlan_name | default("USERS") }}"""

        cursor.execute(
            """
            UPDATE templates
            SET content = ?, updated_at = ?
            WHERE name = ? AND vendor = ? AND content = ?
            """,
            (new_source, now, "VLAN Creation", vendor, old_source),
        )
        cursor.execute(
            """
            UPDATE config_template_versions
            SET source = ?, created_at = CASE WHEN created_at = '' THEN ? ELSE created_at END
            WHERE template_id IN (
                SELECT id FROM templates
                WHERE name = ? AND vendor = ?
            ) AND source = ?
            """,
            (new_source, now, "VLAN Creation", vendor, old_source),
        )
