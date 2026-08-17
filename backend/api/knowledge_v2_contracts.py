"""Strict Pydantic contracts shared by the Knowledge Engine V2 API.

The API boundary deliberately keeps request models separate from persistence
models.  Server-owned tenant, normalized, and audit fields are either omitted
from write contracts or represented as optional compatibility inputs that are
validated again by the service layer.  Extension objects are bounded and
explicit rather than accepting arbitrary request dictionaries at the stable
HTTP boundary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai.schemas.model import (
    AIModelCreate,
    AIModelResponse,
    AIModelRouteCreate,
    AIModelRouteResponse,
    AIModelUpdate,
)
from ai.schemas.provider import (
    AIProviderCreate,
    AIProviderResponse,
    AIProviderTestResponse,
    AIProviderUpdate,
)
from api.knowledge_documents import DocumentLifecycleRequest, DocumentVersionActionRequest
from api.knowledge_ingestion import (
    IngestionJobCancelRequest,
    IngestionJobRetryRequest,
    OfficialUrlImportRequest,
)
from api.knowledge_sources import (
    SourceFetchRequest,
    SourceLifecycleRequest,
    SourceRegistryCreateRequest,
    SourceRegistryUpdateRequest,
    SourceVersionCreateRequest,
)


class StrictContract(BaseModel):
    """Base for stable request models; unknown keys are never silently dropped."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProviderKeyRotationRequest(StrictContract):
    api_key: str = Field(..., min_length=1, max_length=4096, pattern=r"^[^\r\n]+$")


class ProviderKeyInvalidationRequest(StrictContract):
    reason: str = Field(default="manual_invalidation", min_length=1, max_length=80, pattern=r"^[^\r\n]+$")


class ModelAccessRequest(StrictContract):
    subject_type: Literal["role", "user", "tenant"] = "role"
    subject_id: str = Field(default="Operator", min_length=1, max_length=256)
    allow_access: bool = True
    # Kept as an optional compatibility input until API-008 moves the tenant
    # binding entirely to the authenticated principal.
    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)


class DefaultModelRequest(StrictContract):
    model_id: str = Field(..., min_length=1, max_length=128)


class ProductSoftwareScope(StrictContract):
    primary_version: str | None = Field(default=None, max_length=256)
    compatibility_version: str | None = Field(default=None, max_length=256)
    os_family: str | None = Field(default=None, max_length=128)
    software_train: str | None = Field(default=None, max_length=128)
    rule: str | None = Field(default=None, max_length=2000)
    unknown_version: str | None = Field(default=None, max_length=256)


class ProductPlatformBindingAdvisory(StrictContract):
    platform_code: str | None = Field(default=None, max_length=128)
    connection_driver: str | None = Field(default=None, max_length=128)
    parser_platform: str | None = Field(default=None, max_length=128)
    driver_authority: bool = False
    execution_write_authority: bool = False
    note: str | None = Field(default=None, max_length=2000)


class ProductCatalogModelRequest(StrictContract):
    product_model_id: str = Field(..., min_length=1, max_length=256)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    vendor_id: str = Field(..., min_length=1, max_length=64)
    vendor_name: str = Field(..., min_length=1, max_length=256)
    family_code: str = Field(..., min_length=1, max_length=64)
    family_name: str = Field(..., min_length=1, max_length=256)
    series_code: str = Field(..., min_length=1, max_length=64)
    series_name: str = Field(..., min_length=1, max_length=256)
    model_code: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=256)
    status: Literal["draft", "active", "disabled", "archived", "deleted", "purged"] = "draft"
    review_status: str = Field(default="pending_review", min_length=1, max_length=64)
    source_refs: list[str] = Field(default_factory=list, max_length=32)
    software_scope: ProductSoftwareScope = Field(default_factory=ProductSoftwareScope)
    platform_binding_advisory: ProductPlatformBindingAdvisory = Field(default_factory=ProductPlatformBindingAdvisory)
    source_artifact: str = Field(default="API-002-import", max_length=256)


class ProductAliasRequest(StrictContract):
    id: str | None = Field(default=None, min_length=1, max_length=256)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    product_model_id: str = Field(..., min_length=1, max_length=256)
    alias: str = Field(..., min_length=1, max_length=256)
    alias_kind: Literal["exact", "canonical", "prefix", "trigram"]
    status: Literal["draft", "active", "disabled", "archived", "deleted", "purged"] = "draft"


class CatalogVersionBundleContract(StrictContract):
    version: str = Field(..., min_length=1, max_length=64)
    models: list[ProductCatalogModelRequest] = Field(..., min_length=1, max_length=5000)
    aliases: list[ProductAliasRequest] = Field(default_factory=list, max_length=10000)


class CatalogVersionImportContract(CatalogVersionBundleContract):
    expected_active_version_id: str = Field(default="", max_length=128)
    confirm: bool = False


class CatalogVersionRollbackContract(StrictContract):
    expected_active_version_id: str = Field(default="", max_length=128)
    confirm: bool = False


