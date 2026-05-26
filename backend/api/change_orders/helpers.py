import os
import json
import uuid
import logging
import sys
from typing import Optional
from fastapi import HTTPException
from database import get_db_connection
from core.rbac import require_role

logger = logging.getLogger(__name__)

# ── Base Feature Flags ──────────────────────────────────────────────
_BASE_FEATURE_TEMPLATE_REQUIRED: bool = os.environ.get('FEATURE_TEMPLATE_REQUIRED', '0').strip() == '1'
_BASE_FEATURE_CONTROL_SHEET: bool = os.environ.get('FEATURE_CONTROL_SHEET', '0').strip() == '1'


def is_template_required() -> bool:
    """Dynamically resolve FEATURE_TEMPLATE_REQUIRED from package namespace for monkeypatching compatibility."""
    co_module = sys.modules.get('api.change_orders')
    if co_module and hasattr(co_module, 'FEATURE_TEMPLATE_REQUIRED'):
        return co_module.FEATURE_TEMPLATE_REQUIRED
    return _BASE_FEATURE_TEMPLATE_REQUIRED


def is_control_sheet_enabled() -> bool:
    """Dynamically resolve FEATURE_CONTROL_SHEET from package namespace for monkeypatching compatibility."""
    co_module = sys.modules.get('api.change_orders')
    if co_module and hasattr(co_module, 'FEATURE_CONTROL_SHEET'):
        return co_module.FEATURE_CONTROL_SHEET
    return _BASE_FEATURE_CONTROL_SHEET


ALLOWED_STATUSES = {
    'draft', 'initial_review', 'final_review', 'approved', 'implementing', 'completed',
    'rollback_in_progress', 'rolled_back', 'rejected', 'failed', 'cancelled',
    'pending', 'executing',
}

ALLOWED_TRANSITIONS = {
    'draft': {'initial_review', 'cancelled'},
    'initial_review': {'final_review', 'rejected', 'cancelled'},
    'final_review': {'approved', 'rejected', 'cancelled', 'initial_review'},
    'approved': {'implementing', 'cancelled'},
    'implementing': {'completed', 'failed', 'rollback_in_progress', 'cancelled'},
    'rollback_in_progress': {'rolled_back', 'failed'},
    'failed': {'rollback_in_progress', 'cancelled'},
    'rejected': {'draft', 'cancelled'},
    'completed': set(),
    'rolled_back': set(),
    'cancelled': set(),
    'pending': {'approved', 'rejected', 'cancelled'},
    'executing': {'completed', 'failed', 'rollback_in_progress', 'cancelled'},
}

assert ALLOWED_STATUSES <= ALLOWED_TRANSITIONS.keys(), (
    "ALLOWED_TRANSITIONS is missing keys for: "
    + str(ALLOWED_STATUSES - ALLOWED_TRANSITIONS.keys())
)

STATUS_ZH = {
    'draft': '草稿',
    'initial_review': '初审中',
    'final_review': '终审中',
    'approved': '审批完成',
    'implementing': '实施中',
    'completed': '完成',
    'rollback_in_progress': '回溯中',
    'rolled_back': '已回溯',
    'rejected': '已驳回',
    'failed': '执行失败',
    'cancelled': '已取消',
}

_TEMPLATE_REQUIRED_STATUSES = frozenset({
    'initial_review', 'final_review', 'approved', 'implementing', 'completed',
})


def _validate_assignment_rules(requester_username: str, payload: dict):
    rev_id = str(payload.get('assigned_initial_reviewer_id') or '').strip()
    rev_name = str(payload.get('assigned_initial_reviewer_username') or '').strip()
    app_id = str(payload.get('assigned_final_approver_id') or '').strip()
    app_name = str(payload.get('assigned_final_approver_username') or '').strip()

    if rev_name and rev_name == requester_username:
        raise HTTPException(status_code=400, detail='申请人不能作为指定的初审人')
    if app_name and app_name == requester_username:
        raise HTTPException(status_code=400, detail='申请人不能作为指定的终审人')
    if rev_id and rev_id == app_id:
        raise HTTPException(status_code=400, detail='初审人与终审人不能为同一人')


