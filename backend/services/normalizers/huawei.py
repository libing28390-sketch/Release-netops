import re
from typing import List, Dict, Any, Optional
from domain.models import Device, Interface, Neighbor
from services.normalizers.base import BaseNormalizer
from core.textfsm import parse_with_textfsm
from services.topology_service import normalize_interface_name

class HuaweiNormalizer(BaseNormalizer):
    def parse_device_info(self, device_id: str, raw_version: str) -> Device:
        """Parse Huawei display version output into a Device domain object."""
        # Try TextFSM first
        records = parse_with_textfsm(platform="huawei_vrp", command="display version", output=raw_version)
        
        hostname = ""
        version = ""
        model = ""
        serial_number = ""
        uptime = ""
        
        if records:
            r = {k.lower(): v for k, v in records[0].items()}
            # Some Huawei VRP show version records map values
            version = r.get("vrp_version", "") or r.get("version", "")
            model_val = r.get("model", "")
            model = model_val[0] if isinstance(model_val, list) and model_val else model_val
            serial_val = r.get("serial_number", "")
            serial_number = serial_val[0] if isinstance(serial_val, list) and serial_val else serial_val
            uptime = r.get("uptime", "")
            
        # Fallback to Regex
        if not version:
            m = re.search(r'(?i)VRP\s*\(R\)\s*software\s*,\s*Version\s*([^\s(),]+)', raw_version)
            if m: version = m.group(1)
        if not model:
            # Enforce case-sensitive match for capitalized HUAWEI line (model)
            m = re.search(r'HUAWEI\s+(\S+)', raw_version) or re.search(r'Quidway\s+(\S+)', raw_version)
            if m: model = m.group(1)
        if not serial_number:
            m = re.search(r'(?i)Equipment\s+serial\s+number\s*:\s*(\S+)', raw_version)
            if m: serial_number = m.group(1)
        if not uptime:
            m = re.search(r'(?i)uptime\s+is\s+(.*)', raw_version)
            if m: uptime = m.group(1).strip()
            
        if version:
            version = version.strip(",.() ")
            
        return Device(
            id=device_id,
            hostname=hostname or device_id,
            ip_address="",  # Set by DiscoveryService
            vendor="Huawei",
            platform="huawei_vrp",
            status="active",
            compliance="compliant",
            sn=serial_number,
            model=model,
            version=version,
            uptime=uptime
        )

    def parse_interfaces(self, device_id: str, raw_interfaces: str, raw_ip_brief: str = "") -> List[Interface]:
        """Parse Huawei display interface and display ip interface brief."""
        interfaces_map = {}
        
        # 1. Parse display ip interface brief if present
        if raw_ip_brief:
            # Typical row: GigabitEthernet0/0/1       unassigned         down       down
            # MEth0/0/0                  192.168.1.1/24     up         up
            for line in raw_ip_brief.splitlines():
                line = line.strip()
                if not line or line.lower().startswith("interface") or "ip-address" in line.lower():
                    continue
                parts = re.split(r'\s+', line)
                if len(parts) >= 4:
                    name_raw = parts[0]
                    ip_addr = parts[1]
                    admin = parts[2]
                    oper = parts[3]
                    
                    if ip_addr.lower() == "unassigned" or ip_addr.lower() == "unset" or ip_addr.lower() == "*":
                        ip_addr = None
                    else:
                        ip_addr = ip_addr.split('/')[0] # strip mask
                        
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

        # 2. Try TextFSM display interface
        records = parse_with_textfsm(platform="huawei_vrp", command="display interface", output=raw_interfaces)
        if records:
            for r_raw in records:
                r = {k.lower(): v for k, v in r_raw.items()}
                name_raw = r.get("interface", "")
                if not name_raw:
                    continue
                
                admin = r.get("admin_status", "down")
                oper = r.get("oper_status", "down")
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
                
                speed = None
                if speed_str:
                    try:
                        val = int(re.search(r'\d+', speed_str).group())
                        if "G" in speed_str:
                            speed = val * 1000 * 1000 * 1000
                        elif "M" in speed_str:
                            speed = val * 1000 * 1000
                        else:
                            speed = val
                    except Exception:
                        pass
                
                name_display = normalize_interface_name(name_raw)
                if name_raw in interfaces_map:
                    intf = interfaces_map[name_raw]
                    intf.description = desc
                    intf.mtu = mtu
                    intf.mac = mac
                    if speed: intf.speed = speed
                    intf.is_l3 = (intf.primary_ip is not None) or name_raw.lower().startswith("vlanif") or name_raw.lower().startswith("loopback")
                else:
                    interfaces_map[name_raw] = Interface(
                        device_id=device_id,
                        name_raw=name_raw,
                        name_display=name_display,
                        interface_type=self._determine_type(name_raw),
                        description=desc,
                        speed=speed,
                        mtu=mtu,
                        mac=mac,
                        admin_status=admin_status,
                        oper_status=oper_status,
                        is_l3=name_raw.lower().startswith("vlanif") or name_raw.lower().startswith("loopback")
                    )
        else:
            # Fallback regex parsing by splitting on: "GigabitEthernet0/0/1 current state :"
            blocks = re.split(r'(?m)^([A-Za-z0-9\/\.\-]+)\s+current\s+state\s*:\s*', raw_interfaces)
            if len(blocks) > 2:
                for i in range(1, len(blocks), 2):
                    name_raw = blocks[i]
                    info = blocks[i+1] if i+1 < len(blocks) else ""
                    
                    admin_m = re.match(r'(\S+)', info)
                    admin_status = "down"
                    if admin_m:
                        admin_status = "up" if "up" in admin_m.group(1).lower() else "down"
                        
                    oper_m = re.search(r'Line\s+protocol\s+current\s+state\s*:\s*(\S+)', info)
                    oper_status = "down"
                    if oper_m:
                        oper_status = "up" if "up" in oper_m.group(1).lower() else "down"
                        
                    desc_m = re.search(r'Description:\s*(.*)', info)
                    desc = desc_m.group(1).strip() if desc_m else ""
                    
                    mtu_m = re.search(r'The\s+Maximum\s+Transmit\s+Unit\s+is\s+(\d+)', info) or re.search(r'MTU\s*:\s*(\d+)', info)
                    mtu = int(mtu_m.group(1)) if mtu_m else 1500
                    
                    mac_m = re.search(r'Hardware\s+address\s+is\s+([0-9a-fA-F\-]+)', info) or re.search(r'Hardware\s+Address\s*:\s*([0-9a-fA-F\-]+)', info)
                    mac = mac_m.group(1) if mac_m else None
                    
                    name_display = normalize_interface_name(name_raw)
                    if name_raw in interfaces_map:
                        intf = interfaces_map[name_raw]
                        intf.description = desc
                        intf.mtu = mtu
                        intf.mac = mac
                        intf.is_l3 = (intf.primary_ip is not None) or name_raw.lower().startswith("vlanif") or name_raw.lower().startswith("loopback")
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
        """Parse Huawei display lldp neighbor verbose."""
        records = parse_with_textfsm(platform="huawei_vrp", command="display lldp neighbor verbose", output=raw_lldp)
        neighbors = []
        
        if records:
            for r_raw in records:
                r = {k.lower(): v for k, v in r_raw.items()}
                local_port = r.get("local_interface", "") or r.get("local_port", "")
                remote_port = r.get("neighbor_interface", "") or r.get("port_id", "")
                remote_dev = r.get("system_name", "") or r.get("neighbor_device", "")
                
                if local_port and remote_port and remote_dev:
                    neighbors.append(Neighbor(
                        device_id=device_id,
                        local_interface=normalize_interface_name(local_port),
                        remote_device=remote_dev,
                        remote_interface=normalize_interface_name(remote_port)
                    ))
        else:
            # Fallback block parser
            # LLDP neighbor-information of port 1[GigabitEthernet0/0/1]:
            # Port ID         : GigabitEthernet0/0/2
            # System name     : SwitchB
            blocks = re.split(r'LLDP neighbor-information of port|neighbor-information of port', raw_lldp)
            for block in blocks:
                if not block.strip():
                    continue
                local_m = re.search(r'port\s+\d+\[([^\]]+)\]', "port " + block) or re.search(r'port\s*(\S+)\s*:', block)
                remote_m = re.search(r'Port ID\s*:\s*(\S+)', block) or re.search(r'Port ID\s*type\s*:.*?Port ID\s*:\s*(\S+)', block, re.DOTALL)
                dev_m = re.search(r'System name\s*:\s*(\S+)', block) or re.search(r'System\s+Name\s*:\s*(\S+)', block)
                
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
        if "vlanif" in name: return "svi"
        if "tunnel" in name: return "tunnel"
        if "eth-trunk" in name: return "port_channel"
        if "ethernet" in name or "ge" in name or "fe" in name or "xge" in name or "gige" in name: return "physical"
        return "physical"
