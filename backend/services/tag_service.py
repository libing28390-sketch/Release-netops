"""
Tag Service — 设备标签管理服务

标签分类 (category):
  device_type  — 设备类型 (路由器/交换机/防火墙/服务器…)
  vendor       — 厂商 (Cisco/Huawei/H3C/Dell/HPE…)
  os           — 操作系统 (IOS-XE/VRP/Linux/Windows Server…)
  role         — 网络角色 (核心/汇聚/接入/Spine/Leaf…)
  env          — 环境 (生产/预发/测试/灾备…)
  function     — 功能标签 (路由/交换/安全/计算/存储…)
"""

import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────
# Predefined tag seed data — built_in=1, ON CONFLICT DO NOTHING
# ────────────────────────────────────────────────────────────────────

BUILTIN_TAGS: list[dict] = [
    # ═══════════════════════════════════════════════════════════════
    # device_type — 设备类型
    # ═══════════════════════════════════════════════════════════════
    {"category": "device_type", "value": "router",              "label": "Router",              "label_zh": "路由器",       "icon": "🔀", "color": "#6366f1", "sort_order": 1},
    {"category": "device_type", "value": "switch-l2",           "label": "L2 Switch",           "label_zh": "二层交换机",   "icon": "🔌", "color": "#8b5cf6", "sort_order": 2},
    {"category": "device_type", "value": "switch-l3",           "label": "L3 Switch",           "label_zh": "三层交换机",   "icon": "🔌", "color": "#7c3aed", "sort_order": 3},
    {"category": "device_type", "value": "firewall",            "label": "Firewall",            "label_zh": "防火墙",       "icon": "🛡️", "color": "#ef4444", "sort_order": 4},
    {"category": "device_type", "value": "load-balancer",       "label": "Load Balancer",       "label_zh": "负载均衡器",   "icon": "⚖️", "color": "#f59e0b", "sort_order": 5},
    {"category": "device_type", "value": "wireless-controller", "label": "Wireless Controller", "label_zh": "无线控制器",   "icon": "📡", "color": "#06b6d4", "sort_order": 6},
    {"category": "device_type", "value": "wireless-ap",         "label": "Wireless AP",         "label_zh": "无线AP",       "icon": "📶", "color": "#22d3ee", "sort_order": 7},
    {"category": "device_type", "value": "sd-wan-edge",         "label": "SD-WAN Edge",         "label_zh": "SD-WAN边缘",  "icon": "🌐", "color": "#0ea5e9", "sort_order": 8},
    {"category": "device_type", "value": "vpn-gateway",         "label": "VPN Gateway",         "label_zh": "VPN网关",      "icon": "🔒", "color": "#14b8a6", "sort_order": 9},
    {"category": "device_type", "value": "server-physical",     "label": "Physical Server",     "label_zh": "物理服务器",   "icon": "🖥️", "color": "#64748b", "sort_order": 10},
    {"category": "device_type", "value": "server-virtual",      "label": "Virtual Machine",     "label_zh": "虚拟机",       "icon": "💻", "color": "#94a3b8", "sort_order": 11},
    {"category": "device_type", "value": "server-blade",        "label": "Blade Server",        "label_zh": "刀片服务器",   "icon": "🗄️", "color": "#475569", "sort_order": 12},
    {"category": "device_type", "value": "server-container",    "label": "Container Host",      "label_zh": "容器宿主机",   "icon": "🐳", "color": "#0284c7", "sort_order": 13},
    {"category": "device_type", "value": "hypervisor",          "label": "Hypervisor",          "label_zh": "虚拟化主机",   "icon": "☁️", "color": "#3b82f6", "sort_order": 14},
    {"category": "device_type", "value": "storage-san",         "label": "SAN Storage",         "label_zh": "SAN存储",      "icon": "💾", "color": "#a855f7", "sort_order": 15},
    {"category": "device_type", "value": "storage-nas",         "label": "NAS Storage",         "label_zh": "NAS存储",      "icon": "📦", "color": "#d946ef", "sort_order": 16},
    {"category": "device_type", "value": "ups",                 "label": "UPS",                 "label_zh": "UPS电源",      "icon": "🔋", "color": "#eab308", "sort_order": 17},
    {"category": "device_type", "value": "pdu",                 "label": "PDU",                 "label_zh": "配电单元",     "icon": "🔌", "color": "#ca8a04", "sort_order": 18},
    {"category": "device_type", "value": "console-server",      "label": "Console Server",      "label_zh": "控制台服务器", "icon": "🖧", "color": "#78716c", "sort_order": 19},
    {"category": "device_type", "value": "ip-phone",            "label": "IP Phone",            "label_zh": "IP电话",       "icon": "📞", "color": "#10b981", "sort_order": 20},

    # ═══════════════════════════════════════════════════════════════
    # vendor — 厂商 (网络)
    # ═══════════════════════════════════════════════════════════════
    {"category": "vendor", "value": "cisco",       "label": "Cisco",                 "label_zh": "思科",     "icon": "🔵", "color": "#049FD9", "sort_order": 1},
    {"category": "vendor", "value": "huawei",      "label": "Huawei",                "label_zh": "华为",     "icon": "🔴", "color": "#CF0A2C", "sort_order": 2},
    {"category": "vendor", "value": "h3c",         "label": "H3C (New H3C)",         "label_zh": "新华三",   "icon": "🟠", "color": "#E60012", "sort_order": 3},
    {"category": "vendor", "value": "arista",      "label": "Arista Networks",       "label_zh": "瑞斯塔",   "icon": "🔷", "color": "#5B9BD5", "sort_order": 4},
    {"category": "vendor", "value": "juniper",     "label": "Juniper Networks",      "label_zh": "瞻博",     "icon": "🟢", "color": "#84B135", "sort_order": 5},
    {"category": "vendor", "value": "paloalto",    "label": "Palo Alto Networks",    "label_zh": "派拓",     "icon": "🟧", "color": "#FA582D", "sort_order": 6},
    {"category": "vendor", "value": "fortinet",    "label": "Fortinet",              "label_zh": "飞塔",     "icon": "🟥", "color": "#EE3124", "sort_order": 7},
    {"category": "vendor", "value": "f5",          "label": "F5 Networks",           "label_zh": "F5",       "icon": "🔶", "color": "#E4002B", "sort_order": 8},
    {"category": "vendor", "value": "checkpoint",  "label": "Check Point",           "label_zh": "Check Point", "icon": "🟪", "color": "#2DBECD", "sort_order": 9},
    {"category": "vendor", "value": "ruijie",      "label": "Ruijie Networks",       "label_zh": "锐捷",     "icon": "🟡", "color": "#E50012", "sort_order": 10},
    {"category": "vendor", "value": "zte",         "label": "ZTE",                   "label_zh": "中兴",     "icon": "🔷", "color": "#0049A0", "sort_order": 11},
    {"category": "vendor", "value": "maipu",       "label": "Maipu",                 "label_zh": "迈普",     "icon": "🟦", "color": "#0066CC", "sort_order": 12},
    {"category": "vendor", "value": "bdcom",       "label": "BDCom",                 "label_zh": "博达",     "icon": "🟦", "color": "#003399", "sort_order": 13},
    {"category": "vendor", "value": "hillstone",   "label": "Hillstone Networks",    "label_zh": "山石网科", "icon": "🟧", "color": "#FF6600", "sort_order": 14},
    {"category": "vendor", "value": "dptech",      "label": "DPtech",                "label_zh": "迪普科技", "icon": "🔵", "color": "#0055A4", "sort_order": 15},
    {"category": "vendor", "value": "sangfor",     "label": "Sangfor",               "label_zh": "深信服",   "icon": "🟣", "color": "#6A0DAD", "sort_order": 16},
    {"category": "vendor", "value": "venustech",   "label": "Venustech",             "label_zh": "启明星辰", "icon": "⭐", "color": "#003366", "sort_order": 17},
    {"category": "vendor", "value": "nsfocus",     "label": "NSFOCUS",               "label_zh": "绿盟",     "icon": "🟩", "color": "#009933", "sort_order": 18},
    {"category": "vendor", "value": "topsec",      "label": "Topsec",                "label_zh": "天融信",   "icon": "🟦", "color": "#003399", "sort_order": 19},

    # vendor — 厂商 (服务器)
    {"category": "vendor", "value": "dell",        "label": "Dell Technologies",     "label_zh": "戴尔",     "icon": "🖥️", "color": "#007DB8", "sort_order": 30},
    {"category": "vendor", "value": "hpe",         "label": "HPE",                   "label_zh": "慧与",     "icon": "🖥️", "color": "#01A982", "sort_order": 31},
    {"category": "vendor", "value": "lenovo",      "label": "Lenovo",                "label_zh": "联想",     "icon": "🖥️", "color": "#E2231A", "sort_order": 32},
    {"category": "vendor", "value": "inspur",      "label": "Inspur",                "label_zh": "浪潮",     "icon": "🖥️", "color": "#0078D4", "sort_order": 33},
    {"category": "vendor", "value": "sugon",       "label": "Sugon",                 "label_zh": "曙光",     "icon": "🖥️", "color": "#2E75B6", "sort_order": 34},
    {"category": "vendor", "value": "supermicro",  "label": "Supermicro",            "label_zh": "超微",     "icon": "🖥️", "color": "#003DA5", "sort_order": 35},
    {"category": "vendor", "value": "huawei-server", "label": "Huawei (Server)",     "label_zh": "华为(服务器)", "icon": "🖥️", "color": "#CF0A2C", "sort_order": 36},
    {"category": "vendor", "value": "h3c-server",    "label": "H3C UniServer",       "label_zh": "新华三(服务器)","icon": "🖥️", "color": "#E60012", "sort_order": 37},
    {"category": "vendor", "value": "ibm",         "label": "IBM",                   "label_zh": "IBM",      "icon": "🖥️", "color": "#006699", "sort_order": 38},

    # vendor — 厂商 (存储)
    {"category": "vendor", "value": "netapp",       "label": "NetApp",               "label_zh": "NetApp",   "icon": "💾", "color": "#0067C5", "sort_order": 50},
    {"category": "vendor", "value": "emc",          "label": "Dell EMC",             "label_zh": "Dell EMC", "icon": "💾", "color": "#6E2585", "sort_order": 51},
    {"category": "vendor", "value": "pure-storage", "label": "Pure Storage",         "label_zh": "Pure",     "icon": "💾", "color": "#FE5000", "sort_order": 52},
    {"category": "vendor", "value": "huawei-storage","label": "Huawei OceanStor",    "label_zh": "华为(存储)", "icon": "💾", "color": "#CF0A2C", "sort_order": 53},

    # vendor — 厂商 (虚拟化)
    {"category": "vendor", "value": "vmware",      "label": "VMware (Broadcom)",     "label_zh": "VMware",   "icon": "☁️", "color": "#696566", "sort_order": 60},
    {"category": "vendor", "value": "proxmox",     "label": "Proxmox",              "label_zh": "Proxmox",  "icon": "☁️", "color": "#E57000", "sort_order": 61},
    {"category": "vendor", "value": "nutanix",     "label": "Nutanix",              "label_zh": "路坦力",   "icon": "☁️", "color": "#024DA1", "sort_order": 62},
    {"category": "vendor", "value": "smartx",      "label": "SmartX",               "label_zh": "志凌海纳", "icon": "☁️", "color": "#0066FF", "sort_order": 63},

    # vendor — 厂商 (无线)
    {"category": "vendor", "value": "ubiquiti",    "label": "Ubiquiti",              "label_zh": "优倍快",   "icon": "📡", "color": "#0559C9", "sort_order": 70},
    {"category": "vendor", "value": "ruckus",      "label": "Ruckus (CommScope)",    "label_zh": "优科",     "icon": "📡", "color": "#6B2D8B", "sort_order": 71},
    {"category": "vendor", "value": "tp-link",     "label": "TP-Link",              "label_zh": "普联",     "icon": "📡", "color": "#4ACBD6", "sort_order": 72},

    # ═══════════════════════════════════════════════════════════════
    # os — 操作系统 (网络设备)
    # ═══════════════════════════════════════════════════════════════
    {"category": "os", "value": "ios",         "label": "Cisco IOS",          "label_zh": "Cisco IOS",          "icon": "", "color": "#049FD9", "sort_order": 1},
    {"category": "os", "value": "ios-xe",      "label": "Cisco IOS-XE",       "label_zh": "Cisco IOS-XE",       "icon": "", "color": "#049FD9", "sort_order": 2},
    {"category": "os", "value": "ios-xr",      "label": "Cisco IOS-XR",       "label_zh": "Cisco IOS-XR",       "icon": "", "color": "#049FD9", "sort_order": 3},
    {"category": "os", "value": "nxos",        "label": "Cisco NX-OS",        "label_zh": "Cisco NX-OS",        "icon": "", "color": "#049FD9", "sort_order": 4},
    {"category": "os", "value": "asa-os",      "label": "Cisco ASA OS",       "label_zh": "Cisco ASA OS",       "icon": "", "color": "#049FD9", "sort_order": 5},
    {"category": "os", "value": "ftd",         "label": "Cisco FTD",          "label_zh": "Cisco FTD",          "icon": "", "color": "#049FD9", "sort_order": 6},
    {"category": "os", "value": "vrp",         "label": "Huawei VRP",         "label_zh": "华为VRP",            "icon": "", "color": "#CF0A2C", "sort_order": 10},
    {"category": "os", "value": "vrp-v8",      "label": "Huawei VRP V8",      "label_zh": "华为VRP V8",         "icon": "", "color": "#CF0A2C", "sort_order": 11},
    {"category": "os", "value": "comware",     "label": "H3C Comware",        "label_zh": "H3C Comware",        "icon": "", "color": "#E60012", "sort_order": 15},
    {"category": "os", "value": "comware-v5",  "label": "H3C Comware V5",     "label_zh": "H3C Comware V5",     "icon": "", "color": "#E60012", "sort_order": 16},
    {"category": "os", "value": "comware-v7",  "label": "H3C Comware V7",     "label_zh": "H3C Comware V7",     "icon": "", "color": "#E60012", "sort_order": 17},
    {"category": "os", "value": "eos",         "label": "Arista EOS",         "label_zh": "Arista EOS",         "icon": "", "color": "#5B9BD5", "sort_order": 20},
    {"category": "os", "value": "junos",       "label": "Juniper Junos",      "label_zh": "Juniper Junos",      "icon": "", "color": "#84B135", "sort_order": 22},
    {"category": "os", "value": "screenos",    "label": "Juniper ScreenOS",   "label_zh": "ScreenOS",           "icon": "", "color": "#84B135", "sort_order": 23},
    {"category": "os", "value": "panos",       "label": "Palo Alto PAN-OS",   "label_zh": "PAN-OS",             "icon": "", "color": "#FA582D", "sort_order": 25},
    {"category": "os", "value": "fortios",     "label": "Fortinet FortiOS",   "label_zh": "FortiOS",            "icon": "", "color": "#EE3124", "sort_order": 27},
    {"category": "os", "value": "gaia",        "label": "Check Point GAiA",   "label_zh": "GAiA",               "icon": "", "color": "#2DBECD", "sort_order": 29},
    {"category": "os", "value": "rgos",        "label": "Ruijie RGOS",        "label_zh": "锐捷RGOS",           "icon": "", "color": "#E50012", "sort_order": 30},
    {"category": "os", "value": "zxros",       "label": "ZTE ZXROS",          "label_zh": "中兴ZXROS",          "icon": "", "color": "#0049A0", "sort_order": 31},
    {"category": "os", "value": "maipu-os",    "label": "Maipu MyPower",      "label_zh": "迈普MyPower",        "icon": "", "color": "#0066CC", "sort_order": 32},
    {"category": "os", "value": "hillstone-os","label": "Hillstone StoneOS",  "label_zh": "山石StoneOS",        "icon": "", "color": "#FF6600", "sort_order": 33},
    {"category": "os", "value": "sangfor-os",  "label": "Sangfor NGAF",       "label_zh": "深信服NGAF",         "icon": "", "color": "#6A0DAD", "sort_order": 34},
    {"category": "os", "value": "topsec-os",   "label": "Topsec TOS",         "label_zh": "天融信TOS",          "icon": "", "color": "#003399", "sort_order": 35},
    {"category": "os", "value": "f5-tmos",     "label": "F5 TMOS",            "label_zh": "F5 TMOS",            "icon": "", "color": "#E4002B", "sort_order": 36},
    {"category": "os", "value": "f5-big-ip-next", "label": "F5 BIG-IP Next",  "label_zh": "F5 BIG-IP Next",     "icon": "", "color": "#E4002B", "sort_order": 37},

    # os — 操作系统 (服务器/计算)
    {"category": "os", "value": "linux-centos",    "label": "CentOS",               "label_zh": "CentOS",            "icon": "", "color": "#262577", "sort_order": 50},
    {"category": "os", "value": "linux-rhel",      "label": "RHEL",                 "label_zh": "Red Hat",           "icon": "", "color": "#EE0000", "sort_order": 51},
    {"category": "os", "value": "linux-ubuntu",    "label": "Ubuntu Server",        "label_zh": "Ubuntu",            "icon": "", "color": "#E95420", "sort_order": 52},
    {"category": "os", "value": "linux-debian",    "label": "Debian",               "label_zh": "Debian",            "icon": "", "color": "#A80030", "sort_order": 53},
    {"category": "os", "value": "linux-rocky",     "label": "Rocky Linux",          "label_zh": "Rocky Linux",       "icon": "", "color": "#10B981", "sort_order": 54},
    {"category": "os", "value": "linux-alma",      "label": "AlmaLinux",            "label_zh": "AlmaLinux",         "icon": "", "color": "#0F4266", "sort_order": 55},
    {"category": "os", "value": "linux-suse",      "label": "SUSE Linux",           "label_zh": "SUSE",              "icon": "", "color": "#73BA25", "sort_order": 56},
    {"category": "os", "value": "linux-openeuler", "label": "openEuler",            "label_zh": "openEuler",         "icon": "", "color": "#002FA7", "sort_order": 57},
    {"category": "os", "value": "linux-kylin",     "label": "Kylin OS",             "label_zh": "麒麟OS",            "icon": "", "color": "#D72638", "sort_order": 58},
    {"category": "os", "value": "linux-uos",       "label": "UOS (Deepin)",         "label_zh": "统信UOS",           "icon": "", "color": "#0078D6", "sort_order": 59},
    {"category": "os", "value": "windows-server",  "label": "Windows Server",       "label_zh": "Windows Server",    "icon": "", "color": "#00A4EF", "sort_order": 60},
    {"category": "os", "value": "esxi",            "label": "VMware ESXi",          "label_zh": "ESXi",              "icon": "", "color": "#696566", "sort_order": 65},
    {"category": "os", "value": "proxmox-ve",      "label": "Proxmox VE",           "label_zh": "Proxmox VE",        "icon": "", "color": "#E57000", "sort_order": 66},
    {"category": "os", "value": "hyper-v",         "label": "Microsoft Hyper-V",    "label_zh": "Hyper-V",           "icon": "", "color": "#00A4EF", "sort_order": 67},

    # os — 操作系统 (存储)
    {"category": "os", "value": "ontap",       "label": "NetApp ONTAP",       "label_zh": "ONTAP",              "icon": "", "color": "#0067C5", "sort_order": 70},
    {"category": "os", "value": "unity-os",    "label": "Dell EMC UnityOS",   "label_zh": "UnityOS",            "icon": "", "color": "#6E2585", "sort_order": 71},
    {"category": "os", "value": "purity",      "label": "Pure Storage Purity","label_zh": "Purity",             "icon": "", "color": "#FE5000", "sort_order": 72},
    {"category": "os", "value": "oceanstor-os","label": "Huawei OceanStor OS","label_zh": "华为OceanStor OS",   "icon": "", "color": "#CF0A2C", "sort_order": 73},

    # ═══════════════════════════════════════════════════════════════
    # role — 网络角色
    # ═══════════════════════════════════════════════════════════════
    {"category": "role", "value": "core",          "label": "Core",            "label_zh": "核心层",       "icon": "🏛️", "color": "#dc2626", "sort_order": 1},
    {"category": "role", "value": "distribution",  "label": "Distribution",    "label_zh": "汇聚层",       "icon": "🔗", "color": "#ea580c", "sort_order": 2},
    {"category": "role", "value": "access",        "label": "Access",          "label_zh": "接入层",       "icon": "🔌", "color": "#16a34a", "sort_order": 3},
    {"category": "role", "value": "edge",          "label": "Edge",            "label_zh": "边缘",         "icon": "🌐", "color": "#2563eb", "sort_order": 4},
    {"category": "role", "value": "border",        "label": "Border",          "label_zh": "边界路由",     "icon": "🚧", "color": "#9333ea", "sort_order": 5},
    {"category": "role", "value": "spine",         "label": "Spine",           "label_zh": "Spine",        "icon": "🏗️", "color": "#0891b2", "sort_order": 6},
    {"category": "role", "value": "leaf",          "label": "Leaf",            "label_zh": "Leaf",         "icon": "🍃", "color": "#059669", "sort_order": 7},
    {"category": "role", "value": "tor",           "label": "Top of Rack",     "label_zh": "架顶交换机",   "icon": "📦", "color": "#0d9488", "sort_order": 8},
    {"category": "role", "value": "management",    "label": "Management",      "label_zh": "管理",         "icon": "🔧", "color": "#6b7280", "sort_order": 9},
    {"category": "role", "value": "gateway",       "label": "Gateway",         "label_zh": "网关",         "icon": "🚪", "color": "#7c3aed", "sort_order": 10},
    {"category": "role", "value": "dmz",           "label": "DMZ",             "label_zh": "DMZ",          "icon": "🛡️", "color": "#b91c1c", "sort_order": 11},
    {"category": "role", "value": "wan-edge",      "label": "WAN Edge",        "label_zh": "WAN边缘",     "icon": "🌍", "color": "#1d4ed8", "sort_order": 12},
    {"category": "role", "value": "dc-gateway",    "label": "DC Gateway",      "label_zh": "数据中心网关", "icon": "🏢", "color": "#4338ca", "sort_order": 13},
    {"category": "role", "value": "oob",           "label": "Out-of-Band",     "label_zh": "带外管理",     "icon": "🔓", "color": "#78716c", "sort_order": 14},
    {"category": "role", "value": "ilo-bmc",       "label": "iLO / BMC",       "label_zh": "iLO/BMC管理",  "icon": "🖧", "color": "#57534e", "sort_order": 15},
    {"category": "role", "value": "compute",       "label": "Compute Node",    "label_zh": "计算节点",     "icon": "⚡", "color": "#3b82f6", "sort_order": 16},
    {"category": "role", "value": "storage-node",  "label": "Storage Node",    "label_zh": "存储节点",     "icon": "💾", "color": "#a855f7", "sort_order": 17},
    {"category": "role", "value": "database",      "label": "Database Server", "label_zh": "数据库服务器", "icon": "🗃️", "color": "#f59e0b", "sort_order": 18},
    {"category": "role", "value": "app-server",    "label": "App Server",      "label_zh": "应用服务器",   "icon": "⚙️", "color": "#10b981", "sort_order": 19},
    {"category": "role", "value": "web-server",    "label": "Web Server",      "label_zh": "Web服务器",    "icon": "🌐", "color": "#06b6d4", "sort_order": 20},
    {"category": "role", "value": "dns-server",    "label": "DNS Server",      "label_zh": "DNS服务器",    "icon": "📝", "color": "#0ea5e9", "sort_order": 21},
    {"category": "role", "value": "dhcp-server",   "label": "DHCP Server",     "label_zh": "DHCP服务器",   "icon": "📋", "color": "#14b8a6", "sort_order": 22},
    {"category": "role", "value": "ntp-server",    "label": "NTP Server",      "label_zh": "NTP服务器",    "icon": "⏱️", "color": "#8b5cf6", "sort_order": 23},
    {"category": "role", "value": "monitor",       "label": "Monitor Server",  "label_zh": "监控服务器",   "icon": "📊", "color": "#ec4899", "sort_order": 24},
    {"category": "role", "value": "backup-server", "label": "Backup Server",   "label_zh": "备份服务器",   "icon": "📀", "color": "#64748b", "sort_order": 25},

    # ═══════════════════════════════════════════════════════════════
    # env — 环境
    # ═══════════════════════════════════════════════════════════════
    {"category": "env", "value": "production",  "label": "Production",       "label_zh": "生产环境",   "icon": "🟢", "color": "#16a34a", "sort_order": 1},
    {"category": "env", "value": "staging",     "label": "Staging",          "label_zh": "预发布环境", "icon": "🟡", "color": "#eab308", "sort_order": 2},
    {"category": "env", "value": "development", "label": "Development",      "label_zh": "开发环境",   "icon": "🔵", "color": "#3b82f6", "sort_order": 3},
    {"category": "env", "value": "testing",     "label": "Testing",          "label_zh": "测试环境",   "icon": "🟣", "color": "#8b5cf6", "sort_order": 4},
    {"category": "env", "value": "lab",         "label": "Lab",              "label_zh": "实验室",     "icon": "🧪", "color": "#06b6d4", "sort_order": 5},
    {"category": "env", "value": "dr",          "label": "Disaster Recovery","label_zh": "灾备环境",   "icon": "🔴", "color": "#ef4444", "sort_order": 6},
    {"category": "env", "value": "dmz",         "label": "DMZ",              "label_zh": "DMZ区域",    "icon": "🛡️", "color": "#b91c1c", "sort_order": 7},

    # ═══════════════════════════════════════════════════════════════
    # function — 功能标签
    # ═══════════════════════════════════════════════════════════════
    {"category": "function", "value": "routing",         "label": "Routing",          "label_zh": "路由",           "icon": "🔀", "color": "#6366f1", "sort_order": 1},
    {"category": "function", "value": "switching",       "label": "Switching",        "label_zh": "交换",           "icon": "🔌", "color": "#8b5cf6", "sort_order": 2},
    {"category": "function", "value": "security",        "label": "Security",         "label_zh": "安全",           "icon": "🛡️", "color": "#ef4444", "sort_order": 3},
    {"category": "function", "value": "vpn",             "label": "VPN",              "label_zh": "VPN",            "icon": "🔒", "color": "#14b8a6", "sort_order": 4},
    {"category": "function", "value": "load-balancing",  "label": "Load Balancing",   "label_zh": "负载均衡",       "icon": "⚖️", "color": "#f59e0b", "sort_order": 5},
    {"category": "function", "value": "wireless",        "label": "Wireless",         "label_zh": "无线",           "icon": "📡", "color": "#06b6d4", "sort_order": 6},
    {"category": "function", "value": "compute",         "label": "Compute",          "label_zh": "计算",           "icon": "⚡", "color": "#3b82f6", "sort_order": 7},
    {"category": "function", "value": "storage",         "label": "Storage",          "label_zh": "存储",           "icon": "💾", "color": "#a855f7", "sort_order": 8},
    {"category": "function", "value": "virtualization",  "label": "Virtualization",   "label_zh": "虚拟化",         "icon": "☁️", "color": "#0ea5e9", "sort_order": 9},
    {"category": "function", "value": "containerization","label": "Containerization", "label_zh": "容器化",         "icon": "🐳", "color": "#0284c7", "sort_order": 10},
    {"category": "function", "value": "monitoring",      "label": "Monitoring",       "label_zh": "监控",           "icon": "📊", "color": "#ec4899", "sort_order": 11},
    {"category": "function", "value": "dns",             "label": "DNS",              "label_zh": "DNS",            "icon": "📝", "color": "#0ea5e9", "sort_order": 12},
    {"category": "function", "value": "dhcp",            "label": "DHCP",             "label_zh": "DHCP",           "icon": "📋", "color": "#14b8a6", "sort_order": 13},
    {"category": "function", "value": "backup",          "label": "Backup",           "label_zh": "备份",           "icon": "📀", "color": "#64748b", "sort_order": 14},
    {"category": "function", "value": "voice-uc",        "label": "Voice / UC",       "label_zh": "语音/统一通信",  "icon": "📞", "color": "#10b981", "sort_order": 15},
    {"category": "function", "value": "sdwan",           "label": "SD-WAN",           "label_zh": "SD-WAN",         "icon": "🌐", "color": "#0891b2", "sort_order": 16},
    {"category": "function", "value": "nac",             "label": "NAC",              "label_zh": "网络准入控制",   "icon": "🚦", "color": "#be185d", "sort_order": 17},
    {"category": "function", "value": "waf",             "label": "WAF",              "label_zh": "Web应用防火墙",  "icon": "🕸️", "color": "#dc2626", "sort_order": 18},
    {"category": "function", "value": "ids-ips",         "label": "IDS/IPS",          "label_zh": "入侵检测/防御",  "icon": "🔍", "color": "#b91c1c", "sort_order": 19},
    {"category": "function", "value": "log-audit",       "label": "Log & Audit",      "label_zh": "日志审计",       "icon": "📜", "color": "#78716c", "sort_order": 20},
    {"category": "function", "value": "database",        "label": "Database",         "label_zh": "数据库",         "icon": "🗃️", "color": "#f59e0b", "sort_order": 21},
    {"category": "function", "value": "middleware",      "label": "Middleware",        "label_zh": "中间件",         "icon": "⚙️", "color": "#6b7280", "sort_order": 22},
]

