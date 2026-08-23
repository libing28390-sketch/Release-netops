import sqlite3

from database.migrations.m0164_official_required_switch_features import upgrade


def _database():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE templates ("
        "id TEXT PRIMARY KEY, name TEXT, type TEXT, category TEXT, vendor TEXT, "
        "content TEXT, rollback TEXT, last_used TEXT)"
    )
    return conn


def test_required_switch_feature_starters_are_seeded_for_each_vendor():
    conn = _database()
    upgrade(conn.cursor(), use_pg=False)
    rows = conn.execute("SELECT vendor, name, content, rollback, official_reference FROM templates").fetchall()

    for vendor in ("Huawei", "H3C", "Cisco"):
        vendor_rows = [row for row in rows if row[0] == vendor]
        assert vendor_rows
        assert all(row[4].startswith("https://") for row in vendor_rows)
        assert all("{{" in row[2] for row in vendor_rows)

    all_text = "\n".join(row[1] + "\n" + row[2] for row in rows).lower()
    for marker in ("aaa", "qos", "vrrp", "mlag", "s-mlag", "vpc"):
        assert marker in all_text


def test_required_switch_feature_migration_is_idempotent():
    conn = _database()
    upgrade(conn.cursor(), use_pg=False)
    first_count = conn.execute("SELECT count(*) FROM templates").fetchone()[0]
    upgrade(conn.cursor(), use_pg=False)
    assert conn.execute("SELECT count(*) FROM templates").fetchone()[0] == first_count
