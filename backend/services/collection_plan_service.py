"""Role- and capability-aware collection plans.

The scheduler owns timing, while this module owns *whether* a collector is
allowed to run for a device.  Keeping that decision in one place prevents
ARP/MAC/LLDP/routing jobs from growing their own incompatible role rules.
"""

from __future__ import annotations

import hashlib
import ipaddress
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
_ROUTING_ROLES = {
    "router",
    "gateway",
    "core",
    "dist",
    "distribution",
    "aggregation",
    "l3switch",
}
_ROUTE_TABLE_ROLES = _ROUTING_ROLES | {"firewall", "load-balancer"}
_ARP_L3_ROLES = {
    "router",
    "gateway",
    "core",
    "distribution",
    "l3switch",
    "firewall",
    "load-balancer",
}
_ARP_SVI_ROLES = {"access", "switch", "distribution", "l3switch"}

_ROLE_ALIASES = {
    "core switch": "core",
    "aggregation": "distribution",
    "aggregation switch": "distribution",
    "dist": "distribution",
    "distribution switch": "distribution",
    "access switch": "access",
    "layer 3 switch": "l3switch",
    "l3 switch": "l3switch",
    "wireless ac": "wlc",
    "wireless controller": "wlc",
    "wireless lan controller": "wlc",
    "wireless ap": "ap",
    "access point": "ap",
    "load balancer": "load-balancer",
    "loadbalancer": "load-balancer",
    "virtual machine": "virtual-machine",
}

_TEMPLATE_NAMES = {
    "role_default": ("按角色默认", "Role default"),
    "basic": ("基础监控", "Basic monitoring"),
    "layer2_switch": ("二层交换机", "Layer 2 switch"),
    "layer3_gateway": ("三层/网关设备", "Layer 3 / gateway"),
    "firewall": ("防火墙", "Firewall"),
    "wireless": ("无线设备", "Wireless device"),
    "custom": ("自定义", "Custom"),
}

_BASIC_COLLECTORS = {
    "reachability",
    "health_metrics",
    "interface_status",
    "interface_ip",
}
_TEMPLATE_COLLECTORS = {
    "basic": frozenset(_BASIC_COLLECTORS),
    "layer2_switch": frozenset(
        _BASIC_COLLECTORS | {"lldp", "mac_table", "vlan", "endpoint_location"}
    ),
    "layer3_gateway": frozenset(_BASIC_COLLECTORS | {"lldp", "arp", "routes"}),
    # LLDP is permitted for firewalls; platform/command support is decided by
    # the collector, not inferred from the device role.
    "firewall": frozenset(_BASIC_COLLECTORS | {"lldp", "arp", "routes"}),
    # Generic discovery only. Wireless client/radio telemetry is not implied.
    "wireless": frozenset(_BASIC_COLLECTORS | {"lldp"}),
}

# These are the operator-facing NSOT collection dimensions.  Database-derived
# projections are intentionally excluded from the template editor and command
# catalog because they are not independent CLI collection operations.
NSOT_TEMPLATE_COLLECTORS = frozenset(
    set(COLLECTORS) - {"reachability", "health_metrics", "endpoint_location", "prefix_projection"}
)

