"""Persistent state and indexes for the configuration search workspace."""

from __future__ import annotations


VERSION = 53
NAME = "config_search_workspace"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg  # The DDL intentionally uses the PostgreSQL/SQLite common subset.

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_search_documents (
            snapshot_id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            content_hash TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL DEFAULT 'ncm-search-v1',
            line_count INTEGER NOT NULL DEFAULT 0,
            object_count INTEGER NOT NULL DEFAULT 0,
            index_status TEXT NOT NULL DEFAULT 'ready',
            error_text TEXT NOT NULL DEFAULT '',
            indexed_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_search_objects (
            id TEXT PRIMARY KEY,
            snapshot_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            vendor TEXT NOT NULL DEFAULT '',
            object_type TEXT NOT NULL,
            object_key TEXT NOT NULL,
            start_line INTEGER NOT NULL DEFAULT 0,
            end_line INTEGER NOT NULL DEFAULT 0,
            search_text TEXT NOT NULL DEFAULT '',
            attributes_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_search_audit (
            id TEXT PRIMARY KEY,
            actor_username TEXT NOT NULL DEFAULT '',
            query_text TEXT NOT NULL,
            search_type TEXT NOT NULL,
            search_scope TEXT NOT NULL,
            filters_json TEXT NOT NULL DEFAULT '{}',
            result_count INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_config_searches (
            id TEXT PRIMARY KEY,
            owner_username TEXT NOT NULL,
            name TEXT NOT NULL,
            query_text TEXT NOT NULL,
            search_type TEXT NOT NULL DEFAULT 'AUTO',
            search_scope TEXT NOT NULL DEFAULT 'LATEST_VALID_RUNNING',
            filters_json TEXT NOT NULL DEFAULT '{}',
            is_favorite INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_used_at TEXT NOT NULL DEFAULT ''
        )
        """
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_search_documents_device "
        "ON config_search_documents(device_id, indexed_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_search_objects_snapshot "
        "ON config_search_objects(snapshot_id, object_type)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_search_objects_device "
        "ON config_search_objects(device_id, object_type, object_key)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_search_audit_actor_time "
        "ON config_search_audit(actor_username, created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_saved_config_searches_owner "
        "ON saved_config_searches(owner_username, updated_at)"
    )

