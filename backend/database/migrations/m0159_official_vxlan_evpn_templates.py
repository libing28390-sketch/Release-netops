"""Add reviewed VXLAN/EVPN starter templates for data-center switches."""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 159
NAME = "official_vxlan_evpn_templates"


def _columns(cursor, use_pg: bool) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'templates'"
    )
    return {str(row[0]) for row in cursor.fetchall()}



def _ensure_columns(cursor, use_pg: bool) -> None:
    definitions = {
        "description": "TEXT DEFAULT ''", "platform_family": "TEXT DEFAULT ''",
        "software_version": "TEXT DEFAULT ''", "official_reference": "TEXT DEFAULT ''",
        "validation_status": "TEXT DEFAULT 'draft'", "source_type": "TEXT DEFAULT 'custom'",
        "risk_level": "TEXT DEFAULT 'low'", "status": "TEXT DEFAULT 'draft'",
        "current_version": "TEXT DEFAULT '1.0'", "is_official": "INTEGER DEFAULT 0",
        "created_by": "TEXT DEFAULT ''", "created_at": "TEXT DEFAULT ''", "updated_at": "TEXT DEFAULT ''",
    }
    existing = _columns(cursor, use_pg)
    for column, definition in definitions.items():
        if column not in existing:
            cursor.execute(f"ALTER TABLE templates ADD COLUMN {column} {definition}")


_TEMPLATES = (
    {
        "id": "official-huawei-ce6800-vxlan-evpn-basic",
        "name": "华为 CloudEngine 6800 VXLAN BGP EVPN 基础配置",
        "vendor": "Huawei",
        "platform": "huawei_vrp",
        "version": "V300R024C10/C11",
        "description": "数据中心 CE6800 VXLAN/EVPN 骨架；VTEP、BD/VNI 与 BGP EVPN 参数必须按设备版本和拓扑核对。",
        "content": """system-view
evpn-overlay enable
bridge-domain {{ bridge_domain | default(10) }}
 vxlan vni {{ vni | default(10010) }}
quit
interface Nve1
 source {{ vtep_source | default(\"LoopBack1\") }}
 vni {{ vni | default(10010) }} head-end peer-list {{ remote_vtep | default(\"192.0.2.20\") }}
quit
return

display vxlan tunnel
display bgp evpn peer""",
        "rollback": """system-view
interface Nve1
 undo vni {{ vni | default(10010) }}
quit
undo bridge-domain {{ bridge_domain | default(10) }}
return""",
        "reference": "https://support.huawei.com/enterprise/en/doc/EDOC1100463796/5d103d4d/establishing-vxlan-tunnels-in-bgp-evpn-mode-distributed-vxlan-gateway",
    },
    {
        "id": "official-h3c-s6800-s9825-vxlan-evpn-basic",
        "name": "H3C S6800/S9825 Comware EVPN VXLAN 基础配置",
        "vendor": "H3C",
        "platform": "h3c_comware",
        "version": "Comware 7",
        "description": "数据中心 H3C S6800/S9825 EVPN VXLAN 骨架，覆盖 VSI、EVPN 实例与 BGP EVPN 发布。",
        "content": """system-view
vsi {{ vsi_name | default(\"VSI10\") }}
 vxlan {{ vni | default(10010) }}
 evpn encapsulation vxlan
  route-distinguisher auto
  vpn-target {{ route_target | default("65000:10010") }} both
quit
evpn instance {{ evpn_instance | default(\"EVPN10\") }}
 route-distinguisher auto
 vpn-target {{ route_target | default("65000:10010") }} both
quit

display vxlan tunnel
display bgp evpn peer""",
        "rollback": """system-view
undo vsi {{ vsi_name | default(\"VSI10\") }}
undo evpn instance {{ evpn_instance | default(\"EVPN10\") }}
return""",
        "reference": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_CG-18642/19/202404/2105879_294551_0.htm",
    },
    {
        "id": "official-cisco-nexus-vxlan-evpn-basic",
        "name": "Cisco Nexus 9000 NX-OS VXLAN BGP EVPN 基础配置",
        "vendor": "Cisco",
        "platform": "cisco_nxos",
        "version": "NX-OS 9.2/10.x",
        "description": "数据中心 Nexus 9000 VXLAN/EVPN starter，按官方 release guide 先启用 overlay，再配置 VLAN/VNI/VRF。",
        "content": """configure terminal
feature vn-segment
feature nv overlay
feature vn-segment-vlan-based
feature interface-vlan
nv overlay evpn
fabric forwarding anycast-gateway-mac {{ anycast_gateway_mac | default(\"0000.2222.3333\") }}
vlan {{ vlan_id | default(1001) }}
 vn-segment {{ vni | default(2001001) }}
evpn
 vni {{ vni | default(2001001) }} l2
  rd auto
  route-target both auto
vrf context {{ vrf_name | default(\"vxlan-900001\") }}
 vni {{ l3_vni | default(900001) }}
 rd auto
 address-family ipv4 unicast
  route-target both auto
  route-target both auto evpn
end

show nve peers
show bgp l2vpn evpn summary""",
        "rollback": """configure terminal
no nv overlay evpn
no feature vn-segment-vlan-based
no feature nv overlay
no feature vn-segment
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/92x/vxlan-92x/configuration/guide/b-cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-92x/b_Cisco_Nexus_9000_Series_NX-OS_VXLAN_Configuration_Guide_9x_chapter_0100.html",
    },
)


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_columns(cursor, use_pg)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for item in _TEMPLATES:
        existing = cursor.execute("SELECT id FROM templates WHERE id = ?", (item["id"],)).fetchone()
        values = (
            item["name"], "cli", "overlay", item["vendor"], item["content"], item["rollback"],
            item["description"], item["platform"], item["version"], item["reference"],
            "official_reference_reviewed", "official", "medium", "published", "1.0", 1,
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
