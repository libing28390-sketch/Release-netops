"""Structured configuration diff, risk, compliance, and correlation storage."""

from __future__ import annotations

from datetime import datetime, timezone
import json


VERSION = 55
NAME = "config_diff_analysis"


def _column_exists(cursor, table: str, column: str, use_pg: bool) -> bool:
    return cursor.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = ?
          AND column_name = ?
        """,
        (table, column),
    ).fetchone() is not None



def _ensure_column(cursor, table: str, column: str, definition: str, use_pg: bool) -> None:
    if not _column_exists(cursor, table, column, use_pg):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    for column, definition in (
        ("platform", "TEXT DEFAULT ''"),
        ("os_version", "TEXT DEFAULT ''"),
        ("collection_source", "TEXT DEFAULT 'unknown'"),
        ("collection_task_id", "TEXT DEFAULT ''"),
        ("change_ticket_id", "TEXT DEFAULT ''"),
        ("operator_id", "TEXT DEFAULT ''"),
        ("credential_id", "TEXT DEFAULT ''"),
        ("command_used", "TEXT DEFAULT ''"),
        ("validation_status", "TEXT DEFAULT 'unknown'"),
        ("validation_message", "TEXT DEFAULT ''"),
        ("is_duplicate", "INTEGER DEFAULT 0"),
        ("is_baseline", "INTEGER DEFAULT 0"),
        ("is_latest", "INTEGER DEFAULT 0"),
        ("parent_snapshot_id", "TEXT DEFAULT ''"),
        ("updated_at", "TEXT DEFAULT ''"),
    ):
        _ensure_column(cursor, "config_snapshots", column, definition, use_pg)

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_diff_cache (
            cache_key TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            snapshot_a_id TEXT NOT NULL,
            snapshot_b_id TEXT NOT NULL,
            diff_mode TEXT NOT NULL DEFAULT 'normalized',
            normalization_version TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            risk_rule_version TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_diff_risk_rules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            object_type TEXT NOT NULL DEFAULT '*',
            vendors_json TEXT NOT NULL DEFAULT '[]',
            match_json TEXT NOT NULL DEFAULT '{}',
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            potential_impact TEXT NOT NULL DEFAULT '',
            requires_secondary_approval INTEGER NOT NULL DEFAULT 0,
            requires_mfa INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            rule_version TEXT NOT NULL DEFAULT 'risk-v1',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_compliance_rules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            scope_json TEXT NOT NULL DEFAULT '{}',
            rule_type TEXT NOT NULL,
            pattern TEXT NOT NULL,
            minimum_count INTEGER NOT NULL DEFAULT 1,
            severity TEXT NOT NULL DEFAULT 'medium',
            remediation TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_diff_confirmations (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            snapshot_a_id TEXT NOT NULL,
            snapshot_b_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'confirmed',
            note TEXT NOT NULL DEFAULT '',
            confirmed_by TEXT NOT NULL DEFAULT '',
            confirmed_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_diff_source_links (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            snapshot_a_id TEXT NOT NULL,
            snapshot_b_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_label TEXT NOT NULL DEFAULT '',
            linked_by TEXT NOT NULL DEFAULT '',
            linked_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_compliance_scan_results (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            compliant_count INTEGER NOT NULL DEFAULT 0,
            noncompliant_count INTEGER NOT NULL DEFAULT 0,
            compliance_rate INTEGER NOT NULL DEFAULT 0,
            findings_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'completed',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_diff_cache_pair "
        "ON config_diff_cache(device_id, snapshot_a_id, snapshot_b_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_diff_confirmations_pair "
        "ON config_diff_confirmations(device_id, snapshot_a_id, snapshot_b_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_diff_source_links_pair "
        "ON config_diff_source_links(device_id, snapshot_a_id, snapshot_b_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_compliance_scan_device "
        "ON config_compliance_scan_results(device_id, created_at)"
    )

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    risk_rules = [
        ("MGMT_IP_CHANGE", "修改管理地址", "interface", "critical", "管理 IP 发生变化", "可能导致 Nexora、监控与 SSH 失联", 1, 1),
        ("DEFAULT_ROUTE_DELETE", "删除默认路由", "route", "critical", "默认路由被删除", "可能导致全局出口中断", 1, 1),
        ("IFACE_SHUTDOWN", "关闭接口", "interface", "high", "接口被关闭", "可能造成链路或下游网络中断", 1, 1),
        ("ACCESS_TO_TRUNK", "Access 改为 Trunk", "interface", "high", "接口模式由 Access 变为 Trunk", "可能导致 VLAN 泄漏或终端失联", 1, 0),
        ("BGP_NEIGHBOR_DELETE", "删除 BGP 邻居", "bgp", "critical", "BGP 邻居被删除", "可能导致大范围路由撤销", 1, 1),
        ("STATIC_ROUTE_DELETE", "删除静态路由", "route", "high", "静态路由被删除", "特定网段可能不可达", 1, 0),
        ("ACL_WIDEN_ANY", "ACL 放宽到 any", "acl", "high", "访问控制范围放宽", "可能造成安全暴露", 1, 0),
        ("AAA_CHANGE", "修改 AAA/TACACS", "aaa", "high", "管理认证配置发生变化", "可能导致管理员无法登录", 1, 1),
        ("SNMP_CHANGE", "修改 SNMP", "snmp", "medium", "SNMP 配置发生变化", "监控采集可能中断", 0, 0),
        ("NTP_CHANGE", "修改 NTP", "ntp", "medium", "NTP 配置发生变化", "日志时间与审计可能异常", 0, 0),
    ]
    for rule_id, name, object_type, severity, message, impact, approval, mfa in risk_rules:
        if cursor.execute("SELECT 1 FROM config_diff_risk_rules WHERE id = ?", (rule_id,)).fetchone():
            continue
        cursor.execute(
            """
            INSERT INTO config_diff_risk_rules (
                id, name, object_type, vendors_json, match_json, severity,
                message, potential_impact, requires_secondary_approval,
                requires_mfa, enabled, rule_version, created_at, updated_at
            ) VALUES (?, ?, ?, '[]', '{}', ?, ?, ?, ?, ?, 1, 'risk-v1', ?, ?)
            """,
            (rule_id, name, object_type, severity, message, impact, approval, mfa, now, now),
        )

    compliance_rules = [
        ("NTP_TWO_SERVERS", "核心设备至少配置两个 NTP Server", {"roles": ["core"]}, "require", r"(?im)^\s*(?:ntp-service\s+unicast-server|ntp\s+server)\b", 2, "medium", "配置两个独立 NTP Server。"),
        ("TELNET_DISABLED", "禁止启用 Telnet", {}, "forbid", r"(?im)^\s*(?:telnet\s+server\s+enable|transport\s+input\s+.*telnet)", 1, "high", "关闭 Telnet，仅允许 SSH。"),
        ("SYSLOG_REQUIRED", "必须配置日志服务器", {}, "require", r"(?im)^\s*(?:info-center\s+loghost|logging\s+host)\b", 1, "medium", "配置企业 Syslog 服务器。"),
        ("SSH_REQUIRED", "必须启用 SSH 管理", {}, "require", r"(?im)^\s*(?:stelnet\s+server\s+enable|ip\s+ssh\s+version)\b", 1, "high", "启用 SSH 并禁用不安全管理协议。"),
        ("VTY_ACL_REQUIRED", "管理 VTY 必须绑定 ACL", {}, "require", r"(?im)^\s*(?:acl\s+\d+\s+inbound|access-class\s+\S+\s+in)\b", 1, "high", "在 VTY 上绑定管理 ACL。"),
        ("LLDP_ACCESS_REQUIRED", "接入交换机必须启用 LLDP", {"roles": ["access"]}, "require", r"(?im)^\s*(?:lldp\s+enable|lldp\s+run)\b", 1, "low", "全局启用 LLDP。"),
    ]
    for rule_id, name, scope, rule_type, pattern, minimum, severity, remediation in compliance_rules:
        if cursor.execute("SELECT 1 FROM config_compliance_rules WHERE id = ?", (rule_id,)).fetchone():
            continue
        cursor.execute(
            """
            INSERT INTO config_compliance_rules (
                id, name, description, scope_json, rule_type, pattern,
                minimum_count, severity, remediation, enabled, created_by,
                created_at, updated_at
            ) VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, 1, 'system', ?, ?)
            """,
            (
                rule_id,
                name,
                json.dumps(scope, ensure_ascii=False),
                rule_type,
                pattern,
                minimum,
                severity,
                remediation,
                now,
                now,
            ),
        )
