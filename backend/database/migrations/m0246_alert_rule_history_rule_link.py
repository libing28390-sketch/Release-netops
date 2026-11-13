"""Link alert rule history entries to the actual alert rule record."""

from __future__ import annotations


VERSION = 246
NAME = "alert_rule_history_rule_link"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute(
        "ALTER TABLE alert_rule_history ADD COLUMN IF NOT EXISTS rule_id TEXT"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_rule_history_rule_id "
        "ON alert_rule_history(rule_id, created_at DESC)"
    )
    cursor.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'alert_rule_history_rule_id_fkey'
            ) THEN
                ALTER TABLE alert_rule_history
                ADD CONSTRAINT alert_rule_history_rule_id_fkey
                FOREIGN KEY (rule_id) REFERENCES alert_rules(id) ON DELETE CASCADE;
            END IF;
        END $$
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Preserve history rows during rollback; the additive link can remain.
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
