"""Finish the concise action labels used by the quick-query cards."""

from __future__ import annotations


VERSION = 179
NAME = "finish_platform_action_labels"


ACTION_LABELS = {
    "get_interfaces": ("接口详情", "Interface Details"),
    "get_ip_interfaces": ("三层接口", "Layer 3 Interfaces"),
    "get_isis_neighbors": ("ISIS邻居", "ISIS Neighbors"),
    "get_stp": ("STP状态", "STP Status"),
    "get_clock": ("系统时钟", "System Clock"),
    "get_running_config": ("运行配置", "Running Configuration"),
    "get_startup_config": ("启动配置", "Startup Configuration"),
}


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    try:
        cursor.execute("SELECT 1 FROM action_definitions LIMIT 1")
    except Exception:
        return
    for action_code, (name_zh, name_en) in ACTION_LABELS.items():
        cursor.execute(
            "UPDATE action_definitions SET name_zh = ?, name_en = ? WHERE action_code = ?",
            (name_zh, name_en, action_code),
        )


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
