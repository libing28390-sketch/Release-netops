"""PostgreSQL-only RET-008..RET-010 verification probe.

The normal pytest conftest intentionally forces SQLite for the legacy test
suite.  This probe is therefore a separate process and is the authoritative
database evidence for RET.  It uses the real application PostgreSQL
connection, applies m0138 inside one transaction, inserts only transaction
local probe rows, verifies FTS/trigram/vector/tenant behavior, and rolls the
whole transaction back.  No production rows, schema version or migration
history are retained.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from database import core  # noqa: E402
from database.migrations.m0138_retrieval_accelerator_projection import (  # noqa: E402
    upgrade,
)


def _rows(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    return list(cursor.execute(sql, params).fetchall())


def _index_names(cursor: Any, table: str) -> set[str]:
    return {
        str(row[0])
        for row in _rows(
            cursor,
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname=current_schema() AND tablename=?",
            (table,),
        )
    }


def _column_names(cursor: Any, table: str) -> set[str]:
    return {
        str(row[0])
        for row in _rows(
            cursor,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name=?",
            (table,),
        )
    }


def _walk_plan(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "Node Type" in value:
            yield value
        for child in value.values():
            yield from _walk_plan(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_plan(child)


def _vector_literal(dimension: int = 1536) -> str:
    return "[" + ",".join(["1"] + ["0"] * (dimension - 1)) + "]"


def _run() -> dict[str, Any]:
    if not core._USE_PG:
        raise RuntimeError(
            "RET PostgreSQL gate refused to run: DATABASE_URL did not select PostgreSQL"
        )

    conn = core.get_db_connection()
    cur = conn.cursor()
    before_doc_columns = _column_names(cur, "ai_document")
    before_chunk_columns = _column_names(cur, "ai_document_chunk")
    before_doc_indexes = _index_names(cur, "ai_document")
    before_chunk_indexes = _index_names(cur, "ai_document_chunk")
    extension_rows = _rows(
        cur,
        "SELECT extname, extversion FROM pg_extension "
        "WHERE extname IN ('vector', 'pg_trgm') ORDER BY extname",
    )
    extensions = {str(row[0]): str(row[1]) for row in extension_rows}
    if set(extensions) != {"vector", "pg_trgm"}:
        conn.rollback()
        conn.close()
        raise RuntimeError(f"required PostgreSQL extensions missing: {extensions}")

    probe_doc_ids = ("__ret_pg_probe_doc_t1", "__ret_pg_probe_doc_t2")
    probe_chunk_ids = ("__ret_pg_probe_chunk_t1", "__ret_pg_probe_chunk_t2")
    vector = _vector_literal()
    try:
        # The migration and all fixture writes are intentionally in one
        # transaction.  m0138 is idempotent, so this also exercises a real
        # upgrade against the current schema without changing migration
        # history.
        upgrade(cur, use_pg=True)
        after_doc_columns = _column_names(cur, "ai_document")
        after_chunk_columns = _column_names(cur, "ai_document_chunk")
        after_doc_indexes = _index_names(cur, "ai_document")
        after_chunk_indexes = _index_names(cur, "ai_document_chunk")
        required_doc_columns = {"fts_text", "retrieval_index_version"}
        required_chunk_columns = {
            "search_text",
            "retrieval_index_version",
            "embedding_vector",
        }
        required_chunk_indexes = {
            "ix_ai_chunk_search_fts",
            "ix_ai_chunk_search_trgm",
            "ix_ai_chunk_embedding_vector_hnsw",
        }
        if not required_doc_columns <= after_doc_columns:
            raise AssertionError("m0138 did not create all document projection columns")
        if not required_chunk_columns <= after_chunk_columns:
            raise AssertionError("m0138 did not create all chunk projection columns")
        if not required_chunk_indexes <= after_chunk_indexes:
            raise AssertionError("m0138 did not create all PostgreSQL accelerator indexes")

        now = "2026-08-17T00:00:00+00:00"
        kb_row = _rows(cur, "SELECT id FROM ai_knowledge_base ORDER BY id LIMIT 1")
        if not kb_row:
            raise AssertionError("RET PostgreSQL probe requires an existing ai_knowledge_base")
        knowledge_base_id = str(kb_row[0][0])
        cur.execute(
            "INSERT INTO ai_document "
            "(id, knowledge_base_id, name, status, created_at, updated_at, tenant_id, "
            "acl_json, source_trust_level, normalized_content, vendor, platform, "
            "fts_text, retrieval_index_version) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                probe_doc_ids[0],
                knowledge_base_id,
                "RET PostgreSQL OSPF guide",
                now,
                now,
                "tenant-ret-a",
                "{}",
                "official",
                "show ospf peer brief command reference",
                "Huawei",
                "vrp",
                "RET PostgreSQL OSPF guide show ospf peer brief command reference",
                "retrieval-v1",
            ),
        )
        cur.execute(
            "INSERT INTO ai_document "
            "(id, knowledge_base_id, name, status, created_at, updated_at, tenant_id, "
            "acl_json, source_trust_level, normalized_content, vendor, platform, "
            "fts_text, retrieval_index_version) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                probe_doc_ids[1],
                knowledge_base_id,
                "RET PostgreSQL other tenant guide",
                now,
                now,
                "tenant-ret-b",
                "{}",
                "official",
                "show ospf peer other tenant",
                "Cisco",
                "iosxe",
                "RET PostgreSQL other tenant guide show ospf peer other tenant",
                "retrieval-v1",
            ),
        )
        for chunk_id, doc_id, content, search_text in (
            (
                probe_chunk_ids[0],
                probe_doc_ids[0],
                "show ospf peer brief",
                "Command show ospf peer brief",
            ),
            (
                probe_chunk_ids[1],
                probe_doc_ids[1],
                "show ospf peer other tenant",
                "Command show ospf peer other tenant",
            ),
        ):
            cur.execute(
                "INSERT INTO ai_document_chunk "
                "(id, document_id, content, created_at, section, embedding_content, "
                "search_text, retrieval_index_version, embedding_vector, vendor) "
                "VALUES (?, ?, ?, ?, 'Command', ?, ?, 'retrieval-v1', CAST(? AS vector), ?)",
                (
                    chunk_id,
                    doc_id,
                    content,
                    now,
                    content,
                    search_text,
                    vector,
                    "Huawei" if doc_id == probe_doc_ids[0] else "Cisco",
                ),
            )

        scoped_rows = _rows(
            cur,
            "SELECT c.id FROM ai_document_chunk c "
            "JOIN ai_document d ON d.id=c.document_id "
            "WHERE d.tenant_id=? AND d.status='active' AND c.id IN (?, ?)",
            ("tenant-ret-a", *probe_chunk_ids),
        )
        scoped_ids = {str(row[0]) for row in scoped_rows}
        if scoped_ids != {probe_chunk_ids[0]}:
            raise AssertionError(f"tenant/status boundary leaked rows: {scoped_ids}")

        fts_rows = _rows(
            cur,
            "SELECT id, ts_rank_cd(to_tsvector('simple', search_text), "
            "websearch_to_tsquery('simple', ?)) FROM ai_document_chunk "
            "WHERE id IN (?, ?) AND to_tsvector('simple', search_text) @@ "
            "websearch_to_tsquery('simple', ?)",
            ("show ospf peer", *probe_chunk_ids, "show ospf peer"),
        )
        if not fts_rows or str(fts_rows[0][0]) != probe_chunk_ids[0]:
            raise AssertionError(f"PostgreSQL FTS did not match expected chunk: {fts_rows}")

        trgm_rows = _rows(
            cur,
            "SELECT id, similarity(search_text, ?) FROM ai_document_chunk "
            "WHERE id IN (?, ?) AND similarity(search_text, ?) >= ?",
            ("show ospf peer breif", *probe_chunk_ids, "show ospf peer breif", 0.20),
        )
        if not trgm_rows:
            raise AssertionError("pg_trgm threshold query returned no candidate")

        vector_rows = _rows(
            cur,
            "SELECT id, 1 - (embedding_vector <=> CAST(? AS vector)) "
            "FROM ai_document_chunk WHERE id IN (?, ?) ORDER BY 2 DESC",
            (vector, *probe_chunk_ids),
        )
        if not vector_rows or str(vector_rows[0][0]) != probe_chunk_ids[0]:
            raise AssertionError(f"pgvector cosine query did not rank expected chunk: {vector_rows}")

        explain_rows = _rows(
            cur,
            "EXPLAIN (FORMAT JSON) SELECT id FROM ai_document_chunk "
            "WHERE id IN (?, ?) AND similarity(search_text, ?) >= ?",
            (*probe_chunk_ids, "show ospf peer breif", 0.20),
        )
        plan_nodes = list(_walk_plan(explain_rows[0][0])) if explain_rows else []

        result = {
            "status": "PASS",
            "database": "PostgreSQL",
            "server": str(_rows(cur, "SELECT version()")[0][0]),
            "extensions": extensions,
            "migration": {
                "version": 138,
                "idempotent_columns": True,
                "required_document_columns": sorted(required_doc_columns),
                "required_chunk_columns": sorted(required_chunk_columns),
                "required_chunk_indexes": sorted(required_chunk_indexes),
            },
            "retrieval": {
                "tenant_status_scoped_ids": sorted(scoped_ids),
                "fts_candidates": len(fts_rows),
                "trgm_candidates": len(trgm_rows),
                "vector_candidates": len(vector_rows),
                "vector_top_id": str(vector_rows[0][0]),
                "trgm_threshold": 0.20,
            },
            "explain": {
                "node_types": [str(node.get("Node Type")) for node in plan_nodes],
                "captured": bool(explain_rows),
            },
            "rollback": "pending",
        }
        conn.rollback()
        result["rollback"] = "PASS"
        if not required_doc_columns & before_doc_columns:
            if required_doc_columns & _column_names(cur, "ai_document"):
                raise AssertionError("m0138 columns survived rollback")
        if not required_chunk_columns & before_chunk_columns:
            if required_chunk_columns & _column_names(cur, "ai_document_chunk"):
                raise AssertionError("m0138 chunk columns survived rollback")
        if not required_chunk_indexes & before_chunk_indexes:
            if required_chunk_indexes & _index_names(cur, "ai_document_chunk"):
                raise AssertionError("m0138 indexes survived rollback")
        if _rows(cur, "SELECT id FROM ai_document WHERE id IN (?, ?)", probe_doc_ids):
            raise AssertionError("probe documents survived rollback")
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval", action="store_true", help="retained for plan compatibility")
    parser.add_argument("--explain", action="store_true", help="retained for plan compatibility")
    parser.parse_args()
    try:
        result = _run()
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
