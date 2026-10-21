"""Add protocol and credentials for configuration archive offloading."""

from __future__ import annotations


VERSION = 155
NAME = "config_backup_transfer_protocol"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}



def upgrade(cursor, use_pg: bool) -> None:
    columns = _columns(cursor, "config_backup_policies", use_pg)
    if "tftp_protocol" not in columns:
        cursor.execute("ALTER TABLE config_backup_policies ADD COLUMN tftp_protocol TEXT DEFAULT 'tftp'")
    if "tftp_username" not in columns:
        cursor.execute("ALTER TABLE config_backup_policies ADD COLUMN tftp_username TEXT DEFAULT ''")
    if "tftp_password" not in columns:
        cursor.execute("ALTER TABLE config_backup_policies ADD COLUMN tftp_password TEXT DEFAULT ''")

    # Existing policies were explicitly TFTP policies.  Keep their behavior
    # unchanged after the new protocol selector is introduced.
    cursor.execute(
        "UPDATE config_backup_policies SET tftp_protocol = 'tftp' "
        "WHERE tftp_protocol IS NULL OR TRIM(tftp_protocol) = ''"
    )
