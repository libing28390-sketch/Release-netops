"""Seed reviewed common templates for Ruijie, ZTE, DPtech, and Maipu.

The four vendors in the operator's adaptation workbook share several common
networking tasks, but their model/series names are not platform identifiers.
Templates therefore target the OS/CLI family and carry model-pattern
compatibility rows for pre-check and future device-aware selection.
"""

from __future__ import annotations

import json
import hashlib


VERSION = 58
NAME = "official_domestic_vendor_templates"


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _upsert_template(cursor, item: dict[str, str]) -> None:
    now = _now()
    existing = cursor.execute("SELECT id FROM templates WHERE id = ?", (item["id"],)).fetchone()
    values = (
        item["name"], "cli", item["category"], item["vendor"], item["content"],
        item["rollback"], now, item["description"], item["platform"],
        item["software_version"], item["reference"], "official_reference_reviewed",
    )
    if existing:
        cursor.execute(
            """
            UPDATE templates
            SET name = ?, type = ?, category = ?, vendor = ?, content = ?,
                rollback = ?, updated_at = ?, description = ?, platform_family = ?,
                software_version = ?, official_reference = ?,
                validation_status = ?, source_type = 'official', is_official = 1,
                status = 'published', current_version = '1.0'
            WHERE id = ?
            """,
            (*values, item["id"]),
        )
        return
    cursor.execute(
        """
        INSERT INTO templates
        (id, name, type, category, vendor, content, rollback, last_used,
         description, platform_family, software_version, official_reference,
         validation_status, source_type, is_official, status, current_version,
         created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, 'official', 1,
                'published', '1.0', 'system', ?, ?)
        """,
        (
            item["id"], item["name"], "cli", item["category"], item["vendor"],
            item["content"], item["rollback"], item["description"], item["platform"],
            item["software_version"], item["reference"], "official_reference_reviewed",
            now, now,
        ),
    )


