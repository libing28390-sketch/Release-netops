"""Add the PostgreSQL uniqueness boundary for daily AI usage counters."""

from __future__ import annotations

VERSION = 141
NAME = "ai_usage_daily_scope"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_usage_daily_scope ON ai_usage_daily(date, provider_id, model_id, scene)")


def downgrade(cursor, use_pg: bool) -> None:
    return None