# ────────────────────────────────────────────────────────────────────
# Service functions
# ────────────────────────────────────────────────────────────────────

def seed_builtin_tags(conn) -> int:
    """Insert all BUILTIN_TAGS into tag_definitions. Returns count of newly inserted."""
    inserted = 0
    now = datetime.now(timezone.utc).isoformat()
    for tag in BUILTIN_TAGS:
        tag_id = f"builtin-{tag['category']}-{tag['value']}"
        try:
            cursor = conn.execute(
                '''
                INSERT INTO tag_definitions (id, category, value, label, label_zh, color, icon, description, sort_order, built_in, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT (category, value) DO NOTHING
                ''',
                (
                    tag_id,
                    tag['category'],
                    tag['value'],
                    tag['label'],
                    tag.get('label_zh', ''),
                    tag.get('color', ''),
                    tag.get('icon', ''),
                    tag.get('description', ''),
                    tag.get('sort_order', 0),
                    now,
                ),
            )
            if getattr(cursor, 'rowcount', 1) > 0:
                inserted += 1
        except Exception:
            pass  # duplicate — ON CONFLICT handles it
    conn.commit()
    logger.info(f"[TagService] Seeded {inserted} built-in tags (total definitions: {len(BUILTIN_TAGS)})")
    return inserted


