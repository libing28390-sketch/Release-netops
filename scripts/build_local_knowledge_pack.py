"""Build the checked-in four-vendor local Knowledge Engine source pack.

The pack is deliberately source-backed but test-only.  It contains concise,
authored Markdown summaries and command keywords derived from public vendor
pages; it is not a mirror of those pages and it is not production Gold
evidence.  The command never performs network I/O.  A deterministic ZIP can
be produced for an isolated local PostgreSQL test environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
DEFAULT_SOURCE_DIR = ROOT / "data" / "kb_import"
DEFAULT_CATALOG = DEFAULT_SOURCE_DIR / "source_catalog.yaml"
DEFAULT_MANIFEST = DEFAULT_SOURCE_DIR / "manifest.json"
DEFAULT_COVERAGE = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-local-pack-coverage.json"
ANCHOR_DATASET = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-anchors-50-v3-signed-20260905.yaml"
GOLD_400_DATASET = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-400.yaml"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ai.services.knowledge_metadata import (  # noqa: E402
    MetadataParseError,
    MetadataValidationError,
    parse_markdown_document,
    validate_metadata,
)
from ai.security.classification import classify_text  # noqa: E402


PACK_SCHEMA = "nexora-local-knowledge-pack-v1"
PACK_ID = "nexora-kb-official-local-4vendor-v1"
SOURCE_CHECKED_AT = "2026-09-05"
CORE_FEATURES = (
    "vlan",
    "access_port",
    "trunk",
    "ospf",
    "bgp",
    "lacp",
    "acl",
    "ssh",
    "ntp",
    "static_route",
)
VENDORS = ("Huawei", "Cisco", "H3C", "Ruijie")
SUPPLEMENTAL_TRACK_ID = "four_vendor_feature_verification"
SUPPLEMENTAL_DOCUMENT_COUNT = len(VENDORS) * len(CORE_FEATURES)

VENDOR_PROFILES: dict[str, dict[str, str]] = {
    "Huawei": {
        "slug": "huawei",
        "product_family": "Huawei VRP network switches",
        "product_series": "CE6800/CE12800/S5700/S6700",
        "product_model": "CE6800/CE12800/S5700/S6700 series scope",
        "os_family": "VRP",
        "os_generation": "VRP8",
        "software_train": "V200/V300",
        "software_release": "V200R023/V300R024",
        "cli_platform": "huawei_vrp",
    },
    "Cisco": {
        "slug": "cisco",
        "product_family": "Cisco IOS-XE campus and data-center switches",
        "product_series": "Catalyst 3850/Catalyst 9300",
        "product_model": "C3850/C9300 series scope",
        "os_family": "IOS-XE",
        "os_generation": "IOS-XE 17",
        "software_train": "17.x",
        "software_release": "IOS-XE 17.x",
        "cli_platform": "cisco_iosxe",
    },
    "H3C": {
        "slug": "h3c",
        "product_family": "H3C Comware switch platforms",
        "product_series": "S5130/S6520X/S6850",
        "product_model": "S5130/S6520X/S6850 series scope",
        "os_family": "Comware",
        "os_generation": "Comware 7",
        "software_train": "Comware 7",
        "software_release": "Comware 7 R66xx/R67xx",
        "cli_platform": "h3c_comware",
    },
    "Ruijie": {
        "slug": "ruijie",
        "product_family": "Ruijie RGOS switch platforms",
        "product_series": "RG-S6220 and RGOS switches",
        "product_model": "RG-S6220 series scope",
        "os_family": "RGOS",
        "os_generation": "RGOS 10/11",
        "software_train": "RGOS",
        "software_release": "RGOS 10.x/11.x",
        "cli_platform": "ruijie_rgos",
    },
}

OFFICIAL_HOSTS: dict[str, set[str]] = {
    "Huawei": {"support.huawei.com", "info.support.huawei.com"},
    "Cisco": {"www.cisco.com"},
    "H3C": {"www.h3c.com"},
    "Ruijie": {"www.ruijie.com.cn"},
}

FEATURE_DOMAINS = {
    "vlan": "switching",
    "access_port": "switching",
    "trunk": "switching",
    "ospf": "routing",
    "bgp": "routing",
    "lacp": "switching",
    "acl": "security",
    "ssh": "management",
    "ntp": "management",
    "static_route": "routing",
    "vxlan": "overlay",
    "port_security": "security",
    "diagnostic": "operations",
    "interface": "operations",
    "hsrp": "reliability",
    "lldp": "topology",
    "bfd": "routing",
    "pam": "security",
}

FEATURE_LABELS = {
    "vlan": "VLAN",
    "access_port": "Access 端口",
    "trunk": "Trunk 端口",
    "ospf": "OSPF",
    "bgp": "BGP",
    "lacp": "链路聚合",
    "acl": "ACL",
    "ssh": "SSH",
    "ntp": "NTP",
    "static_route": "静态路由",
    "vxlan": "VXLAN/EVPN",
    "port_security": "端口安全",
    "diagnostic": "排障",
    "interface": "接口状态",
    "hsrp": "HSRP",
    "lldp": "LLDP",
    "bfd": "BFD",
    "pam": "AAA/权限管理",
}

SOURCE_URLS: dict[str, dict[str, list[str]]] = {
    "Huawei": {
        "vlan": ["https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans"],
        "access_port": ["https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans"],
        "trunk": ["https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans"],
        "ospf": ["https://support.huawei.com/enterprise/en/doc/EDOC1100459053/e1fd2273/example-for-configuring-ospf-multi-area-adjacency"],
        "bgp": ["https://support.huawei.com/enterprise/en/doc/EDOC1100313446/5829dca4/bgp-peer-relationship-fails-to-be-established"],
        "lacp": ["https://support.huawei.com/enterprise/en/doc/EDOC1100368579/b7014cbe/eth-trunk-configuration-commands"],
        "acl": ["https://info.support.huawei.com/hedex/api/pages/EDOC1100277650/AZM1016J/05/resources/vrp/dc_vrp_acl4_cfg_0057.html"],
        "ssh": ["https://info.support.huawei.com/hedex/api/pages/EDOC1100334321/AEM1020X/06/resources/dc/dc_cfg_login_0006.html"],
        "ntp": ["https://info.support.huawei.com/hedex/api/pages/EDOC1100334321/AEM1020X/05/resources/dc/display_ntp-service_status.html"],
        "static_route": ["https://support.huawei.com/enterprise/en/doc/EDOC1100380848/5b495a28/ipv4-static-route-configuration"],
    },
    "Cisco": {
        "vlan": ["https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/configuration_guide/vlan/b_173_vlan_9400_cg.pdf"],
        "access_port": ["https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/infra/interface-characteristics/interface-characteristics-configuration-guide.html"],
        "trunk": ["https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/configuration_guide/vlan/b_173_vlan_9400_cg.pdf"],
        "ospf": ["https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/rtng/b_1713_rtng_9300_cg.html"],
        "bgp": ["https://www.cisco.com/c/en/us/support/ios-nx-os-software/ios-xe-17/products-command-reference-list.html"],
        "lacp": ["https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/lyr2-fwd/etherchannel/etherchannel-configuration-guide/etherchannels.html"],
        "acl": ["https://www.cisco.com/c/en/us/support/ios-nx-os-software/ios-xe-17/products-command-reference-list.html"],
        "ssh": ["https://www.cisco.com/c/en/us/td/docs/routers/ios-xe/system-management/system-management/m_cf-cli-basics.html"],
        "ntp": ["https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/syst-mgmt/b-system-management/m_bsm-time-calendar-set.html"],
        "static_route": ["https://www.cisco.com/c/en/us/support/ios-nx-os-software/ios-xe-17/products-command-reference-list.html"],
    },
    "H3C": {
        "vlan": ["https://www.h3c.com/en/d_201905/1189999_294551_0.htm"],
        "access_port": ["https://www.h3c.com/en/d_201905/1189999_294551_0.htm"],
        "trunk": ["https://www.h3c.com/en/d_201905/1189999_294551_0.htm"],
        "ospf": ["https://www.h3c.com/en/d_200806/607561_294551_0.htm"],
        "bgp": ["https://www.h3c.com/en/d_202410/2284517_294551_0.htm"],
        "lacp": ["https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_CG-26720/06/202506/2514322_294551_0.htm"],
        "acl": ["https://www.h3c.com/en/Support/Resource_Center/EN/Home/Routers/00-Public/Reference_Guides/Command_References/H3C_MSR_Comware_7_CR-R0615/11/202210/1709612_294551_0.htm"],
        "ssh": ["https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Reference_Guides/Command_References/H3C_CR-26719/03/202506/2513814_294551_0.htm"],
        "ntp": ["https://www.h3c.com/en/d_202405/2120007_294551_0.htm"],
        "static_route": ["https://www.h3c.com/en/d_202205/1607649_294551_0.htm"],
    },
    "Ruijie": {
        "vlan": ["https://www.ruijie.com.cn/fw/wt/18515/"],
        "access_port": ["https://www.ruijie.com.cn/fw/wt/35635/"],
        "trunk": ["https://www.ruijie.com.cn/fw/wt/37263"],
        "ospf": ["https://www.ruijie.com.cn/fw/wt/32518/"],
        "bgp": ["https://www.ruijie.com.cn/fw/wt/90930"],
        "lacp": ["https://www.ruijie.com.cn/fw/wt/37263"],
        "acl": ["https://www.ruijie.com.cn/fw/wt/37269/"],
        "ssh": ["https://www.ruijie.com.cn/fw/wt/35612/"],
        "ntp": ["https://www.ruijie.com.cn/fw/wt/18858/"],
        "static_route": ["https://www.ruijie.com.cn/fw/wt/32514/"],
    },
}

COMMANDS: dict[tuple[str, str], list[str]] = {
    ("Huawei", "vlan"): ["system-view", "vlan 10", "description USERS", "display vlan 10"],
    ("Huawei", "access_port"): ["system-view", "interface GigabitEthernet 0/0/1", "port link-type access", "port default vlan 10"],
    ("Huawei", "trunk"): ["system-view", "interface GigabitEthernet 0/0/48", "port link-type trunk", "port trunk allow-pass vlan 10 20 30"],
    ("Huawei", "ospf"): ["system-view", "ospf 1", "area 0.0.0.0", "network 192.0.2.0 0.0.0.255"],
    ("Huawei", "bgp"): ["system-view", "bgp 65000", "peer 192.0.2.2 as-number 65001", "ipv4-family unicast", "peer 192.0.2.2 enable"],
    ("Huawei", "lacp"): ["system-view", "interface Eth-Trunk 10", "mode lacp-static", "display eth-trunk 10"],
    ("Huawei", "acl"): ["system-view", "acl number 3000", "rule 5 deny tcp destination-port eq 443", "display acl 3000"],
    ("Huawei", "ssh"): ["system-view", "rsa local-key-pair create", "stelnet server enable", "user-interface vty 0 4", "protocol inbound ssh"],
    ("Huawei", "ntp"): ["system-view", "ntp-service enable", "ntp unicast-server 192.0.2.123", "display ntp-service status"],
    ("Huawei", "static_route"): ["system-view", "ip route-static 0.0.0.0 0.0.0.0 192.0.2.1", "display ip routing-table protocol static"],
    ("Cisco", "vlan"): ["configure terminal", "vlan 10", "name USERS", "show vlan id 10"],
    ("Cisco", "access_port"): ["configure terminal", "interface GigabitEthernet1/0/1", "switchport mode access", "switchport access vlan 10"],
    ("Cisco", "trunk"): ["configure terminal", "interface GigabitEthernet1/0/48", "switchport mode trunk", "switchport trunk allowed vlan 10,20,30"],
    ("Cisco", "ospf"): ["configure terminal", "router ospf 1", "network 192.0.2.0 0.0.0.255 area 0"],
    ("Cisco", "bgp"): ["configure terminal", "router bgp 65000", "neighbor 192.0.2.2 remote-as 65001", "address-family ipv4", "network 192.0.2.0 mask 255.255.255.0"],
    ("Cisco", "lacp"): ["configure terminal", "interface range GigabitEthernet1/0/47-48", "channel-group 10 mode active", "interface Port-channel10", "show etherchannel summary"],
    ("Cisco", "acl"): ["configure terminal", "ip access-list extended 101", "permit tcp any any eq 443", "show access-lists 101"],
    ("Cisco", "ssh"): ["configure terminal", "ip ssh version 2", "crypto key generate rsa modulus 2048", "line vty 0 4", "transport input ssh"],
    ("Cisco", "ntp"): ["configure terminal", "ntp server 192.0.2.123", "clock timezone CST 8 0", "show ntp status"],
    ("Cisco", "static_route"): ["configure terminal", "ip route 0.0.0.0 0.0.0.0 192.0.2.1", "show ip route static"],
    ("H3C", "vlan"): ["system-view", "vlan 10", "description USERS", "display vlan 10"],
    ("H3C", "access_port"): ["system-view", "interface GigabitEthernet 1/0/1", "port link-type access", "port access vlan 10"],
    ("H3C", "trunk"): ["system-view", "interface GigabitEthernet 1/0/48", "port link-type trunk", "port trunk permit vlan 10 20 30"],
    ("H3C", "ospf"): ["system-view", "ospf 1", "area 0.0.0.0", "network 192.0.2.0 0.0.0.255"],
    ("H3C", "bgp"): ["system-view", "bgp 65000", "peer 192.0.2.2 as-number 65001", "address-family ipv4 unicast", "peer 192.0.2.2 enable"],
    ("H3C", "lacp"): ["system-view", "interface Bridge-Aggregation 10", "link-aggregation mode dynamic", "display link-aggregation verbose"],
    ("H3C", "acl"): ["system-view", "acl advanced 3000", "rule 5 permit tcp source 192.0.2.0 0.0.0.255", "interface GigabitEthernet 1/0/1", "packet-filter 3000 inbound"],
    ("H3C", "ssh"): ["system-view", "stelnet server enable", "ssh server enable", "line vty 0 4", "authentication-mode scheme"],
    ("H3C", "ntp"): ["system-view", "ntp-service enable", "ntp-service unicast-server 192.0.2.123", "display ntp-service status"],
    ("H3C", "static_route"): ["system-view", "ip route-static 0.0.0.0 0 192.0.2.1", "display ip routing-table protocol static"],
    ("Ruijie", "vlan"): ["enable", "configure terminal", "vlan 10", "show vlan"],
    ("Ruijie", "access_port"): ["enable", "configure terminal", "interface GigabitEthernet 0/1", "switchport mode access", "switchport access vlan 10"],
    ("Ruijie", "trunk"): ["enable", "configure terminal", "interface GigabitEthernet 0/48", "switchport mode trunk", "switchport trunk allowed vlan 10,20,30"],
    ("Ruijie", "ospf"): ["enable", "configure terminal", "router ospf 1", "network 192.0.2.0 0.0.0.255 area 0", "show ip ospf neighbor"],
    ("Ruijie", "bgp"): ["enable", "configure terminal", "router bgp 65000", "neighbor 192.0.2.2 remote-as 65001", "network 192.0.2.0 mask 255.255.255.0"],
    ("Ruijie", "lacp"): ["enable", "configure terminal", "interface range GigabitEthernet 0/1-2", "port-group 1 mode active", "interface aggregateport 1"],
    ("Ruijie", "acl"): ["enable", "configure terminal", "ip access-list standard 1", "1 permit any", "show access-lists 1"],
    ("Ruijie", "ssh"): ["enable", "configure terminal", "enable service ssh-server", "ip ssh version 2", "crypto key generate rsa"],
    ("Ruijie", "ntp"): ["enable", "configure terminal", "sntp server 192.0.2.123", "show sntp status"],
    ("Ruijie", "static_route"): ["enable", "configure terminal", "ip route 0.0.0.0 0.0.0.0 192.0.2.1", "show ip route"],
}

VERIFICATION_COMMANDS: dict[tuple[str, str], list[str]] = {
    ("Huawei", "vlan"): ["display vlan 10", "display current-configuration"],
    ("Huawei", "access_port"): ["display interface brief", "display current-configuration interface GigabitEthernet 0/0/1"],
    ("Huawei", "trunk"): ["display interface GigabitEthernet 0/0/48", "display current-configuration interface GigabitEthernet 0/0/48"],
    ("Huawei", "ospf"): ["display ospf peer brief", "display ip routing-table"],
    ("Huawei", "bgp"): ["display bgp peer", "display bgp routing-table"],
    ("Huawei", "lacp"): ["display eth-trunk 10", "display interface Eth-Trunk 10"],
    ("Huawei", "acl"): ["display acl 3000", "display acl resource"],
    ("Huawei", "ssh"): ["display ssh server status", "display rsa local-key-pair public"],
    ("Huawei", "ntp"): ["display ntp-service status", "display ntp-service sessions"],
    ("Huawei", "static_route"): ["display ip routing-table protocol static", "display ip routing-table"],
    ("Cisco", "vlan"): ["show vlan brief", "show interfaces status"],
    ("Cisco", "access_port"): ["show interfaces status", "show interfaces GigabitEthernet1/0/1 switchport"],
    ("Cisco", "trunk"): ["show interfaces trunk", "show interfaces GigabitEthernet1/0/48 switchport"],
    ("Cisco", "ospf"): ["show ip ospf neighbor", "show ip route ospf"],
    ("Cisco", "bgp"): ["show ip bgp summary", "show ip route bgp"],
    ("Cisco", "lacp"): ["show etherchannel summary", "show lacp neighbor"],
    ("Cisco", "acl"): ["show access-lists 101", "show ip interface"],
    ("Cisco", "ssh"): ["show ip ssh", "show crypto key mypubkey rsa"],
    ("Cisco", "ntp"): ["show ntp status", "show ntp associations"],
    ("Cisco", "static_route"): ["show ip route static", "show ip cef"],
    ("H3C", "vlan"): ["display vlan brief", "display interface brief"],
    ("H3C", "access_port"): ["display interface brief", "display current-configuration interface GigabitEthernet 1/0/1"],
    ("H3C", "trunk"): ["display interface GigabitEthernet 1/0/48", "display vlan brief"],
    ("H3C", "ospf"): ["display ospf peer", "display ip routing-table protocol ospf"],
    ("H3C", "bgp"): ["display bgp peer ipv4", "display ip routing-table protocol bgp"],
    ("H3C", "lacp"): ["display link-aggregation verbose", "display link-aggregation summary"],
    ("H3C", "acl"): ["display acl 3000", "display packet-filter 3000"],
    ("H3C", "ssh"): ["display ssh server status", "display current-configuration | include stelnet"],
    ("H3C", "ntp"): ["display ntp-service status", "display ntp-service sessions"],
    ("H3C", "static_route"): ["display ip routing-table protocol static", "display ip routing-table"],
    ("Ruijie", "vlan"): ["show vlan", "show interface status"],
    ("Ruijie", "access_port"): ["show interface status", "show vlan"],
    ("Ruijie", "trunk"): ["show interface status", "show vlan"],
    ("Ruijie", "ospf"): ["show ip ospf neighbor", "show ip route ospf"],
    ("Ruijie", "bgp"): ["show ip bgp summary", "show ip route bgp"],
    ("Ruijie", "lacp"): ["show aggregateport 1 summary", "show interface aggregateport 1"],
    ("Ruijie", "acl"): ["show access-lists 1", "show ip access-group"],
    ("Ruijie", "ssh"): ["show ip ssh", "show ssh"],
    ("Ruijie", "ntp"): ["show sntp status", "show clock"],
    ("Ruijie", "static_route"): ["show ip route", "show ip route static"],
}

# A second, deliberately separate article for each core feature/vendor pair.
# These are read-only verification and troubleshooting summaries.  Keeping the
# commands in a table makes the extra corpus auditable and keeps the builder
# deterministic; the source URL still comes from SOURCE_URLS above.
SUPPLEMENTAL_COMMANDS: dict[tuple[str, str], list[str]] = {
    ("Huawei", "vlan"): ["display vlan summary", "display mac-address vlan 10"],
    ("Huawei", "access_port"): ["display interface brief", "display current-configuration interface GigabitEthernet 0/0/1"],
    ("Huawei", "trunk"): ["display interface GigabitEthernet 0/0/48", "display vlan"],
    ("Huawei", "ospf"): ["display ospf brief", "display ospf peer last-nbr-down"],
    ("Huawei", "bgp"): ["display bgp peer", "display bgp routing-table"],
    ("Huawei", "lacp"): ["display eth-trunk brief", "display eth-trunk 10"],
    ("Huawei", "acl"): ["display acl all", "display traffic-policy statistics"],
    ("Huawei", "ssh"): ["display ssh server status", "display current-configuration | include stelnet"],
    ("Huawei", "ntp"): ["display ntp-service status", "display clock"],
    ("Huawei", "static_route"): ["display ip routing-table protocol static", "display interface"],
    ("Cisco", "vlan"): ["show vlan brief", "show interfaces trunk"],
    ("Cisco", "access_port"): ["show interfaces status", "show interfaces GigabitEthernet1/0/1 switchport"],
    ("Cisco", "trunk"): ["show interfaces trunk", "show spanning-tree interface GigabitEthernet1/0/48 detail"],
    ("Cisco", "ospf"): ["show ip ospf interface brief", "show ip ospf neighbor"],
    ("Cisco", "bgp"): ["show ip bgp summary", "show ip bgp neighbors 192.0.2.2"],
    ("Cisco", "lacp"): ["show etherchannel summary", "show interfaces port-channel 10"],
    ("Cisco", "acl"): ["show access-lists 101", "show ip interface"],
    ("Cisco", "ssh"): ["show ip ssh", "show users"],
    ("Cisco", "ntp"): ["show ntp status", "show ntp associations"],
    ("Cisco", "static_route"): ["show ip route static", "show ip cef"],
    ("H3C", "vlan"): ["display vlan brief", "display mac-address vlan 10"],
    ("H3C", "access_port"): ["display interface brief", "display current-configuration interface GigabitEthernet 1/0/1"],
    ("H3C", "trunk"): ["display interface GigabitEthernet 1/0/48", "display vlan brief"],
    ("H3C", "ospf"): ["display ospf peer", "display ospf interface"],
    ("H3C", "bgp"): ["display bgp peer ipv4", "display bgp routing-table ipv4"],
    ("H3C", "lacp"): ["display link-aggregation verbose", "display link-aggregation summary"],
    ("H3C", "acl"): ["display acl 3000", "display packet-filter 3000"],
    ("H3C", "ssh"): ["display ssh server status", "display current-configuration | include stelnet"],
    ("H3C", "ntp"): ["display ntp-service status", "display clock"],
    ("H3C", "static_route"): ["display ip routing-table protocol static", "display ip routing-table"],
    ("Ruijie", "vlan"): ["show vlan", "show mac-address-table vlan 10"],
    ("Ruijie", "access_port"): ["show interface status", "show interface GigabitEthernet 0/1 switchport"],
    ("Ruijie", "trunk"): ["show interface status", "show vlan"],
    ("Ruijie", "ospf"): ["show ip ospf neighbor", "show ip ospf interface"],
    ("Ruijie", "bgp"): ["show ip bgp summary", "show ip bgp neighbors 192.0.2.2"],
    ("Ruijie", "lacp"): ["show aggregateport 1 summary", "show interface aggregateport 1"],
    ("Ruijie", "acl"): ["show access-lists 1", "show ip access-group"],
    ("Ruijie", "ssh"): ["show ip ssh", "show ssh"],
    ("Ruijie", "ntp"): ["show sntp status", "show clock"],
    ("Ruijie", "static_route"): ["show ip route", "show ip route static"],
}

SUPPLEMENTAL_FEATURE_NOTES = {
    "vlan": "先确认 VLAN 是否存在，再把端口归属、MAC 学习和两端链路状态放在同一时间点核对；不要只凭单条表项判断故障。",
    "access_port": "先确认接口物理状态、端口模式、PVID/接入 VLAN 和终端学习状态；改动前应记录现有配置。",
    "trunk": "重点核对两端允许 VLAN 集合、Native/PVID 语义和生成树状态；两端命令名称不同但排障维度相同。",
    "ospf": "按接口状态、邻居状态、区域参数和路由表顺序排查；邻居建立不代表目标前缀一定已进入路由表。",
    "bgp": "先看会话状态和最近错误，再看地址族激活、策略和路由表；不要把 Established 直接等同于路由已发布。",
    "lacp": "同时核对聚合成员、协商状态、速率/双工和对端配置；单成员 Up 不代表整个聚合链路健康。",
    "acl": "先确认规则方向、接口/业务上下文和命中计数，再评估放行或拒绝结果；生产策略变更必须有审批和回滚。",
    "ssh": "只读确认服务状态、密钥/认证链路和 VTY 入方向；不要在摘要、日志或测试数据中写入真实认证材料。",
    "ntp": "区分服务启用、服务器可达、选源状态和本地时钟偏差；时钟未同步时先保存状态再调整配置。",
    "static_route": "先确认下一跳可达、出接口和路由优先级，再核对路由表安装状态；避免在未确认回滚前覆盖默认路由。",
}

SUPPLEMENTAL_FAILURE_SIGNALS = {
    "vlan": "常见异常：VLAN 未创建、端口归属不一致、MAC 未学习或链路两端 VLAN 集合不同。",
    "access_port": "常见异常：接口 Down、端口仍处于 Trunk、PVID 不符或终端被错误隔离。",
    "trunk": "常见异常：允许列表不对、Native/PVID 不一致、生成树阻塞或两端协商参数不兼容。",
    "ospf": "常见异常：邻居停留在非 Full 状态、区域/网络宣告不一致、MTU 或认证参数不匹配。",
    "bgp": "常见异常：邻居未建立、地址族未激活、策略过滤前缀或下一跳不可达。",
    "lacp": "常见异常：成员未入组、聚合模式不一致、成员参数不一致或对端只形成单边聚合。",
    "acl": "常见异常：规则方向错误、顺序遮蔽、接口未应用或命中计数与预期不符。",
    "ssh": "常见异常：服务未启用、VTY 入方向受限、认证链路不完整或管理平面访问路径不可达。",
    "ntp": "常见异常：服务器不可达、未选中有效时钟源、偏差过大或时区/显示误解。",
    "static_route": "常见异常：下一跳不可达、路由未安装、优先级被其他路由覆盖或默认路由影响范围过大。",
}

CORE_TITLES = {
    "vlan": "VLAN 配置与验证",
    "access_port": "Access 接入口配置与验证",
    "trunk": "Trunk 中继端口配置与验证",
    "ospf": "OSPF 邻居与区域配置",
    "bgp": "BGP 邻居与路由发布配置",
    "lacp": "LACP 链路聚合配置与验证",
    "acl": "ACL 规则与应用配置",
    "ssh": "SSH/安全管理登录配置",
    "ntp": "NTP 时间同步配置与验证",
    "static_route": "IPv4 静态路由配置与验证",
}

ANCHOR_SPECIAL_IDS = {
    "ANCHOR-003": "local.huawei.vrp.interface_status_ce6885.v1",
    "ANCHOR-016": "local.huawei.vrp.ospf_bfd.v1",
    "ANCHOR-017": "local.huawei.vrp.vxlan_evpn.v1",
    "ANCHOR-018": "local.huawei.vrp.port_security.v1",
    "ANCHOR-019": "local.huawei.vrp.cpu_memory_diagnostic.v1",
    "ANCHOR-020": "local.huawei.vrp.super_password.v1",
    "ANCHOR-026": "local.cisco.iosxe.arp_mac_diagnostic.v1",
    "ANCHOR-027": "local.cisco.iosxe.hsrp.v1",
    "ANCHOR-028": "local.cisco.iosxe.aaa_authentication.v1",
    "ANCHOR-030": "local.h3c.comware7.interface_brief.v1",
    "ANCHOR-034": "local.h3c.comware7.arp_mac_diagnostic.v1",
    "ANCHOR-035": "local.ruijie.ruijie_rgos.access_port.v1",
    "ANCHOR-036": "local.ruijie.ruijie_rgos.lacp.v1",
    "ANCHOR-037": "local.ruijie.ruijie_rgos.static_route.v1",
    "ANCHOR-038": "local.ruijie.ruijie_rgos.ospf.v1",
    "ANCHOR-039": "local.ruijie.rgos.lldp_neighbor.v1",
    "ANCHOR-040": "local.ruijie.ruijie_rgos.acl.v1",
}


@dataclass(frozen=True)
class DocumentArtifact:
    document_id: str
    vendor: str
    feature: str
    relative_path: Path
    content: str
    metadata: dict[str, Any]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")


def _source_urls(vendor: str, feature: str) -> list[str]:
    urls = SOURCE_URLS.get(vendor, {}).get(feature, [])
    if not urls:
        raise ValueError(f"no source URL configured for {vendor}/{feature}")
    return list(urls)


def _validate_source_urls(vendor: str, urls: list[str]) -> None:
    allowed = OFFICIAL_HOSTS[vendor]
    for value in urls:
        parsed = urlsplit(str(value))
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"source URL must be HTTPS for {vendor}: {value}")
        if parsed.hostname.casefold() not in allowed:
            raise ValueError(
                f"source host {parsed.hostname} is not in the candidate allowlist for {vendor}"
            )
        if parsed.username or parsed.password:
            raise ValueError("source URL cannot contain credentials")


def _load_catalog(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError("local knowledge source catalog must be a mapping")
    if str(value.get("pack_id") or "") != PACK_ID:
        raise ValueError(f"unexpected pack_id: {value.get('pack_id')}")
    if value.get("test_only") is not True or value.get("production_eligible") is not False:
        raise ValueError("local pack must remain test_only and production_eligible=false")
    if str(value.get("external_network") or "") != "forbidden":
        raise ValueError("local pack must declare external_network=forbidden")
    if tuple(value.get("core_features") or ()) != CORE_FEATURES:
        raise ValueError("core feature list must match the frozen 400-case feature contract")
    if tuple(value.get("vendors") or ()) != VENDORS:
        raise ValueError("vendor list must be exactly Huawei, Cisco, H3C, Ruijie")
    specials = value.get("special_documents") or []
    if not isinstance(specials, list) or len(specials) != 14:
        raise ValueError("the 50-anchor supplement must contain exactly 14 documents")
    tracks = value.get("supplemental_tracks") or []
    if not isinstance(tracks, list) or len(tracks) != 1:
        raise ValueError("the local pack must declare exactly one supplemental track")
    track = tracks[0]
    if not isinstance(track, dict) or str(track.get("track_id") or "") != SUPPLEMENTAL_TRACK_ID:
        raise ValueError(f"missing supplemental track: {SUPPLEMENTAL_TRACK_ID}")
    if int(track.get("document_count") or 0) != SUPPLEMENTAL_DOCUMENT_COUNT:
        raise ValueError(
            f"supplemental track must contain {SUPPLEMENTAL_DOCUMENT_COUNT} documents"
        )
    seen: set[str] = set()
    for item in specials:
        if not isinstance(item, dict):
            raise ValueError("every special document must be a mapping")
        document_id = str(item.get("document_id") or "").strip()
        vendor = str(item.get("vendor") or "").strip()
        feature = str(item.get("feature") or "").strip()
        urls = item.get("source_urls") or []
        if not document_id or document_id in seen:
            raise ValueError(f"duplicate or missing special document_id: {document_id}")
        seen.add(document_id)
        if vendor not in VENDORS:
            raise ValueError(f"unsupported special document vendor: {vendor}")
        if not feature:
            raise ValueError(f"missing special document feature: {document_id}")
        if not isinstance(urls, list) or not urls:
            raise ValueError(f"special document has no source_urls: {document_id}")
        _validate_source_urls(vendor, [str(url) for url in urls])
        if not item.get("commands") or not item.get("verification_commands"):
            raise ValueError(f"special document requires command and verification lists: {document_id}")
    return value


def _core_records(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for vendor in VENDORS:
        profile = VENDOR_PROFILES[vendor]
        for feature in CORE_FEATURES:
            document_id = f"local.{profile['slug']}.{profile['cli_platform']}.{feature}.v1"
            records.append(
                {
                    "document_id": document_id,
                    "vendor": vendor,
                    "feature": feature,
                    "title": f"{vendor} {profile['os_family']} {CORE_TITLES[feature]}（本地官网摘要）",
                    "document_category": "configuration",
                    "source_urls": _source_urls(vendor, feature),
                    "commands": COMMANDS[(vendor, feature)],
                    "verification_commands": VERIFICATION_COMMANDS[(vendor, feature)],
                    "scope_note": (
                        f"来源页面用于 {vendor} {FEATURE_LABELS[feature]} 的候选证据。"
                        "具体型号、软件版本、板卡能力和命令参数必须在目标设备的版本化命令参考中复核。"
                    ),
                }
            )
    records.extend(_supplemental_records(catalog))
    for item in catalog.get("special_documents") or []:
        records.append(dict(item))
    return records


def _supplemental_records(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Build one read-only verification companion for every core pair."""

    tracks = catalog.get("supplemental_tracks") or []
    if not tracks or str(tracks[0].get("track_id") or "") != SUPPLEMENTAL_TRACK_ID:
        raise ValueError(f"missing supplemental track: {SUPPLEMENTAL_TRACK_ID}")
    records: list[dict[str, Any]] = []
    for vendor in VENDORS:
        profile = VENDOR_PROFILES[vendor]
        for feature in CORE_FEATURES:
            records.append(
                {
                    "document_id": (
                        f"local.{profile['slug']}.{profile['cli_platform']}."
                        f"{feature}.verification.v1"
                    ),
                    "vendor": vendor,
                    "feature": feature,
                    "subfeature": f"{feature}_verification_and_troubleshooting",
                    "title": (
                        f"{vendor} {profile['os_family']} "
                        f"{FEATURE_LABELS[feature]} 核验与排障（本地官网摘要）"
                    ),
                    "document_category": "troubleshooting",
                    "source_urls": _source_urls(vendor, feature),
                    "commands": SUPPLEMENTAL_COMMANDS[(vendor, feature)],
                    "verification_commands": VERIFICATION_COMMANDS[(vendor, feature)],
                    "scope_note": (
                        f"{SUPPLEMENTAL_FEATURE_NOTES[feature]} "
                        f"{SUPPLEMENTAL_FAILURE_SIGNALS[feature]} "
                        "来源页面用于候选证据定位，精确命令和输出字段仍需按型号与软件版本复核。"
                    ),
                    "track_id": SUPPLEMENTAL_TRACK_ID,
                }
            )
    return records