def _validate_template_completeness(payload: dict):
    status = payload.get('status')
    if status not in _TEMPLATE_REQUIRED_STATUSES:
        return

    tpl = payload.get('command_template') or {}
    if not tpl or tpl.get('mode') != 'template' or not str(tpl.get('scenario_id') or '').strip():
        raise HTTPException(
            status_code=400,
            detail='提交初审前必须选择场景化命令模板并渲染出可执行命令',
        )

    preview = tpl.get('preview') or {}
    if not preview.get('execute'):
        raise HTTPException(
            status_code=400,
            detail='提交初审前必须渲染出可执行命令',
        )


def _validate_control_sheet_completeness(conn, order_id: str, payload: dict, new_status: str):
    if new_status == 'initial_review':
        cs = payload.get('control_sheet') or {}
        required_fields = [
            'change_time', 'implementer', 'co_reviewer', 'device_ips',
            'pre_check', 'execution', 'post_verify', 'business_verify',
            'rollback_plan',
        ]
        missing = []
        for f in required_fields:
            val = cs.get(f)
            if val is None:
                missing.append(f)
            elif isinstance(val, (list,)) and not val:
                missing.append(f)
            elif isinstance(val, dict) and not val:
                missing.append(f)
            elif isinstance(val, str) and not val.strip():
                missing.append(f)
        if missing:
            raise HTTPException(status_code=400, detail=f'提交初审前必须填写完整的变更控制表，缺失字段: {", ".join(missing)}')

    if new_status == 'implementing':
        count = conn.execute(
            "SELECT COUNT(*) FROM change_order_control_sheet_attachments WHERE order_id = ?",
            (order_id,)
        ).fetchone()[0]
        if count == 0:
            raise HTTPException(status_code=400, detail='进入实施阶段前必须上传至少一个附件（变更控制表扫描件/截图）')


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _parse_change_groups(raw_value) -> set[str]:
    if isinstance(raw_value, str):
        try:
            raw_value = json.loads(raw_value or '[]')
        except Exception:
            raw_value = []
    if not isinstance(raw_value, (list, tuple, set)):
        return set()
    return {str(item or '').strip() for item in raw_value if str(item or '').strip()}


