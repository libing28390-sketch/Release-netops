from pydantic import BaseModel, Field, field_validator, model_validator
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

def _normalize_mac(v: Optional[str]) -> Optional[str]:
    if not v:
        return v
    clean = _re.sub(r'[^0-9a-fA-F]', '', v)
    if len(clean) != 12:
        raise ValueError('Invalid MAC address format (expected XX:XX:XX:XX:XX:XX)')
    return ':'.join(clean[i:i+2].lower() for i in range(0, 12, 2))


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
        return _normalize_mac(v) or ''

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
        return _normalize_mac(v)

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

_TAG_CATEGORIES = {'business', 'environment', 'network_zone', 'operations', 'security', 'project', 'lifecycle', 'technology'}

class TagDefinitionCreate(BaseModel):
    category: str
    code: str
    label: str
    label_zh: str = ''
    color: str = ''
    icon: str = ''
    description: str = ''
    resource_types: List[str] = ['device']
    exclusive_group: str = ''
    priority: int = 0
    sort_order: int = 0

    @field_validator('category')
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in _TAG_CATEGORIES:
            raise ValueError(f'category must be one of {_TAG_CATEGORIES}')
        return v

    @field_validator('code')
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or len(v) > 96:
            raise ValueError('code must be 1-96 characters')
        if not _re.match(r'^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$', v):
            raise ValueError('code must start with a-z and use lowercase letters, digits, dot, dash or underscore')
        return v


class TagDefinitionUpdate(BaseModel):
    label: str | None = None
    label_zh: str | None = None
    color: str | None = None
    icon: str | None = None
    description: str | None = None
    sort_order: int | None = None
    exclusive_group: str | None = None
    priority: int | None = None
    is_active: int | None = None

class DeviceTagsUpdate(BaseModel):
    tag_ids: List[str]


class BatchDeviceTagsUpdate(BaseModel):
    device_ids: List[str]
    tag_ids: List[str]


class TagTargetFilter(BaseModel):
    include_groups: List[List[str]] = []
    exclude_tag_ids: List[str] = []
    expression: dict | None = None


# ─── Rack Management 机柜管理 ────────────────────────────

_RACK_POSITIONS = {'front', 'rear'}
_RACK_DEVICE_ROLES = {'switch', 'router', 'firewall', 'server', 'storage', 'pdu', 'ups', 'patch_panel', 'other'}
_RACK_STATUSES = {'active', 'planned', 'decommissioned'}
_RACK_DEVICE_STATUSES = {'active', 'offline', 'planned', 'maintenance'}


class RackCreate(BaseModel):
    name: str
    # Canonical location relation. ``datacenter`` remains optional only so
    # older import payloads can be resolved during the transition.
    datacenter: str = ''
    floor: str = ''
    room: str = ''
    row: str = ''
    total_u: int = 42
    description: str = ''
    status: str = 'active'
    power_capacity_watts: int = 0
    placement_strategy: str = 'bottom_first'
    rack_type_id: Optional[str] = ''
    width_mm: Optional[int] = 600
    depth_mm: Optional[int] = 1000
    allow_front_rear_mount: Optional[bool] = True

    site_id: Optional[str] = None
    rack_code: Optional[str] = ''
    rack_name: Optional[str] = ''
    room_name: Optional[str] = ''
    row_name: Optional[str] = ''
    used_u: Optional[int] = 0
    available_u: Optional[int] = 42
    power_capacity_w: Optional[int] = 5000
    current_power_w: Optional[int] = 0
    power_utilization: Optional[float] = 0.0
    max_weight_kg: Optional[int] = None
    current_weight_kg: Optional[int] = 0
    cooling_zone: Optional[str] = ''
    remarks: Optional[str] = ''

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

    @field_validator('placement_strategy')
    @classmethod
    def validate_placement_strategy(cls, v: str) -> str:
        if v not in ('bottom_first', 'top_first'):
            raise ValueError("placement_strategy must be either 'bottom_first' or 'top_first'")
        return v


