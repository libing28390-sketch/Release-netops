from __future__ import annotations

import pytest
from fastapi import HTTPException

from ai.api.assistant import add_document, preview_document_metadata_endpoint, router
from ai.services.metadata_confirmation_service import (
    MetadataConfirmationError,
    preview_document_metadata,
    validate_metadata_confirmation,
)
from api.knowledge_contracts import KnowledgeDocumentCreateRequest, KnowledgeMetadataPreviewRequest


USER = {"id": "operator-ing021", "username": "operator", "tenant_id": "tenant-ing021", "role": "Administrator"}


def _preview(**overrides):
    payload = {
        "name": "OSPF guide",
        "content": "# OSPF\n\nshow ospf peer",
        "vendor": "Huawei",
        "platform": "vrp",
        "knowledge_source_type": "internal_sop",
        "metadata": {"knowledge_directory_path": "01_product/huawei"},
    }
    payload.update(overrides)
    return preview_document_metadata(user=USER, **payload)


def test_ing021_preview_normalizes_legacy_metadata_and_binds_confirmation():
    preview = _preview()

    assert preview["requires_confirmation"] is True
    assert preview["metadata_parse_status"] == "missing"
    assert preview["normalized"]["vendor"] == "Huawei"
    assert "metadata_front_matter_missing_legacy_path" in preview["warnings"]
    assert preview["normalized"]["content_sha256"]
    result = validate_metadata_confirmation(
        user=USER,
        token=preview["confirmation_token"],
        confirmed=True,
        name="OSPF guide",
        content="# OSPF\n\nshow ospf peer",
        vendor="Huawei",
        platform="vrp",
        knowledge_source_type="internal_sop",
        source_trust_level="internal",
        chunk_size=800,
        metadata={"knowledge_directory_path": "01_product/huawei"},
    )
    assert result["preview_id"] == preview["preview_id"]


def test_ing021_structured_upload_is_server_parsed_before_confirmation():
    preview = _preview(
        name="inventory.json",
        content='{"hostname":"sw-1","vendor":"Huawei"}',
        metadata={"knowledge_directory_path": "01_product/huawei"},
    )
    assert preview["normalized"]["format"] == "json"
    assert preview["normalized"]["parser_name"] == "nexora-json"
    assert preview["normalized"]["body_characters"] > 0


def test_ing021_custom_document_envelope_exposes_importable_metadata_preview():
    content = """{
      "format": "nexora-knowledge-document",
      "schema_version": "2.0",
      "metadata": {
        "document_id": "custom.huawei.vlan.v1",
        "title": "Huawei VLAN",
        "vendor": "Huawei",
        "product_type": "network_switch",
        "document_category": "configuration",
        "source_type": "user_document",
        "official_only": false,
        "status": "draft"
      },
      "content": "# Huawei VLAN\\n\\nvlan batch 10"
    }"""
    preview = _preview(name="custom.json", content=content, metadata={"knowledge_directory_path": "03_configuration/huawei"})
    assert preview["metadata_parse_status"] == "parsed"
    assert preview["normalized"]["parser_name"] == "nexora-json-document-envelope"
    assert preview["normalized"]["metadata"]["document_id"] == "custom.huawei.vlan.v1"


def test_ing021_invalid_structured_upload_is_rejected_before_metadata_confirmation():
    with pytest.raises(MetadataConfirmationError) as invalid:
        _preview(name="inventory.json", content="{bad")
    assert invalid.value.code == "METADATA_SOURCE_PARSE_INVALID"


def test_ing021_html_upload_is_cleaned_before_it_is_indexed():
    preview = _preview(
        name="runbook.html",
        content="<nav>menu</nav><h1>VLAN</h1><p>switchport mode access</p><script>ignore()</script>",
        metadata={"knowledge_directory_path": "03_configuration/huawei"},
    )
    assert preview["normalized"]["format"] == "html"
    assert preview["normalized"]["body_characters"] > 0
    assert "html_requires_ing007_content_cleaning" in preview["warnings"]


def test_ing021_front_matter_is_parsed_and_directory_conflicts_are_rejected():
    content = """---
schema_version: '2.0'
document_id: doc-001
title: OSPF Guide
vendor: huawei
product_type: switch
document_category: hardware
source_type: official
official_only: true
status: active
---
# OSPF

show ospf peer
"""
    preview = _preview(content=content, metadata={"knowledge_directory_path": "01_product/huawei"})
    assert preview["metadata_parse_status"] == "parsed"
    assert preview["normalized"]["metadata"]["vendor"] == "Huawei"
    assert preview["normalized"]["metadata"]["document_category"] == "hardware"

    with pytest.raises(MetadataConfirmationError) as conflict:
        _preview(content=content, metadata={"knowledge_directory_path": "02_commands/huawei"})
    assert conflict.value.code == "METADATA_VALIDATION_INVALID"