_BULK_PRESET_TEMPLATES = frozenset(
    {"basic", "layer2_switch", "layer3_gateway", "firewall", "wireless"}
)
_BULK_CATEGORY_SQL = (
    "COALESCE(NULLIF(BTRIM(device_category), ''), "
    "CASE WHEN POSITION('server' IN LOWER(BTRIM(COALESCE(role, '')))) > 0 "
    "THEN 'Server' ELSE 'Network' END)"
)
_DEVICE_SITE_VALUE_SQL = (
    "COALESCE(NULLIF(BTRIM(d.site), ''), NULLIF(BTRIM(d.site_id), ''))"
)
_DEVICE_SITE_LABEL_SQL = (
    "COALESCE(NULLIF(BTRIM(matched_site.site_name), ''), "
    "NULLIF(BTRIM(matched_site.site_code), ''), "
    "CASE WHEN COALESCE(NULLIF(BTRIM(d.site), ''), NULLIF(BTRIM(d.site_id), '')) "
    "~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
    "THEN '未分配站点' ELSE COALESCE(NULLIF(BTRIM(d.site), ''), "
    "NULLIF(BTRIM(d.site_id), '')) END, '未分配站点')"
)
_DEVICE_SITE_JOIN_SQL = """
    LEFT JOIN LATERAL (
        SELECT s.site_name, s.site_code
          FROM sites s
         WHERE s.id = NULLIF(BTRIM(d.site_id), '')
            OR s.id = COALESCE(NULLIF(BTRIM(d.site), ''), NULLIF(BTRIM(d.site_id), ''))
            OR s.site_code = COALESCE(NULLIF(BTRIM(d.site), ''), NULLIF(BTRIM(d.site_id), ''))
            OR s.site_name = COALESCE(NULLIF(BTRIM(d.site), ''), NULLIF(BTRIM(d.site_id), ''))
         ORDER BY CASE WHEN s.id = NULLIF(BTRIM(d.site_id), '') THEN 0 ELSE 1 END,
                  CASE WHEN s.id = COALESCE(NULLIF(BTRIM(d.site), ''), NULLIF(BTRIM(d.site_id), '')) THEN 0
                       WHEN s.site_code = COALESCE(NULLIF(BTRIM(d.site), ''), NULLIF(BTRIM(d.site_id), '')) THEN 1
                       ELSE 2 END
         LIMIT 1
    ) matched_site ON TRUE
"""
_BULK_FILTER_SQL = {
    "site": _DEVICE_SITE_VALUE_SQL,
    "role": "d.role",
    "category": _BULK_CATEGORY_SQL,
    "platform": "d.platform",
}
_BULK_OPTION_SQL = {
    "site": _DEVICE_SITE_VALUE_SQL,
    "role": "d.role",
    "category": _BULK_CATEGORY_SQL,
    "platform": "d.platform",
}
_BULK_OPTION_RESPONSE_KEYS = {
    "site": "sites",
    "role": "roles",
    "category": "categories",
    "platform": "platforms",
}


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


def normalize_device_role(value: Any) -> str:
    """Normalize role labels without inferring platform or device capability."""
    value = str(value or "").strip().lower()
    normalized = " ".join(value.replace("_", " ").replace("-", " ").split())
    return _ROLE_ALIASES.get(normalized, normalized.replace(" ", "-"))


def _role(device: dict[str, Any]) -> str:
    return normalize_device_role(device.get("role"))


def _platform(device: dict[str, Any]) -> str:
    return str(device.get("platform") or "").strip().lower()


def _is_server(device: dict[str, Any]) -> bool:
    return _role(device) in _SERVER_ROLES or _platform(device) in _SERVER_PLATFORMS


