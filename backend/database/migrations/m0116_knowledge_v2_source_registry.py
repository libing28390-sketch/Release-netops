"""Create the tenant-scoped Knowledge Engine V2 source registry.

CAT-003 is the first executable boundary for the DB-008 contract.  The
tables are additive and deliberately do not touch the V1 ``ai_document``
rows.  PostgreSQL remains the production authority; SQLite receives the same
relational columns and constraints for deterministic local tests.
"""

from __future__ import annotations


VERSION = 116
NAME = "knowledge_v2_source_registry"


_REGISTRY_STATUSES = "'draft','active','disabled','archived','deleted','quarantined','purged'"
_VERSION_STATUSES = "'draft','active','disabled','archived','deleted','quarantined','purged','fetched','verified','failed'"
_SOURCE_TYPES = "'official_vendor','official_product','enterprise','internal','user_upload','api'"
_TRUST_LEVELS = "'official','reviewed','internal','untrusted'"
_SOURCE_KINDS = "'official_url','product_page','configuration_guide','command_reference','release_note','product_support','enterprise','internal','user_upload','api'"


def _json_type(use_pg: bool) -> tuple[str, str]:
    if use_pg:
        return "JSONB", "'{}'::jsonb"
    return "TEXT", "'{}'"


def _time_type(use_pg: bool) -> str:
    return "TIMESTAMPTZ" if use_pg else "TEXT"


def _bool_type(use_pg: bool) -> tuple[str, str]:
    return ("BOOLEAN", "FALSE") if use_pg else ("INTEGER", "0")


def _create_registry_table(cursor, use_pg: bool) -> None:
    json_type, json_default = _json_type(use_pg)
    time_type = _time_type(use_pg)
    bool_type, bool_default = _bool_type(use_pg)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS kb_source_registry (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK (source_type IN ({_SOURCE_TYPES})),
            source_kind TEXT NOT NULL DEFAULT 'official_url' CHECK (source_kind IN ({_SOURCE_KINDS})),
            name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            canonical_url TEXT NOT NULL,
            allowed_host TEXT NOT NULL,
            allowed_scheme TEXT NOT NULL DEFAULT 'https',
            allowed_port INTEGER NOT NULL DEFAULT 443,
            host_match_mode TEXT NOT NULL DEFAULT 'exact' CHECK (host_match_mode IN ('exact','explicit_subdomain')),
            trust_level TEXT NOT NULL CHECK (trust_level IN ({_TRUST_LEVELS})),
            collection_policy_json {json_type} NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ({_REGISTRY_STATUSES})),
            fetch_enabled {bool_type} NOT NULL DEFAULT {bool_default},
            max_bytes BIGINT NOT NULL DEFAULT 20000000 CHECK (max_bytes > 0),
            timeout_seconds INTEGER NOT NULL DEFAULT 15 CHECK (timeout_seconds > 0),
            redirect_limit INTEGER NOT NULL DEFAULT 3 CHECK (redirect_limit >= 0),
            rate_limit_per_minute INTEGER NOT NULL DEFAULT 30 CHECK (rate_limit_per_minute > 0),
            policy_version INTEGER NOT NULL DEFAULT 1 CHECK (policy_version > 0),
            policy_hash TEXT NOT NULL DEFAULT '',
            metadata_json {json_type} NOT NULL DEFAULT {json_default},
            validation_status TEXT NOT NULL DEFAULT 'unvalidated' CHECK (validation_status IN ('unvalidated','valid','invalid')),
            validation_json {json_type} NOT NULL DEFAULT {json_default},
            lock_version INTEGER NOT NULL DEFAULT 1 CHECK (lock_version > 0),
            deleted_at {time_type},
            deleted_by TEXT,
            deletion_reason TEXT,
            disabled_at {time_type},
            disabled_by TEXT,
            disable_reason TEXT,
            archived_at {time_type},
            archived_by TEXT,
            archive_reason TEXT,
            legal_hold {bool_type} NOT NULL DEFAULT {bool_default},
            created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, canonical_url)
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_kb_source_registry_tenant_status ON kb_source_registry(tenant_id, status, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_kb_source_registry_tenant_host ON kb_source_registry(tenant_id, allowed_host, status)",
        "CREATE INDEX IF NOT EXISTS ix_kb_source_registry_validation ON kb_source_registry(tenant_id, validation_status, status)",
    ):
        cursor.execute(statement)


