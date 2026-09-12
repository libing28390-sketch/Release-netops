"""Persist the cross-vendor SSH algorithm profile on assets and devices."""

from __future__ import annotations


VERSION = 215
NAME = "ssh_algorithm_profiles"

_PROFILE_CASE = """
    CASE LOWER(BTRIM(COALESCE(ssh_algorithm_profile, '')))
        WHEN 'modern' THEN 'modern'
        WHEN 'strict' THEN 'modern'
        WHEN 'legacy' THEN 'legacy_compat'
        WHEN 'compat' THEN 'legacy_compat'
        WHEN 'legacy_compat' THEN 'legacy_compat'
        WHEN 'legacy-compat' THEN 'legacy_compat'
        WHEN 'break_glass' THEN 'legacy_break_glass'
        WHEN 'break-glass' THEN 'legacy_break_glass'
        WHEN 'legacy_all' THEN 'legacy_break_glass'
        WHEN 'legacy-all' THEN 'legacy_break_glass'
        WHEN 'legacy_break_glass' THEN 'legacy_break_glass'
        WHEN 'legacy-break-glass' THEN 'legacy_break_glass'
        ELSE 'auto'
    END
"""

_PROFILE_CHECK = (
    "ssh_algorithm_profile IN "
    "('auto', 'modern', 'legacy_compat', 'legacy_break_glass')"
)


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("SSH algorithm profile migration requires PostgreSQL")

    for table in ("physical_assets", "devices"):
        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
            "ssh_algorithm_profile TEXT NOT NULL DEFAULT 'auto'"
        )
        # Normalize any pre-existing/manual values before enforcing the CHECK
        # constraint.  Unknown values fail closed to the safe auto profile.
        cursor.execute(
            f"UPDATE {table} SET ssh_algorithm_profile = {_PROFILE_CASE}"
        )
        cursor.execute(
            f"ALTER TABLE {table} ALTER COLUMN ssh_algorithm_profile "
            "SET DEFAULT 'auto'"
        )
        cursor.execute(
            f"ALTER TABLE {table} ALTER COLUMN ssh_algorithm_profile SET NOT NULL"
        )
        constraint = f"ck_{table}_ssh_algorithm_profile"
        cursor.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        cursor.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"CHECK ({_PROFILE_CHECK})"
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep the additive column during rollback so an older application cannot
    # silently discard a device's explicit compatibility choice.
    return None
