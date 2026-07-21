"""
Migration 0004 — Fix foreign key constraint on ip_addresses.

Drops the foreign key constraint pointing to ip_subnets and redirects it to the prefixes table.
"""

VERSION = 4
NAME = "fix_ip_addresses_foreign_key"


def upgrade(cursor, use_pg: bool) -> None:
    if use_pg:
        # Clean up orphan ip_addresses whose subnet_id does not exist in prefixes
        cursor.execute("DELETE FROM ip_addresses WHERE subnet_id NOT IN (SELECT id FROM prefixes)")
        # Drop old constraint
        cursor.execute("ALTER TABLE ip_addresses DROP CONSTRAINT IF EXISTS ip_addresses_subnet_id_fkey")
        # Add new constraint referencing prefixes(id)
        cursor.execute("ALTER TABLE ip_addresses ADD CONSTRAINT ip_addresses_subnet_id_fkey FOREIGN KEY (subnet_id) REFERENCES prefixes(id) ON DELETE CASCADE")
