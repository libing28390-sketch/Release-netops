from __future__ import annotations

import database
from api import config_templates as config_templates_api


class _RecordingConnection:
    """Record list-route SQL while delegating to isolated PostgreSQL."""

    def __init__(self, connection):
        self._connection = connection
        self.statements: list[str] = []

    def execute(self, statement, params=None):
        self.statements.append(" ".join(statement.lower().split()))
        return self._connection.execute(statement, params)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _insert_template(
    connection,
    *,
    template_id: str,
    name: str,
    vendor: str,
    current_version: str = "1.0",
    content: str = "hostname template",
) -> None:
    connection.execute(
        """INSERT INTO templates (
               id, name, type, category, vendor, platform_family, content,
               code, source_type, status, current_version, created_at,
               updated_at, use_count, quality_score
           ) VALUES (?, ?, 'Jinja2', 'batching-test', ?, 'cisco_iosxe', ?,
                     ?, 'custom', 'draft', ?, '2026-10-07T00:00:00+08:00',
                     '2026-10-07T00:00:00+08:00', 0, 0)""",
        (
            template_id,
            name,
            vendor,
            content,
            f"batch-{template_id}",
            current_version,
        ),
    )


def _list_templates(monkeypatch, **overrides):
    connections: list[_RecordingConnection] = []

    def connect():
        recording_connection = _RecordingConnection(database.get_db_connection())
        connections.append(recording_connection)
        return recording_connection

    monkeypatch.setattr(config_templates_api, "get_db_connection", connect)
    arguments = {
        "keyword": "",
        "vendor": "",
        "platform": "",
        "category": "batching-test",
        "source_type": "",
        "status": "",
        "risk_level": "",
        "sort": "name",
        "page": 1,
        "page_size": 50,
        "user": {"username": "alice"},
    }
    arguments.update(overrides)
    result = config_templates_api.list_config_templates(**arguments)
    assert len(connections) == 1
    return result, connections[0].statements


def _assert_batched_query_count(statements: list[str], expected: int = 4) -> None:
    assert len(statements) == expected
    assert sum("from templates where" in statement and "count(*)" in statement for statement in statements) == 1
    assert sum("from templates where" in statement and "limit" in statement for statement in statements) == 1
    assert sum("from config_template_versions" in statement for statement in statements) == 1
    assert sum("from config_template_favorites" in statement for statement in statements) == 1


def test_list_config_templates_batches_versions_and_user_favorites(isolated_db, monkeypatch) -> None:
    connection = database.get_db_connection()
    try:
        for number in range(132):
            template_id = f"batching-{number:03d}"
            _insert_template(
                connection,
                template_id=template_id,
                name=f"Batching template {number:03d}",
                vendor="Cisco" if number == 0 else "Huawei",
                current_version="2.4" if number == 0 else ("3.0" if number == 1 else "1.0"),
                content=(
                    "hostname template"
                    if number == 0
                    else "hostname {{ legacy_name }}" if number == 1 else "hostname template"
                ),
            )

        connection.execute(
            """INSERT INTO config_template_versions
               (id, template_id, version, source, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "batching-version-000",
                "batching-000",
                "2.4",
                "hostname {{ interface_name }}\n description {{ interface_description }}",
                "template-author",
                "2026-10-07T00:00:00+08:00",
            ),
        )
        connection.execute(
            """INSERT INTO config_template_favorites (template_id, username, created_at)
               VALUES (?, ?, ?)""",
            ("batching-000", "alice", "2026-10-07T00:00:00+08:00"),
        )
        connection.execute(
            """INSERT INTO config_template_favorites (template_id, username, created_at)
               VALUES (?, ?, ?)""",
            ("batching-001", "bob", "2026-10-07T00:00:00+08:00"),
        )
        connection.commit()
    finally:
        connection.close()

    empty_result, empty_queries = _list_templates(
        monkeypatch,
        vendor="Juniper",
        user={"username": "alice"},
    )
    assert empty_result["items"] == []
    assert empty_result["total"] == 0
    assert empty_result["total_pages"] == 1
    assert len(empty_queries) == 2

    alice_result, alice_queries = _list_templates(
        monkeypatch,
        vendor="Cisco",
        user={"username": "alice"},
    )
    assert alice_result["total"] == 1
    assert alice_result["items"][0]["current_version"] == "2.4"
    assert alice_result["items"][0]["variable_count"] == 2
    assert alice_result["items"][0]["is_favorite"] is True
    _assert_batched_query_count(alice_queries)

    bob_result, bob_queries = _list_templates(
        monkeypatch,
        vendor="Cisco",
        user={"username": "bob"},
    )
    assert bob_result["total"] == 1
    assert bob_result["items"][0]["is_favorite"] is False
    _assert_batched_query_count(bob_queries)

    bob_fallback_result, bob_fallback_queries = _list_templates(
        monkeypatch,
        vendor="Huawei",
        page_size=1,
        user={"username": "bob"},
    )
    assert bob_fallback_result["total"] == 131
    fallback_item = bob_fallback_result["items"][0]
    assert fallback_item["current_version"] == "3.0"
    assert fallback_item["variable_count"] == 1
    assert fallback_item["is_favorite"] is True
    _assert_batched_query_count(bob_fallback_queries)

    bulk_result, bulk_queries = _list_templates(
        monkeypatch,
        page_size=200,
        user={"username": "alice"},
    )
    assert bulk_result["total"] == 132
    assert len(bulk_result["items"]) == 132
    _assert_batched_query_count(bulk_queries)

    page_result, page_queries = _list_templates(
        monkeypatch,
        page=2,
        page_size=10,
        user={"username": "alice"},
    )
    assert page_result["total"] == 132
    assert page_result["page"] == 2
    assert [item["name"] for item in page_result["items"]] == [
        f"Batching template {number:03d}" for number in range(10, 20)
    ]
    _assert_batched_query_count(page_queries)
