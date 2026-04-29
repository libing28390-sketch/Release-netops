"""
license/models.py — License 数据结构定义
==========================================
Pydantic models for license payload, file format, and runtime status.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class LicenseType(str, enum.Enum):
    """License edition tiers."""
    TRIAL = "trial"
    STANDARD = "standard"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class LicensePayload(BaseModel):
    """
    The core data body embedded inside a signed license file.
    This is the JSON that gets signed by the RSA private key.
    """
    license_id: str = Field(..., description="Unique license identifier (UUID4)")
    company: str = Field(..., description="Licensed company name")
    license_type: LicenseType = Field(default=LicenseType.STANDARD, description="License edition tier")
    issued_at: str = Field(..., description="ISO-8601 issue timestamp")
    expire_at: str = Field(..., description="ISO-8601 expiry timestamp")
    device_limit: int = Field(default=50, ge=1, description="Maximum managed network devices")
    server_limit: int = Field(default=50, ge=1, description="Maximum managed servers")
    features: List[str] = Field(default_factory=list, description="Enabled feature flags")
    # Extensible fields for future use
    machine_id: Optional[str] = Field(default=None, description="Bound machine fingerprint (CPU/MAC)")
    metadata: Optional[dict] = Field(default=None, description="Arbitrary vendor metadata")


class LicenseFile(BaseModel):
    """
    The on-disk license file structure: payload + signature.
    """
    payload: LicensePayload
    signature: str = Field(..., description="Base64-encoded RSA-PSS signature of the payload JSON")


class LicenseStatus(BaseModel):
    """
    Runtime license status returned by the /api/license/status endpoint.
    """
    valid: bool = False
    license_id: Optional[str] = None
    company: Optional[str] = None
    license_type: Optional[str] = None
    issued_at: Optional[str] = None
    expire_at: Optional[str] = None
    days_remaining: Optional[int] = None
    device_limit: Optional[int] = None
    device_current: Optional[int] = None
    server_limit: Optional[int] = None
    server_current: Optional[int] = None
    features: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None


# ── Feature flag constants (canonical names) ──────────────────────────
# These are the strings expected in license.features[].
# Components use require_feature("rbac") etc. to gate access.

FEATURE_RBAC = "rbac"
FEATURE_AUTOMATION = "automation"
FEATURE_CONFIG_MANAGEMENT = "config_management"
FEATURE_CHANGE_ORDERS = "change_orders"
FEATURE_INSPECTIONS = "inspections"
FEATURE_TOPOLOGY = "topology"
FEATURE_MONITORING = "monitoring"
FEATURE_ALERTING = "alerting"
FEATURE_IPAM = "ipam"
FEATURE_CAPACITY = "capacity"
FEATURE_COMPLIANCE = "compliance"
FEATURE_REPORTS = "reports"
FEATURE_API_ACCESS = "api_access"
FEATURE_SCHEDULED_JOBS = "scheduled_jobs"
FEATURE_PASSWORD_ROTATION = "password_rotation"
