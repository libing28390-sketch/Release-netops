"""
Playbook Engine — 三段式变更管理：Pre-Check → Execute → Post-Check (+ 自动回滚)
WebSocket 实时输出流 + 内置场景库
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Body, Request, Query
from fastapi.responses import JSONResponse
import uuid
import json
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from database import get_db_connection
from services.audit_service import log_audit_event
from core.crypto import decrypt_credential

router = APIRouter()
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────
# 平台级持久化命令（exec-mode，write mem / save force）
# IOS-XR 和 Junos 的 commit 已在场景模板里，不重复执行
# ────────────────────────────────────────────────────────────────────
PLATFORM_SAVE_COMMANDS: dict[str, str | None] = {
    'cisco_ios':    'write memory',
    'cisco_nxos':   'copy running-config startup-config',
    'cisco_iosxr':  None,  # commit 已在 execute 阶段模板里
    'huawei_vrp':   'save force',
    'h3c_comware':  'save force',
    'arista_eos':   'write memory',
    'juniper_junos': None,  # commit 已在 execute 阶段模板里
}

# 变更前快照用的 show running-config 命令（平台差异）
PLATFORM_SHOW_RUNNING: dict[str, str] = {
    'cisco_ios':    'show running-config',
    'cisco_nxos':   'show running-config',
    'cisco_iosxr':  'show running-config',
    'huawei_vrp':   'display current-configuration',
    'h3c_comware':  'display current-configuration',
    'arista_eos':   'show running-config',
    'juniper_junos': 'show configuration',
}

# P2: 设备粒度互斥锁 (device_id → asyncio.Lock)
_device_locks: dict[str, asyncio.Lock] = {}

def _get_device_lock(device_id: str) -> asyncio.Lock:
    if device_id not in _device_locks:
        _device_locks[device_id] = asyncio.Lock()
    return _device_locks[device_id]

# P3: 待确认 commit 的回滚任务 (execution_id → asyncio.Task)
_pending_rollbacks: dict[str, asyncio.Task] = {}

# ════════════════════════════════════════════════════════════════════
# 内置场景模板
# ════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════
# 厂商 / 平台 注册表
# ════════════════════════════════════════════════════════════════════

PLATFORMS = {
    "cisco_ios": {
        "vendor": "Cisco",
        "name": "IOS / IOS-XE",
        "description": "Catalyst 3750/3850/9200/9300/9500, ISR 1000/4000, ASR 1000",
        "icon": "🔵",
    },
    "cisco_nxos": {
        "vendor": "Cisco",
        "name": "NX-OS",
        "description": "Nexus 3000/5000/7000/9000",
        "icon": "🟢",
    },
    "cisco_iosxr": {
        "vendor": "Cisco",
        "name": "IOS-XR",
        "description": "ASR 9000, NCS 5500/5000, 8000 Series",
        "icon": "🟣",
    },
    "huawei_vrp": {
        "vendor": "Huawei",
        "name": "VRP",
        "description": "CE12800/CE6800/CE5800, S5700/S6700/S7700, AR6000, NE Series",
        "icon": "🔴",
    },
    "h3c_comware": {
        "vendor": "H3C",
        "name": "Comware V7",
        "description": "S5500/S6800/S12500, MSR, SR8800",
        "icon": "🟠",
    },
    "arista_eos": {
        "vendor": "Arista",
        "name": "EOS",
        "description": "7050X/7060X/7280R/7500R/7800R, 720XP",
        "icon": "⚪",
    },
    "juniper_junos": {
        "vendor": "Juniper",
        "name": "Junos",
        "description": "EX Series, QFX Series, MX Series, SRX Series",
        "icon": "🟤",
    },
}

# ════════════════════════════════════════════════════════════════════
# 内置场景模板（多厂商多平台）
# ════════════════════════════════════════════════════════════════════

BUILTIN_SCENARIOS = [
    # ── 1. VLAN Provisioning ──────────────────────────────────
    {
        "id": "vlan-provision",
        "name": "VLAN Provisioning",
        "name_zh": "VLAN 上线",
        "description": "Create VLAN, assign to interfaces, verify MAC table",
        "description_zh": "创建 VLAN、分配接口、验证 MAC 表",
        "category": "L2",
        "icon": "🏷️",
        "risk": "low",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "vlan_id", "label": "VLAN ID", "type": "number", "required": True, "placeholder": "100"},
            {"key": "vlan_name", "label": "VLAN Name", "type": "text", "required": True, "placeholder": "USERS_VLAN"},
            {
                "key": "interfaces", "label": "Interfaces (comma-sep)", "type": "text", "required": False,
                "placeholder": "GigabitEthernet0/0/1",
                "platform_hints": {
                    "cisco_ios": "GigabitEthernet0/0/1,GigabitEthernet0/0/2",
                    "cisco_nxos": "Ethernet1/1,Ethernet1/2",
                    "huawei_vrp": "GE0/0/1,GE0/0/2",
                    "h3c_comware": "GE1/0/1,GE1/0/2",
                    "arista_eos": "Ethernet1,Ethernet2",
                    "juniper_junos": "ge-0/0/0,ge-0/0/1",
                },
            },
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": [
                    "show vlan brief",
                    "show interfaces trunk",
                ],
                "execute": [
                    "vlan {{vlan_id}}",
                    " name {{vlan_name}}",
                    "{% if interfaces %}{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n switchport mode access\n switchport access vlan {{vlan_id}}\n{% endfor %}{% endif %}"
                ],
                "post_check": [
                    "show vlan id {{vlan_id}}",
                    "show mac address-table vlan {{vlan_id}}",
                ],
                "rollback": [
                    "no vlan {{vlan_id}}",
                ],
            },
            "cisco_nxos": {
                "pre_check": [
                    "show vlan brief",
                    "show interface trunk",
                ],
                "execute": [
                    "vlan {{vlan_id}}",
                    " name {{vlan_name}}",
                    "{% if interfaces %}{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n switchport\n switchport mode access\n switchport access vlan {{vlan_id}}\n no shutdown\n{% endfor %}{% endif %}"
                ],
                "post_check": [
                    "show vlan id {{vlan_id}}",
                    "show mac address-table vlan {{vlan_id}}",
                ],
                "rollback": [
                    "no vlan {{vlan_id}}",
                ],
            },
            "huawei_vrp": {
                "pre_check": [
                    "display vlan",
                    "display port vlan",
                ],
                "execute": [
                    "vlan {{vlan_id}}",
                    " description {{vlan_name}}",
                    " quit",
                    "{% if interfaces %}{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n port link-type access\n port default vlan {{vlan_id}}\n quit\n{% endfor %}{% endif %}"
                ],
                "post_check": [
                    "display vlan {{vlan_id}}",
                    "display mac-address vlan {{vlan_id}}",
                ],
                "rollback": [
                    "undo vlan {{vlan_id}}",
                ],
            },
            "h3c_comware": {
                "pre_check": [
                    "display vlan all",
                    "display interface brief",
                ],
                "execute": [
                    "vlan {{vlan_id}}",
                    " description {{vlan_name}}",
                    " quit",
                    "{% if interfaces %}{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n port link-type access\n port access vlan {{vlan_id}}\n quit\n{% endfor %}{% endif %}"
                ],
                "post_check": [
                    "display vlan {{vlan_id}}",
                    "display mac-address vlan {{vlan_id}}",
                ],
                "rollback": [
                    "undo vlan {{vlan_id}}",
                ],
            },
            "arista_eos": {
                "pre_check": [
                    "show vlan",
                    "show interfaces trunk",
                ],
                "execute": [
                    "vlan {{vlan_id}}",
                    " name {{vlan_name}}",
                    "{% if interfaces %}{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n switchport mode access\n switchport access vlan {{vlan_id}}\n{% endfor %}{% endif %}"
                ],
                "post_check": [
                    "show vlan {{vlan_id}}",
                    "show mac address-table vlan {{vlan_id}}",
                ],
                "rollback": [
                    "no vlan {{vlan_id}}",
                ],
            },
            "juniper_junos": {
                "pre_check": [
                    "show vlans",
                    "show ethernet-switching table",
                ],
                "execute": [
                    "set vlans {{vlan_name}} vlan-id {{vlan_id}}",
                    "{% if interfaces %}{% for intf in interfaces.split(',') %}set interfaces {{intf.strip()}} unit 0 family ethernet-switching interface-mode access\nset interfaces {{intf.strip()}} unit 0 family ethernet-switching vlan members {{vlan_name}}\n{% endfor %}{% endif %}"
                ],
                "post_check": [
                    "show vlans {{vlan_name}}",
                    "show ethernet-switching table vlan-name {{vlan_name}}",
                ],
                "rollback": [
                    "delete vlans {{vlan_name}}",
                ],
            },
        },
    },

    # ── 2. BGP Neighbor Setup ─────────────────────────────────
    {
        "id": "bgp-neighbor",
        "name": "BGP Neighbor Setup",
        "name_zh": "BGP 邻居配置",
        "description": "Configure BGP peer, verify session establishment",
        "description_zh": "配置 BGP 邻居、验证会话建立",
        "category": "L3",
        "icon": "🌐",
        "risk": "high",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "cisco_iosxr", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "bgp_as", "label": "Local AS", "type": "number", "required": True, "placeholder": "65001"},
            {"key": "neighbor_ip", "label": "Neighbor IP", "type": "text", "required": True, "placeholder": "10.0.0.2"},
            {"key": "remote_as", "label": "Remote AS", "type": "number", "required": True, "placeholder": "65002"},
            {"key": "description", "label": "Description", "type": "text", "required": False, "placeholder": "Uplink to Core"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": [
                    "show ip bgp summary",
                    "show ip route summary",
                ],
                "execute": [
                    "router bgp {{bgp_as}}",
                    " neighbor {{neighbor_ip}} remote-as {{remote_as}}",
                    "{% if description %} neighbor {{neighbor_ip}} description {{description}}{% endif %}",
                    " address-family ipv4 unicast",
                    "  neighbor {{neighbor_ip}} activate",
                ],
                "post_check": [
                    "show ip bgp summary",
                    "show ip bgp neighbors {{neighbor_ip}}",
                ],
                "rollback": [
                    "router bgp {{bgp_as}}",
                    " no neighbor {{neighbor_ip}}",
                ],
            },
            "cisco_nxos": {
                "pre_check": [
                    "show ip bgp summary",
                    "show ip route summary",
                ],
                "execute": [
                    "router bgp {{bgp_as}}",
                    " neighbor {{neighbor_ip}}",
                    "  remote-as {{remote_as}}",
                    "{% if description %}  description {{description}}{% endif %}",
                    "  address-family ipv4 unicast",
                ],
                "post_check": [
                    "show ip bgp summary",
                    "show ip bgp neighbors {{neighbor_ip}}",
                ],
                "rollback": [
                    "router bgp {{bgp_as}}",
                    " no neighbor {{neighbor_ip}}",
                ],
            },
            "cisco_iosxr": {
                "pre_check": [
                    "show bgp ipv4 unicast summary",
                    "show route summary",
                ],
                "execute": [
                    "router bgp {{bgp_as}}",
                    " neighbor {{neighbor_ip}}",
                    "  remote-as {{remote_as}}",
                    "{% if description %}  description {{description}}{% endif %}",
                    "  address-family ipv4 unicast",
                    "  commit",
                ],
                "post_check": [
                    "show bgp ipv4 unicast summary",
                    "show bgp ipv4 unicast neighbors {{neighbor_ip}}",
                ],
                "rollback": [
                    "router bgp {{bgp_as}}",
                    " no neighbor {{neighbor_ip}}",
                    " commit",
                ],
            },
            "huawei_vrp": {
                "pre_check": [
                    "display bgp peer",
                    "display ip routing-table statistics",
                ],
                "execute": [
                    "bgp {{bgp_as}}",
                    " peer {{neighbor_ip}} as-number {{remote_as}}",
                    "{% if description %} peer {{neighbor_ip}} description {{description}}{% endif %}",
                    " address-family ipv4 unicast",
                    "  peer {{neighbor_ip}} enable",
                    " quit",
                    " quit",
                ],
                "post_check": [
                    "display bgp peer {{neighbor_ip}} verbose",
                    "display bgp routing-table",
                ],
                "rollback": [
                    "bgp {{bgp_as}}",
                    " undo peer {{neighbor_ip}}",
                    " quit",
                ],
            },
            "h3c_comware": {
                "pre_check": [
                    "display bgp peer ipv4",
                    "display ip routing-table statistics",
                ],
                "execute": [
                    "bgp {{bgp_as}}",
                    " peer {{neighbor_ip}} as-number {{remote_as}}",
                    "{% if description %} peer {{neighbor_ip}} description {{description}}{% endif %}",
                    " address-family ipv4 unicast",
                    "  peer {{neighbor_ip}} enable",
                    " quit",
                    " quit",
                ],
                "post_check": [
                    "display bgp peer {{neighbor_ip}} verbose",
                    "display bgp routing-table ipv4",
                ],
                "rollback": [
                    "bgp {{bgp_as}}",
                    " undo peer {{neighbor_ip}}",
                    " quit",
                ],
            },
            "arista_eos": {
                "pre_check": [
                    "show ip bgp summary",
                    "show ip route summary",
                ],
                "execute": [
                    "router bgp {{bgp_as}}",
                    " neighbor {{neighbor_ip}} remote-as {{remote_as}}",
                    "{% if description %} neighbor {{neighbor_ip}} description {{description}}{% endif %}",
                    " neighbor {{neighbor_ip}} activate",
                ],
                "post_check": [
                    "show ip bgp summary",
                    "show ip bgp neighbors {{neighbor_ip}}",
                ],
                "rollback": [
                    "router bgp {{bgp_as}}",
                    " no neighbor {{neighbor_ip}}",
                ],
            },
            "juniper_junos": {
                "pre_check": [
                    "show bgp summary",
                    "show route summary",
                ],
                "execute": [
                    "set routing-options autonomous-system {{bgp_as}}",
                    "set protocols bgp group EBGP type external",
                    "set protocols bgp group EBGP neighbor {{neighbor_ip}} peer-as {{remote_as}}",
                    "{% if description %}set protocols bgp group EBGP neighbor {{neighbor_ip}} description \"{{description}}\"{% endif %}",
                ],
                "post_check": [
                    "show bgp summary",
                    "show bgp neighbor {{neighbor_ip}}",
                ],
                "rollback": [
                    "delete protocols bgp group EBGP neighbor {{neighbor_ip}}",
                ],
            },
        },
    },

    # ── 3. ACL Rule Update ────────────────────────────────────
    {
        "id": "acl-update",
        "name": "ACL Rule Update",
        "name_zh": "ACL 规则变更",
        "description": "Modify access-list, verify with show commands",
        "description_zh": "修改 ACL 规则、验证生效结果",
        "category": "Security",
        "icon": "🔒",
        "risk": "high",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "acl_name", "label": "ACL Name/Number", "type": "text", "required": True, "placeholder": "101",
             "platform_hints": {
                 "cisco_ios": "101 or BLOCK_LIST",
                 "cisco_nxos": "BLOCK_LIST",
                 "huawei_vrp": "BLOCK_LIST",
                 "h3c_comware": "BLOCK_LIST",
                 "arista_eos": "BLOCK_LIST",
                 "juniper_junos": "BLOCK-FILTER",
             }},
            {"key": "acl_rules", "label": "ACL Rules (one per line)", "type": "textarea", "required": True,
             "placeholder": "permit ip 10.0.0.0 0.0.0.255 any\ndeny ip any any log",
             "platform_hints": {
                 "cisco_ios": "permit ip 10.0.0.0 0.0.0.255 any\ndeny ip any any log",
                 "cisco_nxos": "permit ip 10.0.0.0/24 any\ndeny ip any any",
                 "huawei_vrp": "rule 5 permit ip source 10.0.0.0 0.0.0.255\nrule 10 deny ip",
                 "h3c_comware": "rule 5 permit ip source 10.0.0.0 0.0.0.255\nrule 10 deny ip",
                 "arista_eos": "permit ip 10.0.0.0/24 any\ndeny ip any any log",
                 "juniper_junos": "set term ALLOW from source-address 10.0.0.0/24\nset term ALLOW then accept\nset term DEFAULT then discard",
             }},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": [
                    "show access-lists {{acl_name}}",
                    "show ip interface brief",
                ],
                "execute": [
                    "ip access-list extended {{acl_name}}",
                    "{{acl_rules}}",
                ],
                "post_check": [
                    "show access-lists {{acl_name}}",
                ],
                "rollback": [
                    "no ip access-list extended {{acl_name}}",
                ],
            },
            "cisco_nxos": {
                "pre_check": [
                    "show access-lists {{acl_name}}",
                    "show ip interface brief",
                ],
                "execute": [
                    "ip access-list {{acl_name}}",
                    "{{acl_rules}}",
                ],
                "post_check": [
                    "show access-lists {{acl_name}}",
                ],
                "rollback": [
                    "no ip access-list {{acl_name}}",
                ],
            },
            "huawei_vrp": {
                "pre_check": [
                    "display acl name {{acl_name}}",
                    "display acl all",
                ],
                "execute": [
                    "acl name {{acl_name}} advance",
                    "{{acl_rules}}",
                    " quit",
                ],
                "post_check": [
                    "display acl name {{acl_name}}",
                ],
                "rollback": [
                    "undo acl name {{acl_name}}",
                ],
            },
            "h3c_comware": {
                "pre_check": [
                    "display acl name {{acl_name}}",
                    "display acl all",
                ],
                "execute": [
                    "acl advanced name {{acl_name}}",
                    "{{acl_rules}}",
                    " quit",
                ],
                "post_check": [
                    "display acl name {{acl_name}}",
                ],
                "rollback": [
                    "undo acl name {{acl_name}}",
                ],
            },
            "arista_eos": {
                "pre_check": [
                    "show access-lists {{acl_name}}",
                    "show ip interface brief",
                ],
                "execute": [
                    "ip access-list {{acl_name}}",
                    "{{acl_rules}}",
                ],
                "post_check": [
                    "show access-lists {{acl_name}}",
                ],
                "rollback": [
                    "no ip access-list {{acl_name}}",
                ],
            },
            "juniper_junos": {
                "pre_check": [
                    "show firewall filter {{acl_name}}",
                    "show firewall",
                ],
                "execute": [
                    "{% for line in acl_rules.split('\\n') %}set firewall family inet filter {{acl_name}} {{line.strip()}}\n{% endfor %}"
                ],
                "post_check": [
                    "show firewall filter {{acl_name}}",
                ],
                "rollback": [
                    "delete firewall family inet filter {{acl_name}}",
                ],
            },
        },
    },

    # ── 4. Interface Shutdown / Recovery ──────────────────────
    {
        "id": "interface-shutdown",
        "name": "Interface Shutdown/Recovery",
        "name_zh": "接口批量 Shutdown/恢复",
        "description": "Batch shutdown or no shutdown interfaces for isolation",
        "description_zh": "批量关闭或恢复接口，用于故障隔离应急",
        "category": "Operations",
        "icon": "🔌",
        "risk": "medium",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "cisco_iosxr", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {
                "key": "interfaces", "label": "Interfaces (comma-sep)", "type": "text", "required": True,
                "placeholder": "GigabitEthernet0/0/1",
                "platform_hints": {
                    "cisco_ios": "GigabitEthernet0/0/1,GigabitEthernet0/0/2",
                    "cisco_nxos": "Ethernet1/1,Ethernet1/2",
                    "cisco_iosxr": "GigabitEthernet0/0/0/1,GigabitEthernet0/0/0/2",
                    "huawei_vrp": "GE0/0/1,GE0/0/2",
                    "h3c_comware": "GE1/0/1,GE1/0/2",
                    "arista_eos": "Ethernet1,Ethernet2",
                    "juniper_junos": "ge-0/0/0,ge-0/0/1",
                },
            },
            {"key": "action", "label": "Action", "type": "select", "required": True,
             "options": ["shutdown", "no shutdown"], "placeholder": "shutdown"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": [
                    "{% for intf in interfaces.split(',') %}show interfaces {{intf.strip()}}\n{% endfor %}",
                ],
                "execute": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {{action}}\n{% endfor %}",
                ],
                "post_check": [
                    "{% for intf in interfaces.split(',') %}show interfaces {{intf.strip()}}\n{% endfor %}",
                ],
                "rollback": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {% if action == 'shutdown' %}no shutdown{% else %}shutdown{% endif %}\n{% endfor %}",
                ],
            },
            "cisco_nxos": {
                "pre_check": [
                    "{% for intf in interfaces.split(',') %}show interface {{intf.strip()}}\n{% endfor %}",
                ],
                "execute": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {{action}}\n{% endfor %}",
                ],
                "post_check": [
                    "{% for intf in interfaces.split(',') %}show interface {{intf.strip()}}\n{% endfor %}",
                ],
                "rollback": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {% if action == 'shutdown' %}no shutdown{% else %}shutdown{% endif %}\n{% endfor %}",
                ],
            },
            "cisco_iosxr": {
                "pre_check": [
                    "{% for intf in interfaces.split(',') %}show interfaces {{intf.strip()}} brief\n{% endfor %}",
                ],
                "execute": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {{action}}\n{% endfor %}",
                    "commit",
                ],
                "post_check": [
                    "{% for intf in interfaces.split(',') %}show interfaces {{intf.strip()}} brief\n{% endfor %}",
                ],
                "rollback": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {% if action == 'shutdown' %}no shutdown{% else %}shutdown{% endif %}\n{% endfor %}",
                    "commit",
                ],
            },
            "huawei_vrp": {
                "pre_check": [
                    "{% for intf in interfaces.split(',') %}display interface {{intf.strip()}} brief\n{% endfor %}",
                ],
                "execute": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {% if action == 'shutdown' %}shutdown{% else %}undo shutdown{% endif %}\n quit\n{% endfor %}",
                ],
                "post_check": [
                    "{% for intf in interfaces.split(',') %}display interface {{intf.strip()}} brief\n{% endfor %}",
                ],
                "rollback": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {% if action == 'shutdown' %}undo shutdown{% else %}shutdown{% endif %}\n quit\n{% endfor %}",
                ],
            },
            "h3c_comware": {
                "pre_check": [
                    "{% for intf in interfaces.split(',') %}display interface {{intf.strip()}} brief\n{% endfor %}",
                ],
                "execute": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {% if action == 'shutdown' %}shutdown{% else %}undo shutdown{% endif %}\n quit\n{% endfor %}",
                ],
                "post_check": [
                    "{% for intf in interfaces.split(',') %}display interface {{intf.strip()}} brief\n{% endfor %}",
                ],
                "rollback": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {% if action == 'shutdown' %}undo shutdown{% else %}shutdown{% endif %}\n quit\n{% endfor %}",
                ],
            },
            "arista_eos": {
                "pre_check": [
                    "{% for intf in interfaces.split(',') %}show interfaces {{intf.strip()}}\n{% endfor %}",
                ],
                "execute": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {{action}}\n{% endfor %}",
                ],
                "post_check": [
                    "{% for intf in interfaces.split(',') %}show interfaces {{intf.strip()}}\n{% endfor %}",
                ],
                "rollback": [
                    "{% for intf in interfaces.split(',') %}interface {{intf.strip()}}\n {% if action == 'shutdown' %}no shutdown{% else %}shutdown{% endif %}\n{% endfor %}",
                ],
            },
            "juniper_junos": {
                "pre_check": [
                    "{% for intf in interfaces.split(',') %}show interfaces {{intf.strip()}} terse\n{% endfor %}",
                ],
                "execute": [
                    "{% for intf in interfaces.split(',') %}{% if action == 'shutdown' %}set interfaces {{intf.strip()}} disable{% else %}delete interfaces {{intf.strip()}} disable{% endif %}\n{% endfor %}",
                ],
                "post_check": [
                    "{% for intf in interfaces.split(',') %}show interfaces {{intf.strip()}} terse\n{% endfor %}",
                ],
                "rollback": [
                    "{% for intf in interfaces.split(',') %}{% if action == 'shutdown' %}delete interfaces {{intf.strip()}} disable{% else %}set interfaces {{intf.strip()}} disable{% endif %}\n{% endfor %}",
                ],
            },
        },
    },

    # ── 5. NTP Server Configuration ──────────────────────────
    {
        "id": "ntp-config",
        "name": "NTP Server Configuration",
        "name_zh": "NTP 服务器配置",
        "description": "Configure NTP servers and verify synchronization",
        "description_zh": "配置 NTP 服务器并验证同步状态",
        "category": "Operations",
        "icon": "⏰",
        "risk": "low",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "cisco_iosxr", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "ntp_server", "label": "NTP Server IP", "type": "text", "required": True, "placeholder": "10.0.0.1"},
            {"key": "ntp_server2", "label": "Backup NTP Server", "type": "text", "required": False, "placeholder": "10.0.0.2"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": [
                    "show ntp status",
                    "show ntp associations",
                ],
                "execute": [
                    "ntp server {{ntp_server}} prefer",
                    "{% if ntp_server2 %}ntp server {{ntp_server2}}{% endif %}",
                ],
                "post_check": [
                    "show ntp status",
                    "show ntp associations",
                ],
                "rollback": [
                    "no ntp server {{ntp_server}}",
                    "{% if ntp_server2 %}no ntp server {{ntp_server2}}{% endif %}",
                ],
            },
            "cisco_nxos": {
                "pre_check": [
                    "show ntp peer-status",
                    "show ntp peers",
                ],
                "execute": [
                    "ntp server {{ntp_server}} prefer",
                    "{% if ntp_server2 %}ntp server {{ntp_server2}}{% endif %}",
                ],
                "post_check": [
                    "show ntp peer-status",
                    "show ntp peers",
                ],
                "rollback": [
                    "no ntp server {{ntp_server}}",
                    "{% if ntp_server2 %}no ntp server {{ntp_server2}}{% endif %}",
                ],
            },
            "cisco_iosxr": {
                "pre_check": [
                    "show ntp status",
                    "show ntp associations",
                ],
                "execute": [
                    "ntp server {{ntp_server}} prefer",
                    "{% if ntp_server2 %}ntp server {{ntp_server2}}{% endif %}",
                    "commit",
                ],
                "post_check": [
                    "show ntp status",
                    "show ntp associations",
                ],
                "rollback": [
                    "no ntp server {{ntp_server}}",
                    "{% if ntp_server2 %}no ntp server {{ntp_server2}}{% endif %}",
                    "commit",
                ],
            },
            "huawei_vrp": {
                "pre_check": [
                    "display ntp-service status",
                    "display ntp-service sessions",
                ],
                "execute": [
                    "ntp-service unicast-server {{ntp_server}} preferred",
                    "{% if ntp_server2 %}ntp-service unicast-server {{ntp_server2}}{% endif %}",
                ],
                "post_check": [
                    "display ntp-service status",
                    "display ntp-service sessions",
                ],
                "rollback": [
                    "undo ntp-service unicast-server {{ntp_server}}",
                    "{% if ntp_server2 %}undo ntp-service unicast-server {{ntp_server2}}{% endif %}",
                ],
            },
            "h3c_comware": {
                "pre_check": [
                    "display ntp-service status",
                    "display ntp-service sessions",
                ],
                "execute": [
                    "ntp-service unicast-server {{ntp_server}} priority",
                    "{% if ntp_server2 %}ntp-service unicast-server {{ntp_server2}}{% endif %}",
                ],
                "post_check": [
                    "display ntp-service status",
                    "display ntp-service sessions",
                ],
                "rollback": [
                    "undo ntp-service unicast-server {{ntp_server}}",
                    "{% if ntp_server2 %}undo ntp-service unicast-server {{ntp_server2}}{% endif %}",
                ],
            },
            "arista_eos": {
                "pre_check": [
                    "show ntp status",
                    "show ntp associations",
                ],
                "execute": [
                    "ntp server {{ntp_server}} prefer",
                    "{% if ntp_server2 %}ntp server {{ntp_server2}}{% endif %}",
                ],
                "post_check": [
                    "show ntp status",
                    "show ntp associations",
                ],
                "rollback": [
                    "no ntp server {{ntp_server}}",
                    "{% if ntp_server2 %}no ntp server {{ntp_server2}}{% endif %}",
                ],
            },
            "juniper_junos": {
                "pre_check": [
                    "show ntp associations",
                    "show ntp status",
                ],
                "execute": [
                    "set system ntp server {{ntp_server}} prefer",
                    "{% if ntp_server2 %}set system ntp server {{ntp_server2}}{% endif %}",
                ],
                "post_check": [
                    "show ntp associations",
                    "show ntp status",
                ],
                "rollback": [
                    "delete system ntp server {{ntp_server}}",
                    "{% if ntp_server2 %}delete system ntp server {{ntp_server2}}{% endif %}",
                ],
            },
        },
    },

    # ── 6. SNMP Hardening ─────────────────────────────────────
    {
        "id": "snmp-harden",
        "name": "SNMP Hardening",
        "name_zh": "SNMP 安全加固",
        "description": "Remove default community, configure SNMPv3",
        "description_zh": "删除默认 community，配置 SNMPv3",
        "category": "Security",
        "icon": "🛡️",
        "risk": "medium",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "old_community", "label": "Old Community (to remove)", "type": "text", "required": False, "placeholder": "public"},
            {"key": "snmpv3_user", "label": "SNMPv3 Username", "type": "text", "required": True, "placeholder": "netops_monitor"},
            {"key": "auth_pass", "label": "Auth Password", "type": "text", "required": True, "placeholder": ""},
            {"key": "priv_pass", "label": "Privacy Password", "type": "text", "required": True, "placeholder": ""},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": [
                    "show snmp community",
                    "show snmp user",
                ],
                "execute": [
                    "{% if old_community %}no snmp-server community {{old_community}}{% endif %}",
                    "snmp-server group NETOPS_GROUP v3 priv",
                    "snmp-server user {{snmpv3_user}} NETOPS_GROUP v3 auth sha {{auth_pass}} priv aes 128 {{priv_pass}}",
                ],
                "post_check": [
                    "show snmp community",
                    "show snmp user",
                    "show snmp group",
                ],
                "rollback": [
                    "{% if old_community %}snmp-server community {{old_community}} RO{% endif %}",
                    "no snmp-server user {{snmpv3_user}} NETOPS_GROUP v3",
                ],
            },
            "cisco_nxos": {
                "pre_check": [
                    "show snmp community",
                    "show snmp user",
                ],
                "execute": [
                    "{% if old_community %}no snmp-server community {{old_community}}{% endif %}",
                    "snmp-server user {{snmpv3_user}} auth sha {{auth_pass}} priv aes-128 {{priv_pass}}",
                ],
                "post_check": [
                    "show snmp community",
                    "show snmp user",
                ],
                "rollback": [
                    "{% if old_community %}snmp-server community {{old_community}} ro{% endif %}",
                    "no snmp-server user {{snmpv3_user}}",
                ],
            },
            "huawei_vrp": {
                "pre_check": [
                    "display snmp-agent community",
                    "display snmp-agent usm-user",
                ],
                "execute": [
                    "{% if old_community %}undo snmp-agent community {{old_community}}{% endif %}",
                    "snmp-agent group v3 NETOPS_GROUP privacy",
                    "snmp-agent usm-user v3 {{snmpv3_user}} NETOPS_GROUP authentication-mode sha {{auth_pass}} privacy-mode aes128 {{priv_pass}}",
                ],
                "post_check": [
                    "display snmp-agent community",
                    "display snmp-agent usm-user",
                    "display snmp-agent group",
                ],
                "rollback": [
                    "{% if old_community %}snmp-agent community read {{old_community}}{% endif %}",
                    "undo snmp-agent usm-user v3 {{snmpv3_user}}",
                ],
            },
            "h3c_comware": {
                "pre_check": [
                    "display snmp-agent community",
                    "display snmp-agent usm-user",
                ],
                "execute": [
                    "{% if old_community %}undo snmp-agent community {{old_community}}{% endif %}",
                    "snmp-agent group v3 NETOPS_GROUP privacy",
                    "snmp-agent usm-user v3 {{snmpv3_user}} NETOPS_GROUP authentication-mode sha {{auth_pass}} privacy-mode aes128 {{priv_pass}}",
                ],
                "post_check": [
                    "display snmp-agent community",
                    "display snmp-agent usm-user",
                ],
                "rollback": [
                    "{% if old_community %}snmp-agent community read {{old_community}}{% endif %}",
                    "undo snmp-agent usm-user v3 {{snmpv3_user}}",
                ],
            },
            "arista_eos": {
                "pre_check": [
                    "show snmp community",
                    "show snmp user",
                ],
                "execute": [
                    "{% if old_community %}no snmp-server community {{old_community}}{% endif %}",
                    "snmp-server group NETOPS_GROUP v3 priv",
                    "snmp-server user {{snmpv3_user}} NETOPS_GROUP v3 auth sha {{auth_pass}} priv aes {{priv_pass}}",
                ],
                "post_check": [
                    "show snmp community",
                    "show snmp user",
                    "show snmp group",
                ],
                "rollback": [
                    "{% if old_community %}snmp-server community {{old_community}} ro{% endif %}",
                    "no snmp-server user {{snmpv3_user}} NETOPS_GROUP v3",
                ],
            },
            "juniper_junos": {
                "pre_check": [
                    "show snmp community",
                    "show snmp v3",
                ],
                "execute": [
                    "{% if old_community %}delete snmp community {{old_community}}{% endif %}",
                    "set snmp v3 usm local-engine user {{snmpv3_user}} authentication-sha authentication-key {{auth_pass}}",
                    "set snmp v3 usm local-engine user {{snmpv3_user}} privacy-aes128 privacy-key {{priv_pass}}",
                    "set snmp v3 vacm security-to-group security-model usm security-name {{snmpv3_user}} group NETOPS_GROUP",
                    "set snmp v3 vacm access group NETOPS_GROUP default-context-prefix security-model usm security-level privacy read-view ALL",
                ],
                "post_check": [
                    "show snmp community",
                    "show snmp v3",
                ],
                "rollback": [
                    "{% if old_community %}set snmp community {{old_community}} authorization read-only{% endif %}",
                    "delete snmp v3 usm local-engine user {{snmpv3_user}}",
                ],
            },
        },
    },

    # ── 7. Static Route Management ────────────────────────────
    {
        "id": "static-route",
        "name": "Static Route Management",
        "name_zh": "静态路由管理",
        "description": "Add or remove static routes with verification",
        "description_zh": "添加/删除静态路由并验证路由表",
        "category": "L3",
        "icon": "🛤️",
        "risk": "medium",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "cisco_iosxr", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "network", "label": "Destination Network", "type": "text", "required": True, "placeholder": "10.10.0.0"},
            {"key": "mask", "label": "Mask / Prefix-len", "type": "text", "required": True, "placeholder": "255.255.255.0",
             "platform_hints": {
                 "cisco_ios": "255.255.255.0",
                 "cisco_nxos": "255.255.255.0",
                 "cisco_iosxr": "24 (prefix length)",
                 "huawei_vrp": "255.255.255.0 or 24",
                 "h3c_comware": "255.255.255.0 or 24",
                 "arista_eos": "255.255.255.0",
                 "juniper_junos": "24 (prefix length)",
             }},
            {"key": "next_hop", "label": "Next Hop IP", "type": "text", "required": True, "placeholder": "10.0.0.1"},
            {"key": "description", "label": "Description", "type": "text", "required": False, "placeholder": "To Branch Office"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": [
                    "show ip route {{network}}",
                    "show ip route summary",
                ],
                "execute": [
                    "ip route {{network}} {{mask}} {{next_hop}}{% if description %} name {{description}}{% endif %}",
                ],
                "post_check": [
                    "show ip route {{network}}",
                    "ping {{network}} repeat 3",
                ],
                "rollback": [
                    "no ip route {{network}} {{mask}} {{next_hop}}",
                ],
            },
            "cisco_nxos": {
                "pre_check": [
                    "show ip route {{network}}",
                    "show ip route summary",
                ],
                "execute": [
                    "ip route {{network}}/{{mask}} {{next_hop}}{% if description %} name {{description}}{% endif %}",
                ],
                "post_check": [
                    "show ip route {{network}}",
                    "ping {{network}} count 3",
                ],
                "rollback": [
                    "no ip route {{network}}/{{mask}} {{next_hop}}",
                ],
            },
            "cisco_iosxr": {
                "pre_check": [
                    "show route {{network}}/{{mask}}",
                    "show route summary",
                ],
                "execute": [
                    "router static address-family ipv4 unicast {{network}}/{{mask}} {{next_hop}}{% if description %} description {{description}}{% endif %}",
                    "commit",
                ],
                "post_check": [
                    "show route {{network}}/{{mask}}",
                    "ping {{network}} count 3",
                ],
                "rollback": [
                    "no router static address-family ipv4 unicast {{network}}/{{mask}} {{next_hop}}",
                    "commit",
                ],
            },
            "huawei_vrp": {
                "pre_check": [
                    "display ip routing-table {{network}}",
                    "display ip routing-table statistics",
                ],
                "execute": [
                    "ip route-static {{network}} {{mask}} {{next_hop}}{% if description %} description {{description}}{% endif %}",
                ],
                "post_check": [
                    "display ip routing-table {{network}}",
                    "ping -c 3 {{network}}",
                ],
                "rollback": [
                    "undo ip route-static {{network}} {{mask}} {{next_hop}}",
                ],
            },
            "h3c_comware": {
                "pre_check": [
                    "display ip routing-table {{network}}",
                    "display ip routing-table statistics",
                ],
                "execute": [
                    "ip route-static {{network}} {{mask}} {{next_hop}}{% if description %} description {{description}}{% endif %}",
                ],
                "post_check": [
                    "display ip routing-table {{network}}",
                    "ping -c 3 {{network}}",
                ],
                "rollback": [
                    "undo ip route-static {{network}} {{mask}} {{next_hop}}",
                ],
            },
            "arista_eos": {
                "pre_check": [
                    "show ip route {{network}}",
                    "show ip route summary",
                ],
                "execute": [
                    "ip route {{network}} {{mask}} {{next_hop}}{% if description %} name {{description}}{% endif %}",
                ],
                "post_check": [
                    "show ip route {{network}}",
                    "ping {{network}} repeat 3",
                ],
                "rollback": [
                    "no ip route {{network}} {{mask}} {{next_hop}}",
                ],
            },
            "juniper_junos": {
                "pre_check": [
                    "show route {{network}}/{{mask}}",
                    "show route summary",
                ],
                "execute": [
                    "set routing-options static route {{network}}/{{mask}} next-hop {{next_hop}}",
                    "{% if description %}set routing-options static route {{network}}/{{mask}} no-readvertise{% endif %}",
                ],
                "post_check": [
                    "show route {{network}}/{{mask}}",
                    "ping {{network}} count 3 rapid",
                ],
                "rollback": [
                    "delete routing-options static route {{network}}/{{mask}}",
                ],
            },
        },
    },

    # ── 8. OSPF Neighbor Configuration ────────────────────────
    {
        "id": "ospf-config",
        "name": "OSPF Neighbor Configuration",
        "name_zh": "OSPF 邻居配置",
        "description": "Configure OSPF area and interface, verify adjacency",
        "description_zh": "配置 OSPF 区域和接口、验证邻居关系",
        "category": "L3",
        "icon": "🔗",
        "risk": "high",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "cisco_iosxr", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "process_id", "label": "Process ID", "type": "number", "required": True, "placeholder": "1"},
            {"key": "area_id", "label": "Area ID", "type": "text", "required": True, "placeholder": "0"},
            {"key": "network", "label": "Network", "type": "text", "required": True, "placeholder": "10.0.0.0",
             "platform_hints": {
                 "cisco_ios": "10.0.0.0",
                 "cisco_nxos": "10.0.0.0/24 (interface-level)",
                 "huawei_vrp": "10.0.0.0",
                 "juniper_junos": "ge-0/0/0.0 (interface)",
             }},
            {"key": "wildcard", "label": "Wildcard / Prefix", "type": "text", "required": True, "placeholder": "0.0.0.255",
             "platform_hints": {
                 "cisco_ios": "0.0.0.255",
                 "cisco_nxos": "Ethernet1/1 (interface name)",
                 "cisco_iosxr": "0.0.0.255",
                 "huawei_vrp": "0.0.0.255",
                 "h3c_comware": "0.0.0.255",
                 "arista_eos": "0.0.0.255",
                 "juniper_junos": "interface name if needed",
             }},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": [
                    "show ip ospf neighbor",
                    "show ip ospf interface brief",
                ],
                "execute": [
                    "router ospf {{process_id}}",
                    " network {{network}} {{wildcard}} area {{area_id}}",
                ],
                "post_check": [
                    "show ip ospf neighbor",
                    "show ip ospf interface brief",
                    "show ip route ospf",
                ],
                "rollback": [
                    "router ospf {{process_id}}",
                    " no network {{network}} {{wildcard}} area {{area_id}}",
                ],
            },
            "cisco_nxos": {
                "pre_check": [
                    "show ip ospf neighbors",
                    "show ip ospf interface brief",
                ],
                "execute": [
                    "router ospf {{process_id}}",
                    "interface {{wildcard}}",
                    " ip router ospf {{process_id}} area {{area_id}}",
                ],
                "post_check": [
                    "show ip ospf neighbors",
                    "show ip ospf interface brief",
                    "show ip route ospf",
                ],
                "rollback": [
                    "interface {{wildcard}}",
                    " no ip router ospf {{process_id}} area {{area_id}}",
                ],
            },
            "cisco_iosxr": {
                "pre_check": [
                    "show ospf neighbor",
                    "show ospf interface brief",
                ],
                "execute": [
                    "router ospf {{process_id}}",
                    " area {{area_id}}",
                    "  interface {{network}}",
                    "  commit",
                ],
                "post_check": [
                    "show ospf neighbor",
                    "show ospf interface brief",
                    "show route ospf",
                ],
                "rollback": [
                    "router ospf {{process_id}}",
                    " area {{area_id}}",
                    "  no interface {{network}}",
                    " commit",
                ],
            },
            "huawei_vrp": {
                "pre_check": [
                    "display ospf peer",
                    "display ospf interface all",
                ],
                "execute": [
                    "ospf {{process_id}}",
                    " area {{area_id}}",
                    "  network {{network}} {{wildcard}}",
                    " quit",
                    " quit",
                ],
                "post_check": [
                    "display ospf peer",
                    "display ospf interface all",
                    "display ospf routing",
                ],
                "rollback": [
                    "ospf {{process_id}}",
                    " area {{area_id}}",
                    "  undo network {{network}} {{wildcard}}",
                    " quit",
                    " quit",
                ],
            },
            "h3c_comware": {
                "pre_check": [
                    "display ospf peer",
                    "display ospf interface",
                ],
                "execute": [
                    "ospf {{process_id}}",
                    " area {{area_id}}",
                    "  network {{network}} {{wildcard}}",
                    " quit",
                    " quit",
                ],
                "post_check": [
                    "display ospf peer",
                    "display ospf interface",
                    "display ospf routing",
                ],
                "rollback": [
                    "ospf {{process_id}}",
                    " area {{area_id}}",
                    "  undo network {{network}} {{wildcard}}",
                    " quit",
                    " quit",
                ],
            },
            "arista_eos": {
                "pre_check": [
                    "show ip ospf neighbor",
                    "show ip ospf interface brief",
                ],
                "execute": [
                    "router ospf {{process_id}}",
                    " network {{network}} {{wildcard}} area {{area_id}}",
                ],
                "post_check": [
                    "show ip ospf neighbor",
                    "show ip ospf interface brief",
                    "show ip route ospf",
                ],
                "rollback": [
                    "router ospf {{process_id}}",
                    " no network {{network}} {{wildcard}} area {{area_id}}",
                ],
            },
            "juniper_junos": {
                "pre_check": [
                    "show ospf neighbor",
                    "show ospf interface",
                ],
                "execute": [
                    "set protocols ospf area {{area_id}} interface {{network}}",
                ],
                "post_check": [
                    "show ospf neighbor",
                    "show ospf interface",
                    "show route protocol ospf",
                ],
                "rollback": [
                    "delete protocols ospf area {{area_id}} interface {{network}}",
                ],
            },
        },
    },

    # ── 9. Syslog Configuration ───────────────────────────────
    {
        "id": "syslog-config",
        "name": "Syslog Server Configuration",
        "name_zh": "Syslog 日志服务器配置",
        "description": "Configure remote syslog server and facility level",
        "description_zh": "配置远程 Syslog 服务器和日志级别",
        "category": "Operations",
        "icon": "📋",
        "risk": "low",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "syslog_server", "label": "Syslog Server IP", "type": "text", "required": True, "placeholder": "10.0.0.100"},
            {"key": "severity", "label": "Severity Level", "type": "select", "required": True,
             "options": ["informational", "notifications", "warnings", "errors"],
             "placeholder": "informational"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": [
                    "show logging",
                ],
                "execute": [
                    "logging host {{syslog_server}}",
                    "logging trap {{severity}}",
                    "logging source-interface Loopback0",
                ],
                "post_check": [
                    "show logging",
                ],
                "rollback": [
                    "no logging host {{syslog_server}}",
                ],
            },
            "cisco_nxos": {
                "pre_check": [
                    "show logging server",
                ],
                "execute": [
                    "logging server {{syslog_server}} 6 facility local7",
                    "logging level local7 {{severity}}",
                ],
                "post_check": [
                    "show logging server",
                ],
                "rollback": [
                    "no logging server {{syslog_server}}",
                ],
            },
            "huawei_vrp": {
                "pre_check": [
                    "display info-center",
                ],
                "execute": [
                    "info-center loghost {{syslog_server}} channel loghost",
                    "info-center loghost {{syslog_server}} level {{severity}}",
                ],
                "post_check": [
                    "display info-center",
                ],
                "rollback": [
                    "undo info-center loghost {{syslog_server}}",
                ],
            },
            "h3c_comware": {
                "pre_check": [
                    "display info-center",
                ],
                "execute": [
                    "info-center loghost {{syslog_server}} channel loghost",
                    "info-center loghost {{syslog_server}} level {{severity}}",
                ],
                "post_check": [
                    "display info-center",
                ],
                "rollback": [
                    "undo info-center loghost {{syslog_server}}",
                ],
            },
            "arista_eos": {
                "pre_check": [
                    "show logging",
                ],
                "execute": [
                    "logging host {{syslog_server}}",
                    "logging trap {{severity}}",
                ],
                "post_check": [
                    "show logging",
                ],
                "rollback": [
                    "no logging host {{syslog_server}}",
                ],
            },
            "juniper_junos": {
                "pre_check": [
                    "show system syslog",
                ],
                "execute": [
                    "set system syslog host {{syslog_server}} any {{severity}}",
                    "set system syslog host {{syslog_server}} port 514",
                ],
                "post_check": [
                    "show system syslog",
                ],
                "rollback": [
                    "delete system syslog host {{syslog_server}}",
                ],
            },
        },
    },

    # ── 10. Trunk Port Configuration ─────────────────────────
    {
        "id": "trunk-config",
        "name": "Trunk Port Configuration",
        "name_zh": "Trunk 端口配置",
        "description": "Configure 802.1Q trunk ports and allowed VLAN list",
        "description_zh": "配置 802.1Q Trunk 端口及允许的 VLAN 列表",
        "category": "L2",
        "icon": "🔀",
        "risk": "medium",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware", "arista_eos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "interface", "label": "Interface", "type": "text", "required": True,
             "placeholder": "GigabitEthernet0/1",
             "platform_hints": {
                 "cisco_ios":    "GigabitEthernet0/1",
                 "cisco_nxos":  "Ethernet1/1",
                 "huawei_vrp":  "GE0/0/1",
                 "h3c_comware": "GE1/0/1",
                 "arista_eos":  "Ethernet1",
             }},
            {"key": "allowed_vlans", "label": "Allowed VLANs", "type": "text", "required": True, "placeholder": "10,20,30-50"},
            {"key": "native_vlan", "label": "Native VLAN (optional)", "type": "number", "required": False, "placeholder": "1"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": ["show interfaces {{interface}} trunk", "show vlan brief"],
                "execute": [
                    "interface {{interface}}",
                    " switchport mode trunk",
                    " switchport trunk encapsulation dot1q",
                    " switchport trunk allowed vlan {{allowed_vlans}}",
                    "{% if native_vlan %} switchport trunk native vlan {{native_vlan}}{% endif %}",
                    " no shutdown",
                ],
                "post_check": ["show interfaces {{interface}} trunk", "show interfaces {{interface}} status"],
                "rollback": [
                    "interface {{interface}}",
                    " switchport mode access",
                    " no switchport trunk allowed vlan",
                ],
            },
            "cisco_nxos": {
                "pre_check": ["show interface {{interface}} trunk", "show vlan brief"],
                "execute": [
                    "interface {{interface}}",
                    " switchport",
                    " switchport mode trunk",
                    " switchport trunk allowed vlan {{allowed_vlans}}",
                    "{% if native_vlan %} switchport trunk native vlan {{native_vlan}}{% endif %}",
                    " no shutdown",
                ],
                "post_check": ["show interface {{interface}} trunk", "show interface {{interface}} status"],
                "rollback": [
                    "interface {{interface}}",
                    " switchport mode access",
                    " no switchport trunk allowed vlan",
                ],
            },
            "huawei_vrp": {
                "pre_check": ["display interface {{interface}} brief", "display port vlan"],
                "execute": [
                    "interface {{interface}}",
                    " port link-type trunk",
                    " port trunk allow-pass vlan {{allowed_vlans}}",
                    "{% if native_vlan %} port trunk pvid vlan {{native_vlan}}{% endif %}",
                    " undo shutdown",
                    " quit",
                ],
                "post_check": ["display interface {{interface}} brief", "display port vlan {{interface}}"],
                "rollback": [
                    "interface {{interface}}",
                    " port link-type access",
                    " undo port trunk allow-pass vlan",
                    " quit",
                ],
            },
            "h3c_comware": {
                "pre_check": ["display interface {{interface}} brief", "display port trunk"],
                "execute": [
                    "interface {{interface}}",
                    " port link-type trunk",
                    " port trunk permit vlan {{allowed_vlans}}",
                    "{% if native_vlan %} port trunk pvid vlan {{native_vlan}}{% endif %}",
                    " undo shutdown",
                    " quit",
                ],
                "post_check": ["display interface {{interface}} brief", "display port trunk"],
                "rollback": [
                    "interface {{interface}}",
                    " port link-type access",
                    " undo port trunk permit vlan",
                    " quit",
                ],
            },
            "arista_eos": {
                "pre_check": ["show interfaces {{interface}} trunk", "show vlan brief"],
                "execute": [
                    "interface {{interface}}",
                    " switchport mode trunk",
                    " switchport trunk allowed vlan {{allowed_vlans}}",
                    "{% if native_vlan %} switchport trunk native vlan {{native_vlan}}{% endif %}",
                    " no shutdown",
                ],
                "post_check": ["show interfaces {{interface}} trunk", "show interfaces {{interface}} status"],
                "rollback": [
                    "interface {{interface}}",
                    " switchport mode access",
                    " no switchport trunk allowed vlan",
                ],
            },
        },
    },

    # ── 11. Interface IP Address Configuration ───────────────
    {
        "id": "intf-ip-config",
        "name": "Interface IP Configuration",
        "name_zh": "接口 IP 地址配置",
        "description": "Configure IP address on routed interface or SVI",
        "description_zh": "配置三层接口或 SVI 的 IP 地址",
        "category": "L3",
        "icon": "🌍",
        "risk": "medium",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "cisco_iosxr", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "interface", "label": "Interface", "type": "text", "required": True,
             "placeholder": "GigabitEthernet0/0",
             "platform_hints": {
                 "cisco_ios":    "GigabitEthernet0/0 or Vlan10",
                 "cisco_nxos":  "Ethernet1/1 or Vlan10",
                 "cisco_iosxr": "GigabitEthernet0/0/0/0",
                 "huawei_vrp":  "GE0/0/0 or Vlanif10",
                 "h3c_comware": "GE1/0/0 or Vlan-interface10",
                 "arista_eos":  "Ethernet1 or Vlan10",
                 "juniper_junos": "ge-0/0/0.0",
             }},
            {"key": "ip_address", "label": "IP Address", "type": "text", "required": True, "placeholder": "192.168.1.1"},
            {"key": "subnet_mask", "label": "Subnet Mask / Prefix", "type": "text", "required": True, "placeholder": "255.255.255.0",
             "platform_hints": {
                 "cisco_ios": "255.255.255.0",
                 "cisco_nxos": "255.255.255.0",
                 "cisco_iosxr": "24",
                 "huawei_vrp": "255.255.255.0",
                 "h3c_comware": "255.255.255.0",
                 "arista_eos": "255.255.255.0",
                 "juniper_junos": "24",
             }},
            {"key": "description", "label": "Description", "type": "text", "required": False, "placeholder": "Uplink to Core"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": ["show interfaces {{interface}}", "show ip interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    "{% if description %} description {{description}}{% endif %}",
                    " ip address {{ip_address}} {{subnet_mask}}",
                    " no shutdown",
                ],
                "post_check": ["show ip interface {{interface}}", "ping {{ip_address}} repeat 3"],
                "rollback": ["interface {{interface}}", " no ip address"],
            },
            "cisco_nxos": {
                "pre_check": ["show interface {{interface}}", "show ip interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    " no switchport",
                    "{% if description %} description {{description}}{% endif %}",
                    " ip address {{ip_address}} {{subnet_mask}}",
                    " no shutdown",
                ],
                "post_check": ["show ip interface {{interface}}", "ping {{ip_address}} count 3"],
                "rollback": ["interface {{interface}}", " no ip address"],
            },
            "cisco_iosxr": {
                "pre_check": ["show interfaces {{interface}}", "show ipv4 interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    "{% if description %} description {{description}}{% endif %}",
                    " ipv4 address {{ip_address}}/{{subnet_mask}}",
                    " no shutdown",
                    " commit",
                ],
                "post_check": ["show ipv4 interface {{interface}}", "ping {{ip_address}} count 3"],
                "rollback": ["interface {{interface}}", " no ipv4 address", " commit"],
            },
            "huawei_vrp": {
                "pre_check": ["display interface {{interface}}", "display ip interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    "{% if description %} description {{description}}{% endif %}",
                    " ip address {{ip_address}} {{subnet_mask}}",
                    " undo shutdown",
                    " quit",
                ],
                "post_check": ["display ip interface {{interface}}", "ping -c 3 {{ip_address}}"],
                "rollback": ["interface {{interface}}", " undo ip address", " quit"],
            },
            "h3c_comware": {
                "pre_check": ["display interface {{interface}}", "display ip interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    "{% if description %} description {{description}}{% endif %}",
                    " ip address {{ip_address}} {{subnet_mask}}",
                    " undo shutdown",
                    " quit",
                ],
                "post_check": ["display ip interface {{interface}}", "ping -c 3 {{ip_address}}"],
                "rollback": ["interface {{interface}}", " undo ip address", " quit"],
            },
            "arista_eos": {
                "pre_check": ["show interfaces {{interface}}", "show ip interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    "{% if description %} description {{description}}{% endif %}",
                    " ip address {{ip_address}}/{{subnet_mask}}",
                    " no shutdown",
                ],
                "post_check": ["show ip interface {{interface}}", "ping {{ip_address}} repeat 3"],
                "rollback": ["interface {{interface}}", " no ip address"],
            },
            "juniper_junos": {
                "pre_check": ["show interfaces {{interface}}", "show interfaces {{interface}} detail"],
                "execute": [
                    "set interfaces {{interface}} unit 0 family inet address {{ip_address}}/{{subnet_mask}}",
                    "{% if description %}set interfaces {{interface}} description \"{{description}}\"{% endif %}",
                    "delete interfaces {{interface}} disable",
                ],
                "post_check": ["show interfaces {{interface}} terse", "ping {{ip_address}} count 3 rapid"],
                "rollback": ["delete interfaces {{interface}} unit 0 family inet address {{ip_address}}/{{subnet_mask}}"],
            },
        },
    },

    # ── 12. Port Security ─────────────────────────────────────
    {
        "id": "port-security",
        "name": "Port Security",
        "name_zh": "端口安全配置",
        "description": "Enable port security on access interfaces to limit MAC addresses",
        "description_zh": "在接入端口启用端口安全，限制 MAC 地址数量",
        "category": "Security",
        "icon": "🔐",
        "risk": "medium",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "interface", "label": "Interface", "type": "text", "required": True,
             "placeholder": "GigabitEthernet0/1",
             "platform_hints": {
                 "cisco_ios": "GigabitEthernet0/1",
                 "cisco_nxos": "Ethernet1/1",
                 "huawei_vrp": "GE0/0/1",
                 "h3c_comware": "GE1/0/1",
             }},
            {"key": "max_mac", "label": "Max MAC Addresses", "type": "number", "required": True, "placeholder": "3"},
            {"key": "violation", "label": "Violation Action", "type": "select", "required": True,
             "options": ["shutdown", "restrict", "protect"], "placeholder": "shutdown"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": ["show port-security interface {{interface}}", "show mac address-table interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    " switchport mode access",
                    " switchport port-security",
                    " switchport port-security maximum {{max_mac}}",
                    " switchport port-security violation {{violation}}",
                    " switchport port-security mac-address sticky",
                ],
                "post_check": ["show port-security interface {{interface}}", "show port-security"],
                "rollback": [
                    "interface {{interface}}",
                    " no switchport port-security",
                    " no switchport port-security maximum",
                    " no switchport port-security violation",
                ],
            },
            "cisco_nxos": {
                "pre_check": ["show port-security interface {{interface}}", "show port-security"],
                "execute": [
                    "interface {{interface}}",
                    " switchport",
                    " switchport mode access",
                    " switchport port-security",
                    " switchport port-security maximum {{max_mac}}",
                    " switchport port-security violation {{violation}}",
                    " switchport port-security mac-address sticky",
                ],
                "post_check": ["show port-security interface {{interface}}", "show port-security"],
                "rollback": [
                    "interface {{interface}}",
                    " no switchport port-security",
                ],
            },
            "huawei_vrp": {
                "pre_check": ["display port-security interface {{interface}}", "display mac-address interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    " port-security enable",
                    " port-security max-mac-num {{max_mac}}",
                    " port-security action {% if violation == 'shutdown' %}shutdown{% elif violation == 'restrict' %}restrict{% else %}protect{% endif %}",
                    " quit",
                ],
                "post_check": ["display port-security interface {{interface}}", "display port-security"],
                "rollback": [
                    "interface {{interface}}",
                    " undo port-security enable",
                    " quit",
                ],
            },
            "h3c_comware": {
                "pre_check": ["display port-security interface {{interface}}", "display mac-address interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    " port-security enable",
                    " port-security max-mac-count {{max_mac}}",
                    " port-security violation-mode {% if violation == 'shutdown' %}shutdown{% elif violation == 'restrict' %}restrict{% else %}protect{% endif %}",
                    " quit",
                ],
                "post_check": ["display port-security interface {{interface}}", "display port-security"],
                "rollback": [
                    "interface {{interface}}",
                    " undo port-security enable",
                    " quit",
                ],
            },
        },
    },

    # ── 13. SSH Hardening ─────────────────────────────────────
    {
        "id": "ssh-harden",
        "name": "SSH / Management Hardening",
        "name_zh": "SSH 管理安全加固",
        "description": "Disable Telnet, enforce SSH v2, set timeout and retry limits",
        "description_zh": "禁用 Telnet、强制 SSH v2、设置超时和重试限制",
        "category": "Security",
        "icon": "🔑",
        "risk": "medium",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "domain_name", "label": "Domain Name (for RSA key)", "type": "text", "required": False, "placeholder": "netops.local"},
            {"key": "ssh_timeout", "label": "SSH Timeout (seconds)", "type": "number", "required": True, "placeholder": "60"},
            {"key": "max_retries", "label": "Max Auth Retries", "type": "number", "required": True, "placeholder": "3"},
            {"key": "acl_name", "label": "Management ACL (optional)", "type": "text", "required": False, "placeholder": "MGMT_ACCESS"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": ["show ip ssh", "show line vty 0 4"],
                "execute": [
                    "{% if domain_name %}ip domain-name {{domain_name}}\ncrypto key generate rsa modulus 2048{% endif %}",
                    "ip ssh version 2",
                    "ip ssh time-out {{ssh_timeout}}",
                    "ip ssh authentication-retries {{max_retries}}",
                    "line vty 0 15",
                    " transport input ssh",
                    " exec-timeout {{ssh_timeout}} 0",
                    " login local",
                    "{% if acl_name %} access-class {{acl_name}} in{% endif %}",
                    "no service telnet",
                ],
                "post_check": ["show ip ssh", "show line vty 0 4"],
                "rollback": [
                    "line vty 0 15",
                    " transport input telnet ssh",
                    " no exec-timeout",
                ],
            },
            "cisco_nxos": {
                "pre_check": ["show ssh server", "show line"],
                "execute": [
                    "ssh key rsa 2048",
                    "feature ssh",
                    "no feature telnet",
                    "ip ssh server session-limit 10",
                ],
                "post_check": ["show ssh server", "show feature"],
                "rollback": ["feature telnet", "no ip ssh server session-limit"],
            },
            "huawei_vrp": {
                "pre_check": ["display ssh server status", "display user-interface vty 0 4"],
                "execute": [
                    "ssh server enable",
                    "ssh server timeout {{ssh_timeout}}",
                    "ssh server authentication-retries {{max_retries}}",
                    "user-interface vty 0 4",
                    " authentication-mode aaa",
                    " protocol inbound ssh",
                    "{% if acl_name %} acl inbound {{acl_name}}{% endif %}",
                    " quit",
                    "undo telnet server enable",
                ],
                "post_check": ["display ssh server status", "display user-interface vty 0 4 verbose"],
                "rollback": [
                    "user-interface vty 0 4",
                    " protocol inbound all",
                    " quit",
                    "telnet server enable",
                ],
            },
            "h3c_comware": {
                "pre_check": ["display ssh server", "display user-interface vty 0 4"],
                "execute": [
                    "ssh server enable",
                    "ssh server timeout {{ssh_timeout}}",
                    "ssh server authentication-retries {{max_retries}}",
                    "user-interface vty 0 4",
                    " authentication-mode scheme",
                    " protocol inbound ssh",
                    "{% if acl_name %} acl {{acl_name}} inbound{% endif %}",
                    " quit",
                    "undo telnet server enable",
                ],
                "post_check": ["display ssh server", "display user-interface vty 0 4"],
                "rollback": [
                    "user-interface vty 0 4",
                    " protocol inbound all",
                    " quit",
                    "telnet server enable",
                ],
            },
            "arista_eos": {
                "pre_check": ["show management ssh", "show management telnet"],
                "execute": [
                    "management ssh",
                    " idle-timeout {{ssh_timeout}}",
                    " authentication-retries {{max_retries}}",
                    " no shutdown",
                    "management telnet",
                    " shutdown",
                ],
                "post_check": ["show management ssh", "show management telnet"],
                "rollback": [
                    "management telnet",
                    " no shutdown",
                ],
            },
            "juniper_junos": {
                "pre_check": ["show system services", "show system login"],
                "execute": [
                    "set system services ssh protocol-version v2",
                    "set system services ssh connection-limit 10",
                    "set system services ssh rate-limit {{max_retries}}",
                    "delete system services telnet",
                    "delete system services ftp",
                ],
                "post_check": ["show system services", "show system connections"],
                "rollback": [
                    "set system services telnet",
                    "delete system services ssh protocol-version",
                ],
            },
        },
    },

    # ── 14. HSRP / VRRP Gateway Redundancy ───────────────────
    {
        "id": "hsrp-vrrp",
        "name": "HSRP / VRRP Gateway Redundancy",
        "name_zh": "HSRP/VRRP 网关冗余",
        "description": "Configure gateway redundancy protocol for high availability",
        "description_zh": "配置网关冗余协议，实现默认网关高可用",
        "category": "L3",
        "icon": "⚡",
        "risk": "high",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware", "arista_eos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "interface", "label": "Interface", "type": "text", "required": True, "placeholder": "Vlan10"},
            {"key": "group_id", "label": "Group ID", "type": "number", "required": True, "placeholder": "10"},
            {"key": "virtual_ip", "label": "Virtual IP", "type": "text", "required": True, "placeholder": "192.168.10.254"},
            {"key": "priority", "label": "Priority (default 100)", "type": "number", "required": False, "placeholder": "110"},
            {"key": "preempt", "label": "Enable Preempt", "type": "select", "required": True, "options": ["yes", "no"], "placeholder": "yes"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": ["show standby brief", "show interfaces {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    " standby version 2",
                    " standby {{group_id}} ip {{virtual_ip}}",
                    "{% if priority %} standby {{group_id}} priority {{priority}}{% endif %}",
                    "{% if preempt == 'yes' %} standby {{group_id}} preempt{% endif %}",
                    " standby {{group_id}} timers 2 6",
                ],
                "post_check": ["show standby brief", "show standby {{group_id}}"],
                "rollback": [
                    "interface {{interface}}",
                    " no standby {{group_id}}",
                ],
            },
            "cisco_nxos": {
                "pre_check": ["show hsrp brief", "show interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    " hsrp version 2",
                    " hsrp {{group_id}}",
                    "  ip {{virtual_ip}}",
                    "{% if priority %}  priority {{priority}}{% endif %}",
                    "{% if preempt == 'yes' %}  preempt{% endif %}",
                    "  timers 2 6",
                ],
                "post_check": ["show hsrp brief", "show hsrp {{group_id}}"],
                "rollback": [
                    "interface {{interface}}",
                    " no hsrp {{group_id}}",
                ],
            },
            "huawei_vrp": {
                "pre_check": ["display vrrp brief", "display interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    " vrrp vrid {{group_id}} virtual-ip {{virtual_ip}}",
                    "{% if priority %} vrrp vrid {{group_id}} priority {{priority}}{% endif %}",
                    "{% if preempt == 'yes' %} vrrp vrid {{group_id}} preempt-mode timer delay 0{% endif %}",
                    " vrrp vrid {{group_id}} timer advertise 2",
                    " quit",
                ],
                "post_check": ["display vrrp brief", "display vrrp interface {{interface}} verbose"],
                "rollback": [
                    "interface {{interface}}",
                    " undo vrrp vrid {{group_id}}",
                    " quit",
                ],
            },
            "h3c_comware": {
                "pre_check": ["display vrrp brief", "display interface {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    " vrrp vrid {{group_id}} virtual-ip {{virtual_ip}}",
                    "{% if priority %} vrrp vrid {{group_id}} priority {{priority}}{% endif %}",
                    "{% if preempt == 'yes' %} vrrp vrid {{group_id}} preempt-mode timer delay 0{% endif %}",
                    " quit",
                ],
                "post_check": ["display vrrp brief", "display vrrp interface {{interface}} verbose"],
                "rollback": [
                    "interface {{interface}}",
                    " undo vrrp vrid {{group_id}}",
                    " quit",
                ],
            },
            "arista_eos": {
                "pre_check": ["show vrrp brief", "show interfaces {{interface}}"],
                "execute": [
                    "interface {{interface}}",
                    " vrrp {{group_id}} ip {{virtual_ip}}",
                    "{% if priority %} vrrp {{group_id}} priority {{priority}}{% endif %}",
                    "{% if preempt == 'yes' %} vrrp {{group_id}} preempt{% endif %}",
                    " vrrp {{group_id}} timers advertise 2",
                ],
                "post_check": ["show vrrp brief", "show vrrp interface {{interface}}"],
                "rollback": [
                    "interface {{interface}}",
                    " no vrrp {{group_id}}",
                ],
            },
        },
    },

    # ── 15. DHCP Pool Configuration ───────────────────────────
    {
        "id": "dhcp-pool",
        "name": "DHCP Pool Configuration",
        "name_zh": "DHCP 地址池配置",
        "description": "Configure DHCP pool with gateway, DNS and lease time",
        "description_zh": "配置 DHCP 地址池，含网关、DNS 和租约时间",
        "category": "L3",
        "icon": "🏊",
        "risk": "low",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "pool_name", "label": "Pool Name", "type": "text", "required": True, "placeholder": "VLAN10_POOL"},
            {"key": "network", "label": "Network", "type": "text", "required": True, "placeholder": "192.168.10.0"},
            {"key": "mask", "label": "Subnet Mask", "type": "text", "required": True, "placeholder": "255.255.255.0"},
            {"key": "gateway", "label": "Default Gateway", "type": "text", "required": True, "placeholder": "192.168.10.1"},
            {"key": "dns_server", "label": "DNS Server", "type": "text", "required": False, "placeholder": "8.8.8.8"},
            {"key": "lease_days", "label": "Lease Days", "type": "number", "required": False, "placeholder": "7"},
            {"key": "exclude_start", "label": "Exclude Range Start", "type": "text", "required": False, "placeholder": "192.168.10.1"},
            {"key": "exclude_end", "label": "Exclude Range End", "type": "text", "required": False, "placeholder": "192.168.10.20"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": ["show ip dhcp pool", "show ip dhcp binding"],
                "execute": [
                    "{% if exclude_start %}ip dhcp excluded-address {{exclude_start}} {% if exclude_end %}{{exclude_end}}{% else %}{{exclude_start}}{% endif %}{% endif %}",
                    "ip dhcp pool {{pool_name}}",
                    " network {{network}} {{mask}}",
                    " default-router {{gateway}}",
                    "{% if dns_server %} dns-server {{dns_server}}{% endif %}",
                    "{% if lease_days %} lease {{lease_days}}{% else %} lease 7{% endif %}",
                ],
                "post_check": ["show ip dhcp pool {{pool_name}}", "show ip dhcp binding", "show ip dhcp statistics"],
                "rollback": [
                    "no ip dhcp pool {{pool_name}}",
                    "{% if exclude_start %}no ip dhcp excluded-address {{exclude_start}} {% if exclude_end %}{{exclude_end}}{% else %}{{exclude_start}}{% endif %}{% endif %}",
                ],
            },
            "cisco_nxos": {
                "pre_check": ["show ip dhcp relay statistics", "show ip dhcp binding"],
                "execute": [
                    "service dhcp",
                    "ip dhcp pool {{pool_name}}",
                    " network {{network}} {{mask}}",
                    " default-router {{gateway}}",
                    "{% if dns_server %} dns-server {{dns_server}}{% endif %}",
                    "{% if lease_days %} lease {{lease_days}}{% else %} lease 7{% endif %}",
                ],
                "post_check": ["show ip dhcp binding", "show ip dhcp statistics"],
                "rollback": ["no ip dhcp pool {{pool_name}}"],
            },
            "huawei_vrp": {
                "pre_check": ["display dhcp server pool all", "display dhcp server statistics"],
                "execute": [
                    "dhcp enable",
                    "ip pool {{pool_name}}",
                    " network {{network}} mask {{mask}}",
                    " gateway-list {{gateway}}",
                    "{% if dns_server %} dns-list {{dns_server}}{% endif %}",
                    "{% if lease_days %} lease day {{lease_days}}{% endif %}",
                    "{% if exclude_start %} excluded-ip-address {{exclude_start}} {% if exclude_end %}{{exclude_end}}{% else %}{{exclude_start}}{% endif %}{% endif %}",
                    " quit",
                ],
                "post_check": ["display dhcp server pool {{pool_name}}", "display dhcp server statistics"],
                "rollback": ["undo ip pool {{pool_name}}"],
            },
            "h3c_comware": {
                "pre_check": ["display dhcp server pool all", "display dhcp server statistics"],
                "execute": [
                    "dhcp server ip-pool {{pool_name}}",
                    " network {{network}} mask {{mask}}",
                    " gateway-list {{gateway}}",
                    "{% if dns_server %} dns-list {{dns_server}}{% endif %}",
                    "{% if lease_days %} expired day {{lease_days}}{% endif %}",
                    "{% if exclude_start %} excluded-ip-address {{exclude_start}} {% if exclude_end %}{{exclude_end}}{% else %}{{exclude_start}}{% endif %}{% endif %}",
                    " quit",
                ],
                "post_check": ["display dhcp server pool {{pool_name}}", "display dhcp server statistics"],
                "rollback": ["undo dhcp server ip-pool {{pool_name}}"],
            },
        },
    },

    # ── 16. STP Security (BPDU Guard + Root Guard) ────────────
    {
        "id": "stp-security",
        "name": "STP Security Hardening",
        "name_zh": "STP 安全加固",
        "description": "Enable BPDU Guard on access ports, Root Guard on uplinks",
        "description_zh": "接入端口开启 BPDU Guard，上行端口开启 Root Guard",
        "category": "L2",
        "icon": "🌲",
        "risk": "medium",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "access_interfaces", "label": "Access Interfaces (BPDU Guard)", "type": "text", "required": False,
             "placeholder": "GigabitEthernet0/1,GigabitEthernet0/2",
             "platform_hints": {
                 "cisco_ios": "GigabitEthernet0/1,GigabitEthernet0/2",
                 "cisco_nxos": "Ethernet1/1,Ethernet1/2",
                 "huawei_vrp": "GE0/0/1,GE0/0/2",
                 "h3c_comware": "GE1/0/1,GE1/0/2",
             }},
            {"key": "uplink_interfaces", "label": "Uplink Interfaces (Root Guard)", "type": "text", "required": False,
             "placeholder": "GigabitEthernet0/24",
             "platform_hints": {
                 "cisco_ios": "GigabitEthernet0/24",
                 "cisco_nxos": "Ethernet1/48",
                 "huawei_vrp": "GE0/0/24",
                 "h3c_comware": "GE1/0/24",
             }},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": ["show spanning-tree summary", "show spanning-tree detail"],
                "execute": [
                    "spanning-tree portfast bpduguard default",
                    "{% if access_interfaces %}{% for intf in access_interfaces.split(',') %}interface {{intf.strip()}}\n spanning-tree portfast\n spanning-tree bpduguard enable\n{% endfor %}{% endif %}",
                    "{% if uplink_interfaces %}{% for intf in uplink_interfaces.split(',') %}interface {{intf.strip()}}\n spanning-tree guard root\n{% endfor %}{% endif %}",
                ],
                "post_check": ["show spanning-tree summary", "show spanning-tree inconsistentports"],
                "rollback": [
                    "no spanning-tree portfast bpduguard default",
                    "{% if access_interfaces %}{% for intf in access_interfaces.split(',') %}interface {{intf.strip()}}\n no spanning-tree bpduguard enable\n{% endfor %}{% endif %}",
                    "{% if uplink_interfaces %}{% for intf in uplink_interfaces.split(',') %}interface {{intf.strip()}}\n no spanning-tree guard root\n{% endfor %}{% endif %}",
                ],
            },
            "cisco_nxos": {
                "pre_check": ["show spanning-tree summary", "show spanning-tree detail"],
                "execute": [
                    "spanning-tree portfast bpduguard default",
                    "{% if access_interfaces %}{% for intf in access_interfaces.split(',') %}interface {{intf.strip()}}\n spanning-tree port type edge\n spanning-tree bpduguard enable\n{% endfor %}{% endif %}",
                    "{% if uplink_interfaces %}{% for intf in uplink_interfaces.split(',') %}interface {{intf.strip()}}\n spanning-tree guard root\n{% endfor %}{% endif %}",
                ],
                "post_check": ["show spanning-tree summary", "show spanning-tree inconsistentports"],
                "rollback": [
                    "no spanning-tree portfast bpduguard default",
                    "{% if access_interfaces %}{% for intf in access_interfaces.split(',') %}interface {{intf.strip()}}\n no spanning-tree bpduguard enable\n{% endfor %}{% endif %}",
                ],
            },
            "huawei_vrp": {
                "pre_check": ["display stp brief", "display stp abnormal-port"],
                "execute": [
                    "{% if access_interfaces %}{% for intf in access_interfaces.split(',') %}interface {{intf.strip()}}\n stp edged-port enable\n stp bpdu-protection\n quit\n{% endfor %}{% endif %}",
                    "{% if uplink_interfaces %}{% for intf in uplink_interfaces.split(',') %}interface {{intf.strip()}}\n stp root-protection\n quit\n{% endfor %}{% endif %}",
                ],
                "post_check": ["display stp brief", "display stp abnormal-port"],
                "rollback": [
                    "{% if access_interfaces %}{% for intf in access_interfaces.split(',') %}interface {{intf.strip()}}\n undo stp edged-port\n undo stp bpdu-protection\n quit\n{% endfor %}{% endif %}",
                    "{% if uplink_interfaces %}{% for intf in uplink_interfaces.split(',') %}interface {{intf.strip()}}\n undo stp root-protection\n quit\n{% endfor %}{% endif %}",
                ],
            },
            "h3c_comware": {
                "pre_check": ["display stp brief", "display stp abnormal-port"],
                "execute": [
                    "{% if access_interfaces %}{% for intf in access_interfaces.split(',') %}interface {{intf.strip()}}\n stp edged-port enable\n stp bpdu-protection\n quit\n{% endfor %}{% endif %}",
                    "{% if uplink_interfaces %}{% for intf in uplink_interfaces.split(',') %}interface {{intf.strip()}}\n stp root-protection\n quit\n{% endfor %}{% endif %}",
                ],
                "post_check": ["display stp brief", "display stp abnormal-port"],
                "rollback": [
                    "{% if access_interfaces %}{% for intf in access_interfaces.split(',') %}interface {{intf.strip()}}\n undo stp edged-port\n undo stp bpdu-protection\n quit\n{% endfor %}{% endif %}",
                    "{% if uplink_interfaces %}{% for intf in uplink_interfaces.split(',') %}interface {{intf.strip()}}\n undo stp root-protection\n quit\n{% endfor %}{% endif %}",
                ],
            },
        },
    },

    # ── 17. AAA / RADIUS Authentication ──────────────────────
    {
        "id": "aaa-radius",
        "name": "AAA / RADIUS Authentication",
        "name_zh": "AAA / RADIUS 认证配置",
        "description": "Configure RADIUS server and AAA authentication for device login",
        "description_zh": "配置 RADIUS 服务器和 AAA 认证，用于设备登录统一认证",
        "category": "Security",
        "icon": "👤",
        "risk": "high",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware", "arista_eos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "radius_server", "label": "RADIUS Server IP", "type": "text", "required": True, "placeholder": "10.0.0.100"},
            {"key": "radius_key", "label": "Shared Secret", "type": "text", "required": True, "placeholder": ""},
            {"key": "radius_port_auth", "label": "Auth Port", "type": "number", "required": False, "placeholder": "1812"},
            {"key": "radius_port_acct", "label": "Acct Port", "type": "number", "required": False, "placeholder": "1813"},
            {"key": "local_fallback", "label": "Local Fallback", "type": "select", "required": True, "options": ["yes", "no"], "placeholder": "yes"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": ["show aaa servers", "show radius server-group all"],
                "execute": [
                    "radius server NETOPS_RADIUS",
                    " address ipv4 {{radius_server}} auth-port {% if radius_port_auth %}{{radius_port_auth}}{% else %}1812{% endif %} acct-port {% if radius_port_acct %}{{radius_port_acct}}{% else %}1813{% endif %}",
                    " key 0 {{radius_key}}",
                    "aaa group server radius NETOPS_GROUP",
                    " server name NETOPS_RADIUS",
                    "aaa authentication login default group NETOPS_GROUP{% if local_fallback == 'yes' %} local{% endif %}",
                    "aaa authorization exec default group NETOPS_GROUP{% if local_fallback == 'yes' %} local{% endif %}",
                    "aaa accounting exec default start-stop group NETOPS_GROUP",
                ],
                "post_check": ["show aaa servers", "test aaa group NETOPS_GROUP admin admin legacy"],
                "rollback": [
                    "no aaa authentication login default",
                    "no aaa authorization exec default",
                    "no radius server NETOPS_RADIUS",
                    "aaa authentication login default local",
                ],
            },
            "cisco_nxos": {
                "pre_check": ["show aaa servers", "show radius-server"],
                "execute": [
                    "radius-server host {{radius_server}} auth-port {% if radius_port_auth %}{{radius_port_auth}}{% else %}1812{% endif %} acct-port {% if radius_port_acct %}{{radius_port_acct}}{% else %}1813{% endif %} key 0 {{radius_key}}",
                    "aaa group server radius NETOPS_GROUP",
                    " server {{radius_server}}",
                    "aaa authentication login default group NETOPS_GROUP{% if local_fallback == 'yes' %} local{% endif %}",
                    "aaa authorization exec default group NETOPS_GROUP{% if local_fallback == 'yes' %} local{% endif %}",
                ],
                "post_check": ["show aaa servers", "show radius-server"],
                "rollback": [
                    "no aaa authentication login default",
                    "no radius-server host {{radius_server}}",
                    "aaa authentication login default local",
                ],
            },
            "huawei_vrp": {
                "pre_check": ["display radius-server configuration all", "display aaa configuration"],
                "execute": [
                    "radius-server template NETOPS_RADIUS",
                    " radius-server authentication {{radius_server}} {% if radius_port_auth %}{{radius_port_auth}}{% else %}1812{% endif %} weight 80",
                    " radius-server accounting {{radius_server}} {% if radius_port_acct %}{{radius_port_acct}}{% else %}1813{% endif %} weight 80",
                    " radius-server shared-key cipher {{radius_key}}",
                    " quit",
                    "aaa",
                    " authentication-scheme NETOPS_AUTH",
                    "  authentication-mode radius{% if local_fallback == 'yes' %} local{% endif %}",
                    "  quit",
                    " domain default",
                    "  authentication-scheme NETOPS_AUTH",
                    "  radius-server NETOPS_RADIUS",
                    "  quit",
                    " quit",
                ],
                "post_check": ["display radius-server configuration all", "display aaa configuration"],
                "rollback": [
                    "aaa",
                    " domain default",
                    "  authentication-scheme default",
                    "  quit",
                    " quit",
                    "undo radius-server template NETOPS_RADIUS",
                ],
            },
            "h3c_comware": {
                "pre_check": ["display radius scheme all", "display domain all"],
                "execute": [
                    "radius scheme NETOPS_RADIUS",
                    " primary authentication {{radius_server}} {% if radius_port_auth %}{{radius_port_auth}}{% else %}1812{% endif %}",
                    " primary accounting {{radius_server}} {% if radius_port_acct %}{{radius_port_acct}}{% else %}1813{% endif %}",
                    " key authentication cipher {{radius_key}}",
                    " quit",
                    "domain default",
                    " authentication lan-access radius-scheme NETOPS_RADIUS{% if local_fallback == 'yes' %} local{% endif %}",
                    " authorization lan-access radius-scheme NETOPS_RADIUS{% if local_fallback == 'yes' %} local{% endif %}",
                    " accounting lan-access radius-scheme NETOPS_RADIUS",
                    " quit",
                ],
                "post_check": ["display radius scheme all", "display domain default"],
                "rollback": [
                    "domain default",
                    " authentication lan-access local",
                    " quit",
                    "undo radius scheme NETOPS_RADIUS",
                ],
            },
            "arista_eos": {
                "pre_check": ["show aaa", "show radius"],
                "execute": [
                    "radius-server host {{radius_server}} key 0 {{radius_key}}",
                    "aaa group server radius NETOPS_GROUP",
                    " server {{radius_server}}",
                    "aaa authentication login default group NETOPS_GROUP{% if local_fallback == 'yes' %} local{% endif %}",
                    "aaa authorization exec default group NETOPS_GROUP{% if local_fallback == 'yes' %} local{% endif %}",
                ],
                "post_check": ["show aaa", "show radius"],
                "rollback": [
                    "no aaa authentication login default",
                    "no radius-server host {{radius_server}}",
                    "aaa authentication login default local",
                ],
            },
        },
    },

    # ── 18. QoS Policy Configuration ─────────────────────────
    {
        "id": "qos-policy",
        "name": "QoS Traffic Shaping Policy",
        "name_zh": "QoS 流量整形策略",
        "description": "Configure QoS classification, shaping and queuing policy",
        "description_zh": "配置 QoS 流量分类、整形和队列策略",
        "category": "Operations",
        "icon": "📊",
        "risk": "medium",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp", "h3c_comware"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "policy_name", "label": "Policy Name", "type": "text", "required": True, "placeholder": "VOIP_QOS"},
            {"key": "interface", "label": "Apply to Interface", "type": "text", "required": True, "placeholder": "GigabitEthernet0/1"},
            {"key": "priority_dscp", "label": "Priority Traffic DSCP (e.g. EF)", "type": "text", "required": False, "placeholder": "ef"},
            {"key": "priority_bw_pct", "label": "Priority Bandwidth %", "type": "number", "required": False, "placeholder": "30"},
            {"key": "default_bw_pct", "label": "Default Class Bandwidth %", "type": "number", "required": False, "placeholder": "50"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": ["show policy-map", "show policy-map interface {{interface}}"],
                "execute": [
                    "class-map match-all PRIORITY_CLASS",
                    "{% if priority_dscp %} match dscp {{priority_dscp}}{% else %} match dscp ef{% endif %}",
                    "policy-map {{policy_name}}",
                    " class PRIORITY_CLASS",
                    "  priority percent {% if priority_bw_pct %}{{priority_bw_pct}}{% else %}30{% endif %}",
                    " class class-default",
                    "  bandwidth percent {% if default_bw_pct %}{{default_bw_pct}}{% else %}50{% endif %}",
                    "  fair-queue",
                    "interface {{interface}}",
                    " service-policy output {{policy_name}}",
                ],
                "post_check": [
                    "show policy-map {{policy_name}}",
                    "show policy-map interface {{interface}}",
                ],
                "rollback": [
                    "interface {{interface}}",
                    " no service-policy output {{policy_name}}",
                    "no policy-map {{policy_name}}",
                    "no class-map match-all PRIORITY_CLASS",
                ],
            },
            "cisco_nxos": {
                "pre_check": ["show policy-map", "show policy-map interface {{interface}}"],
                "execute": [
                    "class-map type qos match-all PRIORITY_CLASS",
                    "{% if priority_dscp %} match dscp {{priority_dscp}}{% else %} match dscp ef{% endif %}",
                    "policy-map type qos {{policy_name}}",
                    " class PRIORITY_CLASS",
                    "  set qos-group 1",
                    " class class-default",
                    "  set qos-group 0",
                    "interface {{interface}}",
                    " service-policy type qos input {{policy_name}}",
                ],
                "post_check": ["show policy-map {{policy_name}}", "show policy-map interface {{interface}}"],
                "rollback": [
                    "interface {{interface}}",
                    " no service-policy type qos input {{policy_name}}",
                    "no policy-map type qos {{policy_name}}",
                ],
            },
            "huawei_vrp": {
                "pre_check": ["display qos policy user-defined", "display qos policy interface {{interface}}"],
                "execute": [
                    "traffic classifier PRIORITY_CLASS operator or",
                    "{% if priority_dscp %} if-match dscp {{priority_dscp}}{% else %} if-match dscp ef{% endif %}",
                    " quit",
                    "traffic behavior PRIORITY_ACTION",
                    " car cir 1000 pir 2000 cbs 187500 pbs 375000 green pass yellow pass red discard",
                    " quit",
                    "traffic policy {{policy_name}}",
                    " classifier PRIORITY_CLASS behavior PRIORITY_ACTION",
                    " quit",
                    "interface {{interface}}",
                    " traffic-policy {{policy_name}} outbound",
                    " quit",
                ],
                "post_check": ["display qos policy interface {{interface}}", "display traffic-policy applied-record"],
                "rollback": [
                    "interface {{interface}}",
                    " undo traffic-policy outbound",
                    " quit",
                    "undo traffic policy {{policy_name}}",
                ],
            },
            "h3c_comware": {
                "pre_check": ["display qos policy user-defined", "display qos policy interface {{interface}}"],
                "execute": [
                    "traffic classifier PRIORITY_CLASS operator and",
                    "{% if priority_dscp %} if-match dscp {{priority_dscp}}{% else %} if-match dscp ef{% endif %}",
                    " quit",
                    "traffic behavior PRIORITY_ACTION",
                    " car cir 1000 pir 2000",
                    " quit",
                    "qos policy {{policy_name}}",
                    " classifier PRIORITY_CLASS behavior PRIORITY_ACTION",
                    " quit",
                    "interface {{interface}}",
                    " qos apply policy {{policy_name}} outbound",
                    " quit",
                ],
                "post_check": ["display qos policy interface {{interface}}", "display traffic-policy applied-record"],
                "rollback": [
                    "interface {{interface}}",
                    " undo qos apply policy outbound",
                    " quit",
                    "undo qos policy {{policy_name}}",
                ],
            },
        },
    },

    # ── 19. Banner MOTD Configuration ────────────────────────
    {
        "id": "banner-motd",
        "name": "Banner / MOTD Configuration",
        "name_zh": "Banner / MOTD 横幅配置",
        "description": "Configure login warning banner (MOTD) for compliance",
        "description_zh": "配置登录警告横幅（MOTD），满足合规要求",
        "category": "Operations",
        "icon": "📢",
        "risk": "low",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "cisco_iosxr", "huawei_vrp", "h3c_comware", "arista_eos", "juniper_junos"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "banner_text", "label": "Banner Text", "type": "textarea", "required": True,
             "placeholder": "WARNING: Authorized access only. Unauthorized access is prohibited and subject to criminal prosecution."},
            {"key": "contact_email", "label": "Contact Email (optional)", "type": "text", "required": False, "placeholder": "noc@company.com"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": ["show banner motd"],
                "execute": [
                    "banner motd ^C\n{{banner_text}}\n{% if contact_email %}Contact: {{contact_email}}{% endif %}\n^C",
                ],
                "post_check": ["show banner motd", "show banner login"],
                "rollback": ["no banner motd"],
            },
            "cisco_nxos": {
                "pre_check": ["show banner motd"],
                "execute": [
                    "banner motd ^C\n{{banner_text}}\n{% if contact_email %}Contact: {{contact_email}}{% endif %}\n^C",
                ],
                "post_check": ["show banner motd"],
                "rollback": ["no banner motd"],
            },
            "cisco_iosxr": {
                "pre_check": ["show banner"],
                "execute": [
                    "banner motd ^C\n{{banner_text}}\n{% if contact_email %}Contact: {{contact_email}}{% endif %}\n^C",
                    "commit",
                ],
                "post_check": ["show banner"],
                "rollback": ["no banner motd", "commit"],
            },
            "huawei_vrp": {
                "pre_check": ["display header"],
                "execute": [
                    "header login information \"{{banner_text}}{% if contact_email %} | Contact: {{contact_email}}{% endif %}\"",
                    "header shell information \"{{banner_text}}{% if contact_email %} | Contact: {{contact_email}}{% endif %}\"",
                ],
                "post_check": ["display header"],
                "rollback": ["undo header login", "undo header shell"],
            },
            "h3c_comware": {
                "pre_check": ["display header"],
                "execute": [
                    "header login information \"{{banner_text}}{% if contact_email %} | Contact: {{contact_email}}{% endif %}\"",
                    "header shell information \"{{banner_text}}{% if contact_email %} | Contact: {{contact_email}}{% endif %}\"",
                ],
                "post_check": ["display header"],
                "rollback": ["undo header login", "undo header shell"],
            },
            "arista_eos": {
                "pre_check": ["show banner login"],
                "execute": [
                    "banner login\n{{banner_text}}\n{% if contact_email %}Contact: {{contact_email}}{% endif %}\nEOF",
                    "banner motd\n{{banner_text}}\n{% if contact_email %}Contact: {{contact_email}}{% endif %}\nEOF",
                ],
                "post_check": ["show banner login", "show banner motd"],
                "rollback": ["no banner login", "no banner motd"],
            },
            "juniper_junos": {
                "pre_check": ["show system login message"],
                "execute": [
                    "set system login message \"{{banner_text}}{% if contact_email %} | Contact: {{contact_email}}{% endif %}\"",
                ],
                "post_check": ["show system login message"],
                "rollback": ["delete system login message"],
            },
        },
    },

    # ── 20. IP SLA / Connectivity Monitoring ─────────────────
    {
        "id": "ipsla-monitor",
        "name": "IP SLA Connectivity Monitor",
        "name_zh": "IP SLA 连通性监控",
        "description": "Configure IP SLA probe and track object for link monitoring",
        "description_zh": "配置 IP SLA 探测和 Track 对象，实现链路连通性监控",
        "category": "Operations",
        "icon": "📡",
        "risk": "low",
        "supported_platforms": ["cisco_ios", "cisco_nxos", "huawei_vrp"],
        "default_platform": "cisco_ios",
        "variables": [
            {"key": "sla_id", "label": "SLA ID / Track ID", "type": "number", "required": True, "placeholder": "1"},
            {"key": "target_ip", "label": "Target IP to Probe", "type": "text", "required": True, "placeholder": "8.8.8.8"},
            {"key": "interval_sec", "label": "Probe Interval (seconds)", "type": "number", "required": False, "placeholder": "30"},
            {"key": "timeout_ms", "label": "Timeout (milliseconds)", "type": "number", "required": False, "placeholder": "5000"},
        ],
        "platform_phases": {
            "cisco_ios": {
                "pre_check": ["show ip sla summary", "show track brief"],
                "execute": [
                    "ip sla {{sla_id}}",
                    " icmp-echo {{target_ip}}",
                    " frequency {% if interval_sec %}{{interval_sec}}{% else %}30{% endif %}",
                    " timeout {% if timeout_ms %}{{timeout_ms}}{% else %}5000{% endif %}",
                    "ip sla schedule {{sla_id}} life forever start-time now",
                    "track {{sla_id}} ip sla {{sla_id}} reachability",
                ],
                "post_check": ["show ip sla statistics {{sla_id}}", "show track {{sla_id}}"],
                "rollback": [
                    "no track {{sla_id}}",
                    "no ip sla {{sla_id}}",
                ],
            },
            "cisco_nxos": {
                "pre_check": ["show ip sla summary", "show track brief"],
                "execute": [
                    "ip sla {{sla_id}}",
                    " icmp-echo {{target_ip}}",
                    " frequency {% if interval_sec %}{{interval_sec}}{% else %}30{% endif %}",
                    "ip sla schedule {{sla_id}} life forever start-time now",
                    "track {{sla_id}} ip sla {{sla_id}} reachability",
                ],
                "post_check": ["show ip sla statistics {{sla_id}}", "show track {{sla_id}}"],
                "rollback": [
                    "no track {{sla_id}}",
                    "no ip sla {{sla_id}}",
                ],
            },
            "huawei_vrp": {
                "pre_check": ["display nqa results all", "display nqa session all"],
                "execute": [
                    "nqa test-instance admin sla_{{sla_id}}",
                    " test-type icmp",
                    " destination-address ipv4 {{target_ip}}",
                    " frequency {% if interval_sec %}{{interval_sec}}{% else %}30{% endif %}",
                    " timeout {% if timeout_ms %}{{timeout_ms}}{% else %}5000{% endif %}",
                    " start now",
                    " quit",
                ],
                "post_check": ["display nqa results admin sla_{{sla_id}}", "display nqa history admin sla_{{sla_id}}"],
                "rollback": ["undo nqa test-instance admin sla_{{sla_id}}"],
            },
        },
    },
]

# ════════════════════════════════════════════════════════════════════
# WebSocket 连接管理
# ════════════════════════════════════════════════════════════════════

class ConnectionManager:
    """Manages per-execution WebSocket connections."""
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, execution_id: str, ws: WebSocket):
        await ws.accept()
        if execution_id not in self.connections:
            self.connections[execution_id] = []
        self.connections[execution_id].append(ws)

    def disconnect(self, execution_id: str, ws: WebSocket):
        if execution_id in self.connections:
            self.connections[execution_id] = [
                c for c in self.connections[execution_id] if c is not ws
            ]
            if not self.connections[execution_id]:
                del self.connections[execution_id]

    async def emit(self, execution_id: str, event: dict):
        """Send event to all WebSocket subscribers of this execution."""
        if execution_id not in self.connections:
            return
        dead = []
        for ws in self.connections[execution_id]:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(execution_id, ws)

ws_manager = ConnectionManager()

# ════════════════════════════════════════════════════════════════════
# 简单 Jinja-like 模板渲染：{{var}}、{% if %}、{% for %}
# ════════════════════════════════════════════════════════════════════

def _render_template(template: str, variables: dict) -> str:
    """Render playbook command templates using Jinja2 sandbox (safe, no eval)."""
    from jinja2.sandbox import SandboxedEnvironment
    env = SandboxedEnvironment()
    try:
        tmpl = env.from_string(template)
        return tmpl.render(**variables)
    except Exception:
        # Fallback: simple variable substitution only
        text = template
        for k, v in variables.items():
            text = text.replace('{{' + k + '}}', str(v))
        import re
        text = re.sub(r'\{%.*?%\}', '', text)
        text = re.sub(r'\{\{.*?\}\}', '', text)
        return text.strip()

def _save_snapshot(hostname: str, config_text: str) -> None:
    """将变更前的 running-config 保存到 backup/snapshots/ 目录。"""
    import os
    snap_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'backup', 'snapshots')
    os.makedirs(snap_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(snap_dir, f"{hostname}_{ts}_pre_change.txt")
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(config_text)
        logger.info(f"Pre-change snapshot saved: {filename}")
    except Exception as e:
        logger.warning(f"Failed to save snapshot for {hostname}: {e}")


def _render_phase_commands(phase_templates: list, variables: dict) -> list[str]:
    """Render a list of command templates into actual commands."""
    commands = []
    for tmpl in phase_templates:
        rendered = _render_template(tmpl, variables)
        # If the rendered block looks like a shell script, don't split it
        if rendered.strip().startswith('#!'):
            commands.append(rendered)
        else:
            for line in rendered.split('\n'):
                line = line.rstrip()
                if line:
                    commands.append(line)
    return commands

# ════════════════════════════════════════════════════════════════════
# API 端点
# ════════════════════════════════════════════════════════════════════

@router.get("/playbooks/platforms")
async def list_platforms():
    """Return all supported vendor/platform definitions."""
    return PLATFORMS


def _load_custom_scenarios() -> list[dict]:
    conn = get_db_connection()
    try:
        rows = conn.execute('SELECT data_json FROM custom_scenarios ORDER BY created_at DESC').fetchall()
        scenarios: list[dict] = []
        for row in rows:
            try:
                scenario = json.loads(row['data_json'])
                if isinstance(scenario, dict):
                    scenario['is_custom'] = True
                    scenarios.append(scenario)
            except Exception:
                continue
        return scenarios
    finally:
        conn.close()


def _all_scenarios() -> list[dict]:
    return [*BUILTIN_SCENARIOS, *_load_custom_scenarios()]

@router.get("/playbooks/scenarios")
async def list_scenarios():
    """Return built-in and custom scenario templates."""
    return _all_scenarios()


@router.post("/playbooks/scenarios", status_code=201)
async def create_custom_scenario(request: Request, payload: dict = Body(...)):
    scenario_id = (payload.get('id') or '').strip() or f"custom-{uuid.uuid4().hex[:10]}"
    name = (payload.get('name') or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail='Scenario name is required')

    supported_platforms = payload.get('supported_platforms') or []
    if not supported_platforms:
        raise HTTPException(status_code=400, detail='At least one supported platform is required')

    default_platform = payload.get('default_platform') or supported_platforms[0]
    platform_phases = payload.get('platform_phases') or {}
    if default_platform not in platform_phases:
        raise HTTPException(status_code=400, detail='platform_phases must include the default platform')

    # Prevent ID conflicts with built-ins and existing custom scenarios
    all_ids = {s.get('id') for s in _all_scenarios()}
    if scenario_id in all_ids:
        raise HTTPException(status_code=409, detail='Scenario id already exists')

    now = datetime.now().isoformat()
    scenario_doc = {
        'id': scenario_id,
        'name': name,
        'name_zh': payload.get('name_zh') or name,
        'description': payload.get('description') or '',
        'description_zh': payload.get('description_zh') or payload.get('description') or '',
        'category': payload.get('category') or 'Custom',
        'icon': payload.get('icon') or '🧩',
        'risk': payload.get('risk') or 'medium',
        'supported_platforms': supported_platforms,
        'default_platform': default_platform,
        'variables': payload.get('variables') or [],
        'platform_phases': platform_phases,
        'is_custom': True,
    }

    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO custom_scenarios (id, data_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
            (scenario_id, json.dumps(scenario_doc), payload.get('author', 'admin'), now, now)
        )
        conn.commit()
    finally:
        conn.close()

    log_audit_event(
        event_type='SCENARIO_CREATE',
        category='automation',
        severity='medium',
        status='success',
        summary=f"Created scenario {name}",
        actor_username=payload.get('author', 'admin'),
        actor_role=payload.get('actor_role') or 'Administrator',
        source_ip=request.client.host if request and request.client else None,
        target_type='scenario',
        target_id=scenario_id,
        target_name=name,
        details={'risk': scenario_doc['risk'], 'platforms': supported_platforms},
    )

    return scenario_doc

@router.get("/playbooks")
async def list_playbooks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    status: str = Query('all'),
    scenario: str = Query(''),
):
    """Return paginated playbook execution summaries (no bulky results_json / phases_json)."""
    conn = get_db_connection()
    try:
        where_clauses = []
        params: list = []
        if status != 'all':
            where_clauses.append("status = ?")
            params.append(status)
        if scenario:
            where_clauses.append("scenario_name LIKE ?")
            params.append(f"%{scenario}%")
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM playbook_executions {where_sql}", params
        ).fetchone()[0]
        logger.info(f"[Playbooks] Found {total} total executions (status={status}, scenario={scenario})")
        offset = (page - 1) * page_size
        rows = conn.execute(
            f'''SELECT id, scenario_id, scenario_name, platform, device_ids,
                       variables, status, dry_run, author, concurrency,
                       total_devices, success_count, failed_count, partial_count,
                       created_at, updated_at
                FROM playbook_executions {where_sql}
                ORDER BY created_at DESC LIMIT ? OFFSET ?''',
            [*params, page_size, offset]
        ).fetchall()
        items = []
        for r in rows:
            row_dict = dict(r)
            if not row_dict.get('total_devices'):
                try:
                    row_dict['total_devices'] = len(json.loads(row_dict.get('device_ids', '[]')))
                except Exception:
                    row_dict['total_devices'] = 0
            items.append(row_dict)
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        conn.close()

@router.get("/playbooks/{playbook_id}")
async def get_playbook(playbook_id: str):
    """Legacy endpoint — returns full row including results_json for backward compatibility."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM playbook_executions WHERE id = ?', (playbook_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Playbook execution not found")
        return dict(row)
    finally:
        conn.close()

