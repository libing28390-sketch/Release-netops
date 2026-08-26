"""Normalize the interface L3 flag to a PostgreSQL BOOLEAN column."""

VERSION = 127
NAME = "interface_boolean_flags"


def _data_type(cursor, column: str) -> str | None:
    row = cursor.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'interfaces' AND column_name = ?",
        (column,),
    ).fetchone()
    return str(row[0]).lower() if row else None


def _to_boolean(cursor, column: str) -> None:
    data_type = _data_type(cursor, column)
    if data_type is None or data_type == "boolean":
        return
    cursor.execute(f"ALTER TABLE interfaces ALTER COLUMN {column} DROP DEFAULT")
    cursor.execute(
        f"ALTER TABLE interfaces ALTER COLUMN {column} TYPE BOOLEAN USING "
        f"CASE WHEN {column} IS NULL THEN NULL "
        f"WHEN LOWER(TRIM({column}::text)) IN ('1', 'true', 't', 'yes', 'y', 'on') THEN TRUE "
        f"ELSE FALSE END"
    )
    cursor.execute(f"ALTER TABLE interfaces ALTER COLUMN {column} SET DEFAULT FALSE")


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    _to_boolean(cursor, "is_l3")


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    return None
