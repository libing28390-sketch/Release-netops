import os
import re
import queue
import logging
import uuid
from datetime import datetime, timezone, timedelta

_BEIJING_TZ = timezone(timedelta(hours=8))

def _beijing_now_iso() -> str:
    """Helper to get current time in ISO format (Beijing time)."""
    return datetime.now(_BEIJING_TZ).isoformat(timespec='seconds')

# Load .env BEFORE reading DATABASE_URL from os.environ
# (pydantic-settings loads .env into Settings but NOT into os.environ at import time)
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    load_dotenv(_env_path, override=True)
except ImportError:
    pass

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'netops.db')

logger = logging.getLogger(__name__)

# ── Init Guard ──
_db_initialized = False

# ── # TEST COMMENT - MULTI-ROLE PAM UPDATE
# ── Backend Detection ───────────────────────────────────────
# Priority: DATABASE_URL env > default SQLite
_DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()

# Automatically fix docker compose 'db' host for non-Docker-Compose execution.
# Covers: local dev, GitHub Codespaces, bare-metal Ubuntu, systemd deployments.
# Does NOT replace when running inside docker-compose (where 'db' is a valid service name).
_in_compose = os.path.exists('/.dockerenv') and os.environ.get('POSTGRES_USER') is not None
if not _in_compose and '@db:' in _DATABASE_URL:
    _DATABASE_URL = _DATABASE_URL.replace('@db:', '@localhost:')
    logger.info("Non-compose environment: Auto-replaced 'db' host with 'localhost' in DATABASE_URL")

normalized_db_url = _DATABASE_URL.lower()
_USE_PG = normalized_db_url.startswith('postgresql://') or normalized_db_url.startswith('postgres://')

_safe_db_url = re.sub(r'://[^@]+@', '://***@', _DATABASE_URL)
logger.info("Database backend selected: %s, DATABASE_URL=%s",
            "PostgreSQL" if _USE_PG else "SQLite",
            _safe_db_url or "(unset)")

if _USE_PG:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
else:
    import sqlite3

# ── Connection Pool ─────────────────────────────────────────
_POOL_SIZE = int(os.environ.get('DB_POOL_SIZE', '16'))

# ── PostgreSQL Wrappers ────────────────────────────────────
if _USE_PG:
    _pg_pool: psycopg2.pool.ThreadedConnectionPool | None = None

    def _ensure_pg_pool():
        global _pg_pool
        if _pg_pool is None:
            _pg_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2, maxconn=_POOL_SIZE, dsn=_DATABASE_URL,
                # Enable TCP keepalives to prevent unexpected connection drops
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5
            )

    _LIKE_RE = re.compile(r'\bLIKE\b', re.IGNORECASE)

    class _PgCursor:
        """Wraps psycopg2 DictCursor; auto-translates ``?`` → ``%s`` and ``LIKE`` → ``ILIKE``."""
        __slots__ = ('_cur',)

        def __init__(self, cur):
            self._cur = cur

        @staticmethod
        def _adapt(sql: str) -> str:
            sql = sql.replace('?', '%s')
            sql = _LIKE_RE.sub('ILIKE', sql)
            return sql

        def execute(self, sql, params=None):
            self._cur.execute(self._adapt(sql), params)
            return self

        def executemany(self, sql, params_list):
            self._cur.executemany(self._adapt(sql), params_list)
            return self

        def __getattr__(self, name):
            return getattr(self._cur, name)

        def __iter__(self):
            return iter(self._cur)

    class _PgRawConnection:
        """Wraps psycopg2 connection; provides sqlite3-like ``.execute()``."""
        __slots__ = ('_conn',)

        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, params=None):
            cur = self.cursor()
            cur.execute(sql, params)
            return cur

        def executemany(self, sql, params_list):
            cur = self.cursor()
            cur.executemany(sql, params_list)
            return cur

        def cursor(self):
            return _PgCursor(self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor))

        def commit(self):
            self._conn.commit()

        def rollback(self):
            self._conn.rollback()

        def close(self):
            self._conn.close()

        @property
        def autocommit(self):
            return self._conn.autocommit

        @autocommit.setter
        def autocommit(self, value):
            self._conn.autocommit = value

    class _PgPooledConnection:
        """Close returns PG connection to the pool."""
        __slots__ = ('_conn', '_raw')

        def __init__(self, wrapped, raw):
            self._conn = wrapped
            self._raw = raw

        def close(self):
            raw = self._raw
            if raw is None:
                return
            self._raw = None
            self._conn = None
            try:
                raw.rollback()
                _pg_pool.putconn(raw)
            except Exception:
                try:
                    raw.close()
                except Exception:
                    pass

        def __getattr__(self, name):
            if self._conn is None:
                raise RuntimeError("Connection already returned to pool")
            return getattr(self._conn, name)

        @property
        def autocommit(self):
            return self._conn.autocommit

        @autocommit.setter
        def autocommit(self, value):
            self._conn.autocommit = value

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def __del__(self):
            self.close()

