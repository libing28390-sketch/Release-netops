"""Complete VLAN/SVI templates and keep mask input vendor-safe.

The common SVI/VLANIF commands use a dotted-decimal mask on Cisco IOS XE,
Huawei VRP, and H3C Comware.  Operators may still enter a CIDR length in the
template center; the service normalizes it before rendering.  This migration
only corrects known seeded/custom template content and is safe to re-run.
"""

from __future__ import annotations


VERSION = 57
NAME = "config_template_syntax_completion"


def _replace_template(cursor, template_id: str, old_source: str, new_source: str) -> None:
    """Replace only the known source so user-edited templates are preserved."""
    cursor.execute(
        """
        UPDATE templates
        SET content = ?, updated_at = COALESCE(NULLIF(updated_at, ''), '')
        WHERE id = ? AND content = ?
        """,
        (new_source, template_id, old_source),
    )
    # A version may have been created by an earlier deployment.  Keep it in
    # sync only when it still contains the exact seeded source; never overwrite
    # a user-edited version.
    cursor.execute(
        """
        UPDATE config_template_versions
        SET source = ?, variable_schema_json = '[]', example_values_json = '{}'
        WHERE template_id = ? AND source = ?
        """,
        (new_source, template_id, old_source),
    )


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg  # SQL uses the PostgreSQL/SQLite common parameterized subset.

    cisco_old = """vlan {{ vlan_id | default(10) }}
 name {{ vlan_name | default("USERS") }}
interface Vlan{{ vlan_id | default(10) }}
 description {{ interface_description | default("USER_GATEWAY") }}
 ip address {{ gateway_ip | default("192.0.2.1") }} {{ netmask | default("255.255.255.0") }}
 no shutdown"""
    cisco_new = """vlan {{ vlan_id | default(10) }}
 name {{ vlan_name | default("USERS") }}
interface Vlan{{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default("192.0.2.1") }} {{ netmask | default("255.255.255.0") }}
 description {{ interface_description | default("USER_GATEWAY") }}
 no shutdown"""
    _replace_template(cursor, "official-cisco-svi", cisco_old, cisco_new)

    for template_id, old_source, new_source in (
        (
            "official-huawei-vlanif",
            """vlan {{ vlan_id | default(10) }}
quit
interface Vlanif{{ vlan_id | default(10) }}
 description {{ interface_description | default("USER_GATEWAY") }}
 ip address {{ gateway_ip | default("192.0.2.1") }} {{ netmask | default("255.255.255.0") }}""",
            """vlan {{ vlan_id | default(10) }}
 description {{ vlan_name | default("USERS") }}
quit
interface Vlanif{{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default("192.0.2.1") }} {{ netmask | default("255.255.255.0") }}
 description {{ interface_description | default("USER_GATEWAY") }}""",
        ),
        (
            "official-h3c-vlan-interface",
            """vlan {{ vlan_id | default(10) }}
quit
interface Vlan-interface{{ vlan_id | default(10) }}
 description {{ interface_description | default("USER_GATEWAY") }}
 ip address {{ gateway_ip | default("192.0.2.1") }} {{ netmask | default("255.255.255.0") }}""",
            """vlan {{ vlan_id | default(10) }}
 description {{ vlan_name | default("USERS") }}
quit
interface Vlan-interface{{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default("192.0.2.1") }} {{ netmask | default("255.255.255.0") }}
 description {{ interface_description | default("USER_GATEWAY") }}""",
        ),
    ):
        _replace_template(cursor, template_id, old_source, new_source)

    # The original custom H3C/Huawei VLAN templates exposed no description
    # field: they rendered a hard-coded string.  Replace only that exact
    # source, so arbitrary customer templates are not changed.
    for vendor in ("H3C", "Huawei"):
        old_source = """vlan {{ vlan_id | default(10) }}
 description Created_by_NetOps"""
        new_source = """vlan {{ vlan_id | default(10) }}
 description {{ vlan_name | default(\"USERS\") }}"""
        row = cursor.execute(
            """
            SELECT id FROM templates
            WHERE name = ? AND vendor = ? AND content = ?
            LIMIT 1
            """,
            ("VLAN Creation", vendor, old_source),
        ).fetchone()
        if row:
            _replace_template(cursor, str(row[0]), old_source, new_source)
