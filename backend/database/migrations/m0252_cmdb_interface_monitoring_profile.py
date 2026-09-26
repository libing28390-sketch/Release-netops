"""Add CMDB-owned interface roles and utilization thresholds.

The profile is intentionally stored on the canonical ``interfaces`` row so
monitoring compilers can consume one deterministic configuration source per
interface.  This migration is PostgreSQL-only, matching the supported runtime
database and the current storage/monitoring control-plane migrations.
"""

from __future__ import annotations


VERSION = 252
NAME = "cmdb_interface_monitoring_profile"

_INTERFACE_ROLES = (
    "uplink",
    "wan",
    "transit",
    "server",
    "storage",
    "management",
    "access",
    "loopback",
    "other",
    "unclassified",
)


def _columns(cursor) -> set[str]:
    rows = cursor.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'interfaces'
        """
    ).fetchall()
    return {str(row[0]) for row in rows}


def _constraint_exists(cursor, name: str) -> bool:
    row = cursor.execute(
        """
        SELECT 1
          FROM pg_constraint
         WHERE conrelid = 'interfaces'::regclass
           AND conname = ?
        """,
        (name,),
    ).fetchone()
    return row is not None


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("CMDB interface monitoring profiles require PostgreSQL")

    columns = _columns(cursor)
    additions = {
        "interface_role": "TEXT NOT NULL DEFAULT 'unclassified'",
        "utilization_warn_pct": "NUMERIC(5,2) NOT NULL DEFAULT 60",
        "utilization_high_pct": "NUMERIC(5,2) NOT NULL DEFAULT 75",
        "utilization_critical_pct": "NUMERIC(5,2) NOT NULL DEFAULT 90",
    }
    for name, definition in additions.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE interfaces ADD COLUMN {name} {definition}")

    # A partially applied development database may have the columns without
    # the defaults/NOT NULL guarantees.  Repair only this migration's fields;
    # no existing interface identity or telemetry data is changed.
    role_placeholders = ", ".join("?" for _ in _INTERFACE_ROLES)
    cursor.execute(
        f"""
        UPDATE interfaces
           SET interface_role = 'unclassified'
         WHERE interface_role IS NULL
            OR BTRIM(interface_role) = ''
            OR interface_role NOT IN ({role_placeholders})
        """,
        tuple(_INTERFACE_ROLES),
    )
    cursor.execute(
        """
        UPDATE interfaces
           SET utilization_warn_pct = 60,
               utilization_high_pct = 75,
               utilization_critical_pct = 90
         WHERE utilization_warn_pct IS NULL
            OR utilization_high_pct IS NULL
            OR utilization_critical_pct IS NULL
            OR NOT (
                utilization_warn_pct >= 0
                AND utilization_warn_pct < utilization_high_pct
                AND utilization_high_pct < utilization_critical_pct
                AND utilization_critical_pct <= 100
            )
        """
    )
    cursor.execute(
        "ALTER TABLE interfaces ALTER COLUMN interface_role SET DEFAULT 'unclassified'"
    )
    cursor.execute(
        "ALTER TABLE interfaces ALTER COLUMN interface_role SET NOT NULL"
    )
    for column, default in (
        ("utilization_warn_pct", "60"),
        ("utilization_high_pct", "75"),
        ("utilization_critical_pct", "90"),
    ):
        cursor.execute(
            f"ALTER TABLE interfaces ALTER COLUMN {column} SET DEFAULT {default}"
        )
        cursor.execute(
            f"ALTER TABLE interfaces ALTER COLUMN {column} SET NOT NULL"
        )

    if not _constraint_exists(cursor, "interfaces_monitoring_role_chk"):
        cursor.execute(
            """
            ALTER TABLE interfaces
            ADD CONSTRAINT interfaces_monitoring_role_chk CHECK (
                interface_role IN (
                    'uplink', 'wan', 'transit', 'server', 'storage',
                    'management', 'access', 'loopback', 'other', 'unclassified'
                )
            )
            """
        )
    if not _constraint_exists(cursor, "interfaces_monitoring_utilization_order_chk"):
        cursor.execute(
            """
            ALTER TABLE interfaces
            ADD CONSTRAINT interfaces_monitoring_utilization_order_chk CHECK (
                utilization_warn_pct >= 0
                AND utilization_warn_pct < utilization_high_pct
                AND utilization_high_pct < utilization_critical_pct
                AND utilization_critical_pct <= 100
            )
            """
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # The migration runner has no destructive downgrade path.  Keeping the
    # profile columns preserves the CMDB contract for older application code.
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
