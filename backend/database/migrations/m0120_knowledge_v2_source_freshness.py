"""Add append-only source freshness observations for ING-018.

``kb_source_version`` is an immutable fetch fact and therefore cannot be
rewritten when a conditional request observes a new validator or a 304.  This
small tenant-scoped observation table records the periodic check separately;
the source version remains the content/hash authority and no response body is
stored here.
"""

from __future__ import annotations


VERSION = 120
NAME = "knowledge_v2_source_freshness"


def _json_type(use_pg: bool) -> tuple[str, str]:
    return ("JSONB", "'{}'::jsonb")


def _time_type(use_pg: bool) -> str:
    return "TIMESTAMPTZ"


def upgrade(cursor, use_pg: bool) -> None:
    time_type = _time_type(use_pg)
    json_type, json_default = _json_type(use_pg)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS kb_source_refresh_observation (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            source_registry_id TEXT NOT NULL,
            source_version_id TEXT,
            checked_at {time_type} NOT NULL,
            request_method TEXT NOT NULL CHECK (request_method IN ('GET','HEAD')),
            http_status INTEGER CHECK (http_status IS NULL OR (http_status >= 100 AND http_status <= 599)),
            outcome TEXT NOT NULL CHECK (outcome IN ('not_modified','unchanged','changed','failed')),
            content_hash TEXT NOT NULL DEFAULT '' CHECK (content_hash = '' OR length(content_hash) = 64),
            byte_size BIGINT NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
            source_etag TEXT NOT NULL DEFAULT '',
            source_last_modified TEXT NOT NULL DEFAULT '',
            fetch_url TEXT NOT NULL DEFAULT '',
            response_content_type TEXT NOT NULL DEFAULT '',
            error_code TEXT NOT NULL DEFAULT '',
            error_json {json_type} NOT NULL DEFAULT {json_default},
            metadata_json {json_type} NOT NULL DEFAULT {json_default},
            created_at {time_type} NOT NULL,
            created_by TEXT NOT NULL,
            UNIQUE (tenant_id, id),
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
        "CREATE INDEX IF NOT EXISTS ix_kb_source_refresh_source_time ON kb_source_refresh_observation(tenant_id, source_registry_id, checked_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_kb_source_refresh_outcome ON kb_source_refresh_observation(tenant_id, outcome, checked_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_kb_source_refresh_hash ON kb_source_refresh_observation(tenant_id, content_hash)",
    ):
        cursor.execute(statement)


def downgrade(cursor, use_pg: bool) -> None:
    # Refresh observations are audit evidence.  Rollback disables the writer
    # in the application; it must not delete the source freshness timeline.
    return None

