import os
import re
import queue
import logging
from datetime import datetime, timezone, timedelta

_BEIJING_TZ = timezone(timedelta(hours=8))

def _beijing_now_iso() -> str:
    """Helper to get current time in ISO format (Beijing time)."""
    return datetime.now(_BEIJING_TZ).isoformat(timespec='seconds')

# Load .env BEFORE reading DATABASE_URL from os.environ
try:
    from dotenv import load_dotenv
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

# ── PostgreSQL Connection pooling wrappers ──
if _USE_PG:
    _pg_pool: psycopg2.pool.ThreadedConnectionPool | None = None

    def _ensure_pg_pool():
        global _pg_pool
        if _pg_pool is None:
            _pg_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2, maxconn=_POOL_SIZE, dsn=_DATABASE_URL,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5
            )

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
        raw = _pg_pool.getconn()
        try:
            with raw.cursor() as tmp_cur:
                tmp_cur.execute("SELECT 1")
            raw.rollback()
        except Exception:
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
