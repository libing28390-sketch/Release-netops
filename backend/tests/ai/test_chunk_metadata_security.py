"""Chunk metadata projection must not duplicate server-owned authorization keys."""

from __future__ import annotations

from ai.services.knowledge_metadata import chunk_projection_metadata


def test_chunk_projection_removes_identity_acl_and_credentials_recursively() -> None:
    result = chunk_projection_metadata(
        {
            "vendor": "Huawei",
            "tenant_id": "tenant-secret",
            "nested": {"acl_json": {"role": "admin"}, "feature": "vxlan"},
            "items": [{"user_id": "user-secret", "command": "display version"}],
        }
    )
    assert result == {
        "vendor": "Huawei",
        "nested": {"feature": "vxlan"},
        "items": [{"command": "display version"}],
    }
    assert "tenant-secret" not in str(result)
    assert "admin" not in str(result)


def test_chunk_projection_preserves_semantic_identity_fields() -> None:
    result = chunk_projection_metadata({"document_id": "doc-1", "product_model": "CE6885", "chunk_index": 1})
    assert result == {"document_id": "doc-1", "product_model": "CE6885", "chunk_index": 1}
