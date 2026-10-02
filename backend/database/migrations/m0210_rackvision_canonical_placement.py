"""Evolve the rack model for the RackVision canonical placement contract.

The existing ``rack_devices`` table is retained and extended instead of
introducing a second placement table.  The migration is deliberately additive:
legacy text location fields remain available for the compatibility window and
ambiguous existing rows are reported rather than silently rewritten.
"""

from __future__ import annotations

import json
import logging
import uuid


VERSION = 210
NAME = "rackvision_canonical_placement"

logger = logging.getLogger(__name__)


def _columns(cursor, table_name: str, use_pg: bool) -> set[str]:
    # PostgreSQL is the release authority.  Keep the migration runner's
    # historical ``use_pg`` argument for call-site compatibility, but do not
    # retain a SQLite schema-introspection branch in a production migration.
    del use_pg
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table_name,),
    )
    return {str(row[0]) for row in cursor.fetchall()}


def _ensure_columns(cursor, table_name: str, definitions: dict[str, str], use_pg: bool) -> None:
    existing = _columns(cursor, table_name, use_pg)
    for column, definition in definitions.items():
        if column not in existing:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")


def _record_duplicate_asset_issues(cursor, *, json_type: str) -> bool:
    """Record duplicate installations and return whether any were found."""

    cursor.execute(
        """SELECT TRIM(asset_id) AS asset_id, COUNT(*) AS item_count
           FROM rack_devices
          WHERE asset_id IS NOT NULL AND TRIM(asset_id) <> ''
          GROUP BY TRIM(asset_id)
         HAVING COUNT(*) > 1"""
    )
    duplicate_groups = cursor.fetchall()
    for group in duplicate_groups:
        asset_id = str(group[0]).strip()
        cursor.execute(
            """SELECT id, rack_id, start_u, position
                 FROM rack_devices
                WHERE asset_id IS NOT NULL AND TRIM(asset_id) = ?
                ORDER BY id""",
            (asset_id,),
        )
        installations = [
            {
                "id": str(row[0]),
                "rack_id": str(row[1]),
                "start_u": row[2],
                "position": row[3],
            }
            for row in cursor.fetchall()
        ]
        issue_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"rackvision:duplicate-asset:{asset_id}"))
        details = json.dumps(
            {"asset_id": asset_id, "installations": installations},
            ensure_ascii=False,
            sort_keys=True,
        )
        details_sql = "CAST(? AS JSONB)" if json_type == "JSONB" else "?"
        cursor.execute(
            f"""INSERT INTO rack_data_quality_issues (
                    id, entity_type, entity_id, issue_code, severity,
                    details_json, status, detected_at
                ) VALUES (?, ?, ?, ?, ?, {details_sql}, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    details_json = excluded.details_json,
                    status = excluded.status,
                    detected_at = excluded.detected_at""",
            (
                issue_id,
                "physical_asset",
                asset_id,
                "DUPLICATE_ASSET_INSTALLATION",
                "error",
                details,
                "open",
            ),
        )
    return bool(duplicate_groups)


def upgrade(cursor, use_pg: bool) -> None:
    json_type = "JSONB" if use_pg else "TEXT"

    _ensure_columns(
        cursor,
        "racks",
        {
            "mount_policy": "TEXT NOT NULL DEFAULT 'front_rear'",
            "layout_revision": "INTEGER NOT NULL DEFAULT 1",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "rack_types",
        {
            "mount_policy": "TEXT NOT NULL DEFAULT 'front_rear'",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "device_types",
        {
            "depth_class": "TEXT NOT NULL DEFAULT 'unknown'",
            "width_mm": "INTEGER",
            "depth_mm": "INTEGER",
            "height_mm": "INTEGER",
            "weight_kg": "NUMERIC",
            "dimension_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "default_mount_kind": "TEXT NOT NULL DEFAULT 'u_mount'",
            "model_family": "TEXT NOT NULL DEFAULT ''",
            "catalog_key": "TEXT NOT NULL DEFAULT ''",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "physical_assets",
        {
            "rack_id": "TEXT",
            "rack_position": "TEXT",
            "rack_mount_kind": "TEXT",
            "rack_location_status": "TEXT NOT NULL DEFAULT 'unplaced'",
        },
        use_pg,
    )

    # ``start_u`` was NOT NULL in the legacy table.  PostgreSQL is the
    # production authority and must accept 0U/side-mounted/unknown rows.  A
    # fresh SQLite schema is created with the nullable form; deployed SQLite
    # compatibility databases keep the old constraint until their documented
    # rebuild path is used, rather than risking an implicit table rewrite.
    if use_pg:
        cursor.execute("ALTER TABLE rack_devices ALTER COLUMN start_u DROP NOT NULL")

    _ensure_columns(
        cursor,
        "rack_devices",
        {
            "mount_kind": "TEXT NOT NULL DEFAULT 'u_mount'",
            "height_u": "INTEGER",
            "placement_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "placement_source": "TEXT NOT NULL DEFAULT 'legacy_rack_device'",
            "dimension_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "location_note": "TEXT NOT NULL DEFAULT ''",
            "model_key": "TEXT NOT NULL DEFAULT ''",
        },
        use_pg,
    )

    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS rack_data_quality_issues (
            id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            issue_code TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'warning',
            details_json {json_type} NOT NULL DEFAULT '{{}}',
            status TEXT NOT NULL DEFAULT 'open',
            detected_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT,
            resolution_note TEXT NOT NULL DEFAULT ''
        )"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_rack_quality_entity "
        "ON rack_data_quality_issues(entity_type, entity_id, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_rack_quality_code_status "
        "ON rack_data_quality_issues(issue_code, status, detected_at)"
    )

    has_duplicate_assets = _record_duplicate_asset_issues(cursor, json_type=json_type)

    cursor.execute("CREATE INDEX IF NOT EXISTS ix_rack_devices_rack_position_u ON rack_devices(rack_id, position, start_u)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_rack_devices_asset_id ON rack_devices(asset_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_rack_devices_device_type_id ON rack_devices(device_type_id)")

    if not has_duplicate_assets:
        # The predicate keeps unlinked legacy rows (empty string) outside the
        # identity constraint while enforcing one installation per asset.
        try:
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_rack_devices_nonempty_asset "
                "ON rack_devices(asset_id) "
                "WHERE asset_id IS NOT NULL AND TRIM(asset_id) <> ''"
            )
        except Exception:
            # Keep the migration retryable on an installation whose legacy
            # rows changed between the report and index creation.  The issue
            # table remains the audit trail and a later run can create it.
            logger.warning("Unable to create rack_devices asset uniqueness index; retrying on next migration run", exc_info=True)
