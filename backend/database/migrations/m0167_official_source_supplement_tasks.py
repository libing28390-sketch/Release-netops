"""Persist reviewed official-source supplementation tasks for retrieval misses."""

VERSION = 167
NAME = "official_source_supplement_tasks"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS official_source_suggestion (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            request_id TEXT,
            query_hash TEXT NOT NULL,
            vendor TEXT NOT NULL,
            product_model TEXT,
            software_release TEXT,
            feature TEXT,
            label TEXT NOT NULL,
            suggested_url TEXT NOT NULL,
            reviewed_url TEXT,
            source_kind TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewer_id TEXT,
            reviewed_at TEXT,
            source_registry_id TEXT,
            ingestion_job_id TEXT,
            document_id TEXT,
            recheck_trace_id TEXT,
            recheck_status TEXT,
            error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, trace_id, suggested_url)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_official_source_suggestion_tenant_status ON official_source_suggestion(tenant_id, status, updated_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_official_source_suggestion_trace ON official_source_suggestion(tenant_id, trace_id)")

