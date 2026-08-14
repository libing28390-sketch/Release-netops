"""Add durable source, import-run, and per-file tracking for the MIB repository.

The original ``snmp_mibs`` table is kept for compatibility with the existing
OID picker.  This migration adds the metadata needed to make a local MIB
repository repeatable, resumable, and auditable without putting the raw MIB
source text in PostgreSQL/SQLite for every file.
"""

from __future__ import annotations


VERSION = 134
NAME = "mib_repository_import_tracking"


def _ensure_column(cursor, table: str, column: str, definition: str, use_pg: bool) -> None:
    if use_pg:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
        return

    columns = {str(row[1]).lower() for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
    if column.lower() not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    # Existing rows are marked legacy and remain searchable. New imports fill
    # these fields with source/version/path/hash/parse information.
    for column, definition in (
        ("source_id", "TEXT NOT NULL DEFAULT ''"),
        ("source_commit", "TEXT NOT NULL DEFAULT ''"),
        ("relative_path", "TEXT NOT NULL DEFAULT ''"),
        ("raw_file_path", "TEXT NOT NULL DEFAULT ''"),
        ("sha256", "TEXT NOT NULL DEFAULT ''"),
        ("parse_status", "TEXT NOT NULL DEFAULT 'legacy'"),
        ("parse_error", "TEXT NOT NULL DEFAULT ''"),
        ("parser_version", "TEXT NOT NULL DEFAULT 'legacy'"),
        ("module_oid", "TEXT NOT NULL DEFAULT ''"),
        ("import_run_id", "TEXT NOT NULL DEFAULT ''"),
        ("is_active", "INTEGER NOT NULL DEFAULT 1"),
    ):
        _ensure_column(cursor, "snmp_mibs", column, definition, use_pg)

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_mib_sources (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL DEFAULT 'librenms',
            source_name TEXT NOT NULL,
            source_commit TEXT NOT NULL DEFAULT '',
            root_path TEXT NOT NULL DEFAULT '',
            manifest_path TEXT NOT NULL DEFAULT '',
            file_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ready',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_mib_import_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT 'librenms',
            source_commit TEXT NOT NULL DEFAULT '',
            source_path TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'running',
            total_files INTEGER NOT NULL DEFAULT 0,
            processed_files INTEGER NOT NULL DEFAULT 0,
            imported_files INTEGER NOT NULL DEFAULT 0,
            updated_files INTEGER NOT NULL DEFAULT 0,
            skipped_files INTEGER NOT NULL DEFAULT 0,
            failed_files INTEGER NOT NULL DEFAULT 0,
            duplicate_files INTEGER NOT NULL DEFAULT 0,
            zero_node_files INTEGER NOT NULL DEFAULT 0,
            total_nodes INTEGER NOT NULL DEFAULT 0,
            current_path TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_mib_import_items (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            source_id TEXT NOT NULL DEFAULT '',
            relative_path TEXT NOT NULL,
            vendor_key TEXT NOT NULL DEFAULT '',
            vendor_name TEXT NOT NULL DEFAULT '',
            filename TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL DEFAULT '',
            file_size INTEGER NOT NULL DEFAULT 0,
            raw_file_path TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            mib_id TEXT NOT NULL DEFAULT '',
            module_name TEXT NOT NULL DEFAULT '',
            node_count INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    indexes = (
        "CREATE INDEX IF NOT EXISTS idx_snmp_mibs_source_path ON snmp_mibs(source_id, relative_path)",
        "CREATE INDEX IF NOT EXISTS idx_snmp_mibs_sha256 ON snmp_mibs(sha256)",
        "CREATE INDEX IF NOT EXISTS idx_snmp_mibs_parse_status ON snmp_mibs(parse_status, is_active)",
        "CREATE INDEX IF NOT EXISTS idx_snmp_mibs_module_name ON snmp_mibs(name)",
        "CREATE INDEX IF NOT EXISTS idx_snmp_mib_sources_lookup ON snmp_mib_sources(source_type, source_name, source_commit)",
        "CREATE INDEX IF NOT EXISTS idx_snmp_mib_runs_status ON snmp_mib_import_runs(status, started_at)",
        "CREATE INDEX IF NOT EXISTS idx_snmp_mib_runs_source ON snmp_mib_import_runs(source_id, started_at)",
        "CREATE INDEX IF NOT EXISTS idx_snmp_mib_items_run ON snmp_mib_import_items(run_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_snmp_mib_items_source_path ON snmp_mib_import_items(source_id, relative_path)",
        "CREATE INDEX IF NOT EXISTS idx_snmp_mib_items_hash ON snmp_mib_import_items(sha256)",
        "CREATE INDEX IF NOT EXISTS idx_snmp_mib_items_vendor ON snmp_mib_import_items(vendor_key, status)",
    )
    for statement in indexes:
        cursor.execute(statement)


def downgrade(cursor, use_pg: bool) -> None:
    # The project migration runner does not perform destructive downgrades.
    # Keeping the tables is intentional so an older binary cannot silently
    # delete import history or raw-file references.
    return None
