"""Semantic vector column, dual write and backfill (RAG refactor phase 3).

Runs on the fully migrated PostgreSQL test database.  The sidecar is replaced
by a deterministic fake provider with the real bge-m3 contract (1024-d).
"""

from __future__ import annotations

import argparse
import hashlib
import math

import pytest

from ai.providers import embedding as embedding_module
from ai.providers.embedding import BaseEmbeddingProvider, EmbeddingProviderError
from ai.services import semantic_vectors


class FakeSemanticProvider(BaseEmbeddingProvider):
    model_id = "bge-m3"
    version = "bge-m3-int8-v1"
    dimensions = 1024
    mode = "local_semantic"

    def __init__(self, dimensions: int = 1024, fail: bool = False) -> None:
        self.dimensions = dimensions
        self.fail = fail
        self.calls = 0

    def embed_documents(self, texts, **_):
        self.calls += 1
        if self.fail:
            raise EmbeddingProviderError("Embedding sidecar unavailable: CONNECTION_FAILED")
        vectors = []
        for text in texts:
            seed = hashlib.sha256(str(text).encode("utf-8")).digest()
            raw = [((seed[i % len(seed)] + i) % 17) - 8.0 for i in range(self.dimensions)]
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            vectors.append([v / norm for v in raw])
        return vectors

    def embed_text(self, text, dimensions=None):
        return self.embed_documents([text])[0]


@pytest.fixture
def semantic(monkeypatch):
    """Install a fake semantic provider for ingestion and the maintenance script."""
    embedding_module._EMBEDDING_IDEMPOTENCY_CACHE.clear()
    monkeypatch.delenv("AI_SEMANTIC_EMBEDDING_REQUIRED", raising=False)
    state = {"provider": FakeSemanticProvider()}
    monkeypatch.setattr(semantic_vectors, "semantic_embedding_provider", lambda: state["provider"])
    monkeypatch.setattr(embedding_module, "semantic_embedding_provider", lambda: state["provider"])
    yield state
    embedding_module._EMBEDDING_IDEMPOTENCY_CACHE.clear()


def _add(name: str, content: str) -> str:
    from ai.services.knowledge_service import knowledge_service

    knowledge_base = knowledge_service.create_knowledge_base(f"KB {name}", tenant_id="tenant-default")
    result = knowledge_service.add_document_and_chunk(
        knowledge_base_id=knowledge_base["id"],
        name=name,
        content=content,
        vendor="Huawei",
        platform="huawei_vrp",
        tenant_id="tenant-default",
        metadata={
            "vendor": "Huawei",
            "product_family": "Campus Switch",
            "product_series": "S5700",
            "cli_platform": "huawei_vrp",
            "source_type": "user_document",
            "document_category": "configuration",
        },
        invalidate_cache=False,
    )
    return str(result["document_id"])


def _rows(document_id: str):
    from database.core import get_db_connection

    with get_db_connection() as conn:
        return conn.execute(
            "SELECT id, embedding_v2 IS NOT NULL, embedding_v2_model, embedding_v2_version, embedding_v2_content_hash, "
            "encode(sha256(convert_to(COALESCE(NULLIF(embedding_content, ''), NULLIF(search_text, ''), NULLIF(content, ''), ''), 'UTF8')), 'hex') "
            "FROM ai_document_chunk WHERE document_id = ? ORDER BY id",
            (document_id,),
        ).fetchall()


def _maintenance_module():
    """Load scripts/rag_index_maintenance.py by path.

    ``pytest.ini`` puts ``backend`` first on the path, so ``import scripts``
    resolves to ``backend/scripts`` instead of the repository's ``scripts``.
    """
    import importlib.util
    import sys
    from pathlib import Path

    name = "nexora_rag_index_maintenance"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parents[3] / "scripts" / "rag_index_maintenance.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


DOC = "# OSPF\n\n## Verification\n\nUse display ospf peer to check OSPF neighbor state.\n\n## Troubleshooting\n\nExStart usually means an MTU mismatch."


def test_migration_adds_a_1024_dimension_semantic_column(isolated_db):
    from database.core import get_db_connection

    with get_db_connection() as conn:
        column_type = semantic_vectors.semantic_column_type(conn.cursor())
    assert column_type in {"halfvec(1024)", "vector(1024)"}


