"""Role- and capability-aware collection plans.

The scheduler owns timing, while this module owns *whether* a collector is
allowed to run for a device.  Keeping that decision in one place prevents
ARP/MAC/LLDP/routing jobs from growing their own incompatible role rules.
"""

from __future__ import annotations

import json
from typing import Any


COLLECTORS = (
    "reachability",
    "health_metrics",
    "interface_status",
    "interface_ip",
    "lldp",
    "arp",
    "mac_table",
    "vlan",
    "routes",
    "bgp",
    "ospf",
    "eigrp",
    "isis",
    "rip",
    "bfd",
    "endpoint_location",
    "prefix_projection",
)

_NETWORK_ROLES = {
    "router",
    "gateway",
    "core",
    "dist",
    "distribution",
    "aggregation",
    "l3switch",
    "switch",
    "access",
    "firewall",
    "load-balancer",
    "ap",
    "wlc",
}
_SERVER_ROLES = {"server", "host", "vm", "virtual-machine", "hypervisor", "storage"}
_SERVER_PLATFORMS = {"linux", "ubuntu", "centos", "debian", "redhat", "windows", "vmware", "esxi"}


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"enabled", "enable", "true", "yes", "on", "1"}:
            return True
        if normalized in {"disabled", "disable", "false", "no", "off", "0"}:
            return False
    return None


def parse_collection_policy(value: Any) -> dict[str, Any]:
    """Decode the nullable JSON policy stored on a device."""
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _role(device: dict[str, Any]) -> str:
    return str(device.get("role") or "").strip().lower()


def _platform(device: dict[str, Any]) -> str:
    return str(device.get("platform") or "").strip().lower()


def _is_server(device: dict[str, Any]) -> bool:
    return _role(device) in _SERVER_ROLES or _platform(device) in _SERVER_PLATFORMS


def _default_plan(device: dict[str, Any]) -> dict[str, bool]:
    """Return the lightweight default plan used for ordinary device inventory.

    The default scheduler run is intentionally limited to reachability,
    health, interface state, and interface IPs.  Topology, L2 tables, route
    tables, and routing protocols are opt-in per device through
    ``collection_policy_json``.
    """
    if _is_server(device):
        return {
            "reachability": True,
            "health_metrics": True,
            "interface_status": True,
            "interface_ip": False,
            "lldp": False,
            "arp": False,
            "mac_table": False,
            "vlan": False,
            "routes": False,
            "bgp": False,
            "ospf": False,
            "eigrp": False,
            "isis": False,
            "rip": False,
            "bfd": False,
            "endpoint_location": False,
            "prefix_projection": False,
        }

    return {
        collector: collector in {"reachability", "health_metrics", "interface_status", "interface_ip"}
        for collector in COLLECTORS
    }


def resolve_collection_plan(device: dict[str, Any]) -> dict[str, Any]:
    """Resolve defaults plus explicit per-device overrides.

    Policy values are booleans or ``enabled``/``disabled`` strings. Unknown
    keys are ignored but returned in ``ignored_overrides`` for transparency.
    """
    defaults = _default_plan(device)
    policy = parse_collection_policy(device.get("collection_policy_json"))
    overrides = policy.get("collectors") if isinstance(policy.get("collectors"), dict) else policy
    ignored: list[str] = []
    effective = dict(defaults)
    applied: dict[str, bool] = {}
    for key, value in overrides.items():
        if key not in COLLECTORS:
            ignored.append(str(key))
            continue
        parsed = _as_bool(value)
        if parsed is None:
            ignored.append(str(key))
            continue
        effective[key] = parsed
        applied[key] = parsed

    return {
        "profile": "server" if _is_server(device) else (_role(device) or "network-default"),
        "role": _role(device),
        "platform": _platform(device),
        "defaults": defaults,
        "overrides": applied,
        "effective": effective,
        "ignored_overrides": ignored,
    }


def should_collect(device: dict[str, Any], collector: str) -> bool:
    """Return whether a named collector is enabled for the device."""
    return bool(resolve_collection_plan(device)["effective"].get(collector, False))


def explicit_collector_override(device: dict[str, Any], collector: str) -> bool | None:
    """Return an explicit per-device override, or ``None`` when absent.

    This lets protocol discovery use a safe middle ground: discovered OSPF
    can trigger neighbor collection by default, while an operator's explicit
    ``ospf: false`` remains a hard stop.
    """
    policy = parse_collection_policy(device.get("collection_policy_json"))
    overrides = policy.get("collectors") if isinstance(policy.get("collectors"), dict) else policy
    if collector not in overrides:
        return None
    return _as_bool(overrides.get(collector))


def filter_devices(devices: list[dict[str, Any]], collector: str) -> list[dict[str, Any]]:
    return [device for device in devices if should_collect(device, collector)]


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize an API policy payload without touching secrets."""
    if not isinstance(policy, dict):
        raise ValueError("collection policy must be an object")
    raw = policy.get("collectors", policy)
    if not isinstance(raw, dict):
        raise ValueError("collectors must be an object")
    normalized: dict[str, bool] = {}
    unknown: list[str] = []
    for key, value in raw.items():
        if key not in COLLECTORS:
            unknown.append(str(key))
            continue
        parsed = _as_bool(value)
        if parsed is None:
            raise ValueError(f"collector '{key}' must be enabled/disabled or boolean")
        normalized[key] = parsed
    return {"collectors": normalized, "ignored_keys": unknown}


def collection_catalog() -> list[dict[str, Any]]:
    return [
        {"key": "reachability", "name_zh": "可达性", "transport": "icmp/tcp", "default_interval": "15s"},
        {"key": "health_metrics", "name_zh": "设备健康指标", "transport": "snmp", "default_interval": "1m"},
        {"key": "interface_status", "name_zh": "接口状态与流量", "transport": "snmp", "default_interval": "1m"},
        {"key": "interface_ip", "name_zh": "接口 IP/Loopback", "transport": "ssh/playbook", "default_interval": "24h"},
        {"key": "lldp", "name_zh": "LLDP 邻居", "transport": "ssh/playbook", "default_interval": "24h full reconcile"},
        {"key": "arp", "name_zh": "ARP 表", "transport": "ssh", "default_interval": "10m; bounded batches"},
        {"key": "mac_table", "name_zh": "MAC 地址表", "transport": "ssh", "default_interval": "5m"},
        {"key": "vlan", "name_zh": "VLAN", "transport": "ssh", "default_interval": "5m"},
        {"key": "routes", "name_zh": "路由表", "transport": "ssh", "default_interval": "5m"},
        {"key": "bgp", "name_zh": "BGP", "transport": "ssh", "default_interval": "5m when enabled"},
        {"key": "ospf", "name_zh": "OSPF", "transport": "ssh", "default_interval": "5m when enabled"},
        {"key": "eigrp", "name_zh": "EIGRP", "transport": "ssh", "default_interval": "5m when enabled"},
        {"key": "isis", "name_zh": "IS-IS", "transport": "ssh", "default_interval": "5m when enabled"},
        {"key": "rip", "name_zh": "RIP", "transport": "ssh", "default_interval": "5m when enabled"},
        {"key": "bfd", "name_zh": "BFD", "transport": "ssh", "default_interval": "5m"},
        {"key": "endpoint_location", "name_zh": "终端定位", "transport": "database", "default_interval": "5m"},
        {"key": "prefix_projection", "name_zh": "Prefix 投影", "transport": "database", "default_interval": "event"},
    ]
