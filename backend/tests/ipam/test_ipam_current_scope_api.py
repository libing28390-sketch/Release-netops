from __future__ import annotations

from api import ipam as ipam_api
from database import get_db_connection


def test_current_visible_scopes_use_current_ipam_sources_without_discovery_history(
    isolated_db, monkeypatch,
):
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
               VALUES ('site-current-scope', 'CURRENT', 'Current scope', 'tenant-default')"""
        )
        conn.commit()

    executed_sql: list[str] = []
    original_get_connection = ipam_api.get_db_connection

    class AuditedConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, statement, parameters=()):
            sql = str(statement).lower()
            executed_sql.append(sql)
            assert 'ipam_discovery_observations' not in sql
            assert 'ipam_discovery_snapshots' not in sql
            return self._connection.execute(statement, parameters)

        def close(self):
            self._connection.close()

    monkeypatch.setattr(
        ipam_api, 'get_db_connection',
        lambda: AuditedConnection(original_get_connection()),
    )
    monkeypatch.setattr(ipam_api, 'authorize_resource', lambda *_args, **_kwargs: True)

    scopes = ipam_api._ipam_current_visible_scopes({
        'id': 'current-scope-viewer', 'role': 'Viewer', 'tenant_id': 'tenant-default',
    })

    assert ('tenant-default', 'site-current-scope') in scopes
    assert executed_sql
