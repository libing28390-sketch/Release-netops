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
    for column, definition in definitions.items():
        cursor.execute(f"ALTER TABLE sites ADD COLUMN IF NOT EXISTS {column} {definition}")
    return
