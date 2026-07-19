import os
import re
import queue
import logging
import threading
import time
from datetime import datetime, timezone, timedelta

_BEIJING_TZ = timezone(timedelta(hours=8))

def _beijing_now_iso() -> str:
    """Helper to get current time in ISO format (Beijing time)."""
    return datetime.now(_BEIJING_TZ).isoformat(timespec='seconds')

# Load .env BEFORE reading DATABASE_URL from os.environ
try:
    from dotenv import load_dotenv
    # core.py lives at backend/database/core.py → the project root is three
    # levels up. (Two levels only reaches backend/, where there is no .env.)
    _project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    _env_path = os.path.join(_project_root, '.env')
    _env_local_path = os.path.join(_project_root, '.env.local')
    load_dotenv(_env_path, override=True)
    if os.path.exists(_env_local_path):
        load_dotenv(_env_local_path, override=True)
except ImportError:
    pass

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(BACKEND_DIR))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'netops.db')

logger = logging.getLogger(__name__)

# Connection mode detection
_DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()

_in_compose = os.path.exists('/.dockerenv') and os.environ.get('POSTGRES_USER') is not None
if not _in_compose and '@db:' in _DATABASE_URL:
    _DATABASE_URL = _DATABASE_URL.replace('@db:', '@localhost:')
    logger.info("Non-compose environment: Auto-replaced 'db' host with 'localhost' in DATABASE_URL")

normalized_db_url = _DATABASE_URL.lower()
_USE_PG = normalized_db_url.startswith('postgresql://') or normalized_db_url.startswith('postgres://')

_SERIAL_PK = 'SERIAL PRIMARY KEY' if _USE_PG else 'INTEGER PRIMARY KEY AUTOINCREMENT'
_JSON_ARRAY_FN = 'json_build_array' if _USE_PG else 'json_array'


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

_POOL_SIZE = int(os.environ.get('DB_POOL_SIZE', '16'))
_PG_OVERFLOW_MAX = max(0, int(os.environ.get('DB_POOL_OVERFLOW_MAX', '4')))
_PG_ACQUIRE_TIMEOUT = max(0.1, float(os.environ.get('DB_POOL_ACQUIRE_TIMEOUT_SECONDS', '10')))

