"""Remove Nexora-authored SNMP OID profiles from active device configuration."""

from __future__ import annotations


VERSION = 279
NAME = "retire_custom_snmp_metric_profiles"


def upgrade(cursor, use_pg: bool) -> None:
    """Clear saved local OID definitions and device bindings.

    The schema remains for compatibility with historical deployments and
    reports, but no custom metric profile may remain configured or collect.
    """
    if not use_pg:
        raise RuntimeError("retire_custom_snmp_metric_profiles requires PostgreSQL")

    cursor.execute(
        "UPDATE devices SET snmp_metric_profile_id = '' "
        "WHERE COALESCE(BTRIM(snmp_metric_profile_id), '') <> ''"
    )
    cursor.execute("DELETE FROM snmp_metric_profiles")


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("retire_custom_snmp_metric_profiles requires PostgreSQL")
    raise RuntimeError(
        "retired custom SNMP metric profile data was deleted and cannot be restored"
    )


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
