from __future__ import annotations

from api.knowledge_v2_contract import knowledge_v2_contract
from main import rewrite_knowledge_v2_path


def test_v2_boundary_manifest_is_explicit_and_does_not_include_storage_details():
    manifest = knowledge_v2_contract()
    assert manifest["contract"] == "nxa.kb.v2"
    assert manifest["canonical_prefix"] == "/api/v2/kb"
    assert manifest["compatibility_prefix"] == "/api/knowledge-v2"
    assert manifest["v1_ai_prefix"] == "/api/v1/ai"
    assert "internal_storage_path" not in manifest


def test_v2_path_rewrite_preserves_resource_suffix_and_leaves_other_paths_untouched():
    assert rewrite_knowledge_v2_path("/api/v2/kb") == "/api/knowledge-v2"
    assert rewrite_knowledge_v2_path("/api/v2/kb/sources/a/validate") == "/api/knowledge-v2/sources/a/validate"
    assert rewrite_knowledge_v2_path("/api/knowledge-v2/sources") is None
    assert rewrite_knowledge_v2_path("/api/v1/ai/chat") is None
