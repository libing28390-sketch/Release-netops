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
    use_admin_creds: bool = False

    @field_validator('scope_type')
    @classmethod
    def validate_scope_type(cls, v: str) -> str:
        allowed = {'all', 'site', 'role', 'device', 'devices', 'ip', 'tags'}
        if v not in allowed:
            raise ValueError(f'scope_type must be one of {allowed}')
        return v


class InspectionScheduleCreate(BaseModel):
    name: str
    scheduled_at: str  # ISO datetime — when to execute
    expires_at: str = ''  # ISO datetime — execution window end (optional)
    cron_expr: str = ''  # kept for backward compat, empty for time-range plans
    scope_type: str = 'all'
    scope_filter: str = ''
    description: str = ''
    check_items: list[str] = []
    use_admin_creds: bool = False

    @field_validator('scope_type')
    @classmethod
    def validate_scope_type(cls, v: str) -> str:
        allowed = {'all', 'site', 'role', 'device', 'devices', 'ip', 'tags'}
        if v not in allowed:
            raise ValueError(f'scope_type must be one of {allowed}')
        return v


class InspectionScheduleUpdate(BaseModel):
    name: str | None = None
    scheduled_at: str | None = None
    expires_at: str | None = None
    cron_expr: str | None = None
    scope_type: str | None = None
    scope_filter: str | None = None
    enabled: bool | None = None
    use_admin_creds: bool | None = None
    description: str | None = None
    check_items: list[str] | None = None


# ─── Inspection Items (指标管理) ────────────────
class InspectionItemBase(BaseModel):
    name: str
    name_zh: str
    category: str
    check_key: str
    description: str = ''
    method: str = 'SNMP'
    command: str = ''
    vendor: str = ''
    oid: str = ''
    use_admin_creds: bool = False

class InspectionItemCreate(InspectionItemBase):
    pass

class InspectionItem(InspectionItemBase):
    id: str
    created_at: str
    updated_at: str


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


# ─── Rack Management 机柜管理 ────────────────────────────

_RACK_POSITIONS = {'front', 'rear'}
_RACK_DEVICE_ROLES = {'switch', 'router', 'firewall', 'server', 'storage', 'pdu', 'ups', 'patch_panel', 'other'}
_RACK_STATUSES = {'active', 'planned', 'decommissioned'}
_RACK_DEVICE_STATUSES = {'active', 'offline', 'planned', 'maintenance'}


class RackCreate(BaseModel):
    name: str
    datacenter: str = ''
    room: str = ''
    row: str = ''
    total_u: int = 42
    description: str = ''
    status: str = 'active'
    power_capacity_watts: int = 0

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 64:
            raise ValueError('name must be 1-64 characters')
        return v

    @field_validator('total_u')
    @classmethod
    def validate_total_u(cls, v: int) -> int:
        if v < 1 or v > 60:
            raise ValueError('total_u must be between 1 and 60')
        return v

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in _RACK_STATUSES:
            raise ValueError(f'status must be one of {_RACK_STATUSES}')
        return v


class RackUpdate(BaseModel):
    name: Optional[str] = None
    datacenter: Optional[str] = None
    room: Optional[str] = None
    row: Optional[str] = None
    total_u: Optional[int] = None
    description: Optional[str] = None
    status: Optional[str] = None
    power_capacity_watts: Optional[int] = None


class DeviceTypeCreate(BaseModel):
    model: str
    vendor: str = ''
    u_height: int = 1
    device_role: str = 'switch'
    is_full_depth: bool = True
    description: str = ''
    power_watts: int = 0

    @field_validator('model')
    @classmethod
    def validate_model(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 128:
            raise ValueError('model must be 1-128 characters')
        return v

    @field_validator('u_height')
    @classmethod
    def validate_u_height(cls, v: int) -> int:
        if v < 1 or v > 20:
            raise ValueError('u_height must be between 1 and 20')
        return v

    @field_validator('device_role')
    @classmethod
    def validate_device_role(cls, v: str) -> str:
        if v not in _RACK_DEVICE_ROLES:
            raise ValueError(f'device_role must be one of {_RACK_DEVICE_ROLES}')
        return v


class DeviceTypeUpdate(BaseModel):
    model: Optional[str] = None
    vendor: Optional[str] = None
    u_height: Optional[int] = None
    device_role: Optional[str] = None
    is_full_depth: Optional[bool] = None
    description: Optional[str] = None
    power_watts: Optional[int] = None


class RackDeviceCreate(BaseModel):
    name: str
    rack_id: str
    device_type_id: str
    start_u: int
    position: str = 'front'
    status: str = 'active'
    serial_number: str = ''
    asset_id: str = ''

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 128:
            raise ValueError('name must be 1-128 characters')
        return v

    @field_validator('start_u')
    @classmethod
    def validate_start_u(cls, v: int) -> int:
        if v < 1:
            raise ValueError('start_u must be >= 1')
        return v

    @field_validator('position')
    @classmethod
    def validate_position(cls, v: str) -> str:
        if v not in _RACK_POSITIONS:
            raise ValueError(f'position must be one of {_RACK_POSITIONS}')
        return v


class RackDeviceUpdate(BaseModel):
    name: Optional[str] = None
    rack_id: Optional[str] = None
    device_type_id: Optional[str] = None
    start_u: Optional[int] = None
    position: Optional[str] = None
    status: Optional[str] = None
    serial_number: Optional[str] = None
    asset_id: Optional[str] = None


class PathDiagnoseRequest(BaseModel):
    source_ip: str
    target_ip: str
    port: int = 443
    protocol: str = 'TCP'
    vrf: Optional[str] = None
    src_vrf: Optional[str] = None

    @field_validator('source_ip', 'target_ip')
    @classmethod
    def validate_ips(cls, v: str) -> str:
        v = v.strip()
        try:
            _ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f'Invalid IP address: {v}')
        return v

    @field_validator('port')
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError('port must be between 1 and 65535')
        return v

    @field_validator('protocol')
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        allowed = {'TCP', 'UDP', 'ICMP'}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f'protocol must be one of {allowed}')
        return v

