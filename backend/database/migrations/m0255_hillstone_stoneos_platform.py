"""Seed the Hillstone StoneOS system platform profile for existing installs."""

from __future__ import annotations


VERSION = 255
NAME = "hillstone_stoneos_platform"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    del use_pg

    from database.migrations.m0101_split_platform_profiles import _ensure_system_profiles, _now

    profile_ids = _ensure_system_profiles(cursor, _now())
    if not profile_ids.get("hillstone_stoneos"):
        raise RuntimeError("Hillstone StoneOS system profile was not materialized")


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Devices can reference this system profile; keep it available after rollback.
    return None
