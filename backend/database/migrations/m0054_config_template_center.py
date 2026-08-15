"""Three-column configuration template center persistence model."""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 54
NAME = "config_template_center"


def _column_exists(cursor, table: str, column: str, use_pg: bool) -> bool:
    if use_pg:
        return cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ?
              AND column_name = ?
            """,
            (table, column),
        ).fetchone() is not None
    return any(
        str(row[1]) == column
        for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _ensure_column(cursor, table: str, column: str, definition: str, use_pg: bool) -> None:
    if not _column_exists(cursor, table, column, use_pg):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    for column, definition in (
        ("code", "TEXT DEFAULT ''"),
        ("source_type", "TEXT DEFAULT 'custom'"),
        ("risk_level", "TEXT DEFAULT 'low'"),
        ("status", "TEXT DEFAULT 'draft'"),
        ("current_version", "TEXT DEFAULT '1.0'"),
        ("is_official", "INTEGER DEFAULT 0"),
        ("created_by", "TEXT DEFAULT ''"),
        ("created_at", "TEXT DEFAULT ''"),
        ("updated_at", "TEXT DEFAULT ''"),
        ("variable_schema_json", "TEXT DEFAULT '[]'"),
        ("example_values_json", "TEXT DEFAULT '{}'"),
        ("usage_notes", "TEXT DEFAULT ''"),
        ("risk_notes", "TEXT DEFAULT ''"),
        ("tags_json", "TEXT DEFAULT '[]'"),
        ("favorite_count", "INTEGER DEFAULT 0"),
        ("use_count", "INTEGER DEFAULT 0"),
        ("quality_score", "INTEGER DEFAULT 0"),
    ):
        _ensure_column(cursor, "templates", column, definition, use_pg)

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_template_versions (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            version TEXT NOT NULL,
            source TEXT NOT NULL,
            rollback_source TEXT NOT NULL DEFAULT '',
            variable_schema_json TEXT NOT NULL DEFAULT '[]',
            example_values_json TEXT NOT NULL DEFAULT '{}',
            render_options_json TEXT NOT NULL DEFAULT '{}',
            change_summary TEXT NOT NULL DEFAULT '',
            checksum TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            published_at TEXT NOT NULL DEFAULT '',
            UNIQUE(template_id, version)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_template_parameter_profiles (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            template_version TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            values_json TEXT NOT NULL DEFAULT '{}',
            value_sources_json TEXT NOT NULL DEFAULT '{}',
            scope TEXT NOT NULL DEFAULT 'private',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_template_render_history (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            template_version TEXT NOT NULL,
            parameter_profile_id TEXT NOT NULL DEFAULT '',
            parameters_json TEXT NOT NULL DEFAULT '{}',
            rendered_output TEXT NOT NULL DEFAULT '',
            render_status TEXT NOT NULL,
            validation_result_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_template_compatibility (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            vendor TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT '',
            model_pattern TEXT NOT NULL DEFAULT '',
            min_version TEXT NOT NULL DEFAULT '',
            max_version TEXT NOT NULL DEFAULT '',
            required_capabilities_json TEXT NOT NULL DEFAULT '[]',
            excluded_versions_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_template_favorites (
            template_id TEXT NOT NULL,
            username TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(template_id, username)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_template_task_drafts (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            template_version TEXT NOT NULL,
            parameter_profile_id TEXT NOT NULL DEFAULT '',
            parameters_json TEXT NOT NULL DEFAULT '{}',
            rendered_output TEXT NOT NULL DEFAULT '',
            render_summary_json TEXT NOT NULL DEFAULT '{}',
            risk_level TEXT NOT NULL DEFAULT 'low',
            validation_result_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'draft',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_template_versions_template "
        "ON config_template_versions(template_id, created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_template_profiles_template "
        "ON config_template_parameter_profiles(template_id, updated_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_template_render_history_template "
        "ON config_template_render_history(template_id, created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_template_task_drafts_creator "
        "ON config_template_task_drafts(created_by, created_at)"
    )

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor.execute(
        """
        UPDATE templates
        SET source_type = CASE
                WHEN category = 'official'
                  OR validation_status = 'official_reference_reviewed'
                  OR official_reference <> ''
                THEN 'official'
                ELSE COALESCE(NULLIF(source_type, ''), 'custom')
            END,
            is_official = CASE
                WHEN category = 'official'
                  OR validation_status = 'official_reference_reviewed'
                  OR official_reference <> ''
                THEN 1 ELSE COALESCE(is_official, 0)
            END,
            status = CASE
                WHEN validation_status IN ('official_reference_reviewed', 'device_validated')
                THEN 'published'
                ELSE COALESCE(NULLIF(status, ''), 'draft')
            END,
            current_version = COALESCE(NULLIF(current_version, ''), '1.0'),
            created_at = COALESCE(NULLIF(created_at, ''), ?),
            updated_at = COALESCE(NULLIF(updated_at, ''), ?)
        """,
        (now, now),
    )

