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

        # The normal service bootstrap must not replay destructive legacy
        # imports. The private helper keeps its historical default for
        # explicit recovery/test invocations.
        _init_db_logic(conn, allow_legacy_import=False)
        conn.commit()

        # Apply versioned, tracked schema migrations on top of the baseline.
        try:
            from .migrations import build_migration_plan, run_migrations
            applied = run_migrations(conn, _USE_PG, strict_history=True)
            if applied:
                logger.info("Applied %d pending schema migration(s).", applied)
            migration_plan = build_migration_plan(conn, _USE_PG)
            if not migration_plan.safe_for(strict_history=True):
                raise RuntimeError(
                    "Database migration history is unsafe: "
                    f"unknown={migration_plan.unknown_applied_versions}, "
                    f"name_drift={migration_plan.name_drift}"
                )
            if migration_plan.pending_versions:
                raise RuntimeError(
                    "Database migrations are incomplete; pending versions: "
                    f"{migration_plan.pending_versions}"
                )
        except Exception as mig_exc:
            logger.error("Schema migration runner error: %s", mig_exc, exc_info=True)
            raise

        _db_initialized = True
        logger.info("Database initialization completed successfully.")
    except Exception as e:
        if conn:
            try: conn.rollback()
            except: pass
        logger.error(f"CRITICAL: Database initialization failed: {e}", exc_info=True)
        raise e
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _init_db_logic(conn, *, allow_legacy_import: bool = True):
    cursor = conn.cursor()

    # ``schema_migrations`` is created after the baseline on a fresh install.
    # Detect the table itself (rather than whether it already has rows): a
    # partially initialized database must not be mistaken for a new install
    # and resurrect records that an operator deliberately deleted.
    try:
        if _USE_PG:
            cursor.execute(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'schema_migrations'"
                ")"
            )
            legacy_bootstrap_new = not bool(cursor.fetchone()[0])
        else:
            cursor.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'schema_migrations'"
            )
            legacy_bootstrap_new = cursor.fetchone() is None
    except Exception:
        # The baseline has to remain usable even when the metadata table is
        # unavailable; migration runner will create it later in this boot.
        legacy_bootstrap_new = True

    def ensure_column(table_name: str, column_name: str, definition: str):
        cols = _table_columns(cursor, table_name)
        if column_name not in cols:
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}')
        
    # Create credentials table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS credentials (
        id TEXT PRIMARY KEY,
        credential_name TEXT UNIQUE,
        credential_type TEXT,
        username TEXT DEFAULT '',
        account_role TEXT DEFAULT 'unbound',
        encrypted_password TEXT DEFAULT '',
        enable_password TEXT DEFAULT '',
        private_key TEXT DEFAULT '',
        snmp_community TEXT DEFAULT '',
        created_at TEXT
    )
    ''')
    ensure_column('credentials', 'account_role', "TEXT DEFAULT 'unbound'")
    ensure_column('credentials', 'snmp_server', "TEXT DEFAULT ''")

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
        snmp_community TEXT DEFAULT 'public',
        snmp_port INTEGER DEFAULT 161,
        snmp_cpu_oid TEXT DEFAULT '',
        snmp_memory_oid TEXT DEFAULT '',
        snmp_metric_profile_id TEXT DEFAULT '',
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

    # SNMP metric template definitions.  Device selection is stored explicitly
    # on devices; vendor/model are metadata and filtering fields only.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS snmp_metric_profiles (
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
        template_name TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'custom',
        official_preset_id TEXT NOT NULL DEFAULT ''
    )
    ''')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_snmp_metric_profiles_model '
        'ON snmp_metric_profiles(vendor_key, model_key)'
    )
    ensure_column('snmp_metric_profiles', 'verification_status', "TEXT NOT NULL DEFAULT 'unverified'")
    ensure_column('snmp_metric_profiles', 'last_test_at', 'TEXT')
    ensure_column('snmp_metric_profiles', 'last_test_device_id', "TEXT NOT NULL DEFAULT ''")
    ensure_column('snmp_metric_profiles', 'last_test_message', "TEXT NOT NULL DEFAULT ''")
    ensure_column('snmp_metric_profiles', 'cpu_config_json', "TEXT NOT NULL DEFAULT '{}'")
    ensure_column('snmp_metric_profiles', 'memory_config_json', "TEXT NOT NULL DEFAULT '{}'")
    ensure_column('snmp_metric_profiles', 'metric_definitions_json', "TEXT NOT NULL DEFAULT '{}'")
    ensure_column('snmp_metric_profiles', 'interface_config_json', "TEXT NOT NULL DEFAULT '{}'")
    ensure_column('snmp_metric_profiles', 'interface_verification_status', "TEXT NOT NULL DEFAULT 'unverified'")
    ensure_column('snmp_metric_profiles', 'interface_last_test_at', 'TEXT')
    ensure_column('snmp_metric_profiles', 'interface_last_test_device_id', "TEXT NOT NULL DEFAULT ''")
    ensure_column('snmp_metric_profiles', 'interface_last_test_message', "TEXT NOT NULL DEFAULT ''")

    # Durable baseline for model-defined SNMP counters.  A process-local cache
    # is not sufficient: a worker restart, multiple workers, or a long poll
    # interval must not turn a counter into a false rate.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS snmp_metric_counter_samples (
        device_id TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        oid TEXT NOT NULL,
        config_hash TEXT NOT NULL DEFAULT '',
        counter_bits INTEGER NOT NULL,
        values_json TEXT NOT NULL DEFAULT '{}',
        sampled_at TEXT NOT NULL,
        device_uptime_cs BIGINT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (device_id, profile_id, metric_name),
        FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_snmp_counter_samples_ts '
        'ON snmp_metric_counter_samples(sampled_at)'
    )

    # Durable per-device IF-MIB baseline.  Values are keyed by ifIndex and
    # tagged with the profile/config hash so a template edit cannot reuse an
    # incompatible counter sample.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS snmp_interface_counter_samples (
        device_id TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        config_hash TEXT NOT NULL DEFAULT '',
        values_json TEXT NOT NULL DEFAULT '{}',
        sampled_at TEXT NOT NULL,
        device_uptime_cs BIGINT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (device_id, profile_id),
        FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_snmp_interface_counter_samples_ts '
        'ON snmp_interface_counter_samples(sampled_at)'
    )

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS snmp_mibs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        vendor TEXT NOT NULL DEFAULT 'General',
        filename TEXT NOT NULL,
        file_size INTEGER NOT NULL DEFAULT 0,
        node_count INTEGER NOT NULL DEFAULT 0,
        source_type TEXT NOT NULL DEFAULT 'user_upload',
        description TEXT NOT NULL DEFAULT '',
        content_text TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_snmp_mibs_vendor ON snmp_mibs(vendor)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS snmp_mib_nodes (
        id TEXT PRIMARY KEY,
        mib_id TEXT NOT NULL,
        node_name TEXT NOT NULL,
        oid TEXT NOT NULL,
        parent_oid TEXT NOT NULL DEFAULT '',
        syntax_type TEXT NOT NULL DEFAULT '',
        access_type TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'current',
        description TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (mib_id) REFERENCES snmp_mibs(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_snmp_mib_nodes_oid ON snmp_mib_nodes(oid)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_snmp_mib_nodes_name ON snmp_mib_nodes(node_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_snmp_mib_nodes_mib ON snmp_mib_nodes(mib_id)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS interfaces (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        interface_name TEXT NOT NULL,
        description TEXT DEFAULT '',
        admin_status TEXT DEFAULT 'down',
        oper_status TEXT DEFAULT 'down',
        mac_address TEXT DEFAULT '',
        mtu INTEGER DEFAULT 1500,
        speed REAL DEFAULT 0.0,
        interface_type TEXT DEFAULT 'physical',
        duplex TEXT DEFAULT 'auto',
        bandwidth REAL DEFAULT 0.0,
        parent_interface_id TEXT,
        channel_group INTEGER,
        vrf_id TEXT,
        switchport_mode TEXT DEFAULT 'access',
        access_vlan INTEGER,
        native_vlan INTEGER,
        allowed_vlans TEXT DEFAULT '',
        ip_enabled INTEGER DEFAULT 0,
        last_flapped TEXT,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE,
        FOREIGN KEY (parent_interface_id) REFERENCES interfaces (id) ON DELETE SET NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_interfaces_device_id ON interfaces(device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_interfaces_mac ON interfaces(mac_address)')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_interfaces_device_name ON interfaces(device_id, interface_name)')
    # Keep the baseline aligned with the canonical Interface model and the
    # topology/graph readers. Older installations may have only the original
    # interface_name column; the versioned migration below backfills them.
    ensure_column('interfaces', 'name_raw', "TEXT DEFAULT ''")
    ensure_column('interfaces', 'name_display', "TEXT DEFAULT ''")
    ensure_column('interfaces', 'primary_ip', "TEXT DEFAULT ''")
    ensure_column('interfaces', 'ip_address', "TEXT DEFAULT ''")
    ensure_column('interfaces', 'ip_prefix_length', 'INTEGER')
    ensure_column('interfaces', 'ip_version', 'INTEGER')
    interface_l3_flag_type = "BOOLEAN DEFAULT FALSE" if _USE_PG else "INTEGER DEFAULT 0"
    ensure_column('interfaces', 'is_l3', interface_l3_flag_type)
    ensure_column('interfaces', 'last_change', 'TEXT')
    ensure_column('interfaces', 'last_seen', 'TEXT')
    ensure_column('interfaces', 'lag_id', "TEXT DEFAULT ''")
    ensure_column('interfaces', 'vlan_mode', "TEXT DEFAULT 'access'")
    cursor.execute(
        "UPDATE interfaces SET name_raw = interface_name WHERE COALESCE(name_raw, '') = ''"
    )
    cursor.execute(
        "UPDATE interfaces SET name_display = interface_name WHERE COALESCE(name_display, '') = ''"
    )
    
    # Create tenants table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tenants (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT ''
    )
    ''')

    # Create roles table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS roles (
        id TEXT PRIMARY KEY,
        role_name TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT ''
    )
    ''')

    # Create sites table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sites (
        id TEXT PRIMARY KEY,
        site_code TEXT NOT NULL UNIQUE,
        site_name TEXT NOT NULL,
        country TEXT DEFAULT '',
        state_province TEXT DEFAULT '',
        city TEXT DEFAULT '',
        district TEXT DEFAULT '',
        contact_name TEXT DEFAULT '',
        contact_phone TEXT DEFAULT '',
        contact_email TEXT DEFAULT '',
        timezone TEXT DEFAULT 'Asia/Shanghai',
        address TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        tenant_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
    )
    ''')

    ensure_column('sites', 'state_province', "TEXT DEFAULT ''")
    ensure_column('sites', 'district', "TEXT DEFAULT ''")
    ensure_column('sites', 'contact_name', "TEXT DEFAULT ''")
    ensure_column('sites', 'contact_phone', "TEXT DEFAULT ''")
    ensure_column('sites', 'contact_email', "TEXT DEFAULT ''")
    ensure_column('sites', 'created_at', "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if _USE_PG else "TEXT DEFAULT ''")
    ensure_column('sites', 'updated_at', "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if _USE_PG else "TEXT DEFAULT ''")

    # Create racks table if not exists
    if _USE_PG:
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS racks (
            id VARCHAR(50) PRIMARY KEY,
            site_id VARCHAR(50) NOT NULL,
            rack_code VARCHAR(50) NOT NULL UNIQUE,
            rack_name VARCHAR(100) NOT NULL,
            name VARCHAR(100) DEFAULT '',
            datacenter VARCHAR(100) DEFAULT '',
            floor VARCHAR(100) DEFAULT '',
            room VARCHAR(100) DEFAULT '',
            row VARCHAR(50) DEFAULT '',
            room_name VARCHAR(100),
            row_name VARCHAR(50),
            total_u INTEGER NOT NULL DEFAULT 42,
            used_u INTEGER NOT NULL DEFAULT 0,
            available_u INTEGER NOT NULL DEFAULT 42,
            power_capacity_w INTEGER DEFAULT 5000,
            power_capacity_watts INTEGER DEFAULT 0,
            current_power_w INTEGER DEFAULT 0,
            power_utilization DECIMAL(5,2) DEFAULT 0,
            max_weight_kg INTEGER,
            current_weight_kg INTEGER DEFAULT 0,
            cooling_zone VARCHAR(50),
            status VARCHAR(20) DEFAULT 'active',
            placement_strategy VARCHAR(20) DEFAULT 'bottom_first',
            remarks TEXT,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES sites (id) ON DELETE CASCADE,
            UNIQUE (site_id, rack_code)
        )
        ''')
    else:
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS racks (
            id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            rack_code TEXT NOT NULL UNIQUE,
            rack_name TEXT NOT NULL,
            name TEXT DEFAULT '',
            datacenter TEXT DEFAULT '',
            floor TEXT DEFAULT '',
            room TEXT DEFAULT '',
            row TEXT DEFAULT '',
            room_name TEXT,
            row_name TEXT,
            total_u INTEGER NOT NULL DEFAULT 42,
            used_u INTEGER NOT NULL DEFAULT 0,
            available_u INTEGER NOT NULL DEFAULT 42,
            power_capacity_w INTEGER DEFAULT 5000,
            power_capacity_watts INTEGER DEFAULT 0,
            current_power_w INTEGER DEFAULT 0,
            power_utilization REAL DEFAULT 0,
            max_weight_kg INTEGER,
            current_weight_kg INTEGER DEFAULT 0,
            cooling_zone TEXT,
            status TEXT DEFAULT 'active',
            placement_strategy TEXT DEFAULT 'bottom_first',
            remarks TEXT,
            description TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES sites (id) ON DELETE CASCADE,
            UNIQUE (site_id, rack_code)
        )
        ''')

    ensure_column('racks', 'site_id', "VARCHAR(50)" if _USE_PG else "TEXT DEFAULT ''")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_racks_site_id ON racks(site_id)')
    ensure_column('racks', 'rack_code', "VARCHAR(50)" if _USE_PG else "TEXT DEFAULT ''")
    ensure_column('racks', 'rack_name', "VARCHAR(100)" if _USE_PG else "TEXT DEFAULT ''")
    ensure_column('racks', 'name', "VARCHAR(100) DEFAULT ''" if _USE_PG else "TEXT DEFAULT ''")
    ensure_column('racks', 'datacenter', "VARCHAR(100) DEFAULT ''" if _USE_PG else "TEXT DEFAULT ''")
    ensure_column('racks', 'room', "VARCHAR(100) DEFAULT ''" if _USE_PG else "TEXT DEFAULT ''")
    ensure_column('racks', 'row', "VARCHAR(50) DEFAULT ''" if _USE_PG else "TEXT DEFAULT ''")
    ensure_column('racks', 'floor', "VARCHAR(100) DEFAULT ''" if _USE_PG else "TEXT DEFAULT ''")
    ensure_column('racks', 'room_name', "VARCHAR(100)" if _USE_PG else "TEXT")
    ensure_column('racks', 'row_name', "VARCHAR(50)" if _USE_PG else "TEXT")
    ensure_column('racks', 'total_u', "INTEGER NOT NULL DEFAULT 42" if _USE_PG else "INTEGER DEFAULT 42")
    ensure_column('racks', 'used_u', "INTEGER NOT NULL DEFAULT 0" if _USE_PG else "INTEGER DEFAULT 0")
    ensure_column('racks', 'available_u', "INTEGER NOT NULL DEFAULT 42" if _USE_PG else "INTEGER DEFAULT 42")
    ensure_column('racks', 'power_capacity_w', "INTEGER DEFAULT 5000" if _USE_PG else "INTEGER DEFAULT 5000")
    ensure_column('racks', 'power_capacity_watts', "INTEGER DEFAULT 0" if _USE_PG else "INTEGER DEFAULT 0")
    ensure_column('racks', 'current_power_w', "INTEGER DEFAULT 0" if _USE_PG else "INTEGER DEFAULT 0")
    ensure_column('racks', 'power_utilization', "DECIMAL(5,2) DEFAULT 0" if _USE_PG else "REAL DEFAULT 0")
    ensure_column('racks', 'max_weight_kg', "INTEGER" if _USE_PG else "INTEGER")
    ensure_column('racks', 'current_weight_kg', "INTEGER DEFAULT 0" if _USE_PG else "INTEGER DEFAULT 0")
    ensure_column('racks', 'cooling_zone', "VARCHAR(50)" if _USE_PG else "TEXT")
    ensure_column('racks', 'status', "VARCHAR(20) DEFAULT 'active'" if _USE_PG else "TEXT DEFAULT 'active'")
    ensure_column('racks', 'placement_strategy', "VARCHAR(20) DEFAULT 'bottom_first'" if _USE_PG else "TEXT DEFAULT 'bottom_first'")
    ensure_column('racks', 'rack_type_id', "VARCHAR(50) DEFAULT ''" if _USE_PG else "TEXT DEFAULT ''")
    ensure_column('racks', 'width_mm', "INTEGER DEFAULT 600" if _USE_PG else "INTEGER DEFAULT 600")
    ensure_column('racks', 'depth_mm', "INTEGER DEFAULT 1000" if _USE_PG else "INTEGER DEFAULT 1000")
    ensure_column('racks', 'allow_front_rear_mount', "INTEGER DEFAULT 1" if _USE_PG else "INTEGER DEFAULT 1")
    ensure_column('racks', 'remarks', "TEXT" if _USE_PG else "TEXT")
    ensure_column('racks', 'description', "TEXT DEFAULT ''" if _USE_PG else "TEXT DEFAULT ''")

    ensure_column('racks', 'created_at', "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if _USE_PG else "TEXT")
    ensure_column('racks', 'updated_at', "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if _USE_PG else "TEXT")

    # Create rack_types table if not exists. Rack instances may override
    # dimensions/capacity, but this gives CMDB a reusable enterprise-grade
    # cabinet template layer instead of relying on hardcoded 42U assumptions.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rack_types (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        vendor TEXT DEFAULT '',
        model TEXT DEFAULT '',
        total_u INTEGER NOT NULL DEFAULT 42,
        width_mm INTEGER DEFAULT 600,
        depth_mm INTEGER DEFAULT 1000,
        max_weight_kg INTEGER DEFAULT 0,
        power_capacity_watts INTEGER DEFAULT 0,
        allow_front_rear_mount INTEGER DEFAULT 1,
        description TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_rack_types_name ON rack_types(name)')
    default_rack_types = [
        ('rack-type-24u-standard', '24U Standard Cabinet', 'Generic', 'STD-24U', 24, 600, 800, 600, 6000, 1, 'Default 24U cabinet template'),
        ('rack-type-42u-standard', '42U Standard Cabinet', 'Generic', 'STD-42U', 42, 600, 1000, 1000, 10000, 1, 'Default 42U cabinet template'),
        ('rack-type-48u-network', '48U Network Cabinet', 'Generic', 'NET-48U', 48, 600, 1000, 1200, 12000, 1, 'Default high-density network cabinet template'),
        ('rack-type-wall-mount-12u', '12U Wall Mount Cabinet', 'Generic', 'WALL-12U', 12, 600, 450, 80, 2000, 0, 'Default wall-mount cabinet template'),
    ]
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for rt in default_rack_types:
        exists = cursor.execute(
            "SELECT id FROM rack_types WHERE id = ? OR name = ? LIMIT 1",
            (rt[0], rt[1])
        ).fetchone()
        if not exists:
            cursor.execute(
                """INSERT INTO rack_types (
                    id, name, vendor, model, total_u, width_mm, depth_mm, max_weight_kg,
                    power_capacity_watts, allow_front_rear_mount, description, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*rt, now, now)
            )

    # Create device_types table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS device_types (
        id TEXT PRIMARY KEY,
        vendor TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        part_number TEXT DEFAULT '',
        u_height INTEGER DEFAULT 1,
        device_role TEXT DEFAULT 'switch',
        is_full_depth INTEGER DEFAULT 1,
        description TEXT DEFAULT '',
        created_at TEXT,
        updated_at TEXT,
        UNIQUE (vendor, model)
    )
    ''')
    ensure_column('device_types', 'vendor', "TEXT DEFAULT ''")
    ensure_column('device_types', 'model', "TEXT DEFAULT ''")
    ensure_column('device_types', 'part_number', "TEXT DEFAULT ''")
    ensure_column('device_types', 'u_height', "INTEGER DEFAULT 1")
    ensure_column('device_types', 'device_role', "TEXT DEFAULT 'switch'")
    ensure_column('device_types', 'is_full_depth', "INTEGER DEFAULT 1")
    ensure_column('device_types', 'description', "TEXT DEFAULT ''")
    ensure_column('device_types', 'created_at', "TEXT")
    ensure_column('device_types', 'updated_at', "TEXT")


    # Create vrfs table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS vrfs (
        id TEXT PRIMARY KEY,
        vrf_name TEXT NOT NULL,
        rd TEXT DEFAULT '',
        description TEXT DEFAULT '',
        tenant_id TEXT,
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
    )
    ''')

    # Create vlans table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS vlans (
        id TEXT PRIMARY KEY,
        vlan_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        site_id TEXT,
        status TEXT DEFAULT 'active',
        tenant_id TEXT,
        FOREIGN KEY (site_id) REFERENCES sites (id) ON DELETE CASCADE,
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_vlans_site_vlan ON vlans(site_id, vlan_id)')
    for _unique_sql in (
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_vlans_site_vlan ON vlans(site_id, vlan_id)',
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_vrfs_tenant_name ON vrfs(tenant_id, vrf_name)',
    ):
        try:
            cursor.execute(_unique_sql)
        except Exception as _unique_exc:
            logger.warning("CMDB unique index deferred because historical duplicates exist: %s", _unique_exc)

    # Create prefixes table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS prefixes (
        id TEXT PRIMARY KEY,
        prefix TEXT NOT NULL,
        vrf_id TEXT,
        vlan_id TEXT,
        site_id TEXT,
        tenant_id TEXT,
        status TEXT DEFAULT 'active',
        name TEXT DEFAULT '',
        gateway TEXT DEFAULT '',
        description TEXT DEFAULT '',
        created_at TEXT DEFAULT '',
        updated_at TEXT DEFAULT '',
        FOREIGN KEY (vrf_id) REFERENCES vrfs (id) ON DELETE SET NULL,
        FOREIGN KEY (vlan_id) REFERENCES vlans (id) ON DELETE SET NULL,
        FOREIGN KEY (site_id) REFERENCES sites (id) ON DELETE SET NULL,
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_prefixes_prefix ON prefixes(prefix)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_prefixes_tenant ON prefixes(tenant_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_prefixes_vrf_prefix ON prefixes(vrf_id, prefix)')

    ensure_column('prefixes', 'parent_prefix_id', "TEXT")
    ensure_column('prefixes', 'network_type', "TEXT DEFAULT 'server'")
    ensure_column('prefixes', 'gateway_device_id', "TEXT")
    ensure_column('prefixes', 'gateway_interface_id', "TEXT")
    ensure_column('prefixes', 'traceable', "INTEGER DEFAULT 1")
    ensure_column('prefixes', 'prefix_cidr', "CIDR" if _USE_PG else "TEXT DEFAULT ''")
    ensure_column('prefixes', 'ip_version', "INTEGER DEFAULT 0")
    ensure_column('prefixes', 'prefix_len', "INTEGER DEFAULT 0")
    for col, dtype in [
        ('classification_status', "TEXT DEFAULT 'auto'"),
        ('classification_source', "TEXT DEFAULT 'auto'"),
        ('classification_confidence', "REAL DEFAULT 0"),
        ('classification_rule_version', "TEXT DEFAULT 'prefix-classification-v1'"),
        ('manual_override', "INTEGER DEFAULT 0"),
        ('manual_network_type', "TEXT DEFAULT ''"),
        ('mixed_network', "INTEGER DEFAULT 0"),
        ('address_roles_json', "TEXT DEFAULT '[]'"),
        ('discovered_devices_json', "TEXT DEFAULT '[]'"),
        ('observed_interfaces_json', "TEXT DEFAULT '[]'"),
        ('observed_vlans_json', "TEXT DEFAULT '[]'"),
        ('observed_vrfs_json', "TEXT DEFAULT '[]'"),
        ('evidence_json', "TEXT DEFAULT '[]'"),
        ('candidate_scores_json', "TEXT DEFAULT '{}'"),
        ('conflict_status', "TEXT DEFAULT ''"),
        ('conflict_json', "TEXT DEFAULT '{}'"),
        ('first_seen_at', "TEXT"),
        ('last_seen_at', "TEXT"),
        ('miss_count', "INTEGER DEFAULT 0"),
        ('is_active', "INTEGER DEFAULT 1"),
    ]:
        ensure_column('prefixes', col, dtype)

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS prefix_observations (
        id TEXT PRIMARY KEY,
        prefix_id TEXT NOT NULL,
        collection_run_id TEXT NOT NULL,
        source_device_id TEXT DEFAULT '',
        source_type TEXT NOT NULL,
        observed_value TEXT NOT NULL,
        evidence_json TEXT DEFAULT '{}',
        confidence REAL DEFAULT 0,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        miss_count INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY (prefix_id) REFERENCES prefixes(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_prefix_observation_identity ON prefix_observations(prefix_id, source_device_id, source_type, observed_value)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_prefix_observations_active ON prefix_observations(prefix_id, is_active, last_seen_at)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS prefix_classification_history (
        id TEXT PRIMARY KEY,
        prefix_id TEXT NOT NULL,
        collection_run_id TEXT DEFAULT '',
        previous_type TEXT DEFAULT '',
        next_type TEXT DEFAULT '',
        confidence REAL DEFAULT 0,
        source TEXT DEFAULT '',
        evidence_json TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY (prefix_id) REFERENCES prefixes(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_prefix_class_history_prefix ON prefix_classification_history(prefix_id, created_at)')

    # Create ipam_pools table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ipam_pools (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        prefix_id TEXT NOT NULL,
        start_ip TEXT NOT NULL,
        end_ip TEXT NOT NULL,
        description TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        tenant_id TEXT DEFAULT 'tenant-default',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (prefix_id) REFERENCES prefixes (id) ON DELETE CASCADE,
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE SET NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ipam_pools_prefix ON ipam_pools(prefix_id)')

    # Create ipam_vips table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ipam_vips (
        id TEXT PRIMARY KEY,
        address TEXT NOT NULL,
        vip_type TEXT NOT NULL,
        device_id TEXT,
        interface_name TEXT DEFAULT '',
        description TEXT DEFAULT '',
        real_servers TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        tenant_id TEXT DEFAULT 'tenant-default',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE SET NULL,
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE SET NULL
    )
    ''')
    ensure_column('ipam_vips', 'backup_device_id', "TEXT")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ipam_vips_device ON ipam_vips(device_id)')

    # Create ipam_dhcp_leases table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ipam_dhcp_leases (
        id TEXT PRIMARY KEY,
        address TEXT NOT NULL,
        mac_address TEXT NOT NULL,
        hostname TEXT DEFAULT '',
        dhcp_server TEXT DEFAULT '',
        lease_state TEXT DEFAULT 'active',
        tenant_id TEXT DEFAULT 'tenant-default',
        lease_start TEXT DEFAULT '',
        lease_end TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    ensure_column('ipam_dhcp_leases', 'tenant_id', "TEXT DEFAULT 'tenant-default'")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ipam_dhcp_mac ON ipam_dhcp_leases(mac_address)')


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
    for col, dtype in [
        ('job_type', "TEXT DEFAULT 'generic'"),
        ('created_by', "TEXT DEFAULT 'system'"),
        ('started_at', 'TEXT'),
        ('finished_at', 'TEXT'),
        ('updated_at', 'TEXT'),
        ('progress', 'INTEGER DEFAULT 0'),
        ('total_targets', 'INTEGER DEFAULT 0'),
        ('success_count', 'INTEGER DEFAULT 0'),
        ('failed_count', 'INTEGER DEFAULT 0'),
        ('cancel_requested', 'INTEGER DEFAULT 0'),
        ('error_summary', "TEXT DEFAULT ''"),
        ('concurrency_limit', 'INTEGER DEFAULT 5'),
        ('retry_limit', 'INTEGER DEFAULT 0'),
        ('timeout_seconds', 'INTEGER DEFAULT 300'),
        ('scope_json', "TEXT DEFAULT '{}'"),
    ]:
        ensure_column('jobs', col, dtype)
    
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

    # Multi-role credential columns for PAM & CMDB/IPAM
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
        ('switching_capacity_gbps', 'REAL DEFAULT 0.0'),
        ('tenant_id', "TEXT DEFAULT ''"),
        ('site_id', "TEXT DEFAULT ''"),
        ('device_group_id', "TEXT DEFAULT ''"),
        ('rack_id', "TEXT DEFAULT ''"),
        ('device_type_id', "TEXT DEFAULT ''"),
        ('asset_tag', "TEXT DEFAULT ''"),
        ('serial_number', "TEXT DEFAULT ''"),
        ('os_version', "TEXT DEFAULT ''"),
        ('firmware_version', "TEXT DEFAULT ''"),
        ('lifecycle_status', "TEXT DEFAULT 'staging'"),
        ('purchase_date', "TEXT DEFAULT ''"),
        ('warranty_expire', "TEXT DEFAULT ''"),
        ('owner_team', "TEXT DEFAULT ''"),
        ('criticality', "TEXT DEFAULT 'P3'"),
         ('monitoring_enabled', "INTEGER DEFAULT 1"),
         ('config_backup_enabled', "INTEGER DEFAULT 1"),
         ('last_discovered', "TEXT DEFAULT ''"),
         ('collection_policy_json', "TEXT DEFAULT '{}'")
     ]:
        ensure_column('devices', col, dtype)
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_device_group_id ON devices(device_group_id)')

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
        last_used TEXT,
        description TEXT DEFAULT '',
        platform_family TEXT DEFAULT '',
        software_version TEXT DEFAULT '',
        official_reference TEXT DEFAULT '',
        validation_status TEXT DEFAULT 'draft'
    )
    ''')
    ensure_column('templates', 'rollback', 'TEXT')
    ensure_column('templates', 'description', "TEXT DEFAULT ''")
    ensure_column('templates', 'platform_family', "TEXT DEFAULT ''")
    ensure_column('templates', 'software_version', "TEXT DEFAULT ''")
    ensure_column('templates', 'official_reference', "TEXT DEFAULT ''")
    ensure_column('templates', 'validation_status', "TEXT DEFAULT 'draft'")
    
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
    ensure_column('users', 'role_profile', "TEXT DEFAULT ''")
    ensure_column('users', 'fixed_pin', "TEXT DEFAULT ''")
    ensure_column('users', 'display_name', "TEXT DEFAULT ''")
    ensure_column('users', 'phone', "TEXT DEFAULT ''")
    ensure_column('users', 'email', "TEXT DEFAULT ''")
    ensure_column('users', 'role_id', "TEXT DEFAULT ''")
    ensure_column('users', 'tenant_id', "TEXT DEFAULT ''")
    ensure_column('users', 'scope_type', "TEXT DEFAULT 'global'")
    ensure_column('users', 'scope_ids_json', "TEXT DEFAULT '[]'")
    ensure_column('users', 'mfa_secret', "TEXT DEFAULT ''")
    ensure_column('users', 'mfa_enabled', "INTEGER DEFAULT 0")

    # Store user-defined scenario templates for playbooks
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS custom_scenarios (
        id TEXT PRIMARY KEY,
        data_json TEXT NOT NULL,
        tenant_id TEXT,
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
        value TEXT,
        created_at TEXT DEFAULT '',
        updated_at TEXT DEFAULT ''
    )
    ''')
    ensure_column('global_vars', 'created_at', "TEXT DEFAULT ''")
    ensure_column('global_vars', 'updated_at', "TEXT DEFAULT ''")

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
    ensure_column('config_snapshots', 'raw_hash', "TEXT DEFAULT ''")
    ensure_column('config_snapshots', 'normalized_hash', "TEXT DEFAULT ''")
    ensure_column('config_snapshots', 'line_count', 'INTEGER DEFAULT 0')
    ensure_column('config_snapshots', 'section_count', 'INTEGER DEFAULT 0')
    ensure_column('config_snapshots', 'integrity_status', "TEXT DEFAULT 'unknown'")
    ensure_column('config_snapshots', 'lifecycle_status', "TEXT DEFAULT 'stored_raw'")
    ensure_column('config_snapshots', 'normalizer_version', "TEXT DEFAULT 'ncm-v1'")
    ensure_column('config_snapshots', 'collected_at', "TEXT DEFAULT ''")
    ensure_column('config_snapshots', 'task_id', "TEXT DEFAULT ''")
    ensure_column('config_snapshots', 'policy_id', "TEXT DEFAULT ''")
    ensure_column('config_snapshots', 'config_type', "TEXT DEFAULT 'running'")
    ensure_column('config_snapshots', 'has_unsaved_changes', 'INTEGER DEFAULT 0')
    ensure_column('config_snapshots', 'unsaved_diff_summary', "TEXT DEFAULT ''")
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_config_snapshots_policy_device_time '
        'ON config_snapshots(policy_id, device_id, timestamp DESC)'
    )
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_config_snapshots_dev_type_ts '
        'ON config_snapshots(device_id, config_type, timestamp DESC)'
    )

    # Persistent backup policies. The default row is imported lazily from the
    # legacy global schedule so existing installations retain their settings.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS config_backup_policies (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        cron_expr TEXT NOT NULL DEFAULT '0 2 * * *',
        timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
        priority INTEGER NOT NULL DEFAULT 100,
        scope_json TEXT NOT NULL DEFAULT '{}',
        config_types_json TEXT NOT NULL DEFAULT '["running"]',
        change_only INTEGER NOT NULL DEFAULT 1,
        retention_days INTEGER NOT NULL DEFAULT 90,
        max_versions_per_device INTEGER NOT NULL DEFAULT 30,
        concurrency INTEGER NOT NULL DEFAULT 10,
        retry_count INTEGER NOT NULL DEFAULT 1,
        timeout_seconds INTEGER NOT NULL DEFAULT 30,
        collect_startup_config INTEGER NOT NULL DEFAULT 0,
        tftp_enabled INTEGER NOT NULL DEFAULT 0,
        tftp_server TEXT NOT NULL DEFAULT '',
        tftp_port INTEGER NOT NULL DEFAULT 69,
        tftp_path_prefix TEXT NOT NULL DEFAULT 'backups',
        created_by TEXT NOT NULL DEFAULT '',
        updated_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    ensure_column('config_backup_policies', 'collect_startup_config', 'INTEGER NOT NULL DEFAULT 0')
    ensure_column('config_backup_policies', 'tftp_enabled', 'INTEGER NOT NULL DEFAULT 0')
    ensure_column('config_backup_policies', 'tftp_server', "TEXT NOT NULL DEFAULT ''")
    ensure_column('config_backup_policies', 'tftp_port', 'INTEGER NOT NULL DEFAULT 69')
    ensure_column('config_backup_policies', 'tftp_path_prefix', "TEXT NOT NULL DEFAULT 'backups'")
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_config_backup_policies_enabled_priority '
        'ON config_backup_policies(enabled, priority, name)'
    )

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

    # Create topology_links table if not exists
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS topology_links (
        id TEXT PRIMARY KEY,
        link_key TEXT UNIQUE,
        source_device_id TEXT,
        source_interface_id TEXT,
        source_hostname TEXT,
        source_port TEXT,
        source_port_normalized TEXT,
        target_device_id TEXT,
        target_interface_id TEXT,
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
        source_site_id TEXT DEFAULT '',
        target_site_id TEXT DEFAULT '',
        FOREIGN KEY (source_device_id) REFERENCES devices (id),
        FOREIGN KEY (source_interface_id) REFERENCES interfaces (id),
        FOREIGN KEY (target_device_id) REFERENCES devices (id),
        FOREIGN KEY (target_interface_id) REFERENCES interfaces (id)
    )
    ''')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_topo_links_key ON topology_links(link_key)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topo_links_source_target ON topology_links(source_device_id, target_device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topo_links_src_intf ON topology_links(source_interface_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topo_links_tgt_intf ON topology_links(target_interface_id)')

    for col, dtype in [
        ('link_key', "TEXT"),
        ('source_device_id', "TEXT"),
        ('source_interface_id', "TEXT"),
        ('source_hostname', "TEXT"),
        ('source_port', "TEXT"),
        ('source_port_normalized', "TEXT"),
        ('target_device_id', "TEXT"),
        ('target_interface_id', "TEXT"),
        ('target_hostname', "TEXT"),
        ('target_port', "TEXT"),
        ('target_port_normalized', "TEXT"),
        ('discovery_source', "TEXT DEFAULT 'lldp'"),
        ('confidence', "REAL DEFAULT 0.0"),
        ('status', "TEXT DEFAULT 'up'"),
        ('is_inferred', "INTEGER DEFAULT 0"),
        ('evidence_count', "INTEGER DEFAULT 1"),
        ('metadata_json', "TEXT DEFAULT '{}'"),
        ('created_at', "TEXT"),
        ('updated_at', "TEXT"),
        ('last_seen', "TEXT")
        ,('source_site_id', "TEXT DEFAULT ''")
        ,('target_site_id', "TEXT DEFAULT ''")
    ]:
        ensure_column('topology_links', col, dtype)


    # ── IP Locator tables ──
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS arp_cache (
        target_ip   TEXT PRIMARY KEY,
        mac         TEXT NOT NULL,
        vlan_id     INTEGER,
        arp_source  TEXT NOT NULL DEFAULT '{}',
        cached_at   TEXT NOT NULL,
        expires_at  REAL NOT NULL,
        source_device_id TEXT DEFAULT ''
    )
    ''')
    ensure_column('arp_cache', 'vlan_id', "INTEGER")
    ensure_column('arp_cache', 'source_device_id', "TEXT DEFAULT ''")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_arp_cache_expires ON arp_cache(expires_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_arp_cache_source_device ON arp_cache(source_device_id)')

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS mac_change_log (
        id          {_SERIAL_PK},
        ip          TEXT NOT NULL,
        old_mac     TEXT NOT NULL,
        new_mac     TEXT NOT NULL,
        old_vendor  TEXT NOT NULL DEFAULT '',
        new_vendor  TEXT NOT NULL DEFAULT '',
        old_device  TEXT NOT NULL DEFAULT '',
        new_device  TEXT NOT NULL DEFAULT '',
        detected_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_mac_change_ip ON mac_change_log(ip)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_mac_change_time ON mac_change_log(detected_at DESC)')

    # Check if network_endpoints has the old 'port' column instead of 'switch_port'
    try:
        if _USE_PG:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'network_endpoints' AND column_name = 'port'"
            )
            has_old_port = bool(cursor.fetchone())
        else:
            cols = [row['name'] for row in cursor.execute("PRAGMA table_info(network_endpoints)").fetchall()]
            has_old_port = ('port' in cols and 'switch_port' not in cols)
        if has_old_port:
            cursor.execute("DROP TABLE network_endpoints")
    except Exception:
        pass

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS network_endpoints (
        id          TEXT PRIMARY KEY,
        ip          TEXT UNIQUE,
        mac         TEXT NOT NULL,
        hostname    TEXT NOT NULL DEFAULT '',
        vendor      TEXT NOT NULL DEFAULT '',
        os_type     TEXT NOT NULL DEFAULT '',
        asset_type  TEXT NOT NULL DEFAULT 'host',
        switch_id   TEXT NOT NULL,
        switch_port TEXT NOT NULL,
        vlan        TEXT NOT NULL DEFAULT '',
        vrf         TEXT NOT NULL DEFAULT '',
        site        TEXT NOT NULL DEFAULT '',
        source_type TEXT NOT NULL DEFAULT 'arp',
        confidence  TEXT NOT NULL DEFAULT '95%',
        first_seen  TEXT NOT NULL,
        last_seen   TEXT NOT NULL,
        is_active   INTEGER NOT NULL DEFAULT 1
    )
    ''')

    for col, dtype in [
        ('ip', "TEXT UNIQUE"),
        ('mac', "TEXT DEFAULT ''"),
        ('hostname', "TEXT NOT NULL DEFAULT ''"),
        ('vendor', "TEXT NOT NULL DEFAULT ''"),
        ('os_type', "TEXT NOT NULL DEFAULT ''"),
        ('asset_type', "TEXT NOT NULL DEFAULT 'host'"),
        ('switch_id', "TEXT DEFAULT ''"),
        ('switch_port', "TEXT DEFAULT ''"),
        ('vlan', "TEXT NOT NULL DEFAULT ''"),
        ('vrf', "TEXT NOT NULL DEFAULT ''"),
        ('site', "TEXT NOT NULL DEFAULT ''"),
        ('source_type', "TEXT NOT NULL DEFAULT 'arp'"),
        ('confidence', "TEXT NOT NULL DEFAULT '95%'"),
        ('first_seen', "TEXT DEFAULT ''"),
        ('last_seen', "TEXT DEFAULT ''"),
        ('is_active', "INTEGER NOT NULL DEFAULT 1")
    ]:
        ensure_column('network_endpoints', col, dtype)

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS endpoint_history (
        id TEXT PRIMARY KEY,
        ip TEXT NOT NULL,
        mac TEXT NOT NULL,
        old_switch_id TEXT,
        old_switch_port TEXT,
        old_vlan TEXT,
        new_switch_id TEXT,
        new_switch_port TEXT,
        new_vlan TEXT,
        drift_type TEXT NOT NULL,
        detected_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_endpoint_history_mac ON endpoint_history(mac)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_endpoint_history_ip ON endpoint_history(ip)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ip_inventory (
        ip          TEXT PRIMARY KEY,
        mask        TEXT NOT NULL DEFAULT '255.255.255.255',
        device_id   TEXT NOT NULL,
        interface   TEXT NOT NULL,
        type        TEXT NOT NULL,
        last_seen   TEXT NOT NULL
    )
    ''')

    for col, dtype in [
        ('mask', "TEXT NOT NULL DEFAULT '255.255.255.255'"),
        ('device_id', "TEXT DEFAULT ''"),
        ('interface', "TEXT DEFAULT ''"),
        ('type', "TEXT DEFAULT ''"),
        ('last_seen', "TEXT DEFAULT ''")
    ]:
        ensure_column('ip_inventory', col, dtype)

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS route_cache (
        id          TEXT PRIMARY KEY,
        device_id   TEXT NOT NULL,
        vrf_name    TEXT NOT NULL DEFAULT 'default',
        prefix      TEXT NOT NULL,
        mask        TEXT NOT NULL,
        next_hop    TEXT NOT NULL,
        protocol    TEXT NOT NULL,
        interface   TEXT NOT NULL DEFAULT '',
        metric      INTEGER NOT NULL DEFAULT 0,
        last_update TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_route_cache_device_prefix ON route_cache(device_id, prefix)')

    for col, dtype in [
        ('device_id', "TEXT DEFAULT ''"),
        ('vrf_name', "TEXT DEFAULT 'default'"),
        ('prefix', "TEXT DEFAULT ''"),
        ('mask', "TEXT DEFAULT ''"),
        ('next_hop', "TEXT DEFAULT ''"),
        ('protocol', "TEXT DEFAULT ''"),
        ('interface', "TEXT DEFAULT ''"),
        ('metric', "INTEGER DEFAULT 0"),
        ('last_update', "TEXT DEFAULT ''")
    ]:
        ensure_column('route_cache', col, dtype)

    # Create route_table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS route_table (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        vrf_name TEXT NOT NULL DEFAULT 'default',
        destination TEXT NOT NULL,
        next_hop TEXT NOT NULL DEFAULT '',
        outgoing_interface TEXT NOT NULL DEFAULT '',
        protocol TEXT NOT NULL DEFAULT 'static',
        metric INTEGER DEFAULT 0,
        preference INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        last_updated TEXT NOT NULL,
        route_source TEXT DEFAULT '',
        age INTEGER DEFAULT 0,
        tag INTEGER DEFAULT 0,
        as_path TEXT DEFAULT '',
        community TEXT DEFAULT '',
        origin TEXT DEFAULT '',
        local_pref INTEGER DEFAULT 0,
        med INTEGER DEFAULT 0,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_routes_device_vrf ON route_table(device_id, vrf_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_routes_destination ON route_table(destination)')

    for col, dtype in [
        ('device_id', "TEXT"),
        ('vrf_name', "TEXT DEFAULT 'default'"),
        ('destination', "TEXT"),
        ('next_hop', "TEXT DEFAULT ''"),
        ('outgoing_interface', "TEXT DEFAULT ''"),
        ('protocol', "TEXT DEFAULT 'static'"),
        ('metric', "INTEGER DEFAULT 0"),
        ('preference', "INTEGER DEFAULT 0"),
        ('active', "INTEGER DEFAULT 1"),
        ('last_updated', "TEXT"),
        ('route_source', "TEXT DEFAULT ''"),
        ('age', "INTEGER DEFAULT 0"),
        ('tag', "INTEGER DEFAULT 0"),
        ('as_path', "TEXT DEFAULT ''"),
        ('community', "TEXT DEFAULT ''"),
        ('origin', "TEXT DEFAULT ''"),
        ('local_pref', "INTEGER DEFAULT 0"),
        ('med', "INTEGER DEFAULT 0")
    ]:
        ensure_column('route_table', col, dtype)

    # Create arp_table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS arp_table (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        ip_address TEXT NOT NULL,
        mac_address TEXT NOT NULL,
        interface_name TEXT DEFAULT '',
        vlan_id INTEGER,
        last_updated TEXT NOT NULL,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_arp_device_ip ON arp_table(device_id, ip_address)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_arp_mac ON arp_table(mac_address)')

    for col, dtype in [
        ('device_id', "TEXT"),
        ('ip_address', "TEXT"),
        ('mac_address', "TEXT"),
        ('interface_name', "TEXT DEFAULT ''"),
        ('vlan_id', "INTEGER"),
        ('last_updated', "TEXT")
    ]:
        ensure_column('arp_table', col, dtype)

    # Create mac_table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS mac_table (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        mac_address TEXT NOT NULL,
        interface_name TEXT NOT NULL,
        vlan_id INTEGER NOT NULL,
        entry_type TEXT NOT NULL DEFAULT 'dynamic',
        last_updated TEXT NOT NULL,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_mac_device_vlan ON mac_table(device_id, vlan_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_mac_address ON mac_table(mac_address)')

    for col, dtype in [
        ('device_id', "TEXT"),
        ('mac_address', "TEXT"),
        ('interface_name', "TEXT"),
        ('vlan_id', "INTEGER"),
        ('entry_type', "TEXT DEFAULT 'dynamic'"),
        ('last_updated', "TEXT")
    ]:
        ensure_column('mac_table', col, dtype)

    # Create neighbor_table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS neighbor_table (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        local_interface TEXT NOT NULL,
        neighbor_hostname TEXT NOT NULL,
        neighbor_interface TEXT NOT NULL,
        neighbor_ip TEXT DEFAULT '',
        protocol TEXT NOT NULL,
        last_updated TEXT NOT NULL,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_neighbors_device ON neighbor_table(device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_neighbors_name ON neighbor_table(neighbor_hostname)')

    for col, dtype in [
        ('device_id', "TEXT"),
        ('local_interface', "TEXT"),
        ('neighbor_hostname', "TEXT"),
        ('neighbor_interface', "TEXT"),
        ('neighbor_ip', "TEXT DEFAULT ''"),
        ('protocol', "TEXT"),
        ('last_updated', "TEXT")
    ]:
        ensure_column('neighbor_table', col, dtype)

    # Create routing_neighbors table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS routing_neighbors (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        protocol TEXT NOT NULL,
        neighbor_id TEXT DEFAULT '',
        neighbor_ip TEXT DEFAULT '',
        local_ip TEXT DEFAULT '',
        local_interface TEXT DEFAULT '',
        vrf_name TEXT NOT NULL DEFAULT 'default',
        state TEXT NOT NULL DEFAULT '',
        uptime TEXT DEFAULT '',
        local_as INTEGER DEFAULT 0,
        remote_as INTEGER DEFAULT 0,
        area_id TEXT DEFAULT '',
        last_updated TEXT NOT NULL,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_routing_neigh_device ON routing_neighbors(device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_routing_neigh_proto ON routing_neighbors(protocol)')

    for col, dtype in [
        ('device_id', "TEXT"),
        ('protocol', "TEXT"),
        ('neighbor_id', "TEXT DEFAULT ''"),
        ('neighbor_ip', "TEXT DEFAULT ''"),
        ('local_ip', "TEXT DEFAULT ''"),
        ('local_interface', "TEXT DEFAULT ''"),
        ('vrf_name', "TEXT DEFAULT 'default'"),
        ('state', "TEXT DEFAULT ''"),
        ('uptime', "TEXT DEFAULT ''"),
        ('local_as', "INTEGER DEFAULT 0"),
        ('remote_as', "INTEGER DEFAULT 0"),
        ('area_id', "TEXT DEFAULT ''"),
        ('last_updated', "TEXT")
    ]:
        ensure_column('routing_neighbors', col, dtype)

    # Create bgp_route_table table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bgp_route_table (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        vrf_name TEXT NOT NULL DEFAULT 'default',
        prefix TEXT DEFAULT '',
        next_hop TEXT DEFAULT '',
        metric INTEGER DEFAULT 0,
        loc_pref INTEGER DEFAULT 100,
        weight INTEGER DEFAULT 0,
        as_path TEXT DEFAULT '',
        local_as INTEGER DEFAULT 0,
        is_best INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 0,
        last_updated TEXT NOT NULL,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_bgp_route_device ON bgp_route_table(device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_bgp_route_prefix ON bgp_route_table(prefix)')

    for col, dtype in [
        ('device_id', "TEXT"),
        ('vrf_name', "TEXT DEFAULT 'default'"),
        ('prefix', "TEXT DEFAULT ''"),
        ('next_hop', "TEXT DEFAULT ''"),
        ('metric', "INTEGER DEFAULT 0"),
        ('loc_pref', "INTEGER DEFAULT 100"),
        ('weight', "INTEGER DEFAULT 0"),
        ('as_path', "TEXT DEFAULT ''"),
        ('local_as', "INTEGER DEFAULT 0"),
        ('is_best', "INTEGER DEFAULT 0"),
        ('is_active', "INTEGER DEFAULT 0"),
        ('last_updated', "TEXT")
    ]:
        ensure_column('bgp_route_table', col, dtype)

    # Create config_backups table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS config_backups (
        id TEXT PRIMARY KEY,
        device_id TEXT,
        config_type TEXT NOT NULL,
        backup_time TEXT NOT NULL,
        file_path TEXT NOT NULL,
        config_hash TEXT,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cfg_backup_device ON config_backups(device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cfg_backup_time ON config_backups(backup_time)')

    for col, dtype in [
        ('device_id', "TEXT"),
        ('config_type', "TEXT"),
        ('backup_time', "TEXT"),
        ('file_path', "TEXT"),
        ('config_hash', "TEXT")
    ]:
        ensure_column('config_backups', col, dtype)

    # Create alarms table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS alarms (
        id TEXT PRIMARY KEY,
        device_id TEXT,
        severity TEXT NOT NULL,
        source TEXT NOT NULL,
        alarm_type TEXT NOT NULL,
        alarm_time TEXT NOT NULL,
        clear_time TEXT,
        status TEXT NOT NULL,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alarms_device ON alarms(device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alarms_status ON alarms(status)')

    for col, dtype in [
        ('device_id', "TEXT"),
        ('severity', "TEXT"),
        ('source', "TEXT"),
        ('alarm_type', "TEXT"),
        ('alarm_time', "TEXT"),
        ('clear_time', "TEXT"),
        ('status', "TEXT")
    ]:
        ensure_column('alarms', col, dtype)

    # Create performance_metrics table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS performance_metrics (
        id TEXT PRIMARY KEY,
        device_id TEXT,
        metric_name TEXT NOT NULL,
        metric_value REAL NOT NULL,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_perf_device_metric ON performance_metrics(device_id, metric_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_perf_timestamp ON performance_metrics(timestamp)')

    for col, dtype in [
        ('device_id', "TEXT"),
        ('metric_name', "TEXT"),
        ('metric_value', "REAL"),
        ('timestamp', "TEXT")
    ]:
        ensure_column('performance_metrics', col, dtype)

    # Create events table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        event_source TEXT NOT NULL,
        event_time TEXT NOT NULL,
        payload TEXT DEFAULT '{}'
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(event_type, event_time)')

    for col, dtype in [
        ('event_type', "TEXT"),
        ('event_source', "TEXT"),
        ('event_time', "TEXT"),
        ('payload', "TEXT DEFAULT '{}'")
    ]:
        ensure_column('events', col, dtype)

    # Create discovery_jobs table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS discovery_jobs (
        id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL,
        target TEXT NOT NULL,
        status TEXT NOT NULL,
        start_time TEXT NOT NULL,
        finish_time TEXT,
        result TEXT DEFAULT '{}'
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_disc_status ON discovery_jobs(status)')

    for col, dtype in [
        ('job_type', "TEXT"),
        ('target', "TEXT"),
        ('status', "TEXT"),
        ('start_time', "TEXT"),
        ('finish_time', "TEXT"),
        ('result', "TEXT DEFAULT '{}'")
    ]:
        ensure_column('discovery_jobs', col, dtype)



    cursor.execute('''
    CREATE TABLE IF NOT EXISTS topology_discovery_runs (
        id TEXT PRIMARY KEY,
        scope TEXT NOT NULL DEFAULT 'full',
        status TEXT NOT NULL DEFAULT 'pending',
        requested_by TEXT DEFAULT 'system',
        protocol_scope TEXT DEFAULT 'lldp',
        started_at TEXT NOT NULL,
        completed_at TEXT,
        total_devices INTEGER DEFAULT 0,
        success_devices INTEGER DEFAULT 0,
        failed_devices INTEGER DEFAULT 0,
        total_observations INTEGER DEFAULT 0,
        total_links INTEGER DEFAULT 0,
        summary_json TEXT DEFAULT '{}',
        site_id TEXT DEFAULT '',
        scope_json TEXT DEFAULT '{}',
        cancel_requested INTEGER DEFAULT 0,
        idempotency_key TEXT DEFAULT '',
        lease_owner TEXT DEFAULT '',
        lease_expires_at TEXT,
        heartbeat_at TEXT,
        attempt_count INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 2,
        timeout_seconds INTEGER DEFAULT 300,
        last_error_code TEXT DEFAULT ''
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
        error_code TEXT DEFAULT '',
        attempt_count INTEGER DEFAULT 0,
        last_attempt_at TEXT,
        FOREIGN KEY (run_id) REFERENCES topology_discovery_runs(id),
        FOREIGN KEY (device_id) REFERENCES devices(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_run_devices_run_id ON topology_discovery_run_devices(run_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_run_devices_device_id ON topology_discovery_run_devices(device_id)')
    for col, dtype in [
        ('idempotency_key', "TEXT DEFAULT ''"),
        ('lease_owner', "TEXT DEFAULT ''"),
        ('lease_expires_at', "TEXT"),
        ('heartbeat_at', "TEXT"),
        ('attempt_count', "INTEGER DEFAULT 0"),
        ('max_attempts', "INTEGER DEFAULT 2"),
        ('timeout_seconds', "INTEGER DEFAULT 300"),
        ('last_error_code', "TEXT DEFAULT ''"),
    ]:
        ensure_column('topology_discovery_runs', col, dtype)
    for col, dtype in [
        ('attempt_count', "INTEGER DEFAULT 0"),
        ('last_attempt_at', "TEXT"),
    ]:
        ensure_column('topology_discovery_run_devices', col, dtype)
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_topology_runs_idempotency ON topology_discovery_runs(idempotency_key) WHERE idempotency_key <> \'\'')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_runs_lease ON topology_discovery_runs(status, lease_expires_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_run_devices_status ON topology_discovery_run_devices(run_id, status)')

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
        source_site_id TEXT DEFAULT '',
        match_method TEXT DEFAULT '',
        match_status TEXT DEFAULT 'unmatched',
        match_candidates_json TEXT DEFAULT '[]',
        first_seen_at TEXT,
        last_seen_at TEXT,
        miss_count INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY (source_device_id) REFERENCES devices(id),
        FOREIGN KEY (target_device_id) REFERENCES devices(id),
        FOREIGN KEY (discovery_run_id) REFERENCES topology_discovery_runs(id)
    )
    ''')
    for col, dtype in [
        ('first_seen_at', "TEXT"),
        ('last_seen_at', "TEXT"),
        ('miss_count', "INTEGER DEFAULT 0"),
        ('is_active', "INTEGER DEFAULT 1"),
    ]:
        # Existing PostgreSQL installations need the additive columns before
        # the baseline indexes are created; migrations will backfill values.
        ensure_column('topology_observations', col, dtype)
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_topology_obs_unique ON topology_observations(source_device_id, source_port_normalized, neighbor_name_normalized, target_device_id, target_port_normalized, protocol)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_obs_target ON topology_observations(target_device_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_obs_collected_at ON topology_observations(collected_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_observations_run_collected ON topology_observations(discovery_run_id, collected_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topology_observations_active ON topology_observations(source_device_id, is_active, last_seen_at)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS device_collection_status (
        device_id TEXT NOT NULL,
        collector TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'unknown',
        transport TEXT DEFAULT '',
        source TEXT DEFAULT '',
        last_attempt_at TEXT,
        last_success_at TEXT,
        duration_ms REAL,
        consecutive_failures INTEGER DEFAULT 0,
        coverage_total INTEGER DEFAULT 0,
        coverage_supported INTEGER DEFAULT 0,
        error_code TEXT DEFAULT '',
        error_message TEXT DEFAULT '',
        metadata_json TEXT DEFAULT '{}',
        next_retry_at TEXT,
        failure_class TEXT DEFAULT '',
        circuit_state TEXT DEFAULT 'closed',
        last_failure_at TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (device_id, collector),
        FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
    )
    ''')
    for col, dtype in [
        ('next_retry_at', "TEXT"),
        ('failure_class', "TEXT DEFAULT ''"),
        ('circuit_state', "TEXT DEFAULT 'closed'"),
        ('last_failure_at', "TEXT"),
    ]:
        ensure_column('device_collection_status', col, dtype)
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_collection_status_collector_status ON device_collection_status(collector, status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_collection_status_last_success ON device_collection_status(last_success_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_collection_status_retry ON device_collection_status(collector, circuit_state, next_retry_at)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS collector_sweep_state (
        collector TEXT PRIMARY KEY,
        cursor_position INTEGER NOT NULL DEFAULT 0,
        last_run_id TEXT DEFAULT '',
        last_started_at TEXT,
        last_completed_at TEXT,
        last_eligible INTEGER NOT NULL DEFAULT 0,
        last_selected INTEGER NOT NULL DEFAULT 0,
        last_batch_size INTEGER NOT NULL DEFAULT 0,
        last_successful INTEGER NOT NULL DEFAULT 0,
        last_failed INTEGER NOT NULL DEFAULT 0,
        last_collected INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_collector_sweep_completed ON collector_sweep_state(last_completed_at)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS collector_task_queue (
        id TEXT PRIMARY KEY,
        collector TEXT NOT NULL,
        device_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        priority INTEGER NOT NULL DEFAULT 100,
        available_at TEXT NOT NULL,
        lease_owner TEXT DEFAULT '',
        lease_until TEXT,
        attempt INTEGER NOT NULL DEFAULT 0,
        error_class TEXT DEFAULT '',
        error_message TEXT DEFAULT '',
        payload_json TEXT DEFAULT '{}',
        result_json TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE (collector, device_id),
        FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_collector_task_claim ON collector_task_queue(collector, status, available_at, priority)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_collector_task_lease ON collector_task_queue(collector, lease_until)')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS collector_worker_slots (
        collector TEXT NOT NULL,
        slot_id INTEGER NOT NULL,
        task_id TEXT,
        lease_owner TEXT DEFAULT '',
        lease_until TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (collector, slot_id),
        UNIQUE (collector, task_id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_collector_worker_slot_lease ON collector_worker_slots(collector, lease_until)')

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
    ensure_column('audit_events', 'request_id', "TEXT DEFAULT ''")
    ensure_column('audit_events', 'before_json', "TEXT DEFAULT '{}'")
    ensure_column('audit_events', 'after_json', "TEXT DEFAULT '{}'")

    # Enterprise CMDB/IPAM observations, reconciliation, jobs and scoped access.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS discovery_runs (
        id TEXT PRIMARY KEY,
        run_type TEXT NOT NULL DEFAULT 'network',
        status TEXT NOT NULL DEFAULT 'queued',
        requested_by TEXT DEFAULT 'system',
        scope_json TEXT DEFAULT '{}',
        started_at TEXT NOT NULL,
        completed_at TEXT,
        summary_json TEXT DEFAULT '{}'
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_discovery_runs_status ON discovery_runs(status)')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS discovery_observations (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        source_device_id TEXT,
        source_type TEXT NOT NULL,
        observed_type TEXT NOT NULL,
        observed_key TEXT NOT NULL,
        payload_json TEXT DEFAULT '{}',
        confidence REAL DEFAULT 0.5,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY (run_id) REFERENCES discovery_runs(id) ON DELETE CASCADE,
        FOREIGN KEY (source_device_id) REFERENCES devices(id) ON DELETE SET NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_discovery_observations_run ON discovery_observations(run_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_discovery_observations_key ON discovery_observations(observed_type, observed_key)')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reconciliation_runs (
        id TEXT PRIMARY KEY,
        discovery_run_id TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        requested_by TEXT DEFAULT 'system',
        started_at TEXT NOT NULL,
        completed_at TEXT,
        total_findings INTEGER DEFAULT 0,
        open_findings INTEGER DEFAULT 0,
        summary_json TEXT DEFAULT '{}',
        FOREIGN KEY (discovery_run_id) REFERENCES discovery_runs(id) ON DELETE SET NULL
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reconciliation_findings (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        observation_id TEXT,
        finding_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        risk_level TEXT NOT NULL DEFAULT 'medium',
        target_type TEXT,
        target_id TEXT,
        tenant_id TEXT,
        site_id TEXT,
        observed_json TEXT DEFAULT '{}',
        current_json TEXT DEFAULT '{}',
        proposed_json TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        resolved_at TEXT,
        resolved_by TEXT,
        FOREIGN KEY (run_id) REFERENCES reconciliation_runs(id) ON DELETE CASCADE,
        FOREIGN KEY (observation_id) REFERENCES discovery_observations(id) ON DELETE SET NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_reconciliation_findings_run_status ON reconciliation_findings(run_id, status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_reconciliation_findings_type ON reconciliation_findings(finding_type)')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reconciliation_actions (
        id TEXT PRIMARY KEY,
        finding_id TEXT NOT NULL,
        action_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        requested_by TEXT NOT NULL,
        approved_by TEXT,
        payload_json TEXT DEFAULT '{}',
        result_json TEXT DEFAULT '{}',
        error_message TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        applied_at TEXT,
        FOREIGN KEY (finding_id) REFERENCES reconciliation_findings(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_reconciliation_actions_finding ON reconciliation_actions(finding_id)')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS job_steps (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        step_name TEXT NOT NULL,
        step_order INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'queued',
        started_at TEXT,
        finished_at TEXT,
        error_message TEXT DEFAULT '',
        result_json TEXT DEFAULT '{}',
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_job_steps_job ON job_steps(job_id, step_order)')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS job_targets (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        target_type TEXT NOT NULL DEFAULT 'device',
        target_id TEXT NOT NULL,
        site_id TEXT,
        vendor TEXT,
        status TEXT NOT NULL DEFAULT 'queued',
        attempt_count INTEGER DEFAULT 0,
        started_at TEXT,
        finished_at TEXT,
        error_message TEXT DEFAULT '',
        result_json TEXT DEFAULT '{}',
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_job_targets_job_status ON job_targets(job_id, status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_job_targets_device_lock ON job_targets(target_type, target_id, status)')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS job_artifacts (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        artifact_type TEXT NOT NULL,
        name TEXT NOT NULL,
        uri TEXT NOT NULL,
        metadata_json TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS job_events (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        severity TEXT DEFAULT 'info',
        message TEXT NOT NULL,
        details_json TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_job_events_job_time ON job_events(job_id, created_at)')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_resource_scopes (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        resource_type TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        scope_id TEXT NOT NULL DEFAULT '',
        actions_json TEXT DEFAULT '[]',
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_user_resource_scope ON user_resource_scopes(user_id, resource_type, scope_type, scope_id)')

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
        out_discards INTEGER,
        fcs_errors INTEGER,
        frame_too_long_errors INTEGER,
        mac_rx_errors INTEGER,
        symbol_errors INTEGER,
        packet_counter_source TEXT,
        fcs_source TEXT
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
        fcs_sum INTEGER DEFAULT 0,
        PRIMARY KEY (ts_minute, device_id, interface_name)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_interface_telemetry_1m_ts ON interface_telemetry_1m(ts_minute)')

    # Server/Host telemetry raw samples (7-day retention)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS device_telemetry_samples (
        ts TEXT NOT NULL,
        device_id TEXT NOT NULL,
        cpu_load REAL,
        cpu_util REAL,
        mem_avail REAL,
        swap_util REAL,
        io_wait REAL,
        io_latency REAL,
        disk_util REAL,
        inode_util REAL,
        tcp_conns INTEGER,
        tcp_retrans REAL,
        tcp_estab INTEGER,
        tcp_time_wait INTEGER,
        tcp_close_wait INTEGER,
        tcp_syn_recv INTEGER,
        tcp_listen INTEGER,
        process_health INTEGER,
        service_sshd INTEGER DEFAULT 0,
        service_crond INTEGER DEFAULT 0,
        service_docker INTEGER DEFAULT 0,
        PRIMARY KEY (ts, device_id),
        FOREIGN KEY (device_id) REFERENCES devices(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_device_telemetry_samples_ts ON device_telemetry_samples(ts)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_device_telemetry_samples_dev_ts ON device_telemetry_samples(device_id, ts)')

    # Server/Host telemetry hourly rollup samples (90-day retention)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS device_telemetry_hourly (
        ts_hour TEXT NOT NULL,
        device_id TEXT NOT NULL,
        samples INTEGER DEFAULT 0,
        avg_cpu_load REAL,
        max_cpu_load REAL,
        avg_cpu_util REAL,
        max_cpu_util REAL,
        avg_mem_avail REAL,
        max_mem_avail REAL,
        avg_swap_util REAL,
        max_swap_util REAL,
        avg_io_wait REAL,
        max_io_wait REAL,
        avg_io_latency REAL,
        max_io_latency REAL,
        avg_disk_util REAL,
        max_disk_util REAL,
        avg_inode_util REAL,
        max_inode_util REAL,
        avg_tcp_conns REAL,
        max_tcp_conns REAL,
        avg_tcp_retrans REAL,
        max_tcp_retrans REAL,
        avg_tcp_estab REAL,
        max_tcp_estab REAL,
        avg_tcp_time_wait REAL,
        max_tcp_time_wait REAL,
        avg_tcp_close_wait REAL,
        max_tcp_close_wait REAL,
        avg_tcp_syn_recv REAL,
        max_tcp_syn_recv REAL,
        avg_tcp_listen REAL,
        max_tcp_listen REAL,
        avg_process_health REAL,
        PRIMARY KEY (ts_hour, device_id),
        FOREIGN KEY (device_id) REFERENCES devices(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_device_telemetry_hourly_ts ON device_telemetry_hourly(ts_hour)')

    # Migration: extend telemetry tables with IO latency + per-state TCP metrics.
    # (Older DBs created before these columns existed need them backfilled.)
    for _col, _type in (
        ('io_latency', 'REAL'),
        ('tcp_retrans', 'REAL'),
        ('tcp_estab', 'INTEGER'),
        ('tcp_time_wait', 'INTEGER'),
        ('tcp_close_wait', 'INTEGER'),
        ('tcp_syn_recv', 'INTEGER'),
        ('tcp_listen', 'INTEGER'),
    ):
        ensure_column('device_telemetry_samples', _col, _type)
    for _base in ('io_latency', 'tcp_retrans', 'tcp_estab', 'tcp_time_wait', 'tcp_close_wait', 'tcp_syn_recv', 'tcp_listen'):
        ensure_column('device_telemetry_hourly', f'avg_{_base}', 'REAL')
        ensure_column('device_telemetry_hourly', f'max_{_base}', 'REAL')


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
    if 'snmp_community' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN snmp_community TEXT DEFAULT "public"')
    if 'snmp_port' not in columns:
        cursor.execute('ALTER TABLE devices ADD COLUMN snmp_port INTEGER DEFAULT 161')
    if 'snmp_cpu_oid' not in columns:
        cursor.execute("ALTER TABLE devices ADD COLUMN snmp_cpu_oid TEXT DEFAULT ''")
    if 'snmp_memory_oid' not in columns:
        cursor.execute("ALTER TABLE devices ADD COLUMN snmp_memory_oid TEXT DEFAULT ''")
    if 'snmp_metric_profile_id' not in columns:
        cursor.execute("ALTER TABLE devices ADD COLUMN snmp_metric_profile_id TEXT DEFAULT ''")
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
        if 'fcs_errors' not in raw_columns:
            cursor.execute('ALTER TABLE interface_telemetry_raw ADD COLUMN fcs_errors INTEGER')
        if 'frame_too_long_errors' not in raw_columns:
            cursor.execute('ALTER TABLE interface_telemetry_raw ADD COLUMN frame_too_long_errors INTEGER')
        if 'mac_rx_errors' not in raw_columns:
            cursor.execute('ALTER TABLE interface_telemetry_raw ADD COLUMN mac_rx_errors INTEGER')
        if 'symbol_errors' not in raw_columns:
            cursor.execute('ALTER TABLE interface_telemetry_raw ADD COLUMN symbol_errors INTEGER')
        if 'packet_counter_source' not in raw_columns:
            cursor.execute('ALTER TABLE interface_telemetry_raw ADD COLUMN packet_counter_source TEXT')
        if 'fcs_source' not in raw_columns:
            cursor.execute('ALTER TABLE interface_telemetry_raw ADD COLUMN fcs_source TEXT')

    # Migration for interface_telemetry_1m table
    rollup_columns = _table_columns(cursor, 'interface_telemetry_1m')
    if rollup_columns:
        if 'in_pkts_sum' not in rollup_columns:
            cursor.execute('ALTER TABLE interface_telemetry_1m ADD COLUMN in_pkts_sum INTEGER DEFAULT 0')
        if 'out_pkts_sum' not in rollup_columns:
            cursor.execute('ALTER TABLE interface_telemetry_1m ADD COLUMN out_pkts_sum INTEGER DEFAULT 0')
        if 'fcs_sum' not in rollup_columns:
            cursor.execute('ALTER TABLE interface_telemetry_1m ADD COLUMN fcs_sum INTEGER DEFAULT 0')

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
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS config_baselines (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        config_type TEXT NOT NULL DEFAULT 'running',
        snapshot_id TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        set_by TEXT NOT NULL DEFAULT '',
        set_at TEXT NOT NULL,
        UNIQUE(device_id, config_type)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_config_baselines_snapshot ON config_baselines(snapshot_id)')

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
        FOREIGN KEY (subnet_id) REFERENCES prefixes(id)
    )
    ''')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_ip_addr_unique ON ip_addresses(subnet_id, address)')

    ensure_column('ip_addresses', 'device_type', "TEXT DEFAULT ''")
    ensure_column('ip_addresses', 'ip_address', "TEXT DEFAULT ''")
    ensure_column('ip_addresses', 'prefix_id', "TEXT DEFAULT ''")
    ensure_column('ip_addresses', 'vrf_id', "TEXT DEFAULT ''")
    ensure_column('ip_addresses', 'tenant_id', "TEXT DEFAULT 'tenant-default'")
    ensure_column('ip_addresses', 'site_id', "TEXT DEFAULT ''")
    ensure_column('ip_addresses', 'interface_id', "TEXT DEFAULT ''")
    ensure_column('ip_addresses', 'address_inet', "INET" if _USE_PG else "TEXT DEFAULT ''")
    ensure_column('ip_addresses', 'ip_version', "INTEGER DEFAULT 0")
    for col, dtype in [
        ('released_at', 'TEXT'),
        ('available_after', 'TEXT'),
        ('expires_at', 'TEXT'),
        ('purpose', "TEXT DEFAULT ''"),
        ('requested_by', "TEXT DEFAULT ''"),
        ('source_type', "TEXT DEFAULT 'manual'"),
        ('source_ref', "TEXT DEFAULT ''"),
        ('last_confirmed_at', 'TEXT'),
        ('confirmed_by', "TEXT DEFAULT ''"),
    ]:
        ensure_column('ip_addresses', col, dtype)

    for table_name in ('devices', 'interfaces', 'prefixes'):
        for col, dtype in [
            ('source_type', "TEXT DEFAULT 'manual'"),
            ('source_ref', "TEXT DEFAULT ''"),
            ('confidence', 'REAL DEFAULT 1.0'),
            ('last_confirmed_at', 'TEXT'),
            ('last_observed_at', 'TEXT'),
            ('confirmed_by', "TEXT DEFAULT ''"),
        ]:
            ensure_column(table_name, col, dtype)

    # Fresh PostgreSQL baselines must add the device-to-asset relation before
    # creating its partial unique index.  Older installations already have
    # the column, while a new baseline otherwise leaves the transaction
    # aborted after PostgreSQL reports an undefined column.
    ensure_column('devices', 'asset_id', "TEXT")
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_asset_id ON devices(asset_id) WHERE asset_id IS NOT NULL AND asset_id <> ''")
    except Exception as _asset_unique_exc:
        logger.warning("Asset/device unique index deferred because historical duplicates exist: %s", _asset_unique_exc)
    try:
        if _USE_PG:
            cursor.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_ip_addresses_scope_active
                ON ip_addresses(tenant_id, vrf_id, address_inet)
                WHERE address_inet IS NOT NULL
                  AND COALESCE(status, 'active') NOT IN ('released', 'available')""")
        else:
            cursor.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_ip_addresses_scope_active
                ON ip_addresses(tenant_id, vrf_id, address_inet)
                WHERE address_inet IS NOT NULL AND address_inet <> ''
                  AND COALESCE(status, 'active') NOT IN ('released', 'available')""")
    except Exception as _ip_unique_exc:
        logger.warning("IPAM active-address unique index deferred because historical conflicts exist: %s", _ip_unique_exc)

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
        site_id TEXT DEFAULT '',
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
    # Legacy PostgreSQL installations may have physical_assets without the
    # canonical site relation. Ensure the column before creating its index;
    # this is a schema-shape guard only and deliberately performs no backfill.
    ensure_column('physical_assets', 'site_id', "TEXT DEFAULT ''")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_tag ON physical_assets(asset_tag) WHERE asset_tag != ''")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_asset_type ON physical_assets(asset_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_physical_assets_site_id ON physical_assets(site_id)')

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
    ensure_column('physical_assets', 'credential_id', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'admin_credential_id', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'snmp_credential_id', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'credential_source', "TEXT DEFAULT 'local'")
    ensure_column('physical_assets', 'vault_path', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'requires_strict_audit', "INTEGER DEFAULT 1")
    ensure_column('physical_assets', 'snmp_community', "TEXT DEFAULT 'public'")
    ensure_column('physical_assets', 'snmp_port', "INTEGER DEFAULT 161")
    ensure_column('physical_assets', 'management_port', "INTEGER DEFAULT 22")
    ensure_column('physical_assets', 'is_managed', "INTEGER DEFAULT 0")
    ensure_column('physical_assets', 'takeover_error', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'credential_governance_mode', "TEXT DEFAULT 'managed'")
    ensure_column('physical_assets', 'takeover_exempt_reason', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'takeover_exempt_at', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'asset_origin', "TEXT DEFAULT 'new'")
    for col, dtype in [
        ('source_type', "TEXT DEFAULT 'manual'"),
        ('source_ref', "TEXT DEFAULT ''"),
        ('confidence', 'REAL DEFAULT 1.0'),
        ('last_confirmed_at', 'TEXT'),
        ('last_observed_at', 'TEXT'),
        ('confirmed_by', "TEXT DEFAULT ''"),
    ]:
        ensure_column('physical_assets', col, dtype)
    ensure_column('physical_assets', 'u_height', 'INTEGER NOT NULL DEFAULT 1')
    ensure_column('physical_assets', 'planned_start_u', 'INTEGER')
    ensure_column('physical_assets', 'device_category', "TEXT DEFAULT ''")
    # Topology semantics are asset attributes, not layout hints.  Keep these
    # columns in the baseline as well as m0115 so fresh and upgraded
    # installations expose the same asset/device contract.
    ensure_column('physical_assets', 'function', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'zone', "TEXT DEFAULT 'Unknown'")
    ensure_column('physical_assets', 'power_watts', "INTEGER DEFAULT 0")

    # Generic Web management entry points.  These belong to physical assets
    # rather than only linked network-device rows so server BMC/iLO/iDRAC
    # assets can use the same PAM Web workflow.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS asset_web_access_profiles (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        profile_name TEXT NOT NULL DEFAULT 'Web management',
        scheme TEXT NOT NULL DEFAULT 'https',
        port INTEGER NOT NULL DEFAULT 443,
        path TEXT NOT NULL DEFAULT '/',
        enabled INTEGER NOT NULL DEFAULT 1,
        credential_mode TEXT NOT NULL DEFAULT 'inherit_asset',
        normal_username TEXT NOT NULL DEFAULT '',
        normal_password TEXT NOT NULL DEFAULT '',
        admin_username TEXT NOT NULL DEFAULT '',
        admin_password TEXT NOT NULL DEFAULT '',
        credential_id TEXT NOT NULL DEFAULT '',
        admin_credential_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (asset_id) REFERENCES physical_assets(id) ON DELETE CASCADE,
        UNIQUE (asset_id, scheme, port, path)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_asset_web_profiles_asset ON asset_web_access_profiles(asset_id, enabled)')
    for col, dtype in [
        ('credential_mode', "TEXT NOT NULL DEFAULT 'inherit_asset'"),
        ('normal_username', "TEXT NOT NULL DEFAULT ''"),
        ('normal_password', "TEXT NOT NULL DEFAULT ''"),
        ('admin_username', "TEXT NOT NULL DEFAULT ''"),
        ('admin_password', "TEXT NOT NULL DEFAULT ''"),
        ('credential_id', "TEXT NOT NULL DEFAULT ''"),
        ('admin_credential_id', "TEXT NOT NULL DEFAULT ''"),
    ]:
        ensure_column('asset_web_access_profiles', col, dtype)

    ensure_column('devices', 'credential_id', 'TEXT')
    ensure_column('devices', 'admin_credential_id', "TEXT DEFAULT ''")
    ensure_column('devices', 'snmp_credential_id', "TEXT DEFAULT ''")
    ensure_column('devices', 'asset_id', 'TEXT')
    ensure_column('devices', 'vendor', "TEXT DEFAULT ''")
    ensure_column('devices', 'lifecycle_status', "TEXT DEFAULT 'staging'")
    ensure_column('devices', 'enable_password', "TEXT DEFAULT ''")
    ensure_column('devices', 'priv_username', "TEXT DEFAULT ''")
    ensure_column('devices', 'credential_source', "TEXT DEFAULT 'local'")
    ensure_column('devices', 'vault_path', "TEXT DEFAULT ''")
    ensure_column('devices', 'snmp_cpu_oid', "TEXT DEFAULT ''")
    ensure_column('devices', 'snmp_memory_oid', "TEXT DEFAULT ''")
    ensure_column('devices', 'onboarding_status', "TEXT DEFAULT 'active'")
    ensure_column('devices', 'onboarding_updated_at', "TEXT DEFAULT ''")
    ensure_column('devices', 'password_last_rotated', "TEXT DEFAULT ''")
    ensure_column('devices', 'password_expires_at', "TEXT DEFAULT ''")
    ensure_column('devices', 'rotation_status', "TEXT DEFAULT ''")
    ensure_column('devices', 'device_category', "TEXT DEFAULT ''")
    ensure_column('devices', 'function', "TEXT DEFAULT ''")
    ensure_column('devices', 'zone', "TEXT DEFAULT 'Unknown'")
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
        session_kind TEXT DEFAULT 'ssh_terminal',
        web_profile_id TEXT DEFAULT '',
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
    #
    # Soft-delete policy (Plan A): when an underlying asset is removed,
    # `assets.py` / `devices.py` set `asset_id = ''` and `archived = 1`
    # rather than dropping the row, so the audit trail survives.
    # The FK below uses ON DELETE SET NULL for fresh databases so that
    # even with PRAGMA foreign_keys=ON the cascade behavior is correct.
    # Existing databases were created with ON DELETE CASCADE; that FK is
    # currently inert because the connection layer does not enable
    # foreign_keys, and the application-level soft-delete is the source
    # of truth.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pam_sessions (
        id TEXT PRIMARY KEY,
        request_id TEXT DEFAULT '',
        asset_id TEXT DEFAULT '',
        device_id TEXT DEFAULT '',
        requester_username TEXT NOT NULL,
        access_level TEXT NOT NULL DEFAULT 'normal',
        session_kind TEXT DEFAULT 'ssh_terminal',
        login_username TEXT DEFAULT '',
        connect_method TEXT DEFAULT 'web',
        target_ip TEXT DEFAULT '',
        target_port INTEGER DEFAULT 22,
        target_scheme TEXT DEFAULT '',
        target_path TEXT DEFAULT '/',
        web_profile_id TEXT DEFAULT '',
        agent_id TEXT DEFAULT '',
        agent_token_hash TEXT DEFAULT '',
        last_heartbeat_at TEXT,
        recording_status TEXT DEFAULT 'not_started',
        status TEXT NOT NULL DEFAULT 'connecting',
        connected_at TEXT,
        closed_at TEXT,
        close_reason TEXT DEFAULT '',
        duration_seconds INTEGER DEFAULT 0,
        command_count INTEGER DEFAULT 0,
        recording_path TEXT DEFAULT '',
        risk_level TEXT DEFAULT 'low',
        risk_summary TEXT DEFAULT '',
        target_hostname TEXT DEFAULT '',
        archived INTEGER DEFAULT 0,
        session_token TEXT UNIQUE,
        token_expires_at TEXT NOT NULL,
        token_consumed INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (asset_id) REFERENCES physical_assets(id) ON DELETE SET NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pam_sessions_status ON pam_sessions(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pam_sessions_user ON pam_sessions(requester_username)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pam_sessions_asset ON pam_sessions(asset_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pam_sessions_created ON pam_sessions(created_at)')

    pam_req_cols = _table_columns(cursor, 'pam_access_requests')
    if pam_req_cols and 'session_id' not in pam_req_cols:
        cursor.execute("ALTER TABLE pam_access_requests ADD COLUMN session_id TEXT DEFAULT ''")
    if pam_req_cols and 'session_kind' not in pam_req_cols:
        cursor.execute("ALTER TABLE pam_access_requests ADD COLUMN session_kind TEXT DEFAULT 'ssh_terminal'")
    if pam_req_cols and 'web_profile_id' not in pam_req_cols:
        cursor.execute("ALTER TABLE pam_access_requests ADD COLUMN web_profile_id TEXT DEFAULT ''")

    pam_ses_cols = _table_columns(cursor, 'pam_sessions')
    if pam_ses_cols and 'session_kind' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN session_kind TEXT DEFAULT 'ssh_terminal'")
    if pam_ses_cols and 'target_scheme' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN target_scheme TEXT DEFAULT ''")
    if pam_ses_cols and 'target_path' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN target_path TEXT DEFAULT '/' ")
    if pam_ses_cols and 'web_profile_id' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN web_profile_id TEXT DEFAULT ''")
    if pam_ses_cols and 'agent_id' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN agent_id TEXT DEFAULT ''")
    if pam_ses_cols and 'agent_token_hash' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN agent_token_hash TEXT DEFAULT ''")
    if pam_ses_cols and 'last_heartbeat_at' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN last_heartbeat_at TEXT")
    if pam_ses_cols and 'recording_status' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN recording_status TEXT DEFAULT 'not_started'")
    if pam_ses_cols and 'risk_level' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN risk_level TEXT DEFAULT 'low'")
    if pam_ses_cols and 'risk_summary' not in pam_ses_cols:
        cursor.execute("ALTER TABLE pam_sessions ADD COLUMN risk_summary TEXT DEFAULT ''")

    # Soft-delete support: snapshot the asset hostname at session creation time
    # so the audit trail remains identifiable after the underlying asset/device
    # is removed (asset_id is then cleared but the row itself is preserved).
    ensure_column('pam_sessions', 'tenant_id', "TEXT DEFAULT 'tenant-default'")
    ensure_column('pam_sessions', 'target_hostname', "TEXT DEFAULT ''")
    ensure_column('pam_sessions', 'archived', 'INTEGER DEFAULT 0')

    # Soft-delete migration: relax the asset_id NOT NULL constraint and switch
    # the FK from ON DELETE CASCADE to ON DELETE SET NULL on existing PG
    # databases so that deleting an asset preserves the audit row. The CREATE
    # TABLE above already encodes this for fresh databases; here we patch
    # legacy installations in-place. SQLite cannot ALTER FK / NOT NULL, but
    # its FK enforcement is also off in our connection layer so the cascade
    # never fires there — the application-level soft-delete is the source
    # of truth for SQLite.
    if _USE_PG:
        for _tbl in ('pam_sessions', 'pam_access_requests'):
            try:
                cursor.execute(f"ALTER TABLE {_tbl} ALTER COLUMN asset_id DROP NOT NULL")
            except Exception as _exc:
                logger.debug("[migration] %s.asset_id DROP NOT NULL skipped: %s", _tbl, _exc)
            try:
                cursor.execute(
                    "SELECT conname FROM pg_constraint c "
                    "JOIN pg_class t ON c.conrelid = t.oid "
                    "WHERE t.relname = %s AND c.contype = 'f' "
                    "AND pg_get_constraintdef(c.oid) ILIKE '%%asset_id%%REFERENCES%%physical_assets%%' "
                    "AND pg_get_constraintdef(c.oid) ILIKE '%%CASCADE%%'",
                    (_tbl,)
                )
                for (conname,) in list(cursor.fetchall()):
                    cursor.execute(f'ALTER TABLE {_tbl} DROP CONSTRAINT "{conname}"')
                    logger.info("[migration] Dropped CASCADE FK %s on %s", conname, _tbl)
                # Re-create only if no asset_id FK exists at all now.
                cursor.execute(
                    "SELECT 1 FROM pg_constraint c JOIN pg_class t ON c.conrelid = t.oid "
                    "WHERE t.relname = %s AND c.contype = 'f' "
                    "AND pg_get_constraintdef(c.oid) ILIKE '%%asset_id%%REFERENCES%%physical_assets%%'",
                    (_tbl,)
                )
                if not cursor.fetchone():
                    cursor.execute(
                        f"ALTER TABLE {_tbl} ADD CONSTRAINT {_tbl}_asset_id_fkey "
                        f"FOREIGN KEY (asset_id) REFERENCES physical_assets(id) ON DELETE SET NULL"
                    )
                    logger.info("[migration] Re-created %s.asset_id FK as ON DELETE SET NULL", _tbl)
            except Exception as _exc:
                logger.warning("[migration] Failed to update %s.asset_id FK to SET NULL: %s", _tbl, _exc)

    # Auto-link existing devices to matching assets
    unlinked = cursor.execute(
        "SELECT id, hostname, ip_address, sn, model, role, site, site_id, vendor, status, lifecycle_status FROM devices WHERE (asset_id IS NULL OR asset_id = '')"
    ).fetchall()
    if unlinked:
        for dev in unlinked:
            match = cursor.execute(
                """SELECT pa.id
                   FROM physical_assets pa
                   WHERE pa.asset_type = 'network_device'
                     AND (pa.hostname = ? OR pa.management_ip = ?)
                     AND NOT EXISTS (
                         SELECT 1 FROM devices d2
                         WHERE d2.asset_id = pa.id AND d2.id <> ?
                     )
                   ORDER BY pa.id
                   LIMIT 1""",
                (dev['hostname'], dev['ip_address'], dev['id'])
            ).fetchone()
            if match:
                cursor.execute('UPDATE devices SET asset_id = ? WHERE id = ?', (match['id'], dev['id']))
            else:
                # Identity fields on physical_assets are globally unique. A
                # legacy/shared database can contain two CMDB devices with
                # the same hostname or management IP; keep the second device
                # unlinked rather than failing the entire bootstrap while
                # trying to create a duplicate asset.
                identity_checks = []
                identity_params = []
                for column, value in (
                    ('hostname', dev['hostname']),
                    ('serial_number', dev['sn']),
                    ('management_ip', dev['ip_address']),
                ):
                    if str(value or '').strip():
                        identity_checks.append(f"LOWER(TRIM({column})) = LOWER(TRIM(?))")
                        identity_params.append(value)
                if identity_checks and cursor.execute(
                    "SELECT 1 FROM physical_assets WHERE " + " OR ".join(identity_checks) + " LIMIT 1",
                    identity_params,
                ).fetchone():
                    logger.warning(
                        "[migration] Leaving device %s unlinked because its asset identity is already in use",
                        dev['id'],
                    )
                    continue
                asset_id = f"asset-{uuid.uuid4().hex[:12]}"
                now_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
                cursor.execute('''
                    INSERT INTO physical_assets (
                        id, asset_type, asset_tag, serial_number, vendor, model, hostname,
                        site_id, rack, rack_unit, u_height, planned_start_u, management_ip, business_ip, device_role,
                        vlan, uplink_switch, uplink_port,
                        status, purchase_date, warranty_expiry, department, notes, created_at, updated_at, lifecycle_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    asset_id, 'network_device', '', dev['sn'] or '', dev['vendor'] or '',
                    dev['model'] or '', dev['hostname'] or '',
                    dev['site_id'] or dev['site'] or '', '', '', 1, None,
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

    # Unified metadata/tag system. This is intentionally a clean schema: the
    # platform uses stable tag codes and a resource-agnostic assignment table.
    # The product has explicitly chosen a clean cut-over, so an old tag schema
    # is removed in-place. No device, credential, user, or asset table is
    # touched here.
    try:
        existing_tag_columns = _table_columns(cursor, 'tag_definitions')
        if existing_tag_columns and 'code' not in existing_tag_columns:
            for old_table in ('tag_assignment_history', 'tag_assignments', 'device_tags', 'tag_definitions', 'tag_categories'):
                cursor.execute(f'DROP TABLE IF EXISTS {old_table}')
    except Exception:
        logger.exception('Failed to inspect/reset the legacy tag schema')
        raise
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tag_categories (
        code TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        label_zh TEXT DEFAULT '',
        description TEXT DEFAULT '',
        exclusive INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0,
        is_system INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tag_definitions (
        id TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        code TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL,
        label_zh TEXT DEFAULT '',
        color TEXT DEFAULT '',
        icon TEXT DEFAULT '',
        description TEXT DEFAULT '',
        resource_types TEXT DEFAULT '["device"]',
        exclusive_group TEXT DEFAULT '',
        priority INTEGER DEFAULT 0,
        source_type TEXT NOT NULL DEFAULT 'manual',
        is_system INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        built_in INTEGER DEFAULT 0,
        created_at TEXT DEFAULT '',
        updated_at TEXT DEFAULT '',
        FOREIGN KEY (category) REFERENCES tag_categories(code)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_definitions_category ON tag_definitions(category)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_definitions_active ON tag_definitions(is_active)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_definitions_source ON tag_definitions(source_type)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tag_assignments (
        resource_type TEXT NOT NULL,
        resource_id TEXT NOT NULL,
        tag_id TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'manual',
        rule_id TEXT DEFAULT '',
        inherited_from_type TEXT DEFAULT '',
        inherited_from_id TEXT DEFAULT '',
        expires_at TEXT DEFAULT '',
        created_at TEXT DEFAULT '',
        created_by TEXT DEFAULT '',
        PRIMARY KEY (resource_type, resource_id, tag_id),
        FOREIGN KEY (tag_id) REFERENCES tag_definitions(id)
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_assignments_resource ON tag_assignments(resource_type, resource_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_assignments_tag ON tag_assignments(tag_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_assignments_source ON tag_assignments(source_type)')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tag_assignment_history (
        id TEXT PRIMARY KEY,
        resource_type TEXT NOT NULL,
        resource_id TEXT NOT NULL,
        tag_id TEXT NOT NULL,
        action TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'manual',
        rule_id TEXT DEFAULT '',
        operator TEXT DEFAULT '',
        reason TEXT DEFAULT '',
        occurred_at TEXT DEFAULT ''
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_history_resource ON tag_assignment_history(resource_type, resource_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_history_tag ON tag_assignment_history(tag_id)')

    # Rack Management Indexes and Columns
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_racks_name_dc ON racks(name, datacenter)')
    ensure_column('racks', 'power_capacity_watts', "INTEGER DEFAULT 0")

    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_device_types_model_vendor ON device_types(model, vendor)')
    ensure_column('device_types', 'power_watts', "INTEGER DEFAULT 0")

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

    # Path Measurements (路径性能遥测测量历史表)
    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS path_measurements (
        id {_SERIAL_PK},
        trace_id TEXT NOT NULL,
        src_ip TEXT NOT NULL,
        dst_ip TEXT NOT NULL,
        hop_index INTEGER NOT NULL,
        device_id INTEGER,
        device_name TEXT,
        interface_name TEXT,
        vrf_name TEXT DEFAULT 'default',
        vlan_id INTEGER,
        hop_ip TEXT,
        icmp_rtt REAL,
        tcp_rtt REAL,
        loss REAL DEFAULT 0.0,
        cpu_usage REAL,
        memory_usage REAL,
        status TEXT DEFAULT 'active',
        timestamp TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_path_meas_trace ON path_measurements(trace_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_path_meas_ips ON path_measurements(src_ip, dst_ip)')

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

    if _USE_PG:
        cursor.executemany(
            'INSERT INTO scripts (id, name, content, description, platform, category) '
            'VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET '
            'name = EXCLUDED.name, content = EXCLUDED.content, '
            'description = EXCLUDED.description, platform = EXCLUDED.platform, '
            'category = EXCLUDED.category',
            std_scripts
        )
    else:
        cursor.executemany(
            'INSERT INTO scripts (id, name, content, description, platform, category) '
            'VALUES (?,?,?,?,?,?) ON CONFLICT (id) DO UPDATE SET '
            'name = EXCLUDED.name, content = EXCLUDED.content, '
            'description = EXCLUDED.description, platform = EXCLUDED.platform, '
            'category = EXCLUDED.category',
            std_scripts
        )

    insp_script_ids = [
        'insp_cisco_ios_full', 'insp_cisco_nxos_full',
        'insp_huawei_vrp_full', 'insp_huawei_vrpv8_full',
        'insp_h3c_comware_full', 'insp_juniper_junos_full', 'insp_arista_eos_full',
        'insp_linux_full',
    ]
    for sid in insp_script_ids:
        stype = 'shell' if sid == 'insp_linux_full' else 'cli'
        cursor.execute(
            "UPDATE scripts SET script_type=?, status=?, author=?, "
            "submitter_name=?, approver_username=?, "
            "created_at=COALESCE(NULLIF(created_at, ''), ?), "
            "updated_at=? "
            "WHERE id=?",
            (stype, 'released', 'system', 'system', 'system', now, now, sid)
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

        valid_srv_ids = [item[0] for item in default_items if item[3] == 'Server']
        if valid_srv_ids:
            placeholders = ','.join(['%s' if _USE_PG else '?'] * len(valid_srv_ids))
            cursor.execute(
                f"DELETE FROM inspection_items WHERE category='Server' AND id NOT IN ({placeholders})",
                tuple(valid_srv_ids)
            )

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

    # ──────────────────────────────────────────────────────────────────
    # Performance indexes
    # ──────────────────────────────────────────────────────────────────
    # Hot-path tables that grow with device count / activity but were
    # missing covering indexes. Adding them is idempotent (`IF NOT EXISTS`)
    # and works on both PG and SQLite. Each index targets a query pattern
    # in the API layer that previously did a sequential scan.
    _perf_indexes = (
        # `jobs` — every list call orders by created_at DESC and may filter
        # on status / device_id; the table previously had zero indexes.
        'CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_jobs_device_id ON jobs(device_id)',
        'CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)',
        # `config_snapshots` — backup-stats N+1 and drift-scan both filter
        # by device_id and order by timestamp DESC; covered by composite.
        'CREATE INDEX IF NOT EXISTS idx_config_snapshots_device_ts ON config_snapshots(device_id, timestamp DESC)',
        'CREATE INDEX IF NOT EXISTS idx_config_snapshots_timestamp ON config_snapshots(timestamp DESC)',
        # `playbook_executions` — listing endpoint orders by created_at DESC
        # with optional status / scenario_id filters.
        'CREATE INDEX IF NOT EXISTS idx_playbook_executions_created_at ON playbook_executions(created_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_playbook_executions_status ON playbook_executions(status)',
        'CREATE INDEX IF NOT EXISTS idx_playbook_executions_scenario ON playbook_executions(scenario_id)',
        # `devices` — virtually every page filters by status and joins on asset_id.
        'CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status)',
        'CREATE INDEX IF NOT EXISTS idx_devices_asset_id ON devices(asset_id)',
        'CREATE INDEX IF NOT EXISTS idx_devices_site ON devices(site)',
        # `scripts` — list endpoint orders by updated_at DESC; UI filters by status.
        'CREATE INDEX IF NOT EXISTS idx_scripts_updated_at ON scripts(updated_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_scripts_status ON scripts(status)',
        # `alert_events` — alert desk filters by device_id; existing indexes
        # cover dedupe_key/created_at but not these.
        'CREATE INDEX IF NOT EXISTS idx_alert_events_device_id ON alert_events(device_id)',
    )
    for _idx_sql in _perf_indexes:
        try:
            cursor.execute(_idx_sql)
        except Exception as _exc:
            logger.debug("[migration] index skipped (%s): %s", _idx_sql.split(' ON ')[0], _exc)

    # ──────────────────────────────────────────────────────────────────
    # Data migration: Move passwords from devices to credentials table
    # ──────────────────────────────────────────────────────────────────
    try:
        devices_to_migrate = cursor.execute('''
            SELECT id, hostname, username, password, enable_password, snmp_community,
                   normal_username, normal_password, admin_username, admin_password,
                   credential_id
            FROM devices
            WHERE credential_id IS NULL OR credential_id = ''
        ''').fetchall()

        for dev in devices_to_migrate:
            d_id = dev['id']
            d_host = dev['hostname'] or d_id
            d_uname = dev['username'] or ''
            d_pwd = dev['password'] or ''
            d_en_pwd = dev['enable_password'] or ''
            d_snmp = dev['snmp_community'] or ''
            d_n_uname = dev['normal_username'] or ''
            d_n_pwd = dev['normal_password'] or ''
            d_a_uname = dev['admin_username'] or ''
            d_a_pwd = dev['admin_password'] or ''

            # Select the PRIVILEGED account, pairing each username with its OWN
            # password (mirrors the pre-decoupling backup logic which logged in as
            # admin first, then the primary account, then the normal account).
            # Picking the non-privileged "normal" account here was the regression
            # that broke config backup: the normal account lands at user-EXEC and
            # cannot run `show running-config`.
            if d_a_uname and d_a_pwd:
                uname, pwd = d_a_uname, d_a_pwd
            elif d_uname and d_pwd:
                uname, pwd = d_uname, d_pwd
            elif d_n_uname and d_n_pwd:
                uname, pwd = d_n_uname, d_n_pwd
            else:
                uname = d_a_uname or d_uname or d_n_uname or ''
                pwd = d_a_pwd or d_pwd or d_n_pwd or ''

            # Enable secret: explicit field, else fall back to the chosen login
            # password (matches the historical "enable_password = enable_pass or
            # login_pass" behaviour).
            d_en_pwd = d_en_pwd or pwd

            if not uname and not pwd and not d_en_pwd and not d_snmp:
                continue

            c_id = f"cred-{uuid.uuid4().hex[:12]}"
            c_name = f"cred-{d_host}-{d_id[:8]}"

            if _USE_PG:
                cursor.execute('''
                    INSERT INTO credentials (id, credential_name, credential_type, username, encrypted_password, enable_password, snmp_community, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (c_id, c_name, 'ssh_password', uname, pwd, d_en_pwd, d_snmp, now))
                cursor.execute('UPDATE devices SET credential_id = %s WHERE id = %s', (c_id, d_id))
            else:
                cursor.execute('''
                    INSERT INTO credentials (id, credential_name, credential_type, username, encrypted_password, enable_password, snmp_community, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (c_id, c_name, 'ssh_password', uname, pwd, d_en_pwd, d_snmp, now))
                cursor.execute('UPDATE devices SET credential_id = ? WHERE id = ?', (c_id, d_id))

        # NOTE: We intentionally do NOT wipe the devices.* credential columns here.
        # An earlier version cleared password/enable_password/admin_password/etc.
        # after migrating, which destroyed the privileged (admin) password and left
        # config backup unable to reach privileged EXEC. Keeping the columns intact
        # lets credential resolution fall back to them and avoids irreversible loss.
    except Exception as exc:
        logger.error(f"[migration] Failed to migrate credentials to credentials table: {exc}", exc_info=True)

    # ──────────────────────────────────────────────────────────────────
    # Data migration: Move interface data from devices to interfaces table
    # ──────────────────────────────────────────────────────────────────
    try:
        if _USE_PG:
            cursor.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'interfaces')")
            has_interfaces_table = cursor.fetchone()[0]
        else:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='interfaces'")
            has_interfaces_table = bool(cursor.fetchone())

        if has_interfaces_table:
            dev_cols = _table_columns(cursor, 'devices')
            if 'interface_data' in dev_cols:
                devices_with_interfaces = cursor.execute('SELECT id, hostname, interface_data FROM devices').fetchall()
                for dev in devices_with_interfaces:
                    dev_id = dev['id']
                    raw_intf_data = dev['interface_data']
                    if not raw_intf_data:
                        continue
                    try:
                        if isinstance(raw_intf_data, str):
                            intfs = json.loads(raw_intf_data)
                        else:
                            intfs = raw_intf_data
                    except Exception:
                        continue
                    if not isinstance(intfs, list):
                        continue

                    for iface in intfs:
                        if not isinstance(iface, dict):
                            continue
                        iname = iface.get('name')
                        if not iname:
                            continue
                        
                        if _USE_PG:
                            cursor.execute('SELECT 1 FROM interfaces WHERE device_id = %s AND interface_name = %s LIMIT 1', (dev_id, iname))
                        else:
                            cursor.execute('SELECT 1 FROM interfaces WHERE device_id = ? AND interface_name = ? LIMIT 1', (dev_id, iname))
                        if cursor.fetchone():
                            continue

                        intf_id = f"intf-{uuid.uuid4().hex[:12]}"
                        status = iface.get('status', 'down')
                        speed_mbps = float(iface.get('speed_mbps') or 0.0)
                        speed_bps = speed_mbps * 1_000_000.0
                        desc = iface.get('description', '')
                        mac = iface.get('mac_address', '')
                        
                        if _USE_PG:
                            cursor.execute('''
                                INSERT INTO interfaces (
                                    id, device_id, interface_name, description, admin_status, oper_status,
                                    mac_address, speed, bandwidth, duplex, interface_type, switchport_mode, ip_enabled
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ''', (intf_id, dev_id, iname, desc, status, status, mac, speed_bps, speed_bps, 'auto', 'physical', 'access', 0))
                        else:
                            cursor.execute('''
                                INSERT INTO interfaces (
                                    id, device_id, interface_name, description, admin_status, oper_status,
                                    mac_address, speed, bandwidth, duplex, interface_type, switchport_mode, ip_enabled
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (intf_id, dev_id, iname, desc, status, status, mac, speed_bps, speed_bps, 'auto', 'physical', 'access', 0))

    except Exception as exc:
        logger.error(f"[migration] Failed to migrate interfaces to interfaces table: {exc}", exc_info=True)


    # ──────────────────────────────────────────────────────────────────
    # Data migration: Phase 3 CMDB/IPAM Seeding and Migration
    # ──────────────────────────────────────────────────────────────────
    try:
        # 1. Seed default tenant
        cursor.execute("SELECT 1 FROM tenants WHERE id = 'tenant-default'")
        if not cursor.fetchone():
            if _USE_PG:
                cursor.execute("INSERT INTO tenants (id, name, description) VALUES (%s, %s, %s)",
                               ('tenant-default', 'Default Tenant', 'Default Tenant for NetOps Platform'))
            else:
                cursor.execute("INSERT INTO tenants (id, name, description) VALUES (?, ?, ?)",
                               ('tenant-default', 'Default Tenant', 'Default Tenant for NetOps Platform'))

        # 2. Seed default roles
        for r_id, r_name, r_desc in [
            ('role-admin', 'Administrator', 'Full Administrator Access'),
            ('role-operator', 'Operator', 'Operator Access with Read-Write'),
            ('role-viewer', 'Viewer', 'Read-Only Viewer Access')
        ]:
            if _USE_PG:
                cursor.execute("SELECT 1 FROM roles WHERE id = %s", (r_id,))
                if not cursor.fetchone():
                    cursor.execute("INSERT INTO roles (id, role_name, description) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (r_id, r_name, r_desc))
            else:
                cursor.execute("SELECT 1 FROM roles WHERE id = ?", (r_id,))
                if not cursor.fetchone():
                    cursor.execute("INSERT OR IGNORE INTO roles (id, role_name, description) VALUES (?, ?, ?)", (r_id, r_name, r_desc))

        # 3. Map default users
        cursor.execute("UPDATE users SET tenant_id = 'tenant-default', role_id = 'role-admin' WHERE username = 'admin' AND (tenant_id = '' OR tenant_id IS NULL)")

        # 4. Legacy devices.site values are not authoritative CMDB records.
        # Importing them on every boot made manually deleted sites reappear.
        # Keep the recovery path available, but require an explicit opt-in.
        legacy_cmdb_enabled = (
            allow_legacy_import or legacy_bootstrap_new
            or os.environ.get('NETOPS_MIGRATE_LEGACY_CMDB', '').strip().lower() in {'1', 'true', 'yes'}
        )
        if legacy_cmdb_enabled:
            cursor.execute("SELECT DISTINCT site FROM devices WHERE site IS NOT NULL AND site != ''")
            unique_sites = cursor.fetchall()
        else:
            unique_sites = []
        for site_row in unique_sites:
            s_name = site_row['site'] if hasattr(site_row, '__getitem__') else site_row[0]
            s_code = f"SITE_{s_name.upper().replace(' ', '_')}"
            cursor.execute("SELECT id FROM sites WHERE site_name = ? OR site_code = ?", (s_name, s_code))
            existing_site = cursor.fetchone()
            if existing_site:
                s_id = existing_site['id'] if hasattr(existing_site, '__getitem__') else existing_site[0]
            else:
                s_id = f"site-{uuid.uuid4().hex[:12]}"
                if _USE_PG:
                    cursor.execute("INSERT INTO sites (id, site_code, site_name, country, city, timezone, address, status, tenant_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                                   (s_id, s_code, s_name, '', '', 'Asia/Shanghai', '', 'active', 'tenant-default'))
                else:
                    cursor.execute("INSERT INTO sites (id, site_code, site_name, country, city, timezone, address, status, tenant_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (s_id, s_code, s_name, '', '', 'Asia/Shanghai', '', 'active', 'tenant-default'))
            # update devices
            cursor.execute("UPDATE devices SET site_id = ? WHERE site = ?", (s_id, s_name))

        # Seed the compatibility site only on first install (or explicit
        # legacy recovery). A later restart must not resurrect a user-deleted
        # default site.
        default_site_enabled = (
            allow_legacy_import or legacy_bootstrap_new
            or os.environ.get('NETOPS_MIGRATE_LEGACY_CMDB', '').strip().lower() in {'1', 'true', 'yes'}
        )
        if default_site_enabled:
            cursor.execute("SELECT 1 FROM sites WHERE id = 'site-default'")
            if not cursor.fetchone():
                if _USE_PG:
                    cursor.execute("INSERT INTO sites (id, site_code, site_name, country, city, timezone, address, status, tenant_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                                   ('site-default', 'DEFAULT_SITE', 'Default Site', '', '', 'Asia/Shanghai', '', 'active', 'tenant-default'))
                else:
                    cursor.execute("INSERT INTO sites (id, site_code, site_name, country, city, timezone, address, status, tenant_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   ('site-default', 'DEFAULT_SITE', 'Default Site', '', '', 'Asia/Shanghai', '', 'active', 'tenant-default'))
        cursor.execute(
            "UPDATE devices SET site_id = 'site-default' "
            "WHERE (site_id = '' OR site_id IS NULL) "
            "AND EXISTS (SELECT 1 FROM sites WHERE id = 'site-default')"
        )

        # 5. Seed device types from devices
        cursor.execute("SELECT DISTINCT vendor, model FROM devices WHERE model IS NOT NULL AND model != ''")
        unique_types = cursor.fetchall()
        for type_row in unique_types:
            vendor = type_row['vendor'] if hasattr(type_row, '__getitem__') else type_row[0]
            model = type_row['model'] if hasattr(type_row, '__getitem__') else type_row[1]
            if not vendor:
                vendor = 'Unknown'
            cursor.execute("SELECT id FROM device_types WHERE vendor = ? AND model = ?", (vendor, model))
            existing_type = cursor.fetchone()
            if existing_type:
                dt_id = existing_type['id'] if hasattr(existing_type, '__getitem__') else existing_type[0]
            else:
                dt_id = f"devtype-{uuid.uuid4().hex[:12]}"
                if _USE_PG:
                    cursor.execute("INSERT INTO device_types (id, vendor, model, part_number, u_height, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                                   (dt_id, vendor, model, '', 1, now, now))
                else:
                    cursor.execute("INSERT INTO device_types (id, vendor, model, part_number, u_height, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (dt_id, vendor, model, '', 1, now, now))
            cursor.execute("UPDATE devices SET device_type_id = ? WHERE vendor = ? AND model = ?", (dt_id, vendor, model))

        # 6. Migrate ip_inventory to ip_addresses and prefixes
        import ipaddress
        # ``ip_inventory`` is a legacy collection table.  The old bootstrap
        # imported it on every restart, which resurrected prefixes that an
        # operator had deliberately deleted. Legacy import is now opt-in for
        # an explicit one-time recovery run; normal startup reads only the
        # canonical IPAM tables.
        legacy_ipam_enabled = (
            allow_legacy_import or legacy_bootstrap_new
            or os.environ.get('NETOPS_MIGRATE_LEGACY_IPAM', '').strip().lower() in {'1', 'true', 'yes'}
        )
        if legacy_ipam_enabled:
            cursor.execute("SELECT ip, mask, device_id, interface, type, last_seen FROM ip_inventory")
            inv_rows = cursor.fetchall()
        else:
            inv_rows = []

        # Fetch current prefixes for in-memory CIDR parent resolution
        cursor.execute("SELECT id, prefix FROM prefixes")
        existing_prefixes = [dict(r) if hasattr(r, '__getitem__') else {'id': r[0], 'prefix': r[1]} for r in cursor.fetchall()]

        for inv in inv_rows:
            ip = inv['ip'] if hasattr(inv, '__getitem__') else inv[0]
            mask = inv['mask'] if hasattr(inv, '__getitem__') else inv[1]
            d_id = inv['device_id'] if hasattr(inv, '__getitem__') else inv[2]
            interface = inv['interface'] if hasattr(inv, '__getitem__') else inv[3]
            itype = inv['type'] if hasattr(inv, '__getitem__') else inv[4]
            last_seen = inv['last_seen'] if hasattr(inv, '__getitem__') else inv[5]

            # Determine IP version up-front so both IPv4 and IPv6 are supported
            try:
                ip_obj = ipaddress.ip_address(ip)
                ip_version = ip_obj.version
            except ValueError:
                # Not a parseable IP address — skip this inventory row
                continue

            host_len = 128 if ip_version == 6 else 32
            default_cidr = '::/0' if ip_version == 6 else '0.0.0.0/0'

            # Normalize mask format: dotted (255.255.255.0), '/24', '24', or empty
            try:
                norm_mask = str(mask).strip() if mask else ''
                if norm_mask.startswith('/'):
                    norm_mask = norm_mask[1:]
                if not norm_mask:
                    norm_mask = str(host_len)

                # ip_interface accepts dotted IPv4 masks and integer prefix lengths (v4/v6)
                iface = ipaddress.ip_interface(f"{ip}/{norm_mask}")
                net = iface.network
                prefix_str = str(net)
                prefix_len = net.prefixlen
                ip_addr_with_mask = f"{ip}/{prefix_len}"
                is_host = (prefix_len == host_len)
            except Exception:
                is_host = True
                prefix_len = host_len
                prefix_str = None
                ip_addr_with_mask = f"{ip}/{host_len}"

            if is_host:
                # Do NOT insert host routes (/32, /128) into the prefixes table.
                # Find the most specific matching parent prefix of the same IP version.
                parent_prefix_id = None
                best_len = -1

                for p in existing_prefixes:
                    try:
                        pnet = ipaddress.ip_network(p['prefix'], strict=False)
                        if pnet.version != ip_version:
                            continue
                        if pnet.prefixlen < host_len and ip_obj in pnet:
                            if pnet.prefixlen > best_len:
                                best_len = pnet.prefixlen
                                parent_prefix_id = p['id']
                    except Exception:
                        continue

                if parent_prefix_id:
                    prefix_id = parent_prefix_id
                else:
                    # If no parent network matches, categorize under a version-specific catch-all
                    cursor.execute("SELECT id FROM prefixes WHERE prefix = ?", (default_cidr,))
                    default_prefix_row = cursor.fetchone()
                    if default_prefix_row:
                        prefix_id = default_prefix_row['id'] if hasattr(default_prefix_row, '__getitem__') else default_prefix_row[0]
                    else:
                        prefix_id = f"prefix-default-{'v6' if ip_version == 6 else 'global'}"
                        catch_name = "环回 / 孤立主机地址 (IPv6)" if ip_version == 6 else "环回 / 孤立主机地址"
                        catch_desc = "存放未匹配到任何子网的 Loopback 及孤立主机路由 (/32, /128)"
                        if _USE_PG:
                            cursor.execute("INSERT INTO prefixes (id, prefix, prefix_cidr, name, description, network_type, vrf_id, vlan_id, site_id, tenant_id, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                                           (prefix_id, default_cidr, default_cidr, catch_name, catch_desc, 'loopback', None, None, 'site-default', 'tenant-default', 'active'))
                        else:
                            cursor.execute("INSERT INTO prefixes (id, prefix, prefix_cidr, name, description, network_type, vrf_id, vlan_id, site_id, tenant_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                           (prefix_id, default_cidr, default_cidr, catch_name, catch_desc, 'loopback', None, None, 'site-default', 'tenant-default', 'active'))
                        existing_prefixes.append({'id': prefix_id, 'prefix': default_cidr})
            else:
                # Normal CIDR subnets (e.g. /24)
                cursor.execute("SELECT id FROM prefixes WHERE prefix = ?", (prefix_str,))
                prefix_row = cursor.fetchone()
                if prefix_row:
                    prefix_id = prefix_row['id'] if hasattr(prefix_row, '__getitem__') else prefix_row[0]
                else:
                    prefix_id = f"prefix-{uuid.uuid4().hex[:12]}"
                    # Auto-classify point-to-point interconnects as Transit Network:
                    # IPv4 /30 & /31, or IPv6 /127 are device-to-device links.
                    auto_role = 'transit' if (
                        (ip_version == 4 and prefix_len in (30, 31)) or
                        (ip_version == 6 and prefix_len == 127)
                    ) else 'server'
                    if _USE_PG:
                        cursor.execute("INSERT INTO prefixes (id, prefix, prefix_cidr, network_type, vrf_id, vlan_id, site_id, tenant_id, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                                       (prefix_id, prefix_str, prefix_str, auto_role, None, None, 'site-default', 'tenant-default', 'active'))
                    else:
                        cursor.execute("INSERT INTO prefixes (id, prefix, prefix_cidr, network_type, vrf_id, vlan_id, site_id, tenant_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                       (prefix_id, prefix_str, prefix_str, auto_role, None, None, 'site-default', 'tenant-default', 'active'))
                    existing_prefixes.append({'id': prefix_id, 'prefix': prefix_str})

            # Normalize the IP role (device_type) — detect loopbacks by interface name/type
            iface_l = (interface or '').lower()
            itype_l = (itype or '').strip().lower()
            if 'loopback' in iface_l or (iface_l.startswith('lo') and not iface_l.startswith('local')) or itype_l == 'loopback':
                ip_role = 'loopback'
            else:
                ip_role = itype_l or 'host'

            # Find matching interface_id from interfaces table
            cursor.execute("SELECT id FROM interfaces WHERE device_id = ? AND interface_name = ?", (d_id, interface))
            intf_row = cursor.fetchone()
            intf_id = intf_row['id'] if intf_row else None

            # Insert or update ip_addresses to align prefix relationships and masks
            cursor.execute("SELECT id, ip_address, prefix_id FROM ip_addresses WHERE address = ?", (ip,))
            existing_addr = cursor.fetchone()
            if existing_addr:
                addr_id = existing_addr['id'] if hasattr(existing_addr, '__getitem__') else existing_addr[0]
                old_ip_addr = existing_addr['ip_address'] if hasattr(existing_addr, '__getitem__') else existing_addr[1]
                old_prefix_id = existing_addr['prefix_id'] if hasattr(existing_addr, '__getitem__') else existing_addr[2]
                
                # Update if mask or prefix association has changed
                if old_ip_addr != ip_addr_with_mask or old_prefix_id != prefix_id:
                    cursor.execute(
                        "UPDATE ip_addresses SET ip_address = ?, address_inet = ?, prefix_id = ?, subnet_id = ?, interface_id = ?, device_id = ?, interface_name = ?, device_type = ?, last_seen = ?, updated_at = ? WHERE id = ?",
                        (ip_addr_with_mask, ip, prefix_id, prefix_id, intf_id or '', d_id, interface, ip_role, last_seen, datetime.now(timezone.utc).isoformat(), addr_id)
                    )
            else:
                addr_id = f"ip-{uuid.uuid4().hex[:12]}"
                now = datetime.now(timezone.utc).isoformat()
                if _USE_PG:
                    cursor.execute('''
                        INSERT INTO ip_addresses (
                            id, subnet_id, address, hostname, device_id, interface_name,
                            mac_address, device_type, status, description, last_seen, created_at, updated_at,
                            ip_address, address_inet, prefix_id, vrf_id, interface_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (addr_id, prefix_id, ip, '', d_id, interface, '', ip_role, 'active', 'Imported from ip_inventory', last_seen, now, now, ip_addr_with_mask, ip, prefix_id, '', intf_id or ''))
                else:
                    cursor.execute('''
                        INSERT INTO ip_addresses (
                            id, subnet_id, address, hostname, device_id, interface_name,
                            mac_address, device_type, status, description, last_seen, created_at, updated_at,
                            ip_address, address_inet, prefix_id, vrf_id, interface_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (addr_id, prefix_id, ip, '', d_id, interface, '', ip_role, 'active', 'Imported from ip_inventory', last_seen, now, now, ip_addr_with_mask, ip, prefix_id, '', intf_id or ''))

        # Clean up empty, auto-generated host-route prefixes (/32, /128) no longer referenced
        cursor.execute('''
            DELETE FROM prefixes
            WHERE (prefix LIKE '%/32' OR prefix LIKE '%/128')
              AND (name IS NULL OR name = '')
              AND (description IS NULL OR description = '')
              AND id NOT IN (
                  SELECT DISTINCT prefix_id FROM ip_addresses WHERE prefix_id IS NOT NULL AND prefix_id != ''
              )
        ''')

        # 7. Soft isolation values default
        cursor.execute("UPDATE devices SET tenant_id = 'tenant-default' WHERE tenant_id IS NULL OR tenant_id = ''")
        cursor.execute("UPDATE sites SET tenant_id = 'tenant-default' WHERE tenant_id IS NULL OR tenant_id = ''")
        cursor.execute("UPDATE vrfs SET tenant_id = 'tenant-default' WHERE tenant_id IS NULL OR tenant_id = ''")
        cursor.execute("UPDATE vlans SET tenant_id = 'tenant-default' WHERE tenant_id IS NULL OR tenant_id = ''")
        cursor.execute("UPDATE prefixes SET tenant_id = 'tenant-default' WHERE tenant_id IS NULL OR tenant_id = ''")

        # 8. Migrate links to topology_links
        try:
            cursor.execute("SELECT * FROM links")
            links_rows = cursor.fetchall()

            interface_map = {}
            cursor.execute("SELECT id, device_id, interface_name FROM interfaces")
            intf_rows = cursor.fetchall()
            
            def simple_normalize(val):
                if not val:
                    return ''
                raw = str(val).strip().lower().replace(' ', '').replace('\u200b', '')
                aliases = [
                    ('tengigabitethernet', 'te'), ('tengigeethernet', 'te'), ('twentyfivegige', 'tw'),
                    ('twentyfivegigabitethernet', 'tw'), ('fortygigabitethernet', 'fo'), ('fortyge', 'fo'),
                    ('hundredgigabitethernet', 'hu'), ('hundredge', 'hu'), ('gigabitethernet', 'gi'),
                    ('gige', 'gi'), ('fastethernet', 'fa'), ('xgigabitethernet', 'xge'),
                    ('25gige', 'tw'), ('40gige', 'fo'), ('100gige', 'hu'), ('ethernet', 'eth'),
                    ('eth-trunk', 'eth-trunk'), ('bridge-aggregation', 'bagg'), ('port-channel', 'po'),
                    ('portchannel', 'po'), ('bundle-ether', 'be'), ('loopback', 'lo'),
                    ('management', 'mgmt'), ('mgmteth', 'mgmt'), ('meth', 'mgmt'),
                    ('vlanif', 'vlanif'), ('vlan', 'vl')
                ]
                for source, target in aliases:
                    if raw.startswith(source):
                        raw = raw.replace(source, target, 1)
                        break
                if raw.startswith('ethernet'):
                    raw = raw.replace('ethernet', 'eth', 1)
                return raw

            for row in intf_rows:
                dev_id = row['device_id'] if hasattr(row, '__getitem__') else row[1]
                intf_name = row['interface_name'] if hasattr(row, '__getitem__') else row[2]
                norm = simple_normalize(intf_name)
                interface_map[(dev_id, norm)] = row['id'] if hasattr(row, '__getitem__') else row[0]

            for row in links_rows:
                lnk = dict(row) if hasattr(row, 'keys') else {
                    'id': row[0], 'link_key': row[1], 'source_device_id': row[2], 'source_hostname': row[3],
                    'source_port': row[4], 'source_port_normalized': row[5], 'target_device_id': row[6],
                    'target_hostname': row[7], 'target_port': row[8], 'target_port_normalized': row[9],
                    'discovery_source': row[10], 'confidence': row[11], 'status': row[12], 'is_inferred': row[13],
                    'evidence_count': row[14], 'metadata_json': row[15], 'created_at': row[16], 'updated_at': row[17],
                    'last_seen': row[18]
                }
                
                link_key = lnk.get('link_key')
                src_dev = lnk.get('source_device_id')
                src_port_norm = simple_normalize(lnk.get('source_port_normalized') or lnk.get('source_port') or '')
                src_intf_id = interface_map.get((src_dev, src_port_norm))
                
                tgt_dev = lnk.get('target_device_id')
                tgt_port_norm = simple_normalize(lnk.get('target_port_normalized') or lnk.get('target_port') or '')
                tgt_intf_id = interface_map.get((tgt_dev, tgt_port_norm))

                if src_dev and src_port_norm and not src_intf_id:
                    cursor.execute("SELECT id FROM devices WHERE id = ?", (src_dev,))
                    if cursor.fetchone():
                        src_intf_id = f"intf-{uuid.uuid4().hex[:12]}"
                        if _USE_PG:
                            cursor.execute(
                                "INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status) VALUES (%s, %s, %s, 'up', 'up')",
                                (src_intf_id, src_dev, lnk.get('source_port') or src_port_norm)
                            )
                        else:
                            cursor.execute(
                                "INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status) VALUES (?, ?, ?, 'up', 'up')",
                                (src_intf_id, src_dev, lnk.get('source_port') or src_port_norm)
                            )
                        interface_map[(src_dev, src_port_norm)] = src_intf_id

                if tgt_dev and tgt_port_norm and not tgt_intf_id:
                    cursor.execute("SELECT id FROM devices WHERE id = ?", (tgt_dev,))
                    if cursor.fetchone():
                        tgt_intf_id = f"intf-{uuid.uuid4().hex[:12]}"
                        if _USE_PG:
                            cursor.execute(
                                "INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status) VALUES (%s, %s, %s, 'up', 'up')",
                                (tgt_intf_id, tgt_dev, lnk.get('target_port') or tgt_port_norm)
                            )
                        else:
                            cursor.execute(
                                "INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status) VALUES (?, ?, ?, 'up', 'up')",
                                (tgt_intf_id, tgt_dev, lnk.get('target_port') or tgt_port_norm)
                            )
                        interface_map[(tgt_dev, tgt_port_norm)] = tgt_intf_id

                cursor.execute("SELECT id FROM topology_links WHERE link_key = ?", (link_key,))
                existing_topo = cursor.fetchone()
                if existing_topo:
                    if _USE_PG:
                        cursor.execute(
                            "UPDATE topology_links SET source_interface_id = %s, target_interface_id = %s WHERE link_key = %s",
                            (src_intf_id, tgt_intf_id, link_key)
                        )
                    else:
                        cursor.execute(
                            "UPDATE topology_links SET source_interface_id = ?, target_interface_id = ? WHERE link_key = ?",
                            (src_intf_id, tgt_intf_id, link_key)
                        )
                else:
                    if _USE_PG:
                        cursor.execute(
                            '''INSERT INTO topology_links (
                                id, link_key, source_device_id, source_interface_id, source_hostname, source_port, source_port_normalized,
                                target_device_id, target_interface_id, target_hostname, target_port, target_port_normalized,
                                discovery_source, confidence, status, is_inferred, evidence_count,
                                metadata_json, created_at, updated_at, last_seen
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                            (
                                lnk.get('id') or str(uuid.uuid4()),
                                link_key,
                                src_dev,
                                src_intf_id,
                                lnk.get('source_hostname') or '',
                                lnk.get('source_port') or '',
                                lnk.get('source_port_normalized') or '',
                                tgt_dev,
                                tgt_intf_id,
                                lnk.get('target_hostname') or '',
                                lnk.get('target_port') or '',
                                lnk.get('target_port_normalized') or '',
                                lnk.get('discovery_source') or 'lldp',
                                lnk.get('confidence') or 0.0,
                                lnk.get('status') or 'up',
                                lnk.get('is_inferred') or 0,
                                lnk.get('evidence_count') or 1,
                                lnk.get('metadata_json') or '{}',
                                lnk.get('created_at'),
                                lnk.get('updated_at'),
                                lnk.get('last_seen')
                            )
                        )
                    else:
                        cursor.execute(
                            '''INSERT INTO topology_links (
                                id, link_key, source_device_id, source_interface_id, source_hostname, source_port, source_port_normalized,
                                target_device_id, target_interface_id, target_hostname, target_port, target_port_normalized,
                                discovery_source, confidence, status, is_inferred, evidence_count,
                                metadata_json, created_at, updated_at, last_seen
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (
                                lnk.get('id') or str(uuid.uuid4()),
                                link_key,
                                src_dev,
                                src_intf_id,
                                lnk.get('source_hostname') or '',
                                lnk.get('source_port') or '',
                                lnk.get('source_port_normalized') or '',
                                tgt_dev,
                                tgt_intf_id,
                                lnk.get('target_hostname') or '',
                                lnk.get('target_port') or '',
                                lnk.get('target_port_normalized') or '',
                                lnk.get('discovery_source') or 'lldp',
                                lnk.get('confidence') or 0.0,
                                lnk.get('status') or 'up',
                                lnk.get('is_inferred') or 0,
                                lnk.get('evidence_count') or 1,
                                lnk.get('metadata_json') or '{}',
                                lnk.get('created_at'),
                                lnk.get('updated_at'),
                                lnk.get('last_seen')
                            )
                        )
        except Exception as exc_links:
            logger.error(f"[migration] Failed links to topology_links migration logic: {exc_links}", exc_info=True)

    except Exception as exc:
        logger.error(f"[migration] Failed Phase 3 CMDB/IPAM migration: {exc}", exc_info=True)

    # ──────────────────────────────────────────────────────────────────
    # Data migration: Phase 5 Route & Address Intelligence Migration
    # ──────────────────────────────────────────────────────────────────
    try:
        # Get set of all valid device IDs to prevent ForeignKeyViolations
        cursor.execute("SELECT id FROM devices")
        valid_device_ids = {r['id'] if hasattr(r, '__getitem__') else r[0] for r in cursor.fetchall()}
        # 1. Migrate route_cache to route_table
        cursor.execute("SELECT COUNT(*) AS c FROM route_table")
        rt_cnt = cursor.fetchone()
        rt_cnt = rt_cnt['c'] if hasattr(rt_cnt, '__getitem__') else rt_cnt[0]
        if rt_cnt == 0:
            cursor.execute("SELECT * FROM route_cache")
            rc_rows = cursor.fetchall()
            for row in rc_rows:
                rc = dict(row) if hasattr(row, 'keys') else {
                    'id': row[0], 'device_id': row[1], 'prefix': row[2], 'mask': row[3],
                    'next_hop': row[4], 'protocol': row[5], 'interface': row[6],
                    'metric': row[7], 'last_update': row[8]
                }
                r_id = rc.get('id') or str(uuid.uuid4())
                dev_id = rc.get('device_id')
                if dev_id not in valid_device_ids:
                    continue
                dest = rc.get('prefix') or ''
                mask_val = rc.get('mask') or ''
                if mask_val and '/' not in dest:
                    try:
                        if '.' in mask_val:
                            octets = [int(o) for o in mask_val.split('.')]
                            binary = ''.join(f'{o:08b}' for o in octets)
                            cidr = str(binary.count('1'))
                        else:
                            cidr = str(int(mask_val))
                        dest = f"{dest}/{cidr}"
                    except Exception:
                        dest = f"{dest}/24"
                
                pref_val = 1
                proto_lower = (rc.get('protocol') or '').lower()
                if 'direct' in proto_lower or 'connect' in proto_lower:
                    pref_val = 0
                elif 'static' in proto_lower:
                    pref_val = 1
                elif 'ospf' in proto_lower:
                    pref_val = 110
                elif 'bgp' in proto_lower:
                    pref_val = 200

                if _USE_PG:
                    cursor.execute(
                        '''INSERT INTO route_table (
                            id, device_id, destination, next_hop, outgoing_interface, protocol, metric, preference, last_updated, active
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)''',
                        (r_id, dev_id, dest, rc.get('next_hop'), rc.get('interface'), rc.get('protocol'), rc.get('metric'), pref_val, rc.get('last_update'))
                    )
                else:
                    cursor.execute(
                        '''INSERT INTO route_table (
                            id, device_id, destination, next_hop, outgoing_interface, protocol, metric, preference, last_updated, active
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)''',
                        (r_id, dev_id, dest, rc.get('next_hop'), rc.get('interface'), rc.get('protocol'), rc.get('metric'), pref_val, rc.get('last_update'))
                    )
            logger.info(f"[migration] Migrated {len(rc_rows)} routes from route_cache to route_table.")

        # 2. Migrate arp_cache to arp_table
        cursor.execute("SELECT COUNT(*) AS c FROM arp_table")
        arp_cnt = cursor.fetchone()
        arp_cnt = arp_cnt['c'] if hasattr(arp_cnt, '__getitem__') else arp_cnt[0]
        if arp_cnt == 0:
            cursor.execute("SELECT * FROM arp_cache")
            arp_rows = cursor.fetchall()
            for row in arp_rows:
                ac = dict(row) if hasattr(row, 'keys') else {
                    'target_ip': row[0], 'mac': row[1], 'arp_source': row[2], 'cached_at': row[3]
                }
                source = {}
                try:
                    source = json.loads(ac.get('arp_source') or '{}')
                except Exception:
                    pass
                
                dev_id = source.get('device_id')
                if not dev_id:
                    dev_label = source.get('device')
                    if dev_label:
                        cursor.execute("SELECT id FROM devices WHERE hostname = ? OR ip_address = ?", (dev_label, dev_label))
                        d_row = cursor.fetchone()
                        if d_row:
                            dev_id = d_row['id'] if hasattr(d_row, '__getitem__') else d_row[0]
                
                if dev_id and dev_id not in valid_device_ids:
                    dev_id = None

                if not dev_id:
                    cursor.execute("SELECT id FROM devices LIMIT 1")
                    d_row = cursor.fetchone()
                    if d_row:
                        dev_id = d_row['id'] if hasattr(d_row, '__getitem__') else d_row[0]
                
                if not dev_id or dev_id not in valid_device_ids:
                    continue
                
                if _USE_PG:
                    cursor.execute(
                        '''INSERT INTO arp_table (
                            id, device_id, ip_address, mac_address, interface_name, last_updated
                        ) VALUES (%s, %s, %s, %s, %s, %s)''',
                        (str(uuid.uuid4()), dev_id, ac.get('target_ip'), ac.get('mac'), source.get('interface') or '', ac.get('cached_at'))
                    )
                else:
                    cursor.execute(
                        '''INSERT INTO arp_table (
                            id, device_id, ip_address, mac_address, interface_name, last_updated
                        ) VALUES (?, ?, ?, ?, ?, ?)''',
                        (str(uuid.uuid4()), dev_id, ac.get('target_ip'), ac.get('mac'), source.get('interface') or '', ac.get('cached_at'))
                    )
            logger.info(f"[migration] Migrated {len(arp_rows)} ARP entries from arp_cache to arp_table.")

        # 3. Migrate topology_observations to neighbor_table
        cursor.execute("SELECT COUNT(*) AS c FROM neighbor_table")
        nt_cnt = cursor.fetchone()
        nt_cnt = nt_cnt['c'] if hasattr(nt_cnt, '__getitem__') else nt_cnt[0]
        if nt_cnt == 0:
            cursor.execute("SELECT * FROM topology_observations")
            obs_rows = cursor.fetchall()
            for row in obs_rows:
                obs = dict(row) if hasattr(row, 'keys') else {
                    'id': row[0], 'source_device_id': row[1], 'source_hostname': row[2],
                    'source_port_raw': row[3], 'source_port_normalized': row[4],
                    'neighbor_name_raw': row[5], 'neighbor_name_normalized': row[6],
                    'neighbor_ip_address': row[7], 'target_device_id': row[8],
                    'target_hostname': row[9], 'target_port_raw': row[10],
                    'target_port_normalized': row[11], 'protocol': row[12],
                    'confidence': row[13], 'status': row[14], 'discovery_run_id': row[15],
                    'raw_payload_json': row[16], 'collected_at': row[17], 'updated_at': row[18]
                }
                src_dev_id = obs.get('source_device_id')
                local_intf = obs.get('source_port_raw') or obs.get('source_port_normalized') or ''
                neigh_host = obs.get('neighbor_name_raw') or obs.get('neighbor_name_normalized') or ''
                neigh_intf = obs.get('target_port_raw') or obs.get('target_port_normalized') or ''
                neigh_ip = obs.get('neighbor_ip_address') or ''
                proto = obs.get('protocol') or 'lldp'
                last_upd = obs.get('updated_at') or obs.get('collected_at') or now
                
                if _USE_PG:
                    cursor.execute(
                        '''INSERT INTO neighbor_table (
                            id, device_id, local_interface, neighbor_hostname, neighbor_interface, neighbor_ip, protocol, last_updated
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                        (str(uuid.uuid4()), src_dev_id, local_intf, neigh_host, neigh_intf, neigh_ip, proto, last_upd)
                    )
                else:
                    cursor.execute(
                        '''INSERT INTO neighbor_table (
                            id, device_id, local_interface, neighbor_hostname, neighbor_interface, neighbor_ip, protocol, last_updated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                        (str(uuid.uuid4()), src_dev_id, local_intf, neigh_host, neigh_intf, neigh_ip, proto, last_upd)
                    )
            logger.info(f"[migration] Migrated {len(obs_rows)} observations from topology_observations to neighbor_table.")

    except Exception as exc_p5:
        logger.error(f"[migration] Failed Phase 5 Route Intelligence migration: {exc_p5}", exc_info=True)

    # ──────────────────────────────────────────────────────────────────
    # Data migration: Phase 6 Supporting Engines Migration & Triggers
    # ──────────────────────────────────────────────────────────────────
    try:
        # Get set of all valid device IDs to prevent ForeignKeyViolations
        cursor.execute("SELECT id FROM devices")
        valid_device_ids = {r['id'] if hasattr(r, '__getitem__') else r[0] for r in cursor.fetchall()}
        # 1. Migrate config_snapshots -> config_backups
        cursor.execute("SELECT COUNT(*) AS c FROM config_backups")
        cb_cnt = cursor.fetchone()
        cb_cnt = cb_cnt['c'] if hasattr(cb_cnt, '__getitem__') else cb_cnt[0]
        if cb_cnt == 0:
            cursor.execute("SELECT * FROM config_snapshots")
            snap_rows = cursor.fetchall()
            for row in snap_rows:
                snap = dict(row) if hasattr(row, 'keys') else {
                    'id': row[0], 'device_id': row[1], 'timestamp': row[4], 'file_path': row[8], 'tag': row[9]
                }
                c_id = snap.get('id') or str(uuid.uuid4())
                dev_id = snap.get('device_id')
                if dev_id not in valid_device_ids:
                    continue
                if _USE_PG:
                    cursor.execute(
                        '''INSERT INTO config_backups (id, device_id, config_type, backup_time, file_path, config_hash)
                           VALUES (%s, %s, 'running', %s, %s, %s)''',
                        (c_id, dev_id, snap.get('timestamp'), snap.get('file_path'), snap.get('tag'))
                    )
                else:
                    cursor.execute(
                        '''INSERT INTO config_backups (id, device_id, config_type, backup_time, file_path, config_hash)
                           VALUES (?, ?, 'running', ?, ?, ?)''',
                        (c_id, dev_id, snap.get('timestamp'), snap.get('file_path'), snap.get('tag'))
                    )
            logger.info(f"[migration] Migrated {len(snap_rows)} backups from config_snapshots to config_backups.")

        # 2. Migrate alert_events -> alarms
        cursor.execute("SELECT COUNT(*) AS c FROM alarms")
        al_cnt = cursor.fetchone()
        al_cnt = al_cnt['c'] if hasattr(al_cnt, '__getitem__') else al_cnt[0]
        if al_cnt == 0:
            cursor.execute("SELECT * FROM alert_events")
            alert_rows = cursor.fetchall()
            for row in alert_rows:
                al = dict(row) if hasattr(row, 'keys') else {
                    'id': row[0], 'device_id': row[6], 'severity': row[3], 'source': row[2],
                    'title': row[4], 'created_at': row[8], 'resolved_at': row[9], 'workflow_status': row[10]
                }
                a_id = al.get('id') or str(uuid.uuid4())
                dev_id = al.get('device_id')
                if dev_id not in valid_device_ids:
                    continue
                if _USE_PG:
                    cursor.execute(
                        '''INSERT INTO alarms (id, device_id, severity, source, alarm_type, alarm_time, clear_time, status)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                        (a_id, dev_id, al.get('severity'), al.get('source'), al.get('title'), al.get('created_at'), al.get('resolved_at'), al.get('workflow_status'))
                    )
                else:
                    cursor.execute(
                        '''INSERT INTO alarms (id, device_id, severity, source, alarm_type, alarm_time, clear_time, status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                        (a_id, dev_id, al.get('severity'), al.get('source'), al.get('title'), al.get('created_at'), al.get('resolved_at'), al.get('workflow_status'))
                    )
            logger.info(f"[migration] Migrated {len(alert_rows)} alarms from alert_events to alarms.")

        # 3. Migrate audit_events -> events
        cursor.execute("SELECT COUNT(*) AS c FROM events")
        ev_cnt = cursor.fetchone()
        ev_cnt = ev_cnt['c'] if hasattr(ev_cnt, '__getitem__') else ev_cnt[0]
        if ev_cnt == 0:
            cursor.execute("SELECT * FROM audit_events")
            audit_rows = cursor.fetchall()
            for row in audit_rows:
                ae = dict(row) if hasattr(row, 'keys') else {
                    'id': row[0], 'event_type': row[1], 'category': row[2], 'created_at': row[18],
                    'status': row[4], 'actor_username': row[6], 'actor_role': row[7], 'summary': row[17]
                }
                e_id = ae.get('id') or str(uuid.uuid4())
                payload_str = json.dumps({
                    'status': ae.get('status'),
                    'actor_username': ae.get('actor_username'),
                    'actor_role': ae.get('actor_role'),
                    'summary': ae.get('summary')
                })
                if _USE_PG:
                    cursor.execute(
                        '''INSERT INTO events (event_id, event_type, event_source, event_time, payload)
                           VALUES (%s, %s, %s, %s, %s)''',
                        (e_id, ae.get('event_type'), ae.get('category'), ae.get('created_at'), payload_str)
                    )
                else:
                    cursor.execute(
                        '''INSERT INTO events (event_id, event_type, event_source, event_time, payload)
                           VALUES (?, ?, ?, ?, ?)''',
                        (e_id, ae.get('event_type'), ae.get('category'), ae.get('created_at'), payload_str)
                    )
            logger.info(f"[migration] Migrated {len(audit_rows)} events from audit_events to events.")

        # 4. Migrate jobs and topology_discovery_runs -> discovery_jobs
        cursor.execute("SELECT COUNT(*) AS c FROM discovery_jobs")
        dj_cnt = cursor.fetchone()
        dj_cnt = dj_cnt['c'] if hasattr(dj_cnt, '__getitem__') else dj_cnt[0]
        if dj_cnt == 0:
            # Jobs
            cursor.execute("SELECT * FROM jobs")
            job_rows = cursor.fetchall()
            for row in job_rows:
                jb = dict(row) if hasattr(row, 'keys') else {
                    'id': row[0], 'device_id': row[1], 'task_name': row[2], 'status': row[3], 'output': row[4], 'created_at': row[5]
                }
                j_id = jb.get('id') or str(uuid.uuid4())
                res_str = json.dumps({
                    'task_name': jb.get('task_name'),
                    'output': jb.get('output')
                })
                if _USE_PG:
                    cursor.execute(
                        '''INSERT INTO discovery_jobs (id, job_type, target, status, start_time, finish_time, result)
                           VALUES (%s, 'job', %s, %s, %s, %s, %s)''',
                        (j_id, jb.get('device_id') or '', jb.get('status'), jb.get('created_at'), jb.get('created_at'), res_str)
                    )
                else:
                    cursor.execute(
                        '''INSERT INTO discovery_jobs (id, job_type, target, status, start_time, finish_time, result)
                           VALUES (?, 'job', ?, ?, ?, ?, ?)''',
                        (j_id, jb.get('device_id') or '', jb.get('status'), jb.get('created_at'), jb.get('created_at'), res_str)
                    )
            # Discovery runs
            cursor.execute("SELECT * FROM topology_discovery_runs")
            run_rows = cursor.fetchall()
            for row in run_rows:
                rn = dict(row) if hasattr(row, 'keys') else {
                    'id': row[0], 'scope': row[1], 'status': row[2], 'started_at': row[5], 'completed_at': row[6], 'summary_json': row[12]
                }
                r_id = rn.get('id') or str(uuid.uuid4())
                if _USE_PG:
                    cursor.execute(
                        '''INSERT INTO discovery_jobs (id, job_type, target, status, start_time, finish_time, result)
                           VALUES (%s, 'discovery', %s, %s, %s, %s, %s)''',
                        (r_id, rn.get('scope'), rn.get('status'), rn.get('started_at'), rn.get('completed_at'), rn.get('summary_json'))
                    )
                else:
                    cursor.execute(
                        '''INSERT INTO discovery_jobs (id, job_type, target, status, start_time, finish_time, result)
                           VALUES (?, 'discovery', ?, ?, ?, ?, ?)''',
                        (r_id, rn.get('scope'), rn.get('status'), rn.get('started_at'), rn.get('completed_at'), rn.get('summary_json'))
                    )
            logger.info(f"[migration] Migrated jobs & discovery runs to discovery_jobs.")

        # 5. Create database triggers for continuous synchronization (SQLite only)
        if not _USE_PG:
            # config_snapshots triggers
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_sync_config_snapshots_insert
            AFTER INSERT ON config_snapshots
            BEGIN
                INSERT INTO config_backups (id, device_id, config_type, backup_time, file_path, config_hash)
                VALUES (NEW.id, NEW.device_id, 'running', NEW.timestamp, NEW.file_path, COALESCE(NEW.tag, ''));
            END;
            ''')
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_sync_config_snapshots_update
            AFTER UPDATE ON config_snapshots
            BEGIN
                UPDATE config_backups SET
                    device_id = NEW.device_id,
                    backup_time = NEW.timestamp,
                    file_path = NEW.file_path,
                    config_hash = COALESCE(NEW.tag, '')
                WHERE id = NEW.id;
            END;
            ''')
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_sync_config_snapshots_delete
            AFTER DELETE ON config_snapshots
            BEGIN
                DELETE FROM config_backups WHERE id = OLD.id;
            END;
            ''')

            # alert_events triggers
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_sync_alert_events_insert
            AFTER INSERT ON alert_events
            BEGIN
                INSERT INTO alarms (id, device_id, severity, source, alarm_type, alarm_time, clear_time, status)
                VALUES (NEW.id, NEW.device_id, NEW.severity, NEW.source, NEW.title, NEW.created_at, NEW.resolved_at, NEW.workflow_status);
            END;
            ''')
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_sync_alert_events_update
            AFTER UPDATE ON alert_events
            BEGIN
                UPDATE alarms SET
                    device_id = NEW.device_id,
                    severity = NEW.severity,
                    source = NEW.source,
                    alarm_type = NEW.title,
                    alarm_time = NEW.created_at,
                    clear_time = NEW.resolved_at,
                    status = NEW.workflow_status
                WHERE id = NEW.id;
            END;
            ''')
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_sync_alert_events_delete
            AFTER DELETE ON alert_events
            BEGIN
                DELETE FROM alarms WHERE id = OLD.id;
            END;
            ''')

            # audit_events triggers
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_sync_audit_events_insert
            AFTER INSERT ON audit_events
            BEGIN
                INSERT INTO events (event_id, event_type, event_source, event_time, payload)
                VALUES (NEW.id, NEW.event_type, NEW.category, NEW.created_at, json_object(
                    'status', NEW.status,
                    'actor_username', NEW.actor_username,
                    'actor_role', NEW.actor_role,
                    'summary', NEW.summary
                ));
            END;
            ''')

            # jobs triggers
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_sync_jobs_insert
            AFTER INSERT ON jobs
            BEGIN
                INSERT INTO discovery_jobs (id, job_type, target, status, start_time, finish_time, result)
                VALUES (NEW.id, 'job', COALESCE(NEW.device_id, ''), NEW.status, NEW.created_at, NEW.created_at, json_object('task_name', NEW.task_name, 'output', NEW.output));
            END;
            ''')
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_sync_jobs_update
            AFTER UPDATE ON jobs
            BEGIN
                UPDATE discovery_jobs SET
                    status = NEW.status,
                    result = json_object('task_name', NEW.task_name, 'output', NEW.output)
                WHERE id = NEW.id;
            END;
            ''')

            # topology_discovery_runs triggers
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_sync_topo_runs_insert
            AFTER INSERT ON topology_discovery_runs
            BEGIN
                INSERT INTO discovery_jobs (id, job_type, target, status, start_time, finish_time, result)
                VALUES (NEW.id, 'discovery', NEW.scope, NEW.status, NEW.started_at, NEW.completed_at, NEW.summary_json);
            END;
            ''')
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_sync_topo_runs_update
            AFTER UPDATE ON topology_discovery_runs
            BEGIN
                UPDATE discovery_jobs SET
                    status = NEW.status,
                    finish_time = NEW.completed_at,
                    result = NEW.summary_json
                WHERE id = NEW.id;
            END;
            ''')

            # device_telemetry_samples trigger for performance_metrics
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_telemetry_to_perf_metrics
            AFTER INSERT ON device_telemetry_samples
            BEGIN
                INSERT INTO performance_metrics (id, device_id, metric_name, metric_value, timestamp)
                VALUES (hex(randomblob(16)), NEW.device_id, 'cpu_util', NEW.cpu_util, NEW.ts);
                INSERT INTO performance_metrics (id, device_id, metric_name, metric_value, timestamp)
                VALUES (hex(randomblob(16)), NEW.device_id, 'mem_avail', NEW.mem_avail, NEW.ts);
                INSERT INTO performance_metrics (id, device_id, metric_name, metric_value, timestamp)
                VALUES (hex(randomblob(16)), NEW.device_id, 'cpu_load', NEW.cpu_load, NEW.ts);
                INSERT INTO performance_metrics (id, device_id, metric_name, metric_value, timestamp)
                VALUES (hex(randomblob(16)), NEW.device_id, 'disk_util', NEW.disk_util, NEW.ts);
            END;
            ''')
        else:
            # PostgreSQL triggers
            # config_snapshots triggers
            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_sync_config_snapshots_insert()
            RETURNS TRIGGER AS $$
            BEGIN
                INSERT INTO config_backups (id, device_id, config_type, backup_time, file_path, config_hash)
                VALUES (NEW.id, NEW.device_id, 'running', NEW.timestamp, NEW.file_path, COALESCE(NEW.tag, ''));
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_sync_config_snapshots_insert ON config_snapshots')
            cursor.execute('''
            CREATE TRIGGER trg_sync_config_snapshots_insert
            AFTER INSERT ON config_snapshots
            FOR EACH ROW EXECUTE FUNCTION fn_sync_config_snapshots_insert()
            ''')

            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_sync_config_snapshots_update()
            RETURNS TRIGGER AS $$
            BEGIN
                UPDATE config_backups SET
                    device_id = NEW.device_id,
                    backup_time = NEW.timestamp,
                    file_path = NEW.file_path,
                    config_hash = COALESCE(NEW.tag, '')
                WHERE id = NEW.id;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_sync_config_snapshots_update ON config_snapshots')
            cursor.execute('''
            CREATE TRIGGER trg_sync_config_snapshots_update
            AFTER UPDATE ON config_snapshots
            FOR EACH ROW EXECUTE FUNCTION fn_sync_config_snapshots_update()
            ''')

            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_sync_config_snapshots_delete()
            RETURNS TRIGGER AS $$
            BEGIN
                DELETE FROM config_backups WHERE id = OLD.id;
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_sync_config_snapshots_delete ON config_snapshots')
            cursor.execute('''
            CREATE TRIGGER trg_sync_config_snapshots_delete
            AFTER DELETE ON config_snapshots
            FOR EACH ROW EXECUTE FUNCTION fn_sync_config_snapshots_delete()
            ''')

            # alert_events triggers
            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_sync_alert_events_insert()
            RETURNS TRIGGER AS $$
            BEGIN
                INSERT INTO alarms (id, device_id, severity, source, alarm_type, alarm_time, clear_time, status)
                VALUES (NEW.id, NEW.device_id, NEW.severity, NEW.source, NEW.title, NEW.created_at, NEW.resolved_at, NEW.workflow_status);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_sync_alert_events_insert ON alert_events')
            cursor.execute('''
            CREATE TRIGGER trg_sync_alert_events_insert
            AFTER INSERT ON alert_events
            FOR EACH ROW EXECUTE FUNCTION fn_sync_alert_events_insert()
            ''')

            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_sync_alert_events_update()
            RETURNS TRIGGER AS $$
            BEGIN
                UPDATE alarms SET
                    device_id = NEW.device_id,
                    severity = NEW.severity,
                    source = NEW.source,
                    alarm_type = NEW.title,
                    alarm_time = NEW.created_at,
                    clear_time = NEW.resolved_at,
                    status = NEW.workflow_status
                WHERE id = NEW.id;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_sync_alert_events_update ON alert_events')
            cursor.execute('''
            CREATE TRIGGER trg_sync_alert_events_update
            AFTER UPDATE ON alert_events
            FOR EACH ROW EXECUTE FUNCTION fn_sync_alert_events_update()
            ''')

            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_sync_alert_events_delete()
            RETURNS TRIGGER AS $$
            BEGIN
                DELETE FROM alarms WHERE id = OLD.id;
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_sync_alert_events_delete ON alert_events')
            cursor.execute('''
            CREATE TRIGGER trg_sync_alert_events_delete
            AFTER DELETE ON alert_events
            FOR EACH ROW EXECUTE FUNCTION fn_sync_alert_events_delete()
            ''')

            # audit_events triggers
            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_sync_audit_events_insert()
            RETURNS TRIGGER AS $$
            BEGIN
                INSERT INTO events (event_id, event_type, event_source, event_time, payload)
                VALUES (NEW.id, NEW.event_type, NEW.category, NEW.created_at, json_build_object(
                    'status', NEW.status,
                    'actor_username', NEW.actor_username,
                    'actor_role', NEW.actor_role,
                    'summary', NEW.summary
                )::text);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_sync_audit_events_insert ON audit_events')
            cursor.execute('''
            CREATE TRIGGER trg_sync_audit_events_insert
            AFTER INSERT ON audit_events
            FOR EACH ROW EXECUTE FUNCTION fn_sync_audit_events_insert()
            ''')

            # jobs triggers
            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_sync_jobs_insert()
            RETURNS TRIGGER AS $$
            BEGIN
                INSERT INTO discovery_jobs (id, job_type, target, status, start_time, finish_time, result)
                VALUES (NEW.id, 'job', COALESCE(NEW.device_id, ''), NEW.status, NEW.created_at, NEW.created_at, json_build_object(
                    'task_name', NEW.task_name,
                    'output', NEW.output
                )::text);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_sync_jobs_insert ON jobs')
            cursor.execute('''
            CREATE TRIGGER trg_sync_jobs_insert
            AFTER INSERT ON jobs
            FOR EACH ROW EXECUTE FUNCTION fn_sync_jobs_insert()
            ''')

            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_sync_jobs_update()
            RETURNS TRIGGER AS $$
            BEGIN
                UPDATE discovery_jobs SET
                    status = NEW.status,
                    result = json_build_object(
                        'task_name', NEW.task_name,
                        'output', NEW.output
                    )::text
                WHERE id = NEW.id;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_sync_jobs_update ON jobs')
            cursor.execute('''
            CREATE TRIGGER trg_sync_jobs_update
            AFTER UPDATE ON jobs
            FOR EACH ROW EXECUTE FUNCTION fn_sync_jobs_update()
            ''')

            # topology_discovery_runs triggers
            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_sync_topo_runs_insert()
            RETURNS TRIGGER AS $$
            BEGIN
                INSERT INTO discovery_jobs (id, job_type, target, status, start_time, finish_time, result)
                VALUES (NEW.id, 'discovery', NEW.scope, NEW.status, NEW.started_at, NEW.completed_at, NEW.summary_json);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_sync_topo_runs_insert ON topology_discovery_runs')
            cursor.execute('''
            CREATE TRIGGER trg_sync_topo_runs_insert
            AFTER INSERT ON topology_discovery_runs
            FOR EACH ROW EXECUTE FUNCTION fn_sync_topo_runs_insert()
            ''')

            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_sync_topo_runs_update()
            RETURNS TRIGGER AS $$
            BEGIN
                UPDATE discovery_jobs SET
                    status = NEW.status,
                    finish_time = NEW.completed_at,
                    result = NEW.summary_json
                WHERE id = NEW.id;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_sync_topo_runs_update ON topology_discovery_runs')
            cursor.execute('''
            CREATE TRIGGER trg_sync_topo_runs_update
            AFTER UPDATE ON topology_discovery_runs
            FOR EACH ROW EXECUTE FUNCTION fn_sync_topo_runs_update()
            ''')

            # device_telemetry_samples trigger
            cursor.execute('''
            CREATE OR REPLACE FUNCTION fn_telemetry_to_perf_metrics()
            RETURNS TRIGGER AS $$
            BEGIN
                INSERT INTO performance_metrics (id, device_id, metric_name, metric_value, timestamp)
                VALUES (md5(random()::text), NEW.device_id, 'cpu_util', NEW.cpu_util, NEW.ts);
                INSERT INTO performance_metrics (id, device_id, metric_name, metric_value, timestamp)
                VALUES (md5(random()::text), NEW.device_id, 'mem_avail', NEW.mem_avail, NEW.ts);
                INSERT INTO performance_metrics (id, device_id, metric_name, metric_value, timestamp)
                VALUES (md5(random()::text), NEW.device_id, 'cpu_load', NEW.cpu_load, NEW.ts);
                INSERT INTO performance_metrics (id, device_id, metric_name, metric_value, timestamp)
                VALUES (md5(random()::text), NEW.device_id, 'disk_util', NEW.disk_util, NEW.ts);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            ''')
            cursor.execute('DROP TRIGGER IF EXISTS trg_telemetry_to_perf_metrics ON device_telemetry_samples')
            cursor.execute('''
            CREATE TRIGGER trg_telemetry_to_perf_metrics
            AFTER INSERT ON device_telemetry_samples
            FOR EACH ROW EXECUTE FUNCTION fn_telemetry_to_perf_metrics()
            ''')

    except Exception as exc_p6:
        logger.error(f"[migration] Failed Phase 6 Supporting Engines migration: {exc_p6}", exc_info=True)


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
