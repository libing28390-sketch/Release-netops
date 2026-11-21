from __future__ import annotations

from api.knowledge_contract import knowledge_contract


def test_v1_boundary_manifest_is_explicit_and_does_not_include_storage_details():
    manifest = knowledge_contract()
    assert manifest["contract"] == "nxa.kb.v1"
    assert manifest["canonical_prefix"] == "/api/knowledge"
    assert manifest["compatibility_prefix"] is None
    assert manifest["v1_ai_prefix"] == "/api/v1/ai"
    assert "internal_storage_path" not in manifest


def test_v1_boundary_has_no_legacy_alias_or_shadow_path():
    assert "/api/v2/kb" not in str(knowledge_contract())
    assert "/api/knowledge-v2" not in str(knowledge_contract())