@router.delete("/playbooks/{execution_id}")
async def delete_execution(execution_id: str):
    """Delete a playbook execution and its device results."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT id FROM playbook_executions WHERE id = ?', (execution_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")
        conn.execute('DELETE FROM execution_device_results WHERE execution_id = ?', (execution_id,))
        conn.execute('DELETE FROM playbook_executions WHERE id = ?', (execution_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/summary")
async def get_execution_summary(execution_id: str):
    """Return header-level summary for one execution (no device details)."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''SELECT id, scenario_name, platform, device_ids, status, dry_run, author,
                      total_devices, success_count, failed_count, partial_count,
                      created_at, updated_at
               FROM playbook_executions WHERE id = ?''',
            (execution_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")
        d = dict(row)
        # Fallback: compute total_devices from device_ids for legacy records
        if not d.get('total_devices'):
            try:
                d['total_devices'] = len(json.loads(d.get('device_ids', '[]')))
            except Exception:
                d['total_devices'] = 0
        # Fallback: compute counts from execution_device_results or results_json for legacy records
        if not d.get('success_count') and not d.get('failed_count'):
            try:
                counts = conn.execute(
                    '''SELECT
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as sc,
                        SUM(CASE WHEN status IN ('failed','error') THEN 1 ELSE 0 END) as fc
                    FROM execution_device_results WHERE execution_id = ?''',
                    (execution_id,)
                ).fetchone()
                if counts and (counts['sc'] or counts['fc']):
                    d['success_count'] = counts['sc'] or 0
                    d['failed_count'] = counts['fc'] or 0
            except Exception:
                pass
        # Second fallback: parse results_json blob if counts still 0
        if not d.get('success_count') and not d.get('failed_count'):
            try:
                rj_row = conn.execute(
                    "SELECT results_json FROM playbook_executions WHERE id = ?",
                    (execution_id,)
                ).fetchone()
                if rj_row and rj_row['results_json']:
                    results = json.loads(rj_row['results_json'])
                    sc = fc = pc = 0
                    for v in results.values():
                        st = v.get('status', 'success') if isinstance(v, dict) else 'success'
                        if st == 'success':
                            sc += 1
                        elif st in ('failed', 'error', 'blocked'):
                            fc += 1
                        else:
                            pc += 1
                    d['success_count'] = sc
                    d['failed_count'] = fc
                    d['partial_count'] = pc
            except Exception:
                pass
        try:
            s = datetime.fromisoformat(d['created_at'])
            e = datetime.fromisoformat(d['updated_at'])
            d['duration_ms'] = int((e - s).total_seconds() * 1000)
        except Exception:
            d['duration_ms'] = 0
        return d
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/full")
async def get_execution_full(execution_id: str):
    """Return the complete execution record, including phases_json and variables."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''SELECT id, scenario_id, scenario_name, platform, device_ids, variables, 
                      status, dry_run, author, concurrency, phases_json, 
                      total_devices, success_count, failed_count, partial_count,
                      created_at, updated_at
               FROM playbook_executions WHERE id = ?''',
            (execution_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")
        d = dict(row)
        # Parse JSON fields
        for field in ['device_ids', 'variables', 'phases_json']:
            if d.get(field):
                try:
                    d[field.replace('_json', '')] = json.loads(d[field])
                except Exception:
                    d[field.replace('_json', '')] = d[field]
        return d
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/devices")
async def get_execution_devices(
    execution_id: str,
    status: str = Query('all'),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(''),
):
    """Return paginated per-device results for an execution. Failed devices sorted first."""
    conn = get_db_connection()
    try:
        count_new = conn.execute(
            "SELECT COUNT(*) FROM execution_device_results WHERE execution_id = ?",
            (execution_id,)
        ).fetchone()[0]

        if count_new > 0:
            where_clauses = ["execution_id = ?"]
            params: list = [execution_id]
            if status != 'all':
                where_clauses.append("status = ?")
                params.append(status)
            if search:
                where_clauses.append("(hostname LIKE ? OR ip_address LIKE ?)")
                params.extend([f"%{search}%", f"%{search}%"])
            where_sql = "WHERE " + " AND ".join(where_clauses)
            total = conn.execute(
                f"SELECT COUNT(*) FROM execution_device_results {where_sql}", params
            ).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f'''SELECT id, device_id, hostname, ip_address, status, error_message,
                           started_at, completed_at, duration_ms
                    FROM execution_device_results {where_sql}
                    ORDER BY CASE status
                        WHEN 'failed' THEN 0
                        WHEN 'error' THEN 0
                        WHEN 'partial_failure' THEN 1
                        WHEN 'post_check_failed' THEN 1
                        ELSE 2 END, hostname
                    LIMIT ? OFFSET ?''',
                [*params, page_size, offset]
            ).fetchall()
            items = [dict(r) for r in rows]
        else:
            # Legacy fallback: parse results_json blob
            exec_row = conn.execute(
                "SELECT results_json, device_ids FROM playbook_executions WHERE id = ?",
                (execution_id,)
            ).fetchone()
            if not exec_row:
                raise HTTPException(status_code=404, detail="Execution not found")
            try:
                results = json.loads(exec_row['results_json'] or '{}')
                device_ids_list = json.loads(exec_row['device_ids'] or '[]')
            except Exception:
                results, device_ids_list = {}, []
            all_items = []
            for did in device_ids_list:
                r = results.get(did, {})
                dev_row = conn.execute(
                    "SELECT hostname, ip_address FROM devices WHERE id = ?", (did,)
                ).fetchone()
                hostname = dev_row['hostname'] if dev_row else did
                ip_address = dev_row['ip_address'] if dev_row else ''
                all_items.append({
                    "device_id": did, "hostname": hostname, "ip_address": ip_address,
                    "status": r.get('status', 'success'),
                    "error_message": r.get('error', ''),
                    "started_at": None, "completed_at": None, "duration_ms": 0,
                })
            if status != 'all':
                all_items = [i for i in all_items if i['status'] == status]
            if search:
                sq = search.lower()
                all_items = [i for i in all_items if sq in i['hostname'].lower() or sq in i['ip_address'].lower()]
            all_items.sort(key=lambda x: (
                0 if x['status'] in ('failed', 'error') else
                1 if 'fail' in x['status'] else 2,
                x['hostname']
            ))
            total = len(all_items)
            offset = (page - 1) * page_size
            items = all_items[offset:offset + page_size]
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/devices/{device_id}")
async def get_execution_device_detail(execution_id: str, device_id: str):
    """Return full phase output for one device in an execution."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM execution_device_results WHERE execution_id = ? AND (device_id = ? OR ip_address = ?)",
            (execution_id, device_id, device_id)
        ).fetchone()
        if row:
            res = dict(row)
            if res.get('phases_json'):
                try:
                    res['phases'] = json.loads(res['phases_json'])
                except Exception:
                    res['phases'] = {}
            return res
        # Legacy fallback
        exec_row = conn.execute(
            "SELECT results_json FROM playbook_executions WHERE id = ?", (execution_id,)
        ).fetchone()
        if not exec_row:
            raise HTTPException(status_code=404, detail="Execution not found")
        results = json.loads(exec_row['results_json'] or '{}')
        device_data = results.get(device_id)
        if not device_data:
            raise HTTPException(status_code=404, detail="Device result not found")
        dev_row = conn.execute(
            "SELECT hostname, ip_address FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        return {
            "device_id": device_id,
            "hostname": dev_row['hostname'] if dev_row else device_id,
            "ip_address": dev_row['ip_address'] if dev_row else '',
            "status": device_data.get('status', 'success'),
            "error_message": device_data.get('error', ''),
            "phases_json": json.dumps(device_data.get('phases', {})),
            "started_at": None, "completed_at": None, "duration_ms": 0,
        }
    finally:
        conn.close()

@router.post("/playbooks/preview")
async def preview_playbook(payload: dict = Body(...)):
    """Preview rendered commands without executing."""
    scenario_id = payload.get('scenario_id')
    variables = payload.get('variables', {})
    platform = payload.get('platform', 'cisco_ios')

    scenario = next((s for s in _all_scenarios() if s['id'] == scenario_id), None)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    phases = scenario.get('platform_phases', {}).get(platform)
    if not phases:
        raise HTTPException(status_code=400, detail=f"Platform '{platform}' not supported for this scenario")

    return {
        "platform": platform,
        "pre_check": _render_phase_commands(phases.get('pre_check', []), variables),
        "execute": _render_phase_commands(phases.get('execute', []), variables),
        "post_check": _render_phase_commands(phases.get('post_check', []), variables),
        "rollback": _render_phase_commands(phases.get('rollback', []), variables),
    }


def _parse_iso_to_utc(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _assert_change_order_executable(row: dict, scenario_id: str, platform: str, now_utc: datetime) -> None:
    status = row.get('status') or ''
    if status not in {'approved', 'implementing'}:
        raise HTTPException(status_code=400, detail=f"工单状态为 {status}，仅已审批/执行中的工单允许执行任务")

    start_dt = _parse_iso_to_utc(row.get('scheduled_start'))
    end_dt = _parse_iso_to_utc(row.get('scheduled_end'))
    if start_dt and now_utc < start_dt:
        raise HTTPException(status_code=400, detail=f"变更窗口尚未开始（计划开始：{row.get('scheduled_start') or ''}）")
    if end_dt and now_utc > end_dt:
        raise HTTPException(status_code=400, detail=f"变更窗口已超时（计划结束：{row.get('scheduled_end') or ''}）")

    raw_template = row.get('command_template_json')
    try:
        template = json.loads(raw_template or '{}')
    except (TypeError, json.JSONDecodeError):
        template = {}
    ticket_scenario_id = str(template.get('scenario_id') or '').strip()
    ticket_platform = str(template.get('platform') or '').strip()

    if ticket_scenario_id and scenario_id and ticket_scenario_id != scenario_id:
        raise HTTPException(status_code=400, detail="工单绑定场景与当前执行任务不匹配，请检查工单号")
    if ticket_platform and platform and ticket_platform != platform:
        raise HTTPException(status_code=400, detail="工单绑定平台与当前执行平台不匹配")


def _resolve_change_order_for_playbook(
    conn,
    *,
    ticket_number: str,
    scenario_id: str,
    platform: str,
    now_utc: datetime,
) -> tuple[dict, bool]:
    """Resolve explicit ticket or auto-match one active change order for scenario execution."""
    if ticket_number:
        row = conn.execute(
            """
            SELECT id, order_number, title, status, scheduled_start, scheduled_end, command_template_json
            FROM change_orders WHERE order_number = ?
            """,
            (ticket_number,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="未找到该变更工单，请检查工单号")
        order = dict(row)
        _assert_change_order_executable(order, scenario_id, platform, now_utc)
        return order, False

    rows = conn.execute(
        """
        SELECT id, order_number, title, status, scheduled_start, scheduled_end, command_template_json, updated_at
        FROM change_orders
        WHERE status IN ('approved', 'implementing')
        ORDER BY updated_at DESC
        LIMIT 200
        """
    ).fetchall()

    matched: list[dict] = []
    for row in rows:
        order = dict(row)
        raw_template = order.get('command_template_json')
        try:
            template = json.loads(raw_template or '{}')
        except (TypeError, json.JSONDecodeError):
            template = {}

        if str(template.get('scenario_id') or '').strip() != scenario_id:
            continue
        template_platform = str(template.get('platform') or '').strip()
        if template_platform and template_platform != platform:
            continue

        start_dt = _parse_iso_to_utc(order.get('scheduled_start'))
        end_dt = _parse_iso_to_utc(order.get('scheduled_end'))
        if start_dt and now_utc < start_dt:
            continue
        if end_dt and now_utc > end_dt:
            continue

        matched.append(order)

    if len(matched) == 1:
        _assert_change_order_executable(matched[0], scenario_id, platform, now_utc)
        return matched[0], True

    if len(matched) > 1:
        raise HTTPException(status_code=400, detail="匹配到多个有效变更工单，请填写工单号后再执行")

    raise HTTPException(status_code=400, detail="未找到当前任务对应的有效变更工单，请先创建并审批工单")

@router.post("/playbooks/execute")
async def execute_playbook(request: Request, payload: dict = Body(...)):
    """
    Start an async playbook execution and return immediately.
    Subscribe to /ws/playbook/{execution_id} for real-time updates.
    """
    scenario_id = payload.get('scenario_id')
    device_ids = payload.get('device_ids', [])
    variables = payload.get('variables', {})
    dry_run = payload.get('dry_run', False)
    concurrency = payload.get('concurrency', 1)         # Parallel device count
    change_ticket = str(payload.get('change_ticket') or '').strip()
    author = payload.get('author', 'admin')
    actor_id = payload.get('actor_id')
    actor_role = payload.get('actor_role') or 'Administrator'
    commit_confirmed_ttl = int(payload.get('commit_confirmed_ttl', 0))  # P3: 秒数，0=关闭

    if not device_ids:
        raise HTTPException(status_code=400, detail="No devices selected")

    platform = payload.get('platform', 'cisco_ios')

    scenario = next((s for s in _all_scenarios() if s['id'] == scenario_id), None)
    # Allow custom playbooks (scenario can be None — user provides commands directly)
    custom_phases = payload.get('phases')
    if not scenario and not custom_phases:
        raise HTTPException(status_code=404, detail="Scenario not found and no custom phases provided")

    execution_id = str(uuid.uuid4())
    if scenario:
        phases_def = scenario.get('platform_phases', {}).get(platform)
        if not phases_def:
            raise HTTPException(status_code=400, detail=f"Platform '{platform}' not supported for this scenario")
    else:
        phases_def = custom_phases
    scenario_name = scenario['name'] if scenario else payload.get('name', 'Custom Playbook')
    scenario_risk = str((scenario or {}).get('risk') or 'low').lower()
    now_utc = datetime.now(timezone.utc)

    conn = get_db_connection()
    try:
        resolved_change_order = None
        auto_matched_change_order = False
        if scenario and scenario_risk != 'low':
            resolved_change_order, auto_matched_change_order = _resolve_change_order_for_playbook(
                conn,
                ticket_number=change_ticket,
                scenario_id=scenario_id,
                platform=platform,
                now_utc=now_utc,
            )

        conn.execute(
            '''INSERT INTO playbook_executions
               (id, scenario_id, scenario_name, platform, device_ids, variables, status, dry_run, author, concurrency, phases_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (execution_id, scenario_id or 'custom', scenario_name, platform,
             json.dumps(device_ids), json.dumps(variables),
             'pending', int(dry_run), author, concurrency,
             json.dumps(phases_def),
             datetime.now().isoformat(), datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()

    # Fire-and-forget the execution coroutine
    asyncio.create_task(_run_playbook(execution_id, device_ids, phases_def, variables, dry_run, concurrency, platform, commit_confirmed_ttl))

    log_audit_event(
        event_type='PLAYBOOK_EXECUTION',
        category='automation',
        severity='high' if not dry_run else 'medium',
        status='pending',
        summary=f"Started playbook {scenario_name} for {len(device_ids)} device(s)",
        actor_id=str(actor_id) if actor_id is not None else None,
        actor_username=author,
        actor_role=actor_role,
        source_ip=request.client.host if request.client else None,
        target_type='playbook',
        target_id=execution_id,
        target_name=scenario_name,
        execution_id=execution_id,
        details={
            'scenario_id': scenario_id or 'custom',
            'platform': platform,
            'device_count': len(device_ids),
            'dry_run': dry_run,
            'concurrency': concurrency,
            'change_order_number': (resolved_change_order or {}).get('order_number'),
            'change_order_auto_matched': auto_matched_change_order,
        },
    )

    return {
        "execution_id": execution_id,
        "status": "pending",
        "change_order_number": (resolved_change_order or {}).get('order_number'),
        "change_order_auto_matched": auto_matched_change_order,
    }

# ════════════════════════════════════════════════════════════════════
# WebSocket: /ws/playbook/{execution_id}
# ════════════════════════════════════════════════════════════════════

@router.websocket("/ws/playbook/{execution_id}")
async def playbook_ws(websocket: WebSocket, execution_id: str):
    # Authenticate via query param: ?token=xxx
    token = websocket.query_params.get('token', '')
    if not token:
        await websocket.close(code=1008, reason="Missing authentication token")
        return
    from api.users import validate_session_token
    if not validate_session_token(token):
        await websocket.close(code=1008, reason="Invalid or expired session")
        return

    await ws_manager.connect(execution_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(execution_id, websocket)

# ════════════════════════════════════════════════════════════════════
# 执行引擎（三段式 + 并行控制）
# ════════════════════════════════════════════════════════════════════

async def _save_device_result_to_db(
    execution_id: str,
    device_id: str,
    device: dict,
    device_result: dict,
    started_at_iso: str,
) -> None:
    """Persist one device's execution result into execution_device_results."""
    completed_at_iso = datetime.now().isoformat()
    try:
        started_dt = datetime.fromisoformat(started_at_iso)
        completed_dt = datetime.fromisoformat(completed_at_iso)
        duration_ms = int((completed_dt - started_dt).total_seconds() * 1000)
    except Exception:
        duration_ms = 0
    try:
        conn = get_db_connection()
        conn.execute(
            '''INSERT INTO execution_device_results
               (id, execution_id, device_id, hostname, ip_address, status,
                error_message, phases_json, started_at, completed_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (id) DO UPDATE SET
                 execution_id=excluded.execution_id, device_id=excluded.device_id,
                 hostname=excluded.hostname, ip_address=excluded.ip_address,
                 status=excluded.status, error_message=excluded.error_message,
                 phases_json=excluded.phases_json, started_at=excluded.started_at,
                 completed_at=excluded.completed_at, duration_ms=excluded.duration_ms''',
            (
                str(uuid.uuid4()), execution_id, device_id,
                device.get('hostname') or device_id,
                device.get('ip_address') or device.get('ip') or '',
                device_result.get('status', 'success'),
                device_result.get('error', ''),
                json.dumps(device_result.get('phases', {})),
                started_at_iso, completed_at_iso, duration_ms,
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[DB] Failed to save device result for {device_id}: {e}")


async def _run_playbook(
    execution_id: str,
    device_ids: list,
    phases: dict,
    variables: dict,
    dry_run: bool,
    concurrency: int,
    platform: str = 'cisco_ios',
    commit_confirmed_ttl: int = 0,
):
    """
    Execute the playbook across all selected devices with concurrency control.
    Emits events through WebSocket in real time.
    """
    from services.automation_service import AutomationService

    conn = get_db_connection()
    conn.execute("UPDATE playbook_executions SET status='running', updated_at=? WHERE id=?",
                 (datetime.now().isoformat(), execution_id))
    conn.commit()

    # Load device info
    device_rows = conn.execute(
        f"SELECT * FROM devices WHERE id IN ({','.join('?' * len(device_ids))})",
        device_ids
    ).fetchall()
    devices = {}
    for d in device_rows:
        dd = dict(d)
        dd['password'] = decrypt_credential(dd.get('password')) or ''
        devices[d['id']] = dd
    conn.close()

    total = len(device_ids)
    results = {}      # device_id → {pre_check, execute, post_check, rollback, status}
    overall_ok = True

    await ws_manager.emit(execution_id, {
        "type": "start",
        "execution_id": execution_id,
        "total_devices": total,
        "dry_run": dry_run,
        "timestamp": datetime.now().isoformat(),
    })

    semaphore = asyncio.Semaphore(concurrency)

    async def _process_device(device_id: str, idx: int):
        nonlocal overall_ok
        started_at_iso = datetime.now().isoformat()
        device = devices.get(device_id)
        if not device:
            await ws_manager.emit(execution_id, {
                "type": "device_error",
                "device_id": device_id,
                "error": "Device not found in DB",
            })
            err_result = {"status": "error", "error": "not found", "phases": {}}
            await _save_device_result_to_db(execution_id, device_id, {}, err_result, started_at_iso)
            results[device_id] = err_result
            return

        hostname = device.get('hostname', device_id)
        driver_type = 'mock' if device.get('ip_address') in ['127.0.0.1', '0.0.0.0', 'localhost'] else 'netmiko'
        service = AutomationService(driver_type=driver_type)

        device_result = {"status": "success", "phases": {}}

        async with semaphore:
            async with _get_device_lock(device_id):   # P2: 设备粒度互斥锁
                await ws_manager.emit(execution_id, {
                    "type": "device_start",
                    "device_id": device_id,
                    "hostname": hostname,
                    "index": idx,
                    "total": total,
                })

                # ──── PHASE 1: Pre-Check ────
                pre_cmds = _render_phase_commands(phases.get('pre_check', []), variables)
                if pre_cmds:
                    await ws_manager.emit(execution_id, {
                        "type": "phase_start", "device_id": device_id,
                        "phase": "pre_check", "commands": pre_cmds,
                    })
                    pre_output = await _exec_commands(service, device, pre_cmds, is_config=False)
                    device_result["phases"]["pre_check"] = pre_output
                    if not pre_output.get("success", True):
                        overall_ok = False   # pre_check errors → partial_failure, but execution continues
                    await ws_manager.emit(execution_id, {
                        "type": "phase_done", "device_id": device_id,
                        "phase": "pre_check", "output": pre_output,
                    })

                # ──── P1: 变更前快照 ────
                if not dry_run:
                    snap_cmd = PLATFORM_SHOW_RUNNING.get(platform)
                    if snap_cmd:
                        snap_output = await _exec_commands(service, device, [snap_cmd], is_config=False)
                        if snap_output.get('success'):
                            _save_snapshot(hostname, snap_output.get('output', ''))
                            device_result["snapshot"] = "saved"
                        await ws_manager.emit(execution_id, {
                            "type": "snapshot", "device_id": device_id,
                            "hostname": hostname,
                            "status": "saved" if snap_output.get('success') else "failed",
                        })

                # ──── PHASE 2: Execute ────
                exec_cmds = _render_phase_commands(phases.get('execute', []), variables)
                if exec_cmds:
                    if dry_run:
                        await ws_manager.emit(execution_id, {
                            "type": "phase_start", "device_id": device_id,
                            "phase": "execute", "commands": exec_cmds,
                            "dry_run": True,
                        })
                        device_result["phases"]["execute"] = {
                            "commands": exec_cmds,
                            "output": "[DRY-RUN] Commands not sent to device",
                            "success": True,
                        }
                        await ws_manager.emit(execution_id, {
                            "type": "phase_done", "device_id": device_id,
                            "phase": "execute", "output": device_result["phases"]["execute"],
                            "dry_run": True,
                        })
                    else:
                        await ws_manager.emit(execution_id, {
                            "type": "phase_start", "device_id": device_id,
                            "phase": "execute", "commands": exec_cmds,
                        })
                        # Determine if commands need config mode.
                        # Show/display/ping commands are exec-mode only; config commands
                        # (interface, vlan, router, etc.) need config mode.
                        _show_prefixes = (
                            'show ', 'display ', 'ping ', 'traceroute ', 'tracert ',
                            'dir ', 'more ', 'terminal ', 'debug ', 'undebug ',
                        )
                        _needs_config = not all(
                            any(cmd.lower().strip().startswith(p) for p in _show_prefixes)
                            for cmd in exec_cmds
                            if cmd.strip()
                        )
                        exec_output = await _exec_commands(service, device, exec_cmds, is_config=_needs_config)
                        device_result["phases"]["execute"] = exec_output
                        await ws_manager.emit(execution_id, {
                            "type": "phase_done", "device_id": device_id,
                            "phase": "execute", "output": exec_output,
                        })

                        # P0: Execute 失败 → 自动回滚
                        if not exec_output.get("success", True):
                            overall_ok = False
                            device_result["status"] = "failed"
                            await _do_rollback(execution_id, service, device, phases, variables)
                            device_result["phases"]["rollback"] = {"triggered": True, "reason": "execute_failed"}
                            await _save_device_result_to_db(execution_id, device_id, device, device_result, started_at_iso)
                            results[device_id] = device_result
                            return

                # ──── PHASE 3: Post-Check ────
                post_cmds = _render_phase_commands(phases.get('post_check', []), variables)
                if post_cmds and not dry_run:
                    await ws_manager.emit(execution_id, {
                        "type": "phase_start", "device_id": device_id,
                        "phase": "post_check", "commands": post_cmds,
                    })
                    post_output = await _exec_commands(service, device, post_cmds, is_config=False)
                    device_result["phases"]["post_check"] = post_output
                    await ws_manager.emit(execution_id, {
                        "type": "phase_done", "device_id": device_id,
                        "phase": "post_check", "output": post_output,
                    })

                    # P0: Post-Check 执行失败 → 自动回滚（连接中断/命令报错）
                    if not post_output.get("success", True):
                        overall_ok = False
                        device_result["status"] = "post_check_failed"
                        await ws_manager.emit(execution_id, {
                            "type": "post_check_failed", "device_id": device_id,
                            "hostname": hostname,
                            "message": "Post-check failed, triggering automatic rollback",
                        })
                        await _do_rollback(execution_id, service, device, phases, variables)
                        device_result["phases"]["rollback"] = {"triggered": True, "reason": "post_check_failed"}
                        await _save_device_result_to_db(execution_id, device_id, device, device_result, started_at_iso)
                        results[device_id] = device_result
                        return

                # ──── P0: Save Phase（写入持久化存储）────
                if not dry_run and exec_cmds:
                    save_cmd = PLATFORM_SAVE_COMMANDS.get(platform)
                    if save_cmd:
                        await ws_manager.emit(execution_id, {
                            "type": "phase_start", "device_id": device_id,
                            "phase": "save", "commands": [save_cmd],
                        })
                        save_output = await _exec_commands(service, device, [save_cmd], is_config=False)
                        device_result["phases"]["save"] = save_output
                        await ws_manager.emit(execution_id, {
                            "type": "phase_done", "device_id": device_id,
                            "phase": "save", "output": save_output,
                        })

                await ws_manager.emit(execution_id, {
                    "type": "device_done", "device_id": device_id,
                    "hostname": hostname, "status": device_result["status"],
                })
                await _save_device_result_to_db(execution_id, device_id, device, device_result, started_at_iso)
                results[device_id] = device_result

    # Run with concurrency control
    tasks = [_process_device(did, i) for i, did in enumerate(device_ids)]
    await asyncio.gather(*tasks)

    final_status = 'success' if overall_ok else 'partial_failure'
    if dry_run:
        final_status = 'dry_run_complete'

    # Persist results
    success_c = sum(1 for r in results.values() if r.get('status') == 'success')
    failed_c  = sum(1 for r in results.values() if r.get('status') in ('failed', 'error'))
    partial_c = sum(1 for r in results.values() if 'partial' in r.get('status', '') or 'check_failed' in r.get('status', ''))
    conn2 = get_db_connection()
    conn2.execute(
        """UPDATE playbook_executions
           SET status=?, results_json=?, updated_at=?,
               total_devices=?, success_count=?, failed_count=?, partial_count=?
           WHERE id=?""",
        (final_status, json.dumps(results), datetime.now().isoformat(),
         total, success_c, failed_c, partial_c, execution_id)
    )
    conn2.commit()
    conn2.close()

    # ──── P3: Commit Confirmed 安全网 ────
    # 若请求方指定了 commit_confirmed_ttl > 0，且本次执行全部成功，
    # 启动一个倒计时任务：超时后自动对所有设备执行回滚。
    # 调用 POST /api/playbooks/executions/{id}/confirm-commit 可取消定时器。
    if commit_confirmed_ttl > 0 and overall_ok and not dry_run:
        async def _auto_rollback():
            await asyncio.sleep(commit_confirmed_ttl)
            if execution_id not in _pending_rollbacks:
                return  # 已被 confirm-commit 取消
            del _pending_rollbacks[execution_id]
            await ws_manager.emit(execution_id, {
                "type": "commit_confirmed_timeout",
                "message": f"Commit not confirmed within {commit_confirmed_ttl}s, auto-rollback triggered",
                "execution_id": execution_id,
            })
            for did in device_ids:
                dev = devices.get(did)
                if dev:
                    svc_type = 'mock' if dev.get('ip_address') in ['127.0.0.1', '0.0.0.0', 'localhost'] else 'netmiko'
                    svc = AutomationService(driver_type=svc_type)
                    await _do_rollback(execution_id, svc, dev, phases, variables)

        task = asyncio.create_task(_auto_rollback())
        _pending_rollbacks[execution_id] = task
        await ws_manager.emit(execution_id, {
            "type": "commit_confirm_pending",
            "execution_id": execution_id,
            "ttl": commit_confirmed_ttl,
            "message": f"Changes deployed. Auto-rollback in {commit_confirmed_ttl}s unless confirmed.",
        })

    await ws_manager.emit(execution_id, {
        "type": "complete",
        "execution_id": execution_id,
        "status": final_status,
        "summary": {
            "total": total,
            "success": sum(1 for r in results.values() if r.get("status") == "success"),
            "failed": sum(1 for r in results.values() if r.get("status") != "success"),
        },
        "timestamp": datetime.now().isoformat(),
    })


@router.post("/playbooks/executions/{execution_id}/confirm-commit")
async def confirm_commit(execution_id: str):
    """
    P3 Commit Confirmed：取消该次执行的定时自动回滚任务，正式确认变更。
    须在 commit_confirmed_ttl 秒内调用，否则自动回滚已触发。
    """
    task = _pending_rollbacks.pop(execution_id, None)
    if task:
        task.cancel()
        logger.info(f"Commit confirmed for execution {execution_id}, auto-rollback cancelled")
        return {"status": "confirmed", "execution_id": execution_id,
                "message": "Commit confirmed. Auto-rollback cancelled."}
    return {"status": "no_pending", "execution_id": execution_id,
            "message": "No pending commit confirmation found (already confirmed or timed out)."}


async def _exec_commands(service, device: dict, commands: list, is_config: bool) -> dict:
    """Execute commands on a single device in a thread pool."""
    loop = asyncio.get_event_loop()

    def _run():
        try:
            results = service.execute_commands(device, commands, is_config=is_config)
            output_lines = []
            all_ok = True
            for r in results:
                if r.get('success', False):
                    # Different drivers use different output keys:
                    # NetmikoDriver (engine) → 'stdout'
                    # Legacy drivers         → 'output'
                    out = r.get('output') or r.get('stdout') or ''
                    output_lines.append(out)
                else:
                    err = r.get('error') or r.get('stderr') or ''
                    output_lines.append(f"ERROR: {err}")
                    all_ok = False
            return {"success": all_ok, "output": "\n".join(output_lines), "commands": commands}
        except Exception as e:
            return {"success": False, "output": str(e), "commands": commands, "error": str(e)}

    return await loop.run_in_executor(None, _run)


async def _do_rollback(execution_id: str, service, device: dict, phases: dict, variables: dict):
    """Execute rollback phase and notify via WebSocket."""
    rollback_cmds = _render_phase_commands(phases.get('rollback', []), variables)
    hostname = device.get('hostname', device.get('id', ''))
    if not rollback_cmds:
        await ws_manager.emit(execution_id, {
            "type": "rollback", "device_id": device['id'],
            "hostname": hostname, "status": "no_rollback_defined",
        })
        return

    await ws_manager.emit(execution_id, {
        "type": "rollback_start", "device_id": device['id'],
        "hostname": hostname, "commands": rollback_cmds,
    })
    result = await _exec_commands(service, device, rollback_cmds, is_config=True)
    await ws_manager.emit(execution_id, {
        "type": "rollback_done", "device_id": device['id'],
        "hostname": hostname, "output": result,
    })
