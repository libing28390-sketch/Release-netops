"""PostgreSQL catalog helpers shared by schema and migration tests."""

from __future__ import annotations


def table_columns(connection, table_name: str) -> set[str]:
    rows = connection.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table_name,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def table_names(connection) -> set[str]:
    rows = connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema()"
    ).fetchall()
    return {str(row[0]) for row in rows}


def table_exists(connection, table_name: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table_name,),
        ).fetchone()
    )


def index_names(connection, table_name: str | None = None) -> set[str]:
    if table_name is None:
        rows = connection.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = ?",
            (table_name,),
        ).fetchall()
    return {str(row[0]) for row in rows}


def trigger_names(connection) -> set[str]:
    rows = connection.execute(
        "SELECT trigger_name FROM information_schema.triggers "
        "WHERE trigger_schema = current_schema()"
    ).fetchall()
    return {str(row[0]) for row in rows}


def foreign_key_targets(connection, table_name: str) -> set[str]:
    rows = connection.execute(
        """
        SELECT foreign_table.relname
        FROM pg_constraint constraint_row
        JOIN pg_class local_table ON local_table.oid = constraint_row.conrelid
        JOIN pg_namespace namespace ON namespace.oid = local_table.relnamespace
        JOIN pg_class foreign_table ON foreign_table.oid = constraint_row.confrelid
        WHERE constraint_row.contype = 'f'
          AND namespace.nspname = current_schema()
          AND local_table.relname = ?
        """,
        (table_name,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def schema_object_names(connection) -> set[str]:
    return table_names(connection) | index_names(connection)
