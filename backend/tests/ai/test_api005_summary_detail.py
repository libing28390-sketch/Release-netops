from __future__ import annotations

from api import knowledge_sources
from api.knowledge_v2_response import project_summary
from ai.api import assistant
from api.knowledge_v2_response import (
    SOURCE_SUMMARY_FIELDS,
)


USER = {"id": "api005-user", "username": "api005", "role": "Administrator", "tenant_id": "tenant-api005"}


def _detail_rich_row() -> dict:
    return {
        "id": "row-1",
        "tenant_id": "tenant-api005",
        "name": "Official guide",
        "canonical_url": "https://docs.example.test/guide",
        "status": "active",
        "updated_at": "2026-08-17T00:00:00Z",
        "content": "secret body",
        "original_content": "secret original body",
        "normalized_content": "normalized body",
        "chunks": [{"content": "chunk body"}],
        "logs": [{"message": "internal log"}],
        "trace": {"raw_query": "private query"},
        "raw_content_ref": "s3://private/object",
        "raw_content_storage": "private-bucket",
        "metadata": {"internal": "detail"},
        "validation": {"internal": "detail"},
        "collection_policy": {"timeout_seconds": 30},
        "error": {"exception": "private exception"},
    }


def _assert_detail_free(value: object) -> None:
    rendered = repr(value).lower()
    for marker in (
        "secret body", "secret original body", "normalized body", "chunk body",
        "internal log", "private query", "s3://private/object", "private-bucket",
        "private exception",
    ):
        assert marker not in rendered
    for key in ("content", "original_content", "normalized_content", "chunks", "logs", "trace", "raw_content_ref", "raw_content_storage", "error"):
        assert key not in value if isinstance(value, dict) else True


def test_explicit_summary_projection_drops_detail_and_internal_fields():
    row = _detail_rich_row()
    summary = project_summary(row, fields=SOURCE_SUMMARY_FIELDS)
    assert summary == {
        "id": "row-1",
        "tenant_id": "tenant-api005",
        "name": "Official guide",
        "canonical_url": "https://docs.example.test/guide",
        "status": "active",
        "updated_at": "2026-08-17T00:00:00Z",
    }
    _assert_detail_free(summary)


def test_source_list_routes_return_summaries_only(monkeypatch):
    row = _detail_rich_row()
    monkeypatch.setattr(knowledge_sources, "list_sources", lambda *args, **kwargs: [row])
    monkeypatch.setattr(knowledge_sources, "list_source_versions", lambda *args, **kwargs: [row])
    monkeypatch.setattr(knowledge_sources, "list_source_refresh_observations", lambda *args, **kwargs: [row])

    source_response = knowledge_sources.api_list_sources(page=1, page_size=20, sort_by="updated_at", sort_order="desc", user=USER)
    version_response = knowledge_sources.api_list_source_versions("source-1", page=1, page_size=20, sort_by="fetched_at", sort_order="desc", user=USER)
    observation_response = knowledge_sources.api_list_source_refresh_observations("source-1", limit=50, page=1, page_size=50, sort_by="observed_at", sort_order="desc", user=USER)

    assert source_response["data"][0]["canonical_url"] == row["canonical_url"]
    assert version_response["data"][0]["id"] == row["id"]
    assert observation_response["data"][0]["id"] == row["id"]
    for response in (source_response, version_response, observation_response):
        _assert_detail_free(response["data"][0])


def test_document_list_is_summary_and_detail_is_separate(monkeypatch):
    row = {
        **_detail_rich_row(),
        "knowledge_base_id": "kb-1",
        "source": "upload",
        "vendor": "Huawei",
        "platform": "huawei_vrp",
        "status": "active",
        "knowledge_source_type": "internal_sop",
        "source_trust_level": "internal",
        "created_at": "2026-08-17T00:00:00Z",
        "chunk_count": 1,
    }
    monkeypatch.setattr(
        assistant.knowledge_service,
        "list_documents",
        lambda **kwargs: {"items": [row], "total": 1, "page": 1, "page_size": 20, "total_pages": 1},
    )
    listing = assistant.list_documents(
        source_type=None, search="", directory_path=None, knowledge_scope=None,
        vendor="", product_family="", product_series="", product_model="",
        os_family="", os_generation="", software_train="", software_release="",
        cli_platform="", document_category="", feature_domain="", status="active",
        source_trust_level="", page=1, page_size=20, sort_by="created_at",
        sort_order="desc", user=USER,
    )
    assert listing["items"][0]["name"] == row["name"]
    _assert_detail_free(listing["items"][0])

    detail = {"id": "row-1", "original_content": "secret original body", "chunks": [{"content": "chunk body"}], "trace": {"trace_id": "rt-1"}}
    monkeypatch.setattr(assistant.knowledge_service, "get_document_detail", lambda *args, **kwargs: detail)
    loaded = assistant.get_document_detail("row-1", user=USER)
    assert loaded["original_content"] == "secret original body"
    assert loaded["chunks"][0]["content"] == "chunk body"
    assert loaded["trace"]["trace_id"] == "rt-1"


def test_contract_declares_separate_trace_and_document_detail_routes():
    from api.knowledge_traces import router as trace_router

    assistant_paths = {route.path for route in assistant.router.routes}
    trace_paths = {route.path for route in trace_router.routes}
    assert "/assistant/documents" in assistant_paths
    assert "/assistant/documents/{doc_id}" in assistant_paths
    assert "/knowledge-v2/retrieval-traces" in trace_paths
    assert "/knowledge-v2/retrieval-traces/{trace_id}" in trace_paths
