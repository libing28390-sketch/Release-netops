"""Ensure system availability tags exist for the unified tag schema."""

from datetime import datetime, timezone

VERSION = 15
NAME = 'sync_system_status_tags'


def upgrade(cursor, use_pg: bool) -> None:
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "UPDATE tag_definitions SET category='system_auto', source_type='system', is_system=1 "
        "WHERE code IN ('system.status.online', 'system.status.offline')"
    )
