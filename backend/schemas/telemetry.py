"""Pydantic models for the Telemetry control-plane contract.

Secret material is represented only by references. These models intentionally
do not define a field that accepts certificate or private-key contents.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


TelemetrySupportStatus = Literal[
    "DOCUMENTED",
    "SAMPLE_VERIFIED",
    "DEVICE_VERIFIED",
    "UNSUPPORTED",
    "UNKNOWN",
]
TelemetryTemplateStatus = Literal["DRAFT", "PUBLISHED", "RETIRED"]
TelemetryTLSStatus = Literal["ACTIVE", "ROTATION_PENDING", "EXPIRED", "REVOKED"]
TelemetryConnectionState = Literal[
    "DISABLED", "AWAITING_DEVICE", "CONNECTING", "CONNECTED", "ERROR"
]
TelemetryDataState = Literal["NO_DATA", "FRESH", "PARTIAL", "STALE", "INVALID"]
TelemetryJobAction = Literal["PUBLISH", "ENABLE", "DISABLE", "DELETE", "RETRY", "ROLLBACK"]
TelemetryJobState = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]


class TelemetryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TelemetryProtocolProfileRead(TelemetryModel):
    id: str
    profile_key: str
    vendor: str
    platform: str = ""
    model_scope: str = ""
    version_scope: str = ""
    adapter_key: str
    encoding: str
    auth_mode: str = "unknown"
    required_proto_version: str = ""
    min_interval_seconds: StrictInt | None = Field(default=None, gt=0)
    official_sources: list[str] = Field(default_factory=list)
    support_status: TelemetrySupportStatus = "UNKNOWN"
    is_system: bool = True
    created_at: str
    updated_at: str


class TelemetryMetricMapping(TelemetryModel):
    """One normalized metric mapping stored in a versioned template."""

    metric_key: str = Field(min_length=1, max_length=160)
    source_path: str = Field(min_length=1, max_length=1024)
    source_field: str = Field(default="", max_length=512)
    value_type: Literal["counter", "gauge", "state", "untyped"]
    unit: str = ""
    counter_bits: StrictInt | None = Field(default=None, gt=0, le=64)
    transform: str = ""
    primary_key_mapping: dict[str, str] = Field(default_factory=dict)
    min_interval_seconds: StrictInt | None = Field(default=None, gt=0)
    source_timestamp_semantics: Literal["sample", "collection", "unknown"] = "unknown"
    support_status: TelemetrySupportStatus = "UNKNOWN"
    evidence: list[str] = Field(default_factory=list)


class TelemetrySubscriptionTemplateCreate(TelemetryModel):
    profile_id: str = Field(min_length=1)
    template_key: str = Field(min_length=1, max_length=160)
    version: StrictInt = Field(gt=0)
    metric_mappings: list[TelemetryMetricMapping] = Field(default_factory=list)
    estimated_series: StrictInt = Field(default=0, ge=0)
    default_interval_seconds: StrictInt = Field(gt=0)
    status: TelemetryTemplateStatus = "DRAFT"

    @model_validator(mode="after")
    def validate_unique_metric_keys(self):
        keys = [mapping.metric_key for mapping in self.metric_mappings]
        if len(keys) != len(set(keys)):
            raise ValueError("metric_mappings must not contain duplicate metric_key values")
        return self


class TelemetrySubscriptionTemplateDraftUpdate(TelemetryModel):
    """Mutable draft fields; published version changes must create a new row."""

    metric_mappings: list[TelemetryMetricMapping] | None = None
    estimated_series: StrictInt | None = Field(default=None, ge=0)
    default_interval_seconds: StrictInt | None = Field(default=None, gt=0)
    status: TelemetryTemplateStatus | None = None

    @model_validator(mode="after")
    def validate_unique_metric_keys(self):
        if self.metric_mappings is not None:
            keys = [mapping.metric_key for mapping in self.metric_mappings]
            if len(keys) != len(set(keys)):
                raise ValueError("metric_mappings must not contain duplicate metric_key values")
        return self


class TelemetrySubscriptionTemplateRead(TelemetryModel):
    id: str
    tenant_id: str
    profile_id: str
    template_key: str
    version: StrictInt
    metric_mappings: list[TelemetryMetricMapping] = Field(default_factory=list)
    estimated_series: StrictInt = 0
    default_interval_seconds: StrictInt
    status: TelemetryTemplateStatus
    created_at: str
    updated_at: str


class TelemetryTLSProfileInput(TelemetryModel):
    name: str = Field(min_length=1, max_length=160)
    ca_certificate_ref: str = ""
    client_certificate_ref: str = ""
    encrypted_private_key_ref: str = ""
    fingerprint: str = ""
    valid_from: str | None = None
    valid_until: str | None = None
    version: StrictInt = Field(default=1, gt=0)
    status: TelemetryTLSStatus = "ACTIVE"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("encrypted_private_key_ref")
    @classmethod
    def reject_private_key_material(cls, value: str) -> str:
        if "-----BEGIN" in value.upper():
            raise ValueError("encrypted_private_key_ref must be a secret-store reference")
        return value.strip()


class TelemetryTLSProfileRead(TelemetryModel):
    id: str
    tenant_id: str
    name: str
    fingerprint: str
    valid_from: str | None = None
    valid_until: str | None = None
    version: StrictInt
    status: TelemetryTLSStatus
    created_at: str
    updated_at: str


class TelemetryDeviceConfigUpsert(TelemetryModel):
    profile_id: str = Field(min_length=1)
    collector_id: str = Field(min_length=1)
    device_source_address: str | None = Field(
        default=None,
        description="Expected source IP for this device's Telemetry stream; independent of allowed_sources and may differ when NAT is used.",
    )
    credential_id: str | None = None
    tls_profile_id: str | None = None
    allowed_sources: list[str] = Field(
        default_factory=list,
        description="Source IP allowlist as seen by the receiver; NAT may make it differ from device_source_address.",
    )
    enabled: bool = False
    revision: StrictInt = Field(default=1, gt=0)


class TelemetryDeviceConfigRead(TelemetryModel):
    id: str
    tenant_id: str
    asset_id: str
    device_id: str
    collector_id: str
    profile_id: str
    device_source_address: str | None = None
    credential_id: str | None = None
    tls_profile_id: str | None = None
    allowed_sources: list[str] = Field(default_factory=list)
    enabled: bool = False
    revision: StrictInt
    profile_match_state: Literal["MATCHED", "IDENTIFICATION_PENDING", "MISMATCH"] | None = None
    profile_match_fields: list[Literal["model", "version"]] = Field(default_factory=list)
    version_confirmation_required: bool = False
    profile_match_message: str = ""
    created_at: str
    updated_at: str


class TelemetrySubscriptionCreate(TelemetryModel):
    name: str = Field(min_length=1, max_length=160)
    template_id: str = Field(min_length=1)
    template_version: StrictInt = Field(gt=0)
    interval_seconds: StrictInt = Field(gt=0)
    path_filters: list[str] = Field(default_factory=list)
    reserved_series: StrictInt = Field(default=0, ge=0)
    reserved_sample_rate: float = Field(default=0, ge=0)
    desired_enabled: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class TelemetrySubscriptionUpdate(TelemetrySubscriptionCreate):
    revision: StrictInt = Field(gt=0)


class TelemetrySubscriptionRead(TelemetryModel):
    id: str
    tenant_id: str
    config_id: str
    name: str
    template_id: str
    template_version: StrictInt
    interval_seconds: StrictInt
    path_filters: list[str] = Field(default_factory=list)
    reserved_series: StrictInt = 0
    reserved_sample_rate: float = 0
    desired_enabled: bool = False
    revision: StrictInt
    created_at: str
    updated_at: str
    deleted_at: str | None = None


class TelemetrySubscriptionRuntimeRead(TelemetryModel):
    subscription_id: str
    tenant_id: str
    owner_id: str = ""
    owner_epoch: StrictInt = 0
    lease_expires_at: str | None = None
    applied_version: StrictInt | None = None
    connection_state: TelemetryConnectionState = "DISABLED"
    data_state: TelemetryDataState = "NO_DATA"
    last_received_at: str | None = None
    last_valid_at: str | None = None
    clock_skew_ms: StrictInt | None = None
    active_series: StrictInt = 0
    sample_rate: float = 0
    queue_depth: StrictInt = 0
    dropped_samples: StrictInt = 0
    reconnect_count: StrictInt = 0
    error_code: str = ""
    updated_at: str


class TelemetryConfigJobCreate(TelemetryModel):
    collector_id: str = Field(min_length=1)
    device_config_id: str | None = None
    subscription_id: str | None = None
    action: TelemetryJobAction
    desired_version: StrictInt = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def require_target(self):
        if self.device_config_id is None and self.subscription_id is None:
            raise ValueError("device_config_id or subscription_id is required")
        if self.device_config_id is not None and self.subscription_id is not None:
            raise ValueError("a job may target a device config or one subscription, not both")
        return self

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key must not be blank")
        return value


class TelemetryConfigJobRead(TelemetryModel):
    id: str
    tenant_id: str
    collector_id: str
    device_config_id: str | None = None
    subscription_id: str | None = None
    action: TelemetryJobAction
    desired_version: StrictInt
    idempotency_key: str
    state: TelemetryJobState
    attempt: StrictInt = 0
    lease_owner: str = ""
    lease_expires_at: str | None = None
    next_retry_at: str | None = None
    error_code: str = ""
    created_at: str
    updated_at: str


__all__ = [
    "TelemetrySupportStatus",
    "TelemetryTemplateStatus",
    "TelemetryTLSStatus",
    "TelemetryConnectionState",
    "TelemetryDataState",
    "TelemetryJobAction",
    "TelemetryJobState",
    "TelemetryModel",
    "TelemetryProtocolProfileRead",
    "TelemetryMetricMapping",
    "TelemetrySubscriptionTemplateCreate",
    "TelemetrySubscriptionTemplateDraftUpdate",
    "TelemetrySubscriptionTemplateRead",
    "TelemetryTLSProfileInput",
    "TelemetryTLSProfileRead",
    "TelemetryDeviceConfigUpsert",
    "TelemetryDeviceConfigRead",
    "TelemetrySubscriptionCreate",
    "TelemetrySubscriptionUpdate",
    "TelemetrySubscriptionRead",
    "TelemetrySubscriptionRuntimeRead",
    "TelemetryConfigJobCreate",
    "TelemetryConfigJobRead",
]