# ── PostgreSQL Connection pooling wrappers ──
if _USE_PG:
    _pg_pool: psycopg2.pool.ThreadedConnectionPool | None = None
    _pg_overflow_active = 0
    _pg_overflow_lock = threading.Lock()
    _pg_pool_init_lock = threading.Lock()
    _pg_pool_condition = threading.Condition()

    def _reserve_pg_overflow() -> bool:
        global _pg_overflow_active
        with _pg_overflow_lock:
            if _pg_overflow_active >= _PG_OVERFLOW_MAX:
                return False
            _pg_overflow_active += 1
            return True

    def _release_pg_overflow() -> None:
        global _pg_overflow_active
        with _pg_overflow_lock:
            _pg_overflow_active = max(0, _pg_overflow_active - 1)
        with _pg_pool_condition:
            _pg_pool_condition.notify_all()

    def _notify_pg_connection_available() -> None:
        with _pg_pool_condition:
            _pg_pool_condition.notify_all()

    def _decode_pg_error(exc: BaseException) -> str:
        """Recover a readable message from a psycopg2 error that failed UTF-8 decode.

        On Windows with a non-UTF-8 (e.g. Chinese GBK) PostgreSQL locale, libpq
        returns connection-failure messages encoded in the OS locale. psycopg2
        decodes them as UTF-8 and raises UnicodeDecodeError, masking the real
        cause (bad password, missing database, server down). We recover the raw
        bytes and decode them with locale-aware fallbacks.
        """
        if isinstance(exc, UnicodeDecodeError) and isinstance(exc.object, (bytes, bytearray)):
            raw = bytes(exc.object)
            for enc in ('gbk', 'mbcs', 'latin-1'):
                try:
                    return raw.decode(enc).strip()
                except (LookupError, UnicodeDecodeError):
                    continue
            return raw.decode('utf-8', 'replace').strip()
        return str(exc)

    def _pg_connect(**kwargs):
        """psycopg2.connect forced to UTF-8 client encoding, with readable errors.

        ``client_encoding='UTF8'`` makes the server encode runtime messages as
        UTF-8 for this session. Connection-time failures happen before encoding
        negotiation, so any UnicodeDecodeError is converted into a readable
        OperationalError instead of the original cryptic byte-decode traceback.
        """
        kwargs.setdefault('client_encoding', 'UTF8')
        try:
            return psycopg2.connect(**kwargs)
        except UnicodeDecodeError as e:
            raise psycopg2.OperationalError(
                "无法连接 PostgreSQL（数据库返回非 UTF-8 错误消息，已转码）："
                + _decode_pg_error(e)
            ) from None

    def _ensure_database_exists():
        from urllib.parse import urlparse, urlunparse
        try:
            parsed = urlparse(_DATABASE_URL)
            db_name = parsed.path.lstrip('/')
            if not db_name or db_name.lower() == 'postgres':
                return
            
            # Connect to 'postgres' database to check / create the target database
            postgres_parsed = parsed._replace(path='/postgres')
            postgres_url = urlunparse(postgres_parsed)
            
            conn = _pg_connect(dsn=postgres_url)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
                if not cur.fetchone():
                    logger.info("Database '%s' does not exist, creating it now...", db_name)
                    cur.execute(f'CREATE DATABASE "{db_name}"')
            conn.close()
        except Exception as e:
            logger.error("Failed to ensure database exists: %s", e, exc_info=True)

    def _initialize_pg_pool():
        global _pg_pool
        if _pg_pool is None:
            _ensure_database_exists()
            try:
                _pg_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=2, maxconn=_POOL_SIZE, dsn=_DATABASE_URL,
                    client_encoding='UTF8',
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=5
                )
            except UnicodeDecodeError as e:
                # Surface the real cause (e.g. password/auth failure) instead of
                # the misleading byte-decode error from a GBK-locale server.
                raise psycopg2.OperationalError(
                    "无法初始化 PostgreSQL 连接池（数据库返回非 UTF-8 错误消息，已转码）："
                    + _decode_pg_error(e)
                ) from None

    def _ensure_pg_pool():
        """Initialize the shared pool once, even under concurrent startup requests."""
        global _pg_pool
        if _pg_pool is not None:
            return
        with _pg_pool_init_lock:
            if _pg_pool is None:
                _initialize_pg_pool()

    _LIKE_RE = re.compile(r'\bLIKE\b', re.IGNORECASE)

    class _PgCursor:
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
        __slots__ = ('_conn', '_raw', '_overflow')
        def __init__(self, wrapped, raw, overflow=False):
            self._conn = wrapped
            self._raw = raw
            self._overflow = overflow

        def close(self):
            raw = self._raw
            if raw is None:
                return
            self._raw = None
            self._conn = None
            try:
                raw.rollback()
            except Exception:
                pass
            if self._overflow:
                # 溢出连接不属于池，直接关闭，避免占用池容量
                try:
                    raw.close()
                except Exception:
                    pass
                finally:
                    _release_pg_overflow()
            else:
                try:
                    _pg_pool.putconn(raw)
                except Exception:
                    try:
                        raw.close()
                    except Exception:
                        pass
                finally:
                    _notify_pg_connection_available()

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