def _metadata_for(record: dict[str, Any]) -> dict[str, Any]:
    vendor = str(record["vendor"])
    feature = str(record["feature"])
    profile = VENDOR_PROFILES[vendor]
    urls = [str(url) for url in record["source_urls"]]
    metadata: dict[str, Any] = {
        "schema_version": "2.0",
        "document_id": str(record["document_id"]),
        "title": str(record["title"]),
        "vendor": vendor,
        "product_type": "network_switch",
        "document_category": str(record.get("document_category") or "configuration"),
        "source_type": "official_local",
        "official_only": True,
        # The pack is imported into an isolated test tenant and must be
        # visible to the default ``status=active`` retrieval/list queries.
        # This does not mean production-published: the explicit test_only and
        # production_eligible guards below remain in force.
        "status": "active",
        "product_family": profile["product_family"],
        "product_series": profile["product_series"],
        "product_model": profile["product_model"],
        "os_family": profile["os_family"],
        "os_generation": profile["os_generation"],
        "software_train": profile["software_train"],
        "software_release": profile["software_release"],
        "cli_platform": profile["cli_platform"],
        "feature_domain": FEATURE_DOMAINS.get(feature, "operations"),
        "feature": feature,
        "subfeature": str(record.get("subfeature") or feature),
        "risk_level": "medium" if feature in {"acl", "ssh", "port_security", "hsrp", "pam"} else "low",
        "verification_level": "official_reference_source_checked",
        "rag_priority": 85 if record.get("document_category") != "configuration" else 75,
        "source_url": urls[0],
        "source_urls": urls,
        "source_checked_at": SOURCE_CHECKED_AT,
        "source_version": f"official page checked {SOURCE_CHECKED_AT}",
        "source_reference_type": "public_official_page",
        "source_trust_level": "official",
        "content_origin": "authored_local_summary",
        "review_status": "source_provenance_verified",
        "test_only": True,
        "production_eligible": False,
        "pack_id": PACK_ID,
        "external_network": "forbidden",
        "keywords": [FEATURE_LABELS.get(feature, feature), feature, vendor, profile["cli_platform"]],
        "tags": ["local-pack", "official-reference-candidate", vendor.casefold(), feature],
    }
    return metadata


