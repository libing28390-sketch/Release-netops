from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0050_config_backup_policies import upgrade as upgrade_m0050
from database.migrations.m0153_config_backup_tftp_and_startup import upgrade as upgrade_m0153
from database.migrations.m0155_config_backup_transfer_protocol import upgrade as upgrade_m0155
from services import config_backup_policy_service as policy_service


def _connection() -> postgresql_test_driver.Connection:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.executescript(
        """
        CREATE TABLE action_definitions (
            action_code TEXT PRIMARY KEY,
            name_zh TEXT NOT NULL,
            name_en TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT '',
            risk_level TEXT NOT NULL DEFAULT 'low',
            device_types_json TEXT NOT NULL DEFAULT '[]',
            required_fields_json TEXT NOT NULL DEFAULT '[]',
            optional_fields_json TEXT NOT NULL DEFAULT '[]',
            field_types_json TEXT NOT NULL DEFAULT '{}',
            max_output_bytes INTEGER NOT NULL DEFAULT 2000000,
            max_records INTEGER NOT NULL DEFAULT 1000,
            timeout_seconds INTEGER NOT NULL DEFAULT 30,
            sensitive_level TEXT NOT NULL DEFAULT 'normal',
            consumers_json TEXT NOT NULL DEFAULT '[]',
            read_only INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE global_vars (
            id TEXT PRIMARY KEY,
            key TEXT NOT NULL UNIQUE,
            value TEXT NOT NULL
        );
        CREATE TABLE config_backup_runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL
        );
        CREATE TABLE config_snapshots (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            timestamp TEXT NOT NULL
        );
        CREATE TABLE devices (
            id TEXT PRIMARY KEY,
            hostname TEXT NOT NULL,
            ip_address TEXT,
            platform TEXT,
            vendor TEXT,
            role TEXT,
            site TEXT,
            site_id TEXT,
            status TEXT,
            config_backup_enabled INTEGER DEFAULT 1
        );
        CREATE TABLE tag_assignments (
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            tag_id TEXT NOT NULL
        );
        """
    )
    upgrade_m0050(conn, use_pg=True)
    upgrade_m0153(conn, use_pg=True)
    upgrade_m0155(conn, use_pg=True)
    return conn


def test_migration_is_idempotent_and_adds_policy_attribution() -> None:
    conn = _connection()
    try:
        upgrade_m0050(conn, use_pg=True)
        upgrade_m0153(conn, use_pg=True)
        upgrade_m0155(conn, use_pg=True)
        run_columns = pg_catalog.table_columns(conn, "config_backup_runs")
        snapshot_columns = pg_catalog.table_columns(conn, "config_snapshots")
        policy_indexes = pg_catalog.index_names(conn, "config_backup_policies")
        action = conn.execute(
            "SELECT risk_level, consumers_json FROM action_definitions "
            "WHERE action_code = 'get_startup_config'"
        ).fetchone()
    finally:
        conn.close()

    assert "policy_id" in run_columns
    assert {"policy_id", "config_type"}.issubset(snapshot_columns)
    assert "idx_config_backup_policies_enabled_priority" in policy_indexes
    assert action is not None
    assert action["risk_level"] == "sensitive"
    assert "configuration" in action["consumers_json"]


def test_default_policy_imports_legacy_schedule_and_retention() -> None:
    conn = _connection()
    try:
        conn.executemany(
            "INSERT INTO global_vars (id, key, value) VALUES (?, ?, ?)",
            [
                ("g1", "backup_schedule", '{"enabled": false, "cron": "15 3 * * *"}'),
                ("g2", "backup_retention", '{"max_days": 180, "max_per_device": 60}'),
            ],
        )
        policy = policy_service.ensure_default_policy(conn)
    finally:
        conn.close()

    assert policy["id"] == policy_service.DEFAULT_POLICY_ID
    assert policy["enabled"] is False
    assert policy["cron_expr"] == "15 3 * * *"
    assert policy["retention_days"] == 180
    assert policy["max_versions_per_device"] == 60