def _create_version_table(cursor, use_pg: bool) -> None:
    json_type, json_default = _json_type(use_pg)
    time_type = _time_type(use_pg)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS kb_source_version (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            source_registry_id TEXT NOT NULL,
            fetched_at {time_type} NOT NULL,
            content_hash TEXT NOT NULL,
            byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
            parser_name TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            source_etag TEXT NOT NULL DEFAULT '',
            source_last_modified TEXT NOT NULL DEFAULT '',
            fetch_url TEXT NOT NULL DEFAULT '',
            response_content_type TEXT NOT NULL DEFAULT '',
            http_status INTEGER,
            raw_content_ref TEXT NOT NULL DEFAULT '',
            raw_content_storage TEXT NOT NULL DEFAULT '',
            verified_at {time_type},
            verification_method TEXT NOT NULL DEFAULT '',
            error_code TEXT NOT NULL DEFAULT '',
            error_json {json_type} NOT NULL DEFAULT {json_default},
            metadata_json {json_type} NOT NULL DEFAULT {json_default},
            status TEXT NOT NULL CHECK (status IN ({_VERSION_STATUSES})),
            created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, source_registry_id, content_hash),
            FOREIGN KEY (tenant_id, source_registry_id)
                REFERENCES kb_source_registry(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_kb_source_version_registry_time ON kb_source_version(tenant_id, source_registry_id, fetched_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_kb_source_version_hash ON kb_source_version(tenant_id, content_hash)",
        "CREATE INDEX IF NOT EXISTS ix_kb_source_version_status ON kb_source_version(tenant_id, status, fetched_at DESC)",
    ):
        cursor.execute(statement)


def _create_immutable_fact_guard(cursor, use_pg: bool) -> None:
    """Protect the fetch facts even when a caller bypasses the service layer."""
    if use_pg:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION kb_source_version_fact_immutable_guard()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                   OR NEW.source_registry_id IS DISTINCT FROM OLD.source_registry_id
                   OR NEW.fetched_at IS DISTINCT FROM OLD.fetched_at
                   OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                   OR NEW.byte_size IS DISTINCT FROM OLD.byte_size
                   OR NEW.parser_name IS DISTINCT FROM OLD.parser_name
                   OR NEW.parser_version IS DISTINCT FROM OLD.parser_version
                   OR NEW.source_etag IS DISTINCT FROM OLD.source_etag
                   OR NEW.source_last_modified IS DISTINCT FROM OLD.source_last_modified
                   OR NEW.fetch_url IS DISTINCT FROM OLD.fetch_url
                   OR NEW.raw_content_ref IS DISTINCT FROM OLD.raw_content_ref
                THEN
                    RAISE EXCEPTION 'kb_source_version_fact_immutable';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
        cursor.execute("DROP TRIGGER IF EXISTS trg_kb_source_version_fact_immutable ON kb_source_version")
        cursor.execute(
            """
            CREATE TRIGGER trg_kb_source_version_fact_immutable
            BEFORE UPDATE ON kb_source_version
            FOR EACH ROW EXECUTE FUNCTION kb_source_version_fact_immutable_guard()
            """
        )
        return

    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_kb_source_version_fact_immutable
        BEFORE UPDATE ON kb_source_version
        FOR EACH ROW
        WHEN NEW.tenant_id IS NOT OLD.tenant_id
          OR NEW.source_registry_id IS NOT OLD.source_registry_id
          OR NEW.fetched_at IS NOT OLD.fetched_at
          OR NEW.content_hash IS NOT OLD.content_hash
          OR NEW.byte_size IS NOT OLD.byte_size
          OR NEW.parser_name IS NOT OLD.parser_name
          OR NEW.parser_version IS NOT OLD.parser_version
          OR NEW.source_etag IS NOT OLD.source_etag
          OR NEW.source_last_modified IS NOT OLD.source_last_modified
          OR NEW.fetch_url IS NOT OLD.fetch_url
          OR NEW.raw_content_ref IS NOT OLD.raw_content_ref
        BEGIN
            SELECT RAISE(ABORT, 'kb_source_version_fact_immutable');
        END
        """
    )


def upgrade(cursor, use_pg: bool) -> None:
    _create_registry_table(cursor, use_pg)
    _create_version_table(cursor, use_pg)
    _create_immutable_fact_guard(cursor, use_pg)


def downgrade(cursor, use_pg: bool) -> None:
    # Source versions are immutable facts.  A normal rollback disables writes
    # and archives rows; it never drops the tables or deletes provenance.
    return None
