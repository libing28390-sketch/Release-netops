"""Sync H3C runtime defaults after the expanded OID catalog update."""

from __future__ import annotations

from database.migrations.m0236_expand_h3c_monitoring_oids import upgrade as _refresh_catalog


VERSION = 237
NAME = "sync_h3c_oid_runtime_defaults"


def upgrade(cursor, use_pg: bool) -> None:
    _refresh_catalog(cursor, use_pg)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    return None