# ── SQLite Wrappers ─────────────────────────────────────────
else:
    _pool: queue.Queue = queue.Queue(maxsize=_POOL_SIZE)
    _active_connections = 0

    class _PooledConnection:
        """Transparent wrapper: close() returns the real connection to the pool."""
        __slots__ = ('_conn',)

        def __init__(self, conn):
            global _active_connections
            self._conn = conn
            _active_connections += 1

        def close(self):
            global _active_connections
            conn = self._conn
            if conn is None:
                return
            self._conn = None
            _active_connections = max(0, _active_connections - 1)
            try:
                conn.rollback()
                _pool.put_nowait(conn)
            except queue.Full:
                conn.close()
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass

        def __getattr__(self, name):
            conn = self._conn
            if conn is None:
                raise RuntimeError("Connection already returned to pool")
            return getattr(conn, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def __del__(self):
            self.close()


def _make_raw_connection():
    """Create a new raw connection (SQLite or PG) with standard settings."""
    if _USE_PG:
        _ensure_pg_pool()
        raw = _pg_pool.getconn()
        # Add a simple health check for PG
        try:
            with raw.cursor() as tmp_cur:
                tmp_cur.execute("SELECT 1")
            raw.rollback() # Ensure no active transaction after health check
        except Exception:
            # If health check fails, discard the bad connection and get a new one
            try:
                _pg_pool.putconn(raw, close=True)
            except Exception:
                pass
            raw = _pg_pool.getconn()
            
        return _PgPooledConnection(_PgRawConnection(raw), raw)
    else:
        conn = sqlite3.connect(DB_PATH, timeout=10.0, check_same_thread=False)
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA synchronous=NORMAL;')
        conn.row_factory = sqlite3.Row
        # Re-apply critical pragmas on pooled connections just in case
        try:
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.execute('PRAGMA synchronous=NORMAL;')
        except Exception:
            pass
        return _PooledConnection(conn)


def _utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def get_db_connection():
    if _USE_PG:
        return _make_raw_connection()
    # SQLite path
    if not os.path.exists(os.path.dirname(DB_PATH)):
        os.makedirs(os.path.dirname(DB_PATH))
    try:
        conn = _pool.get_nowait()
        try:
            conn.execute('SELECT 1')
            return _PooledConnection(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    except queue.Empty:
        if _active_connections >= _POOL_SIZE:
            logger.warning("SQLite pool exhausted (active=%d, max=%d). Creating overflow connection.", 
                           _active_connections, _POOL_SIZE)
        pass
    try:
        return _make_raw_connection()
    except sqlite3.DatabaseError as e:
        if "malformed" in str(e).lower():
            logger.warning(f"Database corrupted, deleting {DB_PATH} and recreating...")
            for suffix in ('', '-wal', '-shm'):
                path = DB_PATH + suffix
                if os.path.exists(path):
                    os.remove(path)
            return _make_raw_connection()
        raise e


# ── Helpers ─────────────────────────────────────────────────
_SERIAL_PK = 'SERIAL PRIMARY KEY' if _USE_PG else 'INTEGER PRIMARY KEY AUTOINCREMENT'
_JSON_ARRAY_FN = 'json_build_array' if _USE_PG else 'json_array'


def _table_columns(cursor, table_name: str) -> set[str]:
    """Return column names for *table_name*. Backend-aware."""
    if _USE_PG:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table_name,),
        )
        return {row[0] for row in cursor.fetchall()}
    return {row['name'] for row in cursor.execute(f'PRAGMA table_info({table_name})').fetchall()}