def _resolve_assignment_user(conn, user_id: str, stage: str) -> dict:
    row = conn.execute(
        'SELECT id, username, role, change_groups_json FROM users WHERE id = ?',
        (user_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail='Selected reviewer does not exist')

    user = dict(row)
    groups = _parse_change_groups(user.get('change_groups_json'))
    if stage == 'initial':
        if user.get('role') == 'Viewer':
            raise HTTPException(status_code=400, detail='Initial reviewer must be Operator or Administrator')
        if 'initial_reviewer' not in groups:
            raise HTTPException(status_code=400, detail='Selected user is not in the initial review group')
    if stage == 'final':
        if user.get('role') != 'Administrator':
            raise HTTPException(status_code=400, detail='Final approver must be an Administrator')
        if 'final_approver' not in groups:
            raise HTTPException(status_code=400, detail='Selected user is not in the final approval group')
    return {'id': str(user.get('id') or ''), 'username': str(user.get('username') or '')}


def _normalize_assignment_payload(conn, payload: dict) -> dict:
    normalized = dict(payload)
    assignment_fields = (
        ('assigned_initial_reviewer_id', 'assigned_initial_reviewer_username', 'initial'),
        ('assigned_final_approver_id', 'assigned_final_approver_username', 'final'),
    )
    for id_field, name_field, stage in assignment_fields:
        if id_field not in normalized and name_field not in normalized:
            continue

        assignee_id = str(normalized.get(id_field) or '').strip()
        if not assignee_id:
            normalized[id_field] = ''
            normalized[name_field] = ''
            continue

        assignee = _resolve_assignment_user(conn, assignee_id, stage)
        normalized[id_field] = assignee['id']
        normalized[name_field] = assignee['username']
    return normalized


def _load_actor_change_groups(conn, user_id: str) -> set[str]:
    if not user_id:
        return set()
    row = conn.execute('SELECT change_groups_json FROM users WHERE id = ?', (user_id,)).fetchone()
    if not row:
        return set()
    return _parse_change_groups(row['change_groups_json'])


def validate_variable_value(
    key: str,
    val: str,
    var_type: str = "text",
    platform: str = "",
    variables: dict = None
) -> Optional[str]:
    import re
    import ipaddress
    val_str = str(val).strip()
    if not val_str:
        return None

    is_acl_number = ("acl" in key.lower()) and ("name" not in key.lower())
    is_as_number = any(w == "as" for w in re.split(r'[^a-zA-Z0-9]', key.lower()))

    if is_as_number:
        if '.' in val_str:
            parts = val_str.split('.')
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                high, low = int(parts[0]), int(parts[1])
                if not (0 <= high <= 65535 and 0 <= low <= 65535 and not (high == 0 and low == 0)):
                    return f"AS 号 '{key}' ASdot 格式非法 (高低 16 位均需在 0-65535 之间且不能同时为 0)"
            else:
                return f"AS 号 '{key}' ASdot 格式非法 (应为 X.Y 格式)"
        else:
            if not re.match(r'^\d+$', val_str):
                return f"AS 号 '{key}' 必须是正整数或 ASdot 点分十进制格式"
            num = int(val_str)
            if num < 1 or num > 4294967295:
                return f"AS 号 '{key}' 必须在 1 到 4294967295 之间"
    
    number_indicators = ["vlan", "port", "key_size", "modulus", "process"]
    if (var_type == "number" or is_acl_number or any(k in key.lower() for k in number_indicators)) and not is_as_number:
        if not re.match(r'^\d+$', val_str):
            return f"变量 '{key}' 的值必须是正整数"
        num = int(val_str)
        if "vlan" in key.lower() and (num < 1 or num > 4094):
            return f"VLAN ID '{key}' 必须在 1 到 4094 之间"
        if "port" in key.lower() and (num < 1 or num > 65535):
            return f"端口号 '{key}' 必须在 1 到 65535 之间"
        if "process" in key.lower() and (num < 1 or num > 65535):
            return f"OSPF 进程 ID '{key}' 必须在 1 到 65535 之间"

        if is_acl_number:
            platform_lower = platform.lower() if platform else ""
            if "cisco" in platform_lower:
                if not ((1 <= num <= 199) or (1300 <= num <= 1999) or (2000 <= num <= 2699)):
                    return f"思科 ACL 编号 '{key}' 必须在 1-199 或 1300-1999 或 2000-2699 之间"
            elif "huawei" in platform_lower or "h3c" in platform_lower:
                if not (2000 <= num <= 6999):
                    return f"华为/H3C ACL 编号 '{key}' 必须在 2000-6999 之间"
            elif "arista" in platform_lower:
                if not (1 <= num <= 199):
                    return f"Arista ACL 编号 '{key}' 必须在 1-199 之间"

    if any(k in key.lower() for k in ["wildcard", "inverse_mask"]):
        octets = val_str.split('.')
        if len(octets) != 4 or not all(o.isdigit() and 0 <= int(o) <= 255 for o in octets):
            return f"反掩码 '{key}' 必须是合法的点分十进制格式 (如 0.0.0.255)"
    
    if ("mask" in key.lower()) and ("wildcard" not in key.lower()):
        try:
            if val_str.isdigit():
                platform_lower = platform.lower() if platform else ""
                if "cisco" in platform_lower:
                    return f"思科子网掩码 '{key}' 必须是点分十进制格式 (如 255.255.255.0)，不支持输入数字位数 '{val_str}'"
                num = int(val_str)
                if num < 0 or num > 32:
                    return f"子网掩码 '{key}' 必须在 0 到 32 之间"
            else:
                octets = val_str.split('.')
                if len(octets) != 4 or not all(o.isdigit() and 0 <= int(o) <= 255 for o in octets):
                    return f"子网掩码 '{key}' 必须是合法的点分十进制格式 (如 255.255.255.0)"
                ipaddress.IPv4Network(f"0.0.0.0/{val_str}")
        except ValueError:
            return f"子网掩码 '{key}' 格式非法"

    if "area" in key.lower():
        platform_lower = platform.lower() if platform else ""
        if "juniper" in platform_lower:
            if not re.match(r'^\d+\.\d+\.\d+\.\d+$', val_str):
                return f"Juniper OSPF 区域 ID '{key}' 必须为点分十进制 IP 格式 (如 0.0.0.0)"
            try:
                ipaddress.ip_address(val_str)
            except ValueError:
                return f"OSPF 区域 ID '{key}' 格式非法"
        else:
            if val_str.isdigit():
                num = int(val_str)
                if num < 0 or num > 4294967295:
                    return f"OSPF 区域 ID '{key}' 必须在 0 到 4294967295 之间"
            else:
                try:
                    ipaddress.ip_address(val_str)
                except ValueError:
                    return f"OSPF 区域 ID '{key}' 必须是正整数或点分十进制 IP 格式 (如 0.0.0.0)"

    if any(k in key.lower() for k in ["address_family", "bgp_family", "addr_family"]) or (key.lower() == "family"):
        valid_keywords = ["ipv4", "ipv6", "inet", "inet6", "vpnv4", "vpnv6", "l2vpn", "evpn", "unicast", "multicast"]
        words = re.split(r'[^a-zA-Z0-9-]', val_str.lower())
        if not all(any(vk in w for vk in valid_keywords) for w in words if w):
            return f"地址簇 '{key}' 格式非法 (支持如 ipv4 unicast, ipv4-family, inet unicast 等)"

    if any(k in key.lower() for k in ["interface", "intf"]) and not any(k in key.lower() for k in ["type", "description"]):
        platform_lower = platform.lower() if platform else ""
        if "cisco" in platform_lower:
            if not re.match(r'^(gi|gigabitethernet|fa|fastethernet|te|tengigabitethernet|tw|twentyfivegige|fo|fortygige|hu|hundredgige|vl|vlan|lo|loopback|se|serial|pos|port-channel)\s*\d+([\/\d\.]+)*$', val_str, re.IGNORECASE):
                return f"思科接口名称 '{key}' 格式不正确 (如 GigabitEthernet0/1, Vlan10, GigabitEthernet0/1.10)"
        elif "huawei" in platform_lower or "h3c" in platform_lower:
            if re.match(r'^(ge|gigabitethernet|xge|xgigabitethernet)', val_str, re.IGNORECASE):
                if not re.match(r'^(ge|gigabitethernet|xge|xgigabitethernet)\s*\d+/\d+/\d+(\.\d+)?$', val_str, re.IGNORECASE):
                    return f"华为/H3C物理接口名称 '{key}' 必须是三级槽位格式 (如 GigabitEthernet0/0/1 或 GE0/0/1)"
            else:
                if not re.match(r'^(eth-trunk|vlanif|loopback|lo|null)\s*\d+(\.\d+)?$', val_str, re.IGNORECASE):
                    return f"华为/H3C逻辑接口名称 '{key}' 格式不正确 (如 Vlanif10, Eth-Trunk1)"
        elif "juniper" in platform_lower:
            if not (re.match(r'^(ge|xe|et|ae|fe|lo|vlan|irb)\-\d+\/\d+\/\d+(\.\d+)?$', val_str, re.IGNORECASE) or 
                    re.match(r'^lo0\.\d+$', val_str, re.IGNORECASE) or 
                    re.match(r'^ae\d+(\.\d+)?$', val_str, re.IGNORECASE) or 
                    re.match(r'^vlan\.\d+$', val_str, re.IGNORECASE) or 
                    re.match(r'^irb\.\d+$', val_str, re.IGNORECASE)):
                return f"Juniper接口名称 '{key}' 格式不正确 (如 ge-0/0/0, ge-0/0/0.10, ae1.10, lo0.0)"
        elif "arista" in platform_lower:
            if not re.match(r'^(eth|ethernet|vlan|loopback|port-channel|lo)\s*\d+([\/\d\.]+)*$', val_str, re.IGNORECASE):
                return f"Arista接口名称 '{key}' 格式不正确 (如 Ethernet1, Vlan10, Ethernet1.10)"

    ip_indicators = ["ip", "host", "server", "neighbor", "gateway", "network", "src", "dst", "router"]
    is_ip_field = any(ind in key.lower() for ind in ip_indicators) and not any(k in key.lower() for k in ["mask", "wildcard"])
    
    if is_ip_field:
        strict_ip = any(ind in key.lower() for ind in ["ip", "network", "src", "dst", "addr", "router_id"]) and not any(k in key.lower() for k in ["name", "domain"])
        
        if strict_ip:
            if not re.match(r'^[\d\./]+$', val_str):
                return f"IP地址/网段 '{key}' 格式非法"
        else:
            if not re.match(r'^[\w\.\-\/]+$', val_str):
                return f"IP地址/主机名 '{key}' 的格式不正确"
        
        if re.match(r'^[\d\./]+$', val_str):
            platform_lower = platform.lower() if platform else ""
            has_independent_mask = False
            if variables:
                has_independent_mask = any("mask" in k.lower() or "wildcard" in k.lower() for k in variables.keys())
            
            is_traditional_platform = any(p in platform_lower for p in ["cisco", "huawei", "h3c"])
            is_host_ip_only = any(k in key.lower() for k in ["router_id", "peer_ip", "neighbor_ip", "server_ip", "gateway"])
            
            if is_host_ip_only or (is_traditional_platform and has_independent_mask):
                if '/' in val_str:
                    return f"变量 '{key}' 必须是纯 IP 地址，不能带 '/' 掩码位数"
                try:
                    ipaddress.ip_address(val_str)
                except ValueError:
                    return f"IP地址 '{key}' 格式非法"
            else:
                try:
                    if '/' in val_str:
                        ipaddress.ip_network(val_str, strict=False)
                    else:
                        ipaddress.ip_address(val_str)
                except ValueError:
                    return f"IP地址/网段 '{key}' 格式非法"

    return None


def get_pre_post_checks(platform: str, category: str, name: str) -> tuple[list[str], list[str]]:
    plat = platform.lower()
    cat = (category or "").lower()
    nm = (name or "").lower()

    if "cisco" in plat:
        if cat == "routing" or "bgp" in nm or "ospf" in nm or "route" in nm:
            if "bgp" in nm:
                return (
                    ["show ip bgp summary", "show ip route"],
                    ["show ip bgp summary", "show ip route"]
                )
            elif "ospf" in nm:
                return (
                    ["show ip ospf neighbor", "show ip route"],
                    ["show ip ospf neighbor", "show ip route"]
                )
            else:
                return (
                    ["show ip route"],
                    ["show ip route"]
                )
        elif cat == "security" or "acl" in nm or "ssh" in nm or "aaa" in nm or "tacacs" in nm:
            if "acl" in nm:
                return (
                    ["show ip access-lists"],
                    ["show ip access-lists"]
                )
            elif "ssh" in nm or "aaa" in nm or "tacacs" in nm:
                return (
                    ["show run | include ssh", "show run | include aaa"],
                    ["show ssh", "show run | include ssh"]
                )
            else:
                return (
                    ["show running-config"],
                    ["show running-config"]
                )
        elif cat == "switching" or "vlan" in nm:
            return (
                ["show vlan brief", "show interfaces status"],
                ["show vlan brief", "show interfaces status"]
            )
        elif cat == "management" or "snmp" in nm or "ntp" in nm:
            if "snmp" in nm:
                return (
                    ["show snmp"],
                    ["show snmp"]
                )
            else:
                return (
                    ["show ntp status"],
                    ["show ntp status"]
                )
        return (
            ["show version", "show running-config | include interface"],
            ["show running-config | include interface", "show interfaces status"]
        )

    elif "huawei" in plat or "h3c" in plat:
        if cat == "routing" or "bgp" in nm or "ospf" in nm or "route" in nm:
            if "bgp" in nm:
                return (
                    ["display bgp peer", "display ip routing-table"],
                    ["display bgp peer", "display ip routing-table"]
                )
            elif "ospf" in nm:
                return (
                    ["display ospf peer brief", "display ip routing-table"],
                    ["display ospf peer brief", "display ip routing-table"]
                )
            else:
                return (
                    ["display ip routing-table"],
                    ["display ip routing-table"]
                )
        elif cat == "security" or "acl" in nm or "ssh" in nm or "aaa" in nm or "tacacs" in nm:
            if "acl" in nm:
                return (
                    ["display acl all"],
                    ["display acl all"]
                )
            elif "ssh" in nm or "aaa" in nm or "tacacs" in nm:
                return (
                    ["display local-user"],
                    ["display local-user"]
                )
            else:
                return (
                    ["display current-configuration"],
                    ["display current-configuration"]
                )
        elif cat == "switching" or "vlan" in nm:
            return (
                ["display vlan"],
                ["display vlan"]
            )
        elif cat == "management" or "snmp" in nm or "ntp" in nm:
            if "snmp" in nm:
                return (
                    ["display snmp-agent sys-info"],
                    ["display snmp-agent sys-info"]
                )
            else:
                return (
                    ["display ntp-service status"],
                    ["display ntp-service status"]
                )
        return (
            ["display version", "display current-configuration | include interface"],
            ["display current-configuration | include interface", "display interface"]
        )

    elif "juniper" in plat:
        if cat == "routing" or "bgp" in nm or "ospf" in nm or "route" in nm:
            if "bgp" in nm:
                return (
                    ["show bgp summary", "show route"],
                    ["show bgp summary", "show route"]
                )
            elif "ospf" in nm:
                return (
                    ["show ospf neighbor", "show route"],
                    ["show ospf neighbor", "show route"]
                )
            else:
                return (
                    ["show route"],
                    ["show route"]
                )
        elif cat == "security" or "acl" in nm or "ssh" in nm or "aaa" in nm:
            if "acl" in nm or "filter" in nm:
                return (
                    ["show firewall"],
                    ["show firewall"]
                )
            else:
                return (
                    ["show system services"],
                    ["show system services"]
                )
        elif cat == "switching" or "vlan" in nm:
            return (
                ["show vlans"],
                ["show vlans"]
            )
        elif cat == "management" or "snmp" in nm or "ntp" in nm:
            if "snmp" in nm:
                return (
                    ["show snmp mib"],
                    ["show snmp mib"]
                )
            else:
                return (
                    ["show ntp status"],
                    ["show ntp status"]
                )
        return (
            ["show version", "show configuration | display set | grep interface"],
            ["show configuration | display set | grep interface", "show interfaces"]
        )

    elif "arista" in plat:
        if cat == "routing" or "bgp" in nm or "ospf" in nm or "route" in nm:
            if "bgp" in nm:
                return (
                    ["show ip bgp summary", "show ip route"],
                    ["show ip bgp summary", "show ip route"]
                )
            elif "ospf" in nm:
                return (
                    ["show ip ospf neighbor", "show ip route"],
                    ["show ip ospf neighbor", "show ip route"]
                )
            else:
                return (
                    ["show ip route"],
                    ["show ip route"]
                )
        elif cat == "security" or "acl" in nm or "ssh" in nm:
            return (
                ["show ip access-lists"],
                ["show ip access-lists"]
            )
        elif cat == "switching" or "vlan" in nm:
            return (
                ["show vlan"],
                ["show vlan"]
            )
        elif cat == "management" or "snmp" in nm or "ntp" in nm:
            if "snmp" in nm:
                return (
                    ["show snmp"],
                    ["show snmp"]
                )
            else:
                return (
                    ["show ntp status"],
                    ["show ntp status"]
                )
        return (
            ["show version", "show running-config | include interface"],
            ["show running-config | include interface", "show interfaces status"]
        )

    return ([], [])


def validate_template_parameters(
    scenario_id: str,
    source_kind: str,
    platform: str,
    variables: dict,
    target_devices: list = []
) -> list[str]:
    import re
    errors = []

    from api.playbooks import _all_scenarios

    scenario = None
    if source_kind == 'config_template':
        conn = get_db_connection()
        try:
            row = conn.execute(
                'SELECT id, name, category, vendor, content, rollback FROM templates WHERE id = ?',
                (scenario_id,),
            ).fetchone()
            if not row:
                return [f"配置模板 '{scenario_id}' 不存在"]
            template = dict(row)
        finally:
            conn.close()

        content = template.get('content') or ''
        rollback = template.get('rollback') or ''

        var_matches = re.findall(r'\{\{\s*([\w.-]+)(?:\s*\|\s*[^}]+)?\s*\}\}', content)
        unique_vars = sorted(list(set(var_matches)))

        variable_defs = []
        for k in unique_vars:
            k_lower = k.lower()
            is_req = not any(x in k_lower for x in ["group_name", "family", "description"])
            if k_lower == 'family' or 'address_family' in k_lower or 'bgp_family' in k_lower or 'addr_family' in k_lower:
                variable_defs.append({
                    'key': k, 'label': k, 'type': 'select', 'required': is_req,
                    'options': [
                        'ipv4 unicast', 'ipv4 multicast', 'ipv6 unicast', 'ipv6 multicast',
                        'vpnv4 unicast', 'vpnv6 unicast', 'l2vpn evpn',
                        'ipv4-family unicast', 'ipv4-family vpnv4', 'ipv6-family unicast',
                        'inet unicast', 'inet6 unicast',
                    ],
                })
            else:
                variable_defs.append({'key': k, 'label': k, 'type': 'text', 'required': is_req})

        pre_check, post_check = get_pre_post_checks(platform, template.get('category') or '', template.get('name') or '')
        phases = {
            'pre_check': pre_check,
            'execute': [content] if content.strip() else [],
            'post_check': post_check,
            'rollback': [rollback] if rollback.strip() else [],
        }
    else:
        scenario = next((item for item in _all_scenarios() if item.get('id') == scenario_id), None)
        if not scenario:
            return [f"变更场景 '{scenario_id}' 不存在"]

        variable_defs = scenario.get('variables') or []
        phases = (scenario.get('platform_phases') or {}).get(platform)
        if not phases:
            return [f"所选场景不支持平台 '{platform}'"]

    for variable in variable_defs:
        key = str(variable.get('key') or '').strip()
        if not key:
            continue
        val = str(variables.get(key, '')).strip()
        if variable.get('required') and not val:
            errors.append(f"必填变量 '{variable.get('label') or key}' 不能为空")

    for key, val in variables.items():
        var_def = next((v for v in variable_defs if v.get('key') == key), None)
        var_type = var_def.get('type', 'text') if var_def else 'text'
        err = validate_variable_value(key, val, var_type, platform, variables)
        if err:
            errors.append(err)

    from jinja2 import StrictUndefined, TemplateSyntaxError, UndefinedError
    from jinja2.sandbox import SandboxedEnvironment
    env = SandboxedEnvironment(undefined=StrictUndefined)

    strict_vars = {k: str(v) for k, v in variables.items()}

    try:
        for phase_name, templates_list in phases.items():
            for tmpl_str in templates_list:
                tmpl = env.from_string(tmpl_str)
                tmpl.render(**strict_vars)
    except TemplateSyntaxError as e:
        errors.append(f"模板语法错误: {e.message} (行 {e.lineno})")
    except UndefinedError as e:
        errors.append(f"缺失或未定义变量: {e.message}")
    except Exception as e:
        errors.append(f"模板渲染出错: {str(e)}")

    if target_devices:
        for device in target_devices:
            dev_hostname = device.get('hostname', 'Unknown')
            dev_platform = device.get('platform', '')
            if dev_platform and platform:
                dev_vendor = dev_platform.split('_')[0] if '_' in dev_platform else dev_platform
                tmpl_vendor = platform.split('_')[0] if '_' in platform else platform
                if dev_vendor.lower() != tmpl_vendor.lower():
                    errors.append(f"设备 '{dev_hostname}' 的平台是 '{dev_platform}'，与模板的适配平台 '{platform}' 不兼容")

    return errors


def _build_command_template_snapshot(template_payload: dict, target_devices: list = None, status: str = 'draft') -> dict:
    if target_devices is None:
        target_devices = []
    if not isinstance(template_payload, dict):
        raise HTTPException(status_code=400, detail='command_template must be an object')

    scenario_id = str(template_payload.get('scenario_id') or '').strip()
    if not scenario_id:
        raise HTTPException(status_code=400, detail='command_template.scenario_id is required')
    source_kind = str(template_payload.get('source_kind') or 'scenario').strip().lower()

    from api.playbooks import _all_scenarios, _render_phase_commands

    scenario = None
    if source_kind == 'config_template':
        conn = get_db_connection()
        try:
            row = conn.execute(
                'SELECT id, name, category, vendor, content, rollback FROM templates WHERE id = ?',
                (scenario_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=400, detail='Selected configuration template does not exist')
        template = dict(row)
        platform = str(template_payload.get('platform') or '').strip()
        if not platform:
            raise HTTPException(status_code=400, detail='command_template.platform is required for config template mode')
        pre_check, post_check = get_pre_post_checks(platform, template.get('category') or '', template.get('name') or '')
        scenario = {
            'id': template['id'],
            'name': template.get('name') or '',
            'name_zh': template.get('name') or '',
            'variables': [],
            'platform_phases': {
                platform: {
                    'pre_check': pre_check,
                    'execute': [str(template.get('content') or '')] if str(template.get('content') or '').strip() else [],
                    'post_check': post_check,
                    'rollback': [str(template.get('rollback') or '')] if str(template.get('rollback') or '').strip() else [],
                }
            },
            'default_platform': platform,
            'supported_platforms': [platform],
        }
    else:
        scenario = next((item for item in _all_scenarios() if item.get('id') == scenario_id), None)
        if not scenario:
            raise HTTPException(status_code=400, detail='Selected scenario does not exist')

    supported_platforms = scenario.get('supported_platforms') or []
    default_platform = str(scenario.get('default_platform') or (supported_platforms[0] if supported_platforms else '')).strip()
    platform = str(template_payload.get('platform') or default_platform).strip()
    phases = (scenario.get('platform_phases') or {}).get(platform)
    if not phases:
        raise HTTPException(status_code=400, detail=f"Platform '{platform}' is not supported by the selected scenario")

    raw_variables = template_payload.get('variables') or {}
    if not isinstance(raw_variables, dict):
        raise HTTPException(status_code=400, detail='command_template.variables must be an object')
    variables = {str(key): '' if value is None else str(value) for key, value in raw_variables.items()}

    if status != 'draft':
        errors = validate_template_parameters(scenario_id, source_kind, platform, variables, target_devices)
        if errors:
            raise HTTPException(status_code=400, detail="、".join(errors))

    variable_defs = scenario.get('variables') or []
    missing_labels = []
    for variable in variable_defs:
        key = str(variable.get('key') or '').strip()
        if not key:
            continue
        value = str(variables.get(key, '')).strip()
        if variable.get('required') and not value:
            missing_labels.append(str(variable.get('label') or key))
        options = variable.get('options') or []
        if value and options and str(variable.get('type') or '') == 'select' and value not in [str(item) for item in options]:
            raise HTTPException(status_code=400, detail=f"Invalid option for variable '{key}'")

    if missing_labels:
        raise HTTPException(status_code=400, detail=f"Missing required scenario variables: {', '.join(missing_labels)}")

    preview = {
        'pre_check': _render_phase_commands(phases.get('pre_check', []), variables),
        'execute': _render_phase_commands(phases.get('execute', []), variables),
        'post_check': _render_phase_commands(phases.get('post_check', []), variables),
        'rollback': _render_phase_commands(phases.get('rollback', []), variables),
    }
    if not preview['execute']:
        raise HTTPException(status_code=400, detail='Selected scenario rendered no executable commands')

    return {
        'mode': 'template',
        'source_kind': source_kind,
        'scenario_id': scenario_id,
        'scenario_name': str(scenario.get('name') or ''),
        'scenario_name_zh': str(scenario.get('name_zh') or scenario.get('name') or ''),
        'platform': platform,
        'variables': variables,
        'preview': preview,
        'generated_at': _utc_now_iso(),
    }


def _normalize_command_template_payload(payload: dict) -> dict:
    normalized = dict(payload)
    if 'command_template' not in normalized:
        return normalized

    template_payload = normalized.get('command_template') or {}
    status = normalized.get('status', 'draft')
    order_type = normalized.get('order_type', 'config_change')

    if not template_payload:
        if is_template_required() and status in _TEMPLATE_REQUIRED_STATUSES and order_type == 'config_change':
            raise HTTPException(status_code=400, detail='非草稿状态的配置变更工单必须携带有效的场景化模板')
        normalized['command_template'] = {}
        return normalized

    target_devices = normalized.get('target_devices') or []
    snapshot = _build_command_template_snapshot(template_payload, target_devices, status)
    normalized['command_template'] = snapshot
    normalized['commands'] = snapshot['preview']['execute']
    normalized['rollback_plan'] = '\n'.join(snapshot['preview']['rollback']) if snapshot['preview']['rollback'] else str(normalized.get('rollback_plan') or '')
    return normalized