def list_tag_definitions(conn, category: str | None = None) -> list[dict]:
    """Return all tag definitions, optionally filtered by category."""
    if category:
        rows = conn.execute(
            'SELECT * FROM tag_definitions WHERE category = ? ORDER BY sort_order, value',
            (category,),
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM tag_definitions ORDER BY category, sort_order, value'
        ).fetchall()
    return [dict(r) for r in rows]


def get_tag_definition(conn, tag_id: str) -> dict | None:
    row = conn.execute('SELECT * FROM tag_definitions WHERE id = ?', (tag_id,)).fetchone()
    return dict(row) if row else None


def create_tag_definition(conn, category: str, value: str, label: str, **kwargs) -> dict:
    """Create a user-defined tag. Raises ValueError if duplicate (category,value)."""
    tag_id = f"custom-{category}-{value}"
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            '''
            INSERT INTO tag_definitions (id, category, value, label, label_zh, color, icon, description, sort_order, built_in, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            ''',
            (
                tag_id,
                category,
                value,
                label,
                kwargs.get('label_zh', ''),
                kwargs.get('color', ''),
                kwargs.get('icon', ''),
                kwargs.get('description', ''),
                kwargs.get('sort_order', 0),
                now,
            ),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        if 'UNIQUE' in str(e).upper():
            raise ValueError(f"Tag '{category}:{value}' already exists")
        raise
    return {"id": tag_id, "category": category, "value": value, "label": label, **kwargs}


