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
