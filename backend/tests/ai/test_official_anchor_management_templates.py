from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0204_official_ruijie_gold_templates import upgrade as upgrade_ruijie
from database.migrations.m0205_official_anchor_diagnostic_templates import upgrade as upgrade_diagnostics
from database.migrations.m0206_official_anchor_management_templates import upgrade as upgrade_management
from database.migrations.m0207_official_huawei_interface_template import upgrade as upgrade_interface
from database.migrations.m0208_official_cisco_interface_template import upgrade as upgrade_cisco_interface


def _connection(*, with_compatibility: bool = False):
    conn = postgresql_test_driver.connect()
    conn.executescript(
        """
        CREATE TABLE templates (
            id TEXT PRIMARY KEY,
            name TEXT,
            type TEXT,
            category TEXT,
            vendor TEXT,
            content TEXT,
            rollback TEXT,
            last_used TEXT
        );
        """
    )
    if with_compatibility:
        conn.executescript(
            """
            CREATE TABLE config_template_compatibility (
                id TEXT PRIMARY KEY,
                template_id TEXT,
                vendor TEXT,
                platform TEXT,
                model_pattern TEXT,
                min_version TEXT,
                max_version TEXT,
                required_capabilities_json TEXT,
                excluded_versions_json TEXT
            );
            """
        )
    return conn


def test_ruijie_gold_templates_are_official_and_idempotent():
    conn = _connection(with_compatibility=True)

    upgrade_ruijie(conn.cursor(), use_pg=True)
    upgrade_ruijie(conn.cursor(), use_pg=True)

    rows = conn.execute(
        "SELECT id, vendor, platform_family, official_reference, validation_status, "
        "source_type, status, is_official FROM templates ORDER BY id"
    ).fetchall()
    expected_ids = {
        "ruijie-rgos-vlan-access",
        "ruijie-rgos-aggregateport",
        "ruijie-rgos-show-route",
        "ruijie-rgos-ospf",
        "ruijie-rgos-show-lldp",
        "ruijie-rgos-acl",
    }

    assert {row[0] for row in rows} == expected_ids
    assert conn.execute("SELECT COUNT(*) FROM config_template_compatibility").fetchone()[0] == 6
    for row in rows:
        assert list(row[1:3]) == ["Ruijie", "ruijie_rgos"]
        assert row[3].startswith("https://www.ruijie.com.cn/")
        assert list(row[4:8]) == ["official_reference_reviewed", "official", "published", 1]


def test_anchor_diagnostic_and_management_templates_are_official_and_idempotent():
    conn = _connection()

    upgrade_diagnostics(conn.cursor(), use_pg=True)
    upgrade_management(conn.cursor(), use_pg=True)
    upgrade_interface(conn.cursor(), use_pg=True)
    upgrade_cisco_interface(conn.cursor(), use_pg=True)
    upgrade_diagnostics(conn.cursor(), use_pg=True)
    upgrade_management(conn.cursor(), use_pg=True)
    upgrade_interface(conn.cursor(), use_pg=True)
    upgrade_cisco_interface(conn.cursor(), use_pg=True)

    rows = conn.execute(
        "SELECT id, vendor, platform_family, content, official_reference, "
        "validation_status, source_type, status, is_official FROM templates ORDER BY id"
    ).fetchall()
    expected_ids = {
        "official-huawei-ce12800-vxlan-evpn-basic",
        "official-huawei-port-security-basic",
        "official-huawei-cpu-memory-diagnostic",
        "official-h3c-interface-brief-diagnostic",
        "official-h3c-arp-mac-diagnostic",
        "official-cisco-arp-mac-diagnostic",
        "official-huawei-ospf-bfd-basic",
        "official-huawei-super-password-basic",
        "official-cisco-aaa-authentication-basic",
        "official-huawei-ce6885-interface-status-diagnostic",
        "official-cisco-interface-switchport-basic",
    }

    assert {row[0] for row in rows} == expected_ids
    assert len(rows) == len(expected_ids)
    for row in rows:
        assert row[1] in {"Huawei", "Cisco", "H3C"}
        assert row[2] in {"huawei_vrp", "cisco_iosxe", "h3c_comware"}
        assert row[4].startswith(("https://info.support.huawei.com/", "https://www.cisco.com/", "https://www.h3c.com/"))
        assert list(row[5:9]) == ["official_reference_reviewed", "official", "published", 1]

    by_id = {row[0]: row for row in rows}
    assert "bfd all-interfaces enable" in by_id["official-huawei-ospf-bfd-basic"][3]
    assert "super password" in by_id["official-huawei-super-password-basic"][3]
    assert "aaa authentication login" in by_id["official-cisco-aaa-authentication-basic"][3]
    assert "display interface brief" in by_id["official-huawei-ce6885-interface-status-diagnostic"][3]
    assert "switchport mode" in by_id["official-cisco-interface-switchport-basic"][3]