def _default_plan(device: dict[str, Any]) -> dict[str, bool]:
    """Return the lightweight default plan used for ordinary device inventory.

    The default scheduler run is intentionally limited to reachability,
    health, interface state, and interface IPs.  L3 routing roles also collect
    ARP, the main route table, and BGP state by default because BGP may be
    configured without installing a BGP route into the main RIB. ARP is also
    enabled for SVI-bearing switch roles when the caller supplies ``_has_svi``.
    Other topology, L2 tables, and dynamic routing protocols remain opt-in through
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

    plan = {
        collector: (
            collector in _BASIC_COLLECTORS
            or (
                collector == "arp"
                and (
                    _role(device) in _ARP_L3_ROLES
                    or (_role(device) in _ARP_SVI_ROLES and bool(device.get("_has_svi")))
                )
            )
            or (collector == "routes" and _role(device) in _ROUTE_TABLE_ROLES)
            or (collector == "bgp" and _role(device) in _ROUTING_ROLES)
        )
        for collector in COLLECTORS
    }
    if plan["interface_ip"]:
        plan["prefix_projection"] = True
    return plan


def _policy_template(policy: dict[str, Any]) -> str:
    template = policy.get("template")
    return template if isinstance(template, str) and template in _TEMPLATE_NAMES else "role_default"


def _policy_overrides(policy: dict[str, Any]) -> dict[str, Any]:
    """Return only stored per-device overrides, excluding policy metadata."""
    if "collectors" in policy:
        collectors = policy.get("collectors")
        return collectors if isinstance(collectors, dict) else {}
    if "template" in policy:
        return {}
    # Backward compatibility for older records that stored a bare collector map.
    return policy


def _template_defaults(template_id: str, device: dict[str, Any]) -> dict[str, bool]:
    if template_id in {"role_default", "custom"}:
        return _default_plan(device)
    enabled = _TEMPLATE_COLLECTORS[template_id]
    defaults = {collector: collector in enabled for collector in COLLECTORS}
    if not _is_server(device) and defaults["interface_ip"]:
        defaults["prefix_projection"] = True
    return defaults


def resolve_collection_plan(device: dict[str, Any]) -> dict[str, Any]:
    """Resolve defaults plus explicit per-device overrides.

    Policy values are booleans or ``enabled``/``disabled`` strings. Unknown
    keys are ignored but returned in ``ignored_overrides`` for transparency.
    """
    policy = parse_collection_policy(device.get("collection_policy_json"))
    template_id = _policy_template(policy)
    defaults = _template_defaults(template_id, device)
    overrides = _policy_overrides(policy)
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
        "template_id": template_id,
        "template_name_zh": _TEMPLATE_NAMES[template_id][0],
        "template_name_en": _TEMPLATE_NAMES[template_id][1],
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
    overrides = _policy_overrides(policy)
    if collector not in overrides:
        return None
    return _as_bool(overrides.get(collector))


def filter_devices(devices: list[dict[str, Any]], collector: str) -> list[dict[str, Any]]:
    return [device for device in devices if should_collect(device, collector)]


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize an API policy payload without touching secrets."""
    if not isinstance(policy, dict):
        raise ValueError("collection policy must be an object")
    template = policy.get("template")
    if "template" in policy and (
        not isinstance(template, str) or template not in _TEMPLATE_NAMES
    ):
        raise ValueError(f"unknown collection template '{template}'")

    raw = policy.get("collectors", policy)
    if not isinstance(raw, dict):
        raise ValueError("collectors must be an object")
    if "template" in policy and "collectors" not in policy:
        raw = {}
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
    monitoring = policy.get("monitoring", policy.get("monitoring_modules"))
    normalized_monitoring = None
    if monitoring is not None:
        if isinstance(monitoring, dict):
            monitoring = [monitoring]
        if not isinstance(monitoring, list):
            raise ValueError("monitoring must be an array of module assignments")
        normalized_monitoring = []
        for entry in monitoring:
            if not isinstance(entry, dict):
                raise ValueError("monitoring entries must be objects")
            forbidden = {"community", "password", "priv_password", "auth_password", "credential"} & {str(key).lower() for key in entry}
            if forbidden:
                raise ValueError("monitoring entries cannot contain credentials")
            normalized_monitoring.append(dict(entry))
    result = {"template": template, "collectors": normalized, "ignored_keys": unknown}
    if normalized_monitoring is not None:
        result["monitoring"] = normalized_monitoring
    return result


