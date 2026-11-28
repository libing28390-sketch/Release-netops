"""Compatibility marker for the superseded generic RGOS V10 sample seed.

The original local implementation registered RSR-only outputs under the
generic V10 Profile. Keep this version recorded, but do not repeat that seed;
the RSR samples now use the isolated ``ruijie_rgos_rsr_v10`` parser namespace.
Migration 344 archives the exact rows created by the original implementation.
"""

VERSION = 342
NAME = "ruijie_rgos_v10_official_samples"


def upgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