def _build_network_inspection_items(now: str) -> list[tuple]:
    """
    构建网络设备巡检指标（CLI 方式 + TextFSM 解析）。

    每条记录 21 列对应 inspection_items 扩展字段：
      id, name, name_zh, category, check_key, description, method, command, script_id,
      warning_threshold, critical_threshold, vendor, oid, created_at, updated_at,
      parse_type, textfsm_template, parse_field, parse_filter, fallback_regex, enabled

    parse_type 取值：
      numeric — 数值比较（默认）
      status  — 关键词匹配（ok/fail/down 等）
      count   — 统计行数（支持 parse_filter JSON 过滤条件）
      diff    — 与上次巡检结果对比（变化率超阈值告警）
      info    — 仅记录不告警
    """
    items: list[tuple] = []

    def _item(id_, name, name_zh, category, check_key, desc, cmd, vendor,
              w, c, parse_type, textfsm_template, parse_field,
              parse_filter='', fallback_regex=''):
        items.append((
            id_, name, name_zh, category, check_key, desc,
            'CLI', cmd, '',                    # method=CLI, script_id=空（通过综合脚本采集）
            w, c, vendor, '', now, now,
            parse_type, textfsm_template, parse_field,
            parse_filter, fallback_regex, 1,    # enabled=1
        ))

    # ── Cisco IOS / IOS-XE ────────────────────────────────────────
    _item('net_cisco_ios_cpu', 'Cisco IOS CPU', 'Cisco IOS CPU 利用率', 'Network', 'cisco_ios_cpu',
          'CPU 利用率（5 秒）', 'show processes cpu sorted', 'cisco_ios',
          80, 90, 'numeric', 'cisco_ios_show_processes_cpu', 'CPU_USAGE_5_SEC',
          fallback_regex=r'CPU utilization.*?(\d+)%/\d+%')
    _item('net_cisco_ios_intf_down', 'Cisco IOS Interface Down', 'Cisco IOS 接口 Down 数', 'Network', 'cisco_ios_intf_down',
          '统计 notconnect/down 的接口数量', 'show interfaces status', 'cisco_ios',
          1, 3, 'count', 'cisco_ios_show_interfaces_status', 'STATUS',
          parse_filter='{"field":"STATUS","op":"in","value":["notconnect","disabled","err-disabled","down"]}')
    _item('net_cisco_ios_bgp_down', 'Cisco IOS BGP Peer Down', 'Cisco IOS BGP 邻居 Down 数', 'Network', 'cisco_ios_bgp_down',
          '统计非 Established 的 BGP 邻居', 'show ip bgp summary', 'cisco_ios',
          1, 2, 'count', 'cisco_ios_show_ip_bgp_summary', 'STATE_OR_PREFIXES_RECEIVED',
          parse_filter='{"field":"STATE_OR_PREFIXES_RECEIVED","op":"not_numeric"}')
    _item('net_cisco_ios_route_total', 'Cisco IOS Route Total', 'Cisco IOS 路由总数', 'Network', 'cisco_ios_route_total',
          '路由总数（与上次对比，变化 >10% 告警）', 'show ip route summary', 'cisco_ios',
          10, 30, 'diff', 'cisco_ios_show_ip_route_summary', 'TOTAL_ROUTE_COUNT')

    # ── Cisco NX-OS ───────────────────────────────────────────────
    _item('net_cisco_nxos_cpu', 'Cisco NX-OS CPU', 'Cisco NX-OS CPU 利用率', 'Network', 'cisco_nxos_cpu',
          'CPU 利用率（5 秒）', 'show processes cpu', 'cisco_nxos',
          80, 90, 'numeric', 'cisco_nxos_show_processes_cpu', 'CPU_5_SEC')
    _item('net_cisco_nxos_bgp_down', 'Cisco NX-OS BGP Peer Down', 'Cisco NX-OS BGP 邻居 Down 数', 'Network', 'cisco_nxos_bgp_down',
          '统计非 Established 的 BGP 邻居', 'show bgp ipv4 unicast summary', 'cisco_nxos',
          1, 2, 'count', 'cisco_nxos_show_ip_bgp_summary', 'STATE_PFXRCD',
          parse_filter='{"field":"STATE_PFXRCD","op":"not_numeric"}')

    # ── 华为 VRPv5 (S系列/AR/老NE) ────────────────────────────────
    _item('net_huawei_vrp_cpu', '华为 VRPv5 CPU', '华为 VRPv5 CPU 利用率', 'Network', 'huawei_vrp_cpu',
          'CPU 利用率', 'display cpu-usage', 'huawei_vrp',
          80, 90, 'numeric', 'huawei_vrp_display_cpu_usage', 'CPU_5_SEC',
          fallback_regex=r'CPU utilization for five seconds:\s+(\d+)%')
    _item('net_huawei_vrp_mem', '华为 VRPv5 Memory', '华为 VRPv5 内存利用率', 'Network', 'huawei_vrp_mem',
          '内存利用率', 'display memory-usage', 'huawei_vrp',
          80, 90, 'numeric', 'huawei_vrp_display_memory_usage', 'MEMORY_USING_PCT',
          fallback_regex=r'Memory Using Percentage Is:\s+(\d+)%')
    _item('net_huawei_vrp_intf_down', '华为 VRPv5 Interface Down', '华为 VRPv5 接口 Down 数', 'Network', 'huawei_vrp_intf_down',
          '统计 down 的接口数量', 'display interface brief', 'huawei_vrp',
          1, 3, 'count', 'huawei_vrp_display_interface_brief', 'PHY',
          parse_filter='{"field":"PHY","op":"in","value":["down","*down"]}')
    _item('net_huawei_vrp_bgp_down', '华为 VRPv5 BGP Peer Down', '华为 VRPv5 BGP 邻居 Down 数', 'Network', 'huawei_vrp_bgp_down',
          '统计非 Established 的 BGP 邻居', 'display bgp peer', 'huawei_vrp',
          1, 2, 'count', 'huawei_vrp_display_bgp_peer', 'STATE',
          parse_filter='{"field":"STATE","op":"!=","value":"Established"}')
    _item('net_huawei_vrp_route_total', '华为 VRPv5 Route Total', '华为 VRPv5 路由总数', 'Network', 'huawei_vrp_route_total',
          '路由总数（与上次对比）', 'display ip routing-table statistics', 'huawei_vrp',
          10, 30, 'diff', 'huawei_vrp_display_ip_routing_table_statistics', 'ACTIVE_COUNT',
          parse_filter='{"field":"PROTO","op":"==","value":"Total"}')

    # ── 华为 VRPv8 (CE系列/新NE) ──────────────────────────────────
    _item('net_huawei_vrpv8_cpu', '华为 VRPv8 CPU', '华为 VRPv8 CPU 利用率', 'Network', 'huawei_vrpv8_cpu',
          'CPU 利用率', 'display cpu-usage', 'huawei_vrpv8',
          80, 90, 'numeric', 'huawei_vrp_display_cpu_usage', 'CPU_USAGE_PCT',
          fallback_regex=r'CPU Usage:\s+(\d+)(?:\.\d+)?%')
    _item('net_huawei_vrpv8_mem', '华为 VRPv8 Memory', '华为 VRPv8 内存利用率', 'Network', 'huawei_vrpv8_mem',
          '内存利用率', 'display memory-usage', 'huawei_vrpv8',
          80, 90, 'numeric', 'huawei_vrp_display_memory_usage', 'MEMORY_USING_PCT',
          fallback_regex=r'Memory Using Percentage Is:\s+(\d+)%')
    _item('net_huawei_vrpv8_route_total', '华为 VRPv8 Route Total', '华为 VRPv8 路由总数', 'Network', 'huawei_vrpv8_route_total',
          '路由总数（与上次对比）', 'display ip routing-table statistics', 'huawei_vrpv8',
          10, 30, 'diff', 'huawei_vrp_display_ip_routing_table_statistics', 'ACTIVE_COUNT',
          parse_filter='{"field":"PROTO","op":"==","value":"Total"}')

    # ── H3C Comware ───────────────────────────────────────────────
    _item('net_h3c_cpu', 'H3C Comware CPU', 'H3C Comware CPU 利用率', 'Network', 'h3c_comware_cpu',
          'CPU 利用率', 'display cpu-usage', 'h3c_comware',
          80, 90, 'numeric', 'hp_comware_display_cpu_usage', 'CPU_5_SEC',
          fallback_regex=r'(\d+)%\s+in\s+last\s+5\s+seconds')
    _item('net_h3c_mem', 'H3C Comware Memory', 'H3C Comware 内存利用率', 'Network', 'h3c_comware_mem',
          '内存利用率（计算 Used/Total）', 'display memory', 'h3c_comware',
          80, 90, 'numeric', 'hp_comware_display_memory', 'USED_KB',
          fallback_regex=r'Used\s*\(kB\):\s+(\d+)')
    _item('net_h3c_intf_down', 'H3C Comware Interface Down', 'H3C Comware 接口 Down 数', 'Network', 'h3c_comware_intf_down',
          '统计 DOWN 的接口数量', 'display interface brief', 'h3c_comware',
          1, 3, 'count', 'hp_comware_display_interface_brief', 'LINK',
          parse_filter='{"field":"LINK","op":"in","value":["DOWN","down"]}')
    _item('net_h3c_bgp_down', 'H3C Comware BGP Peer Down', 'H3C Comware BGP 邻居 Down 数', 'Network', 'h3c_comware_bgp_down',
          '统计非 Established 的 BGP 邻居', 'display bgp peer ipv4', 'h3c_comware',
          1, 2, 'count', 'hp_comware_display_bgp_peer_ipv4', 'STATE',
          parse_filter='{"field":"STATE","op":"!=","value":"Established"}')
    _item('net_h3c_route_total', 'H3C Comware Route Total', 'H3C Comware 路由总数', 'Network', 'h3c_comware_route_total',
          '路由总数（与上次对比）', 'display ip routing-table statistics', 'h3c_comware',
          10, 30, 'diff', 'hp_comware_display_ip_routing_table_statistics', 'ACTIVE',
          parse_filter='{"field":"PROTO","op":"==","value":"Total"}')

    # ── Juniper JunOS ─────────────────────────────────────────────
    _item('net_juniper_cpu', 'Juniper JunOS CPU', 'Juniper JunOS CPU 利用率', 'Network', 'juniper_junos_cpu',
          'CPU 利用率（100 - Idle）', 'show chassis routing-engine', 'juniper_junos',
          80, 90, 'numeric', 'juniper_junos_show_chassis_routing_engine', 'CPU_IDLE',
          fallback_regex=r'Idle\s+(\d+)\s+percent')
    _item('net_juniper_mem', 'Juniper JunOS Memory', 'Juniper JunOS 内存利用率', 'Network', 'juniper_junos_mem',
          '内存利用率', 'show chassis routing-engine', 'juniper_junos',
          80, 90, 'numeric', 'juniper_junos_show_chassis_routing_engine', 'MEMORY_UTIL_PCT',
          fallback_regex=r'Memory utilization\s+(\d+)\s+percent')
    _item('net_juniper_route_total', 'Juniper JunOS Route Total', 'Juniper JunOS 路由总数', 'Network', 'juniper_junos_route_total',
          '路由总数（与上次对比）', 'show route summary', 'juniper_junos',
          10, 30, 'diff', 'juniper_junos_show_route_summary', 'ACTIVE_ROUTE_COUNT')

    # ── Arista EOS ────────────────────────────────────────────────
    _item('net_arista_cpu', 'Arista EOS CPU', 'Arista EOS CPU 利用率', 'Network', 'arista_eos_cpu',
          'CPU 利用率', 'show processes top once', 'arista_eos',
          80, 90, 'numeric', 'arista_eos_show_processes_top_once', 'CPU_USER')

    return items


