"""Reconcile the legacy and canonical rack power capacity columns.

``racks.power_capacity_watts`` is the RackVision authority.  Older rows may
have a zero/default canonical value while ``power_capacity_w`` contains the
real capacity, so the migration first promotes that legacy value.  When both
columns contain different non-zero values, the canonical value wins and the
original discrepancy is preserved in ``rack_data_quality_issues`` for review.
"""

from __future__ import annotations

import json
import uuid


VERSION = 213
NAME = "rackvision_power_reconciliation"


def _as_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _issue_id(rack_id: str) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"rackvision:quality:rack:{rack_id}:POWER_FIELD_CONFLICT",
    ))


def upgrade(cursor, use_pg: bool) -> None:
    json_type = "JSONB" if use_pg else "TEXT"
    rows = cursor.execute(
        """SELECT id, power_capacity_w, power_capacity_watts
               FROM racks
              ORDER BY id"""
    ).fetchall()
    for row in rows:
        rack_id = str(row[0])
        legacy = _as_int(row[1])
        canonical = _as_int(row[2])
        conflict = (
            canonical not in (None, 0)
            and legacy not in (None, 0)
            and canonical != legacy
        )

        # A non-zero canonical value is authoritative.  Otherwise promote the
        # old value, including the common fresh-schema combination
        # (legacy=5000, watts=0).
        effective = canonical if canonical not in (None, 0) else (legacy if legacy is not None else 0)
        cursor.execute(
            """UPDATE racks
                  SET power_capacity_w = ?, power_capacity_watts = ?
                WHERE id = ?""",
            (effective, effective, rack_id),
        )

        if conflict:
            details = json.dumps(
                {
                    "rack_id": rack_id,
                    "power_capacity_watts": canonical,
                    "power_capacity_w": legacy,
                    "effective_value": effective,
                    "effective_source": "power_capacity_watts",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            details_sql = "CAST(? AS JSONB)" if use_pg else "?"
            cursor.execute(
                f"""INSERT INTO rack_data_quality_issues (
                            id, entity_type, entity_id, issue_code, severity,
                            details_json, status, detected_at
                        ) VALUES (?, 'rack', ?, 'POWER_FIELD_CONFLICT', 'error',
                                  {details_sql}, 'open', CURRENT_TIMESTAMP)
                        ON CONFLICT (id) DO UPDATE SET
                            severity = excluded.severity,
                            details_json = excluded.details_json,
                            detected_at = excluded.detected_at""",
                (_issue_id(rack_id), rack_id, details),
            )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # The canonical value is intentionally retained.  Reconstructing the old
    # divergence would destroy the evidence this migration recorded.
    return None

