"""Allow current IPv6 neighbor rows in the replaceable IPAM neighbor store."""

from __future__ import annotations


VERSION = 317
NAME = "ipam_current_ndp_observations"


def _replace_source_check(cursor, table_name: str, old_names: tuple[str, ...], name: str, values: tuple[str, ...]) -> None:
    for old_name in old_names:
        cursor.execute(f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS {old_name}")
    allowed = ", ".join(f"'{value}'" for value in values)
    cursor.execute(
        f"ALTER TABLE {table_name} ADD CONSTRAINT {name} CHECK (observation_source IN ({allowed}))"
    )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM current ND observations require PostgreSQL")
    for table_name in ("ipam_endpoint_collection_states", "ipam_current_endpoint_observations"):
        cursor.execute("SELECT to_regclass(?)", (table_name,))
        if cursor.fetchone()[0] is None:
            raise RuntimeError(f"IPAM current ND migration blocked: {table_name} is missing")

    _replace_source_check(
        cursor,
        "ipam_endpoint_collection_states",
        (
            "ck_ipam_endpoint_state_source",
            "ipam_endpoint_collection_states_observation_source_check",
        ),
        "ck_ipam_endpoint_state_source",
        ("arp", "fdb", "ndp"),
    )
    _replace_source_check(
        cursor,
        "ipam_current_endpoint_observations",
        (
            "ck_ipam_current_endpoint_observation_source",
            "ipam_current_endpoint_observations_observation_source_check",
        ),
        "ck_ipam_current_endpoint_observation_source",
        ("arp", "ndp"),
    )
    cursor.execute(
        """ALTER TABLE ipam_current_endpoint_observations
               DROP CONSTRAINT IF EXISTS ck_ipam_current_endpoint_ndp_ipv6"""
    )
    cursor.execute(
        """ALTER TABLE ipam_current_endpoint_observations
               DROP CONSTRAINT IF EXISTS ck_ipam_current_endpoint_address_family"""
    )
    cursor.execute(
        """ALTER TABLE ipam_current_endpoint_observations
               ADD CONSTRAINT ck_ipam_current_endpoint_address_family
               CHECK (
                   (observation_source = 'arp' AND family(ip_address) = 4)
                   OR (observation_source = 'ndp' AND family(ip_address) = 6)
               )"""
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep current NDP observations and widened source checks through rollback.
    return None
