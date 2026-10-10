"""
Pydantic Schemas for AI Analysis Inputs and Structured Outputs
"""

from __future__ import annotations

from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field


# --- Command Analysis ---
class CommandAnalysisRequest(BaseModel):
    command: str = Field(..., description="CLI Command string")
    output: str = Field(..., description="Raw CLI output text")
    device_id: Optional[Any] = None
    vendor: Optional[str] = None
    platform: Optional[str] = None


class CommandAnalysisResponse(BaseModel):
    request_id: str
    command_purpose: str
    summary: str
    important_fields: List[Dict[str, Any]] = []
    abnormalities: List[str] = []
    recommendations: List[str] = []


# --- Config Analysis ---
class ConfigAnalysisRequest(BaseModel):
    config_text: str = Field(..., description="Device configuration text")
    device_id: Optional[Any] = None
    vendor: Optional[str] = None
    platform: Optional[str] = None


class ConfigAnalysisResponse(BaseModel):
    request_id: str
    summary: str
    routing_protocols: List[str] = []
    security_risks: List[Dict[str, Any]] = []
    network_services: List[str] = []
    management_services: List[str] = []
    risk_items: List[Dict[str, Any]] = []
    recommendations: List[str] = []


# --- Config Diff Analysis ---
class DiffAnalysisRequest(BaseModel):
    diff_text: str = Field(..., description="Raw configuration diff text from Nexora Diff Engine")
    config_before_id: Optional[Any] = None
    config_after_id: Optional[Any] = None
    device_id: Optional[Any] = None
    vendor: Optional[str] = None
    platform: Optional[str] = None


class DiffChangeItem(BaseModel):
    type: str
    risk: str
    description: str
    possible_impact: List[str] = []


class DiffAnalysisResponse(BaseModel):
    request_id: str
    summary: str
    risk_level: str = "LOW"
    changes: List[DiffChangeItem] = []
    affected_services: List[str] = []
    verification_commands: List[str] = []
    rollback_recommendation: List[str] = []


# --- Alarm Analysis ---
class AlarmAnalysisRequest(BaseModel):
    alarm_id: Optional[Any] = None
    device_id: Optional[Any] = None
    alarm_title: str
    severity: str
    fingerprint: Optional[str] = None
    raw_content: Optional[str] = None
    context_data: Optional[Dict[str, Any]] = None


class AlarmAnalysisResponse(BaseModel):
    request_id: str
    incident_summary: str
    suspected_root_cause: str
    confidence: float = Field(0.8, ge=0.0, le=1.0)
    evidence: List[str] = []
    affected_scope: List[str] = []
    recommended_actions: List[str] = []
