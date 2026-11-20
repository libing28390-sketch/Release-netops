from __future__ import annotations

import io
import json
import zipfile

import pytest

from ai.services import knowledge_export_service as export_module


def _summary(doc_id: str, name: str) -> dict[str, object]:
    return {"id": doc_id, "name": name}


def _detail(doc_id: str, name: str, status: str = "active") -> dict[str, object]:
    return {
        "id": doc_id,
        "document_id": f"canonical-{doc_id}",
        "name": name,
        "source": "https://official.example.test/guide",
        "vendor": "Cisco",
        "platform": "cisco_iosxe",
        "status": status,
        "knowledge_source_type": "official_url",
        "source_trust_level": "official",
        "normalized_content": "# VLAN\n\ninterface GigabitEthernet1/0/1\n switchport mode access",
        "metadata": {
            "document_category": "configuration",
            "feature_domain": "vlan",
            "tenant_id": "should-not-export",
            "acl_json": {"roles": ["admin"]},
            "nested": {"api_key": "should-not-export"},
        },
        "raw_source": {"references": [{"canonical_url": "https://official.example.test/guide"}]},
    }


def test_build_export_is_portable_and_redacts_server_owned_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_list_documents(**kwargs):
        assert kwargs["tenant_id"] == "tenant-a"
        assert kwargs["knowledge_source_type"] is None
        return {"items": [_summary("doc-1", "Cisco VLAN Guide")], "total": 1, "page": 1}

    monkeypatch.setattr(export_module.knowledge_service, "list_documents", fake_list_documents)
    monkeypatch.setattr(
        export_module.knowledge_service,
        "get_document_detail",
        lambda doc_id, tenant_id, **kwargs: _detail(doc_id, "Cisco VLAN Guide"),
    )

    bundle = export_module.knowledge_export_service.build_export(tenant_id="tenant-a")
    with zipfile.ZipFile(io.BytesIO(bundle["content"])) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        document = archive.read(next(name for name in names if name.startswith("documents/"))).decode("utf-8")

    assert manifest["schema_version"] == "knowledge-export-v1"
    assert manifest["document_count"] == 1
    assert manifest["embeddings_exported"] is False
    assert manifest["reindex_required_on_import"] is True
    assert manifest["import_contract"]["document_format"] == "markdown"
    assert manifest["import_contract"]["document_contract"] == "nexora-knowledge-document"
    assert manifest["import_contract"]["document_contract_version"] == "2.0"
    assert "document_id" in manifest["import_contract"]["required_metadata_fields"]
    assert manifest["import_contract"]["custom_json_yaml_envelope"]["content_type"] == "string"
    assert ".docx" in manifest["import_contract"]["supported_source_extensions"]
    assert "tenant_id" not in json.dumps(manifest, ensure_ascii=False)
    assert "acl_json" not in json.dumps(manifest, ensure_ascii=False)
    assert "api_key" not in json.dumps(manifest, ensure_ascii=False)
    assert document.startswith("---\n")
    assert "switchport mode access" in document
    assert "tenant_id" not in document
    assert "acl_json" not in document
    assert "api_key" not in document


def test_build_export_rejects_unbounded_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        export_module.knowledge_service,
        "list_documents",
        lambda **kwargs: {"items": [], "total": export_module.MAX_DOCUMENTS + 1, "page": 1},
    )

    with pytest.raises(export_module.KnowledgeExportLimitError):
        export_module.knowledge_export_service.build_export(tenant_id="tenant-a")


def test_build_export_can_include_non_active_statuses(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        export_module.knowledge_service,
        "list_documents",
        lambda **kwargs: {"items": [_summary("doc-1", "Draft Guide")], "total": 1, "page": 1},
    )

    def fake_detail(doc_id, tenant_id, **kwargs):
        calls.append(kwargs)
        return _detail(doc_id, "Draft Guide", status="draft")

    monkeypatch.setattr(export_module.knowledge_service, "get_document_detail", fake_detail)
    bundle = export_module.knowledge_export_service.build_export(tenant_id="tenant-a", status="all")

    assert bundle["document_count"] == 1
    assert calls and all(call.get("include_inactive") is True for call in calls)