class KnowledgeBaseCreateRequest(StrictContract):
    name: str = Field(default="Default KB", min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    acl: dict[str, object] = Field(default_factory=dict)


class KnowledgeDocumentCreateRequest(StrictContract):
    """Document import contract; metadata and ACL remain bounded extensions."""

    name: str = Field(default="Untitled Document", min_length=1, max_length=512)
    content: str = Field(..., min_length=1, max_length=20_000_000)
    vendor: str = Field(default="all", max_length=128)
    platform: str | None = Field(default=None, max_length=128)
    knowledge_source_type: str = Field(default="user_document", max_length=64)
    source_trust_level: str = Field(default="internal", max_length=32)
    chunk_size: int = Field(default=800, ge=128, le=4096)
    acl: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class KnowledgeReindexRequest(StrictContract):
    vendor: str | None = Field(default=None, max_length=128)
    directory_path: str | None = Field(default=None, max_length=500)
    document_id: str | None = Field(default=None, max_length=256)
    dry_run: bool = False
    run_async: bool = True
    batch_size: int = Field(default=250, ge=1, le=1000)


class KnowledgeDirectoryCreateRequest(StrictContract):
    name: str = Field(..., min_length=1, max_length=256)
    parent_id: str | None = Field(default=None, max_length=256)


class KnowledgeDirectoryRenameRequest(StrictContract):
    name: str = Field(..., min_length=1, max_length=256)


class RetrievalFilters(StrictContract):
    vendor: str | None = Field(default=None, max_length=128)
    product_family: str | None = Field(default=None, max_length=256)
    product_series: str | None = Field(default=None, max_length=256)
    product_model: str | None = Field(default=None, max_length=256)
    os_family: str | None = Field(default=None, max_length=128)
    os_generation: str | None = Field(default=None, max_length=128)
    software_train: str | None = Field(default=None, max_length=128)
    software_release: str | None = Field(default=None, max_length=128)
    cli_platform: str | None = Field(default=None, max_length=128)
    document_category: str | None = Field(default=None, max_length=128)
    feature_domain: str | None = Field(default=None, max_length=128)
    feature: str | None = Field(default=None, max_length=128)
    subfeature: str | None = Field(default=None, max_length=128)
    risk_level: str | None = Field(default=None, max_length=64)
    verification_level: str | None = Field(default=None, max_length=64)
    rag_priority: str | None = Field(default=None, max_length=64)
    applicability: str | None = Field(default=None, max_length=256)


class SearchContract(StrictContract):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


# Public names used by contract tests and API documentation.  The underlying
# source/document/import models remain defined next to their routers so the
# existing response and permission behaviour stays unchanged.
ProviderCreateContract = AIProviderCreate
ProviderUpdateContract = AIProviderUpdate
ProviderResponseContract = AIProviderResponse
ProviderTestResponseContract = AIProviderTestResponse
ModelCreateContract = AIModelCreate
ModelUpdateContract = AIModelUpdate
ModelResponseContract = AIModelResponse
ModelRouteCreateContract = AIModelRouteCreate
ModelRouteResponseContract = AIModelRouteResponse
SourceCreateContract = SourceRegistryCreateRequest
SourceUpdateContract = SourceRegistryUpdateRequest
SourceVersionContract = SourceVersionCreateRequest
SourceLifecycleContract = SourceLifecycleRequest
SourceFetchContract = SourceFetchRequest
DocumentLifecycleContract = DocumentLifecycleRequest
DocumentVersionActionContract = DocumentVersionActionRequest
OfficialUrlImportContract = OfficialUrlImportRequest
ImportCancelContract = IngestionJobCancelRequest
ImportRetryContract = IngestionJobRetryRequest


__all__ = [
    "ProviderCreateContract", "ProviderUpdateContract", "ProviderResponseContract", "ProviderTestResponseContract",
    "ProviderKeyRotationRequest", "ProviderKeyInvalidationRequest", "ModelCreateContract", "ModelUpdateContract",
    "ModelResponseContract", "ModelRouteCreateContract", "ModelRouteResponseContract", "ModelAccessRequest",
    "DefaultModelRequest", "SourceCreateContract", "SourceUpdateContract", "SourceVersionContract",
    "SourceLifecycleContract", "SourceFetchContract", "DocumentLifecycleContract", "DocumentVersionActionContract",
    "ProductSoftwareScope", "ProductPlatformBindingAdvisory", "ProductCatalogModelRequest", "ProductAliasRequest",
    "CatalogVersionBundleContract", "CatalogVersionImportContract", "CatalogVersionRollbackContract",
    "OfficialUrlImportContract", "ImportCancelContract", "ImportRetryContract", "KnowledgeBaseCreateRequest",
    "KnowledgeDocumentCreateRequest", "KnowledgeReindexRequest", "KnowledgeDirectoryCreateRequest", "KnowledgeDirectoryRenameRequest",
    "RetrievalFilters", "SearchContract",
]
