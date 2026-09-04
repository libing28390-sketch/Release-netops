"""Safe PostgreSQL database lifecycle helpers for the backend test suite."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from urllib.parse import unquote, urlparse, urlunparse

import psycopg2
import psycopg2.extras
from psycopg2 import sql

import database.core as database_core
import database.schema as database_schema


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_PROTECTED_DATABASE_NAMES = {
    "netops",
    "nexora",
    "nexora_prod",
    "nexora_production",
    "production",
}
_TEST_PREFIX = "nexora_pytest_"
_temporary_connections: set["PostgreSQLTestConnection"] = set()
_temporary_targets: dict[str, DatabaseTarget] = {}
_named_target_keys: dict[str, str] = {}


@dataclass(frozen=True)
class DatabaseTarget:
    name: str
    url: str
    admin_url: str


@dataclass(frozen=True)
class DatabaseModuleState:
    url: str
    use_pg: bool
    schema_use_pg: bool
    initialized: bool


def validate_test_server_url(database_url: str) -> None:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise RuntimeError("Backend tests require a PostgreSQL DATABASE_URL")
    if not parsed.hostname:
        raise RuntimeError("Backend tests require a PostgreSQL host")
    allow_remote = os.environ.get("NEXORA_ALLOW_REMOTE_TEST_POSTGRES", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if parsed.hostname.lower() not in _LOCAL_HOSTS and not allow_remote:
        raise RuntimeError(
            "Refusing remote PostgreSQL for tests. Use a local/CI service or explicitly set "
            "NEXORA_ALLOW_REMOTE_TEST_POSTGRES=1 for a dedicated test server."
        )


def capture_database_state() -> DatabaseModuleState:
    return DatabaseModuleState(
        url=database_core._DATABASE_URL,
        use_pg=database_core._USE_PG,
        schema_use_pg=database_schema._USE_PG,
        initialized=database_schema._db_initialized,
    )


def close_database_pool() -> None:
    pool = getattr(database_core, "_pg_pool", None)
    if pool is not None:
        pool.closeall()
    database_core._pg_pool = None


def switch_database(target_url: str, *, initialized: bool) -> None:
    validate_test_server_url(target_url)
    close_database_pool()
    database_core._DATABASE_URL = target_url
    database_core._USE_PG = True
    database_schema._USE_PG = True
    database_schema._db_initialized = initialized


def restore_database_state(state: DatabaseModuleState) -> None:
    close_database_pool()
    database_core._DATABASE_URL = state.url
    database_core._USE_PG = state.use_pg
    database_schema._USE_PG = state.schema_use_pg
    database_schema._db_initialized = state.initialized


def _admin_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path="/postgres", params="", query="", fragment=""))


def _database_name(database_url: str) -> str:
    return unquote(urlparse(database_url).path.lstrip("/"))


def create_test_database(
    source_url: str,
    *,
    purpose: str,
    template_name: str | None = None,
) -> DatabaseTarget:
    validate_test_server_url(source_url)
    normalized_purpose = "".join(char if char.isalnum() else "_" for char in purpose.lower()).strip("_")
    normalized_purpose = normalized_purpose[:20] or "case"
    name = f"{_TEST_PREFIX}{normalized_purpose}_{uuid.uuid4().hex[:12]}"
    admin_url = _admin_url(source_url)
    parsed = urlparse(source_url)
    target_url = urlunparse(parsed._replace(path=f"/{name}", params="", query="", fragment=""))

    admin = psycopg2.connect(admin_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            if template_name:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                        sql.Identifier(name),
                        sql.Identifier(template_name),
                    )
                )
            else:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        admin.close()
    return DatabaseTarget(name=name, url=target_url, admin_url=admin_url)


def drop_test_database(target: DatabaseTarget) -> None:
    if not target.name.startswith(_TEST_PREFIX) or target.name in _PROTECTED_DATABASE_NAMES:
        raise RuntimeError(f"Refusing to drop non-test database: {target.name}")
    admin = psycopg2.connect(target.admin_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(target.name))
            )
    finally:
        admin.close()


def assert_no_test_databases(database_url: str) -> None:
    validate_test_server_url(database_url)
    current_name = _database_name(database_url)
    admin = psycopg2.connect(_admin_url(database_url))
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT datname FROM pg_database WHERE datname LIKE %s AND datname <> %s ORDER BY datname",
                (f"{_TEST_PREFIX}%", current_name),
            )
            leftovers = [row[0] for row in cursor.fetchall()]
    finally:
        admin.close()
    if leftovers:
        raise RuntimeError(f"PostgreSQL test databases were not cleaned up: {leftovers}")


class PostgreSQLTestCursor:
    """Cursor adapter matching the application's question-mark SQL contract."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, statement, params=None):
        self._cursor.execute(
            database_core._adapt_pg_sql(
                statement,
                escape_percent=params is not None,
            ),
            params,
        )
        return self

    def executemany(self, statement, params_list):
        self._cursor.executemany(database_core._adapt_pg_sql(statement), params_list)
        return self

    def executescript(self, script):
        result = self.execute(script)
        # Script-style setup leaves schema/data visible to a second connection.
        # The PostgreSQL adapter must provide the same semantics for the legacy
        # unit-style tests that use it.
        self._cursor.connection.commit()
        return result

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)