def test_ingestion_writes_semantic_vectors_with_their_contract(isolated_db, semantic):
    document_id = _add("OSPF semantic", DOC)
    rows = _rows(document_id)
    assert rows
    for _id, present, model, version, stored_hash, text_hash in rows:
        assert present and model == "bge-m3" and version == "bge-m3-int8-v1"
        assert stored_hash == text_hash  # hash of exactly the embedded text
    assert semantic["provider"].calls >= 1


def test_ingestion_without_semantic_provider_leaves_the_columns_empty(isolated_db, semantic):
    semantic["provider"] = None
    document_id = _add("OSPF disabled", DOC + "\n\ndisabled")
    assert all(not row[1] for row in _rows(document_id))


def test_sidecar_outage_does_not_block_ingestion(isolated_db, semantic):
    semantic["provider"] = FakeSemanticProvider(fail=True)
    document_id = _add("OSPF outage", DOC + "\n\noutage")
    rows = _rows(document_id)
    assert rows and all(not row[1] for row in rows)


def test_required_mode_makes_a_sidecar_outage_fatal(isolated_db, semantic, monkeypatch):
    monkeypatch.setenv("AI_SEMANTIC_EMBEDDING_REQUIRED", "1")
    semantic["provider"] = FakeSemanticProvider(fail=True)
    with pytest.raises(EmbeddingProviderError):
        _add("OSPF required", DOC + "\n\nrequired")


def test_dimension_mismatch_is_not_stored(isolated_db, semantic):
    semantic["provider"] = FakeSemanticProvider(dimensions=768)
    document_id = _add("OSPF 768", DOC + "\n\nmismatch")
    rows = _rows(document_id)
    assert rows and all(not row[1] for row in rows)


def test_backfill_fills_gaps_detects_stale_text_and_builds_the_index(isolated_db, semantic, capsys):
    from database.core import get_db_connection
    maintenance = _maintenance_module()

    semantic["provider"] = None
    document_id = _add("OSPF backfill", DOC + "\n\nbackfill")
    semantic["provider"] = FakeSemanticProvider()

    def run(*argv):
        code = maintenance.main(list(argv))
        out = capsys.readouterr().out
        return code, out

    code, _ = run("--all", "backfill", "--dry-run")
    assert code == 0
    assert all(not row[1] for row in _rows(document_id))  # dry run writes nothing

    code, _ = run("--all", "backfill", "--batch", "2")
    assert code == 0
    rows = _rows(document_id)
    assert rows and all(row[1] and row[4] == row[5] for row in rows)

    # Text changes -> the vector is stale and is re-embedded.
    changed = rows[0][0]
    with get_db_connection() as conn:
        conn.execute("UPDATE ai_document_chunk SET embedding_content = embedding_content || ' changed' WHERE id = ?", (changed,))
        conn.commit()
    namespace = argparse.Namespace(model="bge-m3", version="bge-m3-int8-v1", all=True)
    report = maintenance.status(namespace)
    assert report["chunks"]["stale_text_changed"] >= 1
    code, _ = run("--all", "backfill")
    assert code == 0
    assert all(row[4] == row[5] for row in _rows(document_id))

    # Other model version -> stale as well.
    with get_db_connection() as conn:
        conn.execute("UPDATE ai_document_chunk SET embedding_v2_version = 'old' WHERE id = ?", (changed,))
        conn.commit()
    assert maintenance.status(namespace)["chunks"]["stale_other_model_or_version"] >= 1
    run("--all", "backfill")
    assert maintenance.status(namespace)["chunks"]["stale_other_model_or_version"] == 0

    code, _ = run("build-index", "--maintenance-work-mem", "64MB")
    assert code == 0
    report = maintenance.status(namespace)
    assert report["index"]["exists"] and report["index"]["valid"]
    code, out = run("verify", "--sample", "50")
    assert code == 0 and '"status": "PASS"' in out


def test_backfill_stops_cleanly_when_the_sidecar_is_down(isolated_db, semantic, capsys, monkeypatch):
    maintenance = _maintenance_module()

    semantic["provider"] = None
    _add("OSPF down", DOC + "\n\ndown")
    semantic["provider"] = FakeSemanticProvider(fail=True)
    monkeypatch.setattr(maintenance.time, "sleep", lambda _s: None)
    code = maintenance.main(["--all", "backfill", "--max-failures", "2"])
    assert code == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
