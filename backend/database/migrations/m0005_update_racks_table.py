"""
Migration 0005 — Update racks table with detailed rack properties.

Adds new columns to the `racks` table according to the user's PostgreSQL requirements.
"""

VERSION = 5
NAME = "update_racks_table"


def _column_exists(cursor, table_name: str, column_name: str, use_pg: bool) -> bool:
    if use_pg:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            (table_name, column_name)
        )
        return cursor.fetchone() is not None
    else:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        return column_name in columns


def upgrade(cursor, use_pg: bool) -> None:
    # 1. Add new columns to racks table if they do not exist
    columns_to_add = [
        ("room_name", "VARCHAR(100)" if use_pg else "TEXT"),
        ("row_name", "VARCHAR(50)" if use_pg else "TEXT"),
        ("used_u", "INTEGER DEFAULT 0"),
        ("power_capacity_w", "INTEGER DEFAULT 5000"),
        ("current_power_w", "INTEGER DEFAULT 0"),
        ("power_utilization", "DECIMAL(5,2) DEFAULT 0" if use_pg else "REAL DEFAULT 0"),
        ("max_weight_kg", "INTEGER"),
        ("current_weight_kg", "INTEGER DEFAULT 0"),
        ("cooling_zone", "VARCHAR(50)" if use_pg else "TEXT"),
        ("remarks", "TEXT"),
        ("rack_code", "VARCHAR(50)" if use_pg else "TEXT"),
        ("rack_name", "VARCHAR(100)" if use_pg else "TEXT")
    ]
    
    for col_name, col_def in columns_to_add:
        if not _column_exists(cursor, "racks", col_name, use_pg):
            cursor.execute(f"ALTER TABLE racks ADD COLUMN {col_name} {col_def}")

    # 2. Ensure UNIQUE constraints / Indexes on rack_code
    if use_pg:
        cursor.execute(
            "SELECT 1 FROM pg_constraint "
            "WHERE conrelid = 'racks'::regclass "
            "AND conname = 'racks_rack_code_key'"
        )
        if cursor.fetchone() is None:
            # A legacy database may have duplicate rack codes.  Keep the
            # migration retryable if the constraint cannot be introduced;
            # PostgreSQL otherwise aborts the surrounding transaction even
            # when the caller only wants to defer this integrity check.
            cursor.execute("SAVEPOINT m0005_rack_code_unique")
            try:
                cursor.execute("ALTER TABLE racks ADD CONSTRAINT racks_rack_code_key UNIQUE (rack_code)")
            except Exception:
                cursor.execute("ROLLBACK TO SAVEPOINT m0005_rack_code_unique")
            finally:
                cursor.execute("RELEASE SAVEPOINT m0005_rack_code_unique")
    else:
        try:
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_racks_rack_code ON racks(rack_code)")
        except Exception:
            pass