class PostgreSQLTestConnection:
    """Disposable blank PostgreSQL database used by legacy unit-style tests."""

    def __init__(self, target: DatabaseTarget):
        self._target = target
        self._connection = psycopg2.connect(target.url)
        self._closed = False
        _temporary_connections.add(self)
        _temporary_targets[target.name] = target

    def cursor(self):
        return PostgreSQLTestCursor(
            self._connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
        )

    def execute(self, statement, params=None):
        return self.cursor().execute(statement, params)

    def executemany(self, statement, params_list):
        return self.cursor().executemany(statement, params_list)

    def executescript(self, script):
        result = self.cursor().execute(script)
        # Keep the adapter compatible with the legacy executescript contract:
        # test-created tables and seed rows are immediately visible to other
        # connections opened against the same temporary database.
        self._connection.commit()
        return result

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    @property
    def autocommit(self):
        return self._connection.autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._connection.autocommit = value

    @property
    def row_factory(self):
        return PostgreSQLTestCursor

    @row_factory.setter
    def row_factory(self, _value):
        # DictCursor is always enabled; retain assignment compatibility while
        # tests are migrated away from driver-specific row-factory setup.
        return None

    def close(self):
        # Application services own and close their connection handles. Several
        # unit-style tests deliberately share one handle with the service and
        # inspect committed state afterward, so physical cleanup is deferred to
        # the autouse fixture at the end of the test.
        return None

    def _force_close(self):
        if self._closed:
            return
        self._closed = True
        _temporary_connections.discard(self)
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class PostgreSQLTestDriver:
    Connection = PostgreSQLTestConnection
    Row = PostgreSQLTestCursor
    IntegrityError = psycopg2.IntegrityError
    DatabaseError = psycopg2.DatabaseError

    @staticmethod
    def connect(_target=None) -> PostgreSQLTestConnection:
        key = str(_target) if _target is not None else ""
        target = None
        if key:
            target_name = _named_target_keys.get(key)
            if target_name:
                target = _temporary_targets.get(target_name)
        if target is None:
            target = create_test_database(
                database_core._DATABASE_URL,
                purpose="blank",
            )
            if key:
                _named_target_keys[key] = target.name
        return PostgreSQLTestConnection(target)


postgresql_test_driver = PostgreSQLTestDriver()


def close_temporary_test_connections() -> None:
    errors: list[Exception] = []
    for connection in list(_temporary_connections):
        try:
            connection._force_close()
        except Exception as exc:
            errors.append(exc)
    for target in list(_temporary_targets.values()):
        try:
            drop_test_database(target)
        except Exception as exc:
            errors.append(exc)
    _temporary_targets.clear()
    _named_target_keys.clear()
    if errors:
        raise RuntimeError(
            f"Failed to clean {len(errors)} temporary PostgreSQL test database(s)"
        ) from errors[0]
