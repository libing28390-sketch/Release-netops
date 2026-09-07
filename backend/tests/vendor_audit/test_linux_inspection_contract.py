from __future__ import annotations

from services import inspection_service
from database.seed import get_default_items, std_scripts


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FacetConnection:
    def __init__(self):
        self.queries: list[str] = []

    def execute(self, sql, _params=()):
        self.queries.append(" ".join(str(sql).split()))
        normalized = self.queries[-1].lower()
        if "select count(*) as total from inspection_items" in normalized:
            return _Result([{"total": 3}])
        if "select coalesce(category" in normalized:
            return _Result([
                {"facet_value": "Network", "total": 7},
                {"facet_value": "Server", "total": 3},
            ])
        if "select coalesce(method" in normalized:
            return _Result([
                {"facet_value": "Shell", "total": 3},
                {"facet_value": "SNMP", "total": 1},
            ])
        if "order by category asc, name asc limit" in normalized:
            return _Result([{"id": "server-1", "category": "Server", "method": "Shell"}])
        raise AssertionError(f"unexpected inspection-items query: {sql}")

    def close(self):
        return None


def test_paginated_inspection_items_return_full_catalog_facets(monkeypatch) -> None:
    connection = _FacetConnection()
    monkeypatch.setattr(inspection_service, "get_db_connection", lambda: connection)

    result = inspection_service.list_inspection_items(
        category="Server",
        method="Shell",
        page=1,
        page_size=20,
    )

    assert result["total"] == 3
    assert result["items"] == [{"id": "server-1", "category": "Server", "method": "Shell"}]
    assert result["facets"] == {
        "all": 10,
        "categories": {"Network": 7, "Server": 3},
        "methods": {"SHELL": 3, "SNMP": 1},
    }

    category_query = next(query for query in connection.queries if "select coalesce(category" in query.lower())
    method_query = next(query for query in connection.queries if "select coalesce(method" in query.lower())
    assert "lower(coalesce(category" not in category_query.lower()
    assert "lower(coalesce(method" in category_query.lower()
    assert "lower(coalesce(category" in method_query.lower()
    assert "lower(coalesce(method" not in method_query.lower()


def test_linux_builtin_items_bind_one_script_per_metric() -> None:
    items = {
        item[0]: item
        for item in get_default_items("2026-09-07T20:00:00+08:00")
        if item[3] == "Server"
    }
    script_ids = [item[8] for item in items.values()]

    assert len(script_ids) == len(set(script_ids))
    assert "std_linux_integrated" not in script_ids
    assert items["srv_tcp_retrans_pct"][7:9] == (
        "std_linux_tcp_retrans_pct",
        "std_linux_tcp_retrans_pct",
    )

    scripts = {item[0]: item[2] for item in std_scripts}
    assert set(script_ids).issubset(scripts)


def test_linux_tcp_retransmission_output_is_compatible_and_windowed() -> None:
    scripts = {item[0]: item[2] for item in std_scripts}
    standalone = scripts["std_linux_tcp_retrans_pct"]
    comprehensive = scripts["insp_linux_full"]

    for content in (standalone, comprehensive):
        assert "OutSegs" in content
        assert "RetransSegs" in content
        assert "sleep 1" in content
        assert "tcp_retrans_pct" in content

    assert 'echo "tcp_retrans_pct: ${tcp_retrans_pct:-0}"' in comprehensive
    assert 'echo "tcp_retrans: ${tcp_retrans_pct:-0}"' in comprehensive
