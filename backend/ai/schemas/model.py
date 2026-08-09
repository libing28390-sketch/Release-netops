"""
Pydantic Schemas for AI Model and Scene Route Management
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, field_validator


def _validate_deepseek_model_code(value: str) -> str:
    code = str(value or '').strip()
    if code.lower().startswith('deepseek-') and code.lower() not in {'deepseek-v4-flash', 'deepseek-v4-pro'}:
        raise ValueError('DeepSeek V1 only permits deepseek-v4-flash or deepseek-v4-pro')
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

    @field_validator('model_code')
    @classmethod
    def validate_model_code(cls, value: str) -> str:
        return _validate_deepseek_model_code(value)


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

    @field_validator('model_code')
    @classmethod
    def validate_model_code(cls, value: str | None) -> str | None:
        return _validate_deepseek_model_code(value) if value is not None else value


class AIModelResponse(AIModelBase):
    id: str
    created_at: str
    updated_at: str


class AIModelRouteBase(BaseModel):
    scene: str = Field(..., description="Scene: chat, command_explain, config_explain, config_diff, alarm_analysis, natural_query, troubleshooting, agent")
    model_id: str
    fallback_model_id: Optional[str] = None
    enabled: bool = True


class AIModelRouteCreate(AIModelRouteBase):
    pass


class AIModelRouteResponse(AIModelRouteBase):
    id: str
    created_at: str
    updated_at: str
