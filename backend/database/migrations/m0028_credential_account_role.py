"""Add an explicit normal/admin/shared role to credential vault entries."""

VERSION = 28
NAME = "credential_account_role"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]).lower() for row in rows}
    return {str(row[1]).lower() for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    if "account_role" not in _columns(cursor, "credentials", use_pg):
        cursor.execute("ALTER TABLE credentials ADD COLUMN account_role TEXT DEFAULT 'unbound'")
    cursor.execute(
        "UPDATE credentials SET account_role = 'unbound' "
        "WHERE account_role IS NULL OR TRIM(account_role) = ''"
    )
