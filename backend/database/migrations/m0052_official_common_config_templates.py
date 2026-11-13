"""Add metadata and reviewed common templates for major network vendors."""

from __future__ import annotations


VERSION = 52
NAME = "official_common_config_templates"


def _column_exists(cursor, column: str, use_pg: bool) -> bool:
    return cursor.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'templates'
          AND column_name = ?
        """,
        (column,),
    ).fetchone() is not None



def upgrade(cursor, use_pg: bool) -> None:
    for column, definition in (
        ("description", "TEXT DEFAULT ''"),
        ("platform_family", "TEXT DEFAULT ''"),
        ("software_version", "TEXT DEFAULT ''"),
        ("official_reference", "TEXT DEFAULT ''"),
        ("validation_status", "TEXT DEFAULT 'draft'"),
    ):
        if not _column_exists(cursor, column, use_pg):
            cursor.execute(f"ALTER TABLE templates ADD COLUMN {column} {definition}")

    templates = [
        (
            "official-cisco-access-port",
            "接入口配置（Cisco IOS XE）", "switching", "Cisco", "cisco_iosxe", "IOS XE 17.x",
            "创建 VLAN 并将物理端口配置为静态 Access 端口。",
            """vlan {{ vlan_id | default(10) }}
 name {{ vlan_name | default("USERS") }}
interface {{ interface_name | default("GigabitEthernet1/0/1") }}
 description {{ interface_description | default("ACCESS_PORT") }}
 switchport mode access
 switchport access vlan {{ vlan_id | default(10) }}
 spanning-tree portfast""",
            """interface {{ interface_name | default("GigabitEthernet1/0/1") }}
 no spanning-tree portfast
 no switchport access vlan
 no description
no vlan {{ vlan_id | default(10) }}""",
            "https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/infra/interface-characteristics/interface-characteristics-configuration-guide.html",
        ),
        (
            "official-cisco-trunk-port",
            "Trunk 端口配置（Cisco IOS XE）", "switching", "Cisco", "cisco_iosxe", "IOS XE 17.x",
            "配置 802.1Q Trunk、允许 VLAN 与 Native VLAN。",
            """interface {{ interface_name | default("GigabitEthernet1/0/48") }}
 description {{ interface_description | default("UPLINK_TRUNK") }}
 switchport mode trunk
 switchport trunk native vlan {{ native_vlan | default(999) }}
 switchport trunk allowed vlan {{ allowed_vlans | default("10,20,30,999") }}""",
            """interface {{ interface_name | default("GigabitEthernet1/0/48") }}
 no switchport trunk allowed vlan
 no switchport trunk native vlan
 switchport mode access
 no description""",
            "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/configuration_guide/vlan/b_173_vlan_9400_cg.pdf",
        ),
        (
            "official-cisco-svi",
            "VLAN 三层网关 SVI（Cisco IOS XE）", "routing", "Cisco", "cisco_iosxe", "IOS XE 17.x",
            "创建 VLAN Interface 并配置 IPv4 网关。",
            """vlan {{ vlan_id | default(10) }}
 name {{ vlan_name | default("USERS") }}
interface Vlan{{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default("192.0.2.1") }} {{ netmask | default("255.255.255.0") }}
 description {{ interface_description | default("USER_GATEWAY") }}
 no shutdown""",
            """interface Vlan{{ vlan_id | default(10) }}
 shutdown
 no ip address
 no description
no interface Vlan{{ vlan_id | default(10) }}""",
            "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/configuration_guide/vlan/b_173_vlan_9400_cg.pdf",
        ),
        (
            "official-cisco-lacp-port-channel",
            "LACP Port-Channel（Cisco IOS XE）", "switching", "Cisco", "cisco_iosxe", "IOS XE 17.x",
            "将两个同速率接口加入 LACP EtherChannel，并在逻辑口配置 Trunk。",
            """interface range {{ member_interfaces | default("GigabitEthernet1/0/47-48") }}
 channel-group {{ channel_id | default(10) }} mode active
interface Port-channel{{ channel_id | default(10) }}
 description {{ interface_description | default("LACP_UPLINK") }}
 switchport mode trunk
 switchport trunk allowed vlan {{ allowed_vlans | default("10,20,30") }}""",
            """interface range {{ member_interfaces | default("GigabitEthernet1/0/47-48") }}
 no channel-group {{ channel_id | default(10) }}
