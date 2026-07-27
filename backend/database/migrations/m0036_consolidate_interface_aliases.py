"""Consolidate interface rows that differ only by vendor presentation alias."""

from __future__ import annotations

from collections import defaultdict

from core.interface_utils import normalize_interface_name


VERSION = 36
NAME = "consolidate_interface_aliases"


def _table_exists(cursor, table: str, use_pg: bool) -> bool:
    if use_pg:
        row = cursor.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = ? LIMIT 1",
            (table,),
        ).fetchone()
    else:
        row = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table,),
        ).fetchone()
    return row is not None


def _row_dict(row: tuple, columns: list[str]) -> dict:
    return {column: row[index] for index, column in enumerate(columns)}


def _score(row: dict) -> tuple:
    status = str(row.get("oper_status") or "").lower()
    admin = str(row.get("admin_status") or "").lower()
    return (
        bool(str(row.get("primary_ip") or row.get("ip_address") or "").strip()),
        status not in {"", "unknown"},
        admin not in {"", "unknown"},
        bool(row.get("is_l3")),
        bool(str(row.get("last_seen") or "").strip()),
        -len(str(row.get("interface_name") or "")),
    )


def _merge_value(current, incoming, *, status: bool = False):
    if status and str(current or "").lower() in {"", "unknown"} and str(incoming or "").lower() not in {"", "unknown"}:
        return incoming
    if current is None or current == "":
        return incoming
    return current


def upgrade(cursor, use_pg: bool) -> None:
    if not _table_exists(cursor, "interfaces", use_pg):
        return

    columns = [
        "id", "device_id", "interface_name", "name_raw", "name_display",
        "description", "admin_status", "oper_status", "mac_address", "speed",
        "bandwidth", "mtu", "interface_type", "switchport_mode", "access_vlan",
        "native_vlan", "allowed_vlans", "primary_ip", "ip_address", "ip_prefix_length",
        "is_l3", "ip_enabled", "vrf_id", "parent_interface_id", "lag_id",
        "last_change", "last_seen",
    ]
    rows = cursor.execute(
        "SELECT " + ", ".join(columns) + " FROM interfaces ORDER BY device_id, id"
    ).fetchall()
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for raw_row in rows:
        row = _row_dict(raw_row, columns)
        normalized = normalize_interface_name(row.get("interface_name"))
        if normalized:
            grouped[(str(row.get("device_id") or ""), normalized.lower())].append(row)

    reference_tables = (
        ("ip_addresses", ("interface_id",)),
        ("topology_links", ("source_interface_id", "target_interface_id")),
        ("interface_status_history", ("interface_id",)),
        ("interface_statistics_history", ("interface_id",)),
        ("interface_optical_history", ("interface_id",)),
    )
    merge_columns = (
        "description", "mac_address", "speed", "bandwidth", "mtu", "interface_type",
        "switchport_mode", "access_vlan", "native_vlan", "allowed_vlans", "primary_ip",
        "ip_address", "ip_prefix_length", "is_l3", "ip_enabled", "vrf_id",
        "parent_interface_id", "lag_id", "last_change", "last_seen", "name_raw", "name_display",
    )

    for group in grouped.values():
        if len(group) < 2:
            continue
        survivor = max(group, key=_score)
        duplicate_rows = [row for row in group if row["id"] != survivor["id"]]

        merged = dict(survivor)
        for duplicate in duplicate_rows:
            for column in merge_columns:
                merged[column] = _merge_value(
                    merged.get(column),
                    duplicate.get(column),
                    status=column in {"interface_type", "switchport_mode"},
                )
            if bool(duplicate.get("is_l3")):
                merged["is_l3"] = duplicate.get("is_l3")
            if bool(duplicate.get("ip_enabled")):
                merged["ip_enabled"] = duplicate.get("ip_enabled")

        cursor.execute(
            "UPDATE interfaces SET " + ", ".join(f"{column} = ?" for column in merge_columns) + " WHERE id = ?",
            tuple(merged.get(column) for column in merge_columns) + (survivor["id"],),
        )

        for duplicate in duplicate_rows:
            duplicate_id = duplicate["id"]
            for table, ref_columns in reference_tables:
                if not _table_exists(cursor, table, use_pg):
                    continue
                for ref_column in ref_columns:
                    cursor.execute(
                        f"UPDATE {table} SET {ref_column} = ? WHERE {ref_column} = ?",
                        (survivor["id"], duplicate_id),
                    )
            cursor.execute("DELETE FROM interfaces WHERE id = ?", (duplicate_id,))

