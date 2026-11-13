"""Add alternate-source observations for ING-014 content merging.

Source Registry/Source Version rows remain immutable facts per URL.  This
additive relation lets compatible same-hash versions from different URLs
point at one canonical V2 Document Version without deleting or rewriting any
source provenance.
"""

from __future__ import annotations


VERSION = 118
NAME = "knowledge_v2_document_sources"


def _json_type(use_pg: bool) -> tuple[str, str]:
    return "JSONB", "'{}'::jsonb"
    return "TEXT", "'{}'"


def _time_type(use_pg: bool) -> str:
    return "TIMESTAMPTZ"


def upgrade(cursor, use_pg: bool) -> None:
    json_type, json_default = _json_type(use_pg)
    time_type = _time_type(use_pg)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS kb_document_source (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            document_version_id TEXT NOT NULL,
            source_registry_id TEXT NOT NULL,
            source_version_id TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
            observed_at {time_type} NOT NULL,
            observation_count INTEGER NOT NULL DEFAULT 1 CHECK (observation_count > 0),
            metadata_json {json_type} NOT NULL DEFAULT {json_default},
            status TEXT NOT NULL DEFAULT 'observed' CHECK (status IN ('observed','active','superseded','quarantined')),
            created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, source_version_id),
            UNIQUE (tenant_id, document_version_id, source_registry_id),
            FOREIGN KEY (tenant_id, document_id)
                REFERENCES kb_document(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY (tenant_id, document_version_id)
                REFERENCES kb_document_version(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY (tenant_id, source_registry_id)
                REFERENCES kb_source_registry(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY (tenant_id, source_version_id)
                REFERENCES kb_source_version(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_kb_document_source_document ON kb_document_source(tenant_id, document_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_kb_document_source_document_version ON kb_document_source(tenant_id, document_version_id, observed_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_kb_document_source_source_version ON kb_document_source(tenant_id, source_version_id, observed_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_kb_document_source_hash ON kb_document_source(tenant_id, content_hash)",
        "CREATE INDEX IF NOT EXISTS ix_kb_document_source_registry ON kb_document_source(tenant_id, source_registry_id, observed_at DESC)",
    ):
        cursor.execute(statement)


def downgrade(cursor, use_pg: bool) -> None:
    # Provenance observations are retained. Disable the merge adapter instead
    # of dropping source lineage or deleting rows.
    return None
