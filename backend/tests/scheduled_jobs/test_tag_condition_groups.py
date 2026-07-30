import sqlite3

from services.tag_service import (
    resolve_device_ids_by_condition_groups,
    resolve_device_ids_by_expression,
    resolve_device_ids_by_filter,
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE devices (id TEXT PRIMARY KEY);
        CREATE TABLE tag_assignments (
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            tag_id TEXT NOT NULL
        );
        INSERT INTO devices (id) VALUES ('d1'), ('d2'), ('d3'), ('d4');
        INSERT INTO tag_assignments (resource_type, resource_id, tag_id) VALUES
            ('device', 'd1', 'A'),
            ('device', 'd1', 'B'),
            ('device', 'd2', 'A'),
            ('device', 'd2', 'C'),
            ('device', 'd3', 'B'),
            ('device', 'd3', 'C'),
            ('device', 'd4', 'D');
        """
    )
    return conn


def test_condition_groups_require_every_and_group() -> None:
    conn = _connection()
    try:
        result = resolve_device_ids_by_condition_groups(conn, [
            {"operator": "and", "tag_ids": ["A"]},
            {"operator": "and", "tag_ids": ["B"]},
        ])
    finally:
        conn.close()

    assert result == ["d1"]


def test_condition_groups_accept_any_or_group() -> None:
    conn = _connection()
    try:
        result = resolve_device_ids_by_condition_groups(conn, [
            {"operator": "or", "tag_ids": ["A"]},
            {"operator": "or", "tag_ids": ["B"]},
        ])
    finally:
        conn.close()

    assert result == ["d1", "d2", "d3"]


def test_condition_groups_combine_and_or_not() -> None:
    conn = _connection()
    try:
        result = resolve_device_ids_by_condition_groups(conn, [
            {"operator": "and", "tag_ids": ["A"]},
            {"operator": "or", "tag_ids": ["B", "C"]},
            {"operator": "not", "tag_ids": ["C"]},
        ])
    finally:
        conn.close()

    assert result == ["d1"]


def test_legacy_filter_keeps_and_of_or_behavior() -> None:
    conn = _connection()
    try:
        result = resolve_device_ids_by_filter(
            conn,
            include_groups=[["A"], ["B", "C"]],
            exclude_tag_ids=["C"],
        )
    finally:
        conn.close()

    assert result == ["d1"]


def test_nested_expression_supports_and_with_nested_or() -> None:
    conn = _connection()
    try:
        conn.execute(
            "INSERT INTO tag_assignments (resource_type, resource_id, tag_id) VALUES ('device', 'd1', 'C')"
        )
        result = resolve_device_ids_by_expression(conn, {
            "operator": "and",
            "negated": False,
            "tag_ids": ["A", "B"],
            "groups": [
                {
                    "operator": "or",
                    "negated": False,
                    "tag_ids": ["C", "D"],
                    "groups": [],
                }
            ],
        })
    finally:
        conn.close()

    assert result == ["d1"]


def test_nested_expression_can_negate_a_child_group() -> None:
    conn = _connection()
    try:
        result = resolve_device_ids_by_expression(conn, {
            "operator": "and",
            "negated": False,
            "tag_ids": ["A"],
            "groups": [
                {
                    "operator": "or",
                    "negated": True,
                    "tag_ids": ["C", "D"],
                    "groups": [],
                }
            ],
        })
    finally:
        conn.close()

    assert result == ["d1"]
