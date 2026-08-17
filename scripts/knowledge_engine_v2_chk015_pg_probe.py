"""PostgreSQL-only CHK-015 Chunk viewer contract probe."""

from __future__ import annotations

import json
import uuid

from database.core import _USE_PG, get_db_connection
import ai.services.knowledge_service as knowledge_module
from ai.services.knowledge_service import KnowledgeService


class _TxProxy:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._conn.cursor()

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def commit(self):
        return None

    def rollback(self):
        return None


class _SameConnection:
    def __init__(self, proxy):
        self.proxy = proxy

    def __enter__(self):
        return self.proxy

    def __exit__(self, *_args):
        return False


def main() -> None:
    if not _USE_PG:
        raise SystemExit("CHK-015 requires PostgreSQL; SQLite is not an acceptance backend")
    base = get_db_connection()
    proxy = _TxProxy(base)
    knowledge_module.get_db_connection = lambda: _SameConnection(proxy)
    try:
        cursor = base.cursor()
        cursor.execute("SELECT id FROM ai_knowledge_base ORDER BY id LIMIT 1")
        kb = cursor.fetchone()
        if not kb:
            raise AssertionError("no PostgreSQL knowledge base fixture exists")
        tenant = f"chk015-{uuid.uuid4().hex[:8]}"
        document_id = f"chk015-doc-{uuid.uuid4().hex[:8]}"
        root_id = f"chk015-root-{uuid.uuid4().hex[:8]}"
        child_id = f"chk015-child-{uuid.uuid4().hex[:8]}"
        neighbor_id = f"chk015-neighbor-{uuid.uuid4().hex[:8]}"
        now = "2026-08-17T00:00:00+00:00"
        metadata = {"vendor": "Huawei", "document_category": "command", "api_key": "must-not-leak", "nested": {"token": "hidden", "feature": "ospf"}}
        cursor.execute(
            """
            INSERT INTO ai_document (
                id, knowledge_base_id, name, source, vendor, platform, status,
                created_at, updated_at, tenant_id, metadata_json, normalized_content,
                original_content, document_id, document_category, product_series,
                source_trust_level, knowledge_source_type, document_version, index_version, parser_version
            ) VALUES (?, ?, 'CHK-015 viewer', 'https://example.invalid/chk015', 'Huawei', 'vrp', 'active', ?, ?, ?, CAST(? AS jsonb), ?, ?, ?, 'command', 'CE6800', 'official', 'official_doc', 'v1', 'retrieval-v1', 'parser-v2')
            """,
            (document_id, str(kb[0]), now, now, tenant, json.dumps(metadata), "normalized", "original", "semantic-chk015"),
        )
        rows = [
            (root_id, "Root command", "root", None, 0, "[\"Root\"]", "{\"page\":1,\"line_start\":1}", "[]"),
            (child_id, "Child command", "child", root_id, 1, "[\"Root\",\"Child\"]", "{\"page\":2,\"line_start\":10}", json.dumps([root_id, neighbor_id])),
            (neighbor_id, "Neighbor output", "neighbor", None, 2, "[\"Output\"]", "{\"page\":3,\"line_start\":20}", json.dumps([child_id])),
        ]
        for chunk_id, section, role, parent_id, ordinal, heading, locator, neighbors in rows:
            cursor.execute(
                """
                INSERT INTO ai_document_chunk (
                    id, document_id, content, metadata_json, page, section, created_at,
                    parent_chunk_id, chunk_role, chunk_type, ordinal, heading_path_json,
                    source_locator_json, token_count, content_hash, chunking_version,
                    document_version, index_version, parser_version, neighbor_chunk_ids_json,
                    is_retrieval_candidate
                ) VALUES (?, ?, ?, CAST(? AS jsonb), ?, ?, ?, ?, ?, 'command', ?, ?, ?, ?, ?, 'v2', 'v1', 'retrieval-v1', 'parser-v2', ?, 1)
                """,
                (chunk_id, document_id, f"content for {section}", json.dumps(metadata), ordinal + 1, section, now,
                 parent_id, role, ordinal, heading, locator, 10 + ordinal, f"hash-{ordinal}", neighbors),
            )

        service = KnowledgeService()
        detail = service.get_document_detail(document_id, tenant_id=tenant)
        if not detail or len(detail.get("chunks") or []) != 3:
            raise AssertionError(f"chunk detail missing: {detail}")
        chunks = detail["chunks"]
        child = next(item for item in chunks if item["id"] == child_id)
        if child.get("parent_chunk", {}).get("id") != root_id:
            raise AssertionError("parent chunk relation was not returned")
        if not any(item.get("id") == neighbor_id for item in child.get("neighbors") or []):
            raise AssertionError("neighbor chunk relation was not returned")
        if child.get("source_locator", {}).get("page") != 2:
            raise AssertionError("source locator was not returned")
        if child.get("metadata", {}).get("api_key") is not None or child.get("metadata", {}).get("nested", {}).get("token") is not None:
            raise AssertionError("sensitive metadata leaked")
        if child.get("chunking_version") != "v2" or child.get("parser_version") != "parser-v2" or child.get("document_version") != "v1":
            raise AssertionError("chunk version lineage missing")
        if service.get_document_detail(document_id, tenant_id=f"other-{tenant}") is not None:
            raise AssertionError("cross-tenant document detail was visible")
        rendered = repr(detail).lower()
        if "embedding" in rendered or "api_key" in rendered or "must-not-leak" in rendered or "hidden" in rendered:
            raise AssertionError("detail response contains forbidden fields/secrets")
        cursor.execute("SELECT COUNT(*) FROM ai_document_chunk WHERE document_id = ?", (document_id,))
        if int((cursor.fetchone() or [0])[0]) != 3:
            raise AssertionError("V1 chunk rows changed")
        base.rollback()
        print(json.dumps({
            "status": "PASS",
            "database": "PostgreSQL",
            "chunk_count": 3,
            "parent_relation": True,
            "neighbor_relation": True,
            "metadata_redacted": True,
            "source_locator": True,
            "version_lineage": True,
            "tenant_isolation": True,
            "v1_preserved": True,
            "rollback": True,
        }, ensure_ascii=False))
    finally:
        try:
            base.rollback()
        finally:
            base.close()


if __name__ == "__main__":
    main()

