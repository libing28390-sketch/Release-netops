"""Model-scoped, typed SNMP metric profile management.

An OID is only the address of a value.  A usable monitoring definition also
needs the value semantics, table aggregation, scale/formula, and (for
counters) an explicit width.  This service owns that contract and exposes the
same effective mapping to every collector entry point.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from services.snmp_counter_service import validate_counter_bits
from services.snmp_service import (
    DEFAULT_INTERFACE_CONFIG,
    SYS_UPTIME,
    normalize_interface_config,
    normalize_metric_oid,
)


_PROFILE_CACHE_TTL = 60.0
_profile_cache: dict[tuple[str, str], dict[str, Any]] | None = None
_profile_cache_expires_at = 0.0
_profile_cache_lock = threading.Lock()

SUPPORTED_METRIC_MODES = (
    "direct_percent",
    "direct_value",
    "used_total_percent",
    "used_free_percent",
    "counter_rate_percent",
    "status_code",
)
SUPPORTED_AGGREGATIONS = ("first", "average", "max", "min", "sum")
SUPPORTED_COUNTER_UNITS = ("bits", "octets")
SUPPORTED_METRIC_KEYS = (
    "cpu",
    "memory",
    "temperature",
    "fan",
    "power_supply",
    "power",
    "storage",
    "voltage",
)
# Device health intentionally has a smaller contract than topology, WAN, or
# inspection collection.  Keeping this allow-list here makes the template
# resolver the single source of truth for both the effective OIDs and the
# lightweight collector's scope.
HEALTH_METRIC_KEYS = (
    "cpu",
    "memory",
    "temperature",
    "fan",
    "power_supply",
)

# Alert rules deliberately do not store a second copy of an OID.  These
# bindings describe which collector and which model-template section owns the
# observation, so the alert engine and the SNMP template editor stay aligned.
# The interface defaults below are read from the same IF-MIB configuration
# consumed by ``collect_interface_health``/``collect_interface_data``.
_INTERFACE_DEFAULT_OIDS = {
    key: value
    for key, value in DEFAULT_INTERFACE_CONFIG.items()
    if key.endswith("_oid")
}

ALERT_METRIC_COLLECTION_BINDINGS: dict[str, dict[str, Any]] = {
    "cpu": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 硬件模板",
        "collection_label_en": "SNMP hardware template",
        "template_linked": True,
        "template_section": "硬件指标 / CPU",
        "template_metric": "cpu",
        "oid_paths": [
            "metric_definitions.cpu.oid",
            "metric_definitions.cpu.used_oid",
            "metric_definitions.cpu.total_oid",
            "metric_definitions.cpu.free_oid",
            "metric_definitions.cpu.capacity_oid",
        ],
        "default_oids": {},
        "description": "优先使用已验证的型号模板 CPU 定义；没有模板定义时才使用厂商内置采集器。",
        "description_en": "Use the verified model-template CPU definition first, then the built-in vendor collector.",
    },
    "memory": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 硬件模板",
        "collection_label_en": "SNMP hardware template",
        "template_linked": True,
        "template_section": "硬件指标 / 内存",
        "template_metric": "memory",
        "oid_paths": [
            "metric_definitions.memory.oid",
            "metric_definitions.memory.used_oid",
            "metric_definitions.memory.total_oid",
            "metric_definitions.memory.free_oid",
            "metric_definitions.memory.capacity_oid",
        ],
        "default_oids": {},
        "description": "优先使用已验证的型号模板内存定义；比例计算方式由模板 mode 决定。",
        "description_en": "Use the verified model-template memory definition; the template mode controls the percentage formula.",
    },
    "temperature_high": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 硬件模板",
        "collection_label_en": "SNMP hardware template",
        "template_linked": True,
        "template_section": "硬件指标 / 设备温度",
        "template_metric": "temperature",
        "oid_paths": ["metric_definitions.temperature.oid"],
        "default_oids": {},
        "description": "温度告警复用设备型号模板的 temperature OID 和单位，不在告警规则中另存 OID。",
        "description_en": "Temperature alerts reuse the model template OID and unit; the alert rule stores no duplicate OID.",
    },
    "fan_failure": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 硬件模板",
        "collection_label_en": "SNMP hardware template",
        "template_linked": True,
        "template_section": "硬件指标 / 风扇状态",
        "template_metric": "fan",
        "oid_paths": ["metric_definitions.fan.oid"],
        "default_oids": {},
        "description": "风扇状态使用模板 status_code 语义；未支持/未知不会直接判定为故障。",
        "description_en": "Fan state uses the template status_code semantics; unsupported or unknown is not treated as failure.",
    },
    "power_supply_failure": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 硬件模板",
        "collection_label_en": "SNMP hardware template",
        "template_linked": True,
        "template_section": "硬件指标 / 电源状态",
        "template_metric": "power_supply",
        "oid_paths": ["metric_definitions.power_supply.oid"],
        "default_oids": {},
        "description": "电源状态使用模板 status_code 语义；告警规则不再维护独立 PSU OID。",
        "description_en": "Power state uses the template status_code semantics; the rule does not maintain a separate PSU OID.",
    },
    "interface_util": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 接口模板",
        "collection_label_en": "SNMP interface template",
        "template_linked": True,
        "template_section": "接口指标 / 流量与带宽",
        "template_metric": "interface",
        "oid_paths": [
            "interface_config.if_hc_in_octets_oid",
            "interface_config.if_hc_out_octets_oid",
            "interface_config.if_in_octets_oid",
            "interface_config.if_out_octets_oid",
            "interface_config.if_high_speed_oid",
        ],
        "default_oids": {
            key: _INTERFACE_DEFAULT_OIDS[key]
            for key in (
                "if_hc_in_octets_oid",
                "if_hc_out_octets_oid",
                "if_in_octets_oid",
                "if_out_octets_oid",
                "if_high_speed_oid",
            )
        },
        "description": "接口利用率使用 Counter64 成对优先、Counter32 成对回退，并按 ifHighSpeed 计算带宽。",
        "description_en": "Interface utilization prefers paired Counter64 values, falls back to paired Counter32 values, and uses ifHighSpeed for bandwidth.",
    },
    "interface_down": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 接口模板",
        "collection_label_en": "SNMP interface template",
        "template_linked": True,
        "template_section": "接口指标 / 运行状态",
        "template_metric": "interface",
        "oid_paths": ["interface_config.if_oper_status_oid"],
        "default_oids": {"if_oper_status_oid": _INTERFACE_DEFAULT_OIDS["if_oper_status_oid"]},
        "description": "接口 DOWN 告警读取 ifOperStatus，并只在 UP→DOWN 状态变化时触发。",
        "description_en": "Interface-down alerts read ifOperStatus and trigger only on an UP-to-DOWN transition.",
    },
    "interconnect_down": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 接口模板",
        "collection_label_en": "SNMP interface template",
        "template_linked": True,
        "template_section": "接口指标 / 互联口运行状态",
        "template_metric": "interface",
        "oid_paths": ["interface_config.if_oper_status_oid"],
        "default_oids": {"if_oper_status_oid": _INTERFACE_DEFAULT_OIDS["if_oper_status_oid"]},
        "description": "互联口 DOWN 与普通接口共用 ifOperStatus，区别只来自拓扑端口识别。",
        "description_en": "Interconnect-down uses the same ifOperStatus as ordinary interfaces; topology identifies the interconnect port.",
    },
    "interface_flap": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 接口模板",
        "collection_label_en": "SNMP interface template",
        "template_linked": True,
        "template_section": "接口指标 / 状态变化",
        "template_metric": "interface",
        "oid_paths": [
            "interface_config.if_oper_status_oid",
            "interface_config.if_last_change_oid",
        ],
        "default_oids": {
            key: _INTERFACE_DEFAULT_OIDS[key]
            for key in ("if_oper_status_oid", "if_last_change_oid")
        },
        "description": "接口震荡基于连续采样的 ifOperStatus UP/DOWN 翻转判断，并使用 ifLastChange 辅助校验。",
        "description_en": "Interface flapping is based on sampled ifOperStatus transitions, with ifLastChange as supporting evidence.",
    },
    "interface_error_rate_high": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 接口模板",
        "collection_label_en": "SNMP interface template",
        "template_linked": True,
        "template_section": "接口指标 / 错误率",
        "template_metric": "interface",
        "oid_paths": [
            "interface_config.if_in_errors_oid",
            "interface_config.if_out_errors_oid",
            "interface_config.if_in_discards_oid",
            "interface_config.if_out_discards_oid",
            "interface_config.if_hc_in_ucast_pkts_oid",
            "interface_config.if_hc_in_multicast_pkts_oid",
            "interface_config.if_hc_in_broadcast_pkts_oid",
            "interface_config.if_hc_out_ucast_pkts_oid",
            "interface_config.if_hc_out_multicast_pkts_oid",
            "interface_config.if_hc_out_broadcast_pkts_oid",
            "interface_config.dot3_hc_fcs_errors_oid",
            "interface_config.dot3_hc_frame_too_long_oid",
            "interface_config.dot3_hc_internal_mac_rx_errors_oid",
            "interface_config.dot3_hc_symbol_errors_oid",
        ],
        "default_oids": {
            key: _INTERFACE_DEFAULT_OIDS[key]
            for key in (
                "if_in_errors_oid",
                "if_out_errors_oid",
                "if_in_discards_oid",
                "if_out_discards_oid",
                "if_hc_in_ucast_pkts_oid",
                "if_hc_in_multicast_pkts_oid",
                "if_hc_in_broadcast_pkts_oid",
                "if_hc_out_ucast_pkts_oid",
                "if_hc_out_multicast_pkts_oid",
                "if_hc_out_broadcast_pkts_oid",
                "dot3_hc_fcs_errors_oid",
                "dot3_hc_frame_too_long_oid",
                "dot3_hc_internal_mac_rx_errors_oid",
                "dot3_hc_symbol_errors_oid",
            )
        },
        "description": "错误率优先使用 IF-MIB Counter64 包计数增量；通用错误/丢弃与 EtherLike FCS/CRC 分开采集，避免把通用错误误显示成 CRC。",
        "description_en": "Error rate prefers IF-MIB Counter64 packet deltas; generic errors/discards and EtherLike FCS/CRC are collected separately.",
    },
    "snmp_unreachable": {
        "collection_source": "snmp_probe",
        "collection_label": "SNMP 连通性探测",
        "collection_label_en": "SNMP reachability probe",
        "template_linked": False,
        "template_section": "SNMP 连通性",
        "template_metric": "system",
        "oid_paths": ["system.sysUpTime.0"],
        "default_oids": {"sys_uptime_oid": SYS_UPTIME},
        "description": "这是 SNMP 探测告警，不属于硬件模板指标；使用标准 sysUpTime 作为可达性兜底探测。",
        "description_en": "This is an SNMP probe alert, not a hardware-template metric; sysUpTime is used as the reachability fallback.",
    },
    "lldp_neighbor_lost": {
        "collection_source": "ssh_cli",
        "collection_label": "SSH/CLI 邻居发现",
        "collection_label_en": "SSH/CLI neighbor discovery",
        "template_linked": False,
        "template_section": "LLDP 邻居发现",
        "template_metric": "lldp",
        "oid_paths": [],
        "default_oids": {},
        "description": "当前实现使用厂商 CLI 采集 LLDP 后比对拓扑链路，不从 SNMP 模板取 OID。",
        "description_en": "The current implementation compares topology links from vendor CLI LLDP collection; it does not read an SNMP-template OID.",
    },
    "bgp_neighbor_down": {
        "collection_source": "ssh_cli",
        "collection_label": "SSH/CLI 协议状态",
        "collection_label_en": "SSH/CLI protocol state",
        "template_linked": False,
        "template_section": "BGP 邻居状态",
        "template_metric": "bgp",
        "oid_paths": [],
        "default_oids": {},
        "description": "当前实现通过厂商 CLI 采集 BGP 邻居状态。",
        "description_en": "The current implementation collects BGP neighbor state through vendor CLI.",
    },
    "ospf_neighbor_down": {
        "collection_source": "ssh_cli",
        "collection_label": "SSH/CLI 协议状态",
        "collection_label_en": "SSH/CLI protocol state",
        "template_linked": False,
        "template_section": "OSPF 邻居状态",
        "template_metric": "ospf",
        "oid_paths": [],
        "default_oids": {},
        "description": "当前实现通过厂商 CLI 采集 OSPF 邻居状态。",
        "description_en": "The current implementation collects OSPF neighbor state through vendor CLI.",
    },
    "bfd_session_down": {
        "collection_source": "ssh_cli",
        "collection_label": "SSH/CLI 协议状态",
        "collection_label_en": "SSH/CLI protocol state",
        "template_linked": False,
        "template_section": "BFD 会话状态",
        "template_metric": "bfd",
        "oid_paths": [],
        "default_oids": {},
        "description": "当前实现通过厂商 CLI 采集 BFD 会话状态。",
        "description_en": "The current implementation collects BFD session state through vendor CLI.",
    },
    "ping_unreachable": {
        "collection_source": "icmp",
        "collection_label": "ICMP 探测",
        "collection_label_en": "ICMP probe",
        "template_linked": False,
        "template_section": "网络可达性",
        "template_metric": "icmp",
        "oid_paths": [],
        "default_oids": {},
        "description": "Ping 不可达使用 ICMP，不读取 SNMP OID。",
        "description_en": "Ping reachability uses ICMP and does not read an SNMP OID.",
    },
}

for _host_metric in ("host_cpu", "host_memory", "host_disk"):
    ALERT_METRIC_COLLECTION_BINDINGS[_host_metric] = {
        "collection_source": "host_agent",
        "collection_label": "宿主机采集",
        "collection_label_en": "Host agent",
        "template_linked": False,
        "template_section": "宿主机资源",
        "template_metric": _host_metric,
        "oid_paths": [],
        "default_oids": {},
        "description": "宿主机指标由主机采集器提供，不使用网络设备 SNMP 模板。",
        "description_en": "Host metrics come from the host collector, not the network-device SNMP template.",
    }

for _server_metric in (
    "srv_cpu_load", "srv_cpu_util", "srv_iowait", "srv_mem_avail", "srv_swap",
    "srv_disk_util", "srv_disk_inode", "srv_io_latency", "srv_tcp_retrans",
    "srv_tcp_conns", "srv_process_health",
):
    ALERT_METRIC_COLLECTION_BINDINGS[_server_metric] = {
        "collection_source": "server_agent",
        "collection_label": "服务器采集",
        "collection_label_en": "Server agent",
        "template_linked": False,
        "template_section": "服务器资源",
        "template_metric": _server_metric,
        "oid_paths": [],
        "default_oids": {},
        "description": "服务器指标由服务器采集器提供，不使用网络设备 SNMP 模板。",
        "description_en": "Server metrics come from the server collector, not the network-device SNMP template.",
    }


def get_alert_metric_collection(metric_type: Any) -> dict[str, Any]:
    """Return a copy of the collector/template binding for one alert metric."""
    key = _clean_text(metric_type, 64).casefold()
    binding = ALERT_METRIC_COLLECTION_BINDINGS.get(key)
    if binding is None:
        return {
            "collection_source": "unknown",
            "collection_label": "未定义采集源",
            "collection_label_en": "Undefined collector",
            "template_linked": False,
            "template_section": "",
            "template_metric": key,
            "oid_paths": [],
            "default_oids": {},
            "description": "该指标尚未定义采集源。",
            "description_en": "No collector has been defined for this metric.",
        }
    # The catalog is part of the API response; return a detached JSON-safe
    # copy so callers cannot mutate the shared source-of-truth mapping.
    return json.loads(json.dumps(binding, ensure_ascii=False))


def list_alert_metric_collections() -> dict[str, dict[str, Any]]:
    """Return every alert metric's collector/template binding."""
    return {
        metric_type: get_alert_metric_collection(metric_type)
        for metric_type in sorted(ALERT_METRIC_COLLECTION_BINDINGS)
    }
