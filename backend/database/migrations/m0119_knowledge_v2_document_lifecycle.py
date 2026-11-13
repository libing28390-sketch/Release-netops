"""Add the durable ING-015 document lifecycle boundary.

The V2 shadow tables already expose the legacy ``status`` column used by the
V1-compatible adapters.  ING-015 adds an explicit lifecycle projection so the
new publication/quarantine/supersession states do not force a rewrite of V1
status semantics.  Every transition is recorded once per tenant request and
uses a compare-and-set revision in the service layer.
"""

from __future__ import annotations


VERSION = 119
NAME = "knowledge_v2_document_lifecycle"

_LIFECYCLE_VALUES = "'draft','active','published','quarantined','superseded','disabled','archived','deleted','purged','failed'"

_COLUMNS = {
    "lifecycle_status": f"TEXT NOT NULL DEFAULT 'draft' CHECK (lifecycle_status IN ({_LIFECYCLE_VALUES}))",
    "lifecycle_revision": "INTEGER NOT NULL DEFAULT 0 CHECK (lifecycle_revision >= 0)",
    "lifecycle_changed_at": "TEXT",
    "lifecycle_changed_by": "TEXT NOT NULL DEFAULT ''",
    "lifecycle_reason": "TEXT NOT NULL DEFAULT ''",
    "published_at": "TEXT",
    "published_by": "TEXT NOT NULL DEFAULT ''",
    "quarantined_at": "TEXT",
    "quarantined_by": "TEXT NOT NULL DEFAULT ''",
    "quarantine_reason": "TEXT NOT NULL DEFAULT ''",
    "superseded_at": "TEXT",
    "superseded_by": "TEXT NOT NULL DEFAULT ''",
    "superseded_by_version_id": "TEXT",
    "disabled_at": "TEXT",
    "disabled_by": "TEXT NOT NULL DEFAULT ''",
    "disable_reason": "TEXT NOT NULL DEFAULT ''",
    "legal_hold": "INTEGER NOT NULL DEFAULT 0 CHECK (legal_hold IN (0,1))",
}


def _table_columns(cursor, table: str, use_pg: bool) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    )
    return {str(row[0]) for row in cursor.fetchall()}



def _add_columns(cursor, table: str, use_pg: bool) -> None:
    existing = _table_columns(cursor, table, use_pg)
    for name, definition in _COLUMNS.items():
        if name in existing:
            continue
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {definition}")


def _seed_lifecycle_projection(cursor, table: str) -> None:
    cursor.execute(
        f"""
        UPDATE {table}
        SET lifecycle_status = CASE status
            WHEN 'active' THEN 'published'
            WHEN 'quarantined' THEN 'quarantined'
            WHEN 'disabled' THEN 'disabled'
            WHEN 'archived' THEN 'archived'
            WHEN 'deleted' THEN 'deleted'
            WHEN 'purged' THEN 'purged'
            WHEN 'failed' THEN 'failed'
            ELSE 'draft'
        END
        WHERE lifecycle_status = 'draft' AND status <> 'draft'
        """
    )


def _create_event_table(cursor, use_pg: bool) -> None:
    time_type = "TIMESTAMPTZ"
    json_type = "JSONB"
    json_default = "'{}'::jsonb"
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS kb_document_lifecycle_event (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            document_version_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            from_status TEXT NOT NULL,
            to_status TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            actor_id TEXT NOT NULL,
            created_at {time_type} NOT NULL,
            result_json {json_type} NOT NULL DEFAULT {json_default},
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, request_id),
            FOREIGN KEY (tenant_id, document_id)
                REFERENCES kb_document(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY (tenant_id, document_version_id)
                REFERENCES kb_document_version(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_kb_document_lifecycle_event_document ON kb_document_lifecycle_event(tenant_id, document_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_kb_document_lifecycle_event_version ON kb_document_lifecycle_event(tenant_id, document_version_id, created_at DESC)",
    ):
        cursor.execute(statement)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_document_lifecycle_status ON kb_document(tenant_id, lifecycle_status, updated_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_document_version_lifecycle_status ON kb_document_version(tenant_id, lifecycle_status, updated_at)"
    )


def upgrade(cursor, use_pg: bool) -> None:
    _add_columns(cursor, "kb_document", use_pg)
    _add_columns(cursor, "kb_document_version", use_pg)
    _seed_lifecycle_projection(cursor, "kb_document")
    _seed_lifecycle_projection(cursor, "kb_document_version")
    _create_event_table(cursor, use_pg)


def downgrade(cursor, use_pg: bool) -> None:
    # Lifecycle history is audit/provenance. Disable the adapter rather than
    # dropping transition events or rewriting the V1-compatible status fields.
    return None
