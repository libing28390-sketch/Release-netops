from __future__ import annotations

import pytest

from backend.database.schema import _require_supported_postgres_version


class VersionCursor:
    def __init__(self, version_num: int):
        self.version_num = version_num
        self.executed: list[str] = []

    def execute(self, query: str) -> None:
        self.executed.append(query)

    def fetchone(self) -> tuple[int]:
        return (self.version_num,)


def test_postgresql_18_is_the_only_supported_runtime_major():
    cursor = VersionCursor(180006)

    _require_supported_postgres_version(cursor)

    assert cursor.executed == ["SHOW server_version_num"]


@pytest.mark.parametrize("version_num", [170011, 190000])
def test_other_postgresql_majors_fail_before_schema_initialization(version_num: int):
    cursor = VersionCursor(version_num)

    with pytest.raises(RuntimeError, match=r"requires PostgreSQL 18"):
        _require_supported_postgres_version(cursor)


def test_invalid_postgresql_version_result_fails_closed():
    class InvalidCursor(VersionCursor):
        def fetchone(self):
            return ("unknown",)

    with pytest.raises(RuntimeError, match="Unable to determine"):
        _require_supported_postgres_version(InvalidCursor(0))
