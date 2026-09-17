"""Refresh H3C status metrics with their enumerated SNMP types."""

from __future__ import annotations

from database.migrations.m0236_expand_h3c_monitoring_oids import upgrade as _refresh_catalog


VERSION = 238
NAME = "sync_h3c_metric_types"


def upgrade(cursor, use_pg: bool) -> None:
    _refresh_catalog(cursor, use_pg)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    return None
