"""Add district and operational contact fields to CMDB sites."""

VERSION = 18
NAME = "site_district_contacts"


def upgrade(cursor, use_pg: bool) -> None:
    definitions = {
        "district": "TEXT DEFAULT ''",
        "contact_name": "TEXT DEFAULT ''",
        "contact_phone": "TEXT DEFAULT ''",
        "contact_email": "TEXT DEFAULT ''",
    }
    if use_pg:
        for column, definition in definitions.items():
            cursor.execute(f"ALTER TABLE sites ADD COLUMN IF NOT EXISTS {column} {definition}")
        return

    columns = {row[1] for row in cursor.execute("PRAGMA table_info(sites)").fetchall()}
    for column, definition in definitions.items():
        if column not in columns:
            cursor.execute(f"ALTER TABLE sites ADD COLUMN {column} {definition}")
