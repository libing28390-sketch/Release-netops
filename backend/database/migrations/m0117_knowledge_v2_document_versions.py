"""Add the shadow Knowledge Engine V2 document/version fact tables.

ING-013 needs a durable append-only boundary after CAT/ING source versions
exist.  The tables are additive: legacy ``ai_document`` and
``ai_document_chunk`` remain untouched and continue to serve V1.  Collection
and explicit applicability links are intentionally left to DB-013/DB-009
follow-up migrations; ``collection_id`` is a required legacy-compatible
boundary here so a document can be versioned without a cutover.
"""

from __future__ import annotations


VERSION = 117
NAME = "knowledge_v2_document_versions"

_DOCUMENT_STATUSES = "'draft','active','disabled','archived','deleted','quarantined','purged'"
_VERSION_STATUSES = _DOCUMENT_STATUSES
_DOCUMENT_KINDS = "'official_manual','product_registry','command_reference','configuration','cli_output','troubleshooting','example','enterprise_sop','user_note'"
_TRUST_LEVELS = "'official','reviewed','internal','untrusted'"


def _json_type(use_pg: bool) -> tuple[str, str]:
    if use_pg:
        return "JSONB", "'{}'::jsonb"
    return "TEXT", "'{}'"


def _time_type(use_pg: bool) -> str:
    return "TIMESTAMPTZ" if use_pg else "TEXT"


