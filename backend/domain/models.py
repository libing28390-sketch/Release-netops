from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime

@dataclass
class Device:
    id: str
    hostname: str
    ip_address: str
    vendor: str
    platform: str
    status: str = "active"
    compliance: str = "compliant"
    sn: Optional[str] = None
    model: Optional[str] = None
    version: Optional[str] = None
    role: Optional[str] = None
    site: Optional[str] = None
    uptime: Optional[str] = None

@dataclass
class Interface:
    device_id: str
    name_raw: str
    name_display: str
    interface_type: str                   # physical, svi, loopback, tunnel, port_channel, sub_interface, vxlan, bridge
    description: str = ""
    speed: Optional[int] = None
    bandwidth: Optional[int] = None
    mtu: int = 1500
    mac: Optional[str] = None
    admin_status: str = "down"           # up, down
    oper_status: str = "down"            # up, down
    last_change: Optional[datetime] = None
    is_l3: bool = False
    vrf_id: Optional[str] = None
    primary_ip: Optional[str] = None
    parent_interface_id: Optional[str] = None
    lag_id: Optional[str] = None
    vlan_mode: str = "access"            # access, trunk, routed
    access_vlan: Optional[int] = None
    native_vlan: Optional[int] = None
    allowed_vlans: Optional[List[int]] = field(default_factory=list)

@dataclass
class PowerSupply:
    device_id: str
    name: str                            # e.g., PS1, Power Supply A
    status: str = "ok"                   # ok, fail, empty
    wattage: Optional[int] = None

@dataclass
class Fan:
    device_id: str
    name: str                            # e.g., Fan Tray 1, Fan A
    status: str = "ok"                   # ok, fail, empty
    speed_rpm: Optional[int] = None

@dataclass
class Slot:
    device_id: str
    slot_number: int
    name: str
    status: str = "empty"                # empty, occupied, failed

@dataclass
class Module:
    device_id: str
    slot_number: int
    name: str
    model: str
    serial_number: Optional[str] = None
    status: str = "ok"

@dataclass
class SFP:
    device_id: str
    interface_name: str
    vendor: str
    part_number: str
    serial_number: str
    sfp_type: str                        # 10G-SR, 1G-LX, etc.
    rx_optical_dbm: Optional[float] = None
    tx_optical_dbm: Optional[float] = None

@dataclass
class Neighbor:
    device_id: str
    local_interface: str
    remote_device: str
    remote_interface: str
    platform: Optional[str] = None
    capabilities: Optional[str] = None

@dataclass
class Link:
    link_id: str
    local_interface_id: str
    remote_interface_id: str
    discover_protocol: str               # lldp, cdp, mac_table
    confidence: float = 1.0
    last_seen: Optional[datetime] = None
    status: str = "active"

@dataclass
class VRF:
    id: str
    name: str
    rd: Optional[str] = None
    rt_import: Optional[str] = None
    rt_export: Optional[str] = None
    description: str = ""

@dataclass
class VLAN:
    vlan_id: int
    name: str
    status: str = "active"
    description: str = ""

@dataclass
class Prefix:
    network: str
    prefix_len: int
    vrf_id: Optional[str] = None
    vlan_id: Optional[int] = None
    status: str = "active"               # active, reserved, deprecated
    description: str = ""

@dataclass
class IPAddress:
    address: str
    prefix_len: int
    vrf_id: Optional[str] = None
    device_id: Optional[str] = None
    interface_name: Optional[str] = None
    mac_address: Optional[str] = None
    status: str = "active"               # active, reserved, deprecated
    description: str = ""
