from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0203_official_cisco_hsrp_template import upgrade


def _database():
    conn = postgresql_test_driver.connect()
    conn.execute(
        "CREATE TABLE templates ("
        "id TEXT PRIMARY KEY, name TEXT, type TEXT, category TEXT, vendor TEXT, "
        "content TEXT, rollback TEXT, last_used TEXT)"
    )
    return conn


def test_hsrp_template_is_reviewed_and_idempotent():
    conn = _database()
    upgrade(conn.cursor(), use_pg=True)
    upgrade(conn.cursor(), use_pg=True)

    row = conn.execute(
        "SELECT vendor, platform_family, category, content, rollback, official_reference, "
        "validation_status, source_type, status, is_official FROM templates "
        "WHERE id = 'official-cisco-hsrp-basic'"
    ).fetchone()
    assert tuple(row[0:3]) == ("Cisco", "cisco_iosxe", "reliability")
    assert "standby" in row[3]
    assert "show standby" in row[3]
    assert "no standby" in row[4]
    assert row[5].startswith("https://www.cisco.com/")
    assert tuple(row[6:10]) == ("official_reference_reviewed", "official", "published", 1)
    assert conn.execute(
        "SELECT count(*) FROM templates WHERE id = 'official-cisco-hsrp-basic'"
    ).fetchone()[0] == 1
