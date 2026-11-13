"""Re-run interface alias consolidation after adding short Loop aliases."""

from __future__ import annotations

from .m0036_consolidate_interface_aliases import upgrade as consolidate_aliases


VERSION = 37
NAME = "consolidate_short_loop_aliases"


def upgrade(cursor, use_pg: bool) -> None:
    consolidate_aliases(cursor, use_pg)

