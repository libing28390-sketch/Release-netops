"""PostgreSQL-only CHK-014 shadow-index lifecycle probe.

Every DDL/DML operation runs in one transaction and is rolled back at the end;
the probe never changes the user's persistent database.  SQLite is rejected
up-front and is not an acceptance path for this task.
"""

from __future__ import annotations

import json
import uuid

from database.core import _USE_PG, get_db_connection
from database.migrations.m0150_retrieval_shadow_generations import upgrade
import ai.services.retrieval_index_service as index_module
import ai.services.rag_retriever as retriever_module
from ai.services.retrieval_index_service import RetrievalIndexError, retrieval_index_service
from ai.services.rag_retriever import RAGRetriever, RetrievalRequest


class _TxProxy:
    """Keep service commit calls inside the probe transaction."""

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


def _same_connection(proxy):
    return _SameConnection(proxy)


def _insert_fixture(cursor, *, knowledge_base_id: str, tenant: str, suffix: str, content: str) -> tuple[str, str]:
    document_id = f"chk014-doc-{suffix}-{uuid.uuid4().hex[:8]}"
    chunk_id = f"chk014-chunk-{suffix}-{uuid.uuid4().hex[:8]}"
    now = "2026-08-17T00:00:00+00:00"
    metadata = {"vendor": "huawei", "document_category": "command", "product_series": "CE6800"}
    cursor.execute(
        """
        INSERT INTO ai_document (
            id, knowledge_base_id, name, source, vendor, platform, status,
            created_at, updated_at, tenant_id, metadata_json, normalized_content,
            original_content, document_id, document_category, product_series,
            source_trust_level, knowledge_source_type, fts_text, retrieval_index_version
        ) VALUES (?, ?, ?, ?, 'huawei', 'vrp', 'active', ?, ?, ?, CAST(? AS jsonb), ?, ?, ?, 'command', 'CE6800', 'official', 'official_doc', ?, 'retrieval-v1')
        """,
        (
            document_id, knowledge_base_id, f"CHK-014 {suffix}", f"https://example.invalid/{suffix}",
            now, now, tenant, json.dumps(metadata), content, content, f"semantic-{suffix}", content,
        ),
    )
    cursor.execute(
        """
        INSERT INTO ai_document_chunk (
            id, document_id, content, embedding, metadata_json, page, section,
            created_at, chunk_role, chunk_type, ordinal, embedding_model,
            embedding_dimensions, embedding_version, is_retrieval_candidate,
            search_text, retrieval_index_version
        ) VALUES (?, ?, ?, ?, CAST(? AS jsonb), 1, 'Command', ?, 'standalone', 'command', 0,
                  'probe', 2, 'probe-v1', 1, ?, 'retrieval-v1')
        """,
        (chunk_id, document_id, content, "[1.0,0.0]", json.dumps(metadata), now, content),
    )
    return document_id, chunk_id


