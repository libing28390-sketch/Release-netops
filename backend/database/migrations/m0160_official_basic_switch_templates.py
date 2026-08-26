"""Seed reviewed basic configuration templates for Huawei, H3C and Cisco.

The earlier official-template migrations intentionally started with a small
set of representative VLAN, interface, routing and VXLAN examples.  This
follow-up fills the day-to-day campus and data-centre command surface so a
knowledge query is not forced through the OSPF-only fallback path.
"""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 160
NAME = "official_basic_switch_templates"


def _columns(cursor, use_pg: bool) -> set[str]:
    if use_pg:
        cursor.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'templates'
            """
        )
        return {str(row[0]) for row in cursor.fetchall()}
    return {str(row[1]) for row in cursor.execute("PRAGMA table_info(templates)").fetchall()}


def _ensure_columns(cursor, use_pg: bool) -> None:
    definitions = {
        "description": "TEXT DEFAULT ''",
        "platform_family": "TEXT DEFAULT ''",
        "software_version": "TEXT DEFAULT ''",
        "official_reference": "TEXT DEFAULT ''",
        "validation_status": "TEXT DEFAULT 'draft'",
        "source_type": "TEXT DEFAULT 'custom'",
        "risk_level": "TEXT DEFAULT 'low'",
        "status": "TEXT DEFAULT 'draft'",
        "current_version": "TEXT DEFAULT '1.0'",
        "is_official": "INTEGER DEFAULT 0",
        "created_by": "TEXT DEFAULT ''",
        "created_at": "TEXT DEFAULT ''",
        "updated_at": "TEXT DEFAULT ''",
    }
    existing = _columns(cursor, use_pg)
    for column, definition in definitions.items():
        if column not in existing:
            cursor.execute(f"ALTER TABLE templates ADD COLUMN {column} {definition}")


_HUAWEI_REF = "https://support.huawei.com/enterprise/en/doc/EDOC1100459417/bbc53f99/command-support"
_H3C_REF = "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_CG-18642/19/202404/2105879_294551_0.htm"
_CISCO_REF = "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/rtng/b_1713_rtng_9300_cg.html"


_TEMPLATES = (
    # Huawei VRP campus basics.
    {
        "id": "official-huawei-vlan-basic",
        "name": "VLAN 创建（华为 VRP）", "vendor": "Huawei", "category": "switching",
        "platform": "huawei_vrp", "version": "V200R023 / V300R024",
        "description": "创建单个业务 VLAN 并设置描述。",
        "content": """system-view
