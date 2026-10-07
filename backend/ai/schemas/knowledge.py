"""Strict query contract shared by conversational and administrative RAG."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai.security.sanitizer import sanitize_text
from ai.services.knowledge_metadata import (
    canonical_cli_platform,
    canonical_document_category,
    canonical_feature,
    canonical_vendor,
)


class KnowledgeScope(str, Enum):
    ALL = "all"
    OFFICIAL = "official"
    ENTERPRISE = "enterprise"


_PLAN_FIELDS = frozenset(
    {
        "vendor",
        "product_family",
        "product_series",
        "product_model",
        "os_family",
        "os_generation",
        "software_train",
        "software_release",
        "cli_platform",
        "protocol",
        "document_category",
        "feature_domain",
        "feature",
        "subfeature",
        "keyword",
        "directory_path",
        "knowledge_scope",
        "top_k",
    }
)


def _safe_text(value: Any, *, limit: int = 160) -> str | None:
    if value in (None, "", [], {}, ()):
        return None
    text = sanitize_text(str(value)).strip()
    return text[:limit] or None


def _safe_directory_path(value: Any) -> str | None:
    text = _safe_text(value, limit=512)
    if not text:
        return None
    parts = [part.strip().lower() for part in text.replace("\\", "/").split("/") if part.strip()]
    if parts and parts[0] == "kb_import":
        parts = parts[1:]
    if not parts or len(parts) > 12 or any(part in {".", ".."} for part in parts):
        return None
    if any(len(part) > 96 or not re.fullmatch(r"[a-z0-9_ .-]+", part, re.IGNORECASE) for part in parts):
        return None
    return "/".join(parts)


class KnowledgeQueryPlan(BaseModel):
    """Bounded, allowlisted query fields used before retrieval eligibility."""

    model_config = ConfigDict(extra="forbid", strict=True)

    vendor: str | None = Field(default=None, max_length=96)
    product_family: str | None = Field(default=None, max_length=160)
    product_series: str | None = Field(default=None, max_length=160)
    product_model: str | None = Field(default=None, max_length=160)
    os_family: str | None = Field(default=None, max_length=96)
    os_generation: str | None = Field(default=None, max_length=96)
    software_train: str | None = Field(default=None, max_length=96)
    software_release: str | None = Field(default=None, max_length=128)
    cli_platform: str | None = Field(default=None, max_length=128)
    protocol: str | None = Field(default=None, max_length=96)
    document_category: str | None = Field(default=None, max_length=96)
    feature_domain: str | None = Field(default=None, max_length=96)
    feature: str | None = Field(default=None, max_length=96)
    subfeature: str | None = Field(default=None, max_length=128)
    keyword: str | None = Field(default=None, max_length=512)
    directory_path: str | None = Field(default=None, max_length=512)
    knowledge_scope: KnowledgeScope = KnowledgeScope.ALL
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator(
        "vendor",
        "product_family",
        "product_series",
        "product_model",
        "os_family",
        "os_generation",
        "software_train",
        "software_release",
        "cli_platform",
        "protocol",
        "document_category",
        "feature_domain",
        "feature",
        "subfeature",
        "keyword",
        mode="before",
    )
    @classmethod
    def _normalise_text_fields(cls, value: Any) -> Any:
        return _safe_text(value)

    @field_validator("directory_path", mode="before")
    @classmethod
    def _normalise_directory(cls, value: Any) -> Any:
        return _safe_directory_path(value)

    @field_validator("vendor")
    @classmethod
    def _normalise_vendor(cls, value: str | None) -> str | None:
        return canonical_vendor(value) if value else None

    @field_validator("cli_platform")
    @classmethod
    def _normalise_cli_platform(cls, value: str | None) -> str | None:
        return canonical_cli_platform(value) if value else None

    @field_validator("document_category")
    @classmethod
    def _normalise_category(cls, value: str | None) -> str | None:
        return canonical_document_category(value) if value else None

    @field_validator("protocol", "feature")
    @classmethod
    def _normalise_feature(cls, value: str | None) -> str | None:
        return canonical_feature(value) if value else None

    @classmethod
    def from_sources(
        cls,
        message: str,
        metadata: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        *,
        knowledge_scope: Any = None,
        top_k: int = 5,
    ) -> "KnowledgeQueryPlan":
        """Build a plan from bounded parser/context fields with explicit precedence."""

        merged: dict[str, Any] = {}
        for source in (context or {}, metadata or {}):
            for key, value in dict(source).items():
                if key == "document_scope" and isinstance(value, Mapping):
                    for nested_key, nested_value in dict(value).items():
                        if nested_key in _PLAN_FIELDS or nested_key in {
                            "platform", "os", "version", "knowledgeScope", "source_scope",
                            "knowledge_directory_path", "directory", "scope",
                        }:
                            merged[nested_key] = nested_value
                    continue
                if key in _PLAN_FIELDS or key in {
                    "platform", "os", "version", "knowledgeScope", "source_scope",
                    "document_scope", "knowledge_directory_path", "directory", "scope",
                }:
                    merged[key] = value

        aliases = {
            "platform": "cli_platform",
            "os": "os_family",
            "version": "software_release",
            "knowledgeScope": "knowledge_scope",
            "source_scope": "knowledge_scope",
            "document_scope": "knowledge_scope",
            "scope": "knowledge_scope",
            "knowledge_directory_path": "directory_path",
            "directory": "directory_path",
        }
        values: dict[str, Any] = {}
        for key, value in merged.items():
            values[aliases.get(key, key)] = value

        if isinstance(knowledge_scope, Mapping):
            knowledge_scope = (
                knowledge_scope.get("knowledge_scope")
                or knowledge_scope.get("knowledgeScope")
                or knowledge_scope.get("scope")
            )
        if knowledge_scope not in (None, ""):
            values["knowledge_scope"] = knowledge_scope
        if values.get("knowledge_scope") in (None, ""):
            values["knowledge_scope"] = "all"
        scope_value = values["knowledge_scope"]
        if isinstance(scope_value, KnowledgeScope):
            scope_value = scope_value.value
        values["knowledge_scope"] = KnowledgeScope(str(scope_value).strip().lower())
        if values.get("feature") in (None, "") and values.get("protocol") not in (None, ""):
            values["feature"] = values["protocol"]
        if values.get("protocol") in (None, "") and values.get("feature") not in (None, ""):
            values["protocol"] = values["feature"]
        if values.get("keyword") in (None, ""):
            values["keyword"] = _safe_text(message, limit=512)
        values["top_k"] = max(1, min(int(top_k or values.get("top_k") or 5), 20))
        return cls.model_validate(values)

    def to_resolver_metadata(self) -> dict[str, Any]:
        values = self.model_dump(exclude_none=True)
        values.pop("knowledge_scope", None)
        values.pop("directory_path", None)
        values.pop("keyword", None)
        values.pop("top_k", None)
        if values.get("protocol") and not values.get("feature"):
            values["feature"] = values["protocol"]
        return values

    def to_retrieval_values(self) -> dict[str, Any]:
        values = self.to_resolver_metadata()
        values.update(
            {
                "knowledge_scope": self.knowledge_scope.value,
                "directory_path": self.directory_path,
                "top_k": self.top_k,
            }
        )
        return {key: value for key, value in values.items() if value not in (None, "", [], {})}


__all__ = ["KnowledgeQueryPlan", "KnowledgeScope"]
