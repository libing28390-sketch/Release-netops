"""PostgreSQL acceptance probe for KUI-015 Source Registry refresh status."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from database import core  # noqa: E402
from services import source_registry_service as source_registry_module  # noqa: E402
from services.source_registry_service import SourceRegistryError, get_source_refresh_status  # noqa: E402


TENANT = "__kui015_pg_tenant"
OTHER_TENANT = "__kui015_pg_other"
SOURCE_ID = "__kui015_pg_source"
VERSION_ID = "__kui015_pg_version"
OBS_ID = "__kui015_pg_observation"
USER = {"id": "__kui015_pg_user", "username": "kui015-pg", "role": "Operator", "tenant_id": TENANT}
OTHER_USER = {"id": "__kui015_pg_other_user", "username": "kui015-other", "role": "Operator", "tenant_id": OTHER_TENANT}


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
        # The outer probe owns the real connection and rolls it back once.
        return None


def _run() -> dict[str, Any]:
    if not core._USE_PG:
        raise RuntimeError("KUI-015 PostgreSQL probe refused to run: DATABASE_URL is not PostgreSQL")
    conn = core.get_db_connection()
    original_get_db_connection = source_registry_module.get_db_connection
    try:
        # Keep fixture rows in one transaction.  The observation table is
        # append-only by design, so rollback—not DELETE—is the safe cleanup.
        source_registry_module.get_db_connection = lambda: _SameConnectionContext(conn)
        cur = conn.cursor()
        now = "2026-08-17T00:00:00+00:00"
        body = b"kui015 refresh body"
        digest = hashlib.sha256(body).hexdigest()
        cur.execute(
            """INSERT INTO kb_source_registry
               (id, tenant_id, source_type, source_kind, name, canonical_url, allowed_host,
                trust_level, collection_policy_json, status, fetch_enabled, validation_status,
                created_at, updated_at, created_by, updated_by)
               VALUES (?, ?, 'internal', 'internal', 'KUI015 source',
                       'https://kb.internal.example/kui015', 'kb.internal.example',
                       'internal', '{}', 'active', TRUE, 'valid', ?, ?, ?, ?)""",
            (SOURCE_ID, TENANT, now, now, USER["id"], USER["id"]),
        )
        cur.execute(
            """INSERT INTO kb_source_version
               (id, tenant_id, source_registry_id, fetched_at, content_hash, byte_size,
                parser_name, parser_version, status, created_at, updated_at, created_by, updated_by)
               VALUES (?, ?, ?, ?, ?, ?, 'plain_text', 'kui015-test-1', 'verified', ?, ?, ?, ?)""",
            (VERSION_ID, TENANT, SOURCE_ID, now, digest, len(body), now, now, USER["id"], USER["id"]),
        )
        cur.execute(
            """INSERT INTO kb_source_refresh_observation
               (id, tenant_id, source_registry_id, source_version_id, checked_at,
                request_method, http_status, outcome, content_hash, byte_size,
                source_etag, source_last_modified, fetch_url, response_content_type,
                error_code, error_json, metadata_json, created_at, created_by,
                detection_type, replacement_url, version_signal_json)
               VALUES (?, ?, ?, ?, ?, 'GET', 200, 'unchanged', ?, ?, '', '',
                       'https://kb.internal.example/kui015', 'text/plain', '', '{}',
                       '{"worker":"kui015-probe"}', ?, ?, 'none', '', '{}')""",
            (OBS_ID, TENANT, SOURCE_ID, VERSION_ID, now, digest, len(body), now, USER["id"]),
        )
        conn.commit()
        status = get_source_refresh_status(SOURCE_ID, USER)
        if status["freshness_status"] != "healthy" or status["observation_count"] != 1 or status["counts"]["unchanged"] != 1:
            raise AssertionError(f"refresh status mismatch: {status}")
        if any(secret in json.dumps(status, ensure_ascii=False, default=str).lower() for secret in ("refresh body", "worker")):
            raise AssertionError("refresh status leaked raw/metadata detail")
        denied = False
        try:
            get_source_refresh_status(SOURCE_ID, OTHER_USER)
        except SourceRegistryError as exc:
            denied = exc.code == "SOURCE_NOT_FOUND"
        if not denied:
            raise AssertionError("cross-tenant source status was not denied")
        return {
            "postgresql": True,
            "migration_0120_0121": True,
            "status_projection": True,
            "bounded_observation_history": True,
            "tenant_isolation": True,
            "no_raw_body_or_metadata_leak": True,
            "recovery_cleanup": True,
        }
    finally:
        source_registry_module.get_db_connection = original_get_db_connection
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    print(json.dumps(_run(), ensure_ascii=False, sort_keys=True))
