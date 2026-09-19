"""Classify persisted vendor-native aggregation interfaces correctly.

Older interface collectors stored logical names such as Route-Aggregation12
and Port-channel1 as ``physical``.  The name is still useful evidence, but it
must be classified as a logical aggregation so topology rebuilds can preserve
L2/L3-specific names once member relationships are collected.
"""

from __future__ import annotations

import re


VERSION = 41
NAME = "normalize_aggregation_interface_types"


_AGGREGATION_NAME = re.compile(
    r"^(?:bridge-aggregation|route-aggregation|eth-trunk|port-channel|portchannel|bagg|ragg|po|be)\d+$",
    re.IGNORECASE,
)


def upgrade(cursor, use_pg: bool) -> None:
    rows = cursor.execute(
        "SELECT id, interface_name, interface_type FROM interfaces"
    ).fetchall()
    for row in rows:
        interface_type = str(row[2] or "").strip().lower()
        name = re.sub(r"[^a-z0-9-]", "", str(row[1] or "").strip().lower())
        if interface_type in {"port_channel", "port-channel", "lag", "aggregation"}:
            continue
        if _AGGREGATION_NAME.fullmatch(name):
            cursor.execute(
                "UPDATE interfaces SET interface_type = 'port_channel' WHERE id = ?",
                (row[0],),
            )
