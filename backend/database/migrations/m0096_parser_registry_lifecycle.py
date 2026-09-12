"""Add durable audit events for the TextFSM registry lifecycle."""

from __future__ import annotations


VERSION = 96
NAME = "parser_registry_lifecycle"


def upgrade(cursor, use_pg: bool) -> None:
    """Create the parser audit log table and its lookup indexes.

    The migration deliberately uses the same portable SQL style as the rest
    of the registry migrations so an existing SQLite development database and
    PostgreSQL production database converge on the same contract.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS parser_template_audit_logs (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            version_id TEXT,
            event_type TEXT NOT NULL,
            actor_id TEXT,
            actor_username TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (template_id) REFERENCES parser_templates(id) ON DELETE CASCADE,
            FOREIGN KEY (version_id) REFERENCES parser_template_versions(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_parser_template_audit_template "
        "ON parser_template_audit_logs(template_id, created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_parser_template_audit_version "
        "ON parser_template_audit_logs(version_id, created_at)"
    )
