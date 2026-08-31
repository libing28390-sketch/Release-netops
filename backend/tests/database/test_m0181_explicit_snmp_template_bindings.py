from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0181_explicit_snmp_template_bindings import upgrade


def test_m0181_adds_explicit_binding_columns_and_removes_model_unique_constraint() -> None:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.executescript(
        """
        CREATE TABLE devices (
            id TEXT PRIMARY KEY,
            vendor TEXT,
            platform TEXT,
            model TEXT,
            status TEXT
        );
        CREATE TABLE snmp_metric_profiles (
            id TEXT PRIMARY KEY,
            vendor_key TEXT NOT NULL,
            vendor_name TEXT NOT NULL DEFAULT '',
            model_key TEXT NOT NULL,
            model_name TEXT NOT NULL DEFAULT '',
            cpu_oid TEXT NOT NULL DEFAULT '',
            memory_oid TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL DEFAULT '',
            UNIQUE(vendor_key, model_key)
        );
        INSERT INTO snmp_metric_profiles
            (id, vendor_key, vendor_name, model_key, model_name, created_at, updated_at)
        VALUES ('profile-1', 'h3c', 'H3C', 's6800', 'S6800', 'now', 'now');
        INSERT INTO devices (id, vendor, platform, model, status)
        VALUES ('device-1', 'H3C', 'h3c_comware', 'S6800', 'online');
        """
    )

    upgrade(conn.cursor(), True)

    device_columns = pg_catalog.table_columns(conn, "devices")
    profile_columns = pg_catalog.table_columns(conn, "snmp_metric_profiles")
    assert "snmp_metric_profile_id" in device_columns
    assert {"template_name", "source", "official_preset_id"}.issubset(profile_columns)
    assert conn.execute(
        "SELECT snmp_metric_profile_id FROM devices WHERE id = 'device-1'"
    ).fetchone()[0] == "profile-1"

    # The same vendor/model may now have an official and a custom template.
    conn.execute(
        """
        INSERT INTO snmp_metric_profiles
            (id, vendor_key, vendor_name, model_key, model_name, created_at, updated_at)
        VALUES ('profile-2', 'h3c', 'H3C', 's6800', 'S6800', 'now', 'now')
        """
    )
    conn.commit()

    # A second invocation is safe and does not remove the explicit reference.
    upgrade(conn.cursor(), True)
    assert conn.execute(
        "SELECT snmp_metric_profile_id FROM devices WHERE id = 'device-1'"
    ).fetchone()[0] == "profile-1"
    conn.close()