no interface Port-channel{{ channel_id | default(10) }}""",
            "https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/lyr2-fwd/etherchannel/etherchannel-configuration-guide/etherchannels.html",
        ),
        (
            "official-cisco-loopback",
            "Loopback 管理接口（Cisco IOS XE）", "routing", "Cisco", "cisco_iosxe", "IOS XE 17.x",
            "创建 Loopback 并配置 /32 管理地址。",
            """interface Loopback{{ loopback_id | default(0) }}
 description {{ interface_description | default("MANAGEMENT") }}
 ip address {{ loopback_ip | default("192.0.2.10") }} 255.255.255.255""",
            "no interface Loopback{{ loopback_id | default(0) }}",
            "https://www.cisco.com/c/en/us/td/docs/routers/ios-xe/system-management/system-management/m_cf-cli-basics.html",
        ),
        (
            "official-cisco-snmpv3",
            "SNMPv3 用户与 Trap（Cisco IOS XE）", "management", "Cisco", "cisco_iosxe", "IOS XE 17.x",
            "使用 authPriv 安全级别创建 SNMPv3 组、用户与 Trap 目标；密钥必须来自密钥库变量。",
            """snmp-server group {{ snmp_group | default("NMS-GROUP") }} v3 priv
snmp-server user {{ snmp_user | default("nms-user") }} {{ snmp_group | default("NMS-GROUP") }} v3 auth sha {{ snmp_auth_key }} priv aes 128 {{ snmp_priv_key }}
snmp-server host {{ nms_ip | default("192.0.2.50") }} version 3 priv {{ snmp_user | default("nms-user") }}
snmp-server enable traps""",
            """no snmp-server host {{ nms_ip | default("192.0.2.50") }} version 3 priv {{ snmp_user | default("nms-user") }}
no snmp-server user {{ snmp_user | default("nms-user") }} {{ snmp_group | default("NMS-GROUP") }} v3
no snmp-server group {{ snmp_group | default("NMS-GROUP") }} v3 priv""",
            "https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/mgmt/management-configuration-guide/snmp-configuration.html",
        ),
        (
            "official-huawei-access-port",
            "接入口配置（华为 VRP）", "switching", "Huawei", "huawei_vrp", "V200R023 / V300R024",
            "创建 VLAN 并配置 Access 端口。",
            """vlan {{ vlan_id | default(10) }}
 description {{ vlan_name | default("USERS") }}
quit
interface {{ interface_name | default("GigabitEthernet0/0/1") }}
 description {{ interface_description | default("ACCESS_PORT") }}
 port link-type access
 port default vlan {{ vlan_id | default(10) }}""",
            """interface {{ interface_name | default("GigabitEthernet0/0/1") }}
 undo port default vlan
 undo description
quit
undo vlan {{ vlan_id | default(10) }}""",
            "https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans",
        ),
        (
            "official-huawei-trunk-port",
            "Trunk 端口配置（华为 VRP）", "switching", "Huawei", "huawei_vrp", "V200R023 / V300R024",
            "配置 Trunk、允许 VLAN 与 PVID。",
            """interface {{ interface_name | default("GigabitEthernet0/0/48") }}
 description {{ interface_description | default("UPLINK_TRUNK") }}
 port link-type trunk
 port trunk pvid vlan {{ native_vlan | default(999) }}
 port trunk allow-pass vlan {{ allowed_vlans | default("10 20 30 999") }}""",
            """interface {{ interface_name | default("GigabitEthernet0/0/48") }}
 undo port trunk allow-pass vlan {{ allowed_vlans | default("10 20 30 999") }}
 undo port trunk pvid
 port link-type access
 undo description""",
            "https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans",
        ),
        (
            "official-huawei-vlanif",
            "VLANIF 三层网关（华为 VRP）", "routing", "Huawei", "huawei_vrp", "V200R023 / V300R024",
            "创建 VLANIF 并配置 IPv4 网关。",
            """vlan {{ vlan_id | default(10) }}
 description {{ vlan_name | default("USERS") }}
quit
interface Vlanif{{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default("192.0.2.1") }} {{ netmask | default("255.255.255.0") }}
 description {{ interface_description | default("USER_GATEWAY") }}""",
            """undo interface Vlanif{{ vlan_id | default(10) }}
