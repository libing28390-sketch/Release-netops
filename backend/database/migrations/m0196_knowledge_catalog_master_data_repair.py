"""Repair catalog master-data tables after an older 193 was recorded."""

from __future__ import annotations

from . import m0193_knowledge_catalog_master_data as _catalog


VERSION = 196
NAME = "knowledge_catalog_master_data_repair"


def upgrade(cursor, use_pg: bool) -> None:
    """Ensure catalog tables exist without changing existing catalog rows."""
    _catalog.upgrade(cursor, use_pg)


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
