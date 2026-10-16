"""
Pydantic Schemas for AI Prompt Center & Prompt Versioning
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class AIPromptBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$", description="Unique prompt code identifier")
    name: str = Field(..., min_length=1, max_length=160)
    scene: str = Field(..., min_length=1, max_length=80)
    vendor: str = Field(default="all", max_length=80)
    platform: str = Field(default="all", max_length=80)
    system_prompt: str = Field(..., min_length=1, max_length=30000)
    user_prompt_template: str = Field(..., min_length=1, max_length=30000)
    output_schema: str = Field(default="{}", max_length=12000)
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(2048, ge=1, le=131072)
    enabled: bool = True


class AIPromptCreate(AIPromptBase):
    change_reason: str = Field(default="Initial prompt template", max_length=500)


class AIPromptUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    scene: Optional[str] = Field(default=None, min_length=1, max_length=80)
    vendor: Optional[str] = Field(default=None, max_length=80)
    platform: Optional[str] = Field(default=None, max_length=80)
    system_prompt: Optional[str] = Field(default=None, min_length=1, max_length=30000)
    user_prompt_template: Optional[str] = Field(default=None, min_length=1, max_length=30000)
    output_schema: Optional[str] = Field(default=None, max_length=12000)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=131072)
    enabled: Optional[bool] = None
    expected_version: Optional[int] = Field(default=None, ge=1)
    change_reason: str = Field(default="", max_length=500)


class AIPromptCopyRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    change_reason: str = Field(default="Copied from an existing prompt", max_length=500)


class AIPromptRestoreRequest(BaseModel):
    change_reason: str = Field(default="Restored from an earlier version", max_length=500)
    expected_current_version: Optional[int] = Field(default=None, ge=1)


class AIPromptResponse(AIPromptBase):
    id: str
    version: int
    created_by: Optional[str] = None
    created_at: str
    updated_at: str


class AIPromptVersionResponse(BaseModel):
    id: str
    prompt_id: str
    version: int
    system_prompt: str
    user_prompt_template: str
    output_schema: str
    temperature: float
    max_tokens: int
    created_by: Optional[str] = None
    created_at: str
    change_reason: Optional[str] = None
    change_type: Optional[str] = None
    restored_from_version: Optional[int] = None


class AIPromptPageResponse(BaseModel):
    items: list[AIPromptResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    filters: dict[str, Any] = Field(default_factory=dict)


class AIPromptVersionCompareResponse(BaseModel):
    prompt_id: str
    left: AIPromptVersionResponse
    right: AIPromptVersionResponse
    changed_fields: list[str]
    diff: dict[str, list[str]] = Field(default_factory=dict)


class AIPromptAuditEventResponse(BaseModel):
    id: str
    event_type: str
    category: str
    severity: str
    status: str
    actor_username: Optional[str] = None
    actor_role: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    target_name: Optional[str] = None
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AIPromptAuditPageResponse(BaseModel):
    items: list[AIPromptAuditEventResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
