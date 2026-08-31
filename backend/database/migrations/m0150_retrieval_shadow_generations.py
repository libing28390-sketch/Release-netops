"""PostgreSQL shadow retrieval generations with atomic cutover.

The legacy ``ai_document`` / ``ai_document_chunk`` projection remains the V1
write and rebuild authority.  This migration adds an additive, tenant-scoped
shadow copy for testing a new FTS/trigram/vector index before switching reads.
SQLite is deliberately a compatibility no-op; PostgreSQL is the only
production and acceptance authority for this contract.
"""

from __future__ import annotations

from database.postgres_extensions import ensure_required_extensions


VERSION = 150
NAME = "retrieval_shadow_generations"


def upgrade(cursor, use_pg: bool) -> None:
    pass

    ensure_required_extensions(cursor, names=("vector", "pg_trgm"), create_missing=True)

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_retrieval_index_generation (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            generation_no INTEGER NOT NULL CHECK (generation_no > 0),
            index_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'building'
                CHECK (status IN ('building','shadow','ready','active','superseded','failed','rolled_back')),
            previous_generation_id TEXT,
            document_count INTEGER NOT NULL DEFAULT 0 CHECK (document_count >= 0),
            chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
            verification_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            build_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            failure_code TEXT,
            actor_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            activated_at TEXT,
            rolled_back_at TEXT,
            UNIQUE (tenant_id, generation_no),
            UNIQUE (tenant_id, index_version),
            FOREIGN KEY (previous_generation_id) REFERENCES ai_retrieval_index_generation(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_retrieval_index_shadow_chunk (
            generation_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            page INTEGER,
            section TEXT,
            parent_chunk_id TEXT,
            chunk_role TEXT,
            chunk_type TEXT,
            ordinal INTEGER NOT NULL DEFAULT 0,
            raw_content TEXT,
            embedding_content TEXT,
            heading_path_json TEXT,
            token_count INTEGER,
            content_hash TEXT,
            source_locator_json TEXT,
            chunking_version TEXT,
            is_retrieval_candidate INTEGER NOT NULL DEFAULT 1,
            oversize_reason TEXT,
            document_id_metadata TEXT,
            document_category TEXT,
            vendor TEXT,
            product_series TEXT,
            product_model TEXT,
            software_train TEXT,
            software_release TEXT,
            cli_platform TEXT,
            feature_domain TEXT,
            feature TEXT,
            subfeature TEXT,
            risk_level TEXT,
            verification_level TEXT,
            rag_priority TEXT,
            chunk_index INTEGER,
            embedding_model TEXT,
            embedding_dimensions INTEGER,
            embedding_version TEXT,
            chunker_version TEXT,
            structure_types_json TEXT,
            neighbor_chunk_ids_json TEXT,
            parser_version TEXT,
            document_version TEXT,
            index_version TEXT,
            embedding_mode TEXT,
            embedding_contract_version TEXT,
            search_text TEXT,
            retrieval_index_version TEXT,
            embedding_vector vector(1536),
            created_at TEXT NOT NULL,
            PRIMARY KEY (generation_id, tenant_id, id),
            FOREIGN KEY (generation_id) REFERENCES ai_retrieval_index_generation(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_retrieval_generation_tenant_status
        ON ai_retrieval_index_generation(tenant_id, status, generation_no DESC)
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_retrieval_generation_active
        ON ai_retrieval_index_generation(tenant_id)
        WHERE status = 'active'
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_retrieval_shadow_tenant_candidate
        ON ai_retrieval_index_shadow_chunk(tenant_id, generation_id, is_retrieval_candidate, document_id, ordinal, id)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_retrieval_shadow_fts
        ON ai_retrieval_index_shadow_chunk USING GIN
        (to_tsvector('simple', COALESCE(search_text, '')))
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_retrieval_shadow_trgm
        ON ai_retrieval_index_shadow_chunk USING GIN (search_text gin_trgm_ops)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_retrieval_shadow_vector_hnsw
        ON ai_retrieval_index_shadow_chunk USING hnsw (embedding_vector vector_cosine_ops)
        """
    )


def downgrade(cursor, use_pg: bool) -> None:
    # Shadow generations are audit/release evidence.  Rollback is an atomic
    # pointer change performed by RetrievalIndexService, not destructive DDL.
    return None
