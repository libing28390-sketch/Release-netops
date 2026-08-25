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
    SYS_UPTIME,
    normalize_interface_config,
    normalize_metric_oid,
)


_PROFILE_CACHE_TTL = 60.0
_profile_cache: dict[str, dict[str, Any]] | None = None
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
    "uptime",
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
        "description": "只使用已在 SNMP 指标模板中应用的型号 CPU 定义；未应用模板时不采集该指标。",
        "description_en": "Use only the applied model-template CPU definition; do not collect this metric before a template is applied.",
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
        "description": "只使用已在 SNMP 指标模板中应用的型号内存定义；比例计算方式由模板 mode 决定。",
        "description_en": "Use only the applied model-template memory definition; the template mode controls the percentage formula.",
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
        "default_oids": {},
        "description": "接口利用率只使用已应用模板中的 Counter64/Counter32 与 ifHighSpeed OID；未应用模板时不采集。",
        "description_en": "Interface utilization uses only the applied template's Counter64/Counter32 and ifHighSpeed OIDs; collection is disabled until a template is applied.",
    },
    "interface_down": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 接口模板",
        "collection_label_en": "SNMP interface template",
        "template_linked": True,
        "template_section": "接口指标 / 运行状态",
        "template_metric": "interface",
        "oid_paths": ["interface_config.if_oper_status_oid"],
        "default_oids": {},
        "description": "接口 DOWN 告警只读取已应用模板中的 ifOperStatus，并只在 UP→DOWN 状态变化时触发。",
        "description_en": "Interface-down alerts read ifOperStatus from the applied template and trigger only on an UP-to-DOWN transition.",
    },
    "interconnect_down": {
        "collection_source": "snmp_template",
        "collection_label": "SNMP 接口模板",
        "collection_label_en": "SNMP interface template",
        "template_linked": True,
        "template_section": "接口指标 / 互联口运行状态",
        "template_metric": "interface",
        "oid_paths": ["interface_config.if_oper_status_oid"],
        "default_oids": {},
        "description": "互联口 DOWN 与普通接口共用已应用模板中的 ifOperStatus，区别只来自拓扑端口识别。",
        "description_en": "Interconnect-down uses ifOperStatus from the applied template; topology identifies the interconnect port.",
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
        "default_oids": {},
        "description": "接口震荡只使用已应用模板中的 ifOperStatus/ifLastChange，基于连续采样判断 UP/DOWN 翻转。",
        "description_en": "Interface flapping uses ifOperStatus/ifLastChange from the applied template and sampled UP/DOWN transitions.",
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
        "default_oids": {},
        "description": "错误率只使用已应用模板中的接口错误、丢弃、包计数和 EtherLike OID，避免另行回退到内置 OID。",
        "description_en": "Error rate uses only interface error, discard, packet, and EtherLike OIDs from the applied template; no built-in OID fallback is used.",
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


def _table_columns(conn, table: str) -> set[str]:
    """Read table columns for narrow compatibility with pre-m0181 test DBs.

    Production connections are migrated before collectors start.  Keeping this
    adapter here lets isolated service tests and a briefly older read-only
    connection fail gracefully while the explicit-column path remains the
    normal behavior.
    """
    try:
        cursor = conn.execute(f"SELECT * FROM {table} LIMIT 0")
        return {str(description[0]) for description in (cursor.description or [])}
    except Exception:
        return set()


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


def _load_profile_cache() -> dict[str, dict[str, Any]]:
    global _profile_cache, _profile_cache_expires_at
    now = time.monotonic()
    with _profile_cache_lock:
        if _profile_cache is not None and now < _profile_cache_expires_at:
            return _profile_cache

        profiles: dict[str, dict[str, Any]] = {}
        conn = get_db_connection()
        try:
            # Load every saved row so callers can distinguish an exact model
            # match from an executable model profile.  The saved template is
            # the sole OID source once it is applied. Verification status is
            # retained as quality metadata and must not cause a silent fall
            # back to a vendor-specific OID set.
            rows = conn.execute("SELECT * FROM snmp_metric_profiles").fetchall()
            for row in rows:
                hardware_definitions = _profile_metric_definitions(row)
                interface_definition = _profile_interface_config(row)
                hardware_status = str(_row_value(row, 'verification_status', 'unverified') or 'unverified').casefold()
                interface_status = str(_row_value(row, 'interface_verification_status', 'unverified') or 'unverified').casefold()
                effective_hardware_definitions = {} if hardware_status == 'failed' else hardware_definitions
                effective_interface_definition = {} if interface_status == 'failed' else interface_definition
                profile_id = str(_row_value(row, "id", ""))
                if not profile_id:
                    continue
                profiles[profile_id] = {
                    "profile_id": profile_id,
                    "metrics": effective_hardware_definitions,
                    "interface": effective_interface_definition,
                    "profile_vendor": str(_row_value(row, "vendor_name", "") or ""),
                    "profile_model": str(_row_value(row, "model_name", "") or ""),
                    "template_name": str(_row_value(row, "template_name", "") or ""),
                    "source": str(_row_value(row, "source", "legacy") or "legacy"),
                    "official_preset_id": str(_row_value(row, "official_preset_id", "") or ""),
                    "profile_status": hardware_status,
                    "interface_profile_status": interface_status,
                    "configured": bool(hardware_definitions),
                    "interface_configured": bool(interface_definition),
                }
        except Exception:
            # A collector may briefly start before an additive migration has
            # completed. Do not fall back to a vendor OID set: the explicit
            # template contract must fail closed until the profile table is
            # readable again.
            profiles = {}
        finally:
            conn.close()

        _profile_cache = profiles
        _profile_cache_expires_at = time.monotonic() + _PROFILE_CACHE_TTL
        return profiles


def resolve_metric_profiles(device: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the effective definition for one device.

    A migrated device's explicit ``snmp_metric_profile_id`` is the only source
    of SNMP metric OIDs. Legacy per-device CPU/memory OID fields and
    vendor/model matching are intentionally ignored. A missing/unconfigured
    template is represented explicitly instead of falling back to a
    vendor-specific hard-coded collector. The narrow missing-key compatibility
    branch exists only for pre-m0181 partial objects used during upgrades.
    """
    metrics: dict[str, dict[str, Any]] = {}
    sources: dict[str, str] = {}
    interface: dict[str, Any] = {}
    profile: dict[str, Any] = {}
    profile_id = ""
    has_explicit_binding_field = "snmp_metric_profile_id" in device
    profile_id = str(device.get("snmp_metric_profile_id") or "").strip()
    if profile_id:
        profile = _load_profile_cache().get(profile_id, {})
    elif not has_explicit_binding_field:
        # Compatibility for callers that still pass a pre-m0181 partial device
        # object.  Real migrated device rows always contain the field, and an
        # empty value on those rows intentionally means "not applied".
        device_vendor = normalize_vendor_key(device.get("vendor"), device.get("platform"))
        device_model = normalize_model_key(device.get("model"))
        for candidate in _load_profile_cache().values():
            if (
                normalize_vendor_key(candidate.get("profile_vendor"), "") == device_vendor
                and normalize_model_key(candidate.get("profile_model")) == device_model
            ):
                profile = candidate
                profile_id = str(candidate.get("profile_id") or "")
                break
    if profile_id and not profile:
        profile = _load_profile_cache().get(profile_id, {})
    for metric, config in (profile.get("metrics") or {}).items():
        if config:
            metrics[metric] = dict(config)
            sources[metric] = "snmp_template"
    if profile.get('interface'):
        interface = dict(profile['interface'])

    metric_sources = {
        metric: sources.get(metric, "template_not_applied")
        for metric in HEALTH_METRIC_KEYS
    }
    template_applied = bool(
        profile_id and (profile.get("configured") or profile.get("interface_configured"))
    )
    profile_source = "snmp_template" if template_applied else "template_not_applied"

    return {
        "profile_id": profile_id,
        "metrics": metrics,
        "sources": sources,
        "metric_sources": metric_sources,
        "metric_keys": sorted(metric for metric, config in metrics.items() if config),
        "profile_vendor": str(profile.get("profile_vendor") or ""),
        "profile_model": str(profile.get("profile_model") or ""),
        "template_name": str(profile.get("template_name") or ""),
        "template_source": str(profile.get("source") or "none"),
        "official_preset_id": str(profile.get("official_preset_id") or ""),
        "profile_status": str(profile.get("profile_status") or "none"),
        "interface_profile_status": str(profile.get("interface_profile_status") or "none"),
        "profile_source": profile_source,
        "interface": interface,
        "interface_source": "snmp_template" if interface else "template_not_applied",
        "template_applied": template_applied,
        "template_required": True,
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
        metric: (resolved.get("sources") or {}).get(metric, "template_not_applied")
        for metric in HEALTH_METRIC_KEYS
    }
    resolved["profile_source"] = (
        "snmp_template"
        if resolved.get("template_applied")
        else "template_not_applied"
    )
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
                "name": resolved.get("template_name") or None,
                "status": resolved.get("profile_status") or "none",
                "source": resolved.get("profile_source") or "template_not_applied",
                "template_source": resolved.get("template_source") or "none",
                "official_preset_id": resolved.get("official_preset_id") or None,
                "metric_keys": resolved.get("metric_keys") or [],
                "metric_sources": resolved.get("metric_sources") or {},
                "interface_source": resolved.get("interface_source") or "template_not_applied",
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
                "name": None,
                "status": "none",
                "source": "template_not_applied",
                "template_source": "none",
                "official_preset_id": None,
                "metric_keys": [],
                "metric_sources": {metric: "template_not_applied" for metric in HEALTH_METRIC_KEYS},
                "interface_source": "template_not_applied",
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
    vendor = str(_row_value(row, "vendor_name", "") or "")
    model = str(_row_value(row, "model_name", "") or "")
    template_name = str(_row_value(row, "template_name", "") or "").strip()
    source = str(_row_value(row, "source", "custom") or "custom").strip().casefold()
    if source not in {"official", "custom", "legacy", "inventory"}:
        source = "custom"
    return {
        "profile_id": str(_row_value(row, "id", "")),
        "vendor": vendor,
        "model": model,
        "template_name": template_name or " / ".join(part for part in (vendor, model) if part),
        "source": source,
        "official_preset_id": str(_row_value(row, "official_preset_id", "") or ""),
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
        "bound_device_count": 0,
        "unbound_device_count": 0,
    }


def _collector_status(configured: bool, verification_status: Any, matched_device_count: int) -> str:
    """Describe whether a saved profile can actually be consumed by collectors."""
    if not configured:
        return "template_required"
    if matched_device_count <= 0:
        return "no_matching_device"
    status = str(verification_status or "unverified").casefold()
    if status == "failed":
        return "blocked_failed"
    # Applying a profile is the explicit source-selection action. Live
    # verification remains visible as quality metadata, but it must never
    # switch the collector to a different hard-coded OID set.
    return "active"


def _collect_model_metric_profiles(conn, search: str = "") -> list[dict[str, Any]]:
    """Collect saved templates and inventory candidates for the UI.

    A saved row is one independently selectable template.  ``bound_device_count``
    is intentionally derived from the device foreign-key-like reference, not
    from vendor/model matching.  Inventory-only rows are retained so operators
    can see devices that still need a manual template choice.
    """
    device_rows = conn.execute(
        """
        SELECT id, hostname, ip_address, vendor, platform, model, status,
               snmp_metric_profile_id
        FROM devices
        WHERE COALESCE(TRIM(model), '') <> ''
        ORDER BY CASE WHEN LOWER(TRIM(COALESCE(status, ''))) = 'online' THEN 0 ELSE 1 END,
                 CASE WHEN COALESCE(TRIM(ip_address), '') <> '' THEN 0 ELSE 1 END,
                 COALESCE(hostname, ''), id
        """
    ).fetchall()

    inventory: dict[tuple[str, str], dict[str, Any]] = {}
    devices_by_profile: dict[str, list[dict[str, Any]]] = {}
    for raw in device_rows:
        device = dict(raw)
        vendor = normalize_vendor_name(device.get("vendor"), device.get("platform"))
        model = _clean_text(device.get("model"))
        key = (vendor.casefold(), normalize_model_key(model))
        item = inventory.setdefault(
            key,
            {
                "vendor": vendor,
                "model": model,
                "devices": [],
                "platforms": [],
            },
        )
        item["devices"].append(device)
        platform = _clean_text(device.get("platform"), 128)
        if platform and platform not in item["platforms"]:
            item["platforms"].append(platform)
        profile_id = str(device.get("snmp_metric_profile_id") or "").strip()
        if profile_id:
            devices_by_profile.setdefault(profile_id, []).append(device)

    def _sample(devices: list[dict[str, Any]]) -> dict[str, Any]:
        if not devices:
            return {"sample_device_id": None, "sample_device_ip": None, "sample_device_status": None}
        device = devices[0]
        return {
            "sample_device_id": str(device.get("id") or "") or None,
            "sample_device_ip": str(device.get("ip_address") or "") or None,
            "sample_device_status": str(device.get("status") or "") or None,
        }

    profiles = conn.execute("SELECT * FROM snmp_metric_profiles ORDER BY vendor_name, model_name, id").fetchall()
    items: list[dict[str, Any]] = []
    saved_identity_keys: set[tuple[str, str]] = set()
    for row in profiles:
        profile = _profile_to_dict(row)
        profile_id = str(profile.get("profile_id") or "")
        vendor_key = str(_row_value(row, "vendor_key", "") or "").casefold()
        model_key = str(_row_value(row, "model_key", "") or "")
        identity_key = (
            vendor_key or normalize_vendor_key(profile.get("vendor"), ""),
            model_key or normalize_model_key(profile.get("model")),
        )
        saved_identity_keys.add(identity_key)
        identity = inventory.get(identity_key, {"devices": [], "platforms": []})
        bound_devices = devices_by_profile.get(profile_id, [])
        all_devices = identity.get("devices", [])
        unbound_devices = [device for device in all_devices if not str(device.get("snmp_metric_profile_id") or "").strip()]
        sample = _sample(bound_devices or all_devices)
        profile.update(
            {
                "device_count": len(bound_devices),
                "bound_device_count": len(bound_devices),
                "inventory_device_count": len(all_devices),
                "unbound_device_count": len(unbound_devices),
                "matched_device_count": len(bound_devices),
                "sample_device_id": sample["sample_device_id"],
                "sample_device_ip": sample["sample_device_ip"],
                "sample_device_status": sample["sample_device_status"],
                "platforms": sorted(identity.get("platforms", [])),
            }
        )
        items.append(profile)

    # Keep a discoverable row for a model identity that has no saved template.
    # It is explicitly marked as inventory so the UI cannot mistake discovery
    # coverage for an actual binding.
    for identity_key, identity in inventory.items():
        if identity_key in saved_identity_keys:
            continue
        all_devices = identity.get("devices", [])
        sample = _sample(all_devices)
        items.append(
            {
                "profile_id": None,
                "vendor": identity.get("vendor", ""),
                "model": identity.get("model", ""),
                "template_name": " / ".join(
                    part for part in (identity.get("vendor", ""), identity.get("model", "")) if part
                ),
                "source": "inventory",
                "official_preset_id": "",
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
                "device_count": len(all_devices),
                "bound_device_count": 0,
                "inventory_device_count": len(all_devices),
                "unbound_device_count": len(all_devices),
                "matched_device_count": 0,
                "sample_device_id": sample["sample_device_id"],
                "sample_device_ip": sample["sample_device_ip"],
                "sample_device_status": sample["sample_device_status"],
                "platforms": sorted(identity.get("platforms", [])),
                "updated_at": None,
                "updated_by": "",
            }
        )

    query = _clean_text(search, 128).casefold()
    if query:
        items = [
            item for item in items
            if query in str(item.get("vendor") or "").casefold()
            or query in str(item.get("model") or "").casefold()
            or query in str(item.get("template_name") or "").casefold()
            or query in str(item.get("source") or "").casefold()
            or any(query in str(platform).casefold() for platform in item.get("platforms", []))
        ]

    for item in items:
        item["platforms"] = sorted(item.get("platforms", []))
        matched_device_count = int(item.get("bound_device_count") or 0)
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
            item["collector_status"] = "template_required"
        item["profile_applied_device_count"] = (
            matched_device_count if item["collector_status"] == "active" else 0
        )
        item["blocked_device_count"] = (
            matched_device_count
            if item["collector_status"] in {"blocked_unverified", "blocked_failed"}
            else 0
        )
    return sorted(
        items,
        key=lambda item: (
            str(item.get("vendor") or "").casefold(),
            str(item.get("model") or "").casefold(),
            str(item.get("template_name") or "").casefold(),
        ),
    )


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
    proves that the OIDs work on one device; this report proves which devices
    have explicitly selected the profile.  Vendor/model similarity is shown
    only as inventory context and never grants collection coverage.
    """
    row = conn.execute("SELECT * FROM snmp_metric_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        raise ValueError("Model metric profile not found")
    vendor_key = str(_row_value(row, "vendor_key", ""))
    model_key = str(_row_value(row, "model_key", ""))
    device_columns = _table_columns(conn, "devices")
    explicit_binding_schema = "snmp_metric_profile_id" in device_columns
    if explicit_binding_schema:
        device_rows = conn.execute(
            """
            SELECT id, hostname, ip_address, vendor, platform, model, status,
                   snmp_metric_profile_id
            FROM devices
            WHERE snmp_metric_profile_id = ?
            ORDER BY CASE WHEN LOWER(TRIM(COALESCE(status, ''))) = 'online' THEN 0 ELSE 1 END,
                     CASE WHEN COALESCE(TRIM(ip_address), '') <> '' THEN 0 ELSE 1 END,
                     hostname, id
            """,
            (profile_id,),
        ).fetchall()
        inventory_rows = conn.execute(
            """
            SELECT id, vendor, platform, model, snmp_metric_profile_id
            FROM devices
            WHERE LOWER(TRIM(COALESCE(model, ''))) = LOWER(TRIM(?))
            """,
            (_row_value(row, "model_name", ""),),
        ).fetchall()
    else:
        device_rows = conn.execute(
            """
            SELECT id, hostname, ip_address, vendor, platform, model, status,
                   snmp_cpu_oid, snmp_memory_oid
            FROM devices
            WHERE LOWER(TRIM(COALESCE(model, ''))) = LOWER(TRIM(?))
            ORDER BY CASE WHEN LOWER(TRIM(COALESCE(status, ''))) = 'online' THEN 0 ELSE 1 END,
                     CASE WHEN COALESCE(TRIM(ip_address), '') <> '' THEN 0 ELSE 1 END,
                     hostname, id
            """,
            (_row_value(row, "model_name", ""),),
        ).fetchall()
        inventory_rows = device_rows
    metric_definitions = _profile_metric_definitions(row)
    interface_config = _profile_interface_config(row)

    matching: list[dict[str, Any]] = []
    same_model_other_vendor = 0
    for raw_device in inventory_rows:
        device = dict(raw_device)
        if normalize_vendor_key(device.get("vendor"), device.get("platform")) != vendor_key:
            same_model_other_vendor += 1

    for raw_device in device_rows:
        device = dict(raw_device)
        if not explicit_binding_schema:
            if normalize_model_key(device.get("model")) != model_key:
                continue
            if normalize_vendor_key(device.get("vendor"), device.get("platform")) != vendor_key:
                continue
        matching.append({
            "device_id": str(device.get("id") or ""),
            "hostname": str(device.get("hostname") or device.get("ip_address") or device.get("id") or ""),
            "ip_address": str(device.get("ip_address") or ""),
            "status": str(device.get("status") or "unknown"),
            "vendor": str(device.get("vendor") or ""),
            "model": str(device.get("model") or ""),
            "profile_id": profile_id,
            "cpu_source": "snmp_template" if "cpu" in metric_definitions else "template_not_applied",
            "memory_source": "snmp_template" if "memory" in metric_definitions else "template_not_applied",
        })

    status = str(_row_value(row, "verification_status", "unverified") or "unverified")
    interface_status = str(_row_value(row, "interface_verification_status", "unverified") or "unverified")
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
        collector_status = 'template_required'
    return {
        "profile_id": profile_id,
        "vendor": str(_row_value(row, "vendor_name", "")),
        "model": str(_row_value(row, "model_name", "")),
        "template_name": str(_row_value(row, "template_name", "") or ""),
        "source": str(_row_value(row, "source", "custom") or "custom"),
        "official_preset_id": str(_row_value(row, "official_preset_id", "") or ""),
        "verification_status": status,
        "collector_status": collector_status,
        "hardware_collector_status": hardware_collector_status,
        "interface_verification_status": interface_status,
        "interface_collector_status": interface_collector_status,
        "interface_configured": interface_configured,
        "interface_config": interface_config,
        "matched_device_count": len(matching),
        "bound_device_count": len(matching),
        "inventory_device_count": len(inventory_rows),
        "unbound_device_count": sum(
            1 for raw_device in inventory_rows
            if not explicit_binding_schema
            or not str(_row_value(raw_device, "snmp_metric_profile_id", "") or "").strip()
        ),
        "profile_applied_device_count": len(matching) if collector_status == "active" else 0,
        "blocked_device_count": len(matching) if collector_status in {"blocked_unverified", "blocked_failed"} else 0,
        "cpu_device_override_count": 0,
        "memory_device_override_count": 0,
        "metric_keys": sorted(metric_definitions),
        "same_model_other_vendor_count": same_model_other_vendor,
        "sample_device_id": matching[0]["device_id"] if matching else None,
        "sample_device_status": matching[0]["status"] if matching else None,
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


def _normalized_binding_ids(device_ids: Any) -> list[str]:
    if isinstance(device_ids, str):
        raw_ids = [device_ids]
    elif isinstance(device_ids, (list, tuple, set, frozenset)):
        raw_ids = list(device_ids)
    else:
        raise ValueError("device_ids must be a non-empty list")
    normalized: list[str] = []
    for raw_id in raw_ids:
        device_id = _clean_text(raw_id, 128)
        if device_id and device_id not in normalized:
            normalized.append(device_id)
    if not normalized:
        raise ValueError("at least one device_id is required")
    return normalized


def list_model_metric_profile_devices(conn, profile_id: str) -> list[dict[str, Any]]:
    """Return only safe inventory fields for devices bound to a template."""
    normalized_profile_id = _clean_text(profile_id, 128)
    if not conn.execute(
        "SELECT id FROM snmp_metric_profiles WHERE id = ?",
        (normalized_profile_id,),
    ).fetchone():
        raise ValueError("Model metric profile not found")
    rows = conn.execute(
        """
        SELECT id, hostname, ip_address, vendor, platform, model, status,
               snmp_metric_profile_id
        FROM devices
        WHERE snmp_metric_profile_id = ?
        ORDER BY CASE WHEN LOWER(TRIM(COALESCE(status, ''))) = 'online' THEN 0 ELSE 1 END,
                 CASE WHEN COALESCE(TRIM(ip_address), '') <> '' THEN 0 ELSE 1 END,
                 COALESCE(hostname, ''), id
        """,
        (normalized_profile_id,),
    ).fetchall()
    return [
        {
            "device_id": str(_row_value(row, "id", "") or ""),
            "hostname": str(_row_value(row, "hostname", "") or ""),
            "ip_address": str(_row_value(row, "ip_address", "") or ""),
            "vendor": str(_row_value(row, "vendor", "") or ""),
            "platform": str(_row_value(row, "platform", "") or ""),
            "model": str(_row_value(row, "model", "") or ""),
            "status": str(_row_value(row, "status", "unknown") or "unknown"),
            "profile_id": normalized_profile_id,
        }
        for row in rows
    ]


def bind_model_metric_profile(
    conn,
    profile_id: str,
    device_ids: Any,
) -> dict[str, Any]:
    """Bind a template to explicit devices, replacing their prior choice."""
    normalized_profile_id = _clean_text(profile_id, 128)
    profile_row = conn.execute(
        "SELECT * FROM snmp_metric_profiles WHERE id = ?",
        (normalized_profile_id,),
    ).fetchone()
    if not profile_row:
        raise ValueError("Model metric profile not found")
    normalized_device_ids = _normalized_binding_ids(device_ids)
    placeholders = ", ".join("?" for _ in normalized_device_ids)
    rows = conn.execute(
        f"SELECT id FROM devices WHERE id IN ({placeholders})",
        tuple(normalized_device_ids),
    ).fetchall()
    found_ids = {str(_row_value(row, "id", "") or "") for row in rows}
    missing_ids = [device_id for device_id in normalized_device_ids if device_id not in found_ids]
    if missing_ids:
        raise ValueError(f"Device not found: {', '.join(missing_ids[:5])}")
    conn.execute(
        f"UPDATE devices SET snmp_metric_profile_id = ? WHERE id IN ({placeholders})",
        (normalized_profile_id, *normalized_device_ids),
    )
    invalidate_metric_profile_cache()
    devices = list_model_metric_profile_devices(conn, normalized_profile_id)
    result = _profile_to_dict(profile_row)
    result.update(
        {
            "bound_device_count": len(devices),
            "device_count": len(devices),
            "devices": devices,
        }
    )
    return result


def unbind_model_metric_profile(
    conn,
    profile_id: str,
    device_ids: Any,
) -> dict[str, Any]:
    """Remove a template choice from explicit devices without deleting them."""
    normalized_profile_id = _clean_text(profile_id, 128)
    profile_row = conn.execute(
        "SELECT * FROM snmp_metric_profiles WHERE id = ?",
        (normalized_profile_id,),
    ).fetchone()
    if not profile_row:
        raise ValueError("Model metric profile not found")
    normalized_device_ids = _normalized_binding_ids(device_ids)
    placeholders = ", ".join("?" for _ in normalized_device_ids)
    rows = conn.execute(
        f"SELECT id, snmp_metric_profile_id FROM devices WHERE id IN ({placeholders})",
        tuple(normalized_device_ids),
    ).fetchall()
    by_id = {str(_row_value(row, "id", "") or ""): str(_row_value(row, "snmp_metric_profile_id", "") or "") for row in rows}
    missing_ids = [device_id for device_id in normalized_device_ids if device_id not in by_id]
    if missing_ids:
        raise ValueError(f"Device not found: {', '.join(missing_ids[:5])}")
    not_bound = [device_id for device_id in normalized_device_ids if by_id.get(device_id) != normalized_profile_id]
    if not_bound:
        raise ValueError(f"Device is not bound to this template: {', '.join(not_bound[:5])}")
    conn.execute(
        f"UPDATE devices SET snmp_metric_profile_id = '' WHERE id IN ({placeholders})",
        tuple(normalized_device_ids),
    )
    invalidate_metric_profile_cache()
    devices = list_model_metric_profile_devices(conn, normalized_profile_id)
    result = _profile_to_dict(profile_row)
    result.update(
        {
            "bound_device_count": len(devices),
            "device_count": len(devices),
            "devices": devices,
        }
    )
    return result


def create_model_metric_profile(
    conn,
    payload: Mapping[str, Any],
    updated_by: str = "",
    *,
    source: str = "custom",
    official_preset_id: str = "",
) -> dict[str, Any]:
    vendor, model, vendor_key, model_key = _profile_identity(conn, payload)
    interface_config = _validated_interface_values(payload)
    metric_definitions = _validated_profile_values(payload, allow_empty=bool(interface_config))
    if not metric_definitions and not interface_config:
        raise ValueError("at least one hardware metric or an interface OID definition is required")
    cpu_config = metric_definitions.get("cpu", {})
    memory_config = metric_definitions.get("memory", {})
    normalized_source = _clean_text(source, 32).casefold() or "custom"
    if normalized_source not in {"official", "custom", "legacy"}:
        normalized_source = "custom"
    template_name = _clean_text(
        payload.get("template_name")
        if payload.get("template_name") is not None
        else " / ".join(part for part in (vendor, model) if part),
        160,
    )

    now = _utc_now()
    profile_id = f"snmp-profile-{uuid.uuid4().hex[:12]}"
    profile_columns = _table_columns(conn, "snmp_metric_profiles")
    if {"template_name", "source", "official_preset_id"}.issubset(profile_columns):
        conn.execute(
            """
            INSERT INTO snmp_metric_profiles
                (id, vendor_key, vendor_name, model_key, model_name,
                 cpu_oid, memory_oid, cpu_config_json, memory_config_json,
                 metric_definitions_json, interface_config_json,
                 created_at, updated_at, updated_by, template_name, source,
                 official_preset_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                template_name,
                normalized_source,
                _clean_text(official_preset_id, 160),
            ),
        )
    else:
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


def apply_official_model_preset(conn, preset_id: str, updated_by: str = "") -> dict[str, Any]:
    """Materialize one official preset as the model profile used by devices.

    Official presets are kept in the read-only catalog until an operator
    explicitly applies one. Applying a preset makes the existing
    ``snmp_metric_profiles`` resolver the single source of truth for the
    device list and collectors. Verification remains visible as quality
    metadata; it never switches collection to another OID source.
    """
    normalized_preset_id = str(preset_id or "").strip()
    if not normalized_preset_id:
        raise ValueError("preset_id is required")

    # Import lazily to keep the metric-profile service independent from the
    # MIB catalog during application startup and test isolation.
    from services.snmp_preset_service import list_preset_profiles

    preset = next(
        (item for item in list_preset_profiles() if str(item.get("id") or "") == normalized_preset_id),
        None,
    )
    if not preset:
        raise ValueError("Official SNMP preset not found")
    if preset.get("testable") is False or not preset.get("metric_definitions"):
        raise ValueError("This official SNMP preset must be verified before it can be applied")

    payload = {
        "vendor": preset.get("vendor"),
        "model": preset.get("model"),
        "metric_definitions": preset.get("metric_definitions") or {},
        "interface_config": preset.get("interface_config") or {},
    }
    vendor, model, vendor_key, model_key = _profile_identity(conn, payload)
    profile_columns = _table_columns(conn, "snmp_metric_profiles")
    if {"official_preset_id", "source"}.issubset(profile_columns):
        existing = conn.execute(
            """
            SELECT * FROM snmp_metric_profiles
            WHERE official_preset_id = ? AND LOWER(COALESCE(source, '')) = 'official'
            ORDER BY updated_at DESC, id
            LIMIT 1
            """,
            (normalized_preset_id,),
        ).fetchone()
    else:
        # Pre-m0181 isolated databases had one row per vendor/model.  The
        # application migration removes that uniqueness before this path is
        # used in production; this branch only keeps old service fixtures
        # readable during an upgrade window.
        existing = conn.execute(
            "SELECT * FROM snmp_metric_profiles WHERE vendor_key = ? AND model_key = ?",
            (vendor_key, model_key),
        ).fetchone()
    if existing:
        payload = {
            **payload,
            "template_name": _row_value(existing, "template_name", "")
            or " / ".join(part for part in (vendor, model) if part),
        }
        profile = update_model_metric_profile(
            conn,
            str(_row_value(existing, "id", "")),
            payload,
            updated_by,
            allow_official=True,
        )
        applied_mode = "updated"
    else:
        profile = create_model_metric_profile(
            conn,
            payload,
            updated_by,
            source="official",
            official_preset_id=normalized_preset_id,
        )
        applied_mode = "created"

    profile["applied_preset_id"] = normalized_preset_id
    profile["applied_preset_family_id"] = str(preset.get("family_id") or "")
    profile["applied_mode"] = applied_mode
    profile["source"] = "official" if {"official_preset_id", "source"}.issubset(profile_columns) else "official_preset"
    return profile


def update_model_metric_profile(
    conn,
    profile_id: str,
    payload: Mapping[str, Any],
    updated_by: str = "",
    *,
    allow_official: bool = False,
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM snmp_metric_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        raise ValueError("Model metric profile not found")
    current_source = str(_row_value(row, "source", "custom") or "custom").casefold()
    if current_source == "official" and not allow_official:
        raise ValueError("Official templates are read-only; clone the template before editing")
    vendor, model, vendor_key, model_key = _profile_identity(conn, payload, row)
    interface_config = _validated_interface_values(payload)
    metric_definitions = _validated_profile_values(payload, allow_empty=bool(interface_config))
    if not metric_definitions and not interface_config:
        raise ValueError("at least one hardware metric or an interface OID definition is required")
    cpu_config = metric_definitions.get("cpu", {})
    memory_config = metric_definitions.get("memory", {})
    template_name = _clean_text(
        payload.get("template_name")
        if payload.get("template_name") is not None
        else _row_value(row, "template_name", "")
        or " / ".join(part for part in (vendor, model) if part),
        160,
    )
    official_preset_id = str(_row_value(row, "official_preset_id", "") or "")

    now = _utc_now()
    profile_columns = _table_columns(conn, "snmp_metric_profiles")
    if {"template_name", "source", "official_preset_id"}.issubset(profile_columns):
        conn.execute(
            """
            UPDATE snmp_metric_profiles
            SET vendor_key = ?, vendor_name = ?, model_key = ?, model_name = ?,
                cpu_oid = ?, memory_oid = ?, cpu_config_json = ?, memory_config_json = ?,
                metric_definitions_json = ?, interface_config_json = ?,
                template_name = ?, source = ?, official_preset_id = ?,
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
                template_name,
                current_source,
                official_preset_id,
                now,
                updated_by,
                profile_id,
            ),
        )
    else:
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
    if "snmp_metric_profile_id" in _table_columns(conn, "devices"):
        binding = conn.execute(
            "SELECT COUNT(*) AS count FROM devices WHERE snmp_metric_profile_id = ?",
            (profile_id,),
        ).fetchone()
        if int(_row_value(binding, "count", 0) or 0) > 0:
            raise ValueError("Template is still bound to devices; unbind it before deleting")
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
    "apply_official_model_preset",
    "bind_model_metric_profile",
    "create_model_metric_profile",
    "delete_model_metric_profile",
    "get_model_metric_profile_mapping",
    "get_alert_metric_collection",
    "invalidate_metric_profile_cache",
    "list_model_metric_profiles",
    "list_model_metric_profiles_page",
    "list_model_metric_profile_devices",
    "list_alert_metric_collections",
    "mark_model_metric_profile_test",
    "metric_config_hash",
    "normalize_metric_config",
    "normalize_interface_config",
    "normalize_model_key",
    "normalize_vendor_key",
    "normalize_vendor_name",
    "unbind_model_metric_profile",
    "profile_metric_config",
    "profile_metric_definitions",
    "validate_metric_definitions",
    "profile_interface_config",
    "resolve_metric_oids",
    "resolve_health_metric_profiles",
    "resolve_metric_profiles",
    "update_model_metric_profile",
]
