from __future__ import annotations

from pathlib import Path

import pytest

from database.postgres_extensions import (
    ExtensionInstallError,
    MissingPostgreSQLExtension,
    ensure_required_extensions,
    inspect_extensions,
)


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend" / "database" / "migrations" / "m0104_ai_pgvector_rag.py"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _FakeCursor:
    def __init__(self, *, installed=(), available=(), fail_create=()):
        self.installed = {name: version for name, version in installed}
        self.available = {name: version for name, version in available}
        self.fail_create = set(fail_create)
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params or ())))
        if "FROM pg_extension" in sql:
            return _Rows([(name, version) for name, version in self.installed.items()])
        if "FROM pg_available_extensions" in sql:
            return _Rows([(name, version) for name, version in self.available.items()])
        if sql.startswith("CREATE EXTENSION"):
            name = sql.split("IF NOT EXISTS", 1)[1].strip().lower()
            if name in self.fail_create:
                raise RuntimeError("permission denied for database; dsn=password=secret")
            self.installed[name] = self.available[name]
            return _Rows([])
        raise AssertionError(f"unexpected SQL: {sql}")


def test_sqlite_is_explicitly_not_applicable():
    state = inspect_extensions(None, use_pg=False)
    assert state.not_applicable is True
    assert state.ok is True
    assert state.installed == {}
    assert state.missing == ()


def test_installed_required_extensions_pass_without_create():
    cursor = _FakeCursor(installed=(("vector", "0.8.0"), ("pg_trgm", "1.6")))
    state = ensure_required_extensions(cursor, use_pg=True)
    assert state.ok is True
    assert state.missing == ()
    assert not any(sql.startswith("CREATE EXTENSION") for sql, _ in cursor.calls)


def test_unavailable_extension_is_actionable_and_does_not_leak_secret():
    cursor = _FakeCursor(available=(("pg_trgm", "1.6"),))
    with pytest.raises(MissingPostgreSQLExtension) as caught:
        ensure_required_extensions(cursor, use_pg=True)
    error = caught.value
    assert error.code == "POSTGRES_EXTENSION_MISSING"
    assert error.extension == "vector"
    assert "pgvector" in str(error)
    assert "password" not in str(error).lower()
    assert "secret" not in str(error).lower()


def test_available_extension_is_created_and_rechecked():
    cursor = _FakeCursor(available=(("vector", "0.8.0"), ("pg_trgm", "1.6")))
    state = ensure_required_extensions(cursor, use_pg=True)
    assert state.ok is True
    assert set(state.installed) == {"vector", "pg_trgm"}
    create_calls = [sql for sql, _ in cursor.calls if sql.startswith("CREATE EXTENSION")]
    assert create_calls == ["CREATE EXTENSION IF NOT EXISTS vector", "CREATE EXTENSION IF NOT EXISTS pg_trgm"]


def test_install_failure_is_stable_and_secret_free():
    cursor = _FakeCursor(
        available=(("vector", "0.8.0"), ("pg_trgm", "1.6")),
        fail_create=("vector",),
    )
    with pytest.raises(ExtensionInstallError) as caught:
        ensure_required_extensions(cursor, use_pg=True)
    assert caught.value.code == "POSTGRES_EXTENSION_INSTALL_FAILED"
    assert caught.value.extension == "vector"
    assert "password" not in str(caught.value).lower()
    assert "secret" not in str(caught.value).lower()


def test_extension_names_are_allowlisted_and_migration_no_longer_swallows_errors():
    cursor = _FakeCursor(available=(("vector", "0.8.0"),))
    with pytest.raises(ValueError):
        inspect_extensions(cursor, use_pg=True, names=("vector; DROP DATABASE",))
    source = MIGRATION.read_text(encoding="utf-8")
    assert "ensure_required_extensions" in source
    assert "except Exception:\n            pass" not in source
