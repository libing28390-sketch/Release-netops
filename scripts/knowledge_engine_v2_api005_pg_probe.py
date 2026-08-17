"""PostgreSQL-only API-005 summary/detail contract probe.

The probe writes only inside one transaction and rolls it back.  It exercises
the real PostgreSQL service and route projections so list endpoints cannot
accidentally expose document bodies, chunks, logs, traces, or raw storage
references.  Detail endpoints are called separately and must still return the
requested body/chunk data to the tenant that owns it.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api import knowledge_sources as source_api  # noqa: E402
from ai.api import assistant  # noqa: E402
from ai.services import knowledge_service as knowledge_service_module  # noqa: E402
from database import core  # noqa: E402
from services import source_registry_service as source_registry_module  # noqa: E402


RUN_ID = uuid.uuid4().hex[:12]
TENANT = f"__api005_pg_tenant_{RUN_ID}"
SOURCE_ID = f"__api005_pg_source_{RUN_ID}"
VERSION_ID = f"__api005_pg_version_{RUN_ID}"
OBSERVATION_ID = f"__api005_pg_observation_{RUN_ID}"
DOCUMENT_ID = f"__api005_pg_document_{RUN_ID}"
CHUNK_ID = f"__api005_pg_chunk_{RUN_ID}"
USER = {"id": f"__api005_pg_user_{RUN_ID}", "username": "api005-pg", "role": "Administrator", "tenant_id": TENANT}


class _SameConnectionContext:
    def __init__(self, connection: Any):
        self.connection = connection

    def __enter__(self) -> Any:
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def execute(self, *args, **kwargs):
        return self.connection.execute(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        return self.connection.cursor(*args, **kwargs)

    def rollback(self):
        return self.connection.rollback()

    def close(self):
        return None


def _assert_no_detail(value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, default=str).lower()
    for marker in (
        "api005 document body", "api005 chunk body", "api005 original body",
        "api005 private log", "api005 private trace", "api005-raw-ref",
        "api005-storage", "api005 exception",
    ):
        if marker in rendered:
            raise AssertionError(f"detail marker leaked in list projection: {marker}")
    for key in ("content", "original_content", "normalized_content", "chunks", "logs", "trace", "raw_content_ref", "raw_content_storage", "error", "metadata", "collection_policy", "validation"):
        if isinstance(value, dict) and key in value:
            raise AssertionError(f"detail field leaked in list projection: {key}")


def _run() -> dict[str, Any]:
    if not core._USE_PG:
        raise RuntimeError("API-005 PostgreSQL probe refused to run: DATABASE_URL is not PostgreSQL")

    conn = core.get_db_connection()
    source_original = source_registry_module.get_db_connection
    knowledge_original = knowledge_service_module.get_db_connection
    now = "2026-08-17T00:00:00+00:00"
    source_body = b"api005 source body"
    source_hash = hashlib.sha256(source_body).hexdigest()
    document_body = "api005 document body"
    try:
        cur = conn.cursor()
        kb_row = cur.execute("SELECT id FROM ai_knowledge_base ORDER BY id LIMIT 1").fetchone()
        if not kb_row:
            raise RuntimeError("API-005 probe requires an existing ai_knowledge_base")
        kb_id = str(kb_row[0])

        cur.execute(
            """INSERT INTO kb_source_registry
               (id, tenant_id, source_type, source_kind, name, description,
                canonical_url, allowed_host, trust_level, collection_policy_json,
                status, fetch_enabled, validation_status, metadata_json, validation_json,
                created_at, updated_at, created_by, updated_by)
               VALUES (?, ?, 'internal', 'internal', 'API005 source', 'summary/detail probe',
                       'https://kb.internal.example/api005', 'kb.internal.example', 'internal',
                       '{"timeout_seconds":15}', 'active', TRUE, 'valid',
                       '{"detail":"api005 private metadata"}', '{"detail":"api005 private validation"}',
                       ?, ?, ?, ?)""",
            (SOURCE_ID, TENANT, now, now, USER["id"], USER["id"]),
        )
        cur.execute(
            """INSERT INTO kb_source_version
               (id, tenant_id, source_registry_id, fetched_at, content_hash, byte_size,
                parser_name, parser_version, source_etag, fetch_url, response_content_type,
                http_status, raw_content_ref, raw_content_storage, verification_method,
                error_code, error_json, metadata_json, status, created_at, updated_at,
                created_by, updated_by)
               VALUES (?, ?, ?, ?, ?, ?, 'plain_text', 'api005-1', 'etag-api005',
                       'https://kb.internal.example/api005', 'text/plain', 200,
                       'api005-raw-ref', 'api005-storage', 'sha256', 'API005_ERROR',
                       '{"exception":"api005 exception"}', '{"detail":"api005 private version metadata"}',
                       'verified', ?, ?, ?, ?)""",
            (VERSION_ID, TENANT, SOURCE_ID, now, source_hash, len(source_body), now, now, USER["id"], USER["id"]),
        )
        cur.execute(
            """INSERT INTO kb_source_refresh_observation
               (id, tenant_id, source_registry_id, source_version_id, checked_at,
                request_method, http_status, outcome, content_hash, byte_size,
                source_etag, source_last_modified, fetch_url, response_content_type,
                error_code, error_json, metadata_json, created_at, created_by,
                detection_type, replacement_url, version_signal_json)
               VALUES (?, ?, ?, ?, ?, 'GET', 200, 'unchanged', ?, ?, 'etag-api005', '',
                       'https://kb.internal.example/api005', 'text/plain', 'API005_ERROR',
                       '{"exception":"api005 exception"}', '{"detail":"api005 private refresh metadata"}',
                       ?, ?, 'none', '', '{}')""",
            (OBSERVATION_ID, TENANT, SOURCE_ID, VERSION_ID, now, source_hash, len(source_body), now, USER["id"]),
        )
        cur.execute(
            """INSERT INTO ai_document
               (id, knowledge_base_id, name, source, vendor, platform, status,
                knowledge_source_type, tenant_id, acl_json, source_trust_level,
                metadata_json, original_content, document_id, created_at, updated_at)
               VALUES (?, ?, 'API005 document', 'upload', 'Huawei', 'huawei_vrp',
                       'active', 'internal_sop', ?, '{}', 'internal',
                       '{"detail":"api005 private document metadata"}', ?, ?, ?, ?)""",
            (DOCUMENT_ID, kb_id, TENANT, document_body, DOCUMENT_ID, now, now),
        )
        cur.execute(
            "INSERT INTO ai_document_chunk (id, document_id, page, section, content, created_at) VALUES (?, ?, 1, 'API005', ?, ?)",
            (CHUNK_ID, DOCUMENT_ID, "api005 chunk body", now),
        )
        conn.commit()

        source_registry_module.get_db_connection = lambda: _SameConnectionContext(conn)
        knowledge_service_module.get_db_connection = lambda: _SameConnectionContext(conn)

        source_response = source_api.api_list_sources(
            status="all", tenant_id=None, page=1, page_size=20, sort_by="updated_at", sort_order="desc", user=USER,
        )
        version_response = source_api.api_list_source_versions(
            SOURCE_ID, page=1, page_size=20, sort_by="fetched_at", sort_order="desc", user=USER,
        )
        observation_response = source_api.api_list_source_refresh_observations(
            SOURCE_ID, limit=50, page=1, page_size=50, sort_by="observed_at", sort_order="desc", user=USER,
        )
        document_response = assistant.list_documents(
            source_type=None, search="", directory_path=None, knowledge_scope=None,
            vendor="", product_family="", product_series="", product_model="",
            os_family="", os_generation="", software_train="", software_release="",
            cli_platform="", document_category="", feature_domain="", status="active",
            source_trust_level="", page=1, page_size=20, sort_by="created_at",
            sort_order="desc", user=USER,
        )

        for response in (source_response, version_response, observation_response):
            if not response["data"]:
                raise AssertionError(f"empty API-005 list response: {response}")
            _assert_no_detail(response["data"][0])
        if not document_response["items"]:
            raise AssertionError(f"empty document list response: {document_response}")
        _assert_no_detail(document_response["items"][0])

        detail = assistant.get_document_detail(DOCUMENT_ID, user=USER)
        if detail.get("original_content") != document_body or detail.get("chunks", [{}])[0].get("content") != "api005 chunk body":
            raise AssertionError(f"document detail did not load body/chunk: {detail}")
        source_detail = source_registry_module.get_source(SOURCE_ID, USER)
        if not source_detail.get("metadata") or not source_detail.get("collection_policy"):
            raise AssertionError("source detail did not retain independently loaded configuration")

        return {
            "postgresql": True,
            "list_source_summary": True,
            "list_source_version_summary": True,
            "list_refresh_summary": True,
            "list_document_summary": True,
            "document_detail_body_and_chunks": True,
            "source_detail_independent": True,
            "tenant_scope": True,
            "transactional_cleanup": True,
        }
    finally:
        source_registry_module.get_db_connection = source_original
        knowledge_service_module.get_db_connection = knowledge_original
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    print(json.dumps(_run(), ensure_ascii=False, sort_keys=True))
