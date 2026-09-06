from __future__ import annotations

import re

from core.interface_utils import normalize_interface_name
from domain.models import Device, Interface, Neighbor
from services.normalizers.base import BaseNormalizer
from services.normalizers.common import (
    clean_ip,
    first_match,
    interface_type,
    neighbor_from_record,
    parse_speed_bps,
    record_value,
    regex_lldp_neighbors,
    status_value,
    textfsm_records,
)


class H3CNormalizer(BaseNormalizer):
    _PLATFORMS = ("h3c_comware", "h3c_comware_v3")

    def parse_device_info(self, device_id: str, raw_version: str) -> Device:
        records = textfsm_records(self._PLATFORMS, "display version", raw_version)
        record = records[0] if records else {}
        hostname = record_value(record, "hostname", "system_name") or first_match(raw_version, r"^<([^>]+)>")
        version = record_value(record, "version", "software_version", "comware_version") or first_match(
            raw_version, r"Comware\s+Software,\s*Version\s+([^\r\n]+)"
        )
        model = record_value(record, "hardware", "model", "platform") or first_match(
            raw_version,
            r"^(?:H3C|HP)\s+(\S+)\s+uptime\s+is\b",
            r"Product\s+(?:type|name)\s*:\s*(\S+)",
        )
        serial = record_value(record, "serial", "serial_number") or first_match(
            raw_version, r"(?:Device|System|Equipment)\s+(?:serial number|SN)\s*:\s*(\S+)"
        )
        uptime = record_value(record, "uptime") or first_match(
            raw_version, r"^(?:H3C|HP)\s+\S+\s+uptime\s+is\s+([^\r\n]+)"
        )
        return Device(
            id=device_id,
            hostname=hostname or device_id,
            ip_address="",
            vendor="H3C",
            platform="h3c_comware",
            sn=serial,
            model=model,
            version=version.strip(",. "),
            uptime=uptime,
        )

    def parse_interfaces(self, device_id: str, raw_interfaces: str, raw_ip_brief: str = "") -> list[Interface]:
        interfaces: dict[str, Interface] = {}

        for line in raw_ip_brief.splitlines():
            parts = re.split(r"\s+", line.strip())
            if len(parts) < 4 or parts[0].lower() in {"interface", "link:", "protocol:"}:
                continue
            if parts[1].lower() not in {"up", "down", "adm", "administratively"}:
                continue
            name = parts[0]
            admin, oper = parts[1], parts[2]
            ip_value = parts[3]
            key = self._normalize_interface(name)
            interfaces[key] = Interface(
                device_id=device_id,
                name_raw=name,
                name_display=key,
                interface_type=interface_type(name),
                description=" ".join(parts[4:]),
                admin_status=status_value(admin),
                oper_status=status_value(oper),
                primary_ip=clean_ip(ip_value),
                is_l3=clean_ip(ip_value) is not None or interface_type(name) in {"svi", "loopback"},
            )

        records = textfsm_records(self._PLATFORMS, "display interface", raw_interfaces)
        for record in records:
            name = record_value(record, "interface", "port", "name")
            if not name:
                continue
            self._merge_interface(
                interfaces,
                device_id,
                name,
                record_value(record, "admin_status", "link_status", "status"),
                record_value(record, "oper_status", "protocol_status", "line_protocol"),
                record_value(record, "description"),
                record_value(record, "mtu"),
                record_value(record, "mac_address", "hardware_address"),
                record_value(record, "speed", "bandwidth"),
            )

        header = re.compile(r"(?m)^(\S+)\s+current\s+state\s*:\s*(\S+)\s*$")
        matches = list(header.finditer(raw_interfaces))
        for index, match in enumerate(matches):
            name, admin = match.group(1), match.group(2)
            end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_interfaces)
            block = raw_interfaces[match.end():end]
            oper = first_match(block, r"Line\s+protocol\s+current\s+state\s*:\s*(\S+)")
            description = first_match(block, r"^Description\s*:\s*([^\r\n]*)")
            mtu = first_match(
                block,
                r"Maximum\s+(?:Frame|Transmit)\s+(?:Length|Unit)\s+(?:is\s+)?(\d+)",
                r"\bMTU\s*[: ]\s*(\d+)",
            )
            mac = first_match(block, r"(?:Hardware\s+Address|address)\s+(?:is\s+)?([0-9a-f.:-]+)")
            speed = first_match(block, r"(?:Speed|Bandwidth)\s*[: ]\s*([^,\r\n]+)")
            self._merge_interface(interfaces, device_id, name, admin, oper, description, mtu, mac, speed)

        return list(interfaces.values())

    def parse_neighbors(self, device_id: str, raw_lldp: str) -> list[Neighbor]:
        records = textfsm_records(self._PLATFORMS, "display lldp neighbor-information verbose", raw_lldp)
        parsed = [neighbor for record in records if (neighbor := neighbor_from_record(device_id, record))]
        if parsed:
            return self._normalize_neighbors(parsed)

        parsed = regex_lldp_neighbors(device_id, raw_lldp)
        if parsed:
            return self._normalize_neighbors(parsed)

        neighbors: list[Neighbor] = []
        in_table = False
        for line in raw_lldp.splitlines():
            if re.search(r"System\s+Name\s+Local\s+Interface\s+Chassis\s+ID\s+Port\s+ID", line, re.IGNORECASE):
                in_table = True
                continue
            if not in_table or not line.strip():
                continue
            parts = re.split(r"\s+", line.strip())
            if len(parts) < 4:
                continue
            remote_device, local, _, remote_port = parts[0], parts[1], parts[2], parts[3]
            neighbors.append(
                Neighbor(
                    device_id=device_id,
                    local_interface=self._normalize_interface(local),
                    remote_device=remote_device,
                    remote_interface=self._normalize_interface(remote_port),
                )
            )
        return neighbors

    @classmethod
    def _normalize_neighbors(cls, neighbors: list[Neighbor]) -> list[Neighbor]:
        for neighbor in neighbors:
            neighbor.local_interface = cls._normalize_interface(neighbor.local_interface)
            neighbor.remote_interface = cls._normalize_interface(neighbor.remote_interface)
        return neighbors

    @staticmethod
    def _merge_interface(
        interfaces: dict[str, Interface],
        device_id: str,
        name: str,
        admin: str,
        oper: str,
        description: str,
        mtu_value: str,
        mac: str,
        speed_value: str,
    ) -> None:
        key = H3CNormalizer._normalize_interface(name)
        interface = interfaces.get(key)
        if interface is None:
            interface = Interface(
                device_id=device_id,
                name_raw=name,
                name_display=key,
                interface_type=interface_type(name),
                admin_status=status_value(admin),
                oper_status=status_value(oper),
            )
            interfaces[key] = interface
        elif admin:
            interface.admin_status = status_value(admin)
        if oper:
            interface.oper_status = status_value(oper)
        if description:
            interface.description = description
        if mtu_value and re.search(r"\d+", mtu_value):
            interface.mtu = int(re.search(r"\d+", mtu_value).group())
        if mac:
            interface.mac = mac
        speed = parse_speed_bps(speed_value)
        if speed:
            interface.speed = speed
        interface.is_l3 = interface.is_l3 or interface.primary_ip is not None or interface.interface_type in {
            "svi", "loopback"
        }

    @staticmethod
    def _normalize_interface(name: str) -> str:
        value = str(name or "").strip()
        replacements = (
            (r"^XGE(?=\d)", "XGigabitEthernet"),
            (r"^HGE(?=\d)", "HundredGE"),
            (r"^GE(?=\d)", "GigabitEthernet"),
            (r"^Loop(?=\d)", "Loopback"),
        )
        for pattern, replacement in replacements:
            if re.search(pattern, value, re.IGNORECASE):
                value = re.sub(pattern, replacement, value, count=1, flags=re.IGNORECASE)
                break
        return normalize_interface_name(value)
