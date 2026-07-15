"""Enterprise CMDB/IPAM Phase 0-6 compatibility migration.

The migration is additive on SQLite. On PostgreSQL it also converts the
normalized network columns to native CIDR/INET after quarantining invalid
legacy values as NULL. Legacy text columns remain available for rollback.
"""

VERSION = 8
NAME = "enterprise_cmdb_ipam_phase0_phase6"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            (table,),
        )
        return {row[0] for row in cursor.fetchall()}
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _ensure_columns(cursor, table: str, definitions: list[tuple[str, str]], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    for name, definition in definitions:
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _create_enterprise_tables(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS discovery_runs (
            id TEXT PRIMARY KEY, run_type TEXT NOT NULL DEFAULT 'network',
            status TEXT NOT NULL DEFAULT 'queued', requested_by TEXT DEFAULT 'system',
            scope_json TEXT DEFAULT '{}', started_at TEXT NOT NULL,
            completed_at TEXT, summary_json TEXT DEFAULT '{}'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS discovery_observations (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, source_device_id TEXT,
            source_type TEXT NOT NULL, observed_type TEXT NOT NULL,
            observed_key TEXT NOT NULL, payload_json TEXT DEFAULT '{}',
            confidence REAL DEFAULT 0.5, first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL, is_active INTEGER DEFAULT 1,
            FOREIGN KEY (run_id) REFERENCES discovery_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (source_device_id) REFERENCES devices(id) ON DELETE SET NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation_runs (
            id TEXT PRIMARY KEY, discovery_run_id TEXT,
            status TEXT NOT NULL DEFAULT 'open', requested_by TEXT DEFAULT 'system',
            started_at TEXT NOT NULL, completed_at TEXT,
            total_findings INTEGER DEFAULT 0, open_findings INTEGER DEFAULT 0,
            summary_json TEXT DEFAULT '{}',
            FOREIGN KEY (discovery_run_id) REFERENCES discovery_runs(id) ON DELETE SET NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation_findings (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, observation_id TEXT,
            finding_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
            risk_level TEXT NOT NULL DEFAULT 'medium', target_type TEXT,
            target_id TEXT, tenant_id TEXT, site_id TEXT,
            observed_json TEXT DEFAULT '{}', current_json TEXT DEFAULT '{}',
            proposed_json TEXT DEFAULT '{}', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, resolved_at TEXT, resolved_by TEXT,
            FOREIGN KEY (run_id) REFERENCES reconciliation_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (observation_id) REFERENCES discovery_observations(id) ON DELETE SET NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation_actions (
            id TEXT PRIMARY KEY, finding_id TEXT NOT NULL, action_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', requested_by TEXT NOT NULL,
            approved_by TEXT, payload_json TEXT DEFAULT '{}', result_json TEXT DEFAULT '{}',
            error_message TEXT DEFAULT '', created_at TEXT NOT NULL, applied_at TEXT,
            FOREIGN KEY (finding_id) REFERENCES reconciliation_findings(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_steps (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL, step_name TEXT NOT NULL,
            step_order INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'queued',
            started_at TEXT, finished_at TEXT, error_message TEXT DEFAULT '',
            result_json TEXT DEFAULT '{}',
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_targets (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
            target_type TEXT NOT NULL DEFAULT 'device', target_id TEXT NOT NULL,
            site_id TEXT, vendor TEXT, status TEXT NOT NULL DEFAULT 'queued',
            attempt_count INTEGER DEFAULT 0, started_at TEXT, finished_at TEXT,
            error_message TEXT DEFAULT '', result_json TEXT DEFAULT '{}',
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_artifacts (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL, artifact_type TEXT NOT NULL,
            name TEXT NOT NULL, uri TEXT NOT NULL, metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_events (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL, event_type TEXT NOT NULL,
            severity TEXT DEFAULT 'info', message TEXT NOT NULL,
            details_json TEXT DEFAULT '{}', created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_resource_scopes (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, resource_type TEXT NOT NULL,
            scope_type TEXT NOT NULL, scope_id TEXT NOT NULL DEFAULT '',
            actions_json TEXT DEFAULT '[]', created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_discovery_runs_status ON discovery_runs(status)",
        "CREATE INDEX IF NOT EXISTS idx_discovery_observations_run ON discovery_observations(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_discovery_observations_key ON discovery_observations(observed_type, observed_key)",
        "CREATE INDEX IF NOT EXISTS idx_reconciliation_findings_run_status ON reconciliation_findings(run_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_reconciliation_findings_type ON reconciliation_findings(finding_type)",
        "CREATE INDEX IF NOT EXISTS idx_reconciliation_actions_finding ON reconciliation_actions(finding_id)",
        "CREATE INDEX IF NOT EXISTS idx_job_steps_job ON job_steps(job_id, step_order)",
        "CREATE INDEX IF NOT EXISTS idx_job_targets_job_status ON job_targets(job_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_job_targets_device_lock ON job_targets(target_type, target_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_job_events_job_time ON job_events(job_id, created_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_resource_scope ON user_resource_scopes(user_id, resource_type, scope_type, scope_id)",
    ]
    for statement in indexes:
        cursor.execute(statement)


def _convert_native_network_types(cursor) -> None:
    # Each invalid historical value is retained in the legacy prefix/address
    # column and represented as NULL in the normalized native column.
    cursor.execute("""
        DO $$
        DECLARE item RECORD; candidate TEXT;
        BEGIN
          FOR item IN SELECT id, prefix, prefix_cidr::text AS normalized FROM prefixes LOOP
            candidate := COALESCE(NULLIF(item.normalized, ''), NULLIF(item.prefix, ''));
            BEGIN
              IF candidate IS NOT NULL THEN
                PERFORM candidate::cidr;
                UPDATE prefixes SET prefix_cidr = candidate::cidr WHERE id = item.id;
              END IF;
            EXCEPTION WHEN OTHERS THEN
              UPDATE prefixes SET prefix_cidr = NULL WHERE id = item.id;
            END;
          END LOOP;
        END $$
    """)
    cursor.execute("ALTER TABLE prefixes ALTER COLUMN prefix_cidr DROP DEFAULT")
    cursor.execute("ALTER TABLE prefixes ALTER COLUMN prefix_cidr TYPE CIDR USING NULLIF(prefix_cidr::text, '')::cidr")

    cursor.execute("""
        DO $$
        DECLARE item RECORD; candidate TEXT;
        BEGIN
          FOR item IN SELECT id, address, address_inet::text AS normalized FROM ip_addresses LOOP
            candidate := COALESCE(NULLIF(item.normalized, ''), NULLIF(item.address, ''));
            BEGIN
              IF candidate IS NOT NULL THEN
                PERFORM candidate::inet;
                UPDATE ip_addresses SET address_inet = candidate::inet WHERE id = item.id;
              END IF;
            EXCEPTION WHEN OTHERS THEN
              UPDATE ip_addresses SET address_inet = NULL WHERE id = item.id;
            END;
          END LOOP;
        END $$
    """)
    cursor.execute("ALTER TABLE ip_addresses ALTER COLUMN address_inet DROP DEFAULT")
    cursor.execute("ALTER TABLE ip_addresses ALTER COLUMN address_inet TYPE INET USING NULLIF(address_inet::text, '')::inet")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prefixes_cidr_gist ON prefixes USING GIST(prefix_cidr inet_ops)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ip_addresses_inet ON ip_addresses(tenant_id, vrf_id, address_inet)")
    cursor.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM prefixes
            WHERE prefix_cidr IS NOT NULL
            GROUP BY COALESCE(tenant_id, ''), COALESCE(vrf_id, ''), COALESCE(site_id, ''), prefix_cidr
            HAVING COUNT(*) > 1
          ) THEN
            CREATE UNIQUE INDEX IF NOT EXISTS uq_prefixes_scope_cidr
              ON prefixes(COALESCE(tenant_id, ''), COALESCE(vrf_id, ''), COALESCE(site_id, ''), prefix_cidr);
          END IF;
        END $$
    """)
    cursor.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM ip_addresses
            WHERE address_inet IS NOT NULL
              AND COALESCE(status, 'active') NOT IN ('released', 'available')
            GROUP BY COALESCE(tenant_id, ''), COALESCE(vrf_id, ''), address_inet
            HAVING COUNT(*) > 1
          ) THEN
            CREATE UNIQUE INDEX IF NOT EXISTS uq_ip_addresses_scope_active
              ON ip_addresses(COALESCE(tenant_id, ''), COALESCE(vrf_id, ''), address_inet)
              WHERE address_inet IS NOT NULL
                AND COALESCE(status, 'active') NOT IN ('released', 'available');
          END IF;
          IF NOT EXISTS (SELECT 1 FROM prefixes WHERE prefix_cidr IS NULL) THEN
            ALTER TABLE prefixes ALTER COLUMN prefix_cidr SET NOT NULL;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM ip_addresses WHERE address_inet IS NULL) THEN
            ALTER TABLE ip_addresses ALTER COLUMN address_inet SET NOT NULL;
          END IF;
        END $$
    """)


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_columns(cursor, "jobs", [
        ("job_type", "TEXT DEFAULT 'generic'"), ("created_by", "TEXT DEFAULT 'system'"),
        ("started_at", "TEXT"), ("finished_at", "TEXT"), ("updated_at", "TEXT"),
        ("progress", "INTEGER DEFAULT 0"), ("total_targets", "INTEGER DEFAULT 0"),
        ("success_count", "INTEGER DEFAULT 0"), ("failed_count", "INTEGER DEFAULT 0"),
        ("cancel_requested", "INTEGER DEFAULT 0"), ("error_summary", "TEXT DEFAULT ''"),
        ("concurrency_limit", "INTEGER DEFAULT 5"), ("retry_limit", "INTEGER DEFAULT 0"),
        ("timeout_seconds", "INTEGER DEFAULT 300"), ("scope_json", "TEXT DEFAULT '{}'")
    ], use_pg)
    _ensure_columns(cursor, "audit_events", [
        ("request_id", "TEXT DEFAULT ''"), ("before_json", "TEXT DEFAULT '{}'"),
        ("after_json", "TEXT DEFAULT '{}'")
    ], use_pg)
    _ensure_columns(cursor, "users", [
        ("scope_type", "TEXT DEFAULT 'global'"), ("scope_ids_json", "TEXT DEFAULT '[]'")
    ], use_pg)
    _ensure_columns(cursor, "ip_addresses", [
        ("tenant_id", "TEXT DEFAULT 'tenant-default'"), ("site_id", "TEXT DEFAULT ''"),
        ("released_at", "TEXT"), ("available_after", "TEXT"), ("expires_at", "TEXT"),
        ("purpose", "TEXT DEFAULT ''"), ("requested_by", "TEXT DEFAULT ''"),
        ("source_type", "TEXT DEFAULT 'manual'"), ("source_ref", "TEXT DEFAULT ''"),
        ("last_confirmed_at", "TEXT"), ("confirmed_by", "TEXT DEFAULT ''")
    ], use_pg)
    fact_fields = [
        ("source_type", "TEXT DEFAULT 'manual'"), ("source_ref", "TEXT DEFAULT ''"),
        ("confidence", "REAL DEFAULT 1.0"), ("last_confirmed_at", "TEXT"),
        ("last_observed_at", "TEXT"), ("confirmed_by", "TEXT DEFAULT ''")
    ]
    for table in ("physical_assets", "devices", "interfaces", "prefixes"):
        _ensure_columns(cursor, table, fact_fields, use_pg)

    _create_enterprise_tables(cursor)
    if use_pg:
        cursor.execute("ALTER TABLE vrfs DROP CONSTRAINT IF EXISTS vrfs_vrf_name_key")
        cursor.execute("""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM vlans GROUP BY site_id, vlan_id HAVING COUNT(*) > 1) THEN
                CREATE UNIQUE INDEX IF NOT EXISTS uq_vlans_site_vlan ON vlans(site_id, vlan_id);
              END IF;
              IF NOT EXISTS (SELECT 1 FROM vrfs GROUP BY tenant_id, vrf_name HAVING COUNT(*) > 1) THEN
                CREATE UNIQUE INDEX IF NOT EXISTS uq_vrfs_tenant_name ON vrfs(tenant_id, vrf_name);
              END IF;
              IF NOT EXISTS (
                SELECT 1 FROM devices WHERE asset_id IS NOT NULL AND asset_id <> ''
                GROUP BY asset_id HAVING COUNT(*) > 1
              ) THEN
                CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_asset_id
                  ON devices(asset_id) WHERE asset_id IS NOT NULL AND asset_id <> '';
              END IF;
            END $$
        """)
        _convert_native_network_types(cursor)
    else:
        duplicate_checks = [
            ("SELECT 1 FROM vlans GROUP BY site_id, vlan_id HAVING COUNT(*) > 1 LIMIT 1", "CREATE UNIQUE INDEX IF NOT EXISTS uq_vlans_site_vlan ON vlans(site_id, vlan_id)"),
            ("SELECT 1 FROM vrfs GROUP BY tenant_id, vrf_name HAVING COUNT(*) > 1 LIMIT 1", "CREATE UNIQUE INDEX IF NOT EXISTS uq_vrfs_tenant_name ON vrfs(tenant_id, vrf_name)"),
            ("SELECT 1 FROM devices WHERE asset_id IS NOT NULL AND asset_id <> '' GROUP BY asset_id HAVING COUNT(*) > 1 LIMIT 1", "CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_asset_id ON devices(asset_id) WHERE asset_id IS NOT NULL AND asset_id <> ''"),
            ("SELECT 1 FROM ip_addresses WHERE COALESCE(status, 'active') NOT IN ('released', 'available') GROUP BY tenant_id, vrf_id, address_inet HAVING COUNT(*) > 1 LIMIT 1", "CREATE UNIQUE INDEX IF NOT EXISTS uq_ip_addresses_scope_active ON ip_addresses(tenant_id, vrf_id, address_inet) WHERE COALESCE(status, 'active') NOT IN ('released', 'available')"),
        ]
        for check_sql, index_sql in duplicate_checks:
            if cursor.execute(check_sql).fetchone() is None:
                cursor.execute(index_sql)
