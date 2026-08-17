from __future__ import annotations

from dataclasses import dataclass

from ai.api import usage
from ai.services import database_observability


@dataclass
class _Cursor:
    rows: list[tuple]

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, *, fail_slow: bool = False):
        self.sql: list[str] = []
        self.fail_slow = fail_slow

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split()).lower()
        self.sql.append(normalized)
        if "pg_class c" in normalized:
            return _Cursor([("ai_document", 100, 5, 4096, 1024, 100.0)])
        if "pg_statio_user_tables" in normalized:
            return _Cursor([(1000, 25)])
        if "pg_stat_statements" in normalized:
            if self.fail_slow:
                raise RuntimeError("permission denied; query text must not escape")
            return _Cursor([
                (123, 10, 6000.0, 600.0, 20, 100, 5),
                (456, 4, 100.0, 25.0, 8, 30, 2),
            ])
        if "pg_database_size" in normalized:
            return _Cursor([(4096,)])
        raise AssertionError(f"unexpected SQL: {sql}")


def test_obs008_postgresql_snapshot_is_read_only_bounded_and_redacted(monkeypatch):
    monkeypatch.setattr(database_observability.database_core, "_USE_PG", True)
    connection = _FakeConnection()

    result = database_observability.snapshot(connection)

    assert result["backend"] == "postgresql"
    assert result["status"] == "PASS"
    assert result["read_only"] is True
    assert result["cache"]["hit_rate"] == 0.97561
    assert result["slow_queries"]["slow_query_count"] == 1
    assert result["slow_queries"]["query_text_included"] is False
    assert result["capacity"]["synthetic_rows_inserted"] is False
    assert result["redaction"]["query_text"] is False
    assert all(sql.startswith("select") for sql in connection.sql)


def test_obs008_permission_failure_is_degraded_without_error_text(monkeypatch):
    monkeypatch.setattr(database_observability.database_core, "_USE_PG", True)
    connection = _FakeConnection(fail_slow=True)

    result = database_observability.snapshot(connection)

    assert result["status"] == "DEGRADED"
    assert result["slow_queries"]["status"] == "UNAVAILABLE"
    assert "permission denied" not in str(result)
    assert all(sql.startswith("select") for sql in connection.sql)


def test_obs008_sqlite_is_explicitly_not_applicable(monkeypatch):
    monkeypatch.setattr(database_observability.database_core, "_USE_PG", False)

    result = database_observability.snapshot()

    assert result == {
        "backend": "sqlite",
        "status": "NOT_APPLICABLE",
        "production_authority": "postgresql",
        "reason": "SQLite is compatibility-only for OBS-008 production monitoring",
    }


def test_obs008_metrics_endpoint_exposes_database_snapshot(monkeypatch):
    monkeypatch.setattr(usage.ai_metrics, "snapshot", lambda: {"jobs": {}})
    monkeypatch.setattr(usage, "job_observability_snapshot", lambda: {"status": "PASS"})
    monkeypatch.setattr(usage, "database_observability_snapshot", lambda: {"backend": "postgresql", "status": "PASS"})

    result = usage.get_ai_metrics(user={})

    assert result["database"] == {"backend": "postgresql", "status": "PASS"}
