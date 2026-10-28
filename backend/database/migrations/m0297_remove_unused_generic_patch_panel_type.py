"""Remove the unreferenced generic patch-panel device type placeholder."""

from __future__ import annotations


VERSION = 297
NAME = "remove_unused_generic_patch_panel_type"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Generic device-type cleanup requires PostgreSQL")

    cursor.execute(
        """DELETE FROM device_types
             WHERE LOWER(TRIM(COALESCE(vendor, ''))) = 'generic'
               AND LOWER(TRIM(COALESCE(model, ''))) = 'patch panel 24p'
               AND NOT EXISTS (
                   SELECT 1 FROM rack_devices rd WHERE rd.device_type_id = device_types.id
               )
               AND NOT EXISTS (
                   SELECT 1 FROM devices d WHERE d.device_type_id = device_types.id
               )"""
    )
