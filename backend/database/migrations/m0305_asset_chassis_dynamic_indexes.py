"""Allow chassis ENTITY-MIB observations at any positive integer index."""

from __future__ import annotations

import re


VERSION = 305
NAME = "asset_chassis_dynamic_indexes"

_TABLE_NAME = "asset_chassis_members"
_INDEX_COLUMN = "entity_index"
_POSITIVE_CONSTRAINT_NAME = "ck_asset_chassis_members_entity_index_positive"


def _quote_identifier(value: str) -> str:
    """Quote a constant or PostgreSQL-catalog identifier."""
    return '"' + value.replace('"', '""') + '"'


def _normalize_expression(expression: str) -> str:
    """Normalize the simple expressions returned by PostgreSQL's deparser."""
    return re.sub(r'[\s()"]+', "", expression).lower()


def _entity_index_checks(cursor) -> list[tuple[str, str]]:
    cursor.execute(
        """
        SELECT constraint_row.conname,
               pg_get_expr(constraint_row.conbin, constraint_row.conrelid)
          FROM pg_constraint AS constraint_row
          JOIN pg_class AS table_row
            ON table_row.oid = constraint_row.conrelid
          JOIN pg_namespace AS schema_row
            ON schema_row.oid = table_row.relnamespace
          JOIN pg_attribute AS column_row
            ON column_row.attrelid = table_row.oid
           AND column_row.attnum = constraint_row.conkey[1]
         WHERE schema_row.nspname = current_schema()
           AND table_row.relname = ?
           AND constraint_row.contype = 'c'
           AND array_length(constraint_row.conkey, 1) = 1
           AND column_row.attname = ?
         ORDER BY constraint_row.conname
        """,
        (_TABLE_NAME, _INDEX_COLUMN),
    )
    return [(str(row[0]), str(row[1])) for row in cursor.fetchall()]


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Asset chassis member indexes require PostgreSQL")

    checks = _entity_index_checks(cursor)
    for constraint_name, expression in checks:
        normalized = _normalize_expression(expression)
        if normalized in {
            "entity_indexbetween1and3",
            "entity_index>=1andentity_index<=3",
        }:
            # m0302 used an unnamed, column-level CHECK, whose generated name
            # may vary with the table/column identifiers. Match its actual
            # expression and column instead of assuming that name.
            cursor.execute(
                f"ALTER TABLE {_quote_identifier(_TABLE_NAME)} "
                f"DROP CONSTRAINT {_quote_identifier(constraint_name)}"
            )

    checks = _entity_index_checks(cursor)
    positive_checks = [
        name
        for name, expression in checks
        if _normalize_expression(expression) == "entity_index>0"
    ]
    if positive_checks:
        return

    conflicting_name = next(
        (name for name, _expression in checks if name == _POSITIVE_CONSTRAINT_NAME),
        None,
    )
    if conflicting_name is not None:
        raise RuntimeError(
            f"Constraint {_POSITIVE_CONSTRAINT_NAME} exists with an unexpected expression"
        )

    cursor.execute(
        f"ALTER TABLE {_quote_identifier(_TABLE_NAME)} "
        f"ADD CONSTRAINT {_quote_identifier(_POSITIVE_CONSTRAINT_NAME)} "
        f"CHECK ({_INDEX_COLUMN} > 0)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Preserve collected chassis identity observations on application rollback.
    return None
