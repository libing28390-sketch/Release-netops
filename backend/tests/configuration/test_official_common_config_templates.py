from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0052_official_common_config_templates import upgrade
from services.config_template_validation_service import validate_template


def _connection() -> postgresql_test_driver.Connection:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.execute(
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
        )
        """
    )
    return conn


def test_official_template_seed_is_idempotent_and_complete() -> None:
    conn = _connection()
    try:
        upgrade(conn, use_pg=True)
        upgrade(conn, use_pg=True)
        rows = conn.execute(
            """
            SELECT id, vendor, content, rollback, platform_family,
                   software_version, official_reference, validation_status
            FROM templates
            WHERE id LIKE 'official-%'
            ORDER BY id
            """
        ).fetchall()
        columns = pg_catalog.table_columns(conn, "templates")
    finally:
        conn.close()

    assert len(rows) == 18
    assert {"Cisco", "Huawei", "H3C"} == {row["vendor"] for row in rows}
    assert {
        "description",
        "platform_family",
        "software_version",
        "official_reference",
        "validation_status",
    }.issubset(columns)
    assert all(row["platform_family"] for row in rows)
    assert all(row["software_version"] for row in rows)
    assert all(row["official_reference"].startswith("https://") for row in rows)
    assert all(row["validation_status"] == "official_reference_reviewed" for row in rows)


def test_every_seeded_template_parses_and_renders() -> None:
    conn = _connection()
    try:
        upgrade(conn, use_pg=True)
        rows = conn.execute(
            """
            SELECT id, vendor, platform_family, software_version, content, rollback
            FROM templates WHERE id LIKE 'official-%'
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        result = validate_template(
            row["content"],
            variables={
                "snmp_auth_key": "AuthSecret123",
                "snmp_priv_key": "PrivSecret123",
            },
            vendor=row["vendor"],
            platform=row["platform_family"],
            software_version=row["software_version"],
            rollback=row["rollback"],
        )
        assert result["syntax_valid"] is True, row["id"]
        assert result["render_valid"] is True, (row["id"], result["issues"])
        assert result["missing_variables"] == [], row["id"]
