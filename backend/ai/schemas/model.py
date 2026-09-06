"""
Pydantic Schemas for AI Model and Scene Route Management
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, field_validator


SUPPORTED_MODEL_TYPES = {"chat", "reasoning", "embedding", "rerank"}


def _validate_model_code(value: str) -> str:
    code = str(value or '').strip()
    if not code or len(code) > 256:
        raise ValueError('model_code must be non-empty and <= 256 characters')
    return code


class AIModelBase(BaseModel):
    provider_id: str
    name: str
    model_code: str = Field(..., description="Actual model string sent to API (e.g. deepseek-v4-flash, deepseek-v4-pro)")
    model_type: str = Field("chat", description="chat, reasoning, embedding")
    thinking_supported: bool = False
    tool_call_supported: bool = True
    json_supported: bool = True
    context_length: int = Field(32768, ge=1024)
    max_output_tokens: int = Field(4096, ge=128)
    default_temperature: float = Field(0.7, ge=0.0, le=2.0)
    default_max_tokens: int = Field(2048, ge=1)
    enabled: bool = True
    is_default: bool = False
    priority: int = Field(10, ge=1)
    stream_supported: bool = True
    display_name: Optional[str] = None
    cost_input_per_1k: float = Field(0, ge=0)
    cost_output_per_1k: float = Field(0, ge=0)

    @field_validator('model_code')
    @classmethod
    def validate_model_code(cls, value: str) -> str:
        return _validate_model_code(value)

    @field_validator('model_type')
    @classmethod
    def validate_model_type(cls, value: str) -> str:
        normalized = str(value or '').strip().lower()
        if normalized not in SUPPORTED_MODEL_TYPES:
            raise ValueError(f'Unsupported model_type: {normalized or "empty"}')
        return normalized


class AIModelCreate(AIModelBase):
    pass


class AIModelUpdate(BaseModel):
    provider_id: Optional[str] = None
    name: Optional[str] = None
    model_code: Optional[str] = None
    model_type: Optional[str] = None
    thinking_supported: Optional[bool] = None
    tool_call_supported: Optional[bool] = None
    json_supported: Optional[bool] = None
    context_length: Optional[int] = None
    max_output_tokens: Optional[int] = None
    default_temperature: Optional[float] = None
    default_max_tokens: Optional[int] = None
    enabled: Optional[bool] = None
    is_default: Optional[bool] = None
    priority: Optional[int] = None
    stream_supported: Optional[bool] = None
    display_name: Optional[str] = None
    cost_input_per_1k: Optional[float] = Field(None, ge=0)
    cost_output_per_1k: Optional[float] = Field(None, ge=0)

    @field_validator('model_code')
    @classmethod
    def validate_model_code(cls, value: str | None) -> str | None:
        return _validate_model_code(value) if value is not None else value

    @field_validator('model_type')
    @classmethod
    def validate_model_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = str(value).strip().lower()
        if normalized not in SUPPORTED_MODEL_TYPES:
            raise ValueError(f'Unsupported model_type: {normalized}')
        return normalized


class AIModelResponse(AIModelBase):
    id: str
    created_at: str
    updated_at: str
    stream_supported: bool = True
    display_name: Optional[str] = None
    cost_input_per_1k: float = 0
    cost_output_per_1k: float = 0
    health_status: str = "unknown"
    last_latency_ms: Optional[int] = None
    last_success_at: Optional[str] = None
    last_error_code: Optional[str] = None


class AIModelRouteBase(BaseModel):
    scene: str = Field(..., description="Scene: chat, command_explain, config_explain, config_diff, alarm_analysis, natural_query, troubleshooting, agent")
    model_id: str
    fallback_model_id: Optional[str] = None
    enabled: bool = True
    priority: int = Field(10, ge=1, le=10000)
    data_classification: str = Field("PUBLIC", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL)$")


class AIModelRouteCreate(AIModelRouteBase):
    pass


class AIModelRouteResponse(AIModelRouteBase):
    id: str
    created_at: str
    updated_at: str
