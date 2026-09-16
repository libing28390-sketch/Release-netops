"""Seed reviewed missing campus/data-center switch feature starters."""

from __future__ import annotations

from datetime import datetime, timezone

VERSION = 164
NAME = "official_required_switch_features"


def _columns(cursor, use_pg: bool) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'templates'"
    )
    return {str(row[0]) for row in cursor.fetchall()}



def _ensure_columns(cursor, use_pg: bool) -> None:
    definitions = {
        "description": "TEXT DEFAULT ''",
        "platform_family": "TEXT DEFAULT ''",
        "software_version": "TEXT DEFAULT ''",
        "official_reference": "TEXT DEFAULT ''",
        "validation_status": "TEXT DEFAULT 'draft'",
        "source_type": "TEXT DEFAULT 'user'",
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


_TEMPLATES = (
    {
        "id": "official-huawei-aaa-local",
        "name": "AAA 本地管理员（华为 VRP）",
        "vendor": "Huawei",
        "category": "security",
        "platform": "huawei_vrp",
        "version": "V200R023 / V300R024",
        "description": "使用本地 AAA 用户库保护 SSH/VTY 管理登录；密码只从密钥库注入。",
        "content": """system-view
aaa
 local-user {{ username | default("netops") }} password irreversible-cipher {{ password_from_vault | default("<from-secret-vault:password>") }}
 local-user {{ username | default("netops") }} privilege level 15
 local-user {{ username | default("netops") }} service-type ssh
quit
user-interface vty 0 4
 authentication-mode aaa
 protocol inbound ssh
quit
return

display aaa local-user""",
        "rollback": """system-view
undo user-interface vty 0 4
undo aaa
return""",
        "reference": "https://info.support.huawei.com/hedex/api/pages/EDOC1100277644/AEM10221/03/resources/vrp/dc_vrp_aaa_cfg_1003.html",
    },
    {
        "id": "official-huawei-qos-mqc",
        "name": "MQC QoS 基础策略（华为 VRP）",
        "vendor": "Huawei",
        "category": "management",
        "platform": "huawei_vrp",
        "version": "V200R023 / V300R024",
        "description": "使用 traffic classifier/behavior/policy 识别 DSCP EF 流量并在接口入方向应用策略。",
        "content": """system-view
traffic classifier {{ classifier_name | default("VOICE") }} operator and
 if-match dscp ef
quit
traffic behavior {{ behavior_name | default("VOICE_BEHAVIOR") }}
 remark dscp ef
quit
traffic policy {{ policy_name | default("VOICE_POLICY") }}
 classifier {{ classifier_name | default("VOICE") }} behavior {{ behavior_name | default("VOICE_BEHAVIOR") }}
quit
interface {{ interface_name | default("GigabitEthernet0/0/1") }}
 traffic-policy {{ policy_name | default("VOICE_POLICY") }} inbound
quit
return

display traffic classifier {{ classifier_name | default("VOICE") }}
display traffic behavior {{ behavior_name | default("VOICE_BEHAVIOR") }}
display traffic policy {{ policy_name | default("VOICE_POLICY") }}""",
        "rollback": """system-view
interface {{ interface_name | default("GigabitEthernet0/0/1") }}
 undo traffic-policy {{ policy_name | default("VOICE_POLICY") }} inbound
quit
undo traffic policy {{ policy_name | default("VOICE_POLICY") }}
undo traffic behavior {{ behavior_name | default("VOICE_BEHAVIOR") }}
undo traffic classifier {{ classifier_name | default("VOICE") }}
return""",
        "reference": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100333649/df30cd60/mqc-configuration-commands",
    },
    {
        "id": "official-huawei-mlag-ce",
        "name": "M-LAG 双归接入基础配置（华为 CloudEngine）",
        "vendor": "Huawei",
        "category": "reliability",
        "platform": "huawei_vrp",
        "version": "V300R024C10/C11",
        "description": "CloudEngine 数据中心双机 M-LAG starter；DFS、peer-link、keepalive 和成员一致性必须按版本/拓扑复核。",
        "content": """system-view
dfs-group {{ dfs_group | default(1) }}
 source ip address {{ source_ip | default("192.0.2.11") }}
 priority {{ dfs_priority | default(100) }}
quit
interface Eth-Trunk{{ peer_link_id | default(1) }}
 mode lacp-static
 peer-link {{ peer_link_id | default(1) }}
quit
interface Eth-Trunk{{ mlag_trunk_id | default(10) }}
 mode lacp-static
 dfs-group {{ dfs_group | default(1) }} m-lag {{ mlag_id | default(10) }}
quit
return

display dfs-group {{ dfs_group | default(1) }}
display eth-trunk {{ peer_link_id | default(1) }}""",
        "rollback": """system-view
interface Eth-Trunk{{ mlag_trunk_id | default(10) }}
 undo dfs-group {{ dfs_group | default(1) }} m-lag {{ mlag_id | default(10) }}
quit
interface Eth-Trunk{{ peer_link_id | default(1) }}
 undo peer-link
quit
undo dfs-group {{ dfs_group | default(1) }}
return""",
        "reference": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100458988/ce1602ef/configuration-examples-for-m-lag",
    },
)


_EXTRA_TEMPLATES = (
    {
        "id": "official-h3c-vrrp-basic",
        "name": "VRRP 网关冗余（H3C Comware 7）",
        "vendor": "H3C", "category": "reliability", "platform": "h3c_comware", "version": "Comware 7",
        "description": "在 VLAN 接口上配置 VRRP 虚拟网关、优先级和抢占延时。",
        "content": """system-view
interface Vlan-interface{{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default("192.0.2.2") }} {{ netmask | default("255.255.255.0") }}
 vrrp vrid {{ vrrp_id | default(10) }} virtual-ip {{ virtual_ip | default("192.0.2.1") }}
 vrrp vrid {{ vrrp_id | default(10) }} priority {{ priority | default(120) }}
 vrrp vrid {{ vrrp_id | default(10) }} preempt-mode delay {{ preempt_delay | default(30) }}
quit
return

display vrrp verbose""",
        "rollback": """system-view
interface Vlan-interface{{ vlan_id | default(10) }}
 undo vrrp vrid {{ vrrp_id | default(10) }} virtual-ip {{ virtual_ip | default("192.0.2.1") }}
 undo vrrp vrid {{ vrrp_id | default(10) }} priority
 undo vrrp vrid {{ vrrp_id | default(10) }} preempt-mode
quit
return""",
        "reference": "https://www.h3c.com/en/d_202507/2576036_294551_0.htm",
    },
    {
        "id": "official-h3c-qos-policy",
        "name": "QoS 流量策略（H3C Comware 7）",
        "vendor": "H3C", "category": "management", "platform": "h3c_comware", "version": "Comware 7",
        "description": "使用 QoS classifier/behavior/policy 匹配 EF 流量并在接口入方向应用。",
        "content": """system-view
traffic classifier {{ classifier_name | default("VOICE") }} operator and
 if-match dscp ef
quit
traffic behavior {{ behavior_name | default("VOICE_BEHAVIOR") }}
 remark dscp ef
quit
qos policy {{ policy_name | default("VOICE_POLICY") }}
 classifier {{ classifier_name | default("VOICE") }} behavior {{ behavior_name | default("VOICE_BEHAVIOR") }}
quit
interface {{ interface_name | default("GigabitEthernet1/0/1") }}
 qos apply policy {{ policy_name | default("VOICE_POLICY") }} inbound
quit
return

display qos policy user-defined""",
        "rollback": """system-view
interface {{ interface_name | default("GigabitEthernet1/0/1") }}
 undo qos apply policy {{ policy_name | default("VOICE_POLICY") }} inbound
quit
undo qos policy {{ policy_name | default("VOICE_POLICY") }}
undo traffic behavior {{ behavior_name | default("VOICE_BEHAVIOR") }}
undo traffic classifier {{ classifier_name | default("VOICE") }}
return""",
        "reference": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Reference_Guides/Command_References/H3C_CR-14616/09/202310/1955674_294551_0.htm",
    },
    {
        "id": "official-h3c-aaa-local",
        "name": "AAA 本地管理员（H3C Comware 7）",
        "vendor": "H3C", "category": "security", "platform": "h3c_comware", "version": "Comware 7",
        "description": "使用本地 AAA 用户库保护 SSH/VTY 管理登录；密码必须从密钥库注入。",
        "content": """system-view
domain system
 authentication default local
 authorization default local
 accounting default local
quit
local-user {{ username | default("netops") }} class manage
 password hash {{ password_from_vault | default("<from-secret-vault:password>") }}
 service-type ssh
 authorization-attribute user-role network-admin
quit
line vty 0 4
 authentication-mode scheme
 protocol inbound ssh
quit
return

display local-user""",
        "rollback": """system-view
undo local-user {{ username | default("netops") }}
line vty 0 4
 undo authentication-mode
 undo protocol inbound
quit
return""",
        "reference": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_S6520X_HI_MS4600_CGs_R68xx-27445/00/202602/2752054_294551_0.htm",
    },
    {
        "id": "official-h3c-smlag-basic",
        "name": "S-MLAG 双归接入基础配置（H3C Comware 7）",
        "vendor": "H3C", "category": "reliability", "platform": "h3c_comware", "version": "Comware 7",
        "description": "H3C S-MLAG 的系统 MAC、系统优先级、系统编号和成员聚合基础配置。",
        "content": """system-view
lacp system-mac {{ system_mac | default("0000-0000-0010") }}
lacp system-priority {{ system_priority | default(32768) }}
lacp system-number {{ system_number | default(1) }}
interface Bridge-Aggregation{{ aggregation_id | default(1) }}
 link-aggregation mode dynamic
 port s-mlag group {{ s_mlag_id | default(1) }}
quit
return

display link-aggregation verbose""",
        "rollback": """system-view
interface Bridge-Aggregation{{ aggregation_id | default(1) }}
 undo port s-mlag group {{ s_mlag_id | default(1) }}
 undo link-aggregation mode
quit
undo lacp system-number
undo lacp system-priority
undo lacp system-mac
return""",
        "reference": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Switches/00-Public/Configure___Deploy/Configuration_Guides/S6800%5BS6860%5D%5BS6861%5D%28R27xx%29S6820%28R630x%29_CG/03/202106/1416646_294551_0.htm",
    },
    {
        "id": "official-cisco-vrrpv3-basic",
        "name": "VRRPv3 网关冗余（Cisco IOS XE）",
        "vendor": "Cisco", "category": "reliability", "platform": "cisco_iosxe", "version": "IOS XE 17.x",
        "description": "在 SVI 上配置 VRRPv3 IPv4 虚拟地址、优先级和抢占延时。",
        "content": """enable
configure terminal
fhrp version vrrp v3
interface Vlan{{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default("192.0.2.2") }} {{ netmask | default("255.255.255.0") }}
 vrrp {{ vrrp_id | default(10) }} address-family ipv4
  address {{ virtual_ip | default("192.0.2.1") }} primary
  priority {{ priority | default(120) }}
  preempt delay minimum {{ preempt_delay | default(30) }}
 exit-vrrp
exit
end

show vrrp detail""",
        "rollback": """configure terminal
interface Vlan{{ vlan_id | default(10) }}
 no vrrp {{ vrrp_id | default(10) }} address-family ipv4
exit
no fhrp version vrrp v3
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-15/configuration_guide/ip/b_1715_ip_9300_cg/vrrpv3_protocol___support.html",
    },
    {
        "id": "official-cisco-qos-mqc",
        "name": "MQC QoS 基础策略（Cisco IOS XE）",
        "vendor": "Cisco", "category": "management", "platform": "cisco_iosxe", "version": "IOS XE 17.x/26.x",
        "description": "使用 class-map/policy-map/service-policy 匹配 EF 流量并在接口入方向应用。",
        "content": """enable
configure terminal
class-map match-any {{ class_name | default("VOICE") }}
 match dscp ef
policy-map {{ policy_name | default("VOICE_POLICY") }}
 class {{ class_name | default("VOICE") }}
  priority level 1
interface {{ interface_name | default("GigabitEthernet1/0/1") }}
 service-policy input {{ policy_name | default("VOICE_POLICY") }}
end

show policy-map interface {{ interface_name | default("GigabitEthernet1/0/1") }}""",
        "rollback": """configure terminal
interface {{ interface_name | default("GigabitEthernet1/0/1") }}
 no service-policy input {{ policy_name | default("VOICE_POLICY") }}
exit
no policy-map {{ policy_name | default("VOICE_POLICY") }}
no class-map {{ class_name | default("VOICE") }}
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/26-x/configuration_guide/qos/b_26x_qos_9300_cg/configuring_qos.html",
    },
    {
        "id": "official-cisco-aaa-local",
        "name": "AAA 本地管理员（Cisco IOS XE）",
        "vendor": "Cisco", "category": "security", "platform": "cisco_iosxe", "version": "IOS XE 17.x/26.x",
        "description": "启用本地 AAA、创建特权用户并保护 VTY SSH；密码必须从密钥库注入。",
        "content": """enable
configure terminal
aaa new-model
aaa authentication login default local
aaa authorization exec default local
username {{ username | default("netops") }} privilege 15 secret {{ password_from_vault | default("<from-secret-vault:password>") }}
line vty 0 4
 login authentication default
 transport input ssh
end

show aaa local user lockout""",
        "rollback": """configure terminal
line vty 0 4
 no login authentication default
 no transport input ssh
exit
no username {{ username | default("netops") }}
no aaa authorization exec default local
no aaa authentication login default local
no aaa new-model
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/26-x/configuration_guide/sec/b_26x_sec_9300_cg/configuring_local_authentication_and_authorization.html",
    },
    {
        "id": "official-cisco-nexus-vpc-basic",
        "name": "vPC 双机互联基础配置（Cisco Nexus NX-OS）",
        "vendor": "Cisco", "category": "reliability", "platform": "cisco_nxos", "version": "NX-OS 10.6.x",
        "description": "Nexus 9000 vPC domain、peer-keepalive、peer-link 和成员端口基础骨架。",
        "content": """configure terminal
feature lacp
feature vpc
vpc domain {{ vpc_domain | default(10) }}
 peer-keepalive destination {{ keepalive_peer | default("192.0.2.12") }} source {{ keepalive_source | default("192.0.2.11") }}
interface port-channel{{ peer_link_id | default(1) }}
 vpc peer-link
interface Ethernet{{ peer_link_interface | default("1/1") }}
 channel-group {{ peer_link_id | default(1) }} mode active
interface port-channel{{ vpc_port_channel | default(10) }}
 vpc {{ vpc_id | default(10) }}
end

show vpc brief
show vpc peer-keepalive""",
        "rollback": """configure terminal
interface port-channel{{ vpc_port_channel | default(10) }}
 no vpc {{ vpc_id | default(10) }}
exit
no vpc domain {{ vpc_domain | default(10) }}
no feature vpc
no feature lacp
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/106x/configuration/interfaces/cisco-nexus-9000-series-nx-os-interfaces-configuration-guide-release-106x/m_configuring_vpcs_9x.html",
    },
)


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_columns(cursor, use_pg)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for item in (*_TEMPLATES, *_EXTRA_TEMPLATES):
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
