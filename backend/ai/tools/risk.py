"""
AI Tool Risk Model (R0: READ_ONLY, R1: LOW, R2: MEDIUM, R3: HIGH, R4: CRITICAL)
"""

from __future__ import annotations

from enum import Enum


class ToolRiskLevel(str, Enum):
    R0_READ_ONLY = "R0"
    R1_LOW = "R1"
    R2_MEDIUM = "R2"
    R3_HIGH = "R3"
    R4_CRITICAL = "R4"


class RiskEngine:
    """Enforces tool execution policies based on risk levels."""

    @staticmethod
    def is_executable_by_agent(risk_level: str) -> bool:
        """Agent V1 is strictly allowed ONLY R0 and R1 read-only tools."""
        return risk_level.upper() in ["R0", "R1"]

    @staticmethod
    def requires_approval(risk_level: str) -> bool:
        return risk_level.upper() in ["R3", "R4"]


risk_engine = RiskEngine()