def test_ing021_confirmation_rejects_missing_tampered_stale_and_cross_tenant_inputs():
    preview = _preview()
    with pytest.raises(MetadataConfirmationError) as missing:
        validate_metadata_confirmation(
            user=USER,
            token=preview["confirmation_token"],
            confirmed=False,
            name="OSPF guide",
            content="# OSPF\n\nshow ospf peer",
            vendor="Huawei",
            platform="vrp",
            knowledge_source_type="internal_sop",
            metadata={"knowledge_directory_path": "01_product/huawei"},
        )
    assert missing.value.code == "METADATA_CONFIRMATION_REQUIRED"

    with pytest.raises(MetadataConfirmationError) as tampered:
        validate_metadata_confirmation(
            user=USER,
            token=preview["confirmation_token"][:-1] + ("a" if preview["confirmation_token"][-1] != "a" else "b"),
            confirmed=True,
            name="OSPF guide",
            content="# OSPF\n\nshow ospf peer",
            vendor="Huawei",
            platform="vrp",
            knowledge_source_type="internal_sop",
            metadata={"knowledge_directory_path": "01_product/huawei"},
        )
    assert tampered.value.code == "METADATA_CONFIRMATION_INVALID"

    with pytest.raises(MetadataConfirmationError) as stale:
        validate_metadata_confirmation(
            user=USER,
            token=preview["confirmation_token"],
            confirmed=True,
            name="OSPF guide",
            content="# OSPF\n\nshow ospf peer changed",
            vendor="Huawei",
            platform="vrp",
            knowledge_source_type="internal_sop",
            metadata={"knowledge_directory_path": "01_product/huawei"},
        )
    assert stale.value.code == "METADATA_CONFIRMATION_STALE"

    other_tenant = dict(USER, tenant_id="tenant-other")
    with pytest.raises(MetadataConfirmationError) as scope:
        validate_metadata_confirmation(
            user=other_tenant,
            token=preview["confirmation_token"],
            confirmed=True,
            name="OSPF guide",
            content="# OSPF\n\nshow ospf peer",
            vendor="Huawei",
            platform="vrp",
            knowledge_source_type="internal_sop",
            metadata={"knowledge_directory_path": "01_product/huawei"},
        )
    assert scope.value.code == "METADATA_CONFIRMATION_SCOPE_MISMATCH"


def test_ing021_secret_metadata_is_rejected_and_route_is_exposed():
    with pytest.raises(MetadataConfirmationError) as exc:
        _preview(metadata={"api_key": "should-not-be-accepted"})
    assert exc.value.code == "METADATA_SECRET_FIELD_FORBIDDEN"
    paths = {(route.path, tuple(sorted(route.methods or []))) for route in router.routes}
    assert ("/assistant/documents/metadata-preview", ("POST",)) in paths


def test_ing021_preview_endpoint_and_confirmed_document_write(monkeypatch):
    request = KnowledgeMetadataPreviewRequest(
        name="Endpoint guide",
        content="# Guide\n\nbody",
        vendor="Cisco",
        platform="ios",
        metadata={"knowledge_directory_path": "01_product/cisco"},
    )
    response = preview_document_metadata_endpoint(payload=request, user=USER)
    preview = response["data"]
    assert response["success"] is True
    assert preview["normalized"]["vendor"] == "Cisco"

    calls: list[dict] = []
    monkeypatch.setattr("ai.api.assistant.knowledge_service.list_knowledge_bases", lambda tenant_id: [{"id": "kb-ing021"}])
    monkeypatch.setattr(
        "ai.api.assistant.knowledge_service.add_document_and_chunk",
        lambda **kwargs: calls.append(kwargs) or {"id": "doc-ing021", "chunk_count": 1},
    )
    payload = KnowledgeDocumentCreateRequest(
        name="Endpoint guide",
        content="# Guide\n\nbody",
        vendor="Cisco",
        platform="ios",
        metadata={"knowledge_directory_path": "01_product/cisco"},
        metadata_confirmation_token=preview["confirmation_token"],
        metadata_confirmed=True,
    )
    result = add_document(payload=payload, user=USER)
    assert result["id"] == "doc-ing021"
    assert calls and calls[0]["tenant_id"] == "tenant-ing021"

    invalid_payload = payload.model_copy(update={"content": "# Guide\n\nchanged"})
    with pytest.raises(HTTPException) as invalid:
        add_document(payload=invalid_payload, user=USER)
    assert invalid.value.status_code == 409
    assert invalid.value.detail["code"] == "METADATA_CONFIRMATION_STALE"
