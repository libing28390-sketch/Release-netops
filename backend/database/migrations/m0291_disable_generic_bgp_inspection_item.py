"""Disable the generic BGP placeholder until a platform contract is known."""

from __future__ import annotations


VERSION = 291
NAME = "disable_generic_bgp_inspection_item"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute(
        "UPDATE inspection_items SET "
        "name = 'BGP Neighbor Count (disabled)', "
        "name_zh = 'BGP 邻居数（默认停用）', "
        "description = '通用 BGP 邻居计数占位，默认停用；平台专用 BGP 指标负责默认巡检，需确认适用平台与邻居数据源后再启用', "
        "method = 'SNMP', script_id = '', parse_type = 'count', "
        "warning_threshold = 1, critical_threshold = NULL, expected_value = '', "
        "unit = '个邻居', threshold_direction = 'above', enabled = 0 "
        "WHERE id = 'net_bgp'"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep the unsupported generic check disabled after rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
