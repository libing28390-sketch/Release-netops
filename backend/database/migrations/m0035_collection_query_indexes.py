"""Add indexes for the high-frequency inventory and topology read paths."""

from __future__ import annotations


VERSION = 35
NAME = "collection_query_indexes"


def upgrade(cursor, use_pg: bool) -> None:
    # Device inventory joins rack_devices by asset_id and rack administration
    # checks usage by device_type_id.  The baseline only indexed rack_id.
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_rack_devices_asset_id ON rack_devices(asset_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_rack_devices_device_type_id ON rack_devices(device_type_id)"
    )

    # Topology's default view excludes stale links and unmanaged observations.
    # These indexes keep those predicates bounded as historical evidence grows.
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_topology_links_status_last_seen "
        "ON topology_links(status, last_seen)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_topology_obs_target_source "
        "ON topology_observations(target_device_id, source_device_id)"
    )
