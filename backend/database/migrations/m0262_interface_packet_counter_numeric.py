"""Widen interface counters before the HC packet insert can overflow int4.

The interface packet total is the sum of up to three unsigned Counter64
values, so a signed integer (and even a signed BIGINT) is not a lossless
storage type.  The raw HC fields use NUMERIC(20, 0), which covers one
unsigned Counter64 and the observed three-counter total.  Every one-minute
aggregate is an unbounded NUMERIC because it is a SQL SUM whose sample count
is data dependent.

The four IF-MIB error/discard counters are Counter32 values rather than HC
Counter64 values.  BIGINT is sufficient for an individual unsigned
Counter32, while their rollups remain unbounded NUMERIC because they are
aggregates.
"""

from __future__ import annotations


VERSION = 262
NAME = "interface_packet_counter_numeric"

_RAW_COLUMNS = (
    ("in_pkts", "NUMERIC(20,0)"),
    ("out_pkts", "NUMERIC(20,0)"),
    ("in_errors", "BIGINT"),
    ("out_errors", "BIGINT"),
    ("in_discards", "BIGINT"),
    ("out_discards", "BIGINT"),
    ("fcs_errors", "NUMERIC(20,0)"),
    ("frame_too_long_errors", "NUMERIC(20,0)"),
    ("mac_rx_errors", "NUMERIC(20,0)"),
    ("symbol_errors", "NUMERIC(20,0)"),
)

_ROLLUP_COLUMNS = (
    ("in_pkts_sum", "NUMERIC"),
    ("out_pkts_sum", "NUMERIC"),
    ("err_delta_sum", "NUMERIC"),
    ("discard_delta_sum", "NUMERIC"),
    ("fcs_sum", "NUMERIC"),
)

_TABLES = (
    ("interface_telemetry_raw", _RAW_COLUMNS),
    ("interface_telemetry_1m", _ROLLUP_COLUMNS),
)

_LEGACY_MIN = -2147483648
_LEGACY_MAX = 2147483647


def _column_type(cursor, table: str, column: str) -> tuple[str, int | None, int | None] | None:
    row = cursor.execute(
        """
        SELECT data_type, numeric_precision, numeric_scale
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = ?
           AND column_name = ?
        """,
        (table, column),
    ).fetchone()
    if row is None:
        return None
    return str(row[0]).lower(), row[1], row[2]


def _type_matches(actual: tuple[str, int | None, int | None], target: str) -> bool:
    data_type, precision, scale = actual
    normalized = target.replace(" ", "").upper()
    if normalized == "BIGINT":
        return data_type == "bigint"
    if normalized == "NUMERIC":
        return data_type == "numeric" and precision is None and scale is None
    if normalized == "NUMERIC(20,0)":
        return data_type == "numeric" and precision == 20 and scale == 0
    raise ValueError(f"Unsupported counter type {target!r}")


def _alter_type(cursor, table: str, column: str, target: str, *, has_default: bool) -> None:
    # Rollup columns have a DEFAULT 0 in the baseline schema.  Drop it while
    # changing the type so PostgreSQL never tries to retain an incompatible
    # expression, then restore the documented default.
    if has_default:
        cursor.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
    cursor.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {target} "
        f"USING {column}::{target}"
    )
    if has_default:
        cursor.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT 0")


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Interface counter widening requires PostgreSQL")
    for table, columns in _TABLES:
        has_default = table == "interface_telemetry_1m"
        for column, target in columns:
            actual = _column_type(cursor, table, column)
            if actual is None or _type_matches(actual, target):
                continue
            _alter_type(cursor, table, column, target, has_default=has_default)


def _check_legacy_range(cursor, table: str, column: str) -> None:
    row = cursor.execute(
        f"""
        SELECT 1
          FROM {table}
         WHERE {column} IS NOT NULL
           AND ({column} < ? OR {column} > ?)
         LIMIT 1
        """,
        (_LEGACY_MIN, _LEGACY_MAX),
    ).fetchone()
    if row is not None:
        raise ValueError(
            f"Cannot downgrade {table}.{column} to INTEGER: value is outside "
            f"[{_LEGACY_MIN}, {_LEGACY_MAX}]"
        )


def downgrade(cursor, use_pg: bool) -> None:
    """Restore INTEGER only when every stored value is representable.

    Range checks run for every column before the first ALTER.  An oversized
    counter therefore raises without changing the schema or clamping data;
    any PostgreSQL DDL error is also left to the caller's transaction rollback.
    """
    if not use_pg:
        raise RuntimeError("Interface counter downgrade requires PostgreSQL")
    for table, columns in _TABLES:
        for column, _target in columns:
            actual = _column_type(cursor, table, column)
            if actual is None or actual[0] == "integer":
                continue
            _check_legacy_range(cursor, table, column)

    for table, columns in _TABLES:
        has_default = table == "interface_telemetry_1m"
        for column, _target in columns:
            actual = _column_type(cursor, table, column)
            if actual is None or actual[0] == "integer":
                continue
            _alter_type(cursor, table, column, "INTEGER", has_default=has_default)


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
