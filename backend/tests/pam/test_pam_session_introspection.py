from api import pam as pam_api


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _PostgresLikeConnection:
    """Small fake that models PostgreSQL's failed-transaction behavior."""

    def __init__(self):
        self.failed = False
        self.rollback_calls = 0
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if sql.startswith("PRAGMA"):
            self.failed = True
            raise RuntimeError("syntax error at or near PRAGMA")
        if self.failed:
            raise RuntimeError("current transaction is aborted")
        return _Rows([
            {"column_name": "id"},
            {"column_name": "session_kind"},
            {"column_name": "tenant_id"},
        ])

    def rollback(self):
        self.rollback_calls += 1
        self.failed = False


def test_pam_session_columns_rolls_back_before_postgres_fallback():
    conn = _PostgresLikeConnection()

    columns = pam_api._pam_session_columns(conn)

    assert columns == {"id", "session_kind", "tenant_id"}
    assert conn.rollback_calls == 1
    assert any("information_schema.columns" in statement for statement in conn.statements)
