"""Add an explicit floor field to the CMDB rack location hierarchy."""

VERSION = 22
NAME = "rack_floor"


def upgrade(cursor, use_pg: bool) -> None:
    column_type = "VARCHAR(100)" if use_pg else "TEXT"
    if use_pg:
        exists = cursor.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND table_name = 'racks' AND column_name = 'floor'"
        ).fetchone()
    else:
        exists = next((row for row in cursor.execute("PRAGMA table_info(racks)").fetchall() if row[1] == 'floor'), None)
    if not exists:
        cursor.execute(f"ALTER TABLE racks ADD COLUMN floor {column_type} DEFAULT ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_racks_site_floor ON racks(site_id, floor)")
