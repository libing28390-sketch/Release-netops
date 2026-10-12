"""Refresh registry copies of the H3C grammars changed in m0175."""

from __future__ import annotations

from database.migrations.m0171_h3c_operational_action_bindings import _now
from database.migrations.m0175_reconcile_registry_field_contracts import (
    _refresh_system_template_contents,
)


VERSION = 176
NAME = "sync_h3c_template_content"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    try:
        cursor.execute("SELECT 1 FROM parser_templates LIMIT 1")
        cursor.execute("SELECT 1 FROM parser_template_versions LIMIT 1")
    except Exception:
        return
    _refresh_system_template_contents(cursor, _now())


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