_METRIC_ALLOWED_MODES = {
    "cpu": frozenset(("direct_percent", "used_total_percent", "used_free_percent", "counter_rate_percent")),
    "memory": frozenset(("direct_percent", "used_total_percent", "used_free_percent", "counter_rate_percent")),
    "storage": frozenset(("direct_percent", "used_total_percent", "used_free_percent", "counter_rate_percent")),
    "temperature": frozenset(("direct_value",)),
    "voltage": frozenset(("direct_value",)),
    "power": frozenset(("direct_value",)),
    "fan": frozenset(("status_code",)),
    "power_supply": frozenset(("status_code",)),
}


_PLATFORM_VENDOR_NAMES = {
    "cisco": "Cisco",
    "huawei": "Huawei",
    "h3c": "H3C",
    "comware": "H3C",
    "arista": "Arista",
    "juniper": "Juniper",
    "junos": "Juniper",
    "fortinet": "Fortinet",
    "fortios": "Fortinet",
    "ruijie": "Ruijie",
    "zte": "ZTE",
    "raisecom": "Raisecom",
    "瑞斯康达": "Raisecom",
    "maipu": "Maipu",
}


def _clean_text(value: Any, max_length: int = 256) -> str:
    return " ".join(str(value or "").strip().split())[:max_length]


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def normalize_model_key(value: Any) -> str:
    """Normalize model text without erasing meaningful model punctuation."""
    return _clean_text(value, 256).casefold()


