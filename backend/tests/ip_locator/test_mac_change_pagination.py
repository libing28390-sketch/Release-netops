from __future__ import annotations

import asyncio
import inspect

from api import ip_locator
from services import ip_locator_service


def _entry(index: int) -> dict:
    return {
        "id": index + 1,
        "ip": f"192.0.2.{index % 250}",
        "old_mac": "0011.2233.4455",
        "new_mac": "0011.2233.4466",
        "old_vendor": "Old vendor",
        "new_vendor": "New vendor",
        "old_device": "old-switch",
        "new_device": "new-switch",
        "detected_at": "2026-09-28T00:00:00+00:00",
    }


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return {"total": len(self.rows)}

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.closed = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "COUNT(*)" in sql:
            return _Cursor(self.rows)
        limit, offset = params
        return _Cursor(self.rows[offset : offset + limit])

    def close(self):
        self.closed = True


def test_mac_change_service_pages_through_all_rows_and_returns_full_total(monkeypatch):
    rows = [_entry(index) for index in range(2_105)]
    connection = _Connection(rows)
    monkeypatch.setattr(ip_locator_service, "get_db_connection", lambda: connection)

    first_page = ip_locator_service.get_mac_changes(limit=1_000, offset=0)
    second_page = ip_locator_service.get_mac_changes(limit=1_000, offset=1_000)
    final_page = ip_locator_service.get_mac_changes(limit=1_000, offset=2_000)

    assert [first_page["total"], second_page["total"], final_page["total"]] == [2_105] * 3
    assert [len(first_page["entries"]), len(second_page["entries"]), len(final_page["entries"])] == [1_000, 1_000, 105]
    select_calls = [(sql, params) for sql, params in connection.calls if "COUNT(*)" not in sql]
    assert [params for _, params in select_calls] == [(1_000, 0), (1_000, 1_000), (1_000, 2_000)]
    assert all("ORDER BY detected_at DESC, id DESC LIMIT ? OFFSET ?" in sql for sql, _ in select_calls)
    assert connection.closed is True


def test_mac_change_service_fails_closed_when_database_is_unavailable(monkeypatch):
    def unavailable_connection():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(ip_locator_service, "get_db_connection", unavailable_connection)

    result = ip_locator_service.get_mac_changes(limit=1_000, offset=0)

    assert result["total"] == 0
    assert result["entries"] == []


def test_mac_change_endpoint_forwards_page_parameters(monkeypatch):
    calls = []

    async def get_page(limit, offset):
        calls.append((limit, offset))
        return {"total": 2_105, "entries": []}

    monkeypatch.setattr(ip_locator, "get_mac_changes_async", get_page)
    response = asyncio.run(ip_locator.api_get_mac_changes(limit=73, offset=146, user={"role": "Viewer"}))

    assert response["total"] == 2_105
    assert calls == [(73, 146)]


def test_mac_change_endpoint_declares_bounded_page_query_parameters():
    signature = inspect.signature(ip_locator.api_get_mac_changes)
    limit = signature.parameters["limit"].default
    offset = signature.parameters["offset"].default
    limit_constraints = {type(item).__name__: item for item in limit.metadata}
    offset_constraints = {type(item).__name__: item for item in offset.metadata}

    assert limit.default == 200
    assert limit_constraints["Ge"].ge == 1
    assert limit_constraints["Le"].le == 1_000
    assert offset.default == 0
    assert offset_constraints["Ge"].ge == 0
