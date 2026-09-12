"""
Migration 0001 — baseline marker.

The legacy monolithic bootstrap (schema._init_db_logic) is the schema baseline:
it creates every table idempotently and seeds defaults. This migration records
that the baseline has been established so the versioned migration history starts
from a known point. It performs no DDL of its own.
"""

VERSION = 1
NAME = "baseline"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Intentionally a no-op: the baseline schema is produced by the bootstrap.
    return None
