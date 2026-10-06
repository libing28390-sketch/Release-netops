from database import get_db_connection
from database import core
from backend.tests.pg_test_utils import close_database_pool
import pytest
import psycopg2.pool


def _configure_pool(monkeypatch, size):
    close_database_pool()
    monkeypatch.setattr(core, "_POOL_SIZE", size)
    monkeypatch.setattr(core, "_POOL_MIN_SIZE", size)
    monkeypatch.setattr(core, "_PG_OVERFLOW_MAX", 0)


def test_pg_pool_reuses_connections_across_concurrent_bursts(isolated_db, monkeypatch):
    _configure_pool(monkeypatch, 4)

    def borrow_burst():
        connections = []
        try:
            for _ in range(4):
                connections.append(get_db_connection())
            return {
                connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
                for connection in connections
            }
        finally:
            for connection in connections:
                connection.close()

    first = borrow_burst()
    second = borrow_burst()
    assert len(first) == 4
    assert second == first
    assert len(core._pg_pool._used) == 0
    assert len(core._pg_pool._pool) == 4
    close_database_pool()


def test_reused_pg_connection_rolls_back_uncommitted_work(isolated_db, monkeypatch):
    _configure_pool(monkeypatch, 1)
    connection = get_db_connection()
    connection.execute("CREATE TABLE test_pool_rollback (value INTEGER)")
    connection.commit()
    pid = connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    connection.execute("INSERT INTO test_pool_rollback VALUES (1)")
    connection.close()

    reused = get_db_connection()
    try:
        assert reused.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] == pid
        assert reused.execute("SELECT COUNT(*) AS count FROM test_pool_rollback").fetchone()["count"] == 0
    finally:
        reused.close()
        close_database_pool()


def test_pg_pool_replaces_a_disconnected_idle_connection(isolated_db, monkeypatch):
    _configure_pool(monkeypatch, 1)
    connection = get_db_connection()
    pid = connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    raw = connection._raw
    connection.close()
    raw.close()

    replacement = get_db_connection()
    try:
        assert replacement.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] != pid
    finally:
        replacement.close()
        close_database_pool()


def test_pg_pool_keeps_overflow_bounded_and_closes_it_on_return(isolated_db, monkeypatch):
    _configure_pool(monkeypatch, 2)
    monkeypatch.setattr(core, "_PG_OVERFLOW_MAX", 1)
    monkeypatch.setattr(core, "_PG_ACQUIRE_TIMEOUT", 0.1)
    connections = []
    try:
        for _ in range(3):
            connections.append(get_db_connection())
        overflow_raw = connections[-1]._raw
        assert core._pg_overflow_active == 1
        with pytest.raises(psycopg2.pool.PoolError, match="exhausted"):
            get_db_connection()
        connections.pop().close()
        assert overflow_raw.closed
        assert core._pg_overflow_active == 0
    finally:
        for connection in connections:
            connection.close()
        close_database_pool()