class RackUpdate(BaseModel):
    name: Optional[str] = None
    # Legacy compatibility input; new UI/API writes must use site_id.
    datacenter: Optional[str] = None
    floor: Optional[str] = None
    room: Optional[str] = None
    row: Optional[str] = None
    total_u: Optional[int] = None
    description: Optional[str] = None
    status: Optional[str] = None
    power_capacity_watts: Optional[int] = None
    placement_strategy: Optional[str] = None
    rack_type_id: Optional[str] = None
    width_mm: Optional[int] = None
    depth_mm: Optional[int] = None
    allow_front_rear_mount: Optional[bool] = None

    site_id: Optional[str] = None
    rack_code: Optional[str] = None
    rack_name: Optional[str] = None
    room_name: Optional[str] = None
    row_name: Optional[str] = None
    used_u: Optional[int] = None
    available_u: Optional[int] = None
    power_capacity_w: Optional[int] = None
    current_power_w: Optional[int] = None
    power_utilization: Optional[float] = None
    max_weight_kg: Optional[int] = None
    current_weight_kg: Optional[int] = None
    cooling_zone: Optional[str] = None
    remarks: Optional[str] = None

    @field_validator('placement_strategy')
    @classmethod
    def validate_placement_strategy(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ('bottom_first', 'top_first'):
            raise ValueError("placement_strategy must be either 'bottom_first' or 'top_first'")
        return v


class RackTypeCreate(BaseModel):
    name: str
    vendor: str = ''
    model: str = ''
    total_u: int = 42
    width_mm: int = 600
    depth_mm: int = 1000
    max_weight_kg: int = 0
    power_capacity_watts: int = 0
    allow_front_rear_mount: bool = True
    description: str = ''

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


class RackTypeUpdate(BaseModel):
    name: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    total_u: Optional[int] = None
    width_mm: Optional[int] = None
    depth_mm: Optional[int] = None
    max_weight_kg: Optional[int] = None
    power_capacity_watts: Optional[int] = None
    allow_front_rear_mount: Optional[bool] = None
    description: Optional[str] = None



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



# ─── Credential Vault ───────────────────────────────────

_CREDENTIAL_TYPES = {
    'ssh_password', 'ssh_key', 'snmpv2', 'snmpv3', 'api_token',
}

_CREDENTIAL_ACCOUNT_ROLES = {'normal', 'admin', 'shared', 'unbound'}


class CredentialCreate(BaseModel):
    credential_name: str
    credential_type: str = 'ssh_password'
    username: str = ''
    account_role: str = 'normal'
    password: str = ''          # plaintext on input; stored encrypted
    enable_password: str = ''   # plaintext on input; stored encrypted
    private_key: str = ''       # plaintext on input; stored encrypted
    snmp_community: str = ''     # plaintext on input; stored encrypted
    snmp_server: str = ''        # optional SNMP target override; blank uses device management IP

    @field_validator('credential_name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError('credential_name must be 1-100 characters')
        return v

    @field_validator('credential_type')
    @classmethod
    def validate_type(cls, v: str) -> str:
        v = v.strip()
        if v not in _CREDENTIAL_TYPES:
            raise ValueError(f'credential_type must be one of {sorted(_CREDENTIAL_TYPES)}')
        return v

    @field_validator('account_role')
    @classmethod
    def validate_account_role(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _CREDENTIAL_ACCOUNT_ROLES:
            raise ValueError(f'account_role must be one of {sorted(_CREDENTIAL_ACCOUNT_ROLES)}')
        return v


class CredentialUpdate(BaseModel):
    credential_name: Optional[str] = None
    credential_type: Optional[str] = None
    username: Optional[str] = None
    account_role: Optional[str] = None
    password: Optional[str] = None
    enable_password: Optional[str] = None
    old_password: Optional[str] = None
    old_enable_password: Optional[str] = None
    private_key: Optional[str] = None
    snmp_community: Optional[str] = None
    snmp_server: Optional[str] = None

    @field_validator('credential_name')
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError('credential_name must be 1-100 characters')
        return v

    @field_validator('credential_type')
    @classmethod
    def validate_type(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if v not in _CREDENTIAL_TYPES:
            raise ValueError(f'credential_type must be one of {sorted(_CREDENTIAL_TYPES)}')
        return v

    @field_validator('account_role')
    @classmethod
    def validate_account_role(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().lower()
        if v not in _CREDENTIAL_ACCOUNT_ROLES:
            raise ValueError(f'account_role must be one of {sorted(_CREDENTIAL_ACCOUNT_ROLES)}')
        return v

    @model_validator(mode='after')
    def validate_secret_change_confirmation(self):
        if self.password is not None and not self.password:
            raise ValueError('password must be omitted when unchanged; clearing a password is not supported')
        if self.enable_password is not None and not self.enable_password:
            raise ValueError('enable_password must be omitted when unchanged; clearing a password is not supported')
        if self.password is not None and self.old_password is None:
            raise ValueError('old_password is required when changing password')
        if self.enable_password is not None and self.old_enable_password is None:
            raise ValueError('old_enable_password is required when changing enable_password')
        return self


# ─── CMDB Core Entities (tenants / sites / vrfs / vlans) ───

_SITE_STATUSES = {'active', 'planned', 'staging', 'decommissioned', 'offline'}

# Contact information is part of the operational site record.  Keep the
# rules deliberately conservative: names are human names (not arbitrary
# numbers), phone numbers support Chinese mobile/landline and E.164-style
# international values, and email follows the usual mailbox@domain shape.
_CONTACT_NAME_RE = _re.compile(r"^[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z· .'-]{1,49}$")
_CONTACT_PHONE_RE = _re.compile(r"^(?:1[3-9]\d{9}|0\d{2,3}-?\d{7,8}|\+?[1-9]\d{6,14})$")
_CONTACT_PHONE_INTERNATIONAL_RE = _re.compile(r"^\+[1-9]\d{7,14}$")
_CHINA_COUNTRY_VALUES = {'', '中国', 'China', 'CN'}
_CONTACT_EMAIL_RE = _re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def _contact_name(value: Optional[str], *, required: bool) -> Optional[str]:
    if value is None:
        if required:
            raise ValueError('contact_name is required')
        return value
    value = value.strip()
    if not value:
        if required:
            raise ValueError('contact_name is required')
        return ''
    if len(value) > 50 or not _CONTACT_NAME_RE.fullmatch(value):
        raise ValueError('contact_name must be 2-50 Chinese or English letters')
    return value


def _contact_phone(value: Optional[str], *, required: bool, international_required: bool = False) -> Optional[str]:
    if value is None:
        if required:
            raise ValueError('contact_phone is required')
        return value
    value = value.strip()
    if not value:
        if required:
            raise ValueError('contact_phone is required')
        return ''
    if len(value) > 32 or not _CONTACT_PHONE_RE.fullmatch(value):
        raise ValueError('contact_phone must be an 11-digit mobile, valid landline, or international number')
    if international_required and not _CONTACT_PHONE_INTERNATIONAL_RE.fullmatch(value):
        raise ValueError('contact_phone must include an international country calling code, for example +8613800000000')
    return value


def _contact_email(value: Optional[str], *, required: bool) -> Optional[str]:
    if value is None:
        if required:
            raise ValueError('contact_email is required')
        return value
    value = value.strip()
    if not value:
        if required:
            raise ValueError('contact_email is required')
        return ''
    if len(value) > 254 or not _CONTACT_EMAIL_RE.fullmatch(value):
        raise ValueError('contact_email must be a valid email address')
    return value


class TenantCreate(BaseModel):
    name: str
    description: str = ''

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError('name must be 1-100 characters')
        return v


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError('name must be 1-100 characters')
        return v


class SiteCreate(BaseModel):
    # Site codes are generated by the backend.  Keep the field optional for
    # backwards-compatible API clients, but do not require user input.
    site_code: Optional[str] = None
    site_name: str
    country: str = ''
    state_province: str = ''
    city: str = ''
    district: str = ''
    contact_name: str
    contact_phone: str
    contact_email: str
    timezone: str = 'Asia/Shanghai'
    address: str = ''
    status: str = 'active'
    tenant_id: str = 'tenant-default'

    @field_validator('site_name')
    @classmethod
    def validate_required(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError('value must be 1-100 characters')
        return v

    @field_validator('site_code')
    @classmethod
    def validate_optional_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if len(v) > 100:
            raise ValueError('site_code must be empty or 1-100 characters')
        return v

    @field_validator('contact_name')
    @classmethod
    def validate_contact_name(cls, v: str) -> str:
        return _contact_name(v, required=True) or ''

    @field_validator('contact_phone')
    @classmethod
    def validate_contact_phone(cls, v: str) -> str:
        return _contact_phone(v, required=True) or ''

    @field_validator('contact_email')
    @classmethod
    def validate_contact_email(cls, v: str) -> str:
        return _contact_email(v, required=True) or ''

    @model_validator(mode='after')
    def validate_phone_for_country(self):
        # When the site country is China, an international value must contain
        # the complete +86 prefix plus an 11-digit mobile number.  The
        # generic E.164 validator intentionally remains broader for other
        # countries, but must not admit a truncated +86 number here.
        if self.country in _CHINA_COUNTRY_VALUES and not _re.fullmatch(r'^(?:1[3-9]\d{9}|0\d{2,3}-?\d{7,8}|\+861[3-9]\d{9})$', self.contact_phone):
            raise ValueError('contact_phone must be a valid +86 Chinese mobile, landline, or international number')
        return self

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in _SITE_STATUSES:
            raise ValueError(f'status must be one of {sorted(_SITE_STATUSES)}')
        return v


class SiteImportRequest(BaseModel):
    """Validated site rows submitted by the spreadsheet import workflow."""

    rows: List[SiteCreate] = Field(..., min_length=1, max_length=1000)


class SiteUpdate(BaseModel):
    site_code: Optional[str] = None
    site_name: Optional[str] = None
    country: Optional[str] = None
    state_province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    timezone: Optional[str] = None
    address: Optional[str] = None
    status: Optional[str] = None
    tenant_id: Optional[str] = None

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in _SITE_STATUSES:
            raise ValueError(f'status must be one of {sorted(_SITE_STATUSES)}')
        return v

    @field_validator('contact_name')
    @classmethod
    def validate_contact_name(cls, v: Optional[str]) -> Optional[str]:
        return _contact_name(v, required=False)

    @field_validator('contact_phone')
    @classmethod
    def validate_contact_phone(cls, v: Optional[str]) -> Optional[str]:
        return _contact_phone(v, required=False)

    @field_validator('contact_email')
    @classmethod
    def validate_contact_email(cls, v: Optional[str]) -> Optional[str]:
        return _contact_email(v, required=False)


class VrfCreate(BaseModel):
    vrf_name: str
    rd: str = ''
    description: str = ''
    tenant_id: str = 'tenant-default'

    @field_validator('vrf_name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError('vrf_name must be 1-100 characters')
        return v


class VrfUpdate(BaseModel):
    vrf_name: Optional[str] = None
    rd: Optional[str] = None
    description: Optional[str] = None
    tenant_id: Optional[str] = None

    @field_validator('vrf_name')
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError('vrf_name must be 1-100 characters')
        return v


class VlanCreate(BaseModel):
    vlan_id: int
    name: str
    site_id: Optional[str] = None
    status: str = 'active'
    tenant_id: str = 'tenant-default'

    @field_validator('vlan_id')
    @classmethod
    def validate_vlan_id(cls, v: int) -> int:
        if not (1 <= v <= 4094):
            raise ValueError('vlan_id must be between 1 and 4094')
        return v

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError('name must be 1-100 characters')
        return v


class VlanUpdate(BaseModel):
    vlan_id: Optional[int] = None
    name: Optional[str] = None
    site_id: Optional[str] = None
    status: Optional[str] = None
    tenant_id: Optional[str] = None

    @field_validator('vlan_id')
    @classmethod
    def validate_vlan_id(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if not (1 <= v <= 4094):
            raise ValueError('vlan_id must be between 1 and 4094')
        return v


class VlanBusinessBindingCreate(BaseModel):
    site_id: str = ''
    vrf_id: str = ''
    vlan_id: int
    business_system: str
    department: str = ''
    owner: str = ''
    business_level: str = 'P3'
    status: str = 'active'
    description: str = ''

    @field_validator('vlan_id')
    @classmethod
    def validate_binding_vlan_id(cls, v: int) -> int:
        if not (1 <= v <= 4094):
            raise ValueError('vlan_id must be between 1 and 4094')
        return v

    @field_validator('business_system', 'department', 'owner', 'description')
    @classmethod
    def normalize_binding_text(cls, v: str) -> str:
        return str(v or '').strip()

    @field_validator('business_system')
    @classmethod
    def validate_business_system(cls, v: str) -> str:
        if not v or len(v) > 160:
            raise ValueError('business_system must be 1-160 characters')
        return v

    @field_validator('business_level')
    @classmethod
    def validate_business_level(cls, v: str) -> str:
        value = str(v or '').strip().upper()
        if value not in {'P1', 'P2', 'P3', 'P4'}:
            raise ValueError('business_level must be P1, P2, P3 or P4')
        return value

    @field_validator('status')
    @classmethod
    def validate_business_status(cls, v: str) -> str:
        value = str(v or '').strip().lower()
        if value not in {'active', 'planned', 'retired'}:
            raise ValueError('status must be active, planned or retired')
        return value


class VlanBusinessBindingUpdate(BaseModel):
    site_id: Optional[str] = None
    vrf_id: Optional[str] = None
    vlan_id: Optional[int] = None
    business_system: Optional[str] = None
    department: Optional[str] = None
    owner: Optional[str] = None
    business_level: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None

    @field_validator('vlan_id')
    @classmethod
    def validate_binding_vlan_id(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 4094):
            raise ValueError('vlan_id must be between 1 and 4094')
        return v

    @field_validator('business_system', 'department', 'owner', 'description')
    @classmethod
    def normalize_binding_text(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else str(v).strip()

    @field_validator('business_system')
    @classmethod
    def validate_business_system(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and (not v or len(v) > 160):
            raise ValueError('business_system must be 1-160 characters')
        return v

    @field_validator('business_level')
    @classmethod
    def validate_business_level(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip().upper()
        if value not in {'P1', 'P2', 'P3', 'P4'}:
            raise ValueError('business_level must be P1, P2, P3 or P4')
        return value

    @field_validator('status')
    @classmethod
    def validate_business_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip().lower()
        if value not in {'active', 'planned', 'retired'}:
            raise ValueError('status must be active, planned or retired')
        return value


# ─── New IPAM Schemas (Prefix, Pool, VIP, Lease) ───────────────────

class PrefixCreate(BaseModel):
    prefix: str
    vrf_id: Optional[str] = None
    vlan_id: Optional[str] = None
    site_id: Optional[str] = None
    tenant_id: Optional[str] = 'tenant-default'
    status: str = 'active'
    name: str = ''
    gateway: str = ''
    description: str = ''
    network_type: str = 'server'
    gateway_device_id: Optional[str] = None
    gateway_interface_id: Optional[str] = None
    traceable: int = 1

    @field_validator('prefix')
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        try:
            _ipaddress.ip_network(v, strict=False)
        except ValueError:
            raise ValueError('网段格式无效，请输入合法 CIDR（IPv4 如 10.1.1.0/24，IPv6 如 2001:db8::/64）')
        return v

    @field_validator('gateway')
    @classmethod
    def validate_gateway(cls, v: str) -> str:
        if v:
            try:
                _ipaddress.ip_address(v)
            except ValueError:
                raise ValueError('网关地址无效，请输入合法的 IP 地址（如 10.1.1.1 或 2001:db8::1）')
        return v


class PrefixUpdate(BaseModel):
    prefix: Optional[str] = None
    vrf_id: Optional[str] = None
    vlan_id: Optional[str] = None
    site_id: Optional[str] = None
    tenant_id: Optional[str] = None
    status: Optional[str] = None
    name: Optional[str] = None
    gateway: Optional[str] = None
    description: Optional[str] = None
    network_type: Optional[str] = None
    gateway_device_id: Optional[str] = None
    gateway_interface_id: Optional[str] = None
    traceable: Optional[int] = None


class IPPoolCreate(BaseModel):
    name: str
    prefix_id: str
    start_ip: str
    end_ip: str
    description: str = ''
    status: str = 'active'
    tenant_id: str = 'tenant-default'

    @field_validator('start_ip', 'end_ip')
    @classmethod
    def validate_ips(cls, v: str) -> str:
        _ipaddress.ip_address(v)
        return v


class IPPoolUpdate(BaseModel):
    name: Optional[str] = None
    prefix_id: Optional[str] = None
    start_ip: Optional[str] = None
    end_ip: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    tenant_id: Optional[str] = None


class VIPCreate(BaseModel):
    address: str
    vip_type: str
    device_id: Optional[str] = None
    backup_device_id: Optional[str] = None
    interface_name: str = ''
    description: str = ''
    real_servers: str = ''
    status: str = 'active'
    tenant_id: str = 'tenant-default'

    @field_validator('address')
    @classmethod
    def validate_address(cls, v: str) -> str:
        _ipaddress.ip_address(v)
        return v


class VIPUpdate(BaseModel):
    address: Optional[str] = None
    vip_type: Optional[str] = None
    device_id: Optional[str] = None
    backup_device_id: Optional[str] = None
    interface_name: Optional[str] = None
    description: Optional[str] = None
    real_servers: Optional[str] = None
    status: Optional[str] = None
    tenant_id: Optional[str] = None


class DHCPLeaseCreate(BaseModel):
    address: str
    mac_address: str
    hostname: str = ''
    dhcp_server: str = ''
    lease_state: str = 'active'
    lease_start: str = ''
    lease_end: str = ''

    @field_validator('address')
    @classmethod
    def validate_address(cls, v: str) -> str:
        _ipaddress.ip_address(v)
        return v

    @field_validator('mac_address')
    @classmethod
    def validate_mac(cls, v: str) -> str:
        return _normalize_mac(v) or ''


class DHCPLeaseUpdate(BaseModel):
    address: Optional[str] = None
    mac_address: Optional[str] = None
    hostname: Optional[str] = None
    dhcp_server: Optional[str] = None
    lease_state: Optional[str] = None
    lease_start: Optional[str] = None
    lease_end: Optional[str] = None

    @field_validator('mac_address')
    @classmethod
    def validate_mac(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_mac(v)