def vendor_name_from_platform(platform: Any) -> str:
    platform_text = _clean_text(platform, 128).casefold().replace("-", "_")
    for token, name in _PLATFORM_VENDOR_NAMES.items():
        if token in platform_text:
            return name
    return _clean_text(platform, 128)


def normalize_vendor_name(vendor: Any, platform: Any = "") -> str:
    display = _clean_text(vendor, 128) or vendor_name_from_platform(platform)
    aliases = {
        "raisecom": "Raisecom",
        "瑞斯康达": "Raisecom",
        "瑞斯康达通信": "Raisecom",
    }
    return aliases.get(display.casefold(), display) or "Unknown"


def normalize_vendor_key(vendor: Any, platform: Any = "") -> str:
    return normalize_vendor_name(vendor, platform).casefold()


def _safe_oid(value: Any) -> str:
    try:
        return normalize_metric_oid(value)
    except ValueError:
        return ""


def _number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _code_values(value: Any, field: str) -> list[int]:
    """Normalize status-code lists without accepting ambiguous text."""
    values = value if isinstance(value, (list, tuple, set)) else str(value or "").replace("，", ",").split(",")
    result: list[int] = []
    for raw in values:
        if str(raw).strip() == "":
            continue
        try:
            code = int(str(raw).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must contain integer status codes") from exc
        if code not in result:
            result.append(code)
    return result


def _decode_config(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def normalize_metric_config(value: Any = None, legacy_oid: Any = "") -> dict[str, Any]:
    """Normalize and validate one metric definition.

    Legacy ``cpu_oid``/``memory_oid`` values are intentionally interpreted as
    a *direct gauge percentage* only.  A live verification must still prove
    that the returned ASN.1 type is not Counter32/Counter64.
    """
    raw = _decode_config(value)
    if not raw and _clean_text(legacy_oid):
        raw = {"oid": legacy_oid, "mode": "direct_percent"}
    if not raw:
        return {}

    mode = _clean_text(raw.get("mode") or raw.get("calculation") or raw.get("value_type"), 64).casefold()
    mode_aliases = {
        "gauge_percent": "direct_percent",
        "percent": "direct_percent",
        "value": "direct_value",
        "ratio": "used_total_percent",
        "counter_rate": "counter_rate_percent",
        "status": "status_code",
    }
    mode = mode_aliases.get(mode, mode or "direct_percent")
    if mode not in SUPPORTED_METRIC_MODES:
        raise ValueError(f"mode must be one of: {', '.join(SUPPORTED_METRIC_MODES)}")

    aggregation = _clean_text(raw.get("aggregation") or "average", 32).casefold()
    if aggregation not in SUPPORTED_AGGREGATIONS:
        raise ValueError(f"aggregation must be one of: {', '.join(SUPPORTED_AGGREGATIONS)}")

    oid = _safe_oid(raw.get("oid") or raw.get("source_oid") or legacy_oid)
    used_oid = _safe_oid(raw.get("used_oid") or raw.get("oid"))
    total_oid = _safe_oid(raw.get("total_oid"))
    free_oid = _safe_oid(raw.get("free_oid"))
    capacity_oid = _safe_oid(raw.get("capacity_oid"))
    # Surface malformed input as a validation error instead of silently
    # converting it to an empty definition.
    for field, submitted in (
        ("oid", raw.get("oid") or raw.get("source_oid") or legacy_oid),
        ("used_oid", raw.get("used_oid")),
        ("total_oid", raw.get("total_oid")),
        ("free_oid", raw.get("free_oid")),
        ("capacity_oid", raw.get("capacity_oid")),
    ):
        if _clean_text(submitted) and not {
            "oid": oid,
            "used_oid": used_oid,
            "total_oid": total_oid,
            "free_oid": free_oid,
            "capacity_oid": capacity_oid,
        }[field]:
            raise ValueError(f"{field} must be a dotted decimal SNMP OID")

    scale = _number(raw.get("scale", 1), "scale")
    offset = _number(raw.get("offset", 0), "offset")
    selector = _clean_text(raw.get("selector") or "", 128).strip(".")
    if scale <= 0:
        raise ValueError("scale must be greater than zero")

    counter_bits: int | None = None
    counter_unit = _clean_text(raw.get("counter_unit") or "bits", 32).casefold()
    if mode == "direct_percent":
        if not oid:
            raise ValueError("direct_percent requires oid")
        if raw.get("counter_bits") not in (None, ""):
            raise ValueError("counter_bits is only valid for counter_rate_percent")
    elif mode == "direct_value":
        if not oid:
            raise ValueError("direct_value requires oid")
        if raw.get("counter_bits") not in (None, ""):
            raise ValueError("counter_bits is only valid for counter_rate_percent")
    elif mode == "used_total_percent":
        if not used_oid or not total_oid:
            raise ValueError("used_total_percent requires used_oid and total_oid")
    elif mode == "used_free_percent":
        if not used_oid or not free_oid:
            raise ValueError("used_free_percent requires used_oid and free_oid")
    elif mode == "counter_rate_percent":
        if not oid:
            raise ValueError("counter_rate_percent requires oid")
        if not capacity_oid:
            raise ValueError("counter_rate_percent requires capacity_oid")
        counter_bits = validate_counter_bits(raw.get("counter_bits"))
        if counter_unit not in SUPPORTED_COUNTER_UNITS:
            raise ValueError(f"counter_unit must be one of: {', '.join(SUPPORTED_COUNTER_UNITS)}")
    elif mode == "status_code":
        if not oid:
            raise ValueError("status_code requires oid")
        if raw.get("counter_bits") not in (None, ""):
            raise ValueError("counter_bits is only valid for counter_rate_percent")
        status_ok_values = _code_values(
            raw.get("status_ok_values", raw.get("normal_values")),
            "status_ok_values",
        )
        if not status_ok_values:
            raise ValueError("status_code requires at least one status_ok_values code")
        status_warning_values = _code_values(
            raw.get("status_warning_values", raw.get("warning_values")),
            "status_warning_values",
        )
        status_fail_values = _code_values(
            raw.get("status_fail_values", raw.get("failure_values")),
            "status_fail_values",
        )
    else:  # pragma: no cover - guarded above
        raise ValueError(f"unsupported metric mode: {mode}")

    return {
        "mode": mode,
        "oid": oid,
        "used_oid": used_oid,
        "total_oid": total_oid,
        "free_oid": free_oid,
        "capacity_oid": capacity_oid,
        "counter_bits": counter_bits,
        "counter_unit": counter_unit if mode == "counter_rate_percent" else "",
        "status_ok_values": status_ok_values if mode == "status_code" else [],
        "status_warning_values": status_warning_values if mode == "status_code" else [],
        "status_fail_values": status_fail_values if mode == "status_code" else [],
        "unit": _clean_text(
            raw.get("unit")
            or (
                "%"
                if mode in {"direct_percent", "used_total_percent", "used_free_percent", "counter_rate_percent"}
                else "bool"
                if mode == "status_code"
                else ""
            ),
            32,
        ),
        "aggregation": aggregation,
        "selector": selector,
        "scale": scale,
        "offset": offset,
    }


def metric_config_hash(config: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(config), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _config_json(config: Mapping[str, Any]) -> str:
    return json.dumps(dict(config), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _profile_metric_definitions(row: Any) -> dict[str, dict[str, Any]]:
    """Return all metric definitions, including legacy CPU/memory columns."""
    definitions: dict[str, dict[str, Any]] = {}
    raw_definitions = _decode_config(_row_value(row, "metric_definitions_json", ""))
    for metric_key, raw_config in raw_definitions.items():
        key = _clean_text(metric_key, 64).casefold()
        if not key:
            continue
        try:
            config = normalize_metric_config(raw_config)
            allowed_modes = _METRIC_ALLOWED_MODES.get(key)
            if allowed_modes and config.get("mode") not in allowed_modes:
                raise ValueError(f"{key} mode is incompatible with its output contract")
        except ValueError:
            # A malformed definition must not make the entire profile list
            # endpoint fail.  It remains absent from the collector cache and
            # is surfaced when the operator next edits/saves the profile.
            continue
        if config:
            definitions[key] = config

    # Older profiles have only the two JSON columns.  Keep them visible and
    # executable while operators migrate the remaining hardware metrics.
    for metric in ("cpu", "memory"):
        if metric in definitions:
            continue
        try:
            config = normalize_metric_config(
                _row_value(row, f"{metric}_config_json", ""),
                _row_value(row, f"{metric}_oid", ""),
            )
            allowed_modes = _METRIC_ALLOWED_MODES.get(metric)
            if allowed_modes and config.get("mode") not in allowed_modes:
                raise ValueError(f"{metric} mode is incompatible with its output contract")
        except ValueError:
            config = {}
        if config:
            definitions[metric] = config
    return definitions


def _profile_metric_config(row: Any, metric: str) -> dict[str, Any]:
    return _profile_metric_definitions(row).get(metric, {})


def profile_metric_config(row: Any, metric: str) -> dict[str, Any]:
    """Public row adapter used by the live verification endpoint."""
    metric_key = _clean_text(metric, 64).casefold()
    if not metric_key:
        raise ValueError("metric must not be empty")
    return _profile_metric_config(row, metric_key)


def profile_metric_definitions(row: Any) -> dict[str, dict[str, Any]]:
    """Public row adapter returning every configured hardware metric."""
    return _profile_metric_definitions(row)


def validate_metric_definitions(payload: Mapping[str, Any], *, allow_empty: bool = False) -> dict[str, dict[str, Any]]:
    """Validate a submitted hardware metric map for a read-only live probe.

    The editor's live test uses the exact same normalization and metric-mode
    contract as profile create/update. Keeping this adapter public avoids a
    second, subtly different validation path in the API layer.
    """
    return _validated_profile_values(payload, allow_empty=allow_empty)


def _profile_interface_config(row: Any) -> dict[str, Any]:
    raw = _decode_config(_row_value(row, 'interface_config_json', ''))
    if not raw:
        return {}
    try:
        normalized = normalize_interface_config(raw)
        return normalized if normalized.get('enabled', True) else {}
    except ValueError:
        # Keep the list endpoint resilient to a legacy/manual row.  Save/test
        # paths still validate and surface the exact field error to the user.
        return {}


def profile_interface_config(row: Any) -> dict[str, Any]:
    """Public row adapter for the optional interface OID override."""
    return _profile_interface_config(row)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def invalidate_metric_profile_cache() -> None:
    global _profile_cache, _profile_cache_expires_at
    with _profile_cache_lock:
        _profile_cache = None
        _profile_cache_expires_at = 0.0


def _load_profile_cache() -> dict[tuple[str, str], dict[str, Any]]:
    global _profile_cache, _profile_cache_expires_at
    now = time.monotonic()
    with _profile_cache_lock:
        if _profile_cache is not None and now < _profile_cache_expires_at:
            return _profile_cache

        profiles: dict[tuple[str, str], dict[str, Any]] = {}
        conn = get_db_connection()
        try:
            # Load every saved row so callers can distinguish an exact model
            # match from an executable model profile.  Only verified
            # definitions are placed in the effective collector mapping below;
            # unverified/failed rows remain visible as association metadata.
            rows = conn.execute("SELECT * FROM snmp_metric_profiles").fetchall()
            for row in rows:
                hardware_definitions = _profile_metric_definitions(row)
                interface_definition = _profile_interface_config(row)
                hardware_status = str(_row_value(row, 'verification_status', 'unverified') or 'unverified').casefold()
                interface_status = str(_row_value(row, 'interface_verification_status', 'unverified') or 'unverified').casefold()
                hardware = hardware_definitions if hardware_status == 'verified' else {}
                interface = interface_definition if interface_status == 'verified' else {}
                profiles[(str(_row_value(row, "vendor_key", "")), str(_row_value(row, "model_key", "")))] = {
                    "profile_id": str(_row_value(row, "id", "")),
                    "metrics": hardware,
                    "interface": interface,
                    "profile_vendor": str(_row_value(row, "vendor_name", "") or ""),
                    "profile_model": str(_row_value(row, "model_name", "") or ""),
                    "profile_status": hardware_status,
                    "interface_profile_status": interface_status,
                    "configured": bool(hardware_definitions),
                    "interface_configured": bool(interface_definition),
                }
        except Exception:
            # A collector may briefly start before an additive migration has
            # completed; use built-in vendor logic until the next refresh.
            profiles = {}
        finally:
            conn.close()

        _profile_cache = profiles
        _profile_cache_expires_at = time.monotonic() + _PROFILE_CACHE_TTL
        return profiles


def resolve_metric_profiles(device: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the effective definition for one device.

    Precedence is per metric: device exception -> verified exact vendor/model
    profile -> built-in vendor collector.  An unverified/failed profile is
    deliberately invisible to the collector, but remains exposed through the
    returned association metadata so the UI cannot silently hide a mismatch.
    """
    metrics: dict[str, dict[str, Any]] = {}
    sources: dict[str, str] = {}
    interface: dict[str, Any] = {}
    profile: dict[str, Any] = {}
    for metric, field in (("cpu", "snmp_cpu_oid"), ("memory", "snmp_memory_oid")):
        oid = _safe_oid(device.get(field))
        if oid:
            metrics[metric] = normalize_metric_config({"oid": oid, "mode": "direct_percent"})
            sources[metric] = "device_override"

    profile_id = ""
    model_key = normalize_model_key(device.get("model"))
    if model_key:
        profile = _load_profile_cache().get(
            (normalize_vendor_key(device.get("vendor"), device.get("platform")), model_key),
            {},
        )
        profile_id = str(profile.get("profile_id") or "")
        for metric, config in (profile.get("metrics") or {}).items():
            if metric not in metrics and config:
                metrics[metric] = dict(config)
                sources[metric] = "verified_model_profile"
        if profile.get('interface'):
            interface = dict(profile['interface'])

    metric_sources = {
        metric: sources.get(metric, "builtin_vendor_collector")
        for metric in HEALTH_METRIC_KEYS
    }
    has_device_override = any(source == "device_override" for source in sources.values())
    has_verified_model_profile = any(
        source == "verified_model_profile"
        for source in sources.values()
    ) or bool(interface)
    if has_device_override and has_verified_model_profile:
        profile_source = "mixed"
    elif has_device_override:
        profile_source = "device_override"
    elif has_verified_model_profile:
        profile_source = "model_profile"
    elif profile.get("profile_id") and profile.get("configured"):
        profile_source = "template_blocked"
    else:
        profile_source = "builtin_default"

    return {
        "profile_id": profile_id,
        "metrics": metrics,
        "sources": sources,
        "metric_sources": metric_sources,
        "metric_keys": sorted(metric for metric, config in metrics.items() if config),
        "profile_vendor": str(profile.get("profile_vendor") or ""),
        "profile_model": str(profile.get("profile_model") or ""),
        "profile_status": str(profile.get("profile_status") or "none"),
        "interface_profile_status": str(profile.get("interface_profile_status") or "none"),
        "profile_source": profile_source,
        "interface": interface,
        "interface_source": "verified_model_profile" if interface else "builtin_if_mib",
    }


def resolve_health_metric_profiles(device: Mapping[str, Any]) -> dict[str, Any]:
    """Return the template-resolved subset used by lightweight health polls."""
    resolved = resolve_metric_profiles(device)
    health_metrics = {
        metric: config
        for metric, config in (resolved.get("metrics") or {}).items()
        if metric in HEALTH_METRIC_KEYS and config
    }
    resolved["metrics"] = health_metrics
    resolved["metric_keys"] = sorted(health_metrics)
    resolved["metric_sources"] = {
        metric: (resolved.get("sources") or {}).get(metric, "builtin_vendor_collector")
        for metric in HEALTH_METRIC_KEYS
    }
    health_sources = resolved["metric_sources"]
    has_device_override = any(source == "device_override" for source in health_sources.values())
    has_model_profile = any(source == "verified_model_profile" for source in health_sources.values()) or bool(resolved.get("interface"))
    if has_device_override and has_model_profile:
        resolved["profile_source"] = "mixed"
    elif has_device_override:
        resolved["profile_source"] = "device_override"
    elif has_model_profile:
        resolved["profile_source"] = "model_profile"
    elif resolved.get("profile_id") and resolved.get("profile_status") in {"unverified", "failed"}:
        resolved["profile_source"] = "template_blocked"
    else:
        resolved["profile_source"] = "builtin_default"
    resolved["collection_mode"] = "health_only"
    return resolved


def annotate_devices_with_snmp_profile(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the effective template association without exposing credentials."""
    enriched: list[dict[str, Any]] = []
    for device in devices:
        item = dict(device)
        try:
            resolved = resolve_health_metric_profiles(item)
            item["snmp_metric_profile"] = {
                "id": resolved.get("profile_id") or None,
                "vendor": resolved.get("profile_vendor") or None,
                "model": resolved.get("profile_model") or None,
                "status": resolved.get("profile_status") or "none",
                "source": resolved.get("profile_source") or "builtin_default",
                "metric_keys": resolved.get("metric_keys") or [],
                "metric_sources": resolved.get("metric_sources") or {},
                "interface_source": resolved.get("interface_source") or "builtin_if_mib",
                "interface_status": resolved.get("interface_profile_status") or "none",
                "collection_mode": resolved.get("collection_mode") or "health_only",
            }
        except Exception:
            # Inventory rendering must remain available if a legacy database
            # is missing the optional profile table during startup.
            item["snmp_metric_profile"] = {
                "id": None,
                "vendor": None,
                "model": None,
                "status": "none",
                "source": "builtin_default",
                "metric_keys": [],
                "metric_sources": {metric: "builtin_vendor_collector" for metric in HEALTH_METRIC_KEYS},
                "interface_source": "builtin_if_mib",
                "interface_status": "none",
                "collection_mode": "health_only",
            }
        enriched.append(item)
    return enriched


def resolve_metric_oids(device: Mapping[str, Any]) -> dict[str, str]:
    """Compatibility projection for callers that only need the source OID."""
    resolved = resolve_metric_profiles(device)
    metrics = resolved.get("metrics") or {}
    return {
        "cpu": str((metrics.get("cpu") or {}).get("oid") or ""),
        "memory": str((metrics.get("memory") or {}).get("oid") or ""),
    }


def _profile_to_dict(row: Any) -> dict[str, Any]:
    metric_definitions = _profile_metric_definitions(row)
    interface_config = _profile_interface_config(row)
    cpu_config = metric_definitions.get("cpu", {})
    memory_config = metric_definitions.get("memory", {})
    return {
        "profile_id": str(_row_value(row, "id", "")),
        "vendor": str(_row_value(row, "vendor_name", "")),
        "model": str(_row_value(row, "model_name", "")),
        "cpu_oid": str(cpu_config.get("oid") or ""),
        "memory_oid": str(memory_config.get("oid") or ""),
        "cpu_config": cpu_config,
        "memory_config": memory_config,
        "metric_definitions": metric_definitions,
        "metric_keys": sorted(metric_definitions),
        "configured": bool(metric_definitions),
        "verification_status": str(_row_value(row, "verification_status", "unverified") or "unverified"),
        "interface_config": interface_config,
        "interface_configured": bool(interface_config),
        "interface_verification_status": str(_row_value(row, "interface_verification_status", "unverified") or "unverified"),
        "interface_last_test_at": _row_value(row, "interface_last_test_at"),
        "interface_last_test_device_id": str(_row_value(row, "interface_last_test_device_id", "") or ""),
        "interface_last_test_message": str(_row_value(row, "interface_last_test_message", "") or ""),
        "last_test_at": _row_value(row, "last_test_at"),
        "last_test_device_id": str(_row_value(row, "last_test_device_id", "") or ""),
        "last_test_message": str(_row_value(row, "last_test_message", "") or ""),
        "updated_at": _row_value(row, "updated_at"),
        "updated_by": str(_row_value(row, "updated_by", "") or ""),
    }


def _collector_status(configured: bool, verification_status: Any, matched_device_count: int) -> str:
    """Describe whether a saved profile can actually be consumed by collectors."""
    if not configured:
        return "builtin_only"
    if matched_device_count <= 0:
        return "no_matching_device"
    status = str(verification_status or "unverified").casefold()
    if status == "verified":
        return "active"
    if status == "failed":
        return "blocked_failed"
    return "blocked_unverified"


def _collect_model_metric_profiles(conn, search: str = "") -> list[dict[str, Any]]:
    """Collect discovered model groups and configured definitions for the UI."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    device_rows = conn.execute(
        """
        SELECT MIN(id) AS sample_device_id, vendor, platform, model, COUNT(*) AS device_count
        FROM devices
        WHERE COALESCE(TRIM(model), '') <> ''
        GROUP BY vendor, platform, model
        """
    ).fetchall()
    for row in device_rows:
        vendor = normalize_vendor_name(_row_value(row, "vendor", ""), _row_value(row, "platform", ""))
        model = _clean_text(_row_value(row, "model", ""))
        key = (vendor.casefold(), normalize_model_key(model))
        group = groups.setdefault(
            key,
            {
                "profile_id": None,
                "vendor": vendor,
                "model": model,
                "cpu_oid": "",
                "memory_oid": "",
                "cpu_config": {},
                "memory_config": {},
                "metric_definitions": {},
                "metric_keys": [],
                "configured": False,
                "verification_status": "unverified",
                "interface_config": {},
                "interface_configured": False,
                "interface_verification_status": "unverified",
                "interface_last_test_at": None,
                "interface_last_test_device_id": "",
                "interface_last_test_message": "",
                "last_test_at": None,
                "last_test_device_id": "",
                "last_test_message": "",
                "device_count": 0,
                "sample_device_id": None,
                "platforms": [],
                "updated_at": None,
                "updated_by": "",
            },
        )
        group["device_count"] += int(_row_value(row, "device_count", 0) or 0)
        if not group["sample_device_id"]:
            group["sample_device_id"] = str(_row_value(row, "sample_device_id", "") or "") or None
        platform = _clean_text(_row_value(row, "platform", ""), 128)
        if platform and platform not in group["platforms"]:
            group["platforms"].append(platform)

    profiles = conn.execute("SELECT * FROM snmp_metric_profiles ORDER BY vendor_name, model_name").fetchall()
    for row in profiles:
        profile = _profile_to_dict(row)
        key = (str(_row_value(row, "vendor_key", "")), str(_row_value(row, "model_key", "")))
        group = groups.setdefault(
            key,
            {**profile, "device_count": 0, "sample_device_id": None, "platforms": []},
        )
        group.update(profile)

    query = _clean_text(search, 128).casefold()
    items = list(groups.values())
    if query:
        items = [
            item for item in items
            if query in str(item["vendor"]).casefold()
            or query in str(item["model"]).casefold()
            or any(query in str(platform).casefold() for platform in item["platforms"])
        ]
    for item in items:
        item["platforms"] = sorted(item["platforms"])
        matched_device_count = int(item.get("device_count") or 0)
        item["matched_device_count"] = matched_device_count
        hardware_status = _collector_status(
            bool(item.get("configured")),
            item.get("verification_status"),
            matched_device_count,
        )
        interface_status = _collector_status(
            bool(item.get("interface_configured")),
            item.get("interface_verification_status"),
            matched_device_count,
        )
        item["interface_collector_status"] = interface_status
        item["hardware_collector_status"] = hardware_status
        if hardware_status == "active" or interface_status == "active":
            item["collector_status"] = "active"
        elif item.get("configured"):
            item["collector_status"] = hardware_status
        elif item.get("interface_configured"):
            item["collector_status"] = interface_status
        else:
            item["collector_status"] = "builtin_only"
        item["profile_applied_device_count"] = (
            matched_device_count if item["collector_status"] == "active" else 0
        )
        item["blocked_device_count"] = (
            matched_device_count
            if item["collector_status"] in {"blocked_unverified", "blocked_failed"}
            else 0
        )
    return sorted(items, key=lambda item: (str(item["vendor"]).casefold(), str(item["model"]).casefold()))


def list_model_metric_profiles(conn, search: str = "") -> list[dict[str, Any]]:
    """List all model groups for callers that still need the legacy shape."""
    return _collect_model_metric_profiles(conn, search)


def list_model_metric_profiles_page(
    conn,
    search: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Return a bounded page of model groups with stable pagination metadata.

    The model grouping combines inventory-discovered rows and explicitly saved
    profiles, so the service keeps that merge in one place and applies the
    requested page after filtering.  The API contract remains a list in
    ``data`` while exposing the total and effective page values beside it.
    """
    safe_page_size = max(1, min(100, int(page_size)))
    safe_page = max(1, int(page))
    items = _collect_model_metric_profiles(conn, search)
    total = len(items)
    total_pages = max(1, math.ceil(total / safe_page_size))
    safe_page = min(safe_page, total_pages)
    offset = (safe_page - 1) * safe_page_size
    return {
        "items": items[offset:offset + safe_page_size],
        "total": total,
        "page": safe_page,
        "page_size": safe_page_size,
        "total_pages": total_pages,
    }


def get_model_metric_profile_mapping(conn, profile_id: str) -> dict[str, Any]:
    """Return a deterministic, read-only mapping coverage report.

    This is intentionally separate from live SNMP testing.  A live sample
    proves that the OIDs work on one device; this report proves which inventory
    devices will receive the profile, which ones have an explicit exception,
    and whether the profile is actually eligible for the collector cache.
    """
    row = conn.execute("SELECT * FROM snmp_metric_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        raise ValueError("Model metric profile not found")
    vendor_key = str(_row_value(row, "vendor_key", ""))
    model_key = str(_row_value(row, "model_key", ""))
    device_rows = conn.execute(
        """
        SELECT id, hostname, ip_address, vendor, platform, model,
               snmp_cpu_oid, snmp_memory_oid
        FROM devices
        WHERE LOWER(TRIM(COALESCE(model, ''))) = LOWER(TRIM(?))
        ORDER BY hostname, id
        """,
        (_row_value(row, "model_name", ""),),
    ).fetchall()

    matching: list[dict[str, Any]] = []
    same_model_other_vendor = 0
    cpu_overrides = 0
    memory_overrides = 0
    for raw_device in device_rows:
        device = dict(raw_device)
        is_vendor_match = normalize_vendor_key(device.get("vendor"), device.get("platform")) == vendor_key
        is_model_match = normalize_model_key(device.get("model")) == model_key
        if not is_model_match:
            continue
        if not is_vendor_match:
            same_model_other_vendor += 1
            continue
        cpu_override = bool(_safe_oid(device.get("snmp_cpu_oid")))
        memory_override = bool(_safe_oid(device.get("snmp_memory_oid")))
        cpu_overrides += int(cpu_override)
        memory_overrides += int(memory_override)
        matching.append({
            "device_id": str(device.get("id") or ""),
            "hostname": str(device.get("hostname") or device.get("ip_address") or device.get("id") or ""),
            "ip_address": str(device.get("ip_address") or ""),
            "cpu_source": "device_override" if cpu_override else "model_profile",
            "memory_source": "device_override" if memory_override else "model_profile",
        })

    status = str(_row_value(row, "verification_status", "unverified") or "unverified")
    interface_status = str(_row_value(row, "interface_verification_status", "unverified") or "unverified")
    metric_definitions = _profile_metric_definitions(row)
    interface_config = _profile_interface_config(row)
    configured = bool(metric_definitions)
    interface_configured = bool(interface_config)
    hardware_collector_status = _collector_status(configured, status, len(matching))
    interface_collector_status = _collector_status(interface_configured, interface_status, len(matching))
    if hardware_collector_status == 'active' or interface_collector_status == 'active':
        collector_status = 'active'
    elif configured:
        collector_status = hardware_collector_status
    elif interface_configured:
        collector_status = interface_collector_status
    else:
        collector_status = 'builtin_only'
    return {
        "profile_id": profile_id,
        "vendor": str(_row_value(row, "vendor_name", "")),
        "model": str(_row_value(row, "model_name", "")),
        "verification_status": status,
        "collector_status": collector_status,
        "hardware_collector_status": hardware_collector_status,
        "interface_verification_status": interface_status,
        "interface_collector_status": interface_collector_status,
        "interface_configured": interface_configured,
        "interface_config": interface_config,
        "matched_device_count": len(matching),
        "profile_applied_device_count": len(matching) if collector_status == "active" else 0,
        "blocked_device_count": len(matching) if collector_status in {"blocked_unverified", "blocked_failed"} else 0,
        "cpu_device_override_count": cpu_overrides,
        "memory_device_override_count": memory_overrides,
        "metric_keys": sorted(metric_definitions),
        "same_model_other_vendor_count": same_model_other_vendor,
        "sample_device_id": matching[0]["device_id"] if matching else None,
        "devices": matching[:100],
        "truncated": len(matching) > 100,
    }


def _validated_profile_values(
    payload: Mapping[str, Any],
    *,
    allow_empty: bool = False,
) -> dict[str, dict[str, Any]]:
    """Validate the full hardware metric map with legacy CPU/memory fallback."""
    submitted = payload.get("metric_definitions")
    if not isinstance(submitted, Mapping):
        submitted = payload.get("metrics")
    if not isinstance(submitted, Mapping):
        submitted = {
            "cpu": payload.get("cpu_config") or payload.get("cpu_oid"),
            "memory": payload.get("memory_config") or payload.get("memory_oid"),
        }

    definitions: dict[str, dict[str, Any]] = {}
    for raw_key, raw_config in submitted.items():
        metric_key = _clean_text(raw_key, 64).casefold()
        if not metric_key:
            continue
        try:
            config = normalize_metric_config(raw_config)
        except ValueError as exc:
            raise ValueError(f"{metric_key}: {exc}") from exc
        allowed_modes = _METRIC_ALLOWED_MODES.get(metric_key)
        if allowed_modes and config.get("mode") not in allowed_modes:
            raise ValueError(
                f"{metric_key}: mode must be one of: {', '.join(sorted(allowed_modes))}"
            )
        if config:
            definitions[metric_key] = config
    if not definitions and not allow_empty:
        raise ValueError("at least one hardware metric definition is required")
    return definitions


def _validated_interface_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    submitted = payload.get('interface_config')
    if submitted is None:
        submitted = payload.get('interface')
    if submitted in (None, ''):
        return {}
    try:
        normalized = normalize_interface_config(submitted)
    except ValueError as exc:
        raise ValueError(f'interface_config: {exc}') from exc
    if not normalized or not normalized.get('enabled', True):
        return {}
    return normalized


def _profile_identity(conn, payload: Mapping[str, Any], existing: Any = None) -> tuple[str, str, str, str]:
    vendor = normalize_vendor_name(
        payload.get("vendor") if payload.get("vendor") is not None else _row_value(existing, "vendor_name", ""),
        payload.get("platform") if payload.get("platform") is not None else "",
    )
    model = _clean_text(
        payload.get("model") if payload.get("model") is not None else _row_value(existing, "model_name", "")
    )
    if not model:
        raise ValueError("model is required")
    return vendor, model, vendor.casefold(), normalize_model_key(model)


def create_model_metric_profile(conn, payload: Mapping[str, Any], updated_by: str = "") -> dict[str, Any]:
    vendor, model, vendor_key, model_key = _profile_identity(conn, payload)
    interface_config = _validated_interface_values(payload)
    metric_definitions = _validated_profile_values(payload, allow_empty=bool(interface_config))
    if not metric_definitions and not interface_config:
        raise ValueError("at least one hardware metric or an interface OID definition is required")
    cpu_config = metric_definitions.get("cpu", {})
    memory_config = metric_definitions.get("memory", {})
    if conn.execute(
        "SELECT id FROM snmp_metric_profiles WHERE vendor_key = ? AND model_key = ?",
        (vendor_key, model_key),
    ).fetchone():
        raise ValueError("A profile already exists for this vendor and model")

    now = _utc_now()
    profile_id = f"snmp-profile-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO snmp_metric_profiles
            (id, vendor_key, vendor_name, model_key, model_name,
             cpu_oid, memory_oid, cpu_config_json, memory_config_json,
             metric_definitions_json, interface_config_json,
             created_at, updated_at, updated_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile_id,
            vendor_key,
            vendor,
            model_key,
            model,
            str(cpu_config.get("oid") or ""),
            str(memory_config.get("oid") or ""),
            _config_json(cpu_config),
            _config_json(memory_config),
            _config_json(metric_definitions),
            _config_json(interface_config),
            now,
            now,
            updated_by,
        ),
    )
    invalidate_metric_profile_cache()
    return dict(conn.execute("SELECT * FROM snmp_metric_profiles WHERE id = ?", (profile_id,)).fetchone())


def update_model_metric_profile(conn, profile_id: str, payload: Mapping[str, Any], updated_by: str = "") -> dict[str, Any]:
    row = conn.execute("SELECT * FROM snmp_metric_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        raise ValueError("Model metric profile not found")
    vendor, model, vendor_key, model_key = _profile_identity(conn, payload, row)
    interface_config = _validated_interface_values(payload)
    metric_definitions = _validated_profile_values(payload, allow_empty=bool(interface_config))
    if not metric_definitions and not interface_config:
        raise ValueError("at least one hardware metric or an interface OID definition is required")
    cpu_config = metric_definitions.get("cpu", {})
    memory_config = metric_definitions.get("memory", {})
    conflict = conn.execute(
        "SELECT id FROM snmp_metric_profiles WHERE vendor_key = ? AND model_key = ? AND id <> ?",
        (vendor_key, model_key, profile_id),
    ).fetchone()
    if conflict:
        raise ValueError("A profile already exists for this vendor and model")

    now = _utc_now()
    conn.execute(
        """
        UPDATE snmp_metric_profiles
        SET vendor_key = ?, vendor_name = ?, model_key = ?, model_name = ?,
            cpu_oid = ?, memory_oid = ?, cpu_config_json = ?, memory_config_json = ?,
            metric_definitions_json = ?, interface_config_json = ?,
            verification_status = 'unverified', last_test_at = NULL,
            last_test_device_id = '',
            last_test_message = 'Metric definition changed; live verification required',
            interface_verification_status = 'unverified', interface_last_test_at = NULL,
            interface_last_test_device_id = '',
            interface_last_test_message = 'Interface definition changed; live verification required',
            updated_at = ?, updated_by = ?
        WHERE id = ?
        """,
        (
            vendor_key,
            vendor,
            model_key,
            model,
            str(cpu_config.get("oid") or ""),
            str(memory_config.get("oid") or ""),
            _config_json(cpu_config),
            _config_json(memory_config),
            _config_json(metric_definitions),
            _config_json(interface_config),
            now,
            updated_by,
            profile_id,
        ),
    )
    invalidate_metric_profile_cache()
    return dict(conn.execute("SELECT * FROM snmp_metric_profiles WHERE id = ?", (profile_id,)).fetchone())


def mark_model_metric_profile_test(
    conn,
    profile_id: str,
    device_id: str,
    passed: bool | None = None,
    message: str = '',
    *,
    hardware_passed: bool | None = None,
    interface_passed: bool | None = None,
    interface_message: str = '',
) -> dict[str, Any]:
    if not conn.execute("SELECT id FROM snmp_metric_profiles WHERE id = ?", (profile_id,)).fetchone():
        raise ValueError("Model metric profile not found")
    if hardware_passed is None and passed is not None:
        hardware_passed = bool(passed)
    now = _utc_now()
    assignments: list[str] = []
    values: list[Any] = []
    if hardware_passed is not None:
        assignments.extend(('verification_status = ?', 'last_test_at = ?', 'last_test_device_id = ?', 'last_test_message = ?'))
        values.extend(('verified' if hardware_passed else 'failed', now, device_id, _clean_text(message, 500)))
    if interface_passed is not None:
        assignments.extend((
            'interface_verification_status = ?',
            'interface_last_test_at = ?',
            'interface_last_test_device_id = ?',
            'interface_last_test_message = ?',
        ))
        values.extend(('verified' if interface_passed else 'failed', now, device_id, _clean_text(interface_message, 500)))
    if assignments:
        values.append(profile_id)
        conn.execute(
            f"UPDATE snmp_metric_profiles SET {', '.join(assignments)} WHERE id = ?",
            tuple(values),
        )
    invalidate_metric_profile_cache()
    return dict(conn.execute("SELECT * FROM snmp_metric_profiles WHERE id = ?", (profile_id,)).fetchone())


def delete_model_metric_profile(conn, profile_id: str) -> bool:
    if not conn.execute("SELECT id FROM snmp_metric_profiles WHERE id = ?", (profile_id,)).fetchone():
        raise ValueError("Model metric profile not found")
    conn.execute("DELETE FROM snmp_metric_profiles WHERE id = ?", (profile_id,))
    invalidate_metric_profile_cache()
    return True


__all__ = [
    "SUPPORTED_AGGREGATIONS",
    "SUPPORTED_COUNTER_UNITS",
    "SUPPORTED_METRIC_KEYS",
    "SUPPORTED_METRIC_MODES",
    "HEALTH_METRIC_KEYS",
    "ALERT_METRIC_COLLECTION_BINDINGS",
    "annotate_devices_with_snmp_profile",
    "create_model_metric_profile",
    "delete_model_metric_profile",
    "get_model_metric_profile_mapping",
    "get_alert_metric_collection",
    "invalidate_metric_profile_cache",
    "list_model_metric_profiles",
    "list_model_metric_profiles_page",
    "list_alert_metric_collections",
    "mark_model_metric_profile_test",
    "metric_config_hash",
    "normalize_metric_config",
    "normalize_interface_config",
    "normalize_model_key",
    "normalize_vendor_key",
    "normalize_vendor_name",
    "profile_metric_config",
    "profile_metric_definitions",
    "validate_metric_definitions",
    "profile_interface_config",
    "resolve_metric_oids",
    "resolve_health_metric_profiles",
    "resolve_metric_profiles",
    "update_model_metric_profile",
]
