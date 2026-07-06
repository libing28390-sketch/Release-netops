import re
from typing import List, Dict, Any, Optional
from domain.models import Device, Interface, Neighbor
from services.normalizers.base import BaseNormalizer
from core.textfsm import parse_with_textfsm
from services.topology_service import normalize_interface_name

class CiscoNormalizer(BaseNormalizer):
    def parse_device_info(self, device_id: str, raw_version: str) -> Device:
        """Parse Cisco show version output into a Device domain object."""
        # Try TextFSM first
        records = parse_with_textfsm(platform="cisco_ios", command="show version", output=raw_version)
        
        hostname = ""
        version = ""
        model = ""
        serial_number = ""
        uptime = ""
        
        if records:
            r = {k.lower(): v for k, v in records[0].items()}
            hostname = r.get("hostname", "")
            version = r.get("version", "")
            hardware_val = r.get("hardware", "")
            model = hardware_val[0] if isinstance(hardware_val, list) and hardware_val else hardware_val
            serial_val = r.get("serial", "")
            serial_number = serial_val[0] if isinstance(serial_val, list) and serial_val else serial_val
            uptime = r.get("uptime", "")
            
        # Fallback to Regex
        if not hostname:
            m = re.search(r'(?i)(?:hostname|system name)\s+is\s+(\S+)', raw_version)
            if m: hostname = m.group(1)
        if not version:
            m = re.search(r'(?i)version\s+(\d+\.\S+)', raw_version) or re.search(r'(?i)software\s*\(.*?\)\s*,\s*version\s*(\S+)', raw_version)
            if m: version = m.group(1)
        if not model:
            m = re.search(r'(?i)cisco\s+(\S+)\s+processor', raw_version) or re.search(r'(?i)model\s*(?:number)?\s*:\s*(\S+)', raw_version)
            if m: model = m.group(1)
        if not serial_number:
            m = re.search(r'(?i)(?:system serial number|serial number|system sn|sn)\s*(?:is|:)?\s*(\S+)', raw_version)
            if m: serial_number = m.group(1)
        if not uptime:
            m = re.search(r'(?i)uptime\s+is\s+(.*)', raw_version)
            if m: uptime = m.group(1).strip()
            
        if version:
            version = version.strip(",. ")
            
        return Device(
            id=device_id,
            hostname=hostname or device_id,
            ip_address="",  # Set by DiscoveryService
            vendor="Cisco",
            platform="cisco_ios",
            status="active",
            compliance="compliant",
            sn=serial_number,
            model=model,
            version=version,
            uptime=uptime
        )

    def parse_interfaces(self, device_id: str, raw_interfaces: str, raw_ip_brief: str = "") -> List[Interface]:
        """Parse Cisco show interfaces and show ip interface brief."""
        interfaces_map = {}
        
        # 1. Parse show ip interface brief if present to set IP addresses and admin/oper status
        if raw_ip_brief:
            # Typical row: GigabitEthernet1/0/1    10.0.0.1        YES NVRAM  up                    up
            for line in raw_ip_brief.splitlines():
                line = line.strip()
                if not line or line.lower().startswith("interface") or "ip-address" in line.lower():
                    continue
                parts = re.split(r'\s+', line)
                if len(parts) >= 6:
                    name_raw = parts[0]
                    ip_addr = parts[1]
                    admin = parts[4]
                    oper = parts[5]
                    
                    if ip_addr.lower() == "unassigned" or ip_addr.lower() == "unset":
                        ip_addr = None
                        
                    admin_status = "up" if admin.lower() == "up" else "down"
                    oper_status = "up" if oper.lower() == "up" else "down"
                    
                    name_display = normalize_interface_name(name_raw)
                    interfaces_map[name_raw] = Interface(
                        device_id=device_id,
                        name_raw=name_raw,
                        name_display=name_display,
                        interface_type=self._determine_type(name_raw),
                        admin_status=admin_status,
                        oper_status=oper_status,
                        primary_ip=ip_addr
                    )
                    
        # 2. Try TextFSM show interfaces
        records = parse_with_textfsm(platform="cisco_ios", command="show interfaces", output=raw_interfaces)
        if records:
            for r_raw in records:
                r = {k.lower(): v for k, v in r_raw.items()}
                name_raw = r.get("interface", "")
                if not name_raw:
                    continue
                
                admin = r.get("link_status", "down")
                oper = r.get("protocol_status", "down")
                admin_status = "up" if "up" in admin.lower() else "down"
                oper_status = "up" if "up" in oper.lower() else "down"
                
                desc = r.get("description", "")
                mtu_val = r.get("mtu", "1500")
                try:
                    mtu = int(re.search(r'\d+', str(mtu_val)).group())
                except Exception:
                    mtu = 1500
                    
                mac = r.get("mac_address", None)
                speed_str = r.get("speed", "")
                bw_str = r.get("bandwidth", "")
                
                speed = None
                if speed_str:
                    try:
                        # e.g., "1000Mbps" or "1000000"
                        val = int(re.search(r'\d+', speed_str).group())
                        if "Gb" in speed_str:
                            speed = val * 1000 * 1000 * 1000
                        elif "Mb" in speed_str or "m" in speed_str.lower():
                            speed = val * 1000 * 1000
                        else:
                            speed = val
                    except Exception:
                        pass
                
                bandwidth = None
                if bw_str:
                    try:
                        # e.g., "1000000 Kbit"
                        val = int(re.search(r'\d+', bw_str).group())
                        if "Kbit" in bw_str or "kb" in bw_str.lower():
                            bandwidth = val * 1000
                        elif "Mbit" in bw_str:
                            bandwidth = val * 1000 * 1000
                        else:
                            bandwidth = val
                    except Exception:
                        pass
                
                # Check if SVI/routed
                ip_addr = r.get("ip_address", None)
                is_l3 = bool(ip_addr or name_raw.lower().startswith("vlan") or name_raw.lower().startswith("loopback"))
                
                name_display = normalize_interface_name(name_raw)
                
                if name_raw in interfaces_map:
                    # Update existing brief record
                    intf = interfaces_map[name_raw]
                    intf.description = desc
                    intf.mtu = mtu
                    intf.mac = mac
                    if speed: intf.speed = speed
                    if bandwidth: intf.bandwidth = bandwidth
                    intf.is_l3 = is_l3 or intf.primary_ip is not None
                else:
                    interfaces_map[name_raw] = Interface(
                        device_id=device_id,
                        name_raw=name_raw,
                        name_display=name_display,
                        interface_type=self._determine_type(name_raw),
                        description=desc,
                        speed=speed,
                        bandwidth=bandwidth,
                        mtu=mtu,
                        mac=mac,
                        admin_status=admin_status,
                        oper_status=oper_status,
                        is_l3=is_l3,
                        primary_ip=ip_addr
                    )
        else:
            # Fallback Interface Regex Splitting
            # Splits by interface start: e.g. "GigabitEthernet1/0/1 is up, line protocol is up"
            blocks = re.split(r'(?m)^([A-Za-z0-9\/\.\-]+)\s+is\s+', raw_interfaces)
            if len(blocks) > 2:
                # blocks[0] is header
                # blocks[1] is name, blocks[2] is info, etc.
                for i in range(1, len(blocks), 2):
                    name_raw = blocks[i]
                    info = blocks[i+1] if i+1 < len(blocks) else ""
                    
                    status_m = re.match(r'([^\n,]+),\s+line protocol\s+is\s+(\S+)', info)
                    admin_status = "down"
                    oper_status = "down"
                    if status_m:
                        admin = status_m.group(1)
                        oper = status_m.group(2)
                        admin_status = "up" if "up" in admin.lower() else "down"
                        oper_status = "up" if "up" in oper.lower() else "down"
                        
                    desc_m = re.search(r'Description:\s*(.*)', info)
                    desc = desc_m.group(1).strip() if desc_m else ""
                    
                    mtu_m = re.search(r'MTU\s+(\d+)\s+bytes', info)
                    mtu = int(mtu_m.group(1)) if mtu_m else 1500
                    
                    mac_m = re.search(r'address is\s+([0-9a-fA-F\.\-]+)', info)
                    mac = mac_m.group(1) if mac_m else None
                    
                    name_display = normalize_interface_name(name_raw)
                    if name_raw in interfaces_map:
                        intf = interfaces_map[name_raw]
                        intf.description = desc
                        intf.mtu = mtu
                        intf.mac = mac
                        intf.is_l3 = (intf.primary_ip is not None) or name_raw.lower().startswith("vlan") or name_raw.lower().startswith("loopback")
                    else:
                        interfaces_map[name_raw] = Interface(
                            device_id=device_id,
                            name_raw=name_raw,
                            name_display=name_display,
                            interface_type=self._determine_type(name_raw),
                            description=desc,
                            mtu=mtu,
                            mac=mac,
                            admin_status=admin_status,
                            oper_status=oper_status
                        )
                        
        return list(interfaces_map.values())

    def parse_neighbors(self, device_id: str, raw_lldp: str) -> List[Neighbor]:
        """Parse Cisco show lldp neighbors detail."""
        records = parse_with_textfsm(platform="cisco_ios", command="show lldp neighbors detail", output=raw_lldp)
        neighbors = []
        
        if records:
            for r_raw in records:
                r = {k.lower(): v for k, v in r_raw.items()}
                local_port = r.get("local_interface", "")
                remote_port = r.get("neighbor_interface", "") or r.get("neighbor_port_id", "") or r.get("remote_port_id", "")
                remote_dev = r.get("neighbor_name", "") or r.get("neighbor_device", "") or r.get("system_name", "")
                
                if local_port and remote_port and remote_dev:
                    neighbors.append(Neighbor(
                        device_id=device_id,
                        local_interface=normalize_interface_name(local_port),
                        remote_device=remote_dev,
                        remote_interface=normalize_interface_name(remote_port)
                    ))
        else:
            # Fallback detail block parser
            # Local Intf: Gi1/0/1
            # Port id: Gi2/0/2
            # System Name: SwitchB
            blocks = re.split(r'Local Intf:|Device ID:', raw_lldp)
            for block in blocks:
                if not block.strip():
                    continue
                local_m = re.search(r'Local Intf:\s*(\S+)', "Local Intf: " + block) or re.search(r'Local Interface:\s*(\S+)', block)
                remote_m = re.search(r'Port id:\s*(\S+)', block) or re.search(r'Port ID:\s*(\S+)', block)
                dev_m = re.search(r'System Name:\s*(\S+)', block) or re.search(r'Device ID:\s*(\S+)', block)
                
                if local_m and remote_m and dev_m:
                    neighbors.append(Neighbor(
                        device_id=device_id,
                        local_interface=normalize_interface_name(local_m.group(1)),
                        remote_device=dev_m.group(1),
                        remote_interface=normalize_interface_name(remote_m.group(1))
                    ))
        return neighbors

    def _determine_type(self, name: str) -> str:
        name = name.lower()
        if "loopback" in name: return "loopback"
        if "vlan" in name: return "svi"
        if "tunnel" in name: return "tunnel"
        if "port-channel" in name or "portchannel" in name: return "port_channel"
        if "ethernet" in name or "ge" in name or "fa" in name or "te" in name: return "physical"
        return "physical"