def test_preview_and_execution_scope_share_nested_tag_resolution() -> None:
    conn = _connection()
    try:
        conn.executemany(
            """
            INSERT INTO devices
            (id, hostname, ip_address, platform, vendor, role, site, site_id, status,
             config_backup_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("d1", "core-1", "10.0.0.1", "cisco_ios", "Cisco", "core", "SH", "s1", "online", 1),
                ("d2", "core-2", "10.0.0.2", "huawei_vrp", "Huawei", "core", "SH", "s1", "offline", 1),
                ("d3", "access-1", "10.0.0.3", "h3c_comware", "H3C", "access", "BJ", "s2", "online", 1),
                ("d4", "core-disabled", "10.0.0.4", "cisco_ios", "Cisco", "core", "SH", "s1", "online", 0),
            ],
        )
        conn.executemany(
            "INSERT INTO tag_assignments (resource_type, resource_id, tag_id) VALUES ('device', ?, ?)",
            [
                ("d1", "A"), ("d1", "B"), ("d1", "C"),
                ("d2", "A"), ("d2", "B"), ("d2", "D"),
                ("d3", "A"), ("d3", "C"),
                ("d4", "A"), ("d4", "B"), ("d4", "C"),
            ],
        )
        expression = {
            "operator": "and",
            "negated": False,
            "tag_ids": ["A", "B"],
            "groups": [{
                "operator": "or",
                "negated": False,
                "tag_ids": ["C", "D"],
                "groups": [],
            }],
        }
        policy = {
            "scope": {
                "site_ids": ["s1"],
                "roles": ["core"],
                "platforms": [],
                "vendors": [],
                "device_ids": [],
                "exclude_device_ids": [],
                "tag_expression": expression,
            }
        }
        preview = policy_service.preview_policy(conn, policy, page=1, page_size=20)
        device_rows = conn.execute("SELECT * FROM devices ORDER BY id").fetchall()
        execution_targets = policy_service.filter_devices_by_scope(
            conn, device_rows, policy["scope"],
        )
    finally:
        conn.close()

    assert [item["id"] for item in preview["items"]] == ["d1", "d2"]
    assert [item["id"] for item in execution_targets] == ["d1", "d2"]
    assert preview["online"] == 1
    assert preview["offline"] == 1


def test_policy_crud_preserves_scope_and_paginates() -> None:
    conn = _connection()
    try:
        created = policy_service.create_policy(
            conn,
            {
                "name": "核心设备变更备份",
                "scope": {"roles": ["core"], "vendors": ["Cisco"]},
                "cron_expr": "0 */6 * * *",
                "change_only": True,
                "retention_days": 365,
                "max_versions_per_device": 120,
            },
            actor="tester",
        )
        listing = policy_service.list_policies(conn, search="核心", page=1, page_size=10)
        updated = policy_service.update_policy(
            conn,
            created["id"],
            {**created, "enabled": False, "retry_count": 3},
            actor="tester",
        )
        deleted = policy_service.delete_policy(conn, created["id"])
    finally:
        conn.close()

    assert created["scope"]["roles"] == ["core"]
    assert listing["total"] == 1
    assert updated is not None and updated["enabled"] is False
    assert updated["retry_count"] == 3
    assert deleted is True


def test_vendor_scope_falls_back_to_platform_when_vendor_is_empty() -> None:
    conn = _connection()
    try:
        conn.execute(
            """
            INSERT INTO devices
            (id, hostname, ip_address, platform, vendor, role, site, site_id, status,
             config_backup_enabled)
            VALUES ('d1', 'edge-1', '10.0.0.1', 'h3c_comware', '', 'edge', 'SH', 's1',
                    'online', 1)
            """
        )
        rows = conn.execute("SELECT * FROM devices").fetchall()
        matched = policy_service.filter_devices_by_scope(
            conn,
            rows,
            {"vendors": ["H3C"]},
        )
    finally:
        conn.close()

    assert [item["id"] for item in matched] == ["d1"]
