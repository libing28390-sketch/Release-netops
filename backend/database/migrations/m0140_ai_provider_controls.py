"""Supplemental controls for LLM provider rotation, defaults and budgets."""

from __future__ import annotations

VERSION = 140
NAME = "ai_provider_controls"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_provider_key_audit (
            id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            key_version INTEGER,
            action TEXT NOT NULL,
            actor_id TEXT,
            reason_code TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (provider_id) REFERENCES ai_provider(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_provider_key_audit_provider ON ai_provider_key_audit(provider_id, created_at)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_user_model_preference (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id_opaque TEXT NOT NULL,
            model_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, user_id_opaque),
            FOREIGN KEY (model_id) REFERENCES ai_model(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_user_model_preference_model ON ai_user_model_preference(model_id, tenant_id)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_usage_daily_scope ON ai_usage_daily(date, provider_id, model_id, scene)")


def downgrade(cursor, use_pg: bool) -> None:
    return None
