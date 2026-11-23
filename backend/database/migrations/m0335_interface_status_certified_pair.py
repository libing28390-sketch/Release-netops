"""Keep certified admin/oper values separate from mutable interface projection fields.

Legacy collectors and inventory services still write ``admin_status`` and
``oper_status`` without state provenance. The IPAM liveness reader uses this
pair only when a complete authoritative observation writes it together with
``status_observed_at`` and ``status_observation_source``.
"""

from __future__ import annotations

VERSION = 335
NAME = "interface_status_certified_pair"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute("ALTER TABLE interfaces ADD COLUMN IF NOT EXISTS certified_admin_status TEXT")
    cursor.execute("ALTER TABLE interfaces ADD COLUMN IF NOT EXISTS certified_oper_status TEXT")


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute("ALTER TABLE interfaces DROP COLUMN IF EXISTS certified_oper_status")
    cursor.execute("ALTER TABLE interfaces DROP COLUMN IF EXISTS certified_admin_status")
