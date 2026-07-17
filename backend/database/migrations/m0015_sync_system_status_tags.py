"""Backfill the two fixed availability tags for existing devices."""

from datetime import datetime, timezone

VERSION = 15
NAME = 'sync_system_status_tags'


def upgrade(cursor, use_pg: bool) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for value, label, label_zh, color, sort_order in (
        ('online', 'Online', '在线', '#10b981', 1),
        ('offline', 'Offline', '离线', '#ef4444', 2),
    ):
        cursor.execute(
            '''INSERT INTO tag_definitions
                 (id, category, value, label, label_zh, color, icon, description, sort_order, built_in, created_at)
               VALUES (?, 'status', ?, ?, ?, ?, '', 'System-managed availability tag', ?, 1, ?)
               ON CONFLICT (category, value) DO NOTHING''',
            (f'builtin-status-{value}', value, label, label_zh, color, sort_order, now),
        )

    status_rows = cursor.execute(
        "SELECT id, value FROM tag_definitions WHERE category = 'status' AND value IN ('online', 'offline')"
    ).fetchall()
    status_ids = {str(row[1]): str(row[0]) for row in status_rows}
    if set(status_ids) != {'online', 'offline'}:
        raise RuntimeError('Canonical availability tag definitions are unavailable')

    cursor.execute(
        "DELETE FROM device_tags WHERE tag_id IN (SELECT id FROM tag_definitions WHERE category = 'status')"
    )
    device_rows = cursor.execute('SELECT id, status FROM devices').fetchall()
    for device_id, status in device_rows:
        value = 'online' if str(status or '').lower() == 'online' else 'offline'
        cursor.execute(
            '''INSERT INTO device_tags (device_id, tag_id, created_at, created_by)
               VALUES (?, ?, ?, 'system') ON CONFLICT DO NOTHING''',
            (device_id, status_ids[value], now),
        )
