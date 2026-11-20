from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0155_config_backup_transfer_protocol import upgrade


def test_m0155_adds_archive_protocol_columns_idempotently():
    conn = postgresql_test_driver.connect()
    conn.execute(
        """
        CREATE TABLE config_backup_policies (
            id TEXT PRIMARY KEY,
            tftp_enabled INTEGER DEFAULT 0,
            tftp_server TEXT DEFAULT '',
            tftp_port INTEGER DEFAULT 69,
            tftp_path_prefix TEXT DEFAULT 'backups'
        )
        """
    )
    conn.execute("INSERT INTO config_backup_policies (id) VALUES ('legacy')")

    upgrade(conn, use_pg=True)
    upgrade(conn, use_pg=True)

    columns = pg_catalog.table_columns(conn, "config_backup_policies")
    row = conn.execute("SELECT tftp_protocol, tftp_username, tftp_password FROM config_backup_policies WHERE id = 'legacy'").fetchone()
    conn.close()

    assert {"tftp_protocol", "tftp_username", "tftp_password"}.issubset(columns)
    assert tuple(row) == ("tftp", "", "")