# ── SQLite Connection pooling wrappers ──
else:
    _pool: queue.Queue = queue.Queue(maxsize=_POOL_SIZE)
    _active_connections = 0

    class _PooledConnection:
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
    if _USE_PG:
        _ensure_pg_pool()
        _pg_kwargs = dict(
            keepalives=1, keepalives_idle=30,
            keepalives_interval=10, keepalives_count=5,
        )

        def acquire_connection():
            """Get a pooled connection, waiting briefly before failing under saturation."""
            deadline = time.monotonic() + _PG_ACQUIRE_TIMEOUT
            while True:
                try:
                    return _pg_pool.getconn(), False
                except psycopg2.pool.PoolError as pool_error:
                    if _reserve_pg_overflow():
                        try:
                            raw_connection = _pg_connect(dsn=_DATABASE_URL, **_pg_kwargs)
                            logger.warning(
                                "PG pool exhausted (max=%d). Using bounded overflow connection (active/max=%d/%d).",
                                _POOL_SIZE, _pg_overflow_active, _PG_OVERFLOW_MAX,
                            )
                            return raw_connection, True
                        except Exception:
                            _release_pg_overflow()
                            raise

                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise psycopg2.pool.PoolError(
                            "PG connection pool exhausted; waited %.1fs (pool=%d, overflow=%d/%d)"
                            % (_PG_ACQUIRE_TIMEOUT, _POOL_SIZE, _pg_overflow_active, _PG_OVERFLOW_MAX)
                        ) from pool_error
                    with _pg_pool_condition:
                        _pg_pool_condition.wait(timeout=min(0.25, remaining))

        raw, overflow = acquire_connection()

        try:
            with raw.cursor() as tmp_cur:
                tmp_cur.execute("SELECT 1")
            raw.rollback()
        except Exception:
            # 连接已失效，丢弃并重建一个
            try:
                if overflow:
                    raw.close()
                else:
                    _pg_pool.putconn(raw, close=True)
            except Exception:
                pass
            finally:
                if overflow:
                    _release_pg_overflow()
            raw, overflow = acquire_connection()
        return _PgPooledConnection(_PgRawConnection(raw), raw, overflow)
    else:
        conn = sqlite3.connect(DB_PATH, timeout=10.0, check_same_thread=False)
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA synchronous=NORMAL;')
        conn.row_factory = sqlite3.Row
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


def fetch_interface_data(conn, device_id: str) -> list[dict]:
    try:
        intf_rows = conn.execute('''
            SELECT 
                i.interface_name as name,
                i.interface_type,
                i.parent_interface_id,
                i.channel_group,
                i.aggregation_protocol,
                i.description,
                COALESCE(t.status, i.oper_status) as status,
                COALESCE(t.speed_mbps, i.speed / 1000000.0) as speed_mbps,
                COALESCE(t.in_bps, 0.0) as in_bps,
                COALESCE(t.out_bps, 0.0) as out_bps,
                COALESCE(t.bw_in_pct, 0.0) as bw_in_pct,
                COALESCE(t.bw_out_pct, 0.0) as bw_out_pct,
                COALESCE(t.in_pkts, 0) as in_ucast_pkts,
                COALESCE(t.out_pkts, 0) as out_ucast_pkts,
                COALESCE(t.in_errors, 0) as in_errors,
                COALESCE(t.out_errors, 0) as out_errors,
                COALESCE(t.in_discards, 0) as in_discards,
                COALESCE(t.out_discards, 0) as out_discards
            FROM interfaces i
            LEFT JOIN (
                SELECT latest.*
                FROM interface_telemetry_raw latest
                INNER JOIN (
                    SELECT interface_name, MAX(ts) as max_ts
                    FROM interface_telemetry_raw
                    WHERE device_id = ?
                    GROUP BY interface_name
                ) sub ON latest.interface_name = sub.interface_name AND latest.ts = sub.max_ts
                WHERE latest.device_id = ?
            ) t ON i.interface_name = t.interface_name
            WHERE i.device_id = ?
            ORDER BY i.interface_name
        ''', (device_id, device_id, device_id)).fetchall()
        return [dict(r) for r in intf_rows]
    except Exception as exc:
        logger.warning(f"Failed to fetch interface data for device {device_id}: {exc}")
        return []
