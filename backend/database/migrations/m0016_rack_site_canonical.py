"""Normalize rack locations to the canonical CMDB sites relation.

Older rack records used the free-text ``datacenter`` column.  Keep that
column for backward compatibility, but resolve matching values into
``racks.site_id`` and mirror the site code only as a legacy display value.
"""

VERSION = 16
NAME = "rack_site_canonical"


def upgrade(cursor, use_pg: bool) -> None:
    # Use row-by-row updates instead of correlated UPDATE syntax so this
    # migration behaves identically on PostgreSQL and SQLite.
    for rack_id, legacy_label in cursor.execute(
        "SELECT id, datacenter FROM racks WHERE COALESCE(datacenter, '') <> ''"
    ).fetchall():
        site = cursor.execute(
            """SELECT id, site_code, site_name FROM sites
               WHERE id = ? OR site_code = ? OR site_name = ?
               ORDER BY CASE WHEN id = ? THEN 0 WHEN site_code = ? THEN 1 ELSE 2 END
               LIMIT 1""",
            (legacy_label, legacy_label, legacy_label, legacy_label, legacy_label),
        ).fetchone()
        if site:
            cursor.execute(
                "UPDATE racks SET site_id = ?, datacenter = ? WHERE id = ?",
                (site[0], site[1] or site[2] or site[0], rack_id),
            )

    for rack_id, site_id in cursor.execute(
        "SELECT id, site_id FROM racks WHERE COALESCE(site_id, '') <> ''"
    ).fetchall():
        site = cursor.execute(
            "SELECT site_code, site_name, id FROM sites WHERE id = ?", (site_id,)
        ).fetchone()
        if site:
            cursor.execute(
                "UPDATE racks SET datacenter = ? WHERE id = ?",
                (site[0] or site[1] or site[2], rack_id),
            )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_racks_site_id ON racks(site_id)")
