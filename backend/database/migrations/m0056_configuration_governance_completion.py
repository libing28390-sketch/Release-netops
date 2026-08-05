"""Complete configuration search, template, and diff governance persistence."""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 56
NAME = "configuration_governance_completion"


def _column_exists(cursor, table: str, column: str, use_pg: bool) -> bool:
    if use_pg:
        return cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ?
              AND column_name = ?
            """,
            (table, column),
        ).fetchone() is not None
    return any(str(row[1]) == column for row in cursor.execute(f"PRAGMA table_info({table})").fetchall())


def _ensure_column(cursor, table: str, column: str, definition: str, use_pg: bool) -> None:
    if not _column_exists(cursor, table, column, use_pg):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    for column, definition in (
        ("result_device_count", "INTEGER NOT NULL DEFAULT 0"),
        ("result_object_count", "INTEGER NOT NULL DEFAULT 0"),
        ("result_line_count", "INTEGER NOT NULL DEFAULT 0"),
        ("viewed_sensitive_content", "INTEGER NOT NULL DEFAULT 0"),
        ("exported", "INTEGER NOT NULL DEFAULT 0"),
        ("client_ip", "TEXT NOT NULL DEFAULT ''"),
        ("metadata_json", "TEXT NOT NULL DEFAULT '{}'"),
    ):
        _ensure_column(cursor, "config_search_audit", column, definition, use_pg)

    for column, definition in (
        ("parent_type", "TEXT NOT NULL DEFAULT ''"),
        ("parent_name", "TEXT NOT NULL DEFAULT ''"),
        ("object_hash", "TEXT NOT NULL DEFAULT ''"),
        ("first_seen_at", "TEXT NOT NULL DEFAULT ''"),
        ("last_seen_at", "TEXT NOT NULL DEFAULT ''"),
        ("current_present", "INTEGER NOT NULL DEFAULT 1"),
        ("confidence", "REAL NOT NULL DEFAULT 0.0"),
    ):
        _ensure_column(cursor, "config_search_objects", column, definition, use_pg)

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_search_index_jobs (
            id TEXT PRIMARY KEY,
            scope_type TEXT NOT NULL DEFAULT 'all',
            scope_value TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            total_items INTEGER NOT NULL DEFAULT 0,
            completed_items INTEGER NOT NULL DEFAULT 0,
            failed_items INTEGER NOT NULL DEFAULT 0,
            error_text TEXT NOT NULL DEFAULT '',
            requested_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT '',
            completed_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_template_tests (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            template_version TEXT NOT NULL DEFAULT '1.0',
            name TEXT NOT NULL,
            parameters_json TEXT NOT NULL DEFAULT '{}',
            expected_contains_json TEXT NOT NULL DEFAULT '[]',
            expected_not_contains_json TEXT NOT NULL DEFAULT '[]',
            expected_risk_level TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            last_status TEXT NOT NULL DEFAULT 'never',
            last_result_json TEXT NOT NULL DEFAULT '{}',
            last_run_at TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_template_reviews (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            template_version TEXT NOT NULL,
            action TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            reviewer TEXT NOT NULL,
            reviewed_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_template_import_audit (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'custom',
            source_name TEXT NOT NULL DEFAULT '',
            checksum TEXT NOT NULL,
            expected_checksum TEXT NOT NULL DEFAULT '',
            signature_status TEXT NOT NULL DEFAULT 'unsigned',
            imported_by TEXT NOT NULL,
            imported_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_golden_baselines (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            scope_json TEXT NOT NULL DEFAULT '{}',
            source_type TEXT NOT NULL DEFAULT 'snapshot',
            snapshot_id TEXT NOT NULL DEFAULT '',
            template_id TEXT NOT NULL DEFAULT '',
            expected_config TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_diff_reports (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            snapshot_a_id TEXT NOT NULL,
            snapshot_b_id TEXT NOT NULL,
            report_type TEXT NOT NULL DEFAULT 'risk',
            summary_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'ready',
            generated_by TEXT NOT NULL DEFAULT '',
            generated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_change_validation_workflows (
            id TEXT PRIMARY KEY,
            change_order_id TEXT NOT NULL DEFAULT '',
            device_id TEXT NOT NULL,
            before_snapshot_id TEXT NOT NULL DEFAULT '',
            expected_snapshot_id TEXT NOT NULL DEFAULT '',
            after_snapshot_id TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL DEFAULT 'precheck',
            dry_run_result_json TEXT NOT NULL DEFAULT '{}',
            risk_summary_json TEXT NOT NULL DEFAULT '{}',
            precheck_result_json TEXT NOT NULL DEFAULT '{}',
            postcheck_result_json TEXT NOT NULL DEFAULT '{}',
            rollback_plan_json TEXT NOT NULL DEFAULT '{}',
            requires_mfa INTEGER NOT NULL DEFAULT 1,
            approved_by TEXT NOT NULL DEFAULT '',
            executed_by TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_object_history "
        "ON config_search_objects(object_type, object_key, first_seen_at, last_seen_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_index_jobs_status "
        "ON config_search_index_jobs(status, created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_template_tests_template "
        "ON config_template_tests(template_id, template_version)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_template_reviews_template "
        "ON config_template_reviews(template_id, reviewed_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_golden_baselines_enabled "
        "ON config_golden_baselines(enabled, updated_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_diff_reports_device "
        "ON config_diff_reports(device_id, generated_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_change_validation_device "
        "ON config_change_validation_workflows(device_id, created_at)"
    )

    # Keep the database rule catalog aligned with the risk engine.  The engine
    # remains deterministic and these records provide governance metadata.
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rules = (
        ("INTERFACE_IP_CHANGE", "接口三层地址变化", "interface", "high"),
        ("ACCESS_VLAN_CHANGE", "Access VLAN 变化", "interface", "high"),
        ("TRUNK_ALLOWED_CHANGE", "Trunk VLAN 范围变化", "interface", "high"),
        ("INTERFACE_MTU_CHANGE", "接口 MTU 变化", "interface", "medium"),
        ("INTERFACE_VRF_CHANGE", "接口 VRF 变化", "interface", "critical"),
        ("INTERFACE_ACL_CHANGE", "接口 ACL 绑定变化", "interface", "high"),
        ("DEFAULT_ROUTE_ADD", "新增默认路由", "route", "high"),
        ("STATIC_ROUTE_NEXTHOP_CHANGE", "静态路由下一跳变化", "route", "high"),
        ("BGP_NEIGHBOR_ADD", "新增 BGP 邻居", "bgp", "high"),
        ("ACL_DELETE", "删除 ACL", "acl", "critical"),
        ("OSPF_PROCESS_DELETE", "删除 OSPF 进程", "ospf", "critical"),
        ("OSPF_PROCESS_CHANGE", "修改 OSPF 进程", "ospf", "high"),
        ("ISIS_PROCESS_DELETE", "删除 ISIS 进程", "isis", "critical"),
        ("ISIS_PROCESS_CHANGE", "修改 ISIS 进程", "isis", "high"),
        ("ROUTE_POLICY_CHANGE", "路由策略变化", "route_policy", "high"),
        ("PREFIX_LIST_CHANGE", "前缀列表变化", "prefix_list", "high"),
        ("SNMP_DEFAULT_COMMUNITY", "SNMP 默认 Community", "snmp", "critical"),
        ("NTP_SERVER_DELETE", "删除 NTP Server", "ntp", "high"),
        ("VLAN_DELETE", "删除 VLAN", "vlan", "high"),
        ("TELNET_ENABLE", "启用 Telnet", "vty", "critical"),
        ("LOCAL_USER_CHANGE", "本地管理员变化", "local_user", "high"),
        ("SYSLOG_CHANGE", "日志服务器变化", "syslog", "medium"),
        ("LLDP_DISABLE", "关闭 LLDP", "lldp", "medium"),
    )
    for rule_id, name, object_type, severity in rules:
        if cursor.execute("SELECT 1 FROM config_diff_risk_rules WHERE id = ?", (rule_id,)).fetchone():
            continue
        cursor.execute(
            """
            INSERT INTO config_diff_risk_rules (
                id, name, object_type, vendors_json, match_json, severity,
                message, potential_impact, requires_secondary_approval,
                requires_mfa, enabled, rule_version, created_at, updated_at
            ) VALUES (?, ?, ?, '[]', '{}', ?, ?, '', ?, ?, 1, 'risk-v2', ?, ?)
            """,
            (
                rule_id,
                name,
                object_type,
                severity,
                name,
                1 if severity in {"critical", "high"} else 0,
                1 if severity == "critical" else 0,
                now,
                now,
            ),
        )