def _body_for(record: dict[str, Any], metadata: dict[str, Any]) -> str:
    commands = [str(item) for item in record.get("commands") or []]
    verification = [str(item) for item in record.get("verification_commands") or []]
    urls = [str(item) for item in metadata["source_urls"]]
    scope_note = str(record.get("scope_note") or "").strip()
    command_lines = "\n".join(f"    {item}" for item in commands)
    verification_lines = "\n".join(f"    {item}" for item in verification)
    source_lines = "\n".join(f"- {url}" for url in urls)
    feature = str(record["feature"])
    supplemental_section = ""
    if record.get("track_id") == SUPPLEMENTAL_TRACK_ID:
        supplemental_section = (
            "## 核验重点与异常线索\n\n"
            f"- {SUPPLEMENTAL_FEATURE_NOTES[feature]}\n"
            f"- {SUPPLEMENTAL_FAILURE_SIGNALS[feature]}\n\n"
        )
    return (
        f"# {metadata['title']}\n\n"
        "> 资料性质：本地官网来源摘要；当前仅用于隔离测试和候选 Gold 证据整理，"
        "不等同于生产发布或已完成人工 Gold 审核。\n\n"
        "## 适用范围\n\n"
        f"- 厂商：{metadata['vendor']}\n"
        f"- 产品范围：{metadata['product_series']}（精确型号仍需确认）\n"
        f"- CLI/系统：{metadata['cli_platform']} / {metadata['os_family']} {metadata['os_generation']}\n"
        f"- 主题：{FEATURE_LABELS.get(feature, feature)}\n\n"
        "## 官网摘要\n\n"
        f"{scope_note}\n\n"
        "本文只保留用于检索和人工复核的命令关键词，不复制官网全文；"
        "命令中的地址、VLAN、AS 号和接口均为文档化示例值，不能直接套用到生产网络。\n\n"
        "## 配置或命令摘要\n\n"
        f"{command_lines}\n\n"
        "## 验证命令\n\n"
        f"{verification_lines}\n\n"
        f"{supplemental_section}"
        "## 回滚/注意事项\n\n"
        "- 先记录设备型号、软件版本、当前配置和相关表项，再执行任何写命令。\n"
        "- 生产写操作需要变更审批、备份和厂商版本化命令参考；本摘要不授予执行权限。\n"
        "- 不同产品系列可能使用不同命令、参数或输出字段；发生冲突时应澄清型号/版本。\n\n"
        "## 来源与版本\n\n"
        f"- 核验日期：{SOURCE_CHECKED_AT}\n"
        f"- 来源类型：{metadata['source_reference_type']}\n"
        f"{source_lines}\n"
    )