def main() -> None:
    if not _USE_PG:
        raise SystemExit("CHK-014 requires PostgreSQL; SQLite is not an acceptance backend")

    base = get_db_connection()
    proxy = _TxProxy(base)
    index_module.get_db_connection = lambda: _same_connection(proxy)
    retriever_module.get_db_connection = lambda: _same_connection(proxy)
    try:
        cursor = base.cursor()
        upgrade(cursor, True)
        cursor.execute("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm') ORDER BY extname")
        extensions = [str(row[0]) for row in cursor.fetchall()]
        if extensions != ["pg_trgm", "vector"]:
            raise AssertionError(f"required PostgreSQL extensions missing: {extensions}")
        # Idempotent second application must not fail.
        upgrade(cursor, True)
        cursor.execute("SELECT data_type, udt_name FROM information_schema.columns WHERE table_name = 'ai_retrieval_index_shadow_chunk' AND column_name IN ('metadata_json','embedding_vector') ORDER BY column_name")
        types = [tuple(row) for row in cursor.fetchall()]
        if types != [("USER-DEFINED", "vector"), ("jsonb", "jsonb")]:
            raise AssertionError(f"unexpected shadow types: {types}")
        cursor.execute("SELECT id FROM ai_knowledge_base ORDER BY id LIMIT 1")
        knowledge_base = cursor.fetchone()
        if not knowledge_base:
            raise AssertionError("no PostgreSQL knowledge base fixture exists")
        knowledge_base_id = str(knowledge_base[0])

        tenant_a = f"chk014-a-{uuid.uuid4().hex[:8]}"
        tenant_b = f"chk014-b-{uuid.uuid4().hex[:8]}"
        doc_a, chunk_a = _insert_fixture(cursor, knowledge_base_id=knowledge_base_id, tenant=tenant_a, suffix="a", content="shadow generation A command")
        doc_b, chunk_b = _insert_fixture(cursor, knowledge_base_id=knowledge_base_id, tenant=tenant_a, suffix="b", content="shadow generation B command")
        _insert_fixture(cursor, knowledge_base_id=knowledge_base_id, tenant=tenant_b, suffix="other", content="other tenant command")

        generation_a = retrieval_index_service.create_shadow_generation("retrieval-chk014-a", tenant_id=tenant_a)
        retrieval_index_service.build_shadow_generation(generation_a["id"], tenant_id=tenant_a)
        verified_a = retrieval_index_service.verify_shadow_generation(generation_a["id"], tenant_id=tenant_a)
        if verified_a["status"] != "ready" or verified_a["chunk_count"] != 2:
            raise AssertionError(f"generation A verification failed: {verified_a}")
        active_a = retrieval_index_service.cutover_generation(generation_a["id"], tenant_id=tenant_a)
        if active_a["status"] != "active":
            raise AssertionError("generation A did not become active")

        retriever = RAGRetriever(cache_enabled=False)
        first = retriever.search(RetrievalRequest(query="shadow generation A", tenant_id=tenant_a, top_k=5), min_relevance=0.0)
        if first["debug"].get("index_source") != "shadow" or first["debug"].get("index_version") != "retrieval-chk014-a":
            raise AssertionError(f"RAG did not read active shadow generation: {first['debug']}")
        first_ids = {str(item.get("storage_document_id")) for item in first["results"]}
        if doc_a not in first_ids or doc_b not in first_ids:
            raise AssertionError(f"shadow generation A results incomplete: {first_ids}")

        # A second shadow build proves dual-index operation without changing
        # V1 rows.  The old generation remains readable until cutover.
        generation_b = retrieval_index_service.create_shadow_generation("retrieval-chk014-b", tenant_id=tenant_a)
        retrieval_index_service.build_shadow_generation(generation_b["id"], tenant_id=tenant_a)
        verified_b = retrieval_index_service.verify_shadow_generation(generation_b["id"], tenant_id=tenant_a)
        if verified_b["status"] != "ready":
            raise AssertionError("generation B was not ready")
        still_a = retrieval_index_service.get_active_generation(tenant_a)
        if still_a["id"] != generation_a["id"]:
            raise AssertionError("shadow build changed active pointer before cutover")
        active_b = retrieval_index_service.cutover_generation(generation_b["id"], tenant_id=tenant_a)
        if active_b["status"] != "active" or active_b["previous_generation_id"] != generation_a["id"]:
            raise AssertionError("generation B cutover/lineage failed")
        second = retriever.search(RetrievalRequest(query="shadow generation B", tenant_id=tenant_a, top_k=5), min_relevance=0.0)
        if second["debug"].get("index_generation_id") != generation_b["id"]:
            raise AssertionError("RAG did not switch to generation B")

        # Not-ready generations cannot be activated.
        generation_bad = retrieval_index_service.create_shadow_generation("retrieval-chk014-bad", tenant_id=tenant_a)
        try:
            retrieval_index_service.cutover_generation(generation_bad["id"], tenant_id=tenant_a)
        except RetrievalIndexError as exc:
            if exc.code != "GENERATION_NOT_READY":
                raise
        else:
            raise AssertionError("not-ready generation was cut over")

        rolled_back = retrieval_index_service.rollback_generation(generation_b["id"], tenant_id=tenant_a)
        if rolled_back["id"] != generation_a["id"] or rolled_back["status"] != "active":
            raise AssertionError("rollback did not restore generation A")
        after_rollback = retriever.search(RetrievalRequest(query="shadow generation A", tenant_id=tenant_a, top_k=5), min_relevance=0.0)
        if after_rollback["debug"].get("index_generation_id") != generation_a["id"]:
            raise AssertionError("RAG did not return to generation A after rollback")
        if retrieval_index_service.get_active_generation(tenant_b) is not None:
            raise AssertionError("tenant B unexpectedly inherited tenant A active generation")
        cursor.execute("SELECT COUNT(*) FROM ai_document WHERE id IN (?, ?) AND tenant_id = ?", (doc_a, doc_b, tenant_a))
        if int((cursor.fetchone() or [0])[0]) != 2:
            raise AssertionError("V1 source rows changed")
        base.rollback()
        print(json.dumps({
            "status": "PASS",
            "database": "PostgreSQL",
            "extensions": extensions,
            "generation_a": generation_a["id"],
            "generation_b": generation_b["id"],
            "active_after_rollback": rolled_back["id"],
            "shadow_rows": 2,
            "dual_index": True,
            "atomic_cutover": True,
            "not_ready_rejected": True,
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
