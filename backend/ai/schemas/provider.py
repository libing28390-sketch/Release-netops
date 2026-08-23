"""
Pydantic Schemas for AI Provider Management
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, field_validator

SUPPORTED_PROVIDER_TYPES = {
    "deepseek", "openai", "openai_compatible", "azure_openai", "ollama", "local", "qwen",
}


def _normalize_provider_type(value: str) -> str:
    normalized = str(value or '').strip().lower().replace('-', '_')
    if normalized not in SUPPORTED_PROVIDER_TYPES:
        raise ValueError(f'Unsupported provider_type: {normalized or "empty"}')
    return normalized


class AIProviderBase(BaseModel):
    name: str = Field(..., description="Provider Display Name")
    provider_type: str = Field(..., description="Provider Type: deepseek, openai, qwen, ollama, openai_compatible")
    base_url: Optional[str] = Field(None, description="API Base URL")
    timeout: int = Field(30, ge=1, le=600)
    max_retries: int = Field(3, ge=0, le=10)
    proxy_url: Optional[str] = None
    enabled: bool = True
    tags: list[str] = Field(default_factory=list, max_length=32)
    data_region: str = Field("unknown", max_length=64)
    allowed_data_classification: str = Field("PUBLIC", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL)$")
    # Enterprise cloud egress evidence.  These remain false/empty until an
    # administrator verifies the supplier agreement; the gateway fails closed
    # for INTERNAL data when the evidence is incomplete.
    no_training_confirmed: bool = False
    retention_days: Optional[int] = Field(None, ge=0, le=3650)
    data_processing_agreement_ref: Optional[str] = Field(None, max_length=256)
    agreement_reviewed_at: Optional[str] = Field(None, max_length=64)
    approved_endpoint_patterns: list[str] = Field(default_factory=list, max_length=32)


class AIProviderCreate(AIProviderBase):
    api_key: Optional[str] = Field(None, description="Plaintext API Key (will be AES encrypted)")
    default_model_code: Optional[str] = Field(None, description="Initial Model Code (e.g. deepseek-v4-flash, deepseek-v4-pro)")

    @field_validator('provider_type')
    @classmethod
    def validate_provider_type(cls, value: str) -> str:
        return _normalize_provider_type(value)

    @field_validator('default_model_code')
    @classmethod
    def validate_default_model_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == '':
            return value
        normalized = str(value).strip()
        if len(normalized) > 256 or any(char in normalized for char in ('\r', '\n')):
            raise ValueError('default_model_code must be <= 256 characters and single-line')
        return normalized


class AIProviderUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = Field(None, description="New Plaintext API Key to update")
    timeout: Optional[int] = Field(None, ge=1, le=600)
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    proxy_url: Optional[str] = None
    enabled: Optional[bool] = None
    tags: Optional[list[str]] = Field(None, max_length=32)
    data_region: Optional[str] = Field(None, max_length=64)
    allowed_data_classification: Optional[str] = Field(None, pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL)$")
    no_training_confirmed: Optional[bool] = None
    retention_days: Optional[int] = Field(None, ge=0, le=3650)
    data_processing_agreement_ref: Optional[str] = Field(None, max_length=256)
    agreement_reviewed_at: Optional[str] = Field(None, max_length=64)
    approved_endpoint_patterns: Optional[list[str]] = Field(None, max_length=32)

    @field_validator('provider_type')
    @classmethod
    def validate_provider_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return _normalize_provider_type(value)


class AIProviderResponse(AIProviderBase):
    id: str
    api_key_masked: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str
    updated_at: str
    health_status: str = "unknown"
    last_health_check_at: Optional[str] = None
    last_success_at: Optional[str] = None
    last_error_code: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    data_region: str = "unknown"
    allowed_data_classification: str = "PUBLIC"


class AIProviderTestResponse(BaseModel):
    success: bool
    latency_ms: int
    message: str
    model_tested: Optional[str] = None
    sample_response: Optional[str] = None
    error_code: Optional[str] = None
    provider_id: Optional[str] = None
    route_reason: Optional[str] = None