def _create_document_table(cursor, use_pg: bool) -> None:
    json_type, json_default = _json_type(use_pg)
    time_type = _time_type(use_pg)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS kb_document (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            collection_id TEXT NOT NULL DEFAULT 'legacy-default',
            source_registry_id TEXT NOT NULL,
            canonical_key TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            document_kind TEXT NOT NULL DEFAULT 'official_manual' CHECK (document_kind IN ({_DOCUMENT_KINDS})),
            description TEXT NOT NULL DEFAULT '',
            language TEXT NOT NULL DEFAULT '',
            publisher TEXT NOT NULL DEFAULT '',
            source_uri TEXT NOT NULL DEFAULT '',
            trust_level TEXT NOT NULL DEFAULT 'official' CHECK (trust_level IN ({_TRUST_LEVELS})),
            acl_json {json_type} NOT NULL DEFAULT {json_default},
            metadata_json {json_type} NOT NULL DEFAULT {json_default},
            current_version_id TEXT,
            retention_class TEXT NOT NULL DEFAULT '',
            source_kind TEXT NOT NULL DEFAULT 'official_url',
            canonical_source TEXT NOT NULL DEFAULT 'source_registry',
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ({_DOCUMENT_STATUSES})),
            created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, source_registry_id, canonical_key),
            FOREIGN KEY (tenant_id, source_registry_id)
                REFERENCES kb_source_registry(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_kb_document_tenant_status ON kb_document(tenant_id, status, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_kb_document_source ON kb_document(tenant_id, source_registry_id, canonical_key)",
        "CREATE INDEX IF NOT EXISTS ix_kb_document_current_version ON kb_document(tenant_id, current_version_id)",
    ):
        cursor.execute(statement)


def _create_version_table(cursor, use_pg: bool) -> None:
    json_type, json_default = _json_type(use_pg)
    time_type = _time_type(use_pg)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS kb_document_version (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            source_version_id TEXT NOT NULL,
            version_no INTEGER NOT NULL CHECK (version_no > 0),
            original_content TEXT NOT NULL DEFAULT '',
            normalized_content TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
            metadata_json {json_type} NOT NULL DEFAULT {json_default},
            metadata_hash TEXT NOT NULL DEFAULT '',
            parser_name TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            trust_level TEXT NOT NULL DEFAULT 'official' CHECK (trust_level IN ({_TRUST_LEVELS})),
            acl_json {json_type} NOT NULL DEFAULT {json_default},
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ({_VERSION_STATUSES})),
            mime_type TEXT NOT NULL DEFAULT '',
            byte_size BIGINT NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
            original_content_ref TEXT NOT NULL DEFAULT '',
            normalized_content_hash TEXT NOT NULL DEFAULT '',
            metadata_parse_status TEXT NOT NULL DEFAULT 'missing',
            metadata_parse_error TEXT NOT NULL DEFAULT '',
            fetched_at {time_type},
            approved_at {time_type},
            approved_by TEXT NOT NULL DEFAULT '',
            supersedes_version_id TEXT,
            created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, document_id, version_no),
            UNIQUE (tenant_id, document_id, content_hash),
            FOREIGN KEY (tenant_id, document_id)
                REFERENCES kb_document(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY (tenant_id, source_version_id)
                REFERENCES kb_source_version(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY (tenant_id, supersedes_version_id)
                REFERENCES kb_document_version(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_kb_document_version_document_time ON kb_document_version(tenant_id, document_id, version_no DESC)",
        "CREATE INDEX IF NOT EXISTS ix_kb_document_version_source ON kb_document_version(tenant_id, source_version_id)",
        "CREATE INDEX IF NOT EXISTS ix_kb_document_version_status ON kb_document_version(tenant_id, status, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_kb_document_version_hash ON kb_document_version(tenant_id, content_hash)",
    ):
        cursor.execute(statement)


def _create_fact_guard(cursor, use_pg: bool) -> None:
    """Protect the original/hash/source facts while allowing lifecycle updates."""
    if use_pg:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION kb_document_version_fact_immutable_guard()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                   OR NEW.document_id IS DISTINCT FROM OLD.document_id
                   OR NEW.source_version_id IS DISTINCT FROM OLD.source_version_id
                   OR NEW.version_no IS DISTINCT FROM OLD.version_no
                   OR NEW.original_content IS DISTINCT FROM OLD.original_content
                   OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                   OR NEW.parser_name IS DISTINCT FROM OLD.parser_name
                   OR NEW.parser_version IS DISTINCT FROM OLD.parser_version
                   OR NEW.fetched_at IS DISTINCT FROM OLD.fetched_at
                THEN
                    RAISE EXCEPTION 'kb_document_version_fact_immutable';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
        cursor.execute("DROP TRIGGER IF EXISTS trg_kb_document_version_fact_immutable ON kb_document_version")
        cursor.execute(
            """
            CREATE TRIGGER trg_kb_document_version_fact_immutable
            BEFORE UPDATE ON kb_document_version
            FOR EACH ROW EXECUTE FUNCTION kb_document_version_fact_immutable_guard()
            """
        )
        return

    cursor.execute("DROP TRIGGER IF EXISTS trg_kb_document_version_fact_immutable")
    cursor.execute(
        """
        CREATE TRIGGER trg_kb_document_version_fact_immutable
        BEFORE UPDATE ON kb_document_version
        FOR EACH ROW
        WHEN NEW.tenant_id IS NOT OLD.tenant_id
          OR NEW.document_id IS NOT OLD.document_id
          OR NEW.source_version_id IS NOT OLD.source_version_id
          OR NEW.version_no IS NOT OLD.version_no
          OR NEW.original_content IS NOT OLD.original_content
          OR NEW.content_hash IS NOT OLD.content_hash
          OR NEW.parser_name IS NOT OLD.parser_name
          OR NEW.parser_version IS NOT OLD.parser_version
          OR NEW.fetched_at IS NOT OLD.fetched_at
        BEGIN
            SELECT RAISE(ABORT, 'kb_document_version_fact_immutable');
        END
        """
    )


def upgrade(cursor, use_pg: bool) -> None:
    _create_document_table(cursor, use_pg)
    _create_version_table(cursor, use_pg)
    _create_fact_guard(cursor, use_pg)


def downgrade(cursor, use_pg: bool) -> None:
    # Version facts are provenance.  Rollback disables the adapter; it never
    # drops tables or deletes original/hash facts.
    return None

