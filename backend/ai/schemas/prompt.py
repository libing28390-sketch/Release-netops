"""
Pydantic Schemas for AI Prompt Center & Prompt Versioning
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class AIPromptBase(BaseModel):
    code: str = Field(..., description="Unique prompt code identifier")
    name: str
    scene: str
    vendor: str = "all"
    platform: str = "all"
    system_prompt: str
    user_prompt_template: str
    output_schema: str = "{}"
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(2048, ge=1)
    enabled: bool = True


class AIPromptCreate(AIPromptBase):
    pass


class AIPromptUpdate(BaseModel):
    name: Optional[str] = None
    scene: Optional[str] = None
    vendor: Optional[str] = None
    platform: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt_template: Optional[str] = None
    output_schema: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enabled: Optional[bool] = None


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
