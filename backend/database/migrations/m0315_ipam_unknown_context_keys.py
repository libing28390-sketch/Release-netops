"""Retain raw device-local keys when routing-context type is unresolved."""

from __future__ import annotations


VERSION = 315
NAME = "ipam_unknown_context_keys"


_CONTEXT_KEY_CHECKS = {
    "cmdb_device_interface_address_observations": (
        "cmdb_interface_address_context_key_chk",
    ),
    "ipam_current_endpoint_observations": (
        "ck_ipam_current_endpoint_context_key",
    ),
    "ipam_endpoint_collection_states": (
        "ck_ipam_endpoint_state_context_key",
    ),
}


def _replace_context_key_check(cursor, table_name: str, constraint_name: str) -> None:
    cursor.execute(
        f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS {constraint_name}"
    )
    cursor.execute(
        f"""ALTER TABLE {table_name}
                ADD CONSTRAINT {constraint_name} CHECK (
                    (context_type = 'unknown')
                    OR (context_type IN ('vrf', 'global') AND btrim(local_context_key) <> '')
                )"""
    )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM routing-context keys require PostgreSQL")
    for table_name, (constraint_name,) in _CONTEXT_KEY_CHECKS.items():
        cursor.execute("SELECT to_regclass(?)", (table_name,))
        if cursor.fetchone()[0] is None:
            continue
        _replace_context_key_check(cursor, table_name, constraint_name)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Raw keys may already be needed to resolve current observations. Keep the
    # widened check through application rollback rather than discarding facts.
    return None
