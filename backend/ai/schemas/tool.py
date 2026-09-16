"""Strict contracts for AI tool planning and agent responses.

The tool planner is intentionally separate from handlers.  A model can
propose a bounded plan, but the execution layer must validate the plan again
against the registered tool, authorization context, and one-time approval.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai.tools.risk import ToolRiskLevel


class ToolPlanStatus(str, Enum):
    READY = "ready"
    PREVIEW = "preview"
    CONFIRMATION_REQUIRED = "confirmation_required"
    DENIED = "denied"


class ToolCallPlan(BaseModel):
    """Bounded, auditable proposal for one tool invocation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    tool_name: str = Field(..., min_length=1, max_length=120, pattern=r"^[a-z][a-z0-9_.-]{0,119}$")
    arguments: dict[str, Any] = Field(default_factory=dict, max_length=32)
    device_id: str | None = Field(default=None, max_length=160)
    vendor: str | None = Field(default=None, max_length=96)
    platform: str | None = Field(default=None, max_length=128)
    action: str = Field(default="read", min_length=1, max_length=96)
    risk_level: ToolRiskLevel = ToolRiskLevel.R0_READ_ONLY
    read_only: bool = True
    requires_confirmation: bool = False
    dry_run: bool = True
    change_order_id: str | None = Field(default=None, max_length=160)
    device_state: str | None = Field(default=None, max_length=96)
    impact_scope: str | None = Field(default=None, max_length=512)
    expected_impact: list[str] = Field(default_factory=list, max_length=8)
    status: ToolPlanStatus = ToolPlanStatus.PREVIEW
    confirmation_token: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def enforce_high_risk_gate(self) -> "ToolCallPlan":
        high_risk = self.risk_level in {ToolRiskLevel.R3_HIGH, ToolRiskLevel.R4_CRITICAL}
        if high_risk or not self.read_only:
            self.requires_confirmation = True
            if self.status == ToolPlanStatus.READY and self.confirmation_token is None:
                self.status = ToolPlanStatus.CONFIRMATION_REQUIRED
            if self.status == ToolPlanStatus.CONFIRMATION_REQUIRED:
                self.dry_run = True
        return self


class AgentResponse(BaseModel):
    """Strict JSON envelope emitted by an autonomous agent model."""

    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["tool_call", "final_answer"] = "final_answer"
    tool_name: str | None = Field(default=None, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict, max_length=32)
    result: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def validate_action_shape(self) -> "AgentResponse":
        if self.action == "tool_call" and not self.tool_name:
            raise ValueError("tool_call requires tool_name")
        if self.action == "final_answer" and self.tool_name is not None:
            raise ValueError("final_answer cannot include tool_name")
        return self


__all__ = ["AgentResponse", "ToolCallPlan", "ToolPlanStatus"]