def update_tag_definition(conn, tag_id: str, **kwargs) -> dict | None:
    """Update a tag definition. Only non-builtin tags can have category/value changed."""
    existing = get_tag_definition(conn, tag_id)
    if not existing:
        return None
    allowed = ['label', 'label_zh', 'color', 'icon', 'description', 'sort_order']
    if not existing['built_in']:
        allowed += ['category', 'value']
    sets = []
    params = []
    for k in allowed:
        if k in kwargs:
            sets.append(f"{k} = ?")
            params.append(kwargs[k])
    if not sets:
        return existing
    params.append(tag_id)
    conn.execute(f"UPDATE tag_definitions SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    return get_tag_definition(conn, tag_id)


def delete_tag_definition(conn, tag_id: str) -> bool:
    """Delete a tag definition and all device associations. Built-in tags cannot be deleted."""
    existing = get_tag_definition(conn, tag_id)
    if not existing:
        return False
    if existing['built_in']:
        raise ValueError("Built-in tags cannot be deleted")
    conn.execute('DELETE FROM device_tags WHERE tag_id = ?', (tag_id,))
    conn.execute('DELETE FROM tag_definitions WHERE id = ?', (tag_id,))
    conn.commit()
    return True


# ────────────────────────────────────────────────────────────────────
# Device ↔ Tag associations
# ────────────────────────────────────────────────────────────────────

def get_device_tags(conn, device_id: str) -> list[dict]:
    """Return all tags attached to a device."""
    rows = conn.execute(
        '''
        SELECT td.*, dt.created_at AS assigned_at, dt.created_by
        FROM device_tags dt
        JOIN tag_definitions td ON td.id = dt.tag_id
        WHERE dt.device_id = ?
        ORDER BY td.category, td.sort_order
        ''',
        (device_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_device_tags(conn, device_id: str, tag_ids: list[str], created_by: str = '') -> list[dict]:
    """Replace all tags on a device with the given list. Returns new tag list."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute('DELETE FROM device_tags WHERE device_id = ?', (device_id,))
    for tid in tag_ids:
        conn.execute(
            'INSERT INTO device_tags (device_id, tag_id, created_at, created_by) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING',
            (device_id, tid, now, created_by),
        )
    conn.commit()
    return get_device_tags(conn, device_id)


def add_device_tag(conn, device_id: str, tag_id: str, created_by: str = '') -> bool:
    """Add a single tag to a device. Returns True if tag was added, False if already existed."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            'INSERT INTO device_tags (device_id, tag_id, created_at, created_by) VALUES (?, ?, ?, ?)',
            (device_id, tag_id, now, created_by),
        )
        conn.commit()
        return True
    except Exception:
        return False


def remove_device_tag(conn, device_id: str, tag_id: str) -> bool:
    """Remove a single tag from a device."""
    cursor = conn.execute(
        'DELETE FROM device_tags WHERE device_id = ? AND tag_id = ?',
        (device_id, tag_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def batch_set_device_tags(conn, device_ids: list[str], tag_ids: list[str], created_by: str = '') -> int:
    """Set the given tags on multiple devices (additive, does not remove existing)."""
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for did in device_ids:
        for tid in tag_ids:
            try:
                conn.execute(
                    'INSERT INTO device_tags (device_id, tag_id, created_at, created_by) VALUES (?, ?, ?, ?)',
                    (did, tid, now, created_by),
                )
                count += 1
            except Exception:
                pass  # already exists
    conn.commit()
    return count


def find_devices_by_tags(conn, tag_ids: list[str], match_all: bool = True) -> list[str]:
    """Find device IDs that have given tags. match_all=True requires ALL tags, False requires ANY."""
    if not tag_ids:
        return []
    placeholders = ','.join('?' * len(tag_ids))
    if match_all:
        rows = conn.execute(
            f'''
            SELECT device_id
            FROM device_tags
            WHERE tag_id IN ({placeholders})
            GROUP BY device_id
            HAVING COUNT(DISTINCT tag_id) = ?
            ''',
            (*tag_ids, len(tag_ids)),
        ).fetchall()
    else:
        rows = conn.execute(
            f'SELECT DISTINCT device_id FROM device_tags WHERE tag_id IN ({placeholders})',
            tag_ids,
        ).fetchall()
    return [r['device_id'] for r in rows]


def get_tag_statistics(conn) -> dict:
    """Return tag usage statistics: count per category, most used tags, etc."""
    category_counts = conn.execute(
        'SELECT category, COUNT(*) as count FROM tag_definitions GROUP BY category ORDER BY category'
    ).fetchall()
    usage_counts = conn.execute(
        '''
        SELECT td.id, td.category, td.value, td.label, td.label_zh, COUNT(dt.device_id) as device_count
        FROM tag_definitions td
        LEFT JOIN device_tags dt ON dt.tag_id = td.id
        GROUP BY td.id
        HAVING device_count > 0
        ORDER BY device_count DESC
        LIMIT 20
        '''
    ).fetchall()
    total_definitions = conn.execute('SELECT COUNT(*) FROM tag_definitions').fetchone()[0]
    total_assignments = conn.execute('SELECT COUNT(*) FROM device_tags').fetchone()[0]
    tagged_devices = conn.execute('SELECT COUNT(DISTINCT device_id) FROM device_tags').fetchone()[0]
    return {
        "total_definitions": total_definitions,
        "total_assignments": total_assignments,
        "tagged_devices": tagged_devices,
        "categories": {r['category']: r['count'] for r in category_counts},
        "top_used": [dict(r) for r in usage_counts],
    }
