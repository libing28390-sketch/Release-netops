"""Backfill BGP route actions added after the first parameterized seed."""

from __future__ import annotations

from database.migrations.m0080_parameterized_registry_actions import upgrade as _upgrade


VERSION = 82
NAME = "extend_bgp_registry_actions"


def upgrade(cursor, use_pg: bool) -> None:
    _upgrade(cursor, use_pg)
