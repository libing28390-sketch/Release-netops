"""Add the canonical CMDB site relation to physical assets.

``datacenter`` was an early free-text field.  It remains in the database for
rollback and import compatibility, but the application must use ``site_id``
and the CMDB ``sites`` table for all new reads and writes.
"""

VERSION = 12
NAME = "cmdb_asset_site"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        (table,),
    )
    return {row[0] for row in cursor.fetchall()}



def upgrade(cursor, use_pg: bool) -> None:
    columns = _columns(cursor, "physical_assets", use_pg)
    if "site_id" not in columns:
        cursor.execute("ALTER TABLE physical_assets ADD COLUMN site_id TEXT DEFAULT ''")

    # Fresh installations already use the new baseline and do not have the
    # retired source column.  There is then nothing to backfill.
    if "datacenter" not in columns:
        return

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_physical_assets_site_id ON physical_assets(site_id)"
    )

    # One-time compatibility backfill.  Matching is deliberately deterministic:
    # site id first, then site code/name.  Unmatched legacy text stays empty and
    # is rendered as “Unassigned site” by the CMDB tree.
    cursor.execute(
        """
        UPDATE physical_assets
        SET site_id = COALESCE(
            (
                SELECT s.id FROM sites s
                WHERE s.id = physical_assets.datacenter
                   OR s.site_code = physical_assets.datacenter
                   OR s.site_name = physical_assets.datacenter
                ORDER BY CASE
                    WHEN s.id = physical_assets.datacenter THEN 0
                    WHEN s.site_code = physical_assets.datacenter THEN 1
                    ELSE 2
                END
                LIMIT 1
            ),
            site_id,
            ''
        )
        WHERE COALESCE(site_id, '') = ''
          AND COALESCE(datacenter, '') <> ''
        """
    )