undo vlan {{ vlan_id | default(10) }}""",
            "https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans",
        ),
        (
            "official-huawei-eth-trunk",
            "LACP Eth-Trunk（华为 VRP）", "switching", "Huawei", "huawei_vrp", "V200R023",
            "创建静态 LACP Eth-Trunk 并加入两个成员端口。",
            """interface Eth-Trunk{{ trunk_id | default(10) }}
 mode lacp-static
 description {{ interface_description | default("LACP_UPLINK") }}
quit
interface {{ member_interface_1 | default("GigabitEthernet0/0/47") }}
 eth-trunk {{ trunk_id | default(10) }}
quit
interface {{ member_interface_2 | default("GigabitEthernet0/0/48") }}
 eth-trunk {{ trunk_id | default(10) }}""",
            """interface {{ member_interface_1 | default("GigabitEthernet0/0/47") }}
 undo eth-trunk
quit
interface {{ member_interface_2 | default("GigabitEthernet0/0/48") }}
 undo eth-trunk
quit
undo interface Eth-Trunk{{ trunk_id | default(10) }}""",
            "https://info.support.huawei.com/enterprise/en/doc/EDOC1100365019/493f7e15/example-for-configuring-stack-eth-trunks",
        ),
        (
            "official-huawei-loopback",
            "LoopBack 管理接口（华为 VRP）", "routing", "Huawei", "huawei_vrp", "V200R023 / V300R024",
            "创建 LoopBack 并配置 /32 管理地址。",
            """interface LoopBack{{ loopback_id | default(0) }}
 description {{ interface_description | default("MANAGEMENT") }}
 ip address {{ loopback_ip | default("192.0.2.10") }} 255.255.255.255""",
            "undo interface LoopBack{{ loopback_id | default(0) }}",
            "https://info.support.huawei.com/enterprise/en/doc/EDOC1100411157/5fdfc46d/overview-of-clis",
        ),
        (
            "official-huawei-vrrp",
            "VLANIF VRRP 网关冗余（华为 VRP）", "reliability", "Huawei", "huawei_vrp", "V200R023",
            "在既有 VLANIF 上配置 VRRP 虚拟网关、优先级和抢占延迟。",
            """interface Vlanif{{ vlan_id | default(10) }}
 vrrp vrid {{ vrid | default(10) }} virtual-ip {{ virtual_ip | default("192.0.2.254") }}
 vrrp vrid {{ vrid | default(10) }} priority {{ priority | default(120) }}
 vrrp vrid {{ vrid | default(10) }} preempt-mode timer delay {{ preempt_delay | default(30) }}""",
            """interface Vlanif{{ vlan_id | default(10) }}
 undo vrrp vrid {{ vrid | default(10) }}""",
            "https://info.support.huawei.com/enterprise/en/doc/EDOC1100333880/18db48ec/optional-configuring-vrrp-time-parameters",
        ),
        (
            "official-h3c-access-port",
            "接入口配置（H3C Comware）", "switching", "H3C", "h3c_comware", "Comware 7 R66xx/R67xx",
            "创建 VLAN 并配置 Access 端口。",
            """vlan {{ vlan_id | default(10) }}
 description {{ vlan_name | default("USERS") }}
quit
interface {{ interface_name | default("GigabitEthernet1/0/1") }}
 description {{ interface_description | default("ACCESS_PORT") }}
 port link-type access
 port access vlan {{ vlan_id | default(10) }}""",
            """interface {{ interface_name | default("GigabitEthernet1/0/1") }}
 undo port access vlan
 undo description
quit
undo vlan {{ vlan_id | default(10) }}""",
            "https://www.h3c.com/en/d_201905/1189999_294551_0.htm",
        ),
        (
            "official-h3c-trunk-port",
            "Trunk 端口配置（H3C Comware）", "switching", "H3C", "h3c_comware", "Comware 7 R66xx/R67xx",
            "配置 Trunk、允许 VLAN 与 PVID。",
            """interface {{ interface_name | default("GigabitEthernet1/0/48") }}
 description {{ interface_description | default("UPLINK_TRUNK") }}
 port link-type trunk
 port trunk pvid vlan {{ native_vlan | default(999) }}
 port trunk permit vlan {{ allowed_vlans | default("10 20 30 999") }}""",
            """interface {{ interface_name | default("GigabitEthernet1/0/48") }}
 undo port trunk permit vlan {{ allowed_vlans | default("10 20 30 999") }}
 undo port trunk pvid
 port link-type access
 undo description""",
            "https://www.h3c.com/en/d_201905/1189999_294551_0.htm",
        ),
        (
            "official-h3c-vlan-interface",
            "Vlan-interface 三层网关（H3C Comware）", "routing", "H3C", "h3c_comware", "Comware 7 R66xx/R67xx",
            "创建 VLAN 接口并配置 IPv4 网关。",
            """vlan {{ vlan_id | default(10) }}
 description {{ vlan_name | default("USERS") }}
