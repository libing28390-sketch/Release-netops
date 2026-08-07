"""
Pydantic Schemas for AI Provider Management
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class AIProviderBase(BaseModel):
    name: str = Field(..., description="Provider Display Name")
    provider_type: str = Field(..., description="Provider Type: deepseek, openai, qwen, ollama, openai_compatible")
    base_url: Optional[str] = Field(None, description="API Base URL")
    timeout: int = Field(30, ge=1, le=600)
    max_retries: int = Field(3, ge=0, le=10)
    proxy_url: Optional[str] = None
    enabled: bool = True


class AIProviderCreate(AIProviderBase):
    api_key: Optional[str] = Field(None, description="Plaintext API Key (will be AES encrypted)")
    default_model_code: Optional[str] = Field(None, description="Initial Model Code (e.g. deepseek-chat, gpt-4o)")


class AIProviderUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = Field(None, description="New Plaintext API Key to update")
    timeout: Optional[int] = Field(None, ge=1, le=600)
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    proxy_url: Optional[str] = None
    enabled: Optional[bool] = None


class AIProviderResponse(AIProviderBase):
    id: str
    api_key_masked: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str
    updated_at: str


class AIProviderTestResponse(BaseModel):
    success: bool
    latency_ms: int
    message: str
    model_tested: Optional[str] = None
    sample_response: Optional[str] = None
    error_code: Optional[str] = None