def _upsert_compatibility(cursor, item: dict[str, object]) -> None:
    cursor.execute(
        """
        DELETE FROM config_template_compatibility
        WHERE template_id = ? AND vendor = ? AND platform = ? AND model_pattern = ?
        """,
        (item["template_id"], item["vendor"], item["platform"], item["model_pattern"]),
    )
    cursor.execute(
        """
        INSERT INTO config_template_compatibility
        (id, template_id, vendor, platform, model_pattern, min_version, max_version,
         required_capabilities_json, excluded_versions_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "compat-{}-{}".format(
                item["template_id"],
                hashlib.sha1(str(item["model_pattern"]).encode("utf-8")).hexdigest()[:10],
            ),
            item["template_id"], item["vendor"], item["platform"], item["model_pattern"],
            item.get("min_version", ""), item.get("max_version", ""),
            json.dumps(item.get("required_capabilities", []), ensure_ascii=False),
            json.dumps(item.get("excluded_versions", []), ensure_ascii=False),
        ),
    )


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    references = {
        "Ruijie": "https://community.ruijienetworks.com/forum.php?mod=viewthread&tid=9145",
        "ZTE": "https://www.zte.com.cn/content/dam/zte-site/res-www-zte-com-cn/trust_center/eucc/ZTE_IPN_Common_Criteria_Security_Evaluation_Certified_Configuration.pdf",
        "DPtech": "https://www.dptech.com/uploadfile/2024/0806/20240806041441420.pdf",
        "Maipu": "https://www.maipu.com/upfiles/tinymce/files/20260602/fa464387f51f47b49b37387f2cb25665.pdf",
    }
    templates = [
        {
            "id": "official-ruijie-vlan",
            "name": "Ruijie RGOS VLAN",
            "vendor": "Ruijie", "platform": "ruijie_rgos", "category": "switching",
            "software_version": "RGOS 11.x/12.x",
            "description": "Create an RGOS VLAN and assign its display name.",
            "content": """vlan {{ vlan_id | default(10) }}
 name {{ vlan_name | default(\"USERS\") }}
exit""",
            "rollback": """no vlan {{ vlan_id | default(10) }}""",
        },
        {
            "id": "official-ruijie-access-port",
            "name": "Ruijie RGOS access port",
            "vendor": "Ruijie", "platform": "ruijie_rgos", "category": "switching",
            "software_version": "RGOS 11.x/12.x",
            "description": "Configure an RGOS access port for a VLAN.",
            "content": """interface {{ interface_name | default(\"GigabitEthernet 0/1\") }}
 description {{ interface_description | default(\"ACCESS_PORT\") }}
 switchport mode access
 switchport access vlan {{ vlan_id | default(10) }}
exit""",
            "rollback": """interface {{ interface_name | default(\"GigabitEthernet 0/1\") }}
 no switchport access vlan
 no description
exit""",
        },
        {
            "id": "official-ruijie-svi-ospf",
            "name": "Ruijie RGOS SVI and OSPF",
            "vendor": "Ruijie", "platform": "ruijie_rgos", "category": "routing",
            "software_version": "RGOS 11.x/12.x",
            "description": "Configure a VLAN interface and advertise it in OSPF.",
            "content": """vlan {{ vlan_id | default(10) }}
exit
interface VLAN {{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default(\"192.0.2.1\") }} {{ netmask | default(\"255.255.255.0\") }}
 description {{ interface_description | default(\"USER_GATEWAY\") }}
exit
router ospf {{ process_id | default(1) }}
 network {{ network | default(\"192.0.2.0\") }} {{ wildcard | default(\"0.0.0.255\") }} area {{ area | default(0) }}
exit""",
            "rollback": """no router ospf {{ process_id | default(1) }}
interface VLAN {{ vlan_id | default(10) }}
 no ip address
 no description
exit""",
        },
        {
            "id": "official-zte-zxros-vlan-interface",
            "name": "ZTE ZXROS VLAN interface",
            "vendor": "ZTE", "platform": "zte_zxros", "category": "routing",
            "software_version": "ZXR10 5900/5960/M6000 V5/V6",
            "description": "Configure a ZXROS VLAN interface gateway; verify interface spelling on the target series.",
            "content": """vlan {{ vlan_id | default(10) }}
 name {{ vlan_name | default(\"USERS\") }}
exit
interface vlan {{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default(\"192.0.2.1\") }} {{ netmask | default(\"255.255.255.0\") }}
 description {{ interface_description | default(\"USER_GATEWAY\") }}
exit""",
            "rollback": """interface vlan {{ vlan_id | default(10) }}
 no ip address
 no description
exit
no vlan {{ vlan_id | default(10) }}""",
        },
        {
            "id": "official-zte-zxros-access-port",
            "name": "ZTE ZXROS access port",
            "vendor": "ZTE", "platform": "zte_zxros", "category": "switching",
            "software_version": "ZXR10 5900/5960/9900 V5/V6",
            "description": "Configure a ZXROS access port; validate the physical interface family on the target line card.",
            "content": """interface {{ interface_name | default(\"gei-0/1/1/1\") }}
 description {{ interface_description | default(\"ACCESS_PORT\") }}
 switchport mode access
 switchport access vlan {{ vlan_id | default(10) }}
exit""",
            "rollback": """interface {{ interface_name | default(\"gei-0/1/1/1\") }}
 no switchport access vlan
 no description
exit""",
        },
        {
            "id": "official-dptech-conplat-vlan-interface",
            "name": "DPtech ConPlat VLAN interface",
            "vendor": "DPtech", "platform": "dptech_conplat", "category": "routing",
            "software_version": "ConPlat LSW/X series",
            "description": "Configure a ConPlat VLAN interface and IPv4 gateway.",
            "content": """vlan {{ vlan_id | default(10) }}
 name {{ vlan_name | default(\"USERS\") }}
exit
interface vlan {{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default(\"192.0.2.1\") }} {{ netmask | default(\"255.255.255.0\") }}
 description {{ interface_description | default(\"USER_GATEWAY\") }}
exit""",
            "rollback": """interface vlan {{ vlan_id | default(10) }}
 no ip address
 no description
exit
no vlan {{ vlan_id | default(10) }}""",
        },
        {
            "id": "official-dptech-conplat-access-port",
            "name": "DPtech ConPlat access port",
            "vendor": "DPtech", "platform": "dptech_conplat", "category": "switching",
            "software_version": "ConPlat LSW/X series",
            "description": "Configure a ConPlat access interface for a VLAN.",
            "content": """interface {{ interface_name | default(\"ge0/0\") }}
 description {{ interface_description | default(\"ACCESS_PORT\") }}
 switchport mode access
 switchport access vlan {{ vlan_id | default(10) }}
exit""",
            "rollback": """interface {{ interface_name | default(\"ge0/0\") }}
 no switchport access vlan
 no description
exit""",
        },
        {
            "id": "official-dptech-firewall-vlan-interface",
            "name": "DPtech ConPlat firewall VLAN interface",
            "vendor": "DPtech", "platform": "dptech_conplat_fw", "category": "security",
            "software_version": "ConPlat FW1000/FW series",
            "description": "Configure the network-side VLAN interface of a DPtech firewall.",
            "content": """vlan {{ vlan_id | default(10) }}
 name {{ vlan_name | default(\"USERS\") }}
exit
interface vlan {{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default(\"192.0.2.1\") }} {{ netmask | default(\"255.255.255.0\") }}
 description {{ interface_description | default(\"SECURITY_ZONE_INTERFACE\") }}
exit""",
            "rollback": """interface vlan {{ vlan_id | default(10) }}
 no ip address
 no description
exit""",
        },
        {
            "id": "official-maipu-mypower-vlan-interface",
            "name": "Maipu MyPower VLAN interface",
            "vendor": "Maipu", "platform": "maipu", "category": "routing",
            "software_version": "MyPowerOS S/NSS series",
            "description": "Configure a MyPower VLAN interface and IPv4 gateway.",
            "content": """vlan {{ vlan_id | default(10) }}
 name {{ vlan_name | default(\"USERS\") }}
exit
interface vlan {{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default(\"192.0.2.1\") }} {{ netmask | default(\"255.255.255.0\") }}
 description {{ interface_description | default(\"USER_GATEWAY\") }}
exit""",
            "rollback": """interface vlan {{ vlan_id | default(10) }}
 no ip address
 no description
exit
no vlan {{ vlan_id | default(10) }}""",
        },
        {
            "id": "official-maipu-mypower-access-port",
            "name": "Maipu MyPower access port",
            "vendor": "Maipu", "platform": "maipu", "category": "switching",
            "software_version": "MyPowerOS S/NSS series",
            "description": "Configure a MyPower access interface for a VLAN.",
            "content": """interface {{ interface_name | default(\"GigabitEthernet0/1\") }}
 description {{ interface_description | default(\"ACCESS_PORT\") }}
 switchport mode access
 switchport access vlan {{ vlan_id | default(10) }}
exit""",
            "rollback": """interface {{ interface_name | default(\"GigabitEthernet0/1\") }}
 no switchport access vlan
 no description
exit""",
        },
    ]

    profiles = {
        "Ruijie": [r"^(?:RG-(?:S|CS|NBS)|RG-R|RSR|RG-EG)"],
        "ZTE": [r"^(?:ZXR10\s*)?(?:5900|5960|9900|M6000)|^ZXCTN\s*6700"],
        "DPtech": [r"^(?:LSW|X|MSR|XR|FW|FW1000|FW2000|UAG)"],
        "Maipu": [r"^(?:S|NSS|MP|MSG|MPSec|IFW)"],
    }
    for item in templates:
        item["reference"] = references[item["vendor"]]
        _upsert_template(cursor, item)
        _upsert_compatibility(cursor, {
            "template_id": item["id"],
            "vendor": item["vendor"],
            "platform": item["platform"],
            "model_pattern": profiles[item["vendor"]][0],
            "required_capabilities": ["cli", "ipv4", "vlan"],
        })
