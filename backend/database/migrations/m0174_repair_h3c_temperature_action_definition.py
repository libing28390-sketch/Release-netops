"""Repair the H3C temperature action field contract metadata."""

from __future__ import annotations

from database.migrations.m0171_h3c_operational_action_bindings import (
    _ensure_action_definitions,
    _ensure_release_actions,
    _now,
)


VERSION = 174
NAME = "repair_h3c_temperature_action_definition"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    try:
        cursor.execute("SELECT 1 FROM platform_profiles LIMIT 1")
        cursor.execute("SELECT 1 FROM platform_releases LIMIT 1")
    except Exception:
        return

    now = _now()
    # m0171 now includes get_temperature in its idempotent definition repair.
    # Reusing the helper keeps fresh installs and upgrades on the same contract.
    _ensure_action_definitions(cursor, now)
    _ensure_release_actions(cursor, now)


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