quit
interface Vlan-interface{{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default("192.0.2.1") }} {{ netmask | default("255.255.255.0") }}
 description {{ interface_description | default("USER_GATEWAY") }}""",
            """undo interface Vlan-interface{{ vlan_id | default(10) }}
undo vlan {{ vlan_id | default(10) }}""",
            "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Reference_Guides/Command_References/H3C_S6805_S9850_CRs_Release_6715-18388/00/?CHID=1036877",
        ),
        (
            "official-h3c-lacp-bridge-aggregation",
            "动态 LACP Bridge-Aggregation（H3C Comware）", "switching", "H3C", "h3c_comware", "Comware 7 R66xx/R67xx",
            "创建动态聚合口并加入两个成员接口。",
            """interface Bridge-Aggregation{{ aggregation_id | default(10) }}
 link-aggregation mode dynamic
 description {{ interface_description | default("LACP_UPLINK") }}
quit
interface {{ member_interface_1 | default("GigabitEthernet1/0/47") }}
 port link-aggregation group {{ aggregation_id | default(10) }}
quit
interface {{ member_interface_2 | default("GigabitEthernet1/0/48") }}
 port link-aggregation group {{ aggregation_id | default(10) }}""",
            """interface {{ member_interface_1 | default("GigabitEthernet1/0/47") }}
 undo port link-aggregation group
quit
interface {{ member_interface_2 | default("GigabitEthernet1/0/48") }}
 undo port link-aggregation group
quit
undo interface Bridge-Aggregation{{ aggregation_id | default(10) }}""",
            "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_CG-26720/06/202506/2514322_294551_0.htm",
        ),
        (
            "official-h3c-loopback",
            "LoopBack 管理接口（H3C Comware）", "routing", "H3C", "h3c_comware", "Comware 7 R66xx/R67xx",
            "创建 LoopBack 并配置 /32 管理地址。",
            """interface LoopBack{{ loopback_id | default(0) }}
 description {{ interface_description | default("MANAGEMENT") }}
 ip address {{ loopback_ip | default("192.0.2.10") }} 255.255.255.255""",
            "undo interface LoopBack{{ loopback_id | default(0) }}",
            "https://www.h3c.com/en/d_202004/1283136_294551_0.htm",
        ),
        (
            "official-h3c-ntp-client",
            "NTP 客户端（H3C Comware）", "management", "H3C", "h3c_comware", "Comware 7",
            "配置 NTP 单播服务器与可选源接口。",
            """ntp-service enable
ntp-service unicast-server {{ ntp_server_ip | default("192.0.2.123") }} source {{ source_interface | default("LoopBack0") }}""",
            "undo ntp-service unicast-server {{ ntp_server_ip | default(\"192.0.2.123\") }}",
            "https://www.h3c.com/en/d_202405/2120007_294551_0.htm",
        ),
    ]

    for (
        template_id, name, category, vendor, platform_family, software_version,
        description, content, rollback, official_reference,
    ) in templates:
        existing = cursor.execute(
            "SELECT id FROM templates WHERE id = ? OR (name = ? AND vendor = ?) LIMIT 1",
            (template_id, name, vendor),
        ).fetchone()
        values = (
            name, "cli", category, vendor, content, rollback, description,
            platform_family, software_version, official_reference,
            "official_reference_reviewed",
        )
        if existing:
            cursor.execute(
                """
                UPDATE templates
                SET name = ?, type = ?, category = ?, vendor = ?, content = ?,
                    rollback = ?, description = ?, platform_family = ?,
                    software_version = ?, official_reference = ?,
                    validation_status = ?
                WHERE id = ?
                """,
                (*values, existing[0]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO templates
                (id, name, type, category, vendor, content, rollback, last_used,
                 description, platform_family, software_version,
                 official_reference, validation_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?)
                """,
                (template_id, *values),
            )
