"""Typed contracts for natural-language intent decisions.

The intent parser still exposes a legacy dictionary to existing Assistant
callers.  These models make the LLM boundary strict before that compatibility
projection is created.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IntentType(str, Enum):
    ASSET_ANALYSIS = "asset_analysis"
    DEVICE_SEARCH = "device_search"
    IP_LOCATION = "ip_location"
    MAC_LOCATION = "mac_location"
    ALARM_SEARCH = "alarm_search"
    CONFIG_SEARCH = "config_search"
    TROUBLESHOOTING = "troubleshooting"
    GENERAL_QA = "general_qa"
    KNOWLEDGE = "knowledge"


class IntentRiskLevel(str, Enum):
    """Risk levels shared by intent orchestration and tool policy."""

    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"


class IntentDecision(BaseModel):
    """Validated model output used by the natural-language router."""

    model_config = ConfigDict(extra="ignore", strict=True)

    intent: IntentType
    filters: dict[str, Any] = Field(default_factory=dict, max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=64)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_clarification: bool = False
    missing_fields: list[str] = Field(default_factory=list, max_length=12)
    clarification_question: str | None = Field(default=None, max_length=1000)
    risk_level: IntentRiskLevel = IntentRiskLevel.R0
    requires_confirmation: bool = False

    @model_validator(mode="after")
    def enforce_risk_confirmation(self) -> "IntentDecision":
        if self.risk_level in {IntentRiskLevel.R3, IntentRiskLevel.R4}:
            self.requires_confirmation = True
            # A typed high-risk decision is never executable merely because
            # the model omitted a confirmation slot. Make the missing
            # confirmation explicit so every downstream caller takes the
            # local clarification path.
            if not self.missing_fields:
                self.missing_fields = ["confirmation"]
            if not self.clarification_question:
                self.clarification_question = "该请求可能涉及高风险操作，请明确目标设备、变更内容，并确认是否继续。"
        if self.missing_fields:
            self.needs_clarification = True
        return self