def collection_templates(conn=None) -> list[dict[str, Any]]:
    """Expose built-in templates plus persisted operator-created templates.

    Runtime collection planning still treats the built-in identifiers as the
    stable policy presets.  The optional connection is used by the operation
    catalog and template-management APIs to include persisted custom entries.
    """
    builtins = [
        {
            "id": template_id,
            "name_zh": names[0],
            "name_en": names[1],
            "description_zh": "",
            "description_en": "",
            "collector_keys": sorted(_TEMPLATE_COLLECTORS.get(template_id, ())),
            "builtin": True,
            "editable": False,
            "deletable": False,
        }
        for template_id, names in _TEMPLATE_NAMES.items()
    ]
    if conn is None:
        return builtins

    try:
        rows = conn.execute(
            """SELECT id, name_zh, name_en, description_zh, description_en,
                      collector_keys, builtin, created_by, created_at, updated_at
                 FROM nsot_collection_templates
                ORDER BY builtin DESC, updated_at, id"""
        ).fetchall()
    except Exception:
        # Keep the catalog usable during a rolling deployment before migration
        # 0231 has been applied to every application database.
        return builtins

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            keys = json.loads(item.get("collector_keys") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            keys = []
        item["collector_keys"] = [
            str(key) for key in keys
            if str(key) in NSOT_TEMPLATE_COLLECTORS
        ] if isinstance(keys, list) else []
        item["builtin"] = bool(item.get("builtin"))
        # Persisted system and operator-created templates share the same
        # management lifecycle. The migration-missing fallback above remains
        # read-only during rolling deployments.
        item["editable"] = True
        item["deletable"] = True
        result.append(item)
    # An existing but empty table means templates were intentionally removed;
    # do not silently resurrect the built-in catalog in that case.
    return result


def validate_nsot_template_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize the editable fields for a persisted NSOT template."""
    if not isinstance(payload, dict):
        raise ValueError("template payload must be an object")
    name_zh = str(payload.get("name_zh") or "").strip()
    name_en = str(payload.get("name_en") or "").strip()
    if not name_zh or not name_en:
        raise ValueError("name_zh and name_en are required")
    if len(name_zh) > 128 or len(name_en) > 128:
        raise ValueError("template names must be 128 characters or fewer")
    raw_keys = payload.get("collector_keys")
    if not isinstance(raw_keys, list):
        raise ValueError("collector_keys must be an array")
    collector_keys = list(dict.fromkeys(str(key).strip() for key in raw_keys if str(key).strip()))
    invalid = sorted(set(collector_keys) - NSOT_TEMPLATE_COLLECTORS)
    if invalid:
        raise ValueError(f"unsupported collector keys: {', '.join(invalid)}")
    return {
        "name_zh": name_zh,
        "name_en": name_en,
        "description_zh": str(payload.get("description_zh") or "").strip()[:500],
        "description_en": str(payload.get("description_en") or "").strip()[:500],
        "collector_keys": collector_keys,
    }


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


class BulkSnapshotConflict(ValueError):
    """Raised when a bulk apply no longer matches its preview snapshot."""


def normalize_bulk_filters(filters: Any) -> dict[str, str]:
    """Validate bulk-scope fields while retaining exact option values."""
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")
    unknown = set(filters) - set(_BULK_FILTER_SQL)
    if unknown:
        raise ValueError("unsupported bulk filter")

    normalized: dict[str, str] = {}
    for key, value in filters.items():
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"filter '{key}' must be a string")
        if value.strip():
            normalized[key] = value.strip()
    if not normalized:
        raise ValueError("at least one non-empty filter is required")
    return normalized


def _bulk_where(filters: dict[str, str]) -> tuple[str, tuple[str, ...]]:
    clauses = [f"{_BULK_FILTER_SQL[key]} = ?" for key in filters]
    return " AND ".join(clauses), tuple(filters.values())


def _bulk_scope_clauses(
    *,
    tenant_id: str | None,
    site_ids: tuple[str, ...] | None,
    table_alias: str = "",
) -> tuple[list[str], tuple[str, ...]]:
    clauses: list[str] = []
    params: list[str] = []
    prefix = f"{table_alias}." if table_alias else ""
    if tenant_id:
        clauses.append(f"{prefix}tenant_id = ?")
        params.append(tenant_id)
    if site_ids is not None:
        normalized_site_ids = tuple(sorted({str(site_id) for site_id in site_ids if str(site_id)}))
        if normalized_site_ids:
            clauses.append(f"{prefix}site_id IN ({','.join('?' for _ in normalized_site_ids)})")
            params.extend(normalized_site_ids)
        else:
            clauses.append("1 = 0")
    return clauses, tuple(params)


def _bulk_snapshot_token(
    filters: dict[str, str],
    rows: list[dict[str, Any]],
    *,
    operation: str,
    template_id: str | None,
    tenant_id: str | None,
    site_ids: tuple[str, ...] | None,
) -> str:
    # Keep the exact previous database value in the hash input so even a
    # malformed legacy JSON value changing between preview and apply is stale.
    snapshot = {
        "filters": {key: filters[key] for key in sorted(filters)},
        "operation": operation,
        "template_id": template_id if operation == "apply" else "role_default",
        "tenant_id": tenant_id,
        "site_ids": None if site_ids is None else sorted(set(site_ids)),
        "devices": [
            {"id": str(row.get("id") or ""), "policy": row.get("collection_policy_json")}
            for row in sorted(rows, key=lambda item: str(item.get("id") or ""))
        ],
    }
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bulk_target_rows(
    conn: Any,
    filters: dict[str, str],
    *,
    tenant_id: str | None = None,
    site_ids: tuple[str, ...] | None = None,
    lock: bool = False,
) -> list[dict[str, Any]]:
    filter_clauses, filter_params = _bulk_where(filters)
    scope_clauses, scope_params = _bulk_scope_clauses(
        tenant_id=tenant_id, site_ids=site_ids, table_alias="d"
    )
    where_clause = " AND ".join([filter_clauses, *scope_clauses])
    params = (*filter_params, *scope_params)
    lock_clause = " FOR UPDATE" if lock else ""
    rows = conn.execute(
        "SELECT d.id, d.hostname, d.ip_address, d.role, d.site, d.site_id, d.platform, "
        f"{_BULK_CATEGORY_SQL} AS category, collection_policy_json "
        "FROM devices d WHERE " + where_clause + " ORDER BY COALESCE(d.hostname, ''), d.id" + lock_clause,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _has_device_collector_overrides(device: dict[str, Any]) -> bool:
    policy = parse_collection_policy(device.get("collection_policy_json"))
    collectors = policy.get("collectors")
    if isinstance(collectors, dict):
        return bool(collectors)
    # Legacy policies stored the collector map directly at the top level.
    return "template" not in policy and bool(policy)


def bulk_collection_plan_options(
    conn: Any,
    *,
    tenant_id: str | None = None,
    site_ids: tuple[str, ...] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return value/count pairs for the small set of supported bulk filters."""
    options: dict[str, list[dict[str, Any]]] = {}
    scope_clauses, scope_params = _bulk_scope_clauses(
        tenant_id=tenant_id, site_ids=site_ids, table_alias="d"
    )
    for key, expression in _BULK_OPTION_SQL.items():
        if key == "site":
            query = (
                "SELECT scoped.value, MIN(scoped.label) AS label, COUNT(*) AS count "
                "FROM (SELECT " + _DEVICE_SITE_VALUE_SQL + " AS value, "
                + _DEVICE_SITE_LABEL_SQL + " AS label FROM devices d "
                + _DEVICE_SITE_JOIN_SQL
                + (" WHERE " + " AND ".join(scope_clauses) if scope_clauses else "")
                + ") scoped WHERE scoped.value IS NOT NULL AND BTRIM(scoped.value) <> '' "
                "GROUP BY scoped.value ORDER BY MIN(scoped.label), scoped.value"
            )
            rows = conn.execute(query, scope_params).fetchall()
            options["sites"] = [
                {"value": row["value"], "label": row["label"], "count": int(row["count"])}
                for row in rows
            ]
            continue
        conditions = [
            f"{expression} IS NOT NULL",
            f"BTRIM({expression}) <> ''",
            *scope_clauses,
        ]
        query = (
            f"SELECT {expression} AS value, COUNT(*) AS count FROM devices d "
            "WHERE " + " AND ".join(conditions) + " "
            f"GROUP BY {expression} ORDER BY value"
        )
        rows = conn.execute(query, scope_params).fetchall()
        options[_BULK_OPTION_RESPONSE_KEYS[key]] = [
            {"value": row["value"], "count": int(row["count"])}
            for row in rows
        ]
    return options


class MultipleDevicesForIPAddress(ValueError):
    """Raised when the requested IP is assigned to multiple visible devices."""


def normalize_device_ip(value: Any) -> str:
    """Validate and canonicalize one IPv4 or IPv6 address."""
    try:
        return str(ipaddress.ip_address(str(value or "").strip()))
    except ValueError as exc:
        raise ValueError("ip must be a valid IPv4 or IPv6 address") from exc


def collection_plan_for_ip(
    conn: Any,
    ip: str,
    *,
    tenant_id: str | None = None,
    site_ids: tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    """Find a single visible device by normalized IP and resolve its plan."""
    raw_ip = str(ip or "").strip()
    normalized_ip = normalize_device_ip(raw_ip)
    scope_clauses, scope_params = _bulk_scope_clauses(
        tenant_id=tenant_id, site_ids=site_ids, table_alias="d"
    )

    def _query_matches(ip_predicate: str, ip_params: tuple[str, ...]):
        where = [ip_predicate, *scope_clauses]
        return conn.execute(
            "SELECT d.id, d.hostname, d.ip_address, d.platform, d.role, d.site, d.site_id, "
            "d.device_category, d.status, " + _DEVICE_SITE_LABEL_SQL + " AS site_label, "
            "d.collection_policy_json FROM devices d " + _DEVICE_SITE_JOIN_SQL
            + " WHERE " + " AND ".join(where)
            + " ORDER BY d.id LIMIT 2",
            (*ip_params, *scope_params),
        ).fetchall()

    # Keep the common path indexable. The raw and canonical forms cover normal
    # user input and stored canonical IPs.
    rows = _query_matches("d.ip_address IN (?, ?)", (raw_ip, normalized_ip))
    if ipaddress.ip_address(normalized_ip).version == 6:
        # PostgreSQL 18 is the supported database baseline. This guarded cast
        # tolerates malformed historical text values. Always check IPv6's
        # canonical inet form, even after an exact-text hit, so equivalent
        # compressed/expanded addresses cannot hide an ambiguous device match.
        canonical_rows = _query_matches(
            "CASE WHEN pg_input_is_valid(BTRIM(d.ip_address), 'inet') "
            "THEN HOST(BTRIM(d.ip_address)::inet) = ? ELSE FALSE END",
            (normalized_ip,),
        )
        # Merge because the canonical query also includes any exact-text row.
        rows_by_id = {str(row["id"]): row for row in (*rows, *canonical_rows)}
        rows = list(rows_by_id.values())[:2]
    if len(rows) > 1:
        raise MultipleDevicesForIPAddress("multiple devices use this IP address")
    if not rows:
        return None

    device = dict(rows[0])
    return {
        "device": {
            "id": device.get("id"),
            "hostname": device.get("hostname") or device.get("ip_address") or "",
            "ip_address": device.get("ip_address") or normalized_ip,
            "platform": device.get("platform") or "",
            "role": device.get("role") or "",
            "site": device.get("site") or "",
            "site_id": device.get("site_id") or "",
            "site_label": device.get("site_label") or "未分配站点",
            "category": device.get("device_category") or "",
            "status": device.get("status") or "",
        },
        "plan": resolve_collection_plan(device),
    }


def preview_bulk_collection_plan(
    conn: Any,
    *,
    operation: str,
    template_id: str | None,
    filters: Any,
    tenant_id: str | None = None,
    site_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Preview a filtered collection-plan update without writing any rows."""
    if operation not in {"apply", "reset"}:
        raise ValueError("operation must be 'apply' or 'reset'")
    if operation == "apply" and template_id not in _BULK_PRESET_TEMPLATES:
        raise ValueError("template_id must be an assignable preset template")
    normalized_filters = normalize_bulk_filters(filters)
    rows = _bulk_target_rows(conn, normalized_filters, tenant_id=tenant_id, site_ids=site_ids)
    sample = []
    for row in rows[:10]:
        sample.append(
            {
                "device_id": row.get("id"),
                "hostname": row.get("hostname") or row.get("ip_address") or "",
                "ip_address": row.get("ip_address") or "",
                "role": row.get("role") or "",
                "site": row.get("site") or "",
                "platform": row.get("platform") or "",
                "current_template": resolve_collection_plan(row)["template_id"],
            }
        )
    return {
        "matched_count": len(rows),
        "overridden_count": sum(_has_device_collector_overrides(row) for row in rows),
        "sample": sample,
        "snapshot_token": _bulk_snapshot_token(
            normalized_filters,
            rows,
            operation=operation,
            template_id=template_id,
            tenant_id=tenant_id,
            site_ids=site_ids,
        ),
        "operation": operation,
        "template_id": template_id if operation == "apply" else "role_default",
    }


def apply_bulk_collection_plan(
    conn: Any,
    *,
    operation: str,
    template_id: str | None,
    filters: Any,
    snapshot_token: str,
    tenant_id: str | None = None,
    site_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Atomically update all currently matching devices after snapshot validation."""
    if operation not in {"apply", "reset"}:
        raise ValueError("operation must be 'apply' or 'reset'")
    if operation == "apply" and template_id not in _BULK_PRESET_TEMPLATES:
        raise ValueError("template_id must be an assignable preset template")
    if not isinstance(snapshot_token, str) or not snapshot_token:
        raise ValueError("snapshot_token is required")
    normalized_filters = normalize_bulk_filters(filters)

    try:
        # Lock the current target set while rechecking and updating it. A row
        # that changed its filter fields or policy after preview will either be
        # absent from this set or expose its current policy here.
        rows = _bulk_target_rows(
            conn,
            normalized_filters,
            tenant_id=tenant_id,
            site_ids=site_ids,
            lock=True,
        )
        current_token = _bulk_snapshot_token(
            normalized_filters,
            rows,
            operation=operation,
            template_id=template_id,
            tenant_id=tenant_id,
            site_ids=site_ids,
        )
        if current_token != snapshot_token:
            conn.rollback()
            raise BulkSnapshotConflict("bulk preview is stale; create a new preview")

        target_template = template_id if operation == "apply" else "role_default"
        stored_policy = json.dumps(
            {"template": target_template, "collectors": {}},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        target_ids = [str(row["id"]) for row in rows if row.get("id")]
        affected_count = 0
        if target_ids:
            # One parameterized PostgreSQL array update keeps large device-group
            # operations within a single atomic statement/transaction.
            result = conn.execute(
                "UPDATE devices SET collection_policy_json = ? WHERE id = ANY(?)",
                (stored_policy, target_ids),
            )
            affected_count = int(result.rowcount)
            if affected_count != len(target_ids):
                conn.rollback()
                raise BulkSnapshotConflict("bulk target changed; create a new preview")
        conn.commit()
        return {
            "affected_count": affected_count,
            "operation": operation,
            "template_id": target_template,
        }
    except BulkSnapshotConflict:
        raise
    except Exception:
        conn.rollback()
        raise