def _table_columns_deprecated(cursor, table_name: str) -> set[str]:
    """DEPRECATED — kept for backward compat, use _table_columns instead."""
    return _table_columns(cursor, table_name)

def init_db():
    global _db_initialized
    if _db_initialized:
        return
    
    conn = get_db_connection()
    try:
        # Use autocommit for initialization to prevent transaction poisoning
        if _USE_PG and hasattr(conn, 'autocommit'):
            conn.autocommit = True
        
        # Ensure data directories exist
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
        # We catch and log, but don't re-raise to avoid FastAPI lifespan loop
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
        sys_contact TEXT
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
        script_type TEXT DEFAULT 'shell', -- shell, python, ansible
        author TEXT DEFAULT 'admin',
        version TEXT DEFAULT 'v1.0.0',
        status TEXT DEFAULT 'released',   -- draft, pending_audit, released, rejected
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
        ('takeover_error', "TEXT DEFAULT ''")
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
        # ── 脚本版本管理扩展字段 ──
        ('parent_script_id', "TEXT DEFAULT ''"),     # 指向上一版本
        ('script_family', "TEXT DEFAULT ''"),         # 脚本族标识
        ('is_latest', 'INTEGER DEFAULT 1')            # 是否为该族的最新版本
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

    # Per-device execution results (replaces bulky results_json blob)
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

    # Password reset verification codes (sent via Feishu/DingTalk/WeChat)
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

    # ── Config drift detection results ──
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

    # ── IP/VLAN resource management ──
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

    # Migration: add device_type column if missing
    ip_addr_cols = _table_columns(cursor, 'ip_addresses')
    if 'device_type' not in ip_addr_cols:
        cursor.execute("ALTER TABLE ip_addresses ADD COLUMN device_type TEXT DEFAULT ''")

    # ── Capacity planning snapshots (daily link/device utilization) ──
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

    # ── Physical Asset Management ──
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

    # Migration: add server-specific columns to physical_assets
    ensure_column('physical_assets', 'vlan', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'uplink_switch', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'uplink_port', "TEXT DEFAULT ''")
    ensure_column('physical_assets', 'lifecycle_status', "TEXT DEFAULT 'staging'")

    # Migration: add connection and credential columns for general assets (e.g. servers)
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

    # Rack planning on assets: device height (U) and optional planned start RU for DCIM install flow
    ensure_column('physical_assets', 'u_height', 'INTEGER NOT NULL DEFAULT 1')
    ensure_column('physical_assets', 'planned_start_u', 'INTEGER')

    # Migration: link devices to physical_assets (Plan-A unification)
    ensure_column('devices', 'asset_id', 'TEXT')
    ensure_column('devices', 'vendor', "TEXT DEFAULT ''")

    # Migration: device lifecycle status (staging → production → maintenance → decommissioned)
    ensure_column('devices', 'lifecycle_status', "TEXT DEFAULT 'staging'")

    # Migration: dual-credential model (normal + privileged)
    ensure_column('devices', 'enable_password', "TEXT DEFAULT ''")
    ensure_column('devices', 'priv_username', "TEXT DEFAULT ''")
    # Credential source: 'local' (Fernet-encrypted in DB) or 'vault' (HashiCorp Vault KV)
    ensure_column('devices', 'credential_source', "TEXT DEFAULT 'local'")
    # Vault KV path (e.g. 'netops/devices/core-sw-01'), only used when credential_source='vault'
    ensure_column('devices', 'vault_path', "TEXT DEFAULT ''")

    # Migration: device onboarding status (口令上手 state machine)
    ensure_column('devices', 'onboarding_status', "TEXT DEFAULT 'active'")
    ensure_column('devices', 'onboarding_updated_at', "TEXT DEFAULT ''")

    # Migration: password rotation tracking
    ensure_column('devices', 'password_last_rotated', "TEXT DEFAULT ''")
    ensure_column('devices', 'password_expires_at', "TEXT DEFAULT ''")
    ensure_column('devices', 'rotation_status', "TEXT DEFAULT ''")  # rotating / completed / failed

    # Backfill for dual-auth assets created before normal_username column existed.
    # Keep behavior predictable: normal access should use normal_username first.
    cursor.execute(
        '''
        UPDATE physical_assets
        SET normal_username = COALESCE(normal_username, username, '')
        WHERE LOWER(COALESCE(auth_model, 'single')) = 'dual'
          AND COALESCE(normal_username, '') = ''
          AND COALESCE(username, '') != ''
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
        access_level TEXT NOT NULL DEFAULT 'normal',  -- normal | admin
        reason TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',        -- pending | approved | rejected | expired
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

    # ── PAM Controlled Sessions (受控会话生命周期) ──
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

    # Migration: add session_id to pam_access_requests if missing
    pam_req_cols = _table_columns(cursor, 'pam_access_requests')
    if pam_req_cols and 'session_id' not in pam_req_cols:
        cursor.execute("ALTER TABLE pam_access_requests ADD COLUMN session_id TEXT DEFAULT ''")

    # Auto-link existing devices to matching assets, or create missing assets (Plan-A unification)
    unlinked = cursor.execute(
        "SELECT id, hostname, ip_address, sn, model, role, site, vendor, status, lifecycle_status FROM devices WHERE (asset_id IS NULL OR asset_id = '')"
    ).fetchall()
    if unlinked:
        for dev in unlinked:
            # Check if there's a physical asset with the same hostname or IP
            match = cursor.execute(
                "SELECT id FROM physical_assets WHERE asset_type='network_device' AND (hostname = ? OR management_ip = ?) LIMIT 1",
                (dev['hostname'], dev['ip_address'])
            ).fetchone()
            if match:
                cursor.execute('UPDATE devices SET asset_id = ? WHERE id = ?', (match['id'], dev['id']))
            else:
                # Create a new physical_asset
                asset_id = f"asset-{uuid.uuid4().hex[:12]}"
                now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
                
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
                    dev['status'] or 'active', '', '', '', '', now, now,
                    dev['lifecycle_status'] or 'staging'
                ))
                cursor.execute('UPDATE devices SET asset_id = ? WHERE id = ?', (asset_id, dev['id']))


    # ── Change Order / Ticket Management ──
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
    ensure_column('change_orders', 'initial_reviewer_id', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'initial_reviewer_username', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'final_approver_id', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'final_approver_username', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'authorization_exempt', "INTEGER DEFAULT 0")
    ensure_column('change_orders', 'approval_token', "TEXT DEFAULT ''")
    ensure_column('change_orders', 'rejected_reason', "TEXT DEFAULT ''")

    ensure_column('change_orders', 'control_sheet_json', "TEXT DEFAULT '{}'")
    
    # ── Change Order Control Sheet Attachments ──
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

    # ── Change Order Bookmarks ──
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS change_order_bookmarks (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        order_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(user_id, order_id)
    )
    ''')

    # ── Change Order Templates ──
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

    # ── System Settings (for setup wizard state etc.) ──
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT '',
        updated_at TEXT
    )
    ''')

    # ── Device Inspection (Patrol) ──
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

    # Migration: add time-range scheduling, description and check_items columns
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

    # ── Scheduled Jobs (定时作业 + 执行计划) ──
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
        created_by TEXT DEFAULT 'system',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_job_type ON scheduled_jobs(job_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_status ON scheduled_jobs(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_enabled ON scheduled_jobs(enabled)')

    # ── Tag System: definitions + device-tag junction ──
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

    # ── Rack Management (机柜管理) ──

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

    # ── Inspection Items (巡检指标项管理) ──
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS inspection_items (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        name_zh TEXT NOT NULL,
        category TEXT NOT NULL,
        check_key TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT '',
        method TEXT DEFAULT 'SNMP', -- SNMP, SSH, Shell, Agent
        command TEXT DEFAULT '',     -- Specific command or OID
        script_id TEXT DEFAULT '',   -- Reference to scripts table
        warning_threshold REAL,
        critical_threshold REAL,
        vendor TEXT DEFAULT '',
        oid TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
        ''')
        
    # Migration: Add missing columns if they don't exist
    for col, dtype in [('script_id', "TEXT DEFAULT ''"), ('warning_threshold', 'REAL'), ('critical_threshold', 'REAL'), ('method', "TEXT DEFAULT 'SNMP'"), ('command', "TEXT DEFAULT ''"),
                       # ── TextFSM 解析扩展字段 ──
                       ('parse_type', "TEXT DEFAULT 'numeric'"),       # numeric | status | count | diff | info
                       ('textfsm_template', "TEXT DEFAULT ''"),          # 模板文件名（含 .textfsm）
                       ('parse_field', "TEXT DEFAULT ''"),               # 从 TextFSM 结果中提取的字段名
                       ('parse_filter', "TEXT DEFAULT ''"),              # count/diff 类型的过滤条件 (JSON)
                       ('fallback_regex', "TEXT DEFAULT ''"),            # TextFSM 失败时的正则兜底
                       ('enabled', 'INTEGER DEFAULT 1')]:                 # 是否启用该指标
        ensure_column('inspection_items', col, dtype)
        
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_inspection_items_cat ON inspection_items(category)')

    # Migration for inspection_results
    ensure_column('inspection_results', 'metrics_json', "TEXT DEFAULT '{}'")

    # 提前定义 now，供后续所有 seed 操作使用
    now = _beijing_now_iso()

    # Seed standard scripts
    std_scripts = [
        ('std_linux_mem', 'Linux 内存使用率', '#!/bin/bash\n# 计算内存使用率 (已用/总计)\nmem_total=$(free | grep Mem | awk "{print $2}")\nmem_used=$(free | grep Mem | awk "{print $3}")\n[ "$mem_total" -gt 0 ] && echo | awk "{print ($mem_used/$mem_total)*100}" || echo 0', '计算系统内存使用百分比 (0-100)', 'Linux', 'standard'),
        ('std_linux_cpu', 'Linux CPU 使用率', '#!/bin/bash\n# 提取系统 CPU 整体利用率\ntop -bn1 | grep "Cpu(s)" | sed "s/.*, *\\([0-9.]*\\)%* id.*/\\1/" | awk "{print 100 - $1}"', '计算系统整体 CPU 使用率 (0-100)', 'Linux', 'standard'),
        ('std_linux_disk', 'Linux 全量磁盘空间', '#!/bin/bash\n# 扫描所有本地挂载点，过滤虚拟分区，按使用率排序\necho "Detailed Disk Usage (Top 10):"\ndf -hP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | sort -k5 -rn | head -n 10\n# 提取全局最大利用率作为判定值\nmax_usage=$(df -hP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | awk "{print $5}" | sed "s/%//" | sort -rn | head -1)\necho "MAX_UTILIZATION: ${max_usage:-0}"', '扫描所有本地分区，取最大利用率百分比', 'Linux', 'standard'),
        ('std_linux_inode', 'Linux 全量磁盘 Inode', '#!/bin/bash\n# 扫描所有本地挂载点 Inode 使用率\necho "Detailed Inode Usage (Top 10):"\ndf -iP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | sort -k5 -rn | head -n 10\nmax_inode=$(df -iP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | awk "{print $5}" | sed "s/%//" | sort -rn | head -1)\necho "MAX_INODE_UTIL: ${max_inode:-0}"', '扫描所有本地分区，取最大 Inode 使用率', 'Linux', 'standard'),
        ('std_linux_iowait', 'Linux IO Wait 延迟', '#!/bin/bash\n# 提取 CPU IO 等待比例\niostat -c 1 2 | grep -v "avg-cpu" | tail -1 | awk "{print $4}"', 'CPU 等待磁盘 IO 时间占比 (0-100)', 'Linux', 'standard'),
        ('std_linux_swap', 'Linux Swap 使用率', '#!/bin/bash\nfree | grep Swap | awk "{if ($2>0) print ($3/$2)*100; else print 0}"', '交换分区使用百分比 (0-100)', 'Linux', 'standard'),
        ('std_linux_load', 'Linux CPU 负载比例', '#!/bin/bash\n# 计算负载与核心数的比值\ncores=$(grep -c ^processor /proc/cpuinfo)\nload=$(uptime | awk -F "load average:" "{print $2}" | cut -d, -f1 | xargs)\necho | awk "{print ($load/$cores)*100}"', '系统 1min 负载相对于核心数的比例', 'Linux', 'standard'),
        ('std_linux_conns', 'Linux TCP 连接数', '#!/bin/bash\nss -ant | grep ESTAB | wc -l', '统计系统 Established 状态的 TCP 连接总数', 'Linux', 'standard'),
        ('std_linux_proc', 'Linux 关键进程巡检', '#!/bin/bash\n# 检查指定的多个关键进程，返回丢失的数量\nprocs=${1:-"sshd crond docker"}\nmissing=0\nfor p in $procs; do\n  if ! pgrep -f "$p" > /dev/null; then\n    echo "[CRITICAL] Process not found: $p"\n    missing=$((missing + 1))\n  fi\ndone\necho "MISSING_COUNT: $missing"', '检查进程存活状态，返回未运行的进程数', 'Linux', 'standard'),

        # ── 网络设备综合巡检脚本（每个平台一个，一次连接采集所有指标）──
        # Cisco IOS / IOS-XE
        ('insp_cisco_ios_full', 'Cisco IOS 综合巡检', 'show version\nshow processes cpu sorted\nshow processes memory sorted\nshow environment temperature\nshow environment power all\nshow interfaces status\nshow ip bgp summary\nshow ip ospf neighbor\nshow ip route summary', 'Cisco IOS / IOS-XE 综合巡检脚本，覆盖 CPU/内存/温度/电源/接口/路由协议/路由数量', 'cisco_ios', 'inspection'),
        # Cisco NX-OS
        ('insp_cisco_nxos_full', 'Cisco NX-OS 综合巡检', 'show version\nshow processes cpu\nshow system resources\nshow environment\nshow interface brief\nshow ip bgp summary\nshow ip ospf neighbor\nshow ip route summary', 'Cisco NX-OS 综合巡检脚本，覆盖 CPU/内存/环境/接口/路由协议/路由数量', 'cisco_nxos', 'inspection'),
        # 华为 VRPv5 (S系列/AR/老NE)
        ('insp_huawei_vrp_full', '华为 VRPv5 综合巡检', 'display version\ndisplay cpu-usage\ndisplay memory-usage\ndisplay temperature all\ndisplay fan\ndisplay power\ndisplay interface brief\ndisplay bgp peer\ndisplay ospf peer brief\ndisplay ip routing-table statistics', '华为 VRPv5（S系列/AR/老NE）综合巡检脚本', 'huawei_vrp', 'inspection'),
        # 华为 VRPv8 (CE系列/新NE)
        ('insp_huawei_vrpv8_full', '华为 VRPv8 综合巡检', 'display version\ndisplay cpu-usage\ndisplay memory-usage\ndisplay environment\ndisplay interface brief\ndisplay bgp peer\ndisplay ospf peer brief\ndisplay ip routing-table statistics', '华为 VRPv8（CE系列/新NE）综合巡检脚本', 'huawei_vrpv8', 'inspection'),
        # H3C Comware
        ('insp_h3c_comware_full', 'H3C Comware 综合巡检', 'display version\ndisplay cpu-usage\ndisplay memory\ndisplay environment\ndisplay fan\ndisplay power\ndisplay interface brief\ndisplay bgp peer ipv4\ndisplay ospf peer\ndisplay ip routing-table statistics', 'H3C Comware V7/V9 综合巡检脚本', 'h3c_comware', 'inspection'),
        # Juniper JunOS
        ('insp_juniper_junos_full', 'Juniper JunOS 综合巡检', 'show version\nshow chassis routing-engine\nshow chassis environment\nshow interfaces terse\nshow bgp summary\nshow ospf neighbor\nshow route summary', 'Juniper JunOS 综合巡检脚本（MX/EX/QFX/SRX 通用）', 'juniper_junos', 'inspection'),
        # Arista EOS
        ('insp_arista_eos_full', 'Arista EOS 综合巡检', 'show version\nshow processes top once\nshow memory\nshow environment temperature\nshow environment power\nshow interfaces status\nshow ip bgp summary\nshow ip ospf neighbor\nshow ip route summary', 'Arista EOS 综合巡检脚本', 'arista_eos', 'inspection')
    ]
    cursor.executemany(
        'INSERT INTO scripts (id, name, content, description, platform, category) VALUES (?,?,?,?,?,?) ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content, description = EXCLUDED.description',
        std_scripts
    )

    # ── 网络设备巡检脚本的补充元数据（script_type=cli, status=released, author=system）──
    # 这些字段通过单独的 UPDATE 设置，因为基础 INSERT 语句列数固定
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

    # Seed/Update default items
    default_items = [
        # --- Network Device ---
        ('net_ping', 'Connectivity (Ping)', '网络连通性 (Ping)', 'Network', 'ping', '检查设备 ICMP 响应时间与丢包率', 'ICMP', 'ping -c 3 {ip}', '', 100, 200, 'Generic', '', now, now),
        ('net_ssh', 'SSH Accessibility', '管理通道 (SSH)', 'Network', 'ssh', '检查 22 端口可用性', 'TCP', 'socket.connect({ip}, 22)', '', 500, 2000, 'Generic', '', now, now),
        ('net_cpu', 'CPU Utilization', 'CPU 利用率 (SNMP)', 'Network', 'cpu', '监控网络设备 CPU 负载', 'SNMP', 'OID: 1.3.6.1.4.1.9.9.109.1.1.1.1.7', '', 85, 95, 'Cisco', '1.3.6.1.4.1.9.9.109.1.1.1.1.7', now, now),
        ('net_mem', 'Memory Utilization', '内存利用率 (SNMP)', 'Network', 'memory', '监控网络设备内存消耗', 'SNMP', 'OID: 1.3.6.1.4.1.9.9.48.1.1.1.5.1', '', 90, 98, 'Cisco', '1.3.6.1.4.1.9.9.48.1.1.1.5.1', now, now),
        ('net_bgp', 'BGP Peer Status', 'BGP 邻居状态', 'Network', 'bgp_neighbor', '监控 BGP 状态机', 'SSH', 'show ip bgp summary', '', 0, 1, 'Generic', '', now, now),

        # --- Server / Host ( 精细化采集) ---
        ('srv_cpu_load', 'CPU Load Average', 'CPU 系统负载', 'Server', 'cpu_load', '监控 1min 负载相对于核心数的比例', 'Shell', 'std_linux_load', 'std_linux_load', 80, 150, 'Linux', '', now, now),
        ('srv_cpu_util', 'CPU Utilization', 'CPU 使用率', 'Server', 'cpu_util', '监控整体 CPU 使用率 (0-100)', 'Shell', 'std_linux_cpu', 'std_linux_cpu', 90, 95, 'Linux', '', now, now),
        ('srv_mem_avail', 'Available Memory', '可用内存', 'Server', 'mem_avail', '监控系统内存使用百分比 (0-100)', 'Shell', 'std_linux_mem', 'std_linux_mem', 85, 95, 'Linux', '', now, now),
        ('srv_swap', 'Swap Usage', '交换分区使用率', 'Server', 'swap_util', '监控交换分区使用百分比 (0-100)', 'Shell', 'std_linux_swap', 'std_linux_swap', 70, 90, 'Linux', '', now, now),
        ('srv_iowait', 'Disk IO Wait', '磁盘 IO 等待 (IOWait)', 'Server', 'io_wait', '监控 CPU 等待 IO 时间占比 (阈值: >15% 告警)', 'Shell', 'std_linux_iowait', 'std_linux_iowait', 15, 30, 'Linux', '', now, now),
        ('srv_disk_util', 'Disk Space Usage', '磁盘空间利用率', 'Server', 'disk_util', '监控根分区空间占用 (0-100)', 'Shell', 'std_linux_disk', 'std_linux_disk', 90, 95, 'Linux', '', now, now),
        ('srv_disk_inode', 'Inode Utilization', 'Inode 使用率', 'Server', 'inode_util', '监控根分区 Inode 占用 (0-100)', 'Shell', 'std_linux_inode', 'std_linux_inode', 90, 95, 'Linux', '', now, now),
        ('srv_net_conns', 'Established Connections', '并发连接数', 'Server', 'tcp_conns', '监控 TCP Established 状态连接数', 'Shell', 'std_linux_conns', 'std_linux_conns', 5000, 10000, 'Linux', '', now, now),
        ('srv_process', 'Critical Processes', '核心进程监控', 'Server', 'process_health', '监控指定进程是否存在', 'Shell', 'std_linux_proc', 'std_linux_proc', 1, 0, 'Linux', '', now, now),
    ]

    # ── 网络设备巡检指标（CLI 方式，需要后续迁移补充扩展字段） ──
    # 这里使用统一的 insert_network_items 函数处理，因为它们需要 parse_type / textfsm_template / parse_field 等扩展字段
    network_items_v2 = _build_network_inspection_items(now)
    
    # ── Seed/Update default items ──
    if _USE_PG:
        # PostgreSQL: Atomic Upsert using ON CONFLICT
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
        # SQLite: INSERT OR REPLACE
        for item in default_items:
            cursor.execute('''
                INSERT OR REPLACE INTO inspection_items 
                (id, name, name_zh, category, check_key, description, method, command, script_id, warning_threshold, critical_threshold, vendor, oid, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', item)

    # ── 网络设备巡检指标 Seed（使用扩展字段：parse_type / textfsm_template / parse_field）──
    # 这些指标有 15 列（多了 parse_type / textfsm_template / parse_field / parse_filter / fallback_regex / enabled 6 个字段）
    # 分别对应：id, name, name_zh, category, check_key, description, method, command, script_id,
    #          warning_threshold, critical_threshold, vendor, oid, created_at, updated_at,
    #          parse_type, textfsm_template, parse_field, parse_filter, fallback_regex, enabled
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

    # ── Seed Default Admin User ──
    admin_exists = cursor.execute("SELECT 1 FROM users WHERE username = 'admin'").fetchone()
    if not admin_exists:
        import bcrypt
        # Default password: admin
        hashed = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
        cursor.execute(
            "INSERT INTO users (id, username, password, role, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "admin", hashed, "Administrator", "active", now)
        )
        logger.info("[Database] Default admin user created (admin/admin)")

    conn.commit()

if __name__ == "__main__":
    init_db()
