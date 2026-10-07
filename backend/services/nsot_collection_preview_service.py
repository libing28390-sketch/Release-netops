"""Read-only catalog and preview for scheduled NSOT collection operations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from services.collection_plan_service import (
    collection_templates,
    resolve_collection_plan,
)
from services.platform_registry_service import is_safe_read_command


class NSOTPreviewPermissionError(PermissionError):
    """The caller has no asset:view permission for this preview."""


# These are the categories actually reached by run_unified_nsot_sync. The
# separate reachability and SNMP health samplers are not scheduled by NSOT.
_OPERATION_SPECS: tuple[dict[str, Any], ...] = (
    {"collector_key": "interface_status", "quick_ops_category": "interfaces", "label": "接口状态", "transport": "cli", "category": "interfaces", "action_code": "get_interface_brief"},
    {"collector_key": "interface_status", "quick_ops_category": "interface_description", "label": "接口描述", "transport": "cli", "category": "interface_description", "action_code": "get_interface_description"},
    {"collector_key": "interface_ip", "quick_ops_category": "interfaces", "label": "接口详情", "transport": "cli", "category": "interfaces", "action_code": "get_interfaces"},
    {"collector_key": "interface_ip", "quick_ops_category": "interfaces", "label": "接口 IP", "transport": "cli", "category": "interfaces", "action_code": "get_ip_interfaces"},
    {"collector_key": "lldp", "quick_ops_category": "neighbors", "label": "LLDP 邻居", "transport": "cli", "category": "neighbors", "action_code": "get_lldp_neighbors"},
    {"collector_key": "arp", "quick_ops_category": "arp", "label": "ARP 表", "transport": "cli", "category": "arp", "action_code": "get_arp_table"},
    {"collector_key": "mac_table", "quick_ops_category": "mac_table", "label": "MAC 地址表", "transport": "cli", "category": "mac_table", "action_code": "get_mac_table"},
    {"collector_key": "vlan", "quick_ops_category": "vlan", "label": "VLAN", "transport": "cli", "category": "vlan", "action_code": "get_vlan_table"},
    {"collector_key": "routes", "quick_ops_category": "routing_table", "label": "路由表", "transport": "cli", "category": "routing_table", "action_code": "get_route_table"},
    {"collector_key": "bgp", "quick_ops_category": "bgp", "label": "BGP 邻居", "transport": "cli", "category": "bgp", "action_code": "get_bgp_neighbors"},
    {"collector_key": "bgp", "quick_ops_category": "bgp", "label": "BGP 路由", "transport": "cli", "category": "bgp_routes", "action_code": "get_bgp_routes"},
    {"collector_key": "ospf", "quick_ops_category": "ospf", "label": "OSPF 邻居", "transport": "cli", "category": "ospf", "action_code": "get_ospf_neighbors"},
    {"collector_key": "isis", "quick_ops_category": "isis", "label": "IS-IS 邻居", "transport": "cli", "category": "isis", "action_code": "get_isis_neighbors"},
    {"collector_key": "endpoint_location", "quick_ops_category": None, "label": "终端定位", "transport": "database", "category": None, "action_code": None},
    {"collector_key": "prefix_projection", "quick_ops_category": None, "label": "Prefix 投影", "transport": "database", "category": None, "action_code": None},
)

_COLLECTOR_LABELS = {
    "interface_status": "接口状态与流量",
    "interface_ip": "接口 IP/Loopback",
    "lldp": "LLDP 邻居",
    "arp": "ARP 表",
    "mac_table": "MAC 地址表",
    "vlan": "VLAN",
    "routes": "路由表",
    "bgp": "BGP",
    "ospf": "OSPF",
    "isis": "IS-IS",
    "endpoint_location": "终端定位",
    "prefix_projection": "Prefix 投影",
}

_NSOT_POLICY_COLLECTORS = tuple(_COLLECTOR_LABELS)
_DYNAMIC_PROTOCOLS = ("bgp", "ospf", "isis")


def _asset_view_scope(conn, user: dict[str, Any]):
    from services.rack_scope_service import allowed_resource_scope
    from core.rbac import resource_action_allowed

    if not isinstance(user, dict) or not resource_action_allowed(user, "asset", "view"):
        raise NSOTPreviewPermissionError("Insufficient permission for the device scope")
    scope = allowed_resource_scope(conn, user, "asset", "view")
    if user.get("role") != "Administrator" and not str(user.get("tenant_id") or "").strip():
        raise NSOTPreviewPermissionError("Authenticated user is not assigned to a tenant")
    if scope.site_ids == ():
        raise NSOTPreviewPermissionError("Insufficient permission for the device scope")
    return scope


def _device_rows_in_scope(conn, target_ids: list[str], scope) -> list[dict[str, Any]]:
    if not target_ids:
        return []
    # Keep parameter lists bounded while preserving PostgreSQL compatibility.
    rows_by_id: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(target_ids), 500):
        chunk = target_ids[offset:offset + 500]
        clauses = [f"d.id IN ({','.join('?' for _ in chunk)})", "d.status = 'online'"]
        params: list[Any] = list(chunk)
        if scope.site_ids is not None:
            if not scope.site_ids:
                return []
            clauses.append(
                f"COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, '')) IN ({','.join('?' for _ in scope.site_ids)})"
            )
            params.extend(scope.site_ids)
        if scope.tenant_id:
            clauses.append("COALESCE(NULLIF(d.tenant_id, ''), s.tenant_id) = ?")
            params.append(scope.tenant_id)
        rows = conn.execute(
            """SELECT d.*, p.platform_code AS profile_platform_code,
                      p.name_zh AS profile_name_zh, p.name_en AS profile_name_en,
                      p.parser_platform AS profile_parser_platform,
                      p.connection_driver AS profile_connection_driver,
                      r.id AS profile_release_id,
                      r.release_number AS profile_release_number,
                      r.status AS profile_release_status,
                      s.tenant_id AS site_tenant_id
                 FROM devices d
                 LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                 LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
                 LEFT JOIN platform_profiles p ON p.id = d.platform_profile_id
                 LEFT JOIN platform_releases r
                   ON r.id = p.current_release_id AND r.status = 'PUBLISHED'
                WHERE """ + " AND ".join(clauses),
            tuple(params),
        ).fetchall()
        for row in rows:
            device = dict(row)
            rows_by_id[str(device.get("id") or "")] = device
    return [rows_by_id[item] for item in target_ids if item in rows_by_id]


def _profile_action_map(conn, release_id: str | None) -> dict[str, str]:
    if not release_id:
        return {}
    rows = conn.execute(
        "SELECT action_code, command FROM platform_release_actions WHERE release_id = ?",
        (release_id,),
    ).fetchall()
    return {
        str(row["action_code"]): str(row["command"])
        for row in rows
        if row["action_code"] and row["command"]
    }


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    registry_release_number = profile.get("current_release_number") or profile.get("profile_release_number")
    return {
        "id": str(profile.get("id") or ""),
        "platform_code": str(profile.get("platform_code") or ""),
        "name_zh": str(profile.get("name_zh") or profile.get("platform_code") or ""),
        "name_en": str(profile.get("name_en") or profile.get("platform_code") or ""),
        "vendor": str(profile.get("vendor") or ""),
        "parser_platform": str(profile.get("parser_platform") or ""),
        # Distinguish the Registry publication number from a device's actual
        # software version while keeping the compatibility key for consumers.
        "release_number": registry_release_number,
        "registry_release_number": registry_release_number,
        "release_status": profile.get("current_release_status") or profile.get("profile_release_status"),
    }


def _operation_command(
    conn,
    device: dict[str, Any],
    spec: dict[str, Any],
    *,
    templates_catalog: list[dict[str, Any]],
    action_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    from services.operational_data_service import (
        COMMAND_CATALOG,
        _normalize_platform,
        _resolve_commands,
        resolve_device_platform_context,
        resolve_textfsm_operation_fallback,
    )

    action_code = spec.get("action_code")
    category = spec.get("category")
    if not category:
        return {
            "action_code": action_code,
            "action_bound": False,
            "status": "projection",
            "commands": [],
            "condition": None,
        }
    profile_bound = bool(device.get("platform_profile_id"))
    release_id = str(device.get("profile_release_id") or "")
    release_is_published = str(device.get("profile_release_status") or device.get("current_release_status") or "").upper() == "PUBLISHED"
    actions = (
        action_map if action_map is not None
        else _profile_action_map(conn, release_id) if profile_bound and release_is_published
        else {}
    )
    context = resolve_device_platform_context(device)

    if profile_bound and action_code and action_code in actions:
        command = str(actions[action_code] or "").strip()
        if not is_safe_read_command(command, str(context.get("connection_driver") or "")):
            return {
                "action_code": action_code,
                "action_bound": True,
                "status": "unsupported",
                "commands": [],
                "condition": "当前发布 action command 未通过只读命令校验",
            }
        from services.operational_data_service import resolve_textfsm_template_for_command

        parser_binding = resolve_textfsm_template_for_command(
            device,
            command,
            action_code=str(action_code),
            templates_catalog=templates_catalog,
        )
        return {
            "action_code": action_code,
            "action_bound": True,
            "status": "supported" if parser_binding else "parser_missing",
            "commands": [{
                "action_code": action_code,
                "command": command,
                "command_source": "platform_registry",
                "textfsm_template": parser_binding.get("textfsm_template") if parser_binding else None,
                "textfsm_source": parser_binding.get("textfsm_source") if parser_binding else None,
                "status": "supported" if parser_binding else "parser_missing",
                "condition": None if parser_binding else "已发布 action 存在，但当前 parser platform/version 没有匹配 TextFSM 模板，实际结果可能为原始文本或无法解析",
            }],
            "condition": None if parser_binding else "命令已发布，但解析模板未匹配",
        }

    if profile_bound:
        fallback = resolve_textfsm_operation_fallback(
            device,
            operational_category=str(category or ""),
            action_code=str(action_code) if action_code else None,
            templates_catalog=templates_catalog,
        )
        commands = [
            {
                "action_code": item.get("action_code"),
                "command": item.get("command"),
                "command_source": item.get("command_source"),
                "textfsm_template": item.get("textfsm_template"),
                "textfsm_source": item.get("textfsm_source"),
                "status": item.get("status") or "supported",
                "condition": item.get("condition"),
            }
            for item in (fallback.get("commands") or [])
        ]
        return {
            "action_code": action_code,
            "action_bound": False,
            "status": fallback.get("status") or "unsupported",
            "commands": commands,
            "condition": fallback.get("condition"),
        }

    # Unbound devices keep the production category resolver and its command
    # catalog behavior. This path is not a Registry-missing-action fallback.
    commands_by_category = _resolve_commands(
        str(context.get("catalog_platform") or device.get("platform") or ""),
        [str(category)],
    )
    resolved = commands_by_category.get(str(category), [])
    safe = [
        command for command in resolved
        if is_safe_read_command(str(command), str(context.get("connection_driver") or ""))
    ]
    from services.operational_data_service import resolve_textfsm_template_for_command

    commands = []
    for command in safe:
        parser_binding = resolve_textfsm_template_for_command(
            device,
            command,
            action_code=str(action_code) if action_code else None,
            operational_category=str(category),
            templates_catalog=templates_catalog,
        )
        commands.append({
            "action_code": action_code,
            "command": command,
            "command_source": "legacy_catalog",
            "textfsm_template": parser_binding.get("textfsm_template") if parser_binding else None,
            "textfsm_source": parser_binding.get("textfsm_source") if parser_binding else None,
            "status": "supported" if parser_binding else "parser_missing",
            "condition": None if parser_binding else "命令来自兼容平台目录，但当前 software version 未找到精确 TextFSM 模板",
        })
    return {
        "action_code": action_code,
        "action_bound": False,
        "status": "supported" if any(item["status"] == "supported" for item in commands) else "unsupported" if not commands else "parser_missing",
        "commands": commands,
        "condition": None if commands and any(item["status"] == "supported" for item in commands) else "当前平台/软件版本没有可精确关联的安全命令和解析模板",
    }


def _template_ids_for_collector(
    template_id: str,
    collector_key: str,
    role: str,
    platform: str,
    template: dict[str, Any] | None = None,
) -> bool:
    if template is not None and not bool(template.get("builtin")) and template_id not in {"role_default", "custom"}:
        return collector_key in {
            str(key) for key in (template.get("collector_keys") or [])
        }
    if template_id in {"role_default", "custom"}:
        # These templates can vary by role/SVI evidence and explicit overrides;
        # the catalog presents the possible operation and labels it dynamic.
        return True
    policy = json.dumps({"template": template_id, "collectors": {}}, ensure_ascii=False)
    plan = resolve_collection_plan({
        "platform": platform,
        "role": role,
        "collection_policy_json": policy,
    })
    return bool(plan["effective"].get(collector_key, False))


_TEMPLATE_DESCRIPTIONS = {
    "role_default": "按设备角色、SVI 事实和设备级覆盖动态决定；此页列出该平台可能用到的采集操作。",
    "basic": "基础接口状态和接口 IP 事实。",
    "layer2_switch": "接口与拓扑、MAC/VLAN 和终端定位事实。",
    "layer3_gateway": "接口、LLDP、ARP 与路由事实。",
    "firewall": "基础接口、LLDP、ARP 与适用的路由事实。",
    "wireless": "基础接口与 LLDP 事实；当前不包含无线客户端/射频专用指标。",
    "custom": "以角色默认值为起点，并应用设备单项覆盖；操作范围依设备策略动态变化。",
}


def _operation_template_catalog(
    role: str,
    platform: str,
    templates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for template in templates or collection_templates():
        template_id = str(template.get("id") or "")
        dynamic = template_id in {"role_default", "custom"}
        persisted_keys = {
            str(key) for key in (template.get("collector_keys") or [])
            if str(key) in _NSOT_POLICY_COLLECTORS
        }
        collector_keys = (
            sorted(persisted_keys)
            if not dynamic and not bool(template.get("builtin"))
            else [
                key for key in _NSOT_POLICY_COLLECTORS
                if dynamic or _template_ids_for_collector(template_id, key, role, platform)
            ]
        )
        description = (
            template.get("description_zh")
            or template.get("description_en")
            or _TEMPLATE_DESCRIPTIONS.get(template_id, "")
        )
        catalog.append({
            **template,
            "description_zh": description,
            "description_en": description,
            "collector_keys": collector_keys,
            "condition": description if dynamic else None,
            "dynamic": dynamic,
        })
    return catalog


def build_operation_catalog(
    conn,
    user: dict[str, Any],
    *,
    platform_profile_id: str | None = None,
    role: str = "switch",
) -> dict[str, Any]:
    """Build the profile-aware Quick Ops operation catalog without device I/O."""
    scope = _asset_view_scope(conn, user)
    from services.platform_registry_service import list_profiles
    from core.textfsm import list_templates

    visible_profiles = list_profiles(user)
    profile_summaries = [_profile_summary(profile) for profile in visible_profiles]
    selected = None
    if platform_profile_id:
        selected = next(
            (item for item in visible_profiles if str(item.get("id") or "") == platform_profile_id),
            None,
        )
        if selected is None:
            raise HTTPException(status_code=404, detail="平台 Profile 不存在")
    catalog_profile = dict(selected or {})
    catalog_profile.setdefault("platform_profile_id", catalog_profile.get("id"))
    catalog_profile.setdefault("profile_platform_code", catalog_profile.get("platform_code"))
    catalog_profile.setdefault("profile_parser_platform", catalog_profile.get("parser_platform"))
    catalog_profile.setdefault("profile_connection_driver", catalog_profile.get("connection_driver"))
    catalog_profile.setdefault("platform", catalog_profile.get("platform_code"))
    catalog_profile.setdefault("profile_release_id", catalog_profile.get("current_release_id"))

    operations_by_collector: dict[str, dict[str, Any]] = {}
    template_catalog = _operation_template_catalog(
        role,
        str(catalog_profile.get("platform") or ""),
        templates=collection_templates(conn),
    )
    if selected:
        templates_catalog = list_templates()
        catalog_action_map = (
            _profile_action_map(conn, str(catalog_profile.get("profile_release_id") or ""))
            if str(catalog_profile.get("current_release_status") or "").upper() == "PUBLISHED"
            else {}
        )
        template_ids = [
            item["id"]
            for item in template_catalog
        ]
        template_by_id = {str(item["id"]): item for item in template_catalog}
        for spec in _OPERATION_SPECS:
            applicable = [
                template_id for template_id in template_ids
                if _template_ids_for_collector(
                    template_id,
                    str(spec["collector_key"]),
                    role,
                    str(catalog_profile.get("platform") or ""),
                    template=template_by_id.get(template_id),
                )
            ]
            resolved = _operation_command(
                conn,
                catalog_profile,
                spec,
                templates_catalog=templates_catalog,
                action_map=catalog_action_map,
            )
            collector_key = str(spec["collector_key"])
            operation = operations_by_collector.get(collector_key)
            if operation is None:
                operation = {
                    "collector_key": collector_key,
                    "quick_ops_category": spec["quick_ops_category"],
                    "quick_ops_categories": [],
                    "label": _COLLECTOR_LABELS.get(collector_key, spec["label"]),
                    "transport": spec["transport"],
                    "applicable_templates": [],
                    "action_code": resolved.get("action_code"),
                    "action_bound": False,
                    "status": "supported",
                    "_resolution_statuses": [],
                    "condition": None,
                    "commands": [],
                }
                operations_by_collector[collector_key] = operation
            quick_ops_category = spec.get("quick_ops_category")
            if quick_ops_category and quick_ops_category not in operation["quick_ops_categories"]:
                operation["quick_ops_categories"].append(quick_ops_category)
            for template_id in applicable:
                if template_id not in operation["applicable_templates"]:
                    operation["applicable_templates"].append(template_id)
            for command in resolved.get("commands") or []:
                if command not in operation["commands"]:
                    operation["commands"].append(command)
            operation["action_bound"] = operation["action_bound"] or bool(resolved.get("action_bound"))
            resolved_status = str(resolved.get("status") or "unsupported")
            operation["_resolution_statuses"].append(resolved_status)
            condition = resolved.get("condition")
            if condition:
                operation["condition"] = "; ".join(filter(None, [operation.get("condition"), str(condition)]))
        operations = list(operations_by_collector.values())
        for operation in operations:
            statuses = operation.pop("_resolution_statuses", [])
            if any(status == "supported" for status in statuses):
                operation["status"] = "supported"
            elif any(status == "parser_missing" for status in statuses):
                operation["status"] = "parser_missing"
            elif statuses and all(status == "projection" for status in statuses):
                operation["status"] = "projection"
            else:
                operation["status"] = "unsupported"
            if "role_default" in operation["applicable_templates"] or "custom" in operation["applicable_templates"]:
                operation["dynamic"] = True
                operation["condition"] = "; ".join(filter(None, [operation.get("condition"), "按设备角色、SVI 事实和显式 collector overrides 动态生效"]))
    else:
        # role_default/custom depend on per-device role, SVI evidence and
        # explicit overrides. Return the template/profile catalog without
        # pretending one static operation set applies to every device.
        operations = []
        seen_collectors: set[str] = set()
        for spec in _OPERATION_SPECS:
            collector_key = str(spec["collector_key"])
            if collector_key in seen_collectors:
                continue
            seen_collectors.add(collector_key)
            operations.append({
                "collector_key": collector_key,
                "quick_ops_category": spec["quick_ops_category"],
                "quick_ops_categories": list(dict.fromkeys(
                    str(item.get("quick_ops_category") or "")
                    for item in _collector_specs_for_key(collector_key)
                    if item.get("quick_ops_category")
                )),
                "label": _COLLECTOR_LABELS.get(collector_key, spec["label"]),
                "transport": spec["transport"],
                "applicable_templates": ["role_default", "custom"],
                "action_code": spec["action_code"],
                "action_bound": False,
                "status": "dynamic",
                "condition": "请按设备角色、SVI/运行时证据及设备覆盖项解析有效 collector",
                "commands": [],
                "dynamic": True,
            })

    return {
        "templates": _operation_template_catalog(
            role,
            str((selected or {}).get("platform_code") or ""),
            templates=template_catalog,
        ),
        "profiles": profile_summaries,
        "selected_profile": _profile_summary(selected) if selected else None,
        "operations": operations,
    }


def _collector_specs_for_key(key: str) -> list[dict[str, Any]]:
    return [spec for spec in _OPERATION_SPECS if spec["collector_key"] == key]


def _active_nsot_collectors(device: dict[str, Any], plan: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    effective = plan.get("effective") or {}
    active: list[str] = []
    conditions: dict[str, str] = {}
    for key in _NSOT_POLICY_COLLECTORS:
        if not effective.get(key):
            continue
        if key == "mac_table" and not effective.get("endpoint_location"):
            continue
        if key == "endpoint_location" and not effective.get("mac_table"):
            continue
        active.append(key)
    if effective.get("routes"):
        from services.collection_plan_service import explicit_collector_override

        for protocol in _DYNAMIC_PROTOCOLS:
            if effective.get(protocol):
                continue
            if explicit_collector_override(device, protocol) is False:
                continue
            if explicit_collector_override(device, protocol) is None:
                active.append(protocol)
                conditions[protocol] = "仅当当前路由表证据发现该协议且未显式关闭时才会采集"
    return active, conditions


def build_nsot_collection_preview(conn, job: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Build an aggregate, permission-scoped preview for one NSOT job."""
    from services.scheduler_service import _resolve_nsot_target_device_ids
    from services.collection_plan_service import collection_templates
    from core.textfsm import list_templates

    scope = _asset_view_scope(conn, user)
    target_ids = _resolve_nsot_target_device_ids(job, conn)
    devices = _device_rows_in_scope(conn, target_ids, scope)
    if not devices:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target_count": 0,
            "groups": [],
        }

    templates_catalog = list_templates()
    template_names = {item["id"]: item["name_zh"] for item in collection_templates()}
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    action_cache: dict[str, dict[str, str]] = {}
    operation_cache: dict[tuple[str, ...], dict[str, Any]] = {}
    for device in devices:
        plan = resolve_collection_plan(device)
        collector_keys, collector_conditions = _active_nsot_collectors(device, plan)
        profile_release_id = str(device.get("profile_release_id") or "")
        if profile_release_id not in action_cache:
            action_cache[profile_release_id] = _profile_action_map(conn, profile_release_id)
        collectors: list[dict[str, Any]] = []
        signature_collectors: list[tuple[Any, ...]] = []
        notes = [
            "只读预览，不连接设备；最终发送受在线状态、认证、平台能力、退避和运行时协议/VRF 发现影响。",
            "reachability 与 health_metrics 由独立基础遥测任务处理，不属于本 NSOT 定时作业。",
        ]
        for key in collector_keys:
            specs = _collector_specs_for_key(key)
            commands: list[dict[str, Any]] = []
            conditions: list[str] = []
            resolution_statuses: list[str] = []
            for spec in specs:
                cache_key = (
                    str(device.get("platform_profile_id") or ""),
                    str(spec.get("action_code") or ""),
                    str(spec.get("category") or ""),
                    str(profile_release_id),
                    str(device.get("platform") or "").strip().lower(),
                    str(device.get("vendor") or "").strip().lower(),
                    str(device.get("version") or device.get("software_version") or "").strip().lower(),
                    str(device.get("profile_parser_platform") or "").strip().lower(),
                )
                resolved = operation_cache.get(cache_key)
                if resolved is None:
                    # Resolve each operation through the same Registry/TextFSM
                    # path exposed by operation-catalog.
                    resolved = _operation_command(
                        conn,
                        device,
                        spec,
                        templates_catalog=templates_catalog,
                        action_map=(
                            action_cache[profile_release_id]
                            if device.get("platform_profile_id") and profile_release_id
                            else None
                        ),
                    )
                    operation_cache[cache_key] = resolved
                commands.extend(resolved.get("commands") or [])
                condition = resolved.get("condition")
                if condition:
                    conditions.append(str(condition))
                resolution_statuses.append(str(resolved.get("status") or "unsupported"))
            if key in collector_conditions:
                conditions.append(collector_conditions[key])
            if key == "routes":
                conditions.append("实际路由采集还要求设备角色/L3 证据、凭据及已启用策略")
            elif key in _DYNAMIC_PROTOCOLS:
                conditions.append("协议邻居采集会受当前路由表协议发现及设备能力影响")
            elif key == "arp":
                conditions.append("ARP 扫描受设备资格、凭据、重试退避和批次上限影响")
            elif key in {"interface_status", "interface_ip", "lldp", "mac_table", "vlan"}:
                conditions.append("设备能力、只读权限和连接状态可能改变实际命令")
            elif key in {"endpoint_location", "prefix_projection"}:
                conditions.append("数据库派生投影依赖本轮或已有 CLI 事实数据")

            # Compact duplicate command objects while retaining distinct action
            # codes and source metadata.
            unique_commands: list[dict[str, Any]] = []
            seen_commands: set[tuple[Any, ...]] = set()
            for command in commands:
                cmd_key = (
                    command.get("action_code"), command.get("command"),
                    command.get("command_source"), command.get("textfsm_template"),
                )
                if cmd_key not in seen_commands:
                    seen_commands.add(cmd_key)
                    unique_commands.append(command)
            if key in {"endpoint_location", "prefix_projection"}:
                collector_status = "projection"
            elif any(status == "supported" for status in resolution_statuses):
                collector_status = (
                    "partial"
                    if any(status in {"unsupported", "parser_missing"} for status in resolution_statuses)
                    else "supported"
                )
            elif any(status == "parser_missing" for status in resolution_statuses):
                collector_status = "parser_missing"
            else:
                collector_status = "unsupported"
            collector = {
                "key": key,
                "label": _COLLECTOR_LABELS.get(key, key),
                "transport": "database" if key in {"endpoint_location", "prefix_projection"} else "cli",
                "status": collector_status,
                "conditional": bool(conditions) or collector_status in {"partial", "parser_missing", "unsupported"},
                "commands": unique_commands,
            }
            collectors.append(collector)
            signature_collectors.append((
                key,
                collector["transport"],
                collector["conditional"],
                tuple((item.get("action_code"), item.get("command"), item.get("command_source"), item.get("textfsm_template")) for item in unique_commands),
            ))
            notes.extend(conditions)

        role = str(plan.get("role") or "")
        platform = str(device.get("platform") or "").strip().lower()
        profile_label = str(
            device.get("profile_name_zh") or device.get("profile_name_en") or ""
        ).strip()
        release_number = device.get("profile_release_number")
        group_key = (
            platform,
            profile_label,
            release_number,
            str(device.get("software_version") or device.get("version") or "").strip(),
            str(plan.get("template_id") or "role_default"),
            role,
            tuple(signature_collectors),
        )
        if group_key not in grouped:
            grouped[group_key] = {
                "platform": platform,
                "platform_label": profile_label or platform,
                "profile_label": profile_label or None,
                "release_number": release_number,
                "registry_release_number": release_number,
                "software_version": (
                    str(device.get("software_version") or device.get("version") or "").strip() or None
                ),
                "template_id": plan.get("template_id") or "role_default",
                "template_name": template_names.get(str(plan.get("template_id") or "role_default"), "按角色默认"),
                "role": role,
                "device_count": 0,
                "collectors": collectors,
                "notes": list(dict.fromkeys(notes)),
            }
        grouped[group_key]["device_count"] += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_count": len(devices),
        "groups": list(grouped.values()),
    }
