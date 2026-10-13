"""Create the durable tree used to organize uploaded knowledge documents."""

from __future__ import annotations

VERSION = 112
NAME = "ai_knowledge_directories"


def upgrade(cursor, use_pg: bool) -> None:
    """Create the tenant-scoped knowledge directory tree.

    Directory names and paths are intentionally stored as text.  The physical
    ``kb_import`` folders are an import convention; this table is the source
    of truth for the UI and for document metadata, so custom sub-directories
    survive restarts and are available to every user in the tenant.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_knowledge_directory (
            id TEXT PRIMARY KEY,
            knowledge_base_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            parent_id TEXT,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            depth INTEGER NOT NULL DEFAULT 0,
            is_system INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (knowledge_base_id) REFERENCES ai_knowledge_base(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_id) REFERENCES ai_knowledge_directory(id) ON DELETE CASCADE,
            UNIQUE (knowledge_base_id, tenant_id, path)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_knowledge_directory_tree
        ON ai_knowledge_directory(tenant_id, knowledge_base_id, parent_id, sort_order, name)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_knowledge_directory_state (
            knowledge_base_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            defaults_seeded INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (knowledge_base_id, tenant_id),
            FOREIGN KEY (knowledge_base_id) REFERENCES ai_knowledge_base(id) ON DELETE CASCADE
        )
        """
    )