def _artifact_path(record: dict[str, Any]) -> Path:
    category = str(record.get("document_category") or "configuration").strip().lower()
    root = {
        "hardware": "01_product",
        "command": "02_commands",
        "configuration": "03_configuration",
        "cli_output": "04_cli_outputs",
        "troubleshooting": "05_troubleshooting",
        "example": "06_examples",
    }.get(category, "03_configuration")
    vendor_slug = VENDOR_PROFILES[str(record["vendor"])]["slug"]
    name = _slug(str(record["document_id"])) + ".md"
    return Path(root) / vendor_slug / name


def _render_front_matter(metadata: dict[str, Any]) -> str:
    header = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    ).strip()
    return f"---\n{header}\n---\n\n"


def _build_artifacts(catalog: dict[str, Any]) -> list[DocumentArtifact]:
    records = _core_records(catalog)
    expected_count = (
        len(VENDORS) * len(CORE_FEATURES)
        + SUPPLEMENTAL_DOCUMENT_COUNT
        + len(catalog.get("special_documents") or [])
    )
    if len(records) != expected_count:
        raise ValueError(f"local pack must contain {expected_count} documents, got {len(records)}")
    artifacts: list[DocumentArtifact] = []
    seen_ids: set[str] = set()
    for record in records:
        document_id = str(record["document_id"])
        if document_id in seen_ids:
            raise ValueError(f"duplicate document_id: {document_id}")
        seen_ids.add(document_id)
        metadata = _metadata_for(record)
        body = _body_for(record, metadata)
        raw = _render_front_matter(metadata) + body
        relative_path = _artifact_path(record)
        directory_hint = f"kb_import/{relative_path.as_posix()}"
        try:
            parsed = parse_markdown_document(raw)
            validated = validate_metadata(
                parsed.metadata,
                directory_path=directory_hint,
                name=relative_path.name,
            )
        except (MetadataParseError, MetadataValidationError) as exc:
            raise ValueError(f"metadata validation failed for {relative_path}: {exc}") from exc
        if validated.get("vendor") != record["vendor"]:
            raise ValueError(f"vendor metadata drift for {relative_path}")
        if validated.get("document_id") != document_id:
            raise ValueError(f"document_id metadata drift for {relative_path}")
        if validated.get("document_category") != record.get("document_category", "configuration"):
            raise ValueError(f"category metadata drift for {relative_path}")
        credential_findings = {
            finding.category
            for finding in classify_text(raw)
            if finding.category in {
                "credential",
                "private_key",
                "snmp_community",
                "radius_or_tacacs_key",
                "jwt",
                "cookie",
            }
        }
        if credential_findings:
            raise ValueError(
                f"credential-bearing text is not allowed in local pack: {relative_path} "
                f"({', '.join(sorted(credential_findings))})"
            )
        artifacts.append(
            DocumentArtifact(
                document_id=document_id,
                vendor=str(record["vendor"]),
                feature=str(record["feature"]),
                relative_path=relative_path,
                content=raw.replace("\r\n", "\n").replace("\r", "\n"),
                metadata=validated,
            )
        )
    return sorted(artifacts, key=lambda item: item.relative_path.as_posix())


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_yaml_document(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return value if isinstance(value, dict) else {}


def _load_yaml_cases(path: Path) -> list[dict[str, Any]]:
    value = _load_yaml_document(path)
    cases = value.get("cases")
    return [item for item in cases if isinstance(item, dict)] if isinstance(cases, list) else []


def _candidate_id_index(artifacts: list[DocumentArtifact]) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = {}
    for artifact in artifacts:
        result.setdefault((artifact.vendor, artifact.feature), []).append(artifact.document_id)
    for key in result:
        result[key] = sorted(result[key])
    return result


def _coverage_report(artifacts: list[DocumentArtifact]) -> dict[str, Any]:
    index = _candidate_id_index(artifacts)
    anchor_cases = _load_yaml_cases(ANCHOR_DATASET)
    special_by_id = {case_id: document_id for case_id, document_id in ANCHOR_SPECIAL_IDS.items()}
    anchor_rows: list[dict[str, Any]] = []
    mapped = 0
    answer_cases = 0
    for case in anchor_cases:
        case_id = str(case.get("id") or "")
        expected = str(case.get("expected_outcome") or "").strip().lower()
        vendor = str(case.get("vendor") or "")
        feature = str(case.get("intent") or "").strip().lower()
        candidate_ids: list[str] = []
        if case_id in special_by_id:
            candidate_ids = [special_by_id[case_id]]
        elif expected == "answer" and vendor in VENDORS:
            feature = {"lag": "lacp", "route": "static_route"}.get(feature, feature)
            candidate_ids = index.get((vendor, feature), [])
        if candidate_ids:
            mapped += 1
        if expected == "answer":
            answer_cases += 1
        anchor_rows.append(
            {
                "id": case_id,
                "query": str(case.get("query") or ""),
                "expected_outcome": expected,
                "vendor": vendor or None,
                "feature": feature or None,
                "candidate_document_ids": candidate_ids,
                "status": "candidate_only" if candidate_ids else "guard_or_needs_collection",
                "gold_replacement": False,
                "human_review_required": expected == "answer",
            }
        )

    gold_dataset = _load_yaml_document(GOLD_400_DATASET)
    gold_cases = [item for item in gold_dataset.get("cases") or [] if isinstance(item, dict)]
    gold_review_policy = gold_dataset.get("review_policy") if isinstance(gold_dataset.get("review_policy"), dict) else {}
    gold_features = sorted({str(case.get("feature") or "") for case in gold_cases if case.get("feature")})
    gold_vendors = sorted({str(case.get("vendor") or "") for case in gold_cases if case.get("vendor")})
    vendor_feature_coverage = {
        vendor: {
            feature: bool(index.get((vendor, feature)))
            for feature in CORE_FEATURES
        }
        for vendor in VENDORS
    }
    return {
        "schema_version": 1,
        "pack_id": PACK_ID,
        "status": "candidate_only",
        "test_only": True,
        "production_eligible": False,
        "gold_replacement": False,
        "human_review_required": bool(gold_review_policy.get("human_review_required")),
        "anchor_50": {
            "dataset_id": "nexora-kb-eval-anchors-50-v3-signed-20260905",
            "case_count": len(anchor_cases),
            "answer_case_count": answer_cases,
            "candidate_mapped_case_count": mapped,
            "cases": anchor_rows,
        },
        "gold_400": {
            "dataset_id": str(gold_dataset.get("dataset_id") or "unknown"),
            "case_count": len(gold_cases),
            "test_fixture": bool(gold_dataset.get("test_only")),
            "production_gold_ready": bool(gold_dataset.get("production_eligible")) and not bool(gold_dataset.get("synthetic_data")),
            "human_review_required": bool(gold_review_policy.get("human_review_required")),
            "source_collection": str((gold_dataset.get("source_policy") or {}).get("source_collection") or "unknown"),
            "feature_set_in_dataset": gold_features,
            "vendors_in_dataset": gold_vendors,
            "candidate_vendor_feature_coverage": vendor_feature_coverage,
        },
    }


def _manifest(
    catalog_path: Path,
    artifacts: list[DocumentArtifact],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    documents = []
    for artifact in artifacts:
        raw = artifact.content.encode("utf-8")
        # Keep the local pack on the same wire contract as the normal
        # knowledge export.  The importer treats ``path`` as the ZIP member
        # name and requires the canonical content hash/byte fields; the
        # previous pack used source-relative paths and private aliases, so a
        # ZIP could be built successfully but could never be imported.
        archive_path = f"documents/{artifact.relative_path.as_posix()}"
        documents.append(
            {
                "path": archive_path,
                "document_id": artifact.document_id,
                "vendor": artifact.vendor,
                "feature": artifact.feature,
                "document_category": artifact.metadata.get("document_category"),
                "source_type": artifact.metadata.get("source_type"),
                "source_urls": list(artifact.metadata.get("source_urls") or []),
                "content_sha256": _sha256_bytes(raw),
                "content_bytes": len(raw),
            }
        )
    return {
        # ``knowledge-export-v1`` is the importer contract.  Keep the local
        # pack identity in ``manifest_type``/``pack_schema_version`` rather
        # than overloading this field with an incompatible integer value.
        "schema_version": "knowledge-export-v1",
        "pack_schema_version": 1,
        "manifest_type": PACK_SCHEMA,
        "pack_id": PACK_ID,
        "title": "Nexora 四厂商本地官网知识摘要包",
        "description": "Source-backed local summaries for isolated evaluation and candidate evidence review.",
        "test_only": True,
        "production_eligible": False,
        "gold_replacement": False,
        "external_network": "forbidden",
        "secrets": False,
        "customer_identifiers": False,
        "source_checked_at": SOURCE_CHECKED_AT,
        "source_catalog_sha256": _sha256_bytes(catalog_path.read_bytes()),
        # These top-level fields are part of ``knowledge-export-v1`` and are
        # intentionally repeated outside build_contract because the importer
        # validates them before it reads any document body.
        "embeddings_exported": False,
        "reindex_required_on_import": True,
        "vendor_count": len(VENDORS),
        "vendors": list(VENDORS),
        "core_features": list(CORE_FEATURES),
        "core_document_count": len(VENDORS) * len(CORE_FEATURES),
        "supplemental_track_id": SUPPLEMENTAL_TRACK_ID,
        "supplemental_document_count": SUPPLEMENTAL_DOCUMENT_COUNT,
        "special_document_count": len(artifacts) - len(VENDORS) * len(CORE_FEATURES) - SUPPLEMENTAL_DOCUMENT_COUNT,
        "document_count": len(documents),
        "documents": documents,
        "evaluation_coverage": coverage,
        "build_contract": {
            "deterministic": True,
            "network_calls": False,
            "embedding_required_on_import": True,
            "postgresql_only_runtime_import": True,
            "human_review_required_before_production": False,
        },
    }


def _write_archive(
    output_path: Path,
    catalog_path: Path,
    artifacts: list[DocumentArtifact],
    manifest: dict[str, Any],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    catalog_bytes = catalog_path.read_bytes()
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        members: list[tuple[str, bytes]] = [
            ("manifest.json", manifest_bytes),
            ("source_catalog.yaml", catalog_bytes),
        ]
        members.extend(
            (
                f"documents/{artifact.relative_path.as_posix()}",
                artifact.content.encode("utf-8"),
            )
            for artifact in artifacts
        )
        for name, data in sorted(members, key=lambda item: item[0]):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)


def build_pack(
    *,
    catalog_path: Path = DEFAULT_CATALOG,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    manifest_path: Path = DEFAULT_MANIFEST,
    coverage_path: Path = DEFAULT_COVERAGE,
    archive_path: Path | None = None,
    check_only: bool = False,
) -> dict[str, Any]:
    catalog = _load_catalog(catalog_path)
    artifacts = _build_artifacts(catalog)
    coverage = _coverage_report(artifacts)
    manifest = _manifest(catalog_path, artifacts, coverage)

    if not check_only:
        source_dir.mkdir(parents=True, exist_ok=True)
        for artifact in artifacts:
            destination = source_dir / artifact.relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(artifact.content, encoding="utf-8", newline="\n")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        coverage_path.parent.mkdir(parents=True, exist_ok=True)
        coverage_path.write_text(
            json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if archive_path is not None:
        _write_archive(archive_path, catalog_path, artifacts, manifest)
    return {
        "status": "PASS",
        "manifest_type": PACK_SCHEMA,
        "pack_id": PACK_ID,
        "test_only": True,
        "production_eligible": False,
        "document_count": len(artifacts),
        "vendor_count": len(VENDORS),
        "vendors": list(VENDORS),
        "core_feature_count": len(CORE_FEATURES),
        "anchor_case_count": coverage["anchor_50"]["case_count"],
        "anchor_answer_case_count": coverage["anchor_50"]["answer_case_count"],
        "anchor_candidate_mapped_case_count": coverage["anchor_50"]["candidate_mapped_case_count"],
        "gold_400_case_count": coverage["gold_400"]["case_count"],
        "core_document_count": len(VENDORS) * len(CORE_FEATURES),
        "supplemental_document_count": SUPPLEMENTAL_DOCUMENT_COUNT,
        "special_document_count": len(artifacts) - len(VENDORS) * len(CORE_FEATURES) - SUPPLEMENTAL_DOCUMENT_COUNT,
        "archive": str(archive_path) if archive_path else None,
        "check_only": check_only,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--coverage-output", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--output", type=Path, default=None, help="optional deterministic ZIP output")
    parser.add_argument("--check-only", action="store_true", help="validate and render in memory without writing source files")
    args = parser.parse_args(argv)
    try:
        result = build_pack(
            catalog_path=args.catalog,
            source_dir=args.source_dir,
            manifest_path=args.manifest_output,
            coverage_path=args.coverage_output,
            archive_path=args.output,
            check_only=args.check_only,
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)[:500]}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
