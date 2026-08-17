from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.knowledge_v2_contracts import (
    CatalogVersionBundleContract,
    DefaultModelRequest,
    DocumentLifecycleContract,
    KnowledgeBaseCreateRequest,
    KnowledgeDirectoryCreateRequest,
    KnowledgeDirectoryRenameRequest,
    KnowledgeDocumentCreateRequest,
    KnowledgeReindexRequest,
    ModelAccessRequest,
    OfficialUrlImportContract,
    ProductAliasRequest,
    ProductCatalogModelRequest,
    ProviderCreateContract,
    ProviderKeyInvalidationRequest,
    ProviderKeyRotationRequest,
    RetrievalFilters,
    SearchContract,
    SourceCreateContract,
)


def _product() -> dict:
    return {
        "product_model_id": "huawei:cloudengine_6800:ce6800:ce6860-san",
        "vendor_id": "huawei",
        "vendor_name": "Huawei",
        "family_code": "cloudengine_6800",
        "family_name": "CloudEngine 6800",
        "series_code": "ce6800",
        "series_name": "CloudEngine 6800",
        "model_code": "CE6860-SAN",
        "display_name": "CloudEngine CE6860 SAN",
        "software_scope": {"os_family": "VRP8", "software_train": "V300"},
        "platform_binding_advisory": {"platform_code": "huawei_vrp", "driver_authority": False},
    }


def test_provider_model_and_source_contracts_are_typed_and_secret_safe():
    provider = ProviderCreateContract(name="DeepSeek", provider_type="deepseek", api_key="sk-test")
    assert provider.api_key == "sk-test"
    from api.knowledge_v2_contracts import ProviderResponseContract

    assert "api_key" not in ProviderResponseContract.model_fields
    with pytest.raises(ValidationError):
        ProviderKeyRotationRequest(api_key="bad\nkey")
    with pytest.raises(ValidationError):
        ProviderKeyInvalidationRequest(reason="manual", unexpected=True)
    assert SourceCreateContract.model_config["extra"] == "forbid"
    assert DocumentLifecycleContract.model_config["extra"] == "forbid"


def test_product_alias_bundle_is_nested_and_rejects_unknown_fields():
    bundle = CatalogVersionBundleContract(
        version="2026.08.17-rc1",
        models=[_product()],
        aliases=[{"product_model_id": "huawei:cloudengine_6800:ce6800:ce6860-san", "alias": "CE68", "alias_kind": "prefix"}],
    )
    assert isinstance(bundle.models[0], ProductCatalogModelRequest)
    assert isinstance(bundle.aliases[0], ProductAliasRequest)
    with pytest.raises(ValidationError):
        ProductAliasRequest(product_model_id="m1", alias="CE68", alias_kind="prefix", normalized_alias="ce68")
    with pytest.raises(ValidationError):
        CatalogVersionBundleContract(version="v1", models=[{**_product(), "metadata_secret": "never"}], aliases=[])


def test_import_and_document_contracts_bound_extensions_and_paging_controls():
    document = KnowledgeDocumentCreateRequest(name="runbook.md", content="# VLAN", metadata={"category": "commands"})
    assert document.chunk_size == 800
    assert KnowledgeBaseCreateRequest(name="NetOps", acl={"roles": ["Operator"]}).name == "NetOps"
    assert KnowledgeReindexRequest(batch_size=1000, dry_run=True).batch_size == 1000
    assert KnowledgeDirectoryCreateRequest(name="01_product").parent_id is None
    assert KnowledgeDirectoryRenameRequest(name="renamed").name == "renamed"
    with pytest.raises(ValidationError):
        KnowledgeReindexRequest(batch_size=1001)
    with pytest.raises(ValidationError):
        OfficialUrlImportContract(
            url="https://example.com/doc", vendor="huawei", product_family="ce",
            version_scope={}, terms_review_status="approved", extra_field="x",
        )


def test_search_contract_has_allowlisted_filters_and_bounded_model_preferences():
    request = SearchContract(query="show vlan", filters={"vendor": "cisco", "software_release": "17.9.x"})
    assert isinstance(request.filters, RetrievalFilters)
    assert request.filters.vendor == "cisco"
    assert DefaultModelRequest(model_id="model_1").model_id == "model_1"
    assert ModelAccessRequest(subject_type="role", subject_id="Operator").allow_access is True
    with pytest.raises(ValidationError):
        SearchContract(query="show vlan", filters={"raw_sql": "select 1"})
