"""Bind the newly imported V7 link-aggregation grammar to its action."""

from __future__ import annotations

from database.migrations.m0171_h3c_operational_action_bindings import (
    _ensure_action_definitions,
    _ensure_release_actions,
    _register_new_templates,
    _now,
)


VERSION = 173
NAME = "bind_h3c_v7_link_aggregation_template"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    try:
        cursor.execute("SELECT 1 FROM platform_profiles LIMIT 1")
        cursor.execute("SELECT 1 FROM platform_releases LIMIT 1")
    except Exception:
        return
    now = _now()
    _ensure_action_definitions(cursor, now)
    _register_new_templates(cursor, now)
    _ensure_release_actions(cursor, now)


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
