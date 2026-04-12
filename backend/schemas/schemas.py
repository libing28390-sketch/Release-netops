from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime
import ipaddress as _ipaddress
import re as _re

class DeviceBase(BaseModel):
    hostname: str
    ip_address: str
    platform: str
    username: str

class DeviceCreate(DeviceBase):
    password: str

class Device(DeviceBase):
    id: int
    created_at: str

    class Config:
        from_attributes = True

class JobBase(BaseModel):
    device_id: int
    task_name: str

class Job(JobBase):
    id: int
    status: str
    created_at: str
    completed_at: Optional[str] = None
    logs: Optional[str] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# IPAM Schemas
# ──────────────────────────────────────────────

_MAC_RE = _re.compile(r'^([0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}$')


class SubnetCreate(BaseModel):
    name: str = ''
    network: str
    prefix_len: int
    vlan_id: Optional[int] = None
    vlan_name: str = ''
    gateway: str = ''
    description: str = ''
    site: str = ''

    @field_validator('network')
    @classmethod
    def validate_network(cls, v: str) -> str:
        _ipaddress.ip_address(v)  # raises ValueError if invalid
        return v

    @field_validator('prefix_len')
    @classmethod
    def validate_prefix_len(cls, v: int) -> int:
        if not 1 <= v <= 128:
            raise ValueError('prefix_len must be between 1 and 128')
        return v

    @field_validator('gateway')
    @classmethod
    def validate_gateway(cls, v: str) -> str:
        if v:
            _ipaddress.ip_address(v)
        return v


class SubnetUpdate(BaseModel):
    name: Optional[str] = None
    vlan_id: Optional[int] = None
    vlan_name: Optional[str] = None
    gateway: Optional[str] = None
    description: Optional[str] = None
    site: Optional[str] = None
    status: Optional[str] = None

    @field_validator('gateway')
    @classmethod
    def validate_gateway(cls, v: Optional[str]) -> Optional[str]:
        if v:
            _ipaddress.ip_address(v)
        return v

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in ('active', 'reserved', 'deprecated'):
            raise ValueError("status must be one of: active, reserved, deprecated")
        return v


class IPAddressCreate(BaseModel):
    address: str
    hostname: str = ''
    device_id: str = ''
    interface_name: str = ''
    mac_address: str = ''
    device_type: str = ''
    description: str = ''
    status: str = 'active'

    @field_validator('address')
    @classmethod
    def validate_address(cls, v: str) -> str:
        _ipaddress.ip_address(v)
        return v

    @field_validator('mac_address')
    @classmethod
    def validate_mac(cls, v: str) -> str:
        if v and not _MAC_RE.match(v):
            raise ValueError('Invalid MAC address format (expected XX:XX:XX:XX:XX:XX)')
        return v

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ('active', 'reserved', 'deprecated'):
            raise ValueError("status must be one of: active, reserved, deprecated")
        return v


class IPAddressUpdate(BaseModel):
    hostname: Optional[str] = None
    device_id: Optional[str] = None
    interface_name: Optional[str] = None
    mac_address: Optional[str] = None
    device_type: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None

    @field_validator('mac_address')
    @classmethod
    def validate_mac(cls, v: Optional[str]) -> Optional[str]:
        if v and not _MAC_RE.match(v):
            raise ValueError('Invalid MAC address format (expected XX:XX:XX:XX:XX:XX)')
        return v

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in ('active', 'reserved', 'deprecated'):
            raise ValueError("status must be one of: active, reserved, deprecated")
        return v


# ──────────────────────────────────────────────
# IP Locator Schemas
# ──────────────────────────────────────────────

class IPLocateRequest(BaseModel):
    ip: str
    force_refresh: bool = False

    @field_validator('ip')
    @classmethod
    def validate_ip(cls, v: str) -> str:
        v = v.strip()
        try:
            _ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f'Invalid IP address: {v}')
        return v


class ConnectivityProbeRequest(BaseModel):
    target: str
    tests: list[str] = ['ping', 'tcp', 'traceroute']
    tcp_ports: list[int] = [22, 80, 443]
    source_device_id: int | None = None
    source_interface: str = ''
    ping_count: int = 4

    @field_validator('target')
    @classmethod
    def validate_target(cls, v: str) -> str:
        v = v.strip()
        try:
            _ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f'Invalid IP address: {v}')
        return v

    @field_validator('tests')
    @classmethod
    def validate_tests(cls, v: list[str]) -> list[str]:
        allowed = {'ping', 'tcp', 'traceroute'}
        return [t for t in v if t in allowed]

    @field_validator('tcp_ports')
    @classmethod
    def validate_ports(cls, v: list[int]) -> list[int]:
        return [p for p in v if 1 <= p <= 65535][:10]

    @field_validator('ping_count')
    @classmethod
    def validate_ping_count(cls, v: int) -> int:
        return max(1, min(v, 10))


# ─── Inspection 巡检 ─────────────────────────

class InspectionRunRequest(BaseModel):
    scope_type: str = 'all'
    scope_filter: str = ''

    @field_validator('scope_type')
    @classmethod
    def validate_scope_type(cls, v: str) -> str:
        allowed = {'all', 'site', 'role', 'device', 'devices'}
        if v not in allowed:
            raise ValueError(f'scope_type must be one of {allowed}')
        return v


class InspectionScheduleCreate(BaseModel):
    name: str
    cron_expr: str
    scope_type: str = 'all'
    scope_filter: str = ''

    @field_validator('scope_type')
    @classmethod
    def validate_scope_type(cls, v: str) -> str:
        allowed = {'all', 'site', 'role', 'device', 'devices'}
        if v not in allowed:
            raise ValueError(f'scope_type must be one of {allowed}')
        return v


class InspectionScheduleUpdate(BaseModel):
    name: str | None = None
    cron_expr: str | None = None
    scope_type: str | None = None
    scope_filter: str | None = None
    enabled: bool | None = None


# ─── Tag 标签系统 ─────────────────────────────

_TAG_CATEGORIES = {'device_type', 'vendor', 'os', 'role', 'env', 'function', 'custom'}

class TagDefinitionCreate(BaseModel):
    category: str
    value: str
    label: str
    label_zh: str = ''
    color: str = ''
    icon: str = ''
    description: str = ''
    sort_order: int = 0

    @field_validator('category')
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in _TAG_CATEGORIES:
            raise ValueError(f'category must be one of {_TAG_CATEGORIES}')
        return v

    @field_validator('value')
    @classmethod
    def validate_value(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or len(v) > 64:
            raise ValueError('value must be 1-64 characters')
        if not _re.match(r'^[a-z0-9][a-z0-9._-]*$', v):
            raise ValueError('value must start with a-z/0-9 and contain only a-z, 0-9, dot, dash, underscore')
        return v


class TagDefinitionUpdate(BaseModel):
    label: str | None = None
    label_zh: str | None = None
    color: str | None = None
    icon: str | None = None
    description: str | None = None
    sort_order: int | None = None
    category: str | None = None
    value: str | None = None

    @field_validator('category')
    @classmethod
    def validate_category(cls, v: str | None) -> str | None:
        if v is not None and v not in _TAG_CATEGORIES:
            raise ValueError(f'category must be one of {_TAG_CATEGORIES}')
        return v


class DeviceTagsUpdate(BaseModel):
    tag_ids: List[str]


class BatchDeviceTagsUpdate(BaseModel):
    device_ids: List[str]
    tag_ids: List[str]
