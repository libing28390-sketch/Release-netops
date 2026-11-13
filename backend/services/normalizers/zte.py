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
    record_value,
    regex_lldp_neighbors,
    status_value,
    textfsm_records,
)


class ZTENormalizer(BaseNormalizer):
    _PLATFORMS = ("zte_zxros", "zte", "zxros")

    def parse_device_info(self, device_id: str, raw_version: str) -> Device:
        records = textfsm_records(self._PLATFORMS, "show version", raw_version)
        record = records[0] if records else {}
        hostname = record_value(record, "hostname") or first_match(raw_version, r"^([\w.-]+)#\s*show version")
        model = record_value(record, "model") or first_match(
            raw_version,
            r"ZXR10\s+(\S+)",
            r"Board Name\s*:\s*([^\r\n]+)",
        )
        version = record_value(record, "version") or first_match(
            raw_version, r"Version:\s*([^\r\n,]+)"
        )
        serial = record_value(record, "serial") or first_match(
            raw_version, r"Serial\s+(?:Number|number)\s*:\s*(\S+)"
        )
        uptime = record_value(record, "uptime") or first_match(
            raw_version, r"System uptime is\s+([^\r\n]+)"
        )
        return Device(
            id=device_id,
            hostname=hostname or device_id,
            ip_address="",
            vendor="ZTE",
            platform="zte_zxros",
            sn=serial,
            model=model,
            version=version,
            uptime=uptime,
        )

    def parse_interfaces(self, device_id: str, raw_interfaces: str, raw_ip_brief: str = "") -> list[Interface]:
        interfaces: dict[str, Interface] = {}

        # 1. Parse 'show ip interface brief'
        for line in raw_ip_brief.splitlines():
            columns = [col.strip() for col in re.split(r"\s{2,}", line.strip()) if col.strip()]
            if len(columns) < 4 or columns[0].lower() in {"interface", "--------------------------------------------------------------------------------"}:
                continue
            if columns[-1].lower() not in {"up", "down"} or columns[-2].lower() not in {"up", "down"}:
                continue
            name = columns[0]
            ip_val = clean_ip(columns[1])
            key = normalize_interface_name(name)
            interfaces[key] = Interface(
                device_id=device_id,
                name_raw=name,
                name_display=key,
                interface_type=interface_type(name),
                admin_status=status_value(columns[-3] if len(columns) >= 6 else columns[-2]),
                oper_status=status_value(columns[-1]),
                primary_ip=ip_val,
                is_l3=ip_val is not None or interface_type(name) in {"svi", "loopback"},
            )

        # 2. Parse 'show interface brief'
        for line in raw_interfaces.splitlines():
            columns = [col.strip() for col in re.split(r"\s{2,}", line.strip()) if col.strip()]
            if len(columns) < 5 or columns[0].lower() == "interface":
                continue
            name = columns[0]
            key = normalize_interface_name(name)
            admin_st = status_value(columns[4]) if len(columns) >= 7 else "down"
            oper_st = status_value(columns[6]) if len(columns) >= 7 else (status_value(columns[5]) if len(columns) >= 6 else "down")
            desc = columns[7] if len(columns) >= 8 else ""

            if key in interfaces:
                intf = interfaces[key]
                intf.admin_status = admin_st
                intf.oper_status = oper_st
                if desc:
                    intf.description = desc
            else:
                interfaces[key] = Interface(
                    device_id=device_id,
                    name_raw=name,
                    name_display=key,
                    interface_type=interface_type(name),
                    admin_status=admin_st,
                    oper_status=oper_st,
                    description=desc,
                    is_l3=interface_type(name) in {"svi", "loopback"},
                )

        return list(interfaces.values())

    def parse_neighbors(self, device_id: str, raw_lldp: str) -> list[Neighbor]:
        records = textfsm_records(self._PLATFORMS, "show lldp neighbor", raw_lldp)
        parsed = [neighbor for record in records if (neighbor := neighbor_from_record(device_id, record))]
        return parsed or regex_lldp_neighbors(device_id, raw_lldp)
