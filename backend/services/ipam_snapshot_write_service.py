"""Bulk reconciliation of complete current ARP/ND/FDB snapshots.

Caller must hold the collection-state row lock and own the transaction.
Every surviving row is refreshed to the new generation, even if its identity
is unchanged. Never invoke this for partial or unsuccessful collections.
"""
from __future__ import annotations

from typing import Any

_BATCH_SIZE = 500
_SCOPE_FIELDS = (
    "source_device_id", "observation_source", "context_source",
    "context_type", "local_context_key",
)
_COMMON_FIELDS = ("mac_address", "interface_name", "normalized_interface_name", "vlan_key")
_FRESH_FIELDS = ("generation", "observed_at", "run_id", "metadata_json")
_CASTS = {"ip_address": "?::inet", "metadata_json": "?::jsonb", "observed_at": "?::timestamptz"}


def reconcile_current_snapshot(
    conn, *, scope: tuple[str, str, str, str, str], generation: int,
    rows: list[dict[str, Any]],
) -> None:
    """Upsert the new generation in bounded batches, then delete absent rows.

    All statements and the caller's state update must commit atomically.
    No commits, independent transactions, or fallback deletes occur here.
    """
    if len(scope) != 5 or scope[1] not in {"arp", "ndp", "fdb"} or type(generation) is not int or generation < 1:
        raise ValueError("invalid_snapshot_scope_or_generation")
    is_fdb = scope[1] == "fdb"
    table = "ipam_current_fdb_observations" if is_fdb else "ipam_current_endpoint_observations"
    address = () if is_fdb else ("ip_address",)
    fields = _SCOPE_FIELDS + ("local_context_name",) + address + _COMMON_FIELDS + (
        ("entry_type",) if is_fdb else ()
    ) + _FRESH_FIELDS
    identity = _SCOPE_FIELDS + address + ("mac_address", "normalized_interface_name", "vlan_key")
    update_fields = tuple(field for field in fields if field not in identity)

    # Validate every row before issuing any statement, including across batches.
    seen = set()
    for row in rows:
        if tuple(row[field] for field in _SCOPE_FIELDS) != scope or row["generation"] != generation:
            raise ValueError("snapshot_scope_or_generation_mismatch")
        key = tuple(row[field] for field in identity)
        if key in seen:
            raise ValueError("duplicate_observation_identity")
        seen.add(key)
        if any(field not in row for field in fields):
            raise ValueError("snapshot_field_missing")

    placeholders = "(" + ", ".join(_CASTS.get(field, "?") for field in fields) + ")"
    prefix = f"INSERT INTO {table} ({', '.join(fields)}) VALUES "
    suffix = (f" ON CONFLICT ({', '.join(identity)}) DO UPDATE SET "
              + ", ".join(f"{field} = EXCLUDED.{field}" for field in update_fields))
    for start in range(0, len(rows), _BATCH_SIZE):
        batch = rows[start:start + _BATCH_SIZE]
        params = tuple(row[field] for row in batch for field in fields)
        conn.execute(prefix + ", ".join([placeholders] * len(batch)) + suffix, params)

    # With the state row locked, rows not refreshed to this generation are
    # absent from this complete snapshot. This also handles complete-empty.
    conn.execute(
        f"DELETE FROM {table} WHERE " + " AND ".join(f"{field} = ?" for field in _SCOPE_FIELDS)
        + " AND generation <> ?", (*scope, generation),
    )
