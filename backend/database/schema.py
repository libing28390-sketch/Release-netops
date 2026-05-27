import os
import uuid
import json
import logging
import bcrypt
from datetime import datetime, timezone

from .core import (
    _USE_PG, _JSON_ARRAY_FN, _SERIAL_PK, PROJECT_ROOT, logger,
    get_db_connection, _beijing_now_iso, _utc_now_iso
)
from .seed import (
    _build_network_inspection_items, std_scripts, get_default_items, compliance_expected_values
)

_db_initialized = False

def _table_columns(cursor, table_name: str) -> set[str]:
    """Return column names for *table_name*. Backend-aware."""
    if _USE_PG:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table_name,),
        )
        return {row[0] for row in cursor.fetchall()}
    return {row['name'] for row in cursor.execute(f'PRAGMA table_info({table_name})').fetchall()}


def _table_columns_deprecated(cursor, table_name: str) -> set[str]:
    """DEPRECATED — kept for backward compat, use _table_columns instead."""
    return _table_columns(cursor, table_name)


def init_db():
    global _db_initialized
    if _db_initialized:
        return
    
    conn = get_db_connection()
    try:
        if _USE_PG and hasattr(conn, 'autocommit'):
            conn.autocommit = True
        
        os.makedirs(os.path.join(PROJECT_ROOT, 'data', 'pam_recordings'), exist_ok=True)
        os.makedirs(os.path.join(PROJECT_ROOT, 'data', 'change_order_attachments'), exist_ok=True)

        _init_db_logic(conn)
        conn.commit()
        _db_initialized = True
        logger.info("Database initialization completed successfully.")
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        logger.error(f"CRITICAL: Database initialization failed: {e}", exc_info=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _init_db_logic(conn):
    cursor = conn.cursor()

    def ensure_column(table_name: str, column_name: str, definition: str):
        cols = _table_columns(cursor, table_name)
        if column_name not in cols:
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}')
        
    # Create devices table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS devices (
        id TEXT PRIMARY KEY,
        hostname TEXT,
        ip_address TEXT,
        platform TEXT,
        status TEXT,
        compliance TEXT,
        sn TEXT,
        model TEXT,
        version TEXT,
        role TEXT,
        site TEXT,
        uptime TEXT,
        connection_method TEXT,
        username TEXT,
        password TEXT,
        current_config TEXT,
        config_history TEXT,
        cpu_usage INTEGER DEFAULT 0,
        memory_usage INTEGER DEFAULT 0,
        interface_data TEXT DEFAULT '[]',
        snmp_community TEXT DEFAULT 'public',
        snmp_port INTEGER DEFAULT 161,
        cpu_history TEXT DEFAULT '[]',
        memory_history TEXT DEFAULT '[]',
        temp INTEGER DEFAULT 35,
        fan_status TEXT DEFAULT 'ok',
        psu_status TEXT DEFAULT 'redundant',
        sys_name TEXT,
        sys_location TEXT,
        sys_contact TEXT,
        credential_source TEXT DEFAULT 'local',
        vault_path TEXT DEFAULT '',
        ports_count INTEGER DEFAULT 0,
        ports_bandwidth_gbps REAL DEFAULT 0.0,
        switching_capacity_gbps REAL DEFAULT 0.0
    )
    ''')
        
    # Create jobs table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        device_id TEXT,
        task_name TEXT,
        status TEXT,
        output TEXT,
        created_at TEXT,
        FOREIGN KEY (device_id) REFERENCES devices (id)
    )
    ''')
    
    # Create scripts table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS scripts (
        id TEXT PRIMARY KEY,
        name TEXT,
        content TEXT,
        description TEXT,
        platform TEXT,
        category TEXT DEFAULT 'custom',
        script_type TEXT DEFAULT 'shell',
        author TEXT DEFAULT 'admin',
        version TEXT DEFAULT 'v1.0.0',
        status TEXT DEFAULT 'released',
        submitter_id TEXT DEFAULT '',
        submitter_name TEXT DEFAULT '',
        approver_id TEXT DEFAULT '',
        approver_username TEXT DEFAULT '',
        rejected_reason TEXT DEFAULT '',
        created_at TEXT,
        updated_at TEXT
    )
    ''')

    # Multi-role credential columns for PAM
    for col, dtype in [
        ('normal_username', "TEXT DEFAULT ''"),
        ('normal_password', "TEXT DEFAULT ''"),
        ('admin_username', "TEXT DEFAULT ''"),
        ('admin_password', "TEXT DEFAULT ''"),
        ('auth_model', "TEXT DEFAULT 'single'"),
        ('normal_password_last_rotated', "TEXT DEFAULT ''"),
        ('normal_password_expires_at', "TEXT DEFAULT ''"),
        ('admin_password_last_rotated', "TEXT DEFAULT ''"),
        ('admin_password_expires_at', "TEXT DEFAULT ''"),
        ('enable_password_last_rotated', "TEXT DEFAULT ''"),
        ('enable_password_expires_at', "TEXT DEFAULT ''"),
        ('management_port', "INTEGER DEFAULT 22"),
        ('is_managed', "INTEGER DEFAULT 0"),
        ('takeover_error', "TEXT DEFAULT ''"),
        ('credential_source', "TEXT DEFAULT 'local'"),
        ('vault_path', "TEXT DEFAULT ''"),
        ('ports_count', 'INTEGER DEFAULT 0'),
        ('ports_bandwidth_gbps', 'REAL DEFAULT 0.0'),
        ('switching_capacity_gbps', 'REAL DEFAULT 0.0')
    ]:
        ensure_column('devices', col, dtype)

    # Migration for script management enhancements
    for col, dtype in [
        ('script_type', "TEXT DEFAULT 'shell'"), 
        ('author', "TEXT DEFAULT 'admin'"), 
        ('version', "TEXT DEFAULT 'v1.0.0'"), 
        ('status', "TEXT DEFAULT 'released'"),
        ('submitter_id', "TEXT DEFAULT ''"),
        ('submitter_name', "TEXT DEFAULT ''"),
        ('approver_id', "TEXT DEFAULT ''"),
        ('approver_username', "TEXT DEFAULT ''"),
        ('rejected_reason', "TEXT DEFAULT ''"),
        ('category', "TEXT DEFAULT 'custom'"),
        ('created_at', 'TEXT'),
        ('updated_at', 'TEXT'),
        ('parent_script_id', "TEXT DEFAULT ''"),
        ('script_family', "TEXT DEFAULT ''"),
        ('is_latest', 'INTEGER DEFAULT 1')
    ]:
        ensure_column('scripts', col, dtype)
    
    # Create templates table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS templates (
        id TEXT PRIMARY KEY,
        name TEXT,
        type TEXT,
        category TEXT,
        vendor TEXT,
        content TEXT,
        rollback TEXT,
        last_used TEXT
    )
    ''')
    ensure_column('templates', 'rollback', 'TEXT')
    
    # Create users table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        status TEXT,
        last_login TEXT,
        avatar_url TEXT,
        created_at TEXT
    )
    ''')
    ensure_column('users', 'created_at', 'TEXT')
    ensure_column('users', 'group_name', "TEXT DEFAULT ''")
    ensure_column('users', 'change_groups_json', "TEXT DEFAULT '[]'")
    ensure_column('users', 'notification_channels', "TEXT DEFAULT '{}'")
    ensure_column('users', 'preferred_language', "TEXT DEFAULT 'zh'")
    ensure_column('users', 'fixed_pin', "TEXT DEFAULT ''")
    ensure_column('users', 'display_name', "TEXT DEFAULT ''")
    ensure_column('users', 'phone', "TEXT DEFAULT ''")
    ensure_column('users', 'email', "TEXT DEFAULT ''")

    # Store user-defined scenario templates for playbooks
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS custom_scenarios (
        id TEXT PRIMARY KEY,
        data_json TEXT NOT NULL,
        created_by TEXT DEFAULT 'admin',
        created_at TEXT,
        updated_at TEXT
    )
    ''')
    
    # Create global_vars table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS global_vars (
        id TEXT PRIMARY KEY,
        key TEXT UNIQUE,
        value TEXT
    )
    ''')

    # Create global_notification_channels table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS global_notification_channels (
        platform TEXT PRIMARY KEY,
        webhook_url TEXT,
        enabled INTEGER DEFAULT 0,
        secret TEXT DEFAULT '',
        creator_username TEXT,
        updated_at TEXT
    )
    ''')

    # Create config_snapshots table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS config_snapshots (
        id TEXT PRIMARY KEY,
        device_id TEXT,
        hostname TEXT,
        vendor TEXT,
        timestamp TEXT,
        trigger TEXT,
        author TEXT,
        tag TEXT DEFAULT '',
        file_path TEXT,
        size INTEGER DEFAULT 0,
        FOREIGN KEY (device_id) REFERENCES devices (id)
    )
    ''')

    # Create links table for topology
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS links (
        id TEXT PRIMARY KEY,
        link_key TEXT UNIQUE,
        source_device_id TEXT,
        source_hostname TEXT,
        source_port TEXT,
        source_port_normalized TEXT,
        target_device_id TEXT,
        target_hostname TEXT,
        target_port TEXT,
        target_port_normalized TEXT,
        discovery_source TEXT DEFAULT 'lldp',
        confidence REAL DEFAULT 0.0,
        status TEXT DEFAULT 'up',
        is_inferred INTEGER DEFAULT 0,
        evidence_count INTEGER DEFAULT 1,
        metadata_json TEXT DEFAULT '{}',
        created_at TEXT,
        updated_at TEXT,
        last_seen TEXT,
        FOREIGN KEY (source_device_id) REFERENCES devices (id),
        FOREIGN KEY (target_device_id) REFERENCES devices (id)
    )
    ''')
    ensure_column('links', 'link_key', 'TEXT')
    ensure_column('links', 'source_hostname', 'TEXT')
    ensure_column('links', 'source_port_normalized', 'TEXT')
    ensure_column('links', 'target_hostname', 'TEXT')
    ensure_column('links', 'target_port_normalized', 'TEXT')
    ensure_column('links', 'discovery_source', "TEXT DEFAULT 'lldp'")
    ensure_column('links', 'confidence', 'REAL DEFAULT 0.0')
    ensure_column('links', 'status', "TEXT DEFAULT 'up'")
    ensure_column('links', 'is_inferred', 'INTEGER DEFAULT 0')
    ensure_column('links', 'evidence_count', 'INTEGER DEFAULT 1')
    ensure_column('links', 'metadata_json', "TEXT DEFAULT '{}'")
    ensure_column('links', 'created_at', 'TEXT')
    ensure_column('links', 'updated_at', 'TEXT')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_links_link_key ON links(link_key)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_links_last_seen ON links(last_seen)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_links_source_target ON links(source_device_id, target_device_id)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS topology_discovery_runs (
        id TEXT PRIMARY KEY,
        scope TEXT NOT NULL DEFAULT 'full',
        status TEXT NOT NULL DEFAULT 'pending',
        requested_by TEXT DEFAULT 'system',
        protocol_scope TEXT DEFAULT 'lldp_cdp',
        started_at TEXT NOT NULL,
        completed_at TEXT,
        total_devices INTEGER DEFAULT 0,
        success_devices INTEGER DEFAULT 0,
        failed_devices INTEGER DEFAULT 0,
        total_observations INTEGER DEFAULT 0,
        total_links INTEGER DEFAULT 0,
        summary_json TEXT DEFAULT '{}'
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_runs_started_at ON topology_discovery_runs(started_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_runs_status ON topology_discovery_runs(status)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS topology_discovery_run_devices (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        hostname TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        discovery_method TEXT DEFAULT '',
        started_at TEXT,
        completed_at TEXT,
        observations_count INTEGER DEFAULT 0,
        matched_links_count INTEGER DEFAULT 0,
        error_message TEXT DEFAULT '',
        FOREIGN KEY (run_id) REFERENCES topology_discovery_runs(id),
        FOREIGN KEY (device_id) REFERENCES devices(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_run_devices_run_id ON topology_discovery_run_devices(run_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_run_devices_device_id ON topology_discovery_run_devices(device_id)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS topology_layouts (
        user_id TEXT PRIMARY KEY,
        layout_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_layouts_updated_at ON topology_layouts(updated_at)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS topology_observations (
        id TEXT PRIMARY KEY,
        source_device_id TEXT NOT NULL,
        source_hostname TEXT DEFAULT '',
        source_port_raw TEXT DEFAULT '',
        source_port_normalized TEXT DEFAULT '',
        neighbor_name_raw TEXT DEFAULT '',
        neighbor_name_normalized TEXT DEFAULT '',
        neighbor_ip_address TEXT DEFAULT '',
        target_device_id TEXT,
        target_hostname TEXT DEFAULT '',
        target_port_raw TEXT DEFAULT '',
        target_port_normalized TEXT DEFAULT '',
        protocol TEXT NOT NULL DEFAULT 'lldp',
        confidence REAL DEFAULT 0.5,
        status TEXT DEFAULT 'active',
        discovery_run_id TEXT,
        raw_payload_json TEXT DEFAULT '{}',
        collected_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (source_device_id) REFERENCES devices(id),
        FOREIGN KEY (target_device_id) REFERENCES devices(id),
        FOREIGN KEY (discovery_run_id) REFERENCES topology_discovery_runs(id)
    )
    ''')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_topology_obs_unique ON topology_observations(source_device_id, source_port_normalized, neighbor_name_normalized, target_device_id, target_port_normalized, protocol)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_obs_target ON topology_observations(target_device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_obs_collected_at ON topology_observations(collected_at)')

    # Create playbook_executions table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS playbook_executions (
        id TEXT PRIMARY KEY,
        scenario_id TEXT,
        scenario_name TEXT,
        platform TEXT DEFAULT 'cisco_ios',
        device_ids TEXT DEFAULT '[]',
        variables TEXT DEFAULT '{}',
        status TEXT DEFAULT 'pending',
        dry_run INTEGER DEFAULT 0,
        author TEXT DEFAULT 'admin',
        concurrency INTEGER DEFAULT 1,
        phases_json TEXT DEFAULT '{}',
        results_json TEXT DEFAULT '{}',
        total_devices INTEGER DEFAULT 0,
        success_count INTEGER DEFAULT 0,
        failed_count INTEGER DEFAULT 0,
        partial_count INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    )
    ''')

    # Per-device execution results
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS execution_device_results (
        id TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL,
        device_id TEXT,
        hostname TEXT DEFAULT '',
        ip_address TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        error_message TEXT DEFAULT '',
        phases_json TEXT DEFAULT '{}',
        started_at TEXT,
        completed_at TEXT,
        duration_ms INTEGER DEFAULT 0,
        FOREIGN KEY (execution_id) REFERENCES playbook_executions(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_edr_execution_id ON execution_device_results(execution_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_edr_exec_status ON execution_device_results(execution_id, status)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        category TEXT NOT NULL,
        severity TEXT NOT NULL,
        status TEXT NOT NULL,
        actor_id TEXT,
        actor_username TEXT,
        actor_role TEXT,
        source_ip TEXT,
        target_type TEXT,
        target_id TEXT,
        target_name TEXT,
        device_id TEXT,
        job_id TEXT,
        execution_id TEXT,
        snapshot_id TEXT,
        summary TEXT NOT NULL,
        details_json TEXT DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_events_category ON audit_events(category)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_events_severity ON audit_events(severity)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_events_actor_username ON audit_events(actor_username)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS compliance_rules (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        category TEXT NOT NULL,
        severity TEXT NOT NULL,
        platforms_json TEXT DEFAULT '[]',
        logic_json TEXT DEFAULT '{}',
        remediation TEXT DEFAULT '',
        reference TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        is_builtin INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS compliance_runs (
        id TEXT PRIMARY KEY,
        initiated_by TEXT DEFAULT 'admin',
        scope_json TEXT DEFAULT '[]',
        status TEXT DEFAULT 'pending',
        started_at TEXT NOT NULL,
        completed_at TEXT,
        summary_json TEXT DEFAULT '{}'
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_compliance_runs_started_at ON compliance_runs(started_at)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS compliance_findings (
        id TEXT PRIMARY KEY,
        fingerprint TEXT UNIQUE NOT NULL,
        rule_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        run_id TEXT,
        severity TEXT NOT NULL,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        observed_value TEXT DEFAULT '',
        evidence TEXT DEFAULT '',
        remediation TEXT DEFAULT '',
        owner TEXT DEFAULT '',
        note TEXT DEFAULT '',
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        resolved_at TEXT,
        FOREIGN KEY (rule_id) REFERENCES compliance_rules(id),
        FOREIGN KEY (device_id) REFERENCES devices(id),
        FOREIGN KEY (run_id) REFERENCES compliance_runs(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_compliance_findings_status ON compliance_findings(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_compliance_findings_severity ON compliance_findings(severity)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_compliance_findings_device_id ON compliance_findings(device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_compliance_findings_last_seen_at ON compliance_findings(last_seen_at)')

    # Track notification read status per user
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS notification_reads (
        user_id TEXT,
        notification_id TEXT,
        read_at TEXT,
        PRIMARY KEY (user_id, notification_id)
    )
    ''')

    # Persistent session store
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        username TEXT NOT NULL,
        role TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at)')

    # Persistent login failure tracking
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS login_failures (
        username TEXT PRIMARY KEY,
        count INTEGER DEFAULT 0,
        locked_until REAL DEFAULT 0
    )
    ''')

    # Password reset verification codes
    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS password_reset_codes (
        id {_SERIAL_PK},
        username TEXT NOT NULL,
        code TEXT NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        used INTEGER DEFAULT 0
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pwd_reset_username ON password_reset_codes(username)')

    # High-frequency raw interface telemetry (short retention)
    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS interface_telemetry_raw (
        id {_SERIAL_PK},
        ts TEXT NOT NULL,
        device_id TEXT NOT NULL,
        interface_name TEXT NOT NULL,
        status TEXT,
        speed_mbps REAL,
        in_bps REAL,
        out_bps REAL,
        bw_in_pct REAL,
        bw_out_pct REAL,
        in_pkts INTEGER,
        out_pkts INTEGER,
        in_errors INTEGER,
        out_errors INTEGER,
        in_discards INTEGER,
        out_discards INTEGER
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_interface_telemetry_raw_ts ON interface_telemetry_raw(ts)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_interface_telemetry_raw_dev_intf_ts ON interface_telemetry_raw(device_id, interface_name, ts)')

    # 1-minute rollup telemetry for long-term trending
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS interface_telemetry_1m (
        ts_minute TEXT NOT NULL,
        device_id TEXT NOT NULL,
        interface_name TEXT NOT NULL,
        samples INTEGER DEFAULT 0,
        avg_in_bps REAL,
        max_in_bps REAL,
        avg_out_bps REAL,
        max_out_bps REAL,
        avg_bw_in_pct REAL,
        max_bw_in_pct REAL,
        avg_bw_out_pct REAL,
        max_bw_out_pct REAL,
        in_pkts_sum INTEGER DEFAULT 0,
        out_pkts_sum INTEGER DEFAULT 0,
        err_delta_sum INTEGER DEFAULT 0,
        discard_delta_sum INTEGER DEFAULT 0,
        PRIMARY KEY (ts_minute, device_id, interface_name)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_interface_telemetry_1m_ts ON interface_telemetry_1m(ts_minute)')

    # Alert lifecycle records (open/resolved)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS alert_events (
        id TEXT PRIMARY KEY,
        dedupe_key TEXT NOT NULL,
        source TEXT NOT NULL,
        severity TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        device_id TEXT,
        interface_name TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        workflow_status TEXT NOT NULL DEFAULT 'open',
        assignee TEXT,
        ack_by TEXT,
        ack_at TEXT,
        note TEXT DEFAULT '',
        updated_at TEXT
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_events_created_at ON alert_events(created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_events_resolved_at ON alert_events(resolved_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_events_dedupe_key ON alert_events(dedupe_key)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS protocol_peer_state (
        metric_type TEXT NOT NULL,
        device_id TEXT NOT NULL,
        peer TEXT NOT NULL,
        object_name TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (metric_type, device_id, peer)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_protocol_peer_state_device_metric ON protocol_peer_state(device_id, metric_type)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS alert_maintenance_windows (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        target_ip TEXT NOT NULL,
        target_ips_json TEXT DEFAULT '[]',
        selection_mode TEXT DEFAULT 'resources',
        condition_logic TEXT DEFAULT 'all',
        match_conditions_json TEXT DEFAULT '[]',
        title_pattern TEXT DEFAULT '',
        message_pattern TEXT DEFAULT '',
        starts_at TEXT NOT NULL,
        ends_at TEXT NOT NULL,
        notify_user_ids TEXT DEFAULT '[]',
        reason TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'scheduled',
        created_by TEXT DEFAULT 'system',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_match_count INTEGER DEFAULT 0
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_mw_target_ip ON alert_maintenance_windows(target_ip)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_mw_starts_at ON alert_maintenance_windows(starts_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_mw_ends_at ON alert_maintenance_windows(ends_at)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS alert_rules (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        metric_type TEXT NOT NULL,
        scope_type TEXT NOT NULL DEFAULT 'global',
        scope_match_mode TEXT NOT NULL DEFAULT 'exact',
        scope_value TEXT DEFAULT '',
        severity TEXT NOT NULL DEFAULT 'major',
        threshold REAL,
        enabled INTEGER DEFAULT 1,
        aggregation_mode TEXT DEFAULT 'dedupe_key',
        notification_repeat_window_seconds INTEGER DEFAULT 120,
        notify_on_active INTEGER DEFAULT 1,
        notify_on_recovery INTEGER DEFAULT 1,
        notify_on_reopen_after_maintenance INTEGER DEFAULT 1,
        created_by TEXT DEFAULT 'system',
        created_at TEXT NOT NULL,
        updated_by TEXT DEFAULT 'system',
        updated_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_rules_metric_type ON alert_rules(metric_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_rules_enabled ON alert_rules(enabled)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS alert_rule_settings (
        id TEXT PRIMARY KEY,
        interface_down_enabled INTEGER DEFAULT 1,
        interface_util_threshold REAL DEFAULT 85,
        cpu_threshold REAL DEFAULT 90,
        memory_threshold REAL DEFAULT 90,
        aggregation_mode TEXT DEFAULT 'dedupe_key',
        notification_repeat_window_seconds INTEGER DEFAULT 120,
        notify_on_active INTEGER DEFAULT 1,
        notify_on_recovery INTEGER DEFAULT 1,
        notify_on_reopen_after_maintenance INTEGER DEFAULT 1,
        updated_by TEXT DEFAULT 'system',
        updated_at TEXT NOT NULL
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS alert_rule_history (
        id TEXT PRIMARY KEY,
        settings_id TEXT NOT NULL DEFAULT 'default',
        snapshot_json TEXT NOT NULL,
        changed_by TEXT DEFAULT 'system',
        created_at TEXT NOT NULL,
        FOREIGN KEY (settings_id) REFERENCES alert_rule_settings(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_rule_history_settings_id ON alert_rule_history(settings_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_rule_history_created_at ON alert_rule_history(created_at)')

    # Host resource telemetry for the platform server itself
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS host_resource_samples (
        ts TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        cpu_percent REAL,
        memory_percent REAL,
        disk_percent REAL,
        load_1m REAL,
        process_memory_mb REAL,
        process_cpu_percent REAL,
        memory_used_gb REAL,
        memory_total_gb REAL,
        disk_used_gb REAL,
        disk_total_gb REAL,
        disk_free_gb REAL,
        uptime_hours REAL,
        database_ok INTEGER DEFAULT 0,
        database_status TEXT DEFAULT ''
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_host_resource_samples_ts ON host_resource_samples(ts)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS device_health_samples (
        ts TEXT NOT NULL,
        device_id TEXT NOT NULL,
        hostname TEXT,
        status TEXT,
        health_status TEXT NOT NULL,
        health_score INTEGER NOT NULL,
        open_alert_count INTEGER DEFAULT 0,
        critical_open_alerts INTEGER DEFAULT 0,
        major_open_alerts INTEGER DEFAULT 0,
        warning_open_alerts INTEGER DEFAULT 0,
        interface_down_count INTEGER DEFAULT 0,
        interface_flap_count INTEGER DEFAULT 0,
        high_util_interface_count INTEGER DEFAULT 0,
        interface_error_count INTEGER DEFAULT 0,
        health_summary TEXT DEFAULT '',
        health_reasons_json TEXT DEFAULT '[]',
        PRIMARY KEY (ts, device_id),
        FOREIGN KEY (device_id) REFERENCES devices(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_device_health_samples_ts ON device_health_samples(ts)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_device_health_samples_device_ts ON device_health_samples(device_id, ts)')

    # Migration: add columns to playbook_executions if missing
    pb_cols = _table_columns(cursor, 'playbook_executions')
    if 'platform' not in pb_cols:
        cursor.execute("ALTER TABLE playbook_executions ADD COLUMN platform TEXT DEFAULT 'cisco_ios'")
    if 'total_devices' not in pb_cols:
        cursor.execute("ALTER TABLE playbook_executions ADD COLUMN total_devices INTEGER DEFAULT 0")
    if 'success_count' not in pb_cols:
        cursor.execute("ALTER TABLE playbook_executions ADD COLUMN success_count INTEGER DEFAULT 0")
    if 'failed_count' not in pb_cols:
        cursor.execute("ALTER TABLE playbook_executions ADD COLUMN failed_count INTEGER DEFAULT 0")
    if 'partial_count' not in pb_cols:
        cursor.execute("ALTER TABLE playbook_executions ADD COLUMN partial_count INTEGER DEFAULT 0")

    device_health_columns = _table_columns(cursor, 'device_health_samples')
    if device_health_columns and 'health_reasons_json' not in device_health_columns:
        cursor.execute("ALTER TABLE device_health_samples ADD COLUMN health_reasons_json TEXT DEFAULT '[]'")
        cursor.execute(
            "UPDATE device_health_samples SET health_reasons_json = '[]' WHERE health_reasons_json IS NULL OR health_reasons_json = ''"
        )

    # Migration: Add new columns if they don't exist
    columns = _table_columns(cursor, 'devices')
    
    if 'cpu_usage' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN cpu_usage INTEGER DEFAULT 0')
    if 'memory_usage' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN memory_usage INTEGER DEFAULT 0')
    if 'interface_data' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN interface_data TEXT DEFAULT "[]"')
    if 'snmp_community' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN snmp_community TEXT DEFAULT "public"')
    if 'snmp_port' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN snmp_port INTEGER DEFAULT 161')
    if 'cpu_history' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN cpu_history TEXT DEFAULT "[]"')
    if 'memory_history' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN memory_history TEXT DEFAULT "[]"')

    # Migration: add alert workflow columns if they don't exist
    alert_columns = _table_columns(cursor, 'alert_events')
    if 'workflow_status' not in alert_columns:
        cursor.execute("ALTER TABLE alert_events ADD COLUMN workflow_status TEXT NOT NULL DEFAULT 'open'")
    if 'assignee' not in alert_columns:
        cursor.execute('ALTER TABLE alert_events ADD COLUMN assignee TEXT')
    if 'ack_by' not in alert_columns:
        cursor.execute('ALTER TABLE alert_events ADD COLUMN ack_by TEXT')
    if 'ack_at' not in alert_columns:
        cursor.execute('ALTER TABLE alert_events ADD COLUMN ack_at TEXT')
    if 'note' not in alert_columns:
        cursor.execute("ALTER TABLE alert_events ADD COLUMN note TEXT DEFAULT ''")
    if 'updated_at' not in alert_columns:
        cursor.execute('ALTER TABLE alert_events ADD COLUMN updated_at TEXT')
    
    cursor.execute(
        "UPDATE alert_events SET workflow_status = CASE WHEN resolved_at IS NULL THEN 'open' ELSE 'resolved' END WHERE workflow_status IS NULL OR workflow_status = ''"
    )
    cursor.execute("UPDATE alert_events SET updated_at = COALESCE(updated_at, resolved_at, created_at)")

    maintenance_columns = _table_columns(cursor, 'alert_maintenance_windows')
    if 'target_ips_json' not in maintenance_columns:
        cursor.execute("ALTER TABLE alert_maintenance_windows ADD COLUMN target_ips_json TEXT DEFAULT '[]'")
    if 'selection_mode' not in maintenance_columns:
        cursor.execute("ALTER TABLE alert_maintenance_windows ADD COLUMN selection_mode TEXT DEFAULT 'resources'")
    if 'condition_logic' not in maintenance_columns:
        cursor.execute("ALTER TABLE alert_maintenance_windows ADD COLUMN condition_logic TEXT DEFAULT 'all'")
    if 'match_conditions_json' not in maintenance_columns:
        cursor.execute("ALTER TABLE alert_maintenance_windows ADD COLUMN match_conditions_json TEXT DEFAULT '[]'")
    cursor.execute(
        f'''
        UPDATE alert_maintenance_windows
        SET target_ips_json = CASE
            WHEN COALESCE(target_ips_json, '') = '' OR target_ips_json = '[]' THEN CAST({_JSON_ARRAY_FN}(target_ip) AS TEXT)
            ELSE target_ips_json
        END
        WHERE COALESCE(target_ip, '') != ''
        '''
    )
    cursor.execute(
        '''
        UPDATE alert_maintenance_windows
        SET selection_mode = CASE
            WHEN COALESCE(selection_mode, '') = '' AND (
                COALESCE(title_pattern, '') != '' OR COALESCE(message_pattern, '') != ''
            ) THEN 'conditions'
            WHEN COALESCE(selection_mode, '') = '' THEN 'resources'
            ELSE selection_mode
        END
        '''
    )
    cursor.execute(
        '''
        UPDATE alert_maintenance_windows
        SET condition_logic = CASE
            WHEN COALESCE(condition_logic, '') IN ('all', 'any', 'none') THEN condition_logic
            ELSE 'all'
        END
        '''
    )

    rule_columns = _table_columns(cursor, 'alert_rule_settings')
    if rule_columns:
        if 'aggregation_mode' not in rule_columns:
            cursor.execute("ALTER TABLE alert_rule_settings ADD COLUMN aggregation_mode TEXT DEFAULT 'dedupe_key'")
        if 'notification_repeat_window_seconds' not in rule_columns:
            cursor.execute('ALTER TABLE alert_rule_settings ADD COLUMN notification_repeat_window_seconds INTEGER DEFAULT 120')
        if 'notify_on_active' not in rule_columns:
            cursor.execute('ALTER TABLE alert_rule_settings ADD COLUMN notify_on_active INTEGER DEFAULT 1')
        if 'notify_on_recovery' not in rule_columns:
            cursor.execute('ALTER TABLE alert_rule_settings ADD COLUMN notify_on_recovery INTEGER DEFAULT 1')
        if 'notify_on_reopen_after_maintenance' not in rule_columns:
            cursor.execute('ALTER TABLE alert_rule_settings ADD COLUMN notify_on_reopen_after_maintenance INTEGER DEFAULT 1')
        if 'updated_by' not in rule_columns:
            cursor.execute("ALTER TABLE alert_rule_settings ADD COLUMN updated_by TEXT DEFAULT 'system'")
        if 'updated_at' not in rule_columns:
            cursor.execute("ALTER TABLE alert_rule_settings ADD COLUMN updated_at TEXT")

    cursor.execute(
        '''
        INSERT INTO alert_rule_settings (
            id, interface_down_enabled, interface_util_threshold, cpu_threshold, memory_threshold,
            aggregation_mode, notification_repeat_window_seconds,
            notify_on_active, notify_on_recovery, notify_on_reopen_after_maintenance,
            updated_by, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO NOTHING
        ''',
        (
            'default',
            1,
            85,
            90,
            90,
            'dedupe_key',
            120,
            1,
            1,
            1,
            'system',
            _utc_now_iso(),
        ),
    )
    cursor.execute("UPDATE alert_rule_settings SET updated_at = COALESCE(updated_at, ?) WHERE updated_at IS NULL OR updated_at = ''", (_utc_now_iso(),))

    alert_rule_columns = _table_columns(cursor, 'alert_rules')
    if alert_rule_columns and 'scope_match_mode' not in alert_rule_columns:
        cursor.execute("ALTER TABLE alert_rules ADD COLUMN scope_match_mode TEXT NOT NULL DEFAULT 'exact'")
    if alert_rule_columns and 'for_duration_seconds' not in alert_rule_columns:
        cursor.execute("ALTER TABLE alert_rules ADD COLUMN for_duration_seconds INTEGER DEFAULT 0")

    legacy_rules = cursor.execute(
        '''
        SELECT interface_down_enabled, interface_util_threshold, cpu_threshold, memory_threshold,
               aggregation_mode, notification_repeat_window_seconds,
               notify_on_active, notify_on_recovery, notify_on_reopen_after_maintenance,
               updated_by, updated_at
        FROM alert_rule_settings
        WHERE id = 'default'
        LIMIT 1
        '''
    ).fetchone()
    alert_rules_count = cursor.execute('SELECT COUNT(*) FROM alert_rules').fetchone()[0]
    seeded_at = _utc_now_iso()
    legacy_updated_at = legacy_rules['updated_at'] if legacy_rules and legacy_rules['updated_at'] else seeded_at
    legacy_updated_by = legacy_rules['updated_by'] if legacy_rules and legacy_rules['updated_by'] else 'system'
    legacy_aggregation_mode = legacy_rules['aggregation_mode'] if legacy_rules and legacy_rules['aggregation_mode'] else 'dedupe_key'
    legacy_repeat_window = int(legacy_rules['notification_repeat_window_seconds']) if legacy_rules and legacy_rules['notification_repeat_window_seconds'] is not None else 120
    legacy_notify_on_active = int(legacy_rules['notify_on_active']) if legacy_rules and legacy_rules['notify_on_active'] is not None else 1
    legacy_notify_on_recovery = int(legacy_rules['notify_on_recovery']) if legacy_rules and legacy_rules['notify_on_recovery'] is not None else 1
    legacy_notify_on_reopen = int(legacy_rules['notify_on_reopen_after_maintenance']) if legacy_rules and legacy_rules['notify_on_reopen_after_maintenance'] is not None else 1
    seed_rules = [
        ('builtin-cpu', 'CPU Usage High', 'cpu', 'major', float(legacy_rules['cpu_threshold']) if legacy_rules and legacy_rules['cpu_threshold'] is not None else 90.0, 1),
        ('builtin-memory', 'Memory Usage High', 'memory', 'major', float(legacy_rules['memory_threshold']) if legacy_rules and legacy_rules['memory_threshold'] is not None else 90.0, 1),
        ('builtin-if-util', 'Interface Utilization High', 'interface_util', 'warning', float(legacy_rules['interface_util_threshold']) if legacy_rules and legacy_rules['interface_util_threshold'] is not None else 85.0, 1),
        ('builtin-if-down', 'Interface Down', 'interface_down', 'warning', None, int(legacy_rules['interface_down_enabled']) if legacy_rules and legacy_rules['interface_down_enabled'] is not None else 1),
        ('builtin-interconnect-down', 'Interconnect Down', 'interconnect_down', 'major', None, 1),
        ('builtin-temp-high', 'Temperature High', 'temperature_high', 'major', 75.0, 1),
        ('builtin-snmp-unreachable', 'SNMP Unreachable', 'snmp_unreachable', 'major', None, 1),
        ('builtin-lldp-neighbor-lost', 'LLDP Neighbor Lost', 'lldp_neighbor_lost', 'major', None, 1),
        ('builtin-fan-failure', 'Fan Failure', 'fan_failure', 'critical', None, 1),
        ('builtin-psu-failure', 'Power Supply Failure', 'power_supply_failure', 'critical', None, 1),
        ('builtin-if-error-rate', 'Interface Error Rate High', 'interface_error_rate_high', 'major', 2.0, 1),
        ('builtin-if-flap', 'Interface Flapping', 'interface_flap', 'major', None, 1),
        ('builtin-bgp-neighbor-down', 'BGP Neighbor Down', 'bgp_neighbor_down', 'critical', None, 1),
        ('builtin-ospf-neighbor-down', 'OSPF Neighbor Down', 'ospf_neighbor_down', 'critical', None, 1),
        ('builtin-bfd-session-down', 'BFD Session Down', 'bfd_session_down', 'critical', None, 1),
        ('builtin-ping-unreachable', 'Ping Unreachable', 'ping_unreachable', 'critical', None, 1),
        ('builtin-host-cpu', 'Host CPU Usage High', 'host_cpu', 'major', 75.0, 1),
        ('builtin-host-memory', 'Host Memory Usage High', 'host_memory', 'major', 80.0, 1),
        ('builtin-host-disk', 'Host Disk Usage High', 'host_disk', 'major', 80.0, 1),
    ]

    def _insert_seed_rule(rule_id, name, metric_type, severity, threshold, enabled, created_at):
        cursor.execute(
            '''
            INSERT INTO alert_rules (
                id, name, metric_type, scope_type, scope_match_mode, scope_value, severity, threshold, enabled,
                aggregation_mode, notification_repeat_window_seconds,
                notify_on_active, notify_on_recovery, notify_on_reopen_after_maintenance,
                created_by, created_at, updated_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
            ''',
            (
                rule_id,
                name,
                metric_type,
                'global',
                'exact',
                '',
                severity,
                threshold,
                enabled,
                legacy_aggregation_mode,
                legacy_repeat_window,
                legacy_notify_on_active,
                legacy_notify_on_recovery,
                legacy_notify_on_reopen,
                legacy_updated_by,
                created_at,
                legacy_updated_by,
                created_at,
            ),
        )

    if alert_rules_count == 0:
        for rule in seed_rules:
            _insert_seed_rule(*rule, legacy_updated_at)

    for rule in seed_rules:
        _insert_seed_rule(*rule, seeded_at)
    if 'temp' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN temp INTEGER DEFAULT 35')
    if 'fan_status' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN fan_status TEXT DEFAULT "ok"')
    if 'psu_status' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN psu_status TEXT DEFAULT "redundant"')
    if 'sys_name' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN sys_name TEXT')
    if 'sys_location' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN sys_location TEXT')
    if 'sys_contact' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN sys_contact TEXT')

    # Migration for scripts table
    script_columns = _table_columns(cursor, 'scripts')
    if 'platform' not in script_columns:
        cursor.execute('ALTER TABLE scripts ADD COLUMN platform TEXT')
    if 'category' not in script_columns:
        cursor.execute('ALTER TABLE scripts ADD COLUMN category TEXT DEFAULT "custom"')

    # Migration for users table
    user_columns = _table_columns(cursor, 'users')
    if 'avatar_url' not in user_columns:
        cursor.execute('ALTER TABLE users ADD COLUMN avatar_url TEXT')
    if 'group_name' not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN group_name TEXT DEFAULT ''")
    if 'change_groups_json' not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN change_groups_json TEXT DEFAULT '[]'")
    if 'notification_channels' not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN notification_channels TEXT DEFAULT '{}'")
    if 'preferred_language' not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN preferred_language TEXT DEFAULT 'zh'")

    finding_columns = _table_columns(cursor, 'compliance_findings')
    if finding_columns:
        if 'owner' not in finding_columns:
            cursor.execute("ALTER TABLE compliance_findings ADD COLUMN owner TEXT DEFAULT ''")
        if 'note' not in finding_columns:
            cursor.execute("ALTER TABLE compliance_findings ADD COLUMN note TEXT DEFAULT ''")

    # Migration for interface_telemetry_raw table
    raw_columns = _table_columns(cursor, 'interface_telemetry_raw')
    if raw_columns:
        if 'in_pkts' not in raw_columns:
            cursor.execute('ALTER TABLE interface_telemetry_raw ADD COLUMN in_pkts INTEGER')
        if 'out_pkts' not in raw_columns:
            cursor.execute('ALTER TABLE interface_telemetry_raw ADD COLUMN out_pkts INTEGER')

    # Migration for interface_telemetry_1m table
    rollup_columns = _table_columns(cursor, 'interface_telemetry_1m')
    if rollup_columns:
        if 'in_pkts_sum' not in rollup_columns:
            cursor.execute('ALTER TABLE interface_telemetry_1m ADD COLUMN in_pkts_sum INTEGER DEFAULT 0')
        if 'out_pkts_sum' not in rollup_columns:
            cursor.execute('ALTER TABLE interface_telemetry_1m ADD COLUMN out_pkts_sum INTEGER DEFAULT 0')

    # Config drift detection results
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS config_drift_results (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        hostname TEXT,
        baseline_snapshot_id TEXT,
        current_snapshot_id TEXT,
        drift_status TEXT NOT NULL DEFAULT 'unknown',
        added_lines INTEGER DEFAULT 0,
        removed_lines INTEGER DEFAULT 0,
        changed_lines INTEGER DEFAULT 0,
        diff_summary TEXT DEFAULT '',
        checked_at TEXT NOT NULL,
        FOREIGN KEY (device_id) REFERENCES devices(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_config_drift_device ON config_drift_results(device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_config_drift_checked ON config_drift_results(checked_at)')

    # IP/VLAN resource management
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ip_subnets (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        network TEXT NOT NULL,
        prefix_len INTEGER NOT NULL,
        vlan_id INTEGER,
        vlan_name TEXT DEFAULT '',
        gateway TEXT DEFAULT '',
        description TEXT DEFAULT '',
        site TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        total_ips INTEGER DEFAULT 0,
        used_ips INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_ip_subnets_network ON ip_subnets(network, prefix_len)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ip_addresses (
        id TEXT PRIMARY KEY,
        subnet_id TEXT NOT NULL,
        address TEXT NOT NULL,
        hostname TEXT DEFAULT '',
        device_id TEXT DEFAULT '',
        interface_name TEXT DEFAULT '',
        mac_address TEXT DEFAULT '',
        device_type TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        description TEXT DEFAULT '',
        last_seen TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (subnet_id) REFERENCES ip_subnets(id)
    )
    ''')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_ip_addr_unique ON ip_addresses(subnet_id, address)')

    ip_addr_cols = _table_columns(cursor, 'ip_addresses')
    if 'device_type' not in ip_addr_cols:
        cursor.execute("ALTER TABLE ip_addresses ADD COLUMN device_type TEXT DEFAULT ''")

    # Capacity planning snapshots
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS capacity_snapshots (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        hostname TEXT DEFAULT '',
        interface_name TEXT DEFAULT '',
        snapshot_date TEXT NOT NULL,
        avg_in_util REAL DEFAULT 0,
        avg_out_util REAL DEFAULT 0,
        peak_in_util REAL DEFAULT 0,
        peak_out_util REAL DEFAULT 0,
        bandwidth_mbps REAL DEFAULT 0,
        cpu_avg REAL DEFAULT 0,
        memory_avg REAL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (device_id) REFERENCES devices(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_capacity_snap_device_date ON capacity_snapshots(device_id, snapshot_date)')

    # Physical Asset Management
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS physical_assets (
        id TEXT PRIMARY KEY,
        asset_type TEXT NOT NULL DEFAULT 'server',
        asset_tag TEXT DEFAULT '',
        serial_number TEXT DEFAULT '',
        vendor TEXT DEFAULT '',
        model TEXT DEFAULT '',
        hostname TEXT DEFAULT '',
        datacenter TEXT DEFAULT '',
        rack TEXT DEFAULT '',
        rack_unit TEXT DEFAULT '',
        management_ip TEXT DEFAULT '',
        business_ip TEXT DEFAULT '',
        device_role TEXT DEFAULT '',
        vlan TEXT DEFAULT '',
        uplink_switch TEXT DEFAULT '',
        uplink_port TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        purchase_date TEXT DEFAULT '',
        warranty_expiry TEXT DEFAULT '',
        department TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_tag ON physical_assets(asset_tag) WHERE asset_tag != ''")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_asset_type ON physical_assets(asset_type)')

    ensure_column('physical_assets', 'vlan', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'uplink_switch', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'uplink_port', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'lifecycle_status', "TEXT DEFAULT 'staging'")
    ensure_column('physical_assets', 'platform', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'connection_method', "TEXT DEFAULT 'ssh'")
    ensure_column('physical_assets', 'username', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'password', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'normal_username', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'normal_password', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'admin_username', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'admin_password', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'enable_password', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'auth_model', "TEXT DEFAULT 'single'")
    ensure_column('physical_assets', 'normal_password_last_rotated', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'normal_password_expires_at', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'admin_password_last_rotated', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'admin_password_expires_at', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'enable_password_last_rotated', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'enable_password_expires_at', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'credential_source', "TEXT DEFAULT 'local'")
    ensure_column('physical_assets', 'vault_path', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'requires_strict_audit', "INTEGER DEFAULT 1")
    ensure_column('physical_assets', 'snmp_community', "TEXT DEFAULT 'public'")
    ensure_column('physical_assets', 'snmp_port', "INTEGER DEFAULT 161")
    ensure_column('physical_assets', 'management_port', "INTEGER DEFAULT 22")
    ensure_column('physical_assets', 'is_managed', "INTEGER DEFAULT 0")
    ensure_column('physical_assets', 'takeover_error', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'u_height', 'INTEGER NOT NULL DEFAULT 1')
    ensure_column('physical_assets', 'planned_start_u', 'INTEGER')
    ensure_column('physical_assets', 'device_category', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'power_watts', "INTEGER DEFAULT 0")

    ensure_column('devices', 'asset_id', 'TEXT')
    ensure_column('devices', 'vendor', "TEXT DEFAULT ''")
    ensure_column('devices', 'lifecycle_status', "TEXT DEFAULT 'staging'")
    ensure_column('devices', 'enable_password', "TEXT DEFAULT ''")
    ensure_column('devices', 'priv_username', "TEXT DEFAULT ''")
    ensure_column('devices', 'credential_source', "TEXT DEFAULT 'local'")
    ensure_column('devices', 'vault_path', "TEXT DEFAULT ''")
    ensure_column('devices', 'onboarding_status', "TEXT DEFAULT 'active'")
    ensure_column('devices', 'onboarding_updated_at', "TEXT DEFAULT ''")
    ensure_column('devices', 'password_last_rotated', "TEXT DEFAULT ''")
    ensure_column('devices', 'password_expires_at', "TEXT DEFAULT ''")
    ensure_column('devices', 'rotation_status', "TEXT DEFAULT ''")
    ensure_column('devices', 'device_category', "TEXT DEFAULT ''")
    ensure_column('devices', 'power_watts', "INTEGER DEFAULT 0")

    cursor.execute(
        '''
        UPDATE physical_assets
        SET normal_username = COALESCE(normal_username, username, '')
        WHERE LOWER(COALESCE(auth_model, 'single')) = 'dual'
          AND COALESCE(normal_username, '') = ''
          AND COALESCE(username, '') != ''
        '''
    )
    cursor.execute(
        '''
        UPDATE physical_assets
        SET power_watts = COALESCE((SELECT d.power_watts FROM devices d WHERE d.asset_id = physical_assets.id LIMIT 1), 0)
        WHERE COALESCE(power_watts, 0) = 0
        '''
    )
    cursor.execute(
        '''
        UPDATE physical_assets
        SET device_category = COALESCE((SELECT d.device_category FROM devices d WHERE d.asset_id = physical_assets.id LIMIT 1), '')
        WHERE COALESCE(device_category, '') = ''
        '''
    )

    # PAM access workflow state
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pam_access_requests (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        device_id TEXT DEFAULT '',
        requester_user_id TEXT DEFAULT '',
        requester_username TEXT DEFAULT '',
        access_level TEXT NOT NULL DEFAULT 'normal',
        reason TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        reviewer_username TEXT DEFAULT '',
        review_comment TEXT DEFAULT '',
        expires_at TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (asset_id) REFERENCES physical_assets(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pam_req_asset ON pam_access_requests(asset_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pam_req_status ON pam_access_requests(status)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pam_session_tokens (
        token TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        access_level TEXT NOT NULL DEFAULT 'normal',
        username TEXT DEFAULT '',
        expires_at TEXT NOT NULL,
        consumed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (request_id) REFERENCES pam_access_requests(id),
        FOREIGN KEY (asset_id) REFERENCES physical_assets(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pam_token_exp ON pam_session_tokens(expires_at)')

    # PAM Controlled Sessions
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pam_sessions (
        id TEXT PRIMARY KEY,
        request_id TEXT DEFAULT '',
        asset_id TEXT NOT NULL,
        device_id TEXT DEFAULT '',
        requester_username TEXT NOT NULL,
        access_level TEXT NOT NULL DEFAULT 'normal',
        login_username TEXT DEFAULT '',
        connect_method TEXT DEFAULT 'web',
        target_ip TEXT DEFAULT '',
        target_port INTEGER DEFAULT 22,
        status TEXT NOT NULL DEFAULT 'connecting',
        connected_at TEXT,
        closed_at TEXT,
        close_reason TEXT DEFAULT '',
        duration_seconds INTEGER DEFAULT 0,
        command_count INTEGER DEFAULT 0,
        recording_path TEXT DEFAULT '',
        risk_level TEXT DEFAULT 'low',
        risk_summary TEXT DEFAULT '',
        session_token TEXT UNIQUE,
        token_expires_at TEXT NOT NULL,
        token_consumed INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (asset_id) REFERENCES physical_assets(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pam_sessions_status ON pam_sessions(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pam_sessions_user ON pam_sessions(requester_username)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pam_sessions_asset ON pam_sessions(asset_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pam_sessions_created ON pam_sessions(created_at)')

    pam_req_cols = _table_columns(cursor, 'pam_access_requests')
    if pam_req_cols and 'session_id' not in pam_req_cols:
        cursor.execute("ALTER TABLE pam_access_requests ADD COLUMN session_id TEXT DEFAULT ''")

    pam_ses_cols = _table_columns(cursor, 'pam_sessions')
    if pam_ses_cols and 'risk_level' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN risk_level TEXT DEFAULT 'low'")
    if pam_ses_cols and 'risk_summary' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN risk_summary TEXT DEFAULT ''")

    # Auto-link existing devices to matching assets
    unlinked = cursor.execute(
        "SELECT id, hostname, ip_address, sn, model, role, site, vendor, status, lifecycle_status FROM devices WHERE (asset_id IS NULL OR asset_id = '')"
    ).fetchall()
    if unlinked:
        for dev in unlinked:
            match = cursor.execute(
                "SELECT id FROM physical_assets WHERE asset_type='network_device' AND (hostname = ? OR management_ip = ?) LIMIT 1",
                (dev['hostname'], dev['ip_address'])
            ).fetchone()
            if match:
                cursor.execute('UPDATE devices SET asset_id = ? WHERE id = ?', (match['id'], dev['id']))
            else:
                asset_id = f"asset-{uuid.uuid4().hex[:12]}"
                now_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
                cursor.execute('''
                    INSERT INTO physical_assets (
                        id, asset_type, asset_tag, serial_number, vendor, model, hostname,
                        datacenter, rack, rack_unit, u_height, planned_start_u, management_ip, business_ip, device_role,
                        vlan, uplink_switch, uplink_port,
                        status, purchase_date, warranty_expiry, department, notes, created_at, updated_at, lifecycle_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    asset_id, 'network_device', '', dev['sn'] or '', dev['vendor'] or '',
                    dev['model'] or '', dev['hostname'] or '',
                    dev['site'] or '', '', '', 1, None,
                    dev['ip_address'] or '', '', dev['role'] or '',
                    '', '', '',
                    dev['status'] or 'active', '', '', '', '', now_str, now_str,
                    dev['lifecycle_status'] or 'staging'
                ))
                cursor.execute('UPDATE devices SET asset_id = ? WHERE id = ?', (asset_id, dev['id']))

    # Change Order / Ticket Management
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS change_orders (
        id TEXT PRIMARY KEY,
        order_number TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        order_type TEXT NOT NULL DEFAULT 'config_change',
        priority TEXT NOT NULL DEFAULT 'medium',
        status TEXT NOT NULL DEFAULT 'draft',
        requester_id TEXT DEFAULT '',
        requester_username TEXT DEFAULT '',
        approver_id TEXT DEFAULT '',
        approver_username TEXT DEFAULT '',
        target_devices_json TEXT DEFAULT '[]',
        commands_json TEXT DEFAULT '[]',
        rollback_plan TEXT DEFAULT '',
        risk_level TEXT DEFAULT 'low',
        scheduled_start TEXT DEFAULT '',
        scheduled_end TEXT DEFAULT '',
        authorization_exempt INTEGER NOT NULL DEFAULT 0,
        actual_start TEXT DEFAULT '',
        actual_end TEXT DEFAULT '',
        result_summary TEXT DEFAULT '',
        result_detail_json TEXT DEFAULT '{}',
        approval_token TEXT DEFAULT '',
        rejected_reason TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_change_orders_status ON change_orders(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_change_orders_created_at ON change_orders(created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_change_orders_requester ON change_orders(requester_username)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_change_orders_order_number ON change_orders(order_number)')
    
    ensure_column('change_orders', 'initial_reviewer_id', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'initial_reviewer_username', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'final_approver_id', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'final_approver_username', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'assigned_initial_reviewer_id', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'assigned_initial_reviewer_username', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'assigned_final_approver_id', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'assigned_final_approver_username', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'command_template_json', "TEXT DEFAULT '{}' ")
    ensure_column('change_orders', 'control_sheet_json', "TEXT DEFAULT '{}'")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS change_order_control_sheet_attachments (
        id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_name TEXT NOT NULL,
        file_size INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (order_id) REFERENCES change_orders(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_co_attachments_order ON change_order_control_sheet_attachments(order_id)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS change_order_bookmarks (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        order_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(user_id, order_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS change_order_templates (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        order_type TEXT NOT NULL DEFAULT 'config_change',
        priority TEXT NOT NULL DEFAULT 'medium',
        target_devices_json TEXT DEFAULT '[]',
        commands_json TEXT DEFAULT '[]',
        rollback_plan TEXT DEFAULT '',
        risk_level TEXT DEFAULT 'low',
        creator_id TEXT NOT NULL,
        creator_username TEXT NOT NULL,
        source_order_id TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT '',
        updated_at TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS inspection_schedules (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cron_expr TEXT NOT NULL,
        scope_type TEXT NOT NULL DEFAULT 'all',
        scope_filter TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        created_by TEXT DEFAULT 'system',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_run_at TEXT
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_inspection_schedules_enabled ON inspection_schedules(enabled)')

    for col, default in [('scheduled_at', "''"), ('expires_at', "''"), ('description', "''"), ('check_items', "'[]'")]:
        ensure_column('inspection_schedules', col, f"TEXT DEFAULT {default}")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS inspection_runs (
        id TEXT PRIMARY KEY,
        schedule_id TEXT,
        trigger_type TEXT NOT NULL DEFAULT 'manual',
        scope_type TEXT NOT NULL DEFAULT 'all',
        scope_filter TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        started_at TEXT NOT NULL,
        completed_at TEXT,
        total_devices INTEGER DEFAULT 0,
        success_count INTEGER DEFAULT 0,
        failed_count INTEGER DEFAULT 0,
        unreachable_count INTEGER DEFAULT 0,
        healthy_count INTEGER DEFAULT 0,
        warning_count INTEGER DEFAULT 0,
        critical_count INTEGER DEFAULT 0,
        avg_health_score REAL DEFAULT 0,
        summary_json TEXT DEFAULT '{}',
        created_by TEXT DEFAULT 'system',
        FOREIGN KEY (schedule_id) REFERENCES inspection_schedules(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_inspection_runs_started_at ON inspection_runs(started_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_inspection_runs_status ON inspection_runs(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_inspection_runs_schedule_id ON inspection_runs(schedule_id)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS inspection_results (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        hostname TEXT DEFAULT '',
        ip_address TEXT DEFAULT '',
        platform TEXT DEFAULT '',
        role TEXT DEFAULT '',
        site TEXT DEFAULT '',
        ping_ok INTEGER DEFAULT 0,
        ping_latency_ms REAL,
        ssh_ok INTEGER DEFAULT 0,
        ssh_error TEXT DEFAULT '',
        health_score INTEGER,
        health_status TEXT DEFAULT 'unknown',
        cpu_usage REAL,
        memory_usage REAL,
        temperature REAL,
        fan_status TEXT DEFAULT '',
        psu_status TEXT DEFAULT '',
        interface_total INTEGER DEFAULT 0,
        interface_up INTEGER DEFAULT 0,
        interface_down INTEGER DEFAULT 0,
        interface_flapping INTEGER DEFAULT 0,
        interface_high_util INTEGER DEFAULT 0,
        interface_errors INTEGER DEFAULT 0,
        open_alerts INTEGER DEFAULT 0,
        critical_alerts INTEGER DEFAULT 0,
        compliance_status TEXT DEFAULT 'unknown',
        compliance_findings INTEGER DEFAULT 0,
        findings_json TEXT DEFAULT '[]',
        metrics_json TEXT DEFAULT '{}',
        checked_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES inspection_runs(id),
        FOREIGN KEY (device_id) REFERENCES devices(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_inspection_results_run_id ON inspection_results(run_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_inspection_results_device_id ON inspection_results(device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_inspection_results_health_status ON inspection_results(health_status)')

    for col, default in [('raw_outputs_json', "'{}'"), ('analysis_json', "'[]'")]:
        ensure_column('inspection_results', col, f"TEXT DEFAULT {default}")

    ensure_column('inspection_results', 'correlated_risks_json', "TEXT DEFAULT '[]'")
    ensure_column('inspection_results', 'exception_type', "TEXT DEFAULT ''")
    ensure_column('inspection_runs', 'analysis_summary_json', "TEXT DEFAULT '{}'")

    # Scheduled Jobs
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS scheduled_jobs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        job_type TEXT NOT NULL DEFAULT 'cron',
        action_type TEXT NOT NULL DEFAULT 'command',
        cron_expr TEXT DEFAULT '',
        scheduled_at TEXT DEFAULT '',
        device_scope TEXT NOT NULL DEFAULT 'all',
        device_filter TEXT DEFAULT '',
        commands TEXT DEFAULT '',
        script_id TEXT DEFAULT '',
        is_config INTEGER DEFAULT 0,
        config_reason TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'pending',
        approved_by TEXT DEFAULT '',
        approved_at TEXT DEFAULT '',
        last_run_at TEXT DEFAULT '',
        last_run_status TEXT DEFAULT '',
        run_count INTEGER DEFAULT 0,
        use_admin_creds INTEGER DEFAULT 0,
        created_by TEXT DEFAULT 'system',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_job_type ON scheduled_jobs(job_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_status ON scheduled_jobs(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_enabled ON scheduled_jobs(enabled)')

    ensure_column('scheduled_jobs', 'use_admin_creds', 'INTEGER DEFAULT 0')

    # Tag System
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tag_definitions (
        id TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        value TEXT NOT NULL,
        label TEXT NOT NULL,
        label_zh TEXT DEFAULT '',
        color TEXT DEFAULT '',
        icon TEXT DEFAULT '',
        description TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        built_in INTEGER DEFAULT 0,
        created_at TEXT DEFAULT '',
        UNIQUE(category, value)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_definitions_category ON tag_definitions(category)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS device_tags (
        device_id TEXT NOT NULL,
        tag_id TEXT NOT NULL,
        created_at TEXT DEFAULT '',
        created_by TEXT DEFAULT '',
        PRIMARY KEY (device_id, tag_id),
        FOREIGN KEY (device_id) REFERENCES devices(id),
        FOREIGN KEY (tag_id) REFERENCES tag_definitions(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_device_tags_device_id ON device_tags(device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_device_tags_tag_id ON device_tags(tag_id)')

    # Rack Management
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS racks (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        datacenter TEXT DEFAULT '',
        room TEXT DEFAULT '',
        row TEXT DEFAULT '',
        total_u INTEGER NOT NULL DEFAULT 42,
        description TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_racks_name_dc ON racks(name, datacenter)')
    ensure_column('racks', 'power_capacity_watts', "INTEGER DEFAULT 0")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS device_types (
        id TEXT PRIMARY KEY,
        model TEXT NOT NULL,
        vendor TEXT DEFAULT '',
        u_height INTEGER NOT NULL DEFAULT 1,
        device_role TEXT NOT NULL DEFAULT 'switch',
        is_full_depth INTEGER DEFAULT 1,
        description TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_device_types_model_vendor ON device_types(model, vendor)')
    ensure_column('device_types', 'power_watts', "INTEGER DEFAULT 0")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rack_devices (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        rack_id TEXT NOT NULL,
        device_type_id TEXT NOT NULL,
        start_u INTEGER NOT NULL,
        position TEXT NOT NULL DEFAULT 'front',
        status TEXT NOT NULL DEFAULT 'active',
        serial_number TEXT DEFAULT '',
        asset_id TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (rack_id) REFERENCES racks(id),
        FOREIGN KEY (device_type_id) REFERENCES device_types(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_rack_devices_rack_id ON rack_devices(rack_id)')

    # Inspection Items
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS inspection_items (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        name_zh TEXT NOT NULL,
        category TEXT NOT NULL,
        check_key TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT '',
        method TEXT DEFAULT 'SNMP',
        command TEXT DEFAULT '',
        script_id TEXT DEFAULT '',
        warning_threshold REAL,
        critical_threshold REAL,
        vendor TEXT DEFAULT '',
        oid TEXT DEFAULT '',
        use_admin_creds INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    ''')
        
    for col, dtype in [('script_id', "TEXT DEFAULT ''"), ('warning_threshold', 'REAL'), ('critical_threshold', 'REAL'), ('method', "TEXT DEFAULT 'SNMP'"), ('command', "TEXT DEFAULT ''"),
                       ('parse_type', "TEXT DEFAULT 'numeric'"),
                       ('textfsm_template', "TEXT DEFAULT ''"),
                       ('parse_field', "TEXT DEFAULT ''"),
                       ('parse_filter', "TEXT DEFAULT ''"),
                       ('fallback_regex', "TEXT DEFAULT ''"),
                       ('enabled', 'INTEGER DEFAULT 1'),
                       ('use_admin_creds', 'INTEGER DEFAULT 0'),
                       ('expected_value', "TEXT DEFAULT ''")]:
        ensure_column('inspection_items', col, dtype)
        
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_inspection_items_cat ON inspection_items(category)')

    # Inspection Correlation Rules
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS inspection_correlation_rules (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        name_zh TEXT NOT NULL,
        description TEXT DEFAULT '',
        severity TEXT NOT NULL DEFAULT 'warning',
        suggestion TEXT DEFAULT '',
        conditions_json TEXT NOT NULL DEFAULT '[]',
        enabled INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_correlation_rules_enabled ON inspection_correlation_rules(enabled)')

    correlation_rules_seed = [
        (
            'rule_l2_loop',
            'l2_loop_risk', '二层环路风险',
            'CPU 高负载 + 接口错误激增 + 接口抖动，疑似二层环路或广播风暴。',
            'critical',
            '立即检查 STP 状态，执行 show spanning-tree 排查环路；检查最近的拓扑变更和广播流量。',
            json.dumps([
                {'metric': 'cpu_util', 'op': '>', 'value': 80},
                {'metric': 'intf_errors', 'op': '>', 'value': 100},
                {'metric': 'intf_flapping', 'op': '>', 'value': 3},
            ], ensure_ascii=False),
        ),
        (
            'rule_mem_leak',
            'memory_leak_risk', '内存泄漏风险',
            '内存利用率超阈值且较上次巡检明显增长，可能存在内存泄漏。',
            'warning',
            '检查内存占用进程，关注关键服务的内存增长趋势，必要时计划重启。',
            json.dumps([
                {'metric': 'mem_util', 'op': '>', 'value': 85},
                {'metric': 'mem_util_change_pct', 'op': '>', 'value': 10},
            ], ensure_ascii=False),
        ),
        (
            'rule_uplink_degrade',
            'uplink_degradation', '上行链路劣化风险',
            '上行接口利用率高且错误率上升，链路质量可能劣化。',
            'warning',
            '检查上行链路光衰、CRC 错误，考虑扩容或切换备份链路。',
            json.dumps([
                {'metric': 'uplink_util', 'op': '>', 'value': 70},
                {'metric': 'uplink_error_rate', 'op': '>', 'value': 0.1},
            ], ensure_ascii=False),
        ),
        (
            'rule_routing_unstable',
            'routing_protocol_unstable', '路由协议不稳定',
            'BGP 与 OSPF 邻居同时出现 Down 状态，路由协议不稳定。',
            'critical',
            '检查路由协议配置 and 上联链路质量，确认是否存在批量邻居中断。',
            json.dumps([
                {'metric': 'bgp_neighbor_down', 'op': '>', 'value': 0},
                {'metric': 'ospf_neighbor_down', 'op': '>', 'value': 0},
            ], ensure_ascii=False),
        ),
        (
            'rule_overheat',
            'device_overheat_risk', '设备过热风险',
            '设备温度偏高且 CPU 持续高负载，存在过热风险。',
            'warning',
            '检查机房空调、设备散热风扇运行状态，必要时进行物理巡检。',
            json.dumps([
                {'metric': 'temperature', 'op': '>', 'value': 60},
                {'metric': 'cpu_util', 'op': '>', 'value': 70},
            ], ensure_ascii=False),
        ),
    ]
    for rule_id, name, name_zh, description, severity, suggestion, conditions_json in correlation_rules_seed:
        if _USE_PG:
            cursor.execute(
                '''INSERT INTO inspection_correlation_rules
                    (id, name, name_zh, description, severity, suggestion, conditions_json, enabled, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
                   ON CONFLICT (id) DO NOTHING''',
                (rule_id, name, name_zh, description, severity, suggestion, conditions_json,
                 _beijing_now_iso(), _beijing_now_iso())
            )
        else:
            cursor.execute(
                '''INSERT OR IGNORE INTO inspection_correlation_rules
                    (id, name, name_zh, description, severity, suggestion, conditions_json, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)''',
                (rule_id, name, name_zh, description, severity, suggestion, conditions_json,
                 _beijing_now_iso(), _beijing_now_iso())
            )

    ensure_column('inspection_results', 'metrics_json', "TEXT DEFAULT '{}'")

    now = _beijing_now_iso()

    cursor.executemany(
        'INSERT INTO scripts (id, name, content, description, platform, category) VALUES (?,?,?,?,?,?) ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content, description = EXCLUDED.description',
        std_scripts
    )

    insp_script_ids = [
        'insp_cisco_ios_full', 'insp_cisco_nxos_full',
        'insp_huawei_vrp_full', 'insp_huawei_vrpv8_full',
        'insp_h3c_comware_full', 'insp_juniper_junos_full', 'insp_arista_eos_full',
    ]
    for sid in insp_script_ids:
        cursor.execute(
            "UPDATE scripts SET script_type=?, status=?, author=?, "
            "submitter_name=?, approver_username=?, "
            "created_at=COALESCE(NULLIF(created_at, ''), ?), "
            "updated_at=? "
            "WHERE id=?",
            ('cli', 'released', 'system', 'system', 'system', now, now, sid)
        )

    default_items = get_default_items(now)
    network_items_v2 = _build_network_inspection_items(now)
    
    if _USE_PG:
        pg_sql = '''INSERT INTO inspection_items 
                    (id, name, name_zh, category, check_key, description, method, command, script_id, warning_threshold, critical_threshold, vendor, oid, created_at, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name, name_zh = EXCLUDED.name_zh, category = EXCLUDED.category,
                    check_key = EXCLUDED.check_key, description = EXCLUDED.description,
                    method = EXCLUDED.method, command = EXCLUDED.command, script_id = EXCLUDED.script_id,
                    warning_threshold = EXCLUDED.warning_threshold, critical_threshold = EXCLUDED.critical_threshold,
                    vendor = EXCLUDED.vendor, oid = EXCLUDED.oid, updated_at = EXCLUDED.updated_at'''
        cursor.executemany(pg_sql, default_items)
    else:
        for item in default_items:
            cursor.execute('''
                INSERT OR REPLACE INTO inspection_items 
                (id, name, name_zh, category, check_key, description, method, command, script_id, warning_threshold, critical_threshold, vendor, oid, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', item)

    network_sql_columns = (
        'id, name, name_zh, category, check_key, description, method, command, script_id, '
        'warning_threshold, critical_threshold, vendor, oid, created_at, updated_at, '
        'parse_type, textfsm_template, parse_field, parse_filter, fallback_regex, enabled'
    )
    if _USE_PG:
        pg_net_sql = (
            f'INSERT INTO inspection_items ({network_sql_columns}) '
            f'VALUES (' + ','.join(['%s'] * 21) + ') '
            'ON CONFLICT (id) DO UPDATE SET '
            'name=EXCLUDED.name, name_zh=EXCLUDED.name_zh, category=EXCLUDED.category, '
            'check_key=EXCLUDED.check_key, description=EXCLUDED.description, '
            'method=EXCLUDED.method, command=EXCLUDED.command, script_id=EXCLUDED.script_id, '
            'warning_threshold=EXCLUDED.warning_threshold, critical_threshold=EXCLUDED.critical_threshold, '
            'vendor=EXCLUDED.vendor, oid=EXCLUDED.oid, updated_at=EXCLUDED.updated_at, '
            'parse_type=EXCLUDED.parse_type, textfsm_template=EXCLUDED.textfsm_template, '
            'parse_field=EXCLUDED.parse_field, parse_filter=EXCLUDED.parse_filter, '
            'fallback_regex=EXCLUDED.fallback_regex, enabled=EXCLUDED.enabled'
        )
        cursor.executemany(pg_net_sql, network_items_v2)
    else:
        sqlite_net_sql = (
            f'INSERT OR REPLACE INTO inspection_items ({network_sql_columns}) '
            f'VALUES (' + ','.join(['?'] * 21) + ')'
        )
        for item in network_items_v2:
            cursor.execute(sqlite_net_sql, item)

    for item_id, expected in compliance_expected_values.items():
        if _USE_PG:
            cursor.execute(
                'UPDATE inspection_items SET expected_value = %s WHERE id = %s AND (expected_value IS NULL OR expected_value = %s)',
                (expected, item_id, '')
            )
        else:
            cursor.execute(
                'UPDATE inspection_items SET expected_value = ? WHERE id = ? AND (expected_value IS NULL OR expected_value = ?)',
                (expected, item_id, '')
            )

    admin_row = cursor.execute("SELECT id, password FROM users WHERE username = 'admin'").fetchone()
    if not admin_row:
        hashed = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
        if _USE_PG:
            cursor.execute(
                "INSERT INTO users (id, username, password, role, status, created_at) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (username) DO NOTHING",
                (str(uuid.uuid4()), "admin", hashed, "Administrator", "active", now)
            )
        else:
            cursor.execute(
                "INSERT OR IGNORE INTO users (id, username, password, role, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "admin", hashed, "Administrator", "active", now)
            )
        logger.info("[Database] Default admin user created (admin/admin)")
    else:
        pwd = admin_row['password'] if hasattr(admin_row, '__getitem__') else admin_row[1]
        if not pwd or (not pwd.startswith('$2b$') and not pwd.startswith('$2a$') and pwd != 'admin'):
            hashed = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
            if _USE_PG:
                cursor.execute("UPDATE users SET password = %s WHERE username = 'admin'", (hashed,))
            else:
                cursor.execute("UPDATE users SET password = ? WHERE username = 'admin'", (hashed,))
            logger.info("[Database] Corrupted admin password auto-repaired to default (admin/admin)")
