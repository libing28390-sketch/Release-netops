# -*- coding: utf-8 -*-
# Builtin Scenarios and Platforms configuration
# Generated from monolithic playbooks.py

PLATFORM_SAVE_COMMANDS: dict[str, str | None] = {
    'cisco_ios':    'write memory',
    'cisco_nxos':   'copy running-config startup-config',
    'cisco_iosxr':  None,  # commit 已在 execute 阶段模板里
    'huawei_vrp':   'save force',
    'h3c_comware':  'save force',
    'arista_eos':   'write memory',
    'juniper_junos': None,  # commit 已在 execute 阶段模板里
    # 国产平台的保存命令只登记有官方资料或现有设备样本支持的写法。
    # DPtech/Maipu 暂不自动保存，避免跨型号猜测写盘命令。
    'ruijie_rgos': 'write',
    'zte_zxros': 'write',
    'maipu': None,
    'dptech_conplat': None,
    'dptech_conplat_fw': None,
    'dptech_ios': None,
}


PLATFORM_SHOW_RUNNING: dict[str, str] = {
    'cisco_ios':    'show running-config',
    'cisco_nxos':   'show running-config',
    'cisco_iosxr':  'show running-config',
    'huawei_vrp':   'display current-configuration',
    'h3c_comware':  'display current-configuration',
    'arista_eos':   'show running-config',
    'juniper_junos': 'show configuration',
    'ruijie_rgos': 'show running-config',
    'zte_zxros': 'show running-config',
    'maipu': 'show running-config',
    'dptech_conplat': 'show running-config',
    'dptech_conplat_fw': 'show running-config',
    'dptech_ios': 'show running-config',
}


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
    "ruijie_rgos": {
        "vendor": "Ruijie",
        "name": "RGOS",
        "description": "RG-S/CS/NBS 交换机、RG-R/RSR 路由器、RG-EG 网关",
        "icon": "🟦",
    },
    "zte_zxros": {
        "vendor": "ZTE",
        "name": "ZXROS",
        "description": "ZXR10 交换机、路由器及承载网设备",
        "icon": "🟪",
    },
    "maipu": {
        "vendor": "Maipu",
        "name": "MyPower",
        "description": "MyPower S/NSS 系列交换机及 MP 系列路由器",
        "icon": "⬛",
    },
    "dptech_conplat": {
        "vendor": "DPtech",
        "name": "ConPlat",
        "description": "迪普 ConPlat 交换机与路由平台",
        "icon": "🟧",
    },
    "dptech_conplat_fw": {
        "vendor": "DPtech",
        "name": "ConPlat FW",
        "description": "迪普 ConPlat 防火墙平台",
        "icon": "🟥",
    },
}


BUILTIN_SCENARIOS = [
    # ── 0. Domestic platform read-only inspection ─────────────
    # The Excel vendor matrix supplies the command evidence.  This scenario is
    # deliberately read-only: no configuration-mode command is sent, and the
    # device-specific command list stays isolated by platform family.
    {
        "id": "domestic-readonly-inspection",
        "name": "Domestic Platform Read-only Inspection",
        "name_zh": "国产平台只读巡检",
        "description": "Collect vendor-specific operational facts without changing device configuration",
        "description_zh": "按厂商平台采集基础运行信息，不进入配置模式、不修改设备配置",
        "category": "Operations",
        "icon": "🧭",
        "risk": "low",
        "supported_platforms": [
            "ruijie_rgos", "zte_zxros", "maipu", "dptech_conplat", "dptech_conplat_fw",
        ],
        "default_platform": "ruijie_rgos",
        "variables": [],
        "platform_phases": {
            "ruijie_rgos": {
                "pre_check": [
                    "show version",
                    "show interface status",
                    "show ip interface brief",
                    "show lldp neighbors",
                    "show vlan",
                    "show mac-address-table",
                    "show arp",
                    "show ip route",
                    "show ntp status",
                    "show interfaces transceiver",
                    "show logging",
                    "show cpu",
                    "show memory",
                    "show clock",
                ],
                "execute": [], "post_check": [], "rollback": [],
            },
            "zte_zxros": {
                "pre_check": [
                    "show version",
                    "show interface brief",
                    "show ip interface brief",
                    "show lldp neighbor",
                    "show vlan",
                    "show mac table",
                    "show arp",
                    "show ip forwarding route",
                    "show ntp status",
                    "show opticalinfo brief",
                    "show logging buffer almlog",
                    "show fan",
                    "show power",
                    "show temperature detail",
                    "show clock",
                ],
                "execute": [], "post_check": [], "rollback": [],
            },
            "maipu": {
                "pre_check": [
                    "show version",
                    "show interface switchport brief",
                    "show ip interface brief",
                    "show lldp neighbors",
                    "show vlan",
                    "show mac-address all",
                    "show arp",
                    "show ip route",
                    "show ntp status",
                    "show optical all",
                    "show environment",
                    "show system fan",
                    "show system power",
                    "show clock",
                ],
                "execute": [], "post_check": [], "rollback": [],
            },
            "dptech_conplat": {
                "pre_check": [
                    "show version",
                    "show interface status",
                    "show ip interface brief",
                    "show lldp neighbors",
                    "show vlan",
                    "show mac-address-table",
                    "show arp all",
                    "show ip route",
                    "show ntp status",
                    "show environment",
                    "show logging operlog recent",
                    "show clock",
                ],
                "execute": [], "post_check": [], "rollback": [],
            },
            "dptech_conplat_fw": {
                "pre_check": [
                    "show version",
                    "show interface status",
                    "show ip interface brief",
                    "show lldp neighbors",
                    "show vlan",
                    "show mac-address-table",
                    "show arp all",
                    "show ip route",
                    "show ntp status",
                    "show environment",
                    "show logging operlog recent",
                    "show clock",
                ],
                "execute": [], "post_check": [], "rollback": [],
            },
        },
    },
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
                    "display bgp peer ipv4 unicast",
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
