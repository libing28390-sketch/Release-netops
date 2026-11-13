"""Retry the H3C operational template import for already-upgraded databases.

Version 171 initially used the packaged ntc_templates directory, while this
application's registry source is ``data/textfsm_templates``.  Keep the repair
as a separate migration so installations that already recorded 171 still get
the two exact V7 templates and their release bindings.
"""

from __future__ import annotations

from database.migrations.m0171_h3c_operational_action_bindings import (
    _ensure_action_definitions,
    _ensure_release_actions,
    _register_new_templates,
    _now,
)


VERSION = 172
NAME = "repair_h3c_operational_template_import"


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