vlan {{ vlan_id | default(10) }}
 description {{ vlan_name | default(\"USERS\") }}
quit
display vlan {{ vlan_id | default(10) }}""",
        "rollback": """system-view
undo vlan {{ vlan_id | default(10) }}
return""",
        "reference": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans",
    },
    {
        "id": "official-huawei-static-route-basic",
        "name": "静态路由（华为 VRP）", "vendor": "Huawei", "category": "routing",
        "platform": "huawei_vrp", "version": "V200R023 / V300R024",
        "description": "配置 IPv4 单播静态路由，适用于简单或稳定的园区网络。",
        "content": """system-view
ip route-static {{ destination | default(\"192.0.2.0\") }} {{ mask | default(\"255.255.255.0\") }} {{ next_hop | default(\"192.0.2.254\") }} description {{ route_description | default(\"STATIC_ROUTE\") }}
return

display ip routing-table protocol static""",
        "rollback": """system-view
undo ip route-static {{ destination | default(\"192.0.2.0\") }} {{ mask | default(\"255.255.255.0\") }} {{ next_hop | default(\"192.0.2.254\") }}
return""",
        "reference": "https://support.huawei.com/enterprise/en/doc/DOC1000047418/bfd73d2e/static-route-configuration",
    },
    {
        "id": "official-huawei-bgp-basic",
        "name": "BGP 基础配置（华为 VRP）", "vendor": "Huawei", "category": "routing",
        "platform": "huawei_vrp", "version": "V200R023 / V300R024",
        "description": "配置 IPv4 单播 BGP 邻居并发布一个本地网段。",
        "content": """system-view
bgp {{ local_as | default(65001) }}
 router-id {{ router_id | default(\"192.0.2.1\") }}
 peer {{ peer_ip | default(\"192.0.2.2\") }} as-number {{ peer_as | default(65002) }}
 ipv4-family unicast
  network {{ network | default(\"192.0.2.0\") }} {{ mask | default(\"255.255.255.0\") }}
  peer {{ peer_ip | default(\"192.0.2.2\") }} enable
quit
return

display bgp peer""",
        "rollback": """system-view
undo bgp {{ local_as | default(65001) }}
return""",
        "reference": "https://support.huawei.com/enterprise/en/doc/EDOC1100214493/f0d8283e/network-bgp",
    },
    {
        "id": "official-huawei-acl-basic",
        "name": "基础 ACL（华为 VRP）", "vendor": "Huawei", "category": "security",
        "platform": "huawei_vrp", "version": "V200R023 / V300R024",
        "description": "创建 IPv4 基础 ACL，按源地址允许管理网段并拒绝其他流量。",
        "content": """system-view
acl number {{ acl_number | default(2000) }}
 rule 5 permit source {{ source_network | default(\"192.0.2.0\") }} {{ source_wildcard | default(\"0.0.0.255\") }}
 rule 100 deny source any
quit
display acl {{ acl_number | default(2000) }}""",
        "rollback": """system-view
undo acl number {{ acl_number | default(2000) }}
return""",
        "reference": _HUAWEI_REF,
    },
    {
        "id": "official-huawei-ssh-basic",
        "name": "SSH/ 网管登录（华为 VRP）", "vendor": "Huawei", "category": "security",
        "platform": "huawei_vrp", "version": "V200R023 / V300R024",
        "description": "启用 Stelnet、创建本地管理员并限制 VTY 仅使用 SSH。密码由密钥库注入。",
        "content": """system-view
stelnet server enable
ssh user {{ username | default(\"netops\") }}
ssh user {{ username | default(\"netops\") }} authentication-type password
ssh user {{ username | default(\"netops\") }} service-type stelnet
aaa
 local-user {{ username | default(\"netops\") }} password irreversible-cipher {{ password_from_vault | default(\"<from-secret-vault:password>\") }}
 local-user {{ username | default(\"netops\") }} privilege level 15
 local-user {{ username | default(\"netops\") }} service-type ssh
quit
user-interface vty 0 4
 authentication-mode aaa
 protocol inbound ssh
quit
return""",
        "rollback": """system-view
undo user-interface vty 0 4
undo ssh user {{ username | default(\"netops\") }}
undo local-user {{ username | default(\"netops\") }}
return""",
        "reference": _HUAWEI_REF,
    },
    {
        "id": "official-huawei-stp-basic",
        "name": "MSTP 基础配置（华为 VRP）", "vendor": "Huawei", "category": "switching",
        "platform": "huawei_vrp", "version": "V200R023 / V300R024",
        "description": "启用 MSTP 并建立基础区域；生产环境需按拓扑规划实例和根桥。",
        "content": """system-view
stp enable
stp mode mstp
stp region-configuration
 region-name {{ region_name | default(\"CAMPUS\") }}
 instance 1 vlan {{ instance_vlans | default(\"10 20 30\") }}
 active region-configuration
quit
display stp brief""",
        "rollback": """system-view
undo stp enable
return""",
        "reference": _HUAWEI_REF,
    },
    {
        "id": "official-huawei-ntp-client-basic",
        "name": "NTP 客户端（华为 VRP）", "vendor": "Huawei", "category": "management",
        "platform": "huawei_vrp", "version": "V200R023 / V300R024",
        "description": "指定 NTP 服务器并使用 LoopBack 作为源接口。",
        "content": """system-view
ntp server source-interface {{ source_interface | default(\"LoopBack0\") }}
ntp unicast-server {{ ntp_server_ip | default(\"192.0.2.123\") }}
return

display ntp-service status""",
        "rollback": """system-view
undo ntp unicast-server {{ ntp_server_ip | default(\"192.0.2.123\") }}
return""",
        "reference": "https://support.huawei.com/enterprise/en/doc/EDOC1100420157/8169f6dd/example-for-configuring-authenticated-ntp-broadcast-mode",
    },
    {
        "id": "official-huawei-snmpv3-basic",
        "name": "SNMPv3 基础配置（华为 VRP）", "vendor": "Huawei", "category": "management",
        "platform": "huawei_vrp", "version": "V200R023 / V300R024",
        "description": "创建 SNMPv3 authPriv 用户；认证和加密密钥必须从密钥库注入。",
        "content": """system-view
snmp-agent
snmp-agent sys-info version v3
snmp-agent group v3 {{ snmp_group | default(\"NMS-GROUP\") privacy
snmp-agent usm-user v3 {{ snmp_user | default(\"nms-user\") }} {{ snmp_group | default(\"NMS-GROUP\") }} authentication-mode sha {{ snmp_auth_key }} privacy-mode aes128 {{ snmp_priv_key }}
snmp-agent target-host trap address udp-domain {{ nms_ip | default(\"192.0.2.50\") }} params securityname {{ snmp_user | default(\"nms-user\") }} v3 privacy
return""",
        "rollback": """system-view
undo snmp-agent target-host trap address udp-domain {{ nms_ip | default(\"192.0.2.50\") }} params securityname {{ snmp_user | default(\"nms-user\") }} v3 privacy
undo snmp-agent usm-user v3 {{ snmp_user | default(\"nms-user\") }}
return""",
        "reference": _HUAWEI_REF,
    },

    # H3C Comware 7 campus and data-centre basics.
    {
        "id": "official-h3c-vlan-basic",
        "name": "VLAN 创建（H3C Comware 7）", "vendor": "H3C", "category": "switching",
        "platform": "h3c_comware", "version": "Comware 7",
        "description": "创建业务 VLAN 并设置描述。",
        "content": """system-view
vlan {{ vlan_id | default(10) }}
 description {{ vlan_name | default(\"USERS\") }}
quit
display vlan {{ vlan_id | default(10) }}""",
        "rollback": """system-view
undo vlan {{ vlan_id | default(10) }}
return""",
        "reference": "https://www.h3c.com/en/d_201905/1189999_294551_0.htm",
    },
    {
        "id": "official-h3c-static-route-basic",
        "name": "静态路由（H3C Comware 7）", "vendor": "H3C", "category": "routing",
        "platform": "h3c_comware", "version": "Comware 7",
        "description": "配置 IPv4 单播静态路由或默认路由。",
        "content": """system-view
ip route-static {{ destination | default(\"192.0.2.0\") }} {{ prefix_length | default(24) }} {{ next_hop | default(\"192.0.2.254\") }} description {{ route_description | default(\"STATIC_ROUTE\") }}
return

display ip routing-table protocol static""",
        "rollback": """system-view
undo ip route-static {{ destination | default(\"192.0.2.0\") }} {{ prefix_length | default(24) }} {{ next_hop | default(\"192.0.2.254\") }}
return""",
        "reference": "https://www.h3c.com/en/d_202303/1813694_294551_0.htm",
    },
    {
        "id": "official-h3c-bgp-basic",
        "name": "BGP 基础配置（H3C Comware 7）", "vendor": "H3C", "category": "routing",
        "platform": "h3c_comware", "version": "Comware 7",
        "description": "配置 IPv4 单播 BGP 邻居并发布本地网段。",
        "content": """system-view
bgp {{ local_as | default(65001) }}
 router-id {{ router_id | default(\"192.0.2.2\") }}
 peer {{ peer_ip | default(\"192.0.2.1\") }} as-number {{ peer_as | default(65002) }}
 address-family ipv4 unicast
  network {{ network | default(\"192.0.2.0\") }} {{ prefix_length | default(24) }}
  peer {{ peer_ip | default(\"192.0.2.1\") }} enable
quit
return

display bgp peer""",
        "rollback": """system-view
undo bgp {{ local_as | default(65001) }}
return""",
        "reference": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_S6805_S9850_CGs_Release_671x-9253/05/202303/1790630_294551_0.htm",
    },
    {
        "id": "official-h3c-acl-basic",
        "name": "基础 ACL（H3C Comware 7）", "vendor": "H3C", "category": "security",
        "platform": "h3c_comware", "version": "Comware 7",
        "description": "创建 IPv4 基础 ACL，允许管理网段并拒绝其他源地址。",
        "content": """system-view
acl basic {{ acl_number | default(2000) }}
 rule 5 permit source {{ source_network | default(\"192.0.2.0\") }} {{ source_wildcard | default(\"0.0.0.255\") }}
 rule 100 deny source any
quit
display acl {{ acl_number | default(2000) }}""",
        "rollback": """system-view
undo acl basic {{ acl_number | default(2000) }}
return""",
        "reference": "https://www.h3c.com/en/d_202205/1607933_294551_0.htm",
    },
    {
        "id": "official-h3c-ssh-basic",
        "name": "SSH 管理登录（H3C Comware 7）", "vendor": "H3C", "category": "security",
        "platform": "h3c_comware", "version": "Comware 7",
        "description": "启用 SSH、创建本地管理员并限制 VTY 使用 SSH。密码由密钥库注入。",
        "content": """system-view
ssh server enable
public-key local create rsa
local-user {{ username | default(\"netops\") }} class manage
 password hash {{ password_from_vault | default(\"<from-secret-vault:password>\") }}
 service-type ssh
 authorization-attribute user-role network-admin
quit
user-interface vty 0 4
 authentication-mode scheme
 protocol inbound ssh
quit
return""",
        "rollback": """system-view
undo user-interface vty 0 4
undo local-user {{ username | default(\"netops\") }}
undo ssh server enable
return""",
        "reference": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_S6520X_S6520-SI_CG-R6615Pxx/11/202407/2216314_294551_0.htm",
    },
    {
        "id": "official-h3c-stp-basic",
        "name": "MSTP 基础配置（H3C Comware 7）", "vendor": "H3C", "category": "switching",
        "platform": "h3c_comware", "version": "Comware 7",
        "description": "启用 MSTP 并建立基础区域；根桥优先级应按实际拓扑规划。",
        "content": """system-view
stp enable
stp mode mstp
stp region-configuration
 region-name {{ region_name | default(\"CAMPUS\") }}
 instance 1 vlan {{ instance_vlans | default(\"10 20 30\") }}
 active region-configuration
quit
display stp brief""",
        "rollback": """system-view
undo stp enable
return""",
        "reference": _H3C_REF,
    },
    {
        "id": "official-h3c-ntp-client-basic",
        "name": "NTP 客户端（H3C Comware 7）", "vendor": "H3C", "category": "management",
        "platform": "h3c_comware", "version": "Comware 7",
        "description": "启用 NTP 并指定单播时间服务器。",
        "content": """system-view
ntp-service enable
ntp-service unicast-server {{ ntp_server_ip | default(\"192.0.2.123\") }} source {{ source_interface | default(\"LoopBack0\") }}
return

display ntp-service status""",
        "rollback": """system-view
undo ntp-service unicast-server {{ ntp_server_ip | default(\"192.0.2.123\") }}
return""",
        "reference": "https://www.h3c.com/en/d_202405/2120007_294551_0.htm",
    },
    {
        "id": "official-h3c-snmpv3-basic",
        "name": "SNMPv3 基础配置（H3C Comware 7）", "vendor": "H3C", "category": "management",
        "platform": "h3c_comware", "version": "Comware 7",
        "description": "创建 SNMPv3 authPriv 用户；认证和加密密钥必须从密钥库注入。",
        "content": """system-view
snmp-agent
snmp-agent sys-info version v3
snmp-agent group v3 {{ snmp_group | default(\"NMS-GROUP\") privacy
snmp-agent usm-user v3 {{ snmp_user | default(\"nms-user\") }} {{ snmp_group | default(\"NMS-GROUP\") }} authentication-mode sha {{ snmp_auth_key }} privacy-mode aes128 {{ snmp_priv_key }}
snmp-agent target-host trap address udp-domain {{ nms_ip | default(\"192.0.2.50\") }} params securityname {{ snmp_user | default(\"nms-user\") }} v3 privacy
return""",
        "rollback": """system-view
undo snmp-agent target-host trap address udp-domain {{ nms_ip | default(\"192.0.2.50\") }} params securityname {{ snmp_user | default(\"nms-user\") }} v3 privacy
undo snmp-agent usm-user v3 {{ snmp_user | default(\"nms-user\") }}
return""",
        "reference": _H3C_REF,
    },

    # Cisco IOS XE campus basics.
    {
        "id": "official-cisco-vlan-basic",
        "name": "VLAN 创建（Cisco IOS XE）", "vendor": "Cisco", "category": "switching",
        "platform": "cisco_iosxe", "version": "IOS XE 17.x",
        "description": "创建业务 VLAN 并设置名称。",
        "content": """enable
configure terminal
vlan {{ vlan_id | default(10) }}
 name {{ vlan_name | default(\"USERS\") }}
exit
end

show vlan id {{ vlan_id | default(10) }}""",
        "rollback": """configure terminal
no vlan {{ vlan_id | default(10) }}
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/configuration_guide/vlan/b_173_vlan_9400_cg.pdf",
    },
    {
        "id": "official-cisco-static-route-basic",
        "name": "静态路由（Cisco IOS XE）", "vendor": "Cisco", "category": "routing",
        "platform": "cisco_iosxe", "version": "IOS XE 17.x",
        "description": "配置 IPv4 单播静态路由或默认路由。",
        "content": """enable
configure terminal
ip routing
ip route {{ destination | default(\"192.0.2.0\") }} {{ mask | default(\"255.255.255.0\") }} {{ next_hop | default(\"192.0.2.254\") }}
end

show ip route static""",
        "rollback": """configure terminal
no ip route {{ destination | default(\"192.0.2.0\") }} {{ mask | default(\"255.255.255.0\") }} {{ next_hop | default(\"192.0.2.254\") }}
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-8/configuration_guide/rtng/b_178_rtng_9300_cg/protocol_independent_features.html",
    },
    {
        "id": "official-cisco-bgp-basic",
        "name": "BGP 基础配置（Cisco IOS XE）", "vendor": "Cisco", "category": "routing",
        "platform": "cisco_iosxe", "version": "IOS XE 17.13",
        "description": "配置 IPv4 单播 BGP 邻居并发布一个本地网段。",
        "content": """enable
configure terminal
ip routing
router bgp {{ local_as | default(65001) }}
 bgp router-id {{ router_id | default(\"192.0.2.3\") }}
 neighbor {{ peer_ip | default(\"192.0.2.2\") }} remote-as {{ peer_as | default(65002) }}
 address-family ipv4
  network {{ network | default(\"192.0.2.0\") }} mask {{ mask | default(\"255.255.255.0\") }}
  neighbor {{ peer_ip | default(\"192.0.2.2\") }} activate
 exit-address-family
end

show ip bgp summary""",
        "rollback": """configure terminal
no router bgp {{ local_as | default(65001) }}
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/rtng/b_1713_rtng_9300_cg/configuring_bgp.html",
    },
    {
        "id": "official-cisco-acl-basic",
        "name": "基础 IPv4 ACL（Cisco IOS XE）", "vendor": "Cisco", "category": "security",
        "platform": "cisco_iosxe", "version": "IOS XE 17.13",
        "description": "创建扩展 IPv4 ACL，允许管理网段并拒绝其他流量。应用到接口前请确认方向。",
        "content": """enable
configure terminal
ip access-list extended {{ acl_name | default(\"MGMT_ONLY\") }}
 permit ip {{ source_network | default(\"192.0.2.0\") }} 0.0.0.255 any
 deny ip any any log
exit
end

show ip access-lists {{ acl_name | default(\"MGMT_ONLY\") }}""",
        "rollback": """configure terminal
no ip access-list extended {{ acl_name | default(\"MGMT_ONLY\") }}
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/sec/b_1713_sec_9300_cg/configuring_ipv4_acls.html",
    },
    {
        "id": "official-cisco-ssh-basic",
        "name": "SSH 管理登录（Cisco IOS XE）", "vendor": "Cisco", "category": "security",
        "platform": "cisco_iosxe", "version": "IOS XE 17.x",
        "description": "配置域名、RSA 密钥、SSH v2 和本地管理员；密码由密钥库注入。",
        "content": """enable
configure terminal
hostname {{ hostname | default(\"C9300\") }}
ip domain name {{ domain_name | default(\"example.invalid\") }}
crypto key generate rsa modulus {{ rsa_modulus | default(2048) }}
ip ssh version 2
username {{ username | default(\"netops\") }} privilege 15 secret {{ password_from_vault | default(\"<from-secret-vault:password>\") }}
line vty 0 4
 login local
 transport input ssh
end""",
        "rollback": """configure terminal
line vty 0 4
 no transport input ssh
exit
no username {{ username | default(\"netops\") }}
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/16-10/configuration_guide/sys_mgmt/b_1610_sys_mgmt_9300_cg/administering_the_device.html",
    },
    {
        "id": "official-cisco-stp-basic",
        "name": "生成树基础配置（Cisco IOS XE）", "vendor": "Cisco", "category": "switching",
        "platform": "cisco_iosxe", "version": "IOS XE 17.x",
        "description": "启用 Rapid PVST+ 并为接入口启用 PortFast 默认行为。",
        "content": """enable
configure terminal
spanning-tree mode rapid-pvst
spanning-tree portfast default
spanning-tree bpduguard enable
end

show spanning-tree summary""",
        "rollback": """configure terminal
no spanning-tree portfast default
no spanning-tree bpduguard enable
end""",
        "reference": _CISCO_REF,
    },
    {
        "id": "official-cisco-ntp-client-basic",
        "name": "NTP 客户端（Cisco IOS XE）", "vendor": "Cisco", "category": "management",
        "platform": "cisco_iosxe", "version": "IOS XE 17.x",
        "description": "指定 NTP 服务器并使用 Loopback 作为源接口。",
        "content": """enable
configure terminal
ntp server {{ ntp_server_ip | default(\"192.0.2.123\") }}
ntp source {{ source_interface | default(\"Loopback0\") }}
end

show ntp status""",
        "rollback": """configure terminal
no ntp server {{ ntp_server_ip | default(\"192.0.2.123\") }}
no ntp source {{ source_interface | default(\"Loopback0\") }}
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/16-10/configuration_guide/sys_mgmt/b_1610_sys_mgmt_9300_cg/administering_the_device.html",
    },
    {
        "id": "official-cisco-snmpv3-basic",
        "name": "SNMPv3 基础配置（Cisco IOS XE）", "vendor": "Cisco", "category": "management",
        "platform": "cisco_iosxe", "version": "IOS XE 17.x",
        "description": "创建 SNMPv3 authPriv 用户和 Trap 目标；密钥必须从密钥库注入。",
        "content": """enable
configure terminal
snmp-server group {{ snmp_group | default(\"NMS-GROUP\") }} v3 priv
snmp-server user {{ snmp_user | default(\"nms-user\") }} {{ snmp_group | default(\"NMS-GROUP\") }} v3 auth sha {{ snmp_auth_key }} priv aes 128 {{ snmp_priv_key }}
snmp-server host {{ nms_ip | default(\"192.0.2.50\") }} version 3 priv {{ snmp_user | default(\"nms-user\") }}
snmp-server enable traps
end""",
        "rollback": """configure terminal
no snmp-server host {{ nms_ip | default(\"192.0.2.50\") }} version 3 priv {{ snmp_user | default(\"nms-user\") }}
no snmp-server user {{ snmp_user | default(\"nms-user\") }} {{ snmp_group | default(\"NMS-GROUP\") }} v3
no snmp-server group {{ snmp_group | default(\"NMS-GROUP\") }} v3 priv
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/mgmt/management-configuration-guide/snmp-configuration.html",
    },

    # Data-centre-specific BGP starters keep product/OS filtering precise.
    {
        "id": "official-huawei-ce6800-bgp-basic",
        "name": "CloudEngine 6800 BGP 基础配置（华为 VRP）", "vendor": "Huawei", "category": "routing",
        "platform": "huawei_vrp", "version": "V300R024C10/C11",
        "description": "适用于 CloudEngine 6800 数据中心交换机的 IPv4 单播 BGP 邻居与网段发布。",
        "content": """system-view
bgp {{ local_as | default(65001) }}
 router-id {{ router_id | default(\"192.0.2.11\") }}
 peer {{ peer_ip | default(\"192.0.2.12\") }} as-number {{ peer_as | default(65002) }}
 ipv4-family unicast
  network {{ network | default(\"192.0.2.0\") }} {{ mask | default(\"255.255.255.0\") }}
  peer {{ peer_ip | default(\"192.0.2.12\") }} enable
quit
return

display bgp peer""",
        "rollback": """system-view
undo bgp {{ local_as | default(65001) }}
return""",
        "reference": "https://support.huawei.com/enterprise/en/doc/EDOC1100463796/5d103d4d/establishing-vxlan-tunnels-in-bgp-evpn-mode-distributed-vxlan-gateway",
    },
    {
        "id": "official-h3c-s6800-s9825-bgp-basic",
        "name": "S6800/S9825 BGP 基础配置（H3C Comware 7）", "vendor": "H3C", "category": "routing",
        "platform": "h3c_comware", "version": "Comware 7",
        "description": "适用于 H3C S6800/S9825/S9855 数据中心交换机的 IPv4 单播 BGP 基础配置。",
        "content": """system-view
bgp {{ local_as | default(65001) }}
 router-id {{ router_id | default(\"192.0.2.21\") }}
 peer {{ peer_ip | default(\"192.0.2.22\") }} as-number {{ peer_as | default(65002) }}
 address-family ipv4 unicast
  network {{ network | default(\"192.0.2.0\") }} {{ prefix_length | default(24) }}
  peer {{ peer_ip | default(\"192.0.2.22\") }} enable
quit
return

display bgp peer""",
        "rollback": """system-view
undo bgp {{ local_as | default(65001) }}
return""",
        "reference": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_CG-29160/06/202509/2657318_294551_0.htm",
    },
    {
        "id": "official-cisco-nexus-bgp-basic",
        "name": "Nexus 3000/9000 BGP 基础配置（Cisco NX-OS）", "vendor": "Cisco", "category": "routing",
        "platform": "cisco_nxos", "version": "NX-OS 9.x/10.x",
        "description": "适用于 Cisco Nexus 数据中心交换机的 IPv4 单播 BGP 邻居与网段发布。",
        "content": """configure terminal
feature bgp
router bgp {{ local_as | default(65001) }}
 router-id {{ router_id | default(\"192.0.2.31\") }}
 address-family ipv4 unicast
 neighbor {{ peer_ip | default(\"192.0.2.32\") }}
  remote-as {{ peer_as | default(65002) }}
  address-family ipv4 unicast
 network {{ network | default(\"192.0.2.0/24\") }}
copy running-config startup-config

show bgp ipv4 unicast summary""",
        "rollback": """configure terminal
no router bgp {{ local_as | default(65001) }}
no feature bgp""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/6-x/unicast/configuration/guide/l3_cli_nxos.pdf",
    },
)


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_columns(cursor, use_pg)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for item in _TEMPLATES:
        existing = cursor.execute("SELECT id FROM templates WHERE id = ?", (item["id"],)).fetchone()
        values = (
            item["name"], "cli", item["category"], item["vendor"], item["content"], item["rollback"],
            item["description"], item["platform"], item["version"], item["reference"],
            "official_reference_reviewed", "official", "low", "published", "1.0", 1,
            "system", now, now,
        )
        if existing:
            cursor.execute(
                """
                UPDATE templates
                SET name = ?, type = ?, category = ?, vendor = ?, content = ?, rollback = ?,
                    description = ?, platform_family = ?, software_version = ?, official_reference = ?,
                    validation_status = ?, source_type = ?, risk_level = ?, status = ?,
                    current_version = ?, is_official = ?, created_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (*values[:17], values[18], item["id"]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO templates (
                    id, name, type, category, vendor, content, rollback, last_used,
                    description, platform_family, software_version, official_reference,
                    validation_status, source_type, risk_level, status, current_version,
                    is_official, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item["id"], *values),
            )


__all__ = ["VERSION", "NAME", "upgrade"]
