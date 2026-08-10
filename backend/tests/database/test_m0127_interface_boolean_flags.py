from database.migrations import m0127_interface_boolean_flags as migration


class _Cursor:
    def __init__(self, types: dict[str, str]):
        self.types = types
        self.statements: list[tuple[str, tuple | None]] = []
        self.row = None

    def execute(self, sql: str, params=None):
        self.statements.append((sql, params))
        if "information_schema.columns" in sql:
            column = params[0]
            data_type = self.types.get(column)
            self.row = (data_type,) if data_type else None
        return self

    def fetchone(self):
        return self.row


def test_m0127_skips_sqlite_without_schema_changes():
    cursor = _Cursor({"is_l3": "integer", "ip_enabled": "integer"})

    migration.upgrade(cursor, False)

    assert cursor.statements == []


def test_m0127_converts_only_the_l3_flag_to_postgres_boolean():
    cursor = _Cursor({"is_l3": "integer", "ip_enabled": "boolean"})

    migration.upgrade(cursor, True)

    statements = [sql for sql, _ in cursor.statements]
    assert any("ALTER COLUMN is_l3 TYPE BOOLEAN" in sql for sql in statements)
    assert not any("ALTER COLUMN ip_enabled" in sql for sql in statements)
    assert any("LOWER(TRIM(is_l3::text))" in sql for sql in statements)
