"""Track live verification state for model-scoped SNMP metric profiles."""

from __future__ import annotations


VERSION = 124
NAME = "metric_profile_verification"


_COLUMNS = {
    "verification_status": "TEXT NOT NULL DEFAULT 'unverified'",
    "last_test_at": "TEXT",
    "last_test_device_id": "TEXT NOT NULL DEFAULT ''",
    "last_test_message": "TEXT NOT NULL DEFAULT ''",
}


def _columns(cursor, use_pg: bool) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        ("snmp_metric_profiles",),
    )
    return {str(row[0]) for row in cursor.fetchall()}



def upgrade(cursor, use_pg: bool) -> None:
    existing = _columns(cursor, use_pg)
    for name, definition in _COLUMNS.items():
        if name in existing:
            continue
        cursor.execute(
            f"ALTER TABLE snmp_metric_profiles ADD COLUMN IF NOT EXISTS {name} {definition}"
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Preserve verification evidence on rollback; it is harmless to older
    # readers and avoids silently losing the operator's validation history.
    return None
